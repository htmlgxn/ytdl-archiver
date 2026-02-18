"""Tests for archive tracking functionality."""

from pathlib import Path
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
        with patch("yt_dlp.YoutubeDL") as mock_ydl:
            mock_ydl_instance = Mock()
            mock_ydl.return_value.__enter__ = Mock(return_value=mock_ydl_instance)
            mock_ydl.return_value.__exit__ = Mock(return_value=False)
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
        with patch("yt_dlp.YoutubeDL") as mock_ydl:
            mock_ydl_instance = Mock()
            mock_ydl.return_value.__enter__ = Mock(return_value=mock_ydl_instance)
            mock_ydl.return_value.__exit__ = Mock(return_value=False)
            mock_ydl_instance.extract_info.side_effect = Exception("Network error")

            result = archiver._get_playlist_info(
                "https://www.youtube.com/playlist?list=test"
            )

            assert result == {}

    def test_process_playlist_basic(
        self, config, temp_dir, sample_playlist_data, mocker
    ):
        """Test basic playlist processing."""
        archiver = PlaylistArchiver(config)

        # Mock the _get_playlist_info method
        mocker.patch.object(
            archiver, "_get_playlist_info", return_value=sample_playlist_data
        )

        # Mock the downloader to avoid actual downloads
        mocker.patch.object(
            archiver.downloader,
            "download_video_with_config",
            return_value=sample_playlist_data["entries"][0],
        )
        mocker.patch.object(config, "get_playlist_config", return_value={})

        # Process playlist - should not raise
        archiver.process_playlist("test_playlist", "TestPlaylist")

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
            with patch.object(config, "get_playlist_config", return_value={}):
            # Should not raise exception
                archiver.process_playlist("test", "TestPlaylist")

    def test_process_playlist_uses_clean_playlist_label(self, config, mocker):
        """Test playlist formatter input does not duplicate Processing prefix."""
        formatter = Mock()
        formatter.playlist_start.return_value = "playlist-start"
        formatter.warning.return_value = ""
        formatter.playlist_summary.return_value = ""
        archiver = PlaylistArchiver(config, formatter=formatter)

        mocker.patch.object(
            archiver,
            "_get_playlist_info",
            return_value={"entries": []},
        )

        archiver.process_playlist("playlist-id", "My Playlist")

        formatter.playlist_start.assert_called_once_with("My Playlist", 0)

    def test_run_formats_all_playlists_line(self, config, temp_dir, mocker):
        """Test run emits normalized all playlists processing line."""
        playlists_file = temp_dir / "playlists.toml"
        playlists_file.write_text("")
        formatter = Mock()
        formatter.playlist_start.return_value = "all-playlists"

        mocker.patch.object(config, "get_playlists_file", return_value=playlists_file)
        mocker.patch.object(
            config,
            "load_playlists",
            return_value=[{"id": "a", "path": "one"}, {"id": "b", "path": "two"}],
        )

        archiver = PlaylistArchiver(config, formatter=formatter)
        process_playlist = mocker.patch.object(archiver, "process_playlist")

        archiver.run()

        formatter.playlist_start.assert_called_once_with(
            "all playlists", 2, include_videos_label=False
        )
        assert process_playlist.call_count == 2

    def test_process_playlist_does_not_emit_duplicate_video_completion(
        self, config, temp_dir, mocker
    ):
        """Test archive layer only emits NFO sidecar line when created."""
        config._config["archive"]["base_directory"] = str(temp_dir)
        formatter = Mock()
        formatter.playlist_start.return_value = "playlist-start"
        formatter.playlist_summary.return_value = "playlist-summary"
        formatter.warning.return_value = ""
        formatter.artifact_complete.return_value = "nfo-sidecar"

        archiver = PlaylistArchiver(config, formatter=formatter)

        mocker.patch.object(
            archiver,
            "_get_playlist_info",
            return_value={"entries": [{"id": "video1", "title": "Video 1"}]},
        )
        mocker.patch.object(
            archiver.downloader,
            "download_video_with_config",
            return_value={"title": "Video 1"},
        )
        mocker.patch.object(archiver, "_generate_nfo_if_needed", return_value=True)
        mocker.patch.object(config, "get_playlist_config", return_value={})

        archiver.process_playlist("playlist-id", "PlaylistPath")

        formatter.artifact_complete.assert_called_once_with("Video 1", ".nfo")
        formatter.video_complete.assert_not_called()

    def test_run_refreshes_cookies_before_start_and_each_playlist(
        self, config, temp_dir, mocker
    ):
        """Test cookie refresh runs at startup and per playlist."""
        config._config["archive"]["delay_between_playlists"] = 0
        playlists_file = temp_dir / "dummy.toml"
        playlists_file.write_text("")
        mocker.patch.object(config, "get_playlists_file", return_value=playlists_file)
        mocker.patch.object(
            config,
            "load_playlists",
            return_value=[
                {"id": "a", "path": "one"},
                {"id": "b", "path": "two"},
            ],
        )
        mocker.patch.object(
            config,
            "get_cookie_file_target_path",
            return_value=Path("/tmp/test-cookies.txt"),
        )

        cookie_refresher = Mock()
        archiver = PlaylistArchiver(
            config,
            cookie_refresher=cookie_refresher,
            cookie_browser="firefox",
        )
        process_playlist = mocker.patch.object(archiver, "process_playlist")

        archiver.run()

        assert cookie_refresher.refresh_to_file.call_count == 3
        assert process_playlist.call_count == 2

    def test_run_cookie_refresh_failure_aborts_remaining_playlists(
        self, config, temp_dir, mocker
    ):
        """Test failure before a playlist aborts processing."""
        config._config["archive"]["delay_between_playlists"] = 0
        playlists_file = temp_dir / "dummy.toml"
        playlists_file.write_text("")
        mocker.patch.object(config, "get_playlists_file", return_value=playlists_file)
        mocker.patch.object(
            config,
            "load_playlists",
            return_value=[
                {"id": "a", "path": "one"},
                {"id": "b", "path": "two"},
            ],
        )
        mocker.patch.object(
            config,
            "get_cookie_file_target_path",
            return_value=Path("/tmp/test-cookies.txt"),
        )

        cookie_refresher = Mock()
        cookie_refresher.refresh_to_file.side_effect = [
            None,
            None,
            RuntimeError("boom"),
        ]
        archiver = PlaylistArchiver(
            config,
            cookie_refresher=cookie_refresher,
            cookie_browser="firefox",
        )
        process_playlist = mocker.patch.object(archiver, "process_playlist")

        with pytest.raises(ArchiveError, match="Cookie refresh failed"):
            archiver.run()

        assert process_playlist.call_count == 1
