"""YouTube video downloader with retry logic."""

import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

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
from .utils import is_short, sanitize_filename

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    logger = logging.getLogger(__name__)

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
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.CRITICAL)
    logger.addHandler(logging.NullHandler())


@contextmanager
def suppress_output():
    """Context manager to suppress stdout and stderr."""
    with open(os.devnull, "w") as devnull:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        try:
            sys.stdout = devnull
            sys.stderr = devnull
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr


class ProgressCallback:
    """Progress callback for yt-dlp with formatter integration."""

    def __init__(self, formatter):
        self.formatter = formatter
        self.current_video = None

    def __call__(self, d: dict[str, Any]) -> None:
        """Handle yt-dlp progress callback."""
        if d["status"] == "downloading" and self.formatter:
            title = d.get("info_dict", {}).get("title", "Unknown")
            if self.current_video != title:
                self.current_video = title
                # Start new progress bar
                if hasattr(self.formatter, "start_video_progress"):
                    self.formatter.start_video_progress(title)
                else:
                    # Fallback to old behavior
                    start_msg = f"🔵 Starting download: {title}"
                    print(start_msg, flush=True)

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
                    print(progress_msg, end="\r", flush=True)

        elif d["status"] == "finished" and self.formatter:
            if self.current_video:
                title = self.current_video
                resolution = ""
                if d.get("info_dict", {}).get("height") and d.get("info_dict", {}).get(
                    "width"
                ):
                    resolution = f"{d.get('info_dict', {}).get('height')}p"

                size = ""
                if d.get("total_bytes_str"):
                    size = d.get("total_bytes_str", "")

                # Close progress bar and show completion
                if hasattr(self.formatter, "close_video_progress"):
                    self.formatter.close_video_progress()
                else:
                    # Fallback to old behavior
                    print(" " * 120, end="\r")

                complete_msg = self.formatter.video_complete(title, resolution, size)
                print(complete_msg)
                self.current_video = None


