"""YouTube video downloader with retry logic."""

import json
import logging
import re
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, cast

import yt_dlp
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config.settings import Config
from ..exceptions import DownloadError
from ..output import emit_formatter_message, emit_rendered
from .utils import (
    build_output_filename,
    extract_video_id,
    is_short,
)
from .utils import (
    suppress_output as shared_suppress_output,
)

# Backward-compatible export for existing imports/tests.
suppress_output = shared_suppress_output

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    logger = logging.getLogger(__name__)
stdlib_logger = logging.getLogger(__name__)

# Completely suppress yt-dlp's own logger to prevent unwanted output
yt_dlp_logger = logging.getLogger("yt_dlp")
yt_dlp_logger.setLevel(logging.CRITICAL)
yt_dlp_logger.addHandler(logging.NullHandler())

# Also suppress any child loggers
for logger_name in [
    "yt_dlp",
    "yt_dlp.extractor",
    "yt_dlp.downloader",
    "yt_dlp.postprocessor",
]:
    child_logger = logging.getLogger(logger_name)
    child_logger.setLevel(logging.CRITICAL)
    child_logger.addHandler(logging.NullHandler())


class SilentYTDLPLogger:
    """No-op logger for yt-dlp to keep CLI output formatter-controlled."""

    def debug(self, msg: str) -> None:
        _ = msg

    def info(self, msg: str) -> None:
        _ = msg

    def warning(self, msg: str) -> None:
        _ = msg

    def error(self, msg: str) -> None:
        _ = msg


