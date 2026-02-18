"""Archive tracking for downloaded videos."""

import logging
import time
from pathlib import Path
from typing import Any

from ..exceptions import ArchiveError, ConfigurationError, DownloadError, MetadataError
from ..output import emit_formatter_message, emit_rendered
from .cookies import BrowserCookieRefresher

# Suppress yt-dlp's own logger to prevent unwanted output
yt_dlp_logger = logging.getLogger("yt_dlp")
yt_dlp_logger.setLevel(logging.CRITICAL)
yt_dlp_logger.addHandler(logging.NullHandler())


try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


class ArchiveTracker:
    """Track downloaded videos to avoid re-downloading."""

    def __init__(self, archive_file: Path):
        self.archive_file = archive_file
        self.downloaded_videos: set[str] = set()
        self.load_archive()

    def load_archive(self) -> None:
        """Load existing archive file."""
        try:
            if self.archive_file.exists():
                with open(self.archive_file) as f:
                    lines = f.read().splitlines()
                    self.downloaded_videos = set(
                        line.strip() for line in lines if line.strip()
                    )
                logger.info("Loaded archive", video_count=len(self.downloaded_videos))
            else:
                # Create empty archive file
                self.archive_file.parent.mkdir(parents=True, exist_ok=True)
                self.archive_file.touch()
                logger.info("Created new archive file", path=str(self.archive_file))
        except OSError as e:
            logger.error("Failed to load archive", error=str(e))
            raise ArchiveError(f"Failed to load archive: {e}") from e

    def is_downloaded(self, video_id: str) -> bool:
        """Check if video has been downloaded."""
        return video_id in self.downloaded_videos

    def mark_downloaded(self, video_id: str) -> None:
        """Mark video as downloaded."""
        try:
            self.downloaded_videos.add(video_id)
            with open(self.archive_file, "a") as f:
                f.write(video_id + "\n")
            logger.debug("Marked video as downloaded", video_id=video_id)
        except OSError as e:
            logger.error(
                "Failed to mark video as downloaded", video_id=video_id, error=str(e)
            )
            raise ArchiveError(f"Failed to mark video as downloaded: {e}") from e

    def get_downloaded_count(self) -> int:
        """Get count of downloaded videos."""
        return len(self.downloaded_videos)