class YouTubeDownloader:
    """YouTube video downloader with retry logic and configuration."""

    def __init__(self, config: Config, formatter=None):
        self.config = config
        self.formatter = formatter
        self.ydl_opts = self._build_ydl_options()

    def _build_ydl_options(
        self, playlist_config: dict[str, Any] = None
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
            return None

        # Start with global defaults
        opts = {
            "format": first_defined("format") or self.config.get("download.format"),
            "merge_output_format": first_defined("merge_output_format")
            or self.config.get("download.merge_output_format"),
            "writesubtitles": first_defined("writesubtitles", "write_subtitles")
            if first_defined("writesubtitles", "write_subtitles") is not None
            else self.config.get("download.write_subtitles"),
            "subtitlesformat": first_defined("subtitlesformat", "subtitle_format")
            or self.config.get("download.subtitle_format"),
            "convertsubtitles": first_defined("convertsubtitles", "convert_subtitles")
            or self.config.get("download.convert_subtitles"),
            "subtitleslangs": first_defined("subtitleslangs", "subtitle_languages")
            or self.config.get("download.subtitle_languages"),
            "writethumbnail": first_defined("writethumbnail", "write_thumbnail")
            if first_defined("writethumbnail", "write_thumbnail") is not None
            else self.config.get("download.write_thumbnail"),
            "postprocessors": [
                {
                    "key": "FFmpegThumbnailsConvertor",
                    "format": first_defined("thumbnail_format")
                    or self.config.get("download.thumbnail_format"),
                },
            ],
            "http_headers": {
                "User-Agent": self.config.get("http.user_agent"),
            },
            "socket_timeout": first_defined("socket_timeout")
            or self.config.get("http.request_timeout"),
            "connect_timeout": first_defined("connect_timeout")
            or self.config.get("http.connect_timeout"),
        }

        # Add JavaScript runtime handling to suppress warnings
        if self.formatter and hasattr(self.formatter, "js_runtime_warning"):
            opts["extractor_args"] = {"youtube": {"player_client": "default"}}

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
        parsed = urlparse(video_url)
        query_id = parse_qs(parsed.query).get("v", [None])[0]
        if query_id:
            return query_id

        path = parsed.path.strip("/")
        if path.startswith("shorts/"):
            short_id = path.split("/", 1)[1]
            if short_id:
                return short_id

        tail = path.split("/")[-1]
        if tail:
            return tail

        return "unknown-video"

    def _build_output_filename(self, metadata: dict[str, Any] | None, video_url: str) -> str:
        """Build a deterministic output filename."""
        video_id = self._extract_video_id(video_url)
        fallback_title = f"video-{video_id}"

        title = metadata.get("title", fallback_title) if metadata else fallback_title
        channel = metadata.get("uploader", "unknown-channel") if metadata else "unknown-channel"

        safe_title = sanitize_filename(title) or fallback_title
        safe_channel = sanitize_filename(channel) or "unknown-channel"
        return f"{safe_title}_{safe_channel}"

    def _emit_formatter_error(self, message: str) -> None:
        """Print formatter-generated errors consistently."""
        if not self.formatter:
            return
        rendered = self.formatter.error(message)
        if rendered:
            print(rendered)

    def _emit_formatter_warning(self, message: str) -> None:
        """Print formatter-generated warnings consistently."""
        if not self.formatter:
            return
        rendered = self.formatter.warning(message)
        if rendered:
            print(rendered)

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
        return self.download_video(video_url, output_template, output_directory, filename)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((DownloadError, yt_dlp.DownloadError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
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

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=True)
                return info_dict
        except yt_dlp.DownloadError as e:
            logger.error("Download failed", video_url=video_url, error=str(e))
            raise DownloadError(f"Failed to download {video_url}: {e}")
        except Exception as e:
            if self.formatter:
                self._emit_formatter_error(f"Unexpected error downloading video - {e!s}")
            else:
                logger.error(
                    "Unexpected error during download",
                    video_url=video_url,
                    error=str(e),
                )
            raise DownloadError(f"Unexpected error downloading {video_url}: {e}")

    def get_metadata(self, video_url: str) -> dict[str, Any] | None:
        """Get video metadata without downloading."""
        opts = self._build_runtime_ydl_options(include_progress_hooks=False)

        verbose = self.config.get("logging.level") == "DEBUG"

        try:
            if verbose:
                logger.debug("Fetching metadata", video_url=video_url)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=False)
                if verbose and info_dict:
                    logger.debug("Metadata fetched", title=info_dict.get("title"))
                return info_dict
        except Exception as e:
            if self.formatter:
                self._emit_formatter_error(f"Failed to get metadata - {e!s}")
            else:
                logger.error(
                    "Failed to get metadata", video_url=video_url, error=str(e)
                )
            return None

    def download_video_with_config(
        self,
        video_url: str,
        output_directory: Path,
        playlist_config: dict[str, Any] = None,
    ) -> dict[str, Any]:
        """Download video and handle directory structure based on metadata."""
        metadata = self.get_metadata(video_url)
        if metadata is None:
            self._emit_formatter_warning(
                "Metadata prefetch failed. Falling back to direct download."
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

        return self._download_with_effective_config(
            video_url,
            output_template,
            output_directory,
            filename,
            playlist_config,
        )

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

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=True)
                return info_dict
        except yt_dlp.DownloadError as e:
            logger.error("Download failed", video_url=video_url, error=str(e))
            raise DownloadError(f"Failed to download {video_url}: {e}")
        except Exception as e:
            if self.formatter:
                self._emit_formatter_error(f"Unexpected error downloading video - {e!s}")
            logger.error(
                "Unexpected error during download", video_url=video_url, error=str(e)
            )
            raise DownloadError(f"Unexpected error downloading {video_url}: {e}")
