"""YouTube video downloader with retry logic."""

import logging
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
    logger = logging.getLogger(__name__)


class ProgressCallback:
    """Progress callback for yt-dlp with formatter integration."""
    
    def __init__(self, formatter):
        self.formatter = formatter
        self.current_video = None
    
    def __call__(self, d: Dict[str, Any]) -> None:
        """Handle yt-dlp progress callback."""
        if d['status'] == 'downloading' and self.formatter:
            title = d.get('info_dict', {}).get('title', 'Unknown')
            if self.current_video != title:
                self.current_video = title
                # Show start of new download
                start_msg = f"🔵 Starting download: {title}"
                print(start_msg, flush=True)
            
            # Show progress during download
            progress_msg = self.formatter.video_progress(
                self.current_video,
                {
                    'percent': d.get('_percent_str', '0%'),
                    'speed': d.get('_speed_str', ''),
                    'eta': d.get('_eta_str', '')
                }
            )
            if progress_msg:
                print(progress_msg, end='\r', flush=True)
                
        elif d['status'] == 'finished' and self.formatter:
            if self.current_video:
                title = self.current_video
                resolution = ""
                if d.get('info_dict', {}).get('height') and d.get('info_dict', {}).get('width'):
                    resolution = f"{d.get('info_dict', {}).get('height')}p"
                
                size = ""
                if d.get('total_bytes_str'):
                    size = d.get('total_bytes_str', '')
                
                # Clear the progress line and show completion
                print(' ' * 120, end='\r')  # Clear progress line
                complete_msg = self.formatter.video_complete(title, resolution, size)
                print(complete_msg)
                self.current_video = None


class YouTubeDownloader:
    """YouTube video downloader with retry logic and configuration."""

    def __init__(self, config: Config, formatter=None):
        self.config = config
        self.formatter = formatter
        self.ydl_opts = self._build_ydl_options()

    def _build_ydl_options(self, playlist_config: Dict[str, Any] = None) -> Dict[str, Any]:
        """Build yt-dlp options from configuration with playlist-specific overrides."""
        # Use empty dict if no playlist config provided
        if playlist_config is None:
            playlist_config = {}
        
        # Start with global defaults
        opts = {
            "format": playlist_config.get("format", self.config.get("download.format")),
            "merge_output_format": playlist_config.get(
                "merge_output_format", self.config.get("download.merge_output_format")
            ),
            "writesubtitles": playlist_config.get(
                "writesubtitles", self.config.get("download.write_subtitles")
            ),
            "subtitlesformat": playlist_config.get(
                "subtitlesformat", self.config.get("download.subtitle_format")
            ),
            "convertsubtitles": playlist_config.get(
                "convertsubtitles", self.config.get("download.convert_subtitles")
            ),
            "subtitleslangs": playlist_config.get(
                "subtitleslangs", self.config.get("download.subtitle_languages")
            ),
            "writethumbnail": playlist_config.get(
                "writethumbnail", self.config.get("download.write_thumbnail")
            ),
            "quiet": True,  # Suppress raw yt-dlp output
            "no_warnings": True,  # Suppress warnings
            "progress_hooks": [],  # We'll add this dynamically
            "postprocessors": [
                {
                    "key": "FFmpegThumbnailsConvertor",
                    "format": playlist_config.get(
                        "thumbnail_format", self.config.get("download.thumbnail_format")
                    ),
                },
            ],
            "http_headers": {
                "User-Agent": self.config.get("http.user_agent"),
            },
            "socket_timeout": playlist_config.get(
                "socket_timeout", self.config.get("http.request_timeout")
            ),
            "connect_timeout": playlist_config.get(
                "connect_timeout", self.config.get("http.connect_timeout")
            ),
        }

        # Add JavaScript runtime handling to suppress warnings
        if self.formatter and hasattr(self.formatter, 'js_runtime_warning'):
            opts["extractor_args"] = "youtube:player_client=default"

        # Remove None values to avoid yt-dlp issues
        opts = {k: v for k, v in opts.items() if v is not None}
        return opts

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
            # Add progress callback if formatter supports it
            progress_callback = None
            if self.formatter and hasattr(self.formatter, 'video_progress'):
                progress_callback = ProgressCallback(self.formatter)
                opts["progress_hooks"] = [progress_callback]
            
            # Ensure we suppress all raw output
            opts["quiet"] = True
            opts["no_warnings"] = True
            opts["progress"] = False  # Disable built-in progress bar
            opts["extract_flat"] = False  # Don't show extraction details
            opts["print_json"] = False  # Don't print JSON
            opts["simulate"] = False  # Actually download, but quietly
            opts["noplaylist"] = False  # Allow playlists
            opts["extractaudio"] = False  # Don't show audio extraction messages
            opts["extractvideo"] = False  # Don't show video extraction messages
            opts["no_color"] = True  # Disable all colors from yt-dlp
            opts["progress_with_newline"] = False  # Don't add newlines to progress
            opts["xattr_set_filesize"] = False  # Don't show file size messages
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=True)
                return info_dict
        except yt_dlp.DownloadError as e:
            if self.formatter:
                self.formatter.error(f"Failed to download video - {str(e)}")
            else:
                logger.error("Download failed", video_url=video_url, error=str(e))
            raise DownloadError(f"Failed to download {video_url}: {e}")
        except Exception as e:
            if self.formatter:
                self.formatter.error(f"Unexpected error downloading video - {str(e)}")
            else:
                logger.error("Unexpected error during download", video_url=video_url, error=str(e))
            raise DownloadError(f"Unexpected error downloading {video_url}: {e}")

    def get_metadata(self, video_url: str) -> Optional[Dict[str, Any]]:
        """Get video metadata without downloading."""
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }

        # Add JavaScript runtime handling
        if self.formatter and hasattr(self.formatter, 'js_runtime_warning'):
            opts["extractor_args"] = "youtube:player_client=default"

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=False)
                return info_dict
        except Exception as e:
            if self.formatter:
                self.formatter.error(f"Failed to get metadata - {str(e)}")
            else:
                logger.error("Failed to get metadata", video_url=video_url, error=str(e))
            return None

    def download_video_with_config(
        self,
        video_url: str,
        output_directory: Path,
        playlist_config: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
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

        # Use playlist-specific config if provided
        if playlist_config:
            return self.download_video_with_config_impl(
                video_url, output_template, output_directory, filename, playlist_config
            )
        else:
            return self.download_video(video_url, output_template, output_directory, filename)

    def download_video_with_config_impl(
        self,
        video_url: str,
        output_template: str,
        output_directory: Path,
        filename: str,
        playlist_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Download video with specific configuration."""
        opts = self._build_ydl_options(playlist_config)
        opts["outtmpl"] = {
            "default": output_template,
            "subtitle": str(output_directory / f"{filename}.%(subtitle_lang)s.%(ext)s"),
            "thumbnail": str(output_directory / f"{filename}.%(ext)s"),
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=True)
                logger.info(
                    "Successfully downloaded video with custom config",
                    video_id=info_dict.get("id"),
                    title=info_dict.get("title"),
                    duration=info_dict.get("duration"),
                    format=playlist_config.get("format", "default"),
                )
                return info_dict
        except yt_dlp.DownloadError as e:
            logger.error("Download failed", video_url=video_url, error=str(e))
            raise DownloadError(f"Failed to download {video_url}: {e}")
        except Exception as e:
            logger.error("Unexpected error during download", video_url=video_url, error=str(e))
            raise DownloadError(f"Unexpected error downloading {video_url}: {e}")