class PlaylistArchiver:
    """Main archiver class for processing playlists."""

    def __init__(
        self,
        config,
        formatter=None,
        cookie_refresher: BrowserCookieRefresher | None = None,
        cookie_browser: str | None = None,
        cookie_profile: str | None = None,
        skip_initial_cookie_refresh: bool = False,
    ):
        self.config = config
        self.formatter = formatter
        self.cookie_refresher = cookie_refresher
        self.cookie_browser = cookie_browser.strip().lower() if cookie_browser else None
        self.cookie_profile = cookie_profile
        self.skip_initial_cookie_refresh = skip_initial_cookie_refresh
        self.downloader = None
        self.metadata_generator = None

        # Initialize components
        self._init_components()

    def _init_components(self) -> None:
        """Initialize downloader and metadata generator."""
        from .downloader import YouTubeDownloader
        from .metadata import MetadataGenerator

        self.downloader = YouTubeDownloader(self.config, self.formatter)
        self.metadata_generator = MetadataGenerator(self.config)

    def _emit_formatter_message(self, level: str, message: str) -> None:
        """Print formatter messages consistently."""
        emit_formatter_message(self.formatter, level, message)

    def _refresh_cookies(self, stage: str) -> None:
        """Refresh cookies from browser if refresh settings are enabled."""
        if not self.cookie_refresher or not self.cookie_browser:
            return

        cookie_path = self.config.get_cookie_file_target_path()
        try:
            self.cookie_refresher.refresh_to_file(
                self.cookie_browser,
                self.cookie_profile,
                cookie_path,
            )
            logger.info(
                "Refreshed browser cookies",
                stage=stage,
                browser=self.cookie_browser,
                cookie_file=str(cookie_path),
            )
        except Exception as e:
            message = (
                f"Cookie refresh failed at {stage} "
                f"(browser={self.cookie_browser}) - {e!s}"
            )
            self._emit_formatter_message("error", message)
            logger.error(
                "Cookie refresh failed",
                stage=stage,
                browser=self.cookie_browser,
                cookie_file=str(cookie_path),
                error=str(e),
            )
            raise ArchiveError(message) from e

    def process_playlist(self, playlist_id: str, playlist_path: str) -> None:
        """Process a single playlist."""
        base_directory = self.config.get_archive_directory()
        output_directory = base_directory / playlist_path
        output_directory.mkdir(parents=True, exist_ok=True)

        # Get playlist info first
        playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
        playlist_info = self._get_playlist_info(playlist_url)

        if not playlist_info or "entries" not in playlist_info:
            if self.formatter:
                self._emit_formatter_message(
                    "error",
                    f"Failed to get playlist info for {playlist_path} (ID: {playlist_id})",
                )
                self._emit_formatter_message(
                    "error",
                    "Please check that the playlist ID is correct and the playlist is public",
                )
            else:
                logger.error(
                    "Failed to get playlist info",
                    playlist_id=playlist_id,
                    playlist_path=playlist_path,
                )
            return

        # Show playlist start message before initializing tracker
        if self.formatter:
            playlist_msg = self.formatter.playlist_start(
                f"Processing: {playlist_path}", len(playlist_info.get("entries", []))
            )
            emit_rendered(playlist_msg)

            cookie_path = self.config.get_cookie_file_path()
            if cookie_path and not playlist_info.get("entries"):
                emit_rendered(
                    self.formatter.warning(
                        "Playlist is empty but cookies.txt exists - "
                        "you may need to re-authenticate your cookies"
                    )
                )

        # Initialize archive tracker
        archive_file = output_directory / ".archive.txt"
        tracker = ArchiveTracker(archive_file)

        # Track statistics
        stats = {"new": 0, "skipped": 0, "failed": 0}

        # Process each video
        for entry in playlist_info.get("entries", []):
            if not entry or not entry.get("id"):
                continue

            video_id = entry["id"]
            video_url = f"https://www.youtube.com/watch?v={video_id}"

            # Skip if already downloaded
            if tracker.is_downloaded(video_id):
                stats["skipped"] += 1
                if self.formatter:
                    emit_rendered(
                        self.formatter.warning(
                            f"Already downloaded: {entry.get('title', 'Unknown')}"
                        )
                    )
                else:
                    logger.debug("Skipping already downloaded video", video_id=video_id)
                continue

            # Download video
            try:
                # Get playlist-specific configuration
                playlist_config = self.config.get_playlist_config(
                    playlist_id, playlist_path
                )

                metadata = self.downloader.download_video_with_config(
                    video_url, output_directory, playlist_config
                )

                if metadata:
                    stats["new"] += 1

                    # Generate NFO file
                    self._generate_nfo_if_needed(metadata, output_directory)

                    # Mark as downloaded
                    tracker.mark_downloaded(video_id)

                    if self.formatter:
                        title = metadata.get("title", "Unknown")
                        resolution = ""
                        if metadata.get("height") and metadata.get("width"):
                            resolution = f"{metadata.get('height')}p"

                        # Show completion messages
                        emit_rendered(self.formatter.video_complete(title, resolution))
                        emit_rendered(self.formatter.file_generated("NFO metadata"))
                        emit_rendered(self.formatter.file_generated("Thumbnail image"))

                        # Only show subtitle message if subtitles were actually downloaded
                        if metadata.get("subtitles"):
                            emit_rendered(
                                self.formatter.file_generated("Subtitle file")
                            )
                    else:
                        logger.info(
                            "Successfully processed video",
                            video_id=video_id,
                            title=metadata.get("title"),
                        )

            except (ArchiveError, DownloadError, MetadataError, OSError, ValueError) as e:
                stats["failed"] += 1
                if self.formatter:
                    emit_rendered(
                        self.formatter.error(
                            f"Failed to download {entry.get('title', 'Unknown')} - {e!s}"
                        )
                    )
                else:
                    logger.error(
                        "Failed to process video", video_id=video_id, error=str(e)
                    )
                continue

        if self.formatter:
            emit_rendered(self.formatter.playlist_summary(stats))
        else:
            logger.info(
                "Finished processing playlist",
                playlist_id=playlist_id,
                downloaded_count=tracker.get_downloaded_count(),
            )

    def _get_playlist_info(self, playlist_url: str) -> dict[str, Any]:
        """Get playlist information."""
        opts = {
            "extract_flat": True,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "no_color": True,
            "progress": False,
            "progress_with_newline": False,
            "simulate": False,
            "print_json": False,
            "socket_timeout": 30,
            "retries": 2,
            "extractor_retries": 2,
            "no_check_certificates": True,
            "no_call_home": True,
            "no_update_check": True,
            "noplaylist": False,
        }

        cookie_path = self.config.get_cookie_file_path()
        if cookie_path:
            opts["cookiefile"] = str(cookie_path)

        opts["extractor_args"] = {"youtube": {"player_client": "default"}}

        try:
            import yt_dlp

            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(playlist_url, download=False)
        except Exception as e:
            logger.error(
                "Failed to get playlist info", playlist_url=playlist_url, error=str(e)
            )
            return {}

    def _generate_nfo_if_needed(
        self, metadata: dict[str, Any], output_directory: Path
    ) -> None:
        """Generate NFO file if enabled."""
        if not self.config.get("media_server.generate_nfo", True):
            return

        try:
            title = metadata.get("title", "unknown-title")
            channel = metadata.get("uploader", "unknown-channel")

            from .utils import sanitize_filename

            safe_title = sanitize_filename(title)
            safe_channel = sanitize_filename(channel)
            filename = f"{safe_title}_{safe_channel}"

            # Check if video file exists
            video_file = output_directory / f"{filename}.mp4"
            if video_file.exists():
                nfo_path = video_file.with_suffix(".nfo")
                self.metadata_generator.create_nfo_file(metadata, nfo_path)

        except (MetadataError, OSError, ValueError, RuntimeError, TypeError) as e:
            logger.error("Failed to generate NFO", error=str(e))

    def run(self) -> None:
        """Run the archiver with playlists from file."""
        if not self.skip_initial_cookie_refresh:
            self._refresh_cookies("startup")

        playlists_file = self.config.get_playlists_file()

        if not playlists_file.exists():
            if self.formatter:
                self._emit_formatter_message(
                    "error", f"Playlists file not found: {playlists_file}"
                )
            else:
                logger.error("Playlists file not found", path=playlists_file)
            raise ArchiveError(f"Playlists file not found: {playlists_file}")

        # Load playlists
        try:
            playlists = self.config.load_playlists()
        except (ConfigurationError, ArchiveError, OSError, ValueError) as e:
            if self.formatter:
                self._emit_formatter_message(
                    "error", f"Failed to load playlists - {e!s}"
                )
            else:
                logger.error("Failed to load playlists", error=str(e))
            raise ArchiveError(f"Failed to load playlists: {e}") from e

        if self.formatter:
            emit_rendered(
                self.formatter.playlist_start("All Playlists", len(playlists))
            )

        # Process each playlist
        for i, playlist in enumerate(playlists):
            playlist_id = playlist.get("id")
            playlist_path = playlist.get("path")

            if not playlist_id or not playlist_path:
                if self.formatter:
                    self._emit_formatter_message(
                        "warning", "Invalid playlist entry - skipping"
                    )
                else:
                    logger.warning("Invalid playlist entry", playlist=playlist)
                continue

            self._refresh_cookies(f"before playlist {playlist_path}")

            try:
                self.process_playlist(playlist_id, playlist_path)

                # Add delay between playlists
                if i < len(playlists) - 1:  # Not the last playlist
                    delay = self.config.get("archive.delay_between_playlists", 30)
                    if delay > 0:
                        logger.info("Waiting before next playlist", delay=delay)
                        time.sleep(delay)

            except (ArchiveError, DownloadError, OSError, ValueError, RuntimeError) as e:
                logger.error(
                    "Failed to process playlist", playlist_id=playlist_id, error=str(e)
                )
                continue

        logger.info("Archiver run completed")
