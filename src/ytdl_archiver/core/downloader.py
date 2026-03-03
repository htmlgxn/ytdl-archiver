"""YouTube video downloader with retry logic."""

import logging
import re
import sys
import time
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

    def __call__(self, d: dict[str, Any]) -> None:
        """Handle yt-dlp progress callback."""
        if d["status"] == "downloading" and self.formatter:
            title = d.get("info_dict", {}).get("title", "Unknown")
            if self.current_video != title:
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
            if self.current_video != title:
                self._reset_current_video_state(title)

            if hasattr(self.formatter, "close_video_progress"):
                self.formatter.close_video_progress()

            extension = self._extract_extension(d)
            resolution = self._extract_resolution(d)
            size = self._extract_size(d)
            primary_ext = self._normalize_extension(
                str(d.get("info_dict", {}).get("ext") or "")
            )

            is_primary = not self._primary_emitted_for_current and (
                not primary_ext or extension == primary_ext
            )

            if is_primary:
                complete_msg = self.formatter.video_complete(
                    title, resolution, extension, size
                )
                emit_rendered(complete_msg)
                self._primary_emitted_for_current = True
            elif (
                extension
                and extension not in self._emitted_artifact_exts
                and extension not in self.INTERMEDIATE_MEDIA_EXTENSIONS
                and extension not in self.THUMBNAIL_EXTENSIONS
            ):
                artifact_type = self._artifact_type_for_extension(extension)
                complete_msg = self.formatter.artifact_complete(
                    title, extension, artifact_type
                )
                emit_rendered(complete_msg)
                self._emitted_artifact_exts.add(extension)


class YouTubeDownloader:
    """YouTube video downloader with retry logic and configuration."""

    def __init__(self, config: Config, formatter=None):
        self.config = config
        self.formatter = formatter
        self.ydl_opts = self._build_ydl_options()

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

        mp4_path = output_directory / f"{filename}.mp4"
        if mp4_path.exists():
            mp4_size = self._format_size_from_bytes(mp4_path.stat().st_size)
            emit_rendered(self.formatter.mp4_generated(title, resolution, mp4_size))

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
            
        write_thumbnail = first_defined("write_thumbnail", "writethumbnail")
        if write_thumbnail is not None:
            opts["writethumbnail"] = write_thumbnail

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

        # Add recode video postprocessor if enabled
        recode_video = first_defined("recode_video")
        merge_output_format = first_defined("merge_output_format")
        if recode_video and merge_output_format:
            postprocessors.append({
                "key": "FFmpegVideoConvertor",
                "preferedformat": merge_output_format,
            })

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
        opts["outtmpl"] = {
            "default": output_template,
            "subtitle": str(output_directory / f"{filename}.%(subtitle_lang)s.%(ext)s"),
            "thumbnail": str(output_directory / f"{filename}.%(ext)s"),
        }
        return self._download_with_opts(video_url, opts)

    def get_metadata(self, video_url: str) -> dict[str, Any] | None:
        """Get video metadata without downloading."""
        opts = self._build_runtime_ydl_options(include_progress_hooks=False)
        
        # TEMPORARY: Disable ignoreerrors to see actual yt-dlp errors
        opts["ignoreerrors"] = False

        verbose = self.config.get("logging.level") == "DEBUG"

        # DEBUG: Print options to stderr
        print(f"DEBUG: get_metadata {video_url}", file=sys.stderr, flush=True)
        print(f"DEBUG: cookiefile={opts.get('cookiefile')}", file=sys.stderr, flush=True)
        print(f"DEBUG: format={repr(opts.get('format'))}", file=sys.stderr, flush=True)
        print(f"DEBUG: format_sort={repr(opts.get('format_sort'))}", file=sys.stderr, flush=True)
        print(f"DEBUG: extractor_args={opts.get('extractor_args')}", file=sys.stderr, flush=True)

        try:
            if verbose:
                logger.debug("Fetching metadata", extra={"video_url": video_url})
            with yt_dlp.YoutubeDL(opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=False)
                if info_dict is None:
                    print(f"DEBUG: yt-dlp returned None", file=sys.stderr, flush=True)
                    return None
                print(f"DEBUG: SUCCESS {info_dict.get('title')}", file=sys.stderr, flush=True)
                return info_dict
        except Exception as e:
            print(f"DEBUG ERROR: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            # Log at debug level since we have a fallback
            if verbose:
                logger.debug(
                    "Metadata prefetch failed (will use direct download)",
                    extra={"video_url": video_url, "error": str(e)},
                )
            return None

    def download_video_with_config(
        self,
        video_url: str,
        output_directory: Path,
        playlist_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Download video and handle directory structure based on metadata."""
        metadata = self.get_metadata(video_url)
        if metadata is None:
            emit_formatter_message(
                self.formatter,
                "warning",
                "Metadata prefetch failed. Falling back to direct download.",
            )

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
            playlist_config,
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
        opts["outtmpl"] = {
            "default": output_template,
            "subtitle": str(output_directory / f"{filename}.%(subtitle_lang)s.%(ext)s"),
            "thumbnail": str(output_directory / f"{filename}.%(ext)s"),
        }
        return self._download_with_opts(video_url, opts)
