"""YouTube video downloader with retry logic."""

import logging
from pathlib import Path
from typing import Any, cast

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
from .artifacts import (
    rename_stem_artifacts,
    stem_looks_like_fallback,
)
from .progress import ProgressCallback
from .sidecars import (
    emit_post_download_generated_lines,
    resolve_final_media_path,
    resolve_output_base_path,
    write_max_metadata_sidecar,
)
from .utils import (
    build_output_filename,
    extract_video_id,
    is_short,
    suppress_output,
)
from .ydl_options import (
    SilentYTDLPLogger,
    build_runtime_ydl_options,
    build_ydl_options,
)

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    logger = logging.getLogger(__name__)
stdlib_logger = logging.getLogger(__name__)


class YouTubeDownloader:
    """YouTube video downloader with retry logic and configuration."""

    def __init__(self, config: Config, formatter=None):
        self.config = config
        self.formatter = formatter
        self.ydl_opts = build_ydl_options(config)
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
        playlist_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve effective format/remux strategy for container policy.

        Uses yt-dlp's native ``format_sort`` preferences instead of fragile
        height-pinned format strings.
        """
        policy = str(
            self._effective_download_setting(
                "container_policy",
                playlist_config,
                default="prefer_mp4",
            )
        ).strip()
        if policy not in {"prefer_mp4", "force_mp4", "prefer_source"}:
            policy = "prefer_mp4"

        overrides: dict[str, Any] = {}

        if policy == "force_mp4":
            overrides["format"] = "bestvideo*+bestaudio/best"
            overrides["format_sort"] = ["res", "br", "fps", "ext:mp4:m4a:mov"]
            overrides["remux_video"] = "mp4"
        elif policy == "prefer_mp4":
            overrides["format"] = "bestvideo*+bestaudio/best"
            overrides["format_sort"] = ["res", "br", "fps", "ext:mp4:m4a:mov"]
        else:
            # prefer_source: best quality, default sorting
            overrides["format"] = "bestvideo*+bestaudio/best"

        self._emit_verbose_debug(
            "Format selection strategy resolved",
            policy=policy,
            format=overrides.get("format"),
            format_sort=overrides.get("format_sort"),
            remux_video=overrides.get("remux_video"),
        )
        return overrides

    def _build_ydl_options(
        self, playlist_config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Build yt-dlp options from configuration (delegates to ydl_options module)."""
        return build_ydl_options(self.config, playlist_config)

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

    def _resolve_effective_stem(
        self,
        *,
        output_directory: Path,
        filename: str,
        video_url: str,
        download_result: dict[str, Any] | None,
    ) -> str:
        """Resolve final stem, reconciling fallback names after download."""
        source_stem = filename
        media_path = resolve_final_media_path(output_directory, filename, download_result)
        if media_path is not None:
            source_stem = media_path.stem

        if not isinstance(download_result, dict) or not download_result:
            return source_stem

        target_stem = self._build_output_filename(download_result, video_url)
        if not target_stem:
            return source_stem
        if source_stem == target_stem:
            return source_stem
        if "unknown-channel" in target_stem and "unknown-channel" not in source_stem:
            return source_stem
        if stem_looks_like_fallback(target_stem) and not stem_looks_like_fallback(source_stem):
            return source_stem
        if stem_looks_like_fallback(source_stem) and stem_looks_like_fallback(target_stem):
            return source_stem

        rename_result = rename_stem_artifacts(output_directory, source_stem, target_stem)
        if rename_result.status == "renamed":
            self._emit_verbose_debug(
                "Reconciled artifact stem from final metadata",
                source_stem=source_stem,
                target_stem=target_stem,
                renamed_count=rename_result.renamed_count,
                video_url=video_url,
            )
            return target_stem

        if rename_result.status == "conflict":
            emit_formatter_message(
                self.formatter,
                "warning",
                (
                    "Rename skipped: target stem already exists "
                    f"({source_stem} -> {target_stem})"
                ),
            )
            self._emit_verbose_debug(
                "Stem reconciliation skipped due to conflict",
                source_stem=source_stem,
                target_stem=target_stem,
                conflict_path=str(rename_result.conflict_path) if rename_result.conflict_path else "",
                video_url=video_url,
            )
            return source_stem

        if rename_result.status == "failed":
            emit_formatter_message(
                self.formatter,
                "warning",
                (
                    "Rename failed: could not reconcile artifact stem "
                    f"({source_stem} -> {target_stem})"
                ),
            )
            self._emit_verbose_debug(
                "Stem reconciliation failed",
                source_stem=source_stem,
                target_stem=target_stem,
                video_url=video_url,
            )
            return source_stem

        return source_stem

    def _build_runtime_ydl_options(
        self,
        playlist_config: dict[str, Any] | None = None,
        *,
        include_progress_hooks: bool = False,
    ) -> dict[str, Any]:
        """Build effective yt-dlp options used at runtime."""
        return build_runtime_ydl_options(
            self.config,
            playlist_config,
            include_progress_hooks=include_progress_hooks,
            formatter=self.formatter,
        )

    def _extract_video_id(self, video_url: str) -> str:
        """Extract a stable video id from common YouTube URL formats."""
        return extract_video_id(video_url, None)

    def _build_output_filename(
        self, metadata: dict[str, Any] | None, video_url: str
    ) -> str:
        """Build a deterministic output filename."""
        return build_output_filename(self.config, metadata, video_url)

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

    def _download_with_opts(
        self, video_url: str, opts: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute yt-dlp with prepared options."""
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                result = ydl.extract_info(video_url, download=True)
                if result is None:
                    raise DownloadError(
                        f"yt-dlp returned no result for {video_url} "
                        "(video may be unavailable, geo-blocked, or age-restricted)"
                    )
                return result
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

    def download_video_with_config(
        self,
        video_url: str,
        output_directory: Path,
        playlist_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Download video and handle directory structure based on metadata."""
        self._emitted_subtitle_paths = set()
        effective_playlist_config = dict(playlist_config or {})

        # Apply container policy overrides (no metadata prefetch needed)
        strategy_overrides = self._resolve_download_strategy_overrides(
            effective_playlist_config
        )
        effective_playlist_config.update(strategy_overrides)

        # Use a preliminary filename based on video ID for download
        video_id = self._extract_video_id(video_url)
        preliminary_filename = f"video-{video_id}" if video_id else self._build_output_filename(None, video_url)

        output_directory.mkdir(parents=True, exist_ok=True)
        output_template = str(output_directory / f"{preliminary_filename}.%(ext)s")

        download_result = self._download_with_effective_config(
            video_url,
            output_template,
            output_directory,
            preliminary_filename,
            effective_playlist_config or None,
        )

        # Build canonical filename from download result metadata
        filename = self._build_output_filename(download_result, video_url)

        # Post-download Shorts detection and relocation
        if self.config.get("shorts.detect_shorts", True):
            threshold = self.config.get("shorts.aspect_ratio_threshold", 0.7)
            if is_short(download_result, threshold):
                shorts_dir = output_directory / self.config.get(
                    "shorts.shorts_subdirectory", "YouTube Shorts"
                )
                shorts_dir.mkdir(parents=True, exist_ok=True)
                # Move artifacts from output_directory to shorts_dir
                move_result = rename_stem_artifacts(
                    output_directory, preliminary_filename, preliminary_filename,
                    target_directory=shorts_dir,
                )
                if move_result.status == "renamed":
                    output_directory = shorts_dir

        # Reconcile preliminary stem to canonical filename
        effective_stem = self._resolve_effective_stem(
            output_directory=output_directory,
            filename=preliminary_filename,
            video_url=video_url,
            download_result=download_result,
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
            output_base_path = resolve_output_base_path(
                output_directory, effective_stem, download_result
            )
            write_max_metadata_sidecar(
                base_path=output_base_path,
                video_url=video_url,
                download_result=download_result,
                formatter=self.formatter,
                verbose_debug=self._emit_verbose_debug if self._verbose_enabled() else None,
            )
        emit_post_download_generated_lines(
            output_directory, effective_stem, download_result, download_result,
            formatter=self.formatter,
            emitted_subtitle_paths=self._emitted_subtitle_paths,
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