class ProgressCallback:
    """Progress callback for yt-dlp with formatter integration."""

    THUMBNAIL_EXTENSIONS: ClassVar[set[str]] = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
    }
    INTERMEDIATE_MEDIA_EXTENSIONS: ClassVar[set[str]] = {
        ".webm",
        ".m4a",
        ".mp4",
        ".mkv",
        ".mov",
        ".ts",
    }
    PRIMARY_VIDEO_EXTENSIONS: ClassVar[set[str]] = {
        ".mp4",
        ".mkv",
        ".webm",
        ".mov",
        ".m4v",
        ".avi",
        ".flv",
        ".ts",
        ".m2ts",
        ".mpg",
        ".mpeg",
        ".wmv",
        ".m4a",
        ".mp3",
        ".aac",
        ".opus",
        ".wav",
        ".flac",
    }
    SUBTITLE_EXTENSIONS: ClassVar[set[str]] = {
        ".srt",
        ".vtt",
        ".ass",
        ".ssa",
        ".ttml",
        ".srv1",
        ".srv2",
        ".srv3",
    }

    def __init__(self, formatter):
        self.formatter = formatter
        self.current_video = None
        self._primary_emitted_for_current = False
        self._emitted_artifact_exts: set[str] = set()

    @staticmethod
    def _normalize_extension(extension: str) -> str:
        """Normalize extension to .ext lowercase format."""
        ext = extension.strip().lower()
        if not ext:
            return ""
        if not ext.startswith("."):
            return f".{ext}"
        return ext

    def _extract_extension(self, d: dict[str, Any]) -> str:
        """Extract extension from callback payload."""
        filename = str(d.get("filename") or "").strip()
        if filename:
            suffix = Path(filename).suffix
            if suffix:
                return self._normalize_extension(suffix)

        info_ext = str(d.get("info_dict", {}).get("ext") or "").strip()
        return self._normalize_extension(info_ext)

    @staticmethod
    def _format_size(total_bytes: int) -> str:
        """Format bytes to mb/gb with requested precision rules."""
        if total_bytes <= 0:
            return ""

        gib = 1024**3
        mib = 1024**2

        if total_bytes >= gib:
            gb_value = total_bytes / gib
            formatted = f"{gb_value:.2f}".rstrip("0").rstrip(".")
            return f"{formatted}gb"

        mb_value = max(1, round(total_bytes / mib))
        return f"{int(mb_value)}mb"

    @staticmethod
    def _parse_size_text(size_text: str) -> int | None:
        """Parse yt-dlp size strings like 100MiB/1.25GiB to bytes."""
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([KMGTP]?)i?B", size_text, re.I)
        if not match:
            return None

        value = float(match.group(1))
        prefix = match.group(2).upper()
        power = {"": 0, "K": 1, "M": 2, "G": 3, "T": 4, "P": 5}.get(prefix)
        if power is None:
            return None

        return int(value * (1024**power))

    def _extract_size(self, d: dict[str, Any]) -> str:
        """Extract and normalize size text from callback payload."""
        for key in ("total_bytes", "total_bytes_estimate", "downloaded_bytes"):
            raw_value = d.get(key)
            if isinstance(raw_value, (int, float)) and raw_value > 0:
                return self._format_size(int(raw_value))

        size_text = str(
            d.get("total_bytes_str") or d.get("_total_bytes_str") or ""
        ).strip()
        if not size_text:
            return ""

        parsed_bytes = self._parse_size_text(size_text)
        if parsed_bytes is None:
            return ""
        return self._format_size(parsed_bytes)

    @staticmethod
    def _extract_resolution(d: dict[str, Any]) -> str:
        """Extract display resolution from callback payload."""
        info = d.get("info_dict", {})
        height = info.get("height")
        width = info.get("width")
        if height and width:
            return f"{height}p"
        return ""

    def _reset_current_video_state(self, title: str) -> None:
        """Reset per-video completion tracking."""
        self.current_video = title
        self._primary_emitted_for_current = False
        self._emitted_artifact_exts = set()

    def _artifact_type_for_extension(self, extension: str) -> str:
        """Map known extension types to readable artifact labels."""
        if extension in self.THUMBNAIL_EXTENSIONS:
            return "thumbnail"
        return ""

    def _extract_subtitle_language(self, d: dict[str, Any]) -> str:
        """Extract subtitle language identifier for deduplication."""
        info = d.get("info_dict", {})
        for key in ("lang", "language", "subtitle_lang"):
            value = str(info.get(key) or "").strip()
            if value:
                return value.lower()

        filename = str(d.get("filename") or "").strip()
        if not filename:
            return ""

        stem = Path(filename).stem
        parts = stem.split(".")
        if len(parts) < 2:
            return ""

        candidate = parts[-1].strip().lower()
        if candidate and candidate != "na":
            return candidate
        return ""

    def __call__(self, d: dict[str, Any]) -> None:
        """Handle yt-dlp progress callback."""
        if d["status"] == "downloading" and self.formatter:
            title = d.get("info_dict", {}).get("title") or self.current_video or "Unknown"
            if self.current_video != title and title != "Unknown":
                self._reset_current_video_state(title)
                # Start new progress bar
                if hasattr(self.formatter, "start_video_progress"):
                    self.formatter.start_video_progress(title)
                else:
                    # Fallback to old behavior
                    start_msg = f"🔵 Starting download: {title}"
                    emit_rendered(start_msg)

            # Update progress bar
            if hasattr(self.formatter, "update_video_progress"):
                self.formatter.update_video_progress(
                    {
                        "percent": d.get("_percent_str", "0%"),
                        "speed": d.get("_speed_str", ""),
                        "eta": d.get("_eta_str", ""),
                    }
                )
            else:
                # Fallback to old behavior
                progress_msg = self.formatter.video_progress(
                    self.current_video,
                    {
                        "percent": d.get("_percent_str", "0%"),
                        "speed": d.get("_speed_str", ""),
                        "eta": d.get("_eta_str", ""),
                    },
                )
                if progress_msg:
                    emit_rendered(progress_msg)

        elif d["status"] == "finished" and self.formatter:
            title = (
                d.get("info_dict", {}).get("title") or self.current_video or "Unknown"
            )
            if self.current_video != title and title != "Unknown":
                self._reset_current_video_state(title)

            if hasattr(self.formatter, "close_video_progress"):
                self.formatter.close_video_progress()

            extension = self._extract_extension(d)
            resolution = self._extract_resolution(d)
            size = self._extract_size(d)
            primary_ext = self._normalize_extension(
                str(d.get("info_dict", {}).get("ext") or "")
            )

            candidate_primary = primary_ext or extension
            is_primary = (
                not self._primary_emitted_for_current
                and candidate_primary in self.PRIMARY_VIDEO_EXTENSIONS
                and extension in self.PRIMARY_VIDEO_EXTENSIONS
            )

            if is_primary:
                complete_msg = self.formatter.video_complete(
                    title, resolution, extension, size
                )
                emit_rendered(complete_msg)
                self._primary_emitted_for_current = True
            elif (
                extension
                and extension in self.SUBTITLE_EXTENSIONS
                and extension not in self.INTERMEDIATE_MEDIA_EXTENSIONS
                and extension not in self.THUMBNAIL_EXTENSIONS
            ):
                # Subtitle reporting is emitted from deterministic filesystem scans
                # after download completion to avoid missing/duplicate/unknown lines.
                return


