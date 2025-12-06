"""Archive tracking for downloaded videos."""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Set

import toml
from ..exceptions import ArchiveError

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
        self.downloaded_videos: Set[str] = set()
        self.load_archive()

    def load_archive(self) -> None:
        """Load existing archive file."""
        try:
            if self.archive_file.exists():
                with open(self.archive_file, "r") as f:
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
        except Exception as e:
            logger.error("Failed to load archive", error=str(e))
            raise ArchiveError(f"Failed to load archive: {e}")

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
        except Exception as e:
            logger.error(
                "Failed to mark video as downloaded", video_id=video_id, error=str(e)
            )
            raise ArchiveError(f"Failed to mark video as downloaded: {e}")

    def get_downloaded_count(self) -> int:
        """Get count of downloaded videos."""
        return len(self.downloaded_videos)


class PlaylistArchiver:
    """Main archiver class for processing playlists."""

    def __init__(self, config):
        self.config = config
        self.downloader = None
        self.metadata_generator = None

        # Initialize components
        self._init_components()

    def _init_components(self) -> None:
        """Initialize downloader and metadata generator."""
        from .downloader import YouTubeDownloader
        from .metadata import MetadataGenerator

        self.downloader = YouTubeDownloader(self.config)
        self.metadata_generator = MetadataGenerator(self.config)

    def process_playlist(self, playlist_id: str, playlist_path: str) -> None:
        """Process a single playlist."""
        base_directory = self.config.get_archive_directory()
        output_directory = base_directory / playlist_path
        output_directory.mkdir(parents=True, exist_ok=True)

        # Initialize archive tracker
        archive_file = output_directory / ".archive.txt"
        tracker = ArchiveTracker(archive_file)

        logger.info("Processing playlist", playlist_id=playlist_id, path=playlist_path)

        # Get playlist info
        playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
        playlist_info = self._get_playlist_info(playlist_url)

        if not playlist_info or "entries" not in playlist_info:
            logger.error("Failed to get playlist info", playlist_id=playlist_id)
            return

        # Process each video
        for entry in playlist_info["entries"]:
            if not entry or not entry.get("id"):
                continue

            video_id = entry["id"]
            video_url = f"https://www.youtube.com/watch?v={video_id}"

            # Skip if already downloaded
            if tracker.is_downloaded(video_id):
                logger.debug("Skipping already downloaded video", video_id=video_id)
                continue

            # Download video
            try:
                metadata = self.downloader.download_video_with_metadata(
                    video_url, output_directory
                )

                if metadata:
                    # Generate NFO file
                    self._generate_nfo_if_needed(metadata, output_directory)

                    # Mark as downloaded
                    tracker.mark_downloaded(video_id)

                    logger.info(
                        "Successfully processed video",
                        video_id=video_id,
                        title=metadata.get("title"),
                    )

            except Exception as e:
                logger.error("Failed to process video", video_id=video_id, error=str(e))
                continue

        logger.info(
            "Finished processing playlist",
            playlist_id=playlist_id,
            downloaded_count=tracker.get_downloaded_count(),
        )

    def _get_playlist_info(self, playlist_url: str) -> Dict[str, Any]:
        """Get playlist information."""
        opts = {
            "extract_flat": True,
            "quiet": True,
            "ignoreerrors": True,
        }

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
        self, metadata: Dict[str, Any], output_directory: Path
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

        except Exception as e:
            logger.error("Failed to generate NFO", error=str(e))

    def run(self, playlists_file: Path = None) -> None:
        """Run the archiver with playlists from file."""
        if playlists_file is None:
            playlists_file = self.config.get_playlists_file()

        if not playlists_file.exists():
            raise ArchiveError(f"Playlists file not found: {playlists_file}")

        # Load playlists
        try:
            if playlists_file.suffix.lower() == ".toml":
                with open(playlists_file, "r") as f:
                    playlists_data = toml.load(f)
                    playlists = playlists_data.get("playlists", [])
            else:
                with open(playlists_file, "r") as f:
                    playlists = json.load(f)
        except Exception as e:
            raise ArchiveError(f"Failed to load playlists: {e}")

        logger.info("Starting archiver", playlist_count=len(playlists))

        # Process each playlist
        for i, playlist in enumerate(playlists):
            playlist_id = playlist.get("id")
            playlist_path = playlist.get("path")

            if not playlist_id or not playlist_path:
                logger.warning("Invalid playlist entry", playlist=playlist)
                continue

            try:
                self.process_playlist(playlist_id, playlist_path)

                # Add delay between playlists
                if i < len(playlists) - 1:  # Not the last playlist
                    delay = self.config.get("archive.delay_between_playlists", 30)
                    if delay > 0:
                        logger.info("Waiting before next playlist", delay=delay)
                        time.sleep(delay)

            except Exception as e:
                logger.error(
                    "Failed to process playlist", playlist_id=playlist_id, error=str(e)
                )
                continue

        logger.info("Archiver run completed")
