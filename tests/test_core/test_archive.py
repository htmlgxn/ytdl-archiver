"""Tests for archive tracking functionality."""

from unittest.mock import Mock, patch

import pytest

from ytdl_archiver.core.archive import ArchiveTracker, PlaylistArchiver
from ytdl_archiver.exceptions import ArchiveError


class TestArchiveTracker:
    """Test cases for ArchiveTracker class."""

    def test_init_with_existing_archive(self, temp_dir):
        """Test ArchiveTracker initialization with existing archive file."""
        # Create existing archive file
        archive_file = temp_dir / ".archive.txt"
        archive_file.write_text("video1\nvideo2\nvideo3\n")

        tracker = ArchiveTracker(archive_file)

        assert len(tracker.downloaded_videos) == 3
        assert "video1" in tracker.downloaded_videos
        assert "video2" in tracker.downloaded_videos
        assert "video3" in tracker.downloaded_videos

    def test_init_with_new_archive(self, archive_file):
        """Test ArchiveTracker initialization with new archive file."""
        tracker = ArchiveTracker(archive_file)

        assert len(tracker.downloaded_videos) == 0
        assert archive_file.exists()

    def test_is_downloaded(self, archive_tracker):
        """Test checking if video is downloaded."""
        # Add some videos to tracker
        archive_tracker.downloaded_videos = {"video1", "video2"}

        assert archive_tracker.is_downloaded("video1") is True
        assert archive_tracker.is_downloaded("video2") is True
        assert archive_tracker.is_downloaded("video3") is False

    def test_mark_downloaded(self, archive_tracker):
        """Test marking video as downloaded."""
        assert archive_tracker.is_downloaded("new_video") is False

        archive_tracker.mark_downloaded("new_video")

        assert archive_tracker.is_downloaded("new_video") is True
        assert "new_video" in archive_tracker.downloaded_videos

    def test_mark_downloaded_saves_to_file(self, archive_tracker):
        """Test that marking downloaded saves to file."""
        # Mark some videos as downloaded
        archive_tracker.mark_downloaded("video1")
        archive_tracker.mark_downloaded("video2")
        archive_tracker.mark_downloaded("video3")

        # Read file content
        content = archive_tracker.archive_file.read_text()
        lines = content.strip().split("\n")

        assert len(lines) == 3
        assert "video1" in lines
        assert "video2" in lines
        assert "video3" in lines

    def test_load_archive_with_empty_lines(self, temp_dir):
        """Test loading archive with empty lines and whitespace."""
        archive_file = temp_dir / ".archive.txt"
        archive_file.write_text("video1\n\nvideo2\n  \nvideo3\n\n")

        tracker = ArchiveTracker(archive_file)

        assert len(tracker.downloaded_videos) == 3
        assert "video1" in tracker.downloaded_videos
        assert "video2" in tracker.downloaded_videos
        assert "video3" in tracker.downloaded_videos

    def test_mark_downloaded_duplicate(self, archive_tracker):
        """Test marking already downloaded video."""
        archive_tracker.downloaded_videos = {"video1"}

        # Should not duplicate
        archive_tracker.mark_downloaded("video1")

        assert len(archive_tracker.downloaded_videos) == 1
        assert "video1" in archive_tracker.downloaded_videos

    def test_get_downloaded_count(self, archive_tracker):
        """Test getting downloaded count."""
        assert archive_tracker.get_downloaded_count() == 0

        archive_tracker.downloaded_videos = {"video1", "video2", "video3"}
        assert archive_tracker.get_downloaded_count() == 3

    def test_mark_downloaded_permission_error(self, archive_tracker, mocker):
        """Test marking downloaded with permission error."""
        # Mock open to raise permission error
        mocker.patch("builtins.open", side_effect=PermissionError("Permission denied"))

        with pytest.raises(ArchiveError, match="Failed to mark video as downloaded"):
            archive_tracker.mark_downloaded("test_video")


class TestPlaylistArchiver:
    """Test cases for PlaylistArchiver class."""

    def test_init(self, config):
        """Test PlaylistArchiver initialization."""
        archiver = PlaylistArchiver(config)

        assert archiver.config == config
        assert archiver.downloader is not None
        assert archiver.metadata_generator is not None

    def test_get_playlist_info(self, config):
        """Test getting playlist info."""
        archiver = PlaylistArchiver(config)

        # Mock yt-dlp to return test data
        with patch("ytdl_archiver.core.archive.yt_dlp.YoutubeDL") as mock_ydl:
            mock_ydl_instance = Mock()
            mock_ydl.return_value = mock_ydl_instance
            mock_ydl_instance.extract_info.return_value = {
                "id": "test_playlist",
                "title": "Test",
            }

            result = archiver._get_playlist_info(
                "https://www.youtube.com/playlist?list=test"
            )

            assert result["id"] == "test_playlist"
            assert result["title"] == "Test"

    def test_get_playlist_info_error(self, config):
        """Test getting playlist info with error."""
        archiver = PlaylistArchiver(config)

        # Mock yt-dlp to raise exception
        with patch("ytdl_archiver.core.archive.yt_dlp.YoutubeDL") as mock_ydl:
            mock_ydl_instance = Mock()
            mock_ydl.return_value = mock_ydl_instance
            mock_ydl_instance.extract_info.side_effect = Exception("Network error")

            result = archiver._get_playlist_info(
                "https://www.youtube.com/playlist?list=test"
            )

            assert result is None

    @patch("ytdl_archiver.core.downloader.YouTubeDownloader")
    def test_process_playlist_basic(
        self, mock_downloader, config, temp_dir, sample_playlist_data
    ):
        """Test basic playlist processing."""
        # Setup mocks
        mock_downloader_instance = Mock()
        mock_downloader.return_value = mock_downloader_instance
        mock_downloader_instance.download_video_with_config.return_value = (
            sample_playlist_data["entries"][0]
        )

        # Create archiver
        archiver = PlaylistArchiver(config)

        # Mock the _get_playlist_info method
        with patch.object(
            archiver, "_get_playlist_info", return_value=sample_playlist_data
        ):
            # Process playlist
            archiver.process_playlist(
                "PLOgg6_QCO8CeFd55aR1RgzSQOOWhR12uj", "TestPlaylist"
            )

        # Verify downloader was called for each video
        assert mock_downloader_instance.download_video_with_config.call_count == 3

    def test_process_playlist_no_entries(self, config):
        """Test processing playlist with no entries."""
        archiver = PlaylistArchiver(config)

        # Mock empty playlist
        empty_playlist = {"id": "empty", "entries": []}

        with patch.object(archiver, "_get_playlist_info", return_value=empty_playlist):
            # Should not raise exception
            archiver.process_playlist("empty", "EmptyPlaylist")

    def test_process_playlist_none_entries(self, config):
        """Test processing playlist with None entries."""
        archiver = PlaylistArchiver(config)

        # Mock playlist with None entries
        playlist_with_none = {
            "id": "test",
            "entries": [
                {"id": "video1", "title": "Video 1"},
                None,  # Deleted video
                {"id": "video2", "title": "Video 2"},
            ],
        }

        with patch.object(
            archiver, "_get_playlist_info", return_value=playlist_with_none
        ):
            # Should not raise exception
            archiver.process_playlist("test", "TestPlaylist")