class YouTubeDownloader:
    """YouTube video downloader with retry logic and configuration."""

    def __init__(self, config: Config, formatter=None):
        self.config = config
        self.formatter = formatter
        self.ydl_opts = self._build_ydl_options()
        self._emitted_subtitle_paths: set[str] = set()

    def _verbose_enabled(self) -> bool:
        """Return True when runtime is configured for verbose diagnostics."""
        return str(self.config.get("logging.level", "INFO")).upper() == "DEBUG"

    def _emit_verbose_debug(self, message: str, **extra: Any) -> None:
        """Emit debug diagnostics only in verbose mode."""
        if not self._verbose_enabled():
            return
        emit_formatter_message(self.formatter, "debug", message)
        if extra:
            logger.debug(message, extra=extra)
        else:
            logger.debug(message)

    @staticmethod
    def _runtime_option_snapshot(opts: dict[str, Any]) -> dict[str, Any]:
        """Build a sanitized option snapshot for diagnostic output."""
        return {
            "cookiefile": bool(opts.get("cookiefile")),
            "format": opts.get("format"),
            "format_sort": opts.get("format_sort"),
            "socket_timeout": opts.get("socket_timeout"),
            "connect_timeout": opts.get("connect_timeout"),
            "writeinfojson": opts.get("writeinfojson"),
            "writesubtitles": opts.get("writesubtitles"),
            "subtitlesformat": opts.get("subtitlesformat"),
            "convertsubtitles": opts.get("convertsubtitles"),
            "embedsubtitles": opts.get("embedsubtitles"),
            "remux_video": opts.get("remux_video"),
            "writethumbnail": opts.get("writethumbnail"),
            "postprocessors_count": len(opts.get("postprocessors", [])),
        }

    def _effective_download_setting(
        self,
        key: str,
        playlist_config: dict[str, Any] | None = None,
        default: Any = None,
    ) -> Any:
        """Resolve playlist override, then global config, then default."""
        if playlist_config and key in playlist_config:
            return playlist_config[key]
        value = self.config.get(f"download.{key}")
        if value is not None:
            return value
        return default

    def _resolve_download_strategy_overrides(
        self,
        metadata: dict[str, Any] | None,
        playlist_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve effective format/remux strategy for container policy."""
        policy = str(
            self._effective_download_setting(
                "container_policy",
                playlist_config,
                default="no_webm_prefer_mp4",
            )
        ).strip()
        if policy not in {"no_webm_prefer_mp4", "force_mp4", "prefer_source"}:
            policy = "no_webm_prefer_mp4"

        max_height = 0
        has_mp4_at_max = False
        formats = metadata.get("formats") if isinstance(metadata, dict) else None
        if isinstance(formats, list):
            video_formats: list[dict[str, Any]] = []
            for item in formats:
                if not isinstance(item, dict):
                    continue
                vcodec = str(item.get("vcodec") or "").strip().lower()
                if not vcodec or vcodec == "none":
                    continue
                try:
                    height = int(item.get("height") or 0)
                except (TypeError, ValueError):
                    height = 0
                if height <= 0:
                    continue
                video_formats.append(item)

            if video_formats:
                heights: list[int] = []
                for item in video_formats:
                    try:
                        height = int(item.get("height") or 0)
                    except (TypeError, ValueError):
                        height = 0
                    if height > 0:
                        heights.append(height)
                max_height = max(heights) if heights else 0
                def _height(value: Any) -> int:
                    try:
                        return int(value or 0)
                    except (TypeError, ValueError):
                        return 0

                has_mp4_at_max = any(
                    _height(item.get("height")) == max_height
                    and str(item.get("ext") or "").lower() == "mp4"
                    for item in video_formats
                )

        overrides: dict[str, Any] = {}
        if policy == "force_mp4":
            if max_height > 0:
                overrides["format"] = (
                    f"bestvideo[height={max_height}][ext=mp4]+bestaudio[ext=m4a]/"
                    f"best[height={max_height}][ext=mp4]/"
                    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
                )
            else:
                overrides["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
            overrides["remux_video"] = "mp4"
            self._emit_verbose_debug(
                "Format selection strategy resolved",
                policy=policy,
                max_height=max_height,
                has_mp4_at_max=has_mp4_at_max,
                format=overrides["format"],
                remux_video=overrides["remux_video"],
            )
            return overrides

        if max_height > 0:
            if policy == "no_webm_prefer_mp4" and has_mp4_at_max:
                overrides["format"] = (
                    f"bestvideo[height={max_height}][ext=mp4]+bestaudio/"
                    f"best[height={max_height}][ext=mp4]/"
                    f"bestvideo[height={max_height}][ext=mp4]/"
                    f"best[height={max_height}]"
                )
            else:
                overrides["format"] = (
                    f"bestvideo[height={max_height}]+bestaudio/"
                    f"best[height={max_height}]/bestvideo+bestaudio/best"
                )

        if policy == "no_webm_prefer_mp4":
            overrides["remux_video"] = "mp4/mkv"

        self._emit_verbose_debug(
            "Format selection strategy resolved",
            policy=policy,
            max_height=max_height,
            has_mp4_at_max=has_mp4_at_max,
            format=overrides.get("format"),
            remux_video=overrides.get("remux_video"),
        )
        return overrides

    @staticmethod
    def _normalize_extension(extension: str) -> str:
        """Normalize extension to .ext format."""
        ext = extension.strip().lower()
        if not ext:
            return ""
        if not ext.startswith("."):
            return f".{ext}"
        return ext

    @staticmethod
    def _subtitle_base_name(path: Path) -> str:
        """Return subtitle base name without lang/extension suffix."""
        parts = path.name.split(".")
        if len(parts) >= 3:
            return ".".join(parts[:-2])
        if len(parts) == 2:
            return parts[0]
        return path.stem

    @classmethod
    def _subtitle_status_for_file(
        cls,
        subtitle_path: Path,
        all_subtitles: list[Path],
        requested_subtitles: dict[str, Any] | None = None,
    ) -> str:
        """Build subtitle status text for formatter output."""
        ext = cls._normalize_extension(subtitle_path.suffix)
        if ext == ".srt":
            base = cls._subtitle_base_name(subtitle_path)
            source_exts = {
                cls._normalize_extension(candidate.suffix)
                for candidate in all_subtitles
                if cls._subtitle_base_name(candidate) == base
            }
            if ".vtt" in source_exts:
                return ".vtt -> .srt"

            # When source sidecar was cleaned up/replaced, infer conversion source
            # from requested_subtitles metadata if available.
            if requested_subtitles:
                lang = subtitle_path.stem.split(".")[-1].lower()
                sub_info = requested_subtitles.get(lang)
                if isinstance(sub_info, dict):
                    source_ext = cls._normalize_extension(str(sub_info.get("ext") or ""))
                    if source_ext and source_ext != ".srt":
                        return f"{source_ext} -> .srt"
            return ".srt"
        if ext:
            return ext
        return "subtitles"

    @staticmethod
    def _collect_existing_subtitles(
        output_directory: Path, filename: str
    ) -> tuple[list[Path], list[Path]]:
        """Collect preferred subtitle files and all subtitle candidates."""
        candidates: list[Path] = []
        for path in sorted(output_directory.glob(f"{filename}.*")):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in ProgressCallback.SUBTITLE_EXTENSIONS:
                candidates.append(path)

        # Prefer final .srt when both source and converted subtitle exist.
        preferred_by_key: dict[str, Path] = {}
        for candidate in candidates:
            key = YouTubeDownloader._subtitle_base_name(candidate)
            existing = preferred_by_key.get(key)
            if existing is None:
                preferred_by_key[key] = candidate
                continue

            candidate_ext = YouTubeDownloader._normalize_extension(candidate.suffix)
            existing_ext = YouTubeDownloader._normalize_extension(existing.suffix)
            if candidate_ext == ".srt" and existing_ext != ".srt":
                preferred_by_key[key] = candidate

        preferred = sorted(preferred_by_key.values(), key=lambda p: p.name)
        return preferred, candidates

    def _emit_subtitle_pipeline_debug(self, opts: dict[str, Any]) -> None:
        """Emit subtitle pipeline diagnostics in verbose mode."""
        if not opts.get("writesubtitles"):
            return
        languages = opts.get("subtitleslangs") or []
        self._emit_verbose_debug(
            "Subtitle pipeline active",
            writesubtitles=bool(opts.get("writesubtitles")),
            subtitlesformat=opts.get("subtitlesformat"),
            convertsubtitles=opts.get("convertsubtitles"),
            embedsubtitles=bool(opts.get("embedsubtitles")),
            subtitleslangs=list(languages) if isinstance(languages, list) else languages,
        )

    @staticmethod
    def _format_size_from_bytes(total_bytes: int) -> str:
        """Format bytes to mb/gb with requested precision rules."""
        if total_bytes <= 0:
            return ""

        gib = 1024**3
        mib = 1024**2

        if total_bytes >= gib:
            gb_value = total_bytes / gib
            formatted = f"{gb_value:.2f}".rstrip("0").rstrip(".")
            return f"{formatted}gb"

        mb_value = max(1, round(total_bytes / mib))
        return f"{int(mb_value)}mb"

    @staticmethod
    def _extract_resolution_from_metadata(metadata: dict[str, Any] | None) -> str:
        """Extract display resolution from metadata."""
        if not metadata:
            return ""
        height = metadata.get("height")
        width = metadata.get("width")
        if height and width:
            return f"{height}p"
        return ""

    @staticmethod
    def _extract_title(
        download_result: dict[str, Any] | None, metadata: dict[str, Any] | None
    ) -> str:
        """Extract best available title."""
        if download_result and download_result.get("title"):
            return str(download_result["title"])
        if metadata and metadata.get("title"):
            return str(metadata["title"])
        return "Unknown"

    @staticmethod
    def _first_existing_thumbnail(
        output_directory: Path, filename: str
    ) -> tuple[Path, str] | None:
        """Find the first thumbnail file generated for a video."""
        thumbnail_extensions = (".jpg", ".jpeg", ".png", ".webp", ".gif")
        for extension in thumbnail_extensions:
            candidate = output_directory / f"{filename}{extension}"
            if candidate.exists():
                return candidate, extension
        return None

    @staticmethod
    def _iter_existing_result_filepaths(
        download_result: dict[str, Any] | None,
    ) -> list[Path]:
        """Extract existing local file paths from yt-dlp result payload."""
        if not isinstance(download_result, dict):
            return []

        paths: list[Path] = []
        requested_downloads = download_result.get("requested_downloads")
        if isinstance(requested_downloads, list):
            for entry in requested_downloads:
                if not isinstance(entry, dict):
                    continue
                filepath = entry.get("filepath")
                if isinstance(filepath, str) and filepath.strip():
                    path_obj = Path(filepath)
                    if path_obj.exists() and path_obj.is_file():
                        paths.append(path_obj)

        fallback_filename = download_result.get("_filename")
        if isinstance(fallback_filename, str) and fallback_filename.strip():
            path_obj = Path(fallback_filename)
            if path_obj.exists() and path_obj.is_file():
                paths.append(path_obj)

        return paths

    @classmethod
    def _resolve_final_media_path(
        cls,
        output_directory: Path,
        filename: str,
        download_result: dict[str, Any] | None,
    ) -> Path | None:
        """Resolve the final primary media file path."""
        existing_result_paths = cls._iter_existing_result_filepaths(download_result)
        if existing_result_paths:
            preferred_exts = (".mp4", ".mkv")
            for extension in preferred_exts:
                for path in existing_result_paths:
                    if cls._normalize_extension(path.suffix) == extension:
                        return path
            return existing_result_paths[0]

        for extension in (".mp4", ".mkv"):
            candidate = output_directory / f"{filename}{extension}"
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    @classmethod
    def _resolve_output_base_path(
        cls,
        output_directory: Path,
        filename: str,
        download_result: dict[str, Any] | None,
    ) -> Path:
        """Resolve base path used for sidecar outputs."""
        media_path = cls._resolve_final_media_path(output_directory, filename, download_result)
        if media_path is not None:
            return media_path.with_suffix("")
        return output_directory / filename

    def _emit_post_download_generated_lines(
        self,
        output_directory: Path,
        filename: str,
        download_result: dict[str, Any] | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        """Emit generated artifact lines based on actual files on disk."""
        if not self.formatter:
            return

        title = self._extract_title(download_result, metadata)
        resolution = self._extract_resolution_from_metadata(download_result or metadata)

        thumbnail = self._first_existing_thumbnail(output_directory, filename)
        if thumbnail is not None:
            _, thumbnail_ext = thumbnail
            emit_rendered(self.formatter.thumbnail_generated(title, thumbnail_ext))

        media_path = self._resolve_final_media_path(output_directory, filename, download_result)
        if media_path is not None:
            media_size = self._format_size_from_bytes(media_path.stat().st_size)
            emit_rendered(
                self.formatter.container_generated(
                    title, media_path.suffix, resolution, media_size
                )
            )

        subtitle_files, subtitle_candidates = self._collect_existing_subtitles(
            output_directory, filename
        )
        requested_subtitles: dict[str, Any] | None = None
        if isinstance(download_result, dict):
            raw_requested = download_result.get("requested_subtitles")
            if isinstance(raw_requested, dict):
                requested_subtitles = raw_requested
        for subtitle_path in subtitle_files:
            subtitle_key = str(subtitle_path.resolve())
            if subtitle_key in self._emitted_subtitle_paths:
                continue
            status = self._subtitle_status_for_file(
                subtitle_path, subtitle_candidates, requested_subtitles
            )
            emit_rendered(self.formatter.subtitle_downloaded(title, status))
            self._emitted_subtitle_paths.add(subtitle_key)

    def _write_max_metadata_sidecar(
        self,
        *,
        base_path: Path,
        video_url: str,
        download_result: dict[str, Any] | None,
    ) -> None:
        """Write full metadata sidecar as project-owned JSON payload."""
        if not isinstance(download_result, dict) or not download_result:
            return

        metadata_path = base_path.with_suffix(".metadata.json")
        tmp_path = metadata_path.with_suffix(".metadata.json.tmp")
        self._emit_verbose_debug(
            "Writing metadata sidecar",
            metadata_path=str(metadata_path),
            video_url=video_url,
        )
        try:
            sanitized_info = yt_dlp.YoutubeDL.sanitize_info(deepcopy(download_result))
            payload = {
                "video_url": video_url,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "extractor": str(download_result.get("extractor") or ""),
                "metadata": sanitized_info,
            }
            tmp_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            tmp_path.replace(metadata_path)
            self._emit_verbose_debug(
                "Metadata sidecar written",
                metadata_path=str(metadata_path),
                video_url=video_url,
            )
        except (OSError, TypeError, ValueError) as e:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            self._emit_verbose_debug(
                f"Failed to write metadata sidecar ({type(e).__name__}: {e!s})",
                metadata_path=str(metadata_path),
                video_url=video_url,
            )
            logger.warning(
                "Failed to write metadata sidecar",
                extra={"metadata_path": str(metadata_path), "error": str(e)},
            )

    def _build_ydl_options(
        self, playlist_config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Build yt-dlp options from configuration with playlist-specific overrides."""
        # Use empty dict if no playlist config provided
        if playlist_config is None:
            playlist_config = {}

        def first_defined(*keys: str) -> Any:
            for key in keys:
                value = playlist_config.get(key)
                if value is not None:
                    return value
            for key in keys:
                value = self.config.get(f"download.{key}")
                if value is not None:
                    return value
            return None

        # Start with global defaults
        opts = {
            "format": first_defined("format"),
            "format_sort": first_defined("format_sort"),
            "merge_output_format": first_defined("merge_output_format"),
            "http_headers": {
                "User-Agent": self.config.get("http.user_agent"),
            },
            "socket_timeout": first_defined("socket_timeout")
            or self.config.get("http.request_timeout"),
            "connect_timeout": first_defined("connect_timeout")
            or self.config.get("http.connect_timeout"),
        }
        
        # Handle boolean options separately to preserve False values
        write_subtitles = first_defined("write_subtitles", "writesubtitles")
        if write_subtitles is not None:
            opts["writesubtitles"] = write_subtitles

        embed_subtitles = first_defined("embed_subtitles", "embedsubtitles")
        if embed_subtitles is not None:
            opts["embedsubtitles"] = embed_subtitles
            
        write_thumbnail = first_defined("write_thumbnail", "writethumbnail")
        if write_thumbnail is not None:
            opts["writethumbnail"] = write_thumbnail

        write_info_json = first_defined("write_info_json", "writeinfojson")
        if write_info_json is not None:
            opts["writeinfojson"] = write_info_json

        remux_video = first_defined("remux_video")
        if remux_video is not None:
            opts["remux_video"] = remux_video

        # Subtitle format options
        subtitle_format = first_defined("subtitle_format", "subtitlesformat")
        if subtitle_format is not None:
            opts["subtitlesformat"] = subtitle_format
            
        convert_subtitles = first_defined("convert_subtitles", "convertsubtitles")
        if convert_subtitles is not None:
            opts["convertsubtitles"] = convert_subtitles
            
        subtitle_languages = first_defined("subtitle_languages", "subtitleslangs")
        if subtitle_languages is not None:
            opts["subtitleslangs"] = subtitle_languages

        # Build postprocessors list
        postprocessors = []
        container_policy = str(first_defined("container_policy") or "").strip()

        # Keep explicit subtitle conversion/embed processors when enabled.
        if opts.get("writesubtitles") and opts.get("convertsubtitles"):
            postprocessors.append(
                {
                    "key": "FFmpegSubtitlesConvertor",
                    "format": str(opts["convertsubtitles"]).lstrip("."),
                }
            )

        if opts.get("writesubtitles") and opts.get("embedsubtitles"):
            postprocessors.append(
                {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": True}
            )

        # Add recode video postprocessor if enabled
        recode_video = first_defined("recode_video")
        merge_output_format = first_defined("merge_output_format")
        if recode_video and merge_output_format:
            postprocessors.append({
                "key": "FFmpegVideoConvertor",
                "preferedformat": merge_output_format,
            })
        elif opts.get("remux_video"):
            postprocessors.append(
                {
                    "key": "FFmpegVideoRemuxer",
                    "preferedformat": str(opts["remux_video"]),
                }
            )
        elif container_policy == "no_webm_prefer_mp4":
            postprocessors.append(
                {
                    "key": "FFmpegVideoRemuxer",
                    "preferedformat": "mp4/mkv",
                }
            )

        # Add thumbnail converter postprocessor
        thumbnail_format = first_defined("thumbnail_format")
        if thumbnail_format:
            postprocessors.append({
                "key": "FFmpegThumbnailsConvertor",
                "format": thumbnail_format,
            })

        opts["postprocessors"] = postprocessors

        return {k: v for k, v in opts.items() if v is not None}

    def _build_runtime_ydl_options(
        self,
        playlist_config: dict[str, Any] | None = None,
        *,
        include_progress_hooks: bool = False,
    ) -> dict[str, Any]:
        """Build effective yt-dlp options used at runtime."""
        opts = self._build_ydl_options(playlist_config)
        
        # Convert format_sort from comma-separated string to list for Python API
        format_sort = opts.get("format_sort")
        if format_sort and isinstance(format_sort, str):
            opts["format_sort"] = [s.strip() for s in format_sort.split(",")]

        opts.update(
            {
                "quiet": True,
                "no_warnings": True,
                "logger": SilentYTDLPLogger(),
                "progress": False,
                "extract_flat": False,
                "print_json": False,
                "simulate": False,
                "noplaylist": False,
                "extractaudio": False,
                "extractvideo": False,
                "no_color": True,
                "progress_with_newline": False,
                "xattr_set_filesize": False,
                "skip_unavailable_fragments": True,
                "ignoreerrors": True,
                "no_check_certificates": True,
                "socket_timeout": 60,
                "retries": 3,
                "fragment_retries": 3,
                "extractor_retries": 3,
                "file_access_retries": 3,
                "no_call_home": True,
                "no_update_check": True,
                "download_archive": None,
                "user_agent": None,
            }
        )

        if include_progress_hooks and self.formatter:
            opts["progress_hooks"] = [ProgressCallback(self.formatter)]
        else:
            opts["progress_hooks"] = []

        cookie_path = self.config.get_cookie_file_path()
        if cookie_path:
            opts["cookiefile"] = str(cookie_path)

        return {k: v for k, v in opts.items() if v is not None}

    def _extract_video_id(self, video_url: str) -> str:
        """Extract a stable video id from common YouTube URL formats."""
        return extract_video_id(video_url, None)

    def _build_output_filename(
        self, metadata: dict[str, Any] | None, video_url: str
    ) -> str:
        """Build a deterministic output filename."""
        return build_output_filename(self.config, metadata, video_url)

    def _download_with_opts(
        self, video_url: str, opts: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute yt-dlp with prepared options."""
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(video_url, download=True)
        except yt_dlp.DownloadError as e:
            logger.exception(
                "Download failed",
                extra={"video_url": video_url, "error": str(e)},
            )
            raise DownloadError(f"Failed to download {video_url}: {e}") from e
        except Exception as e:
            emit_formatter_message(
                self.formatter, "error", f"Unexpected error downloading video - {e!s}"
            )
            logger.exception(
                "Unexpected error during download",
                extra={"video_url": video_url, "error": str(e)},
            )
            raise DownloadError(f"Unexpected error downloading {video_url}: {e}") from e

    def _download_with_effective_config(
        self,
        video_url: str,
        output_template: str,
        output_directory: Path,
        filename: str,
        playlist_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Download using either global settings or playlist-specific settings."""
        if playlist_config:
            return self.download_video_with_config_impl(
                video_url, output_template, output_directory, filename, playlist_config
            )
        return self.download_video(
            video_url, output_template, output_directory, filename
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((DownloadError, yt_dlp.DownloadError)),
        before_sleep=before_sleep_log(cast(Any, stdlib_logger), logging.WARNING),
        reraise=True,
    )
    def download_video(
        self,
        video_url: str,
        output_template: str,
        output_directory: Path,
        filename: str,
    ) -> dict[str, Any]:
        """Download video with retry logic."""
        opts = self._build_runtime_ydl_options(include_progress_hooks=True)
        self._emit_subtitle_pipeline_debug(opts)
        opts["outtmpl"] = {
            "default": output_template,
            "subtitle": str(output_directory / f"{filename}.%(lang)s.%(ext)s"),
            "thumbnail": str(output_directory / f"{filename}.%(ext)s"),
        }
        return self._download_with_opts(video_url, opts)

    def get_metadata(self, video_url: str) -> dict[str, Any] | None:
        """Get video metadata without downloading."""
        opts = self._build_runtime_ydl_options(include_progress_hooks=False)

        # Keep explicit failure signals for metadata prefetch fallback handling.
        opts["ignoreerrors"] = False
        runtime_snapshot = self._runtime_option_snapshot(opts)
        self._emit_verbose_debug(
            f"Metadata prefetch started: {video_url}",
            video_url=video_url,
            runtime_opts=runtime_snapshot,
        )

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=False)
                if info_dict is None:
                    self._emit_verbose_debug(
                        "Metadata prefetch returned no data",
                        video_url=video_url,
                        runtime_opts=runtime_snapshot,
                    )
                    return None
                self._emit_verbose_debug(
                    f"Metadata prefetch succeeded: {info_dict.get('title', 'Unknown')}",
                    video_url=video_url,
                    title=info_dict.get("title"),
                )
                return info_dict
        except Exception as e:
            self._emit_verbose_debug(
                f"Metadata prefetch failed; falling back to direct download ({type(e).__name__}: {e!s})",
                video_url=video_url,
                error=str(e),
            )
            return None

    def download_video_with_config(
        self,
        video_url: str,
        output_directory: Path,
        playlist_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Download video and handle directory structure based on metadata."""
        self._emitted_subtitle_paths = set()
        effective_playlist_config = dict(playlist_config or {})
        metadata = self.get_metadata(video_url)
        if metadata is None:
            self._emit_verbose_debug(
                "Metadata prefetch failed. Falling back to direct download.",
                video_url=video_url,
            )
        else:
            strategy_overrides = self._resolve_download_strategy_overrides(
                metadata, effective_playlist_config
            )
            effective_playlist_config.update(strategy_overrides)

        filename = self._build_output_filename(metadata, video_url)

        # Check if video is a YouTube Short
        if metadata and self.config.get("shorts.detect_shorts", True):
            threshold = self.config.get("shorts.aspect_ratio_threshold", 0.7)
            if is_short(metadata, threshold):
                shorts_dir = output_directory / self.config.get(
                    "shorts.shorts_subdirectory", "YouTube Shorts"
                )
                shorts_dir.mkdir(parents=True, exist_ok=True)
                output_directory = shorts_dir

        output_directory.mkdir(parents=True, exist_ok=True)
        output_template = str(output_directory / f"{filename}.%(ext)s")

        # Add delay between videos
        delay = self.config.get("archive.delay_between_videos", 10)
        if delay > 0:
            time.sleep(delay)

        download_result = self._download_with_effective_config(
            video_url,
            output_template,
            output_directory,
            filename,
            effective_playlist_config or None,
        )
        effective_write_max_metadata = self.config.get(
            "download.write_max_metadata_json", True
        )
        if (
            effective_playlist_config
            and "write_max_metadata_json" in effective_playlist_config
        ):
            effective_write_max_metadata = bool(
                effective_playlist_config.get("write_max_metadata_json")
            )
        if effective_write_max_metadata:
            output_base_path = self._resolve_output_base_path(
                output_directory, filename, download_result
            )
            self._write_max_metadata_sidecar(
                base_path=output_base_path,
                video_url=video_url,
                download_result=download_result,
            )
        self._emit_post_download_generated_lines(
            output_directory, filename, download_result, metadata
        )
        return download_result

    def download_video_with_config_impl(
        self,
        video_url: str,
        output_template: str,
        output_directory: Path,
        filename: str,
        playlist_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Download video with specific configuration."""
        opts = self._build_runtime_ydl_options(
            playlist_config, include_progress_hooks=True
        )
        self._emit_subtitle_pipeline_debug(opts)
        opts["outtmpl"] = {
            "default": output_template,
            "subtitle": str(output_directory / f"{filename}.%(lang)s.%(ext)s"),
            "thumbnail": str(output_directory / f"{filename}.%(ext)s"),
        }
        return self._download_with_opts(video_url, opts)
