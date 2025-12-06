"""YouTube video downloader with retry logic."""

import time
from pathlib import Path
from typing import Any, Dict, Optional

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
    import logging

    logger = logging.getLogger(__name__)


class YouTubeDownloader:
    """YouTube video downloader with retry logic and configuration."""

    def __init__(self, config: Config):
        self.config = config
        self.ydl_opts = self._build_ydl_options()

    def _build_ydl_options(self) -> Dict[str, Any]:
        """Build yt-dlp options from configuration."""
        return {
            "format": self.config.get("download.format"),
            "merge_output_format": self.config.get("download.merge_output_format"),
            "writesubtitles": self.config.get("download.write_subtitles"),
            "subtitlesformat": self.config.get("download.subtitle_format"),
            "convertsubtitles": self.config.get("download.convert_subtitles"),
            "subtitleslangs": self.config.get("download.subtitle_languages"),
            "writethumbnail": self.config.get("download.write_thumbnail"),
            "postprocessors": [
                {
                    "key": "FFmpegThumbnailsConvertor",
                    "format": self.config.get("download.thumbnail_format"),
                },
            ],
            "http_headers": {
                "User-Agent": self.config.get("http.user_agent"),
            },
            "socket_timeout": self.config.get("http.request_timeout"),
            "connect_timeout": self.config.get("http.connect_timeout"),
        }

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
    ) -> Dict[str, Any]:
        """Download video with retry logic."""
        opts = self.ydl_opts.copy()
        opts["outtmpl"] = {
            "default": output_template,
            "subtitle": str(output_directory / f"{filename}.%(subtitle_lang)s.%(ext)s"),
            "thumbnail": str(output_directory / f"{filename}.%(ext)s"),
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=True)
                logger.info(
                    "Successfully downloaded video",
                    video_id=info_dict.get("id"),
                    title=info_dict.get("title"),
                    duration=info_dict.get("duration"),
                )
                return info_dict
        except yt_dlp.DownloadError as e:
            logger.error("Download failed", video_url=video_url, error=str(e))
            raise DownloadError(f"Failed to download {video_url}: {e}")
        except Exception as e:
            logger.error(
                "Unexpected error during download", video_url=video_url, error=str(e)
            )
            raise DownloadError(f"Unexpected error downloading {video_url}: {e}")

    def get_metadata(self, video_url: str) -> Optional[Dict[str, Any]]:
        """Get video metadata without downloading."""
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=False)
                return info_dict
        except Exception as e:
            logger.error("Failed to get metadata", video_url=video_url, error=str(e))
            return None

    def download_video_with_metadata(
        self,
        video_url: str,
        output_directory: Path,
    ) -> Optional[Dict[str, Any]]:
        """Download video and handle directory structure based on metadata."""
        metadata = self.get_metadata(video_url)
        if metadata is None:
            return None

        title = metadata.get("title", "unknown-title")
        channel = metadata.get("uploader", "unknown-channel")

        safe_title = sanitize_filename(title)
        safe_channel = sanitize_filename(channel)
        filename = f"{safe_title}_{safe_channel}"

        # Check if video is a YouTube Short
        if self.config.get("shorts.detect_shorts", True):
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

        return self.download_video(
            video_url, output_template, output_directory, filename
        )
