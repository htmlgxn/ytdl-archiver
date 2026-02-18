"""Tests for YouTube downloader functionality."""

from unittest.mock import Mock, patch, MagicMock

import pytest

from ytdl_archiver.core.downloader import (
    ProgressCallback,
    YouTubeDownloader,
    suppress_output,
)


class TestYouTubeDownloader:
    """Test cases for YouTubeDownloader class."""

    def test_init(self, config):
        """Test YouTubeDownloader initialization."""
        downloader = YouTubeDownloader(config)

        assert downloader.config == config
        assert downloader.ydl_opts is not None
        assert "format" in downloader.ydl_opts
        assert "http_headers" in downloader.ydl_opts

    def test_build_ydl_options_default(self, config):
        """Test building yt-dlp options with defaults."""
        downloader = YouTubeDownloader(config)
        opts = downloader.ydl_opts

        # Check that global config values are used
        assert opts["format"] == config.get("download.format")
        assert opts["writesubtitles"] == config.get("download.write_subtitles")
        assert opts["writethumbnail"] == config.get("download.write_thumbnail")

    def test_build_ydl_options_with_playlist_config(self, config):
        """Test building yt-dlp options with playlist overrides."""
        downloader = YouTubeDownloader(config)

        playlist_config = {
            "format": "best[height<=480]",
            "writesubtitles": False,
            "writethumbnail": True,
        }

        opts = downloader._build_ydl_options(playlist_config)

        # Check that playlist config overrides are used
        assert opts["format"] == "best[height<=480]"
        assert opts["writesubtitles"] is False
        assert opts["writethumbnail"] is True

    def test_build_ydl_options_accepts_alias_playlist_keys(self, config):
        """Test playlist overrides accept config-style key aliases."""
        downloader = YouTubeDownloader(config)

        playlist_config = {
            "write_subtitles": False,
            "subtitle_languages": ["en", "es"],
            "write_thumbnail": False,
        }

        opts = downloader._build_ydl_options(playlist_config)

        assert opts["writesubtitles"] is False
        assert opts["subtitleslangs"] == ["en", "es"]
        assert opts["writethumbnail"] is False

    @patch("ytdl_archiver.core.downloader.yt_dlp.YoutubeDL")
    def test_extract_metadata_success(self, mock_ydl, config, mock_video_info):
        """Test successful metadata extraction."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value.__enter__ = Mock(return_value=mock_ydl_instance)
        mock_ydl.return_value.__exit__ = Mock(return_value=False)
        mock_ydl_instance.extract_info.return_value = mock_video_info

        downloader = YouTubeDownloader(config)

        result = downloader.get_metadata("https://www.youtube.com/watch?v=test_video")

        assert result == mock_video_info

    @patch("ytdl_archiver.core.downloader.yt_dlp.YoutubeDL")
    def test_extract_metadata_error(self, mock_ydl, config):
        """Test metadata extraction with error."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value.__enter__ = Mock(return_value=mock_ydl_instance)
        mock_ydl.return_value.__exit__ = Mock(return_value=False)
        mock_ydl_instance.extract_info.side_effect = Exception("Network error")

        downloader = YouTubeDownloader(config)

        result = downloader.get_metadata("https://www.youtube.com/watch?v=test_video")

        assert result is None

    @patch("ytdl_archiver.core.downloader.yt_dlp.YoutubeDL")
    def test_download_video_success(self, mock_ydl, config, temp_dir, mock_video_info):
        """Test successful video download."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value.__enter__ = Mock(return_value=mock_ydl_instance)
        mock_ydl.return_value.__exit__ = Mock(return_value=False)
        mock_ydl_instance.extract_info.return_value = mock_video_info

        downloader = YouTubeDownloader(config)

        output_template = str(temp_dir / "test.%(ext)s")
        result = downloader.download_video(
            "https://www.youtube.com/watch?v=test_video",
            output_template,
            temp_dir,
            "test_video",
        )

        assert result is not None
        assert result == mock_video_info

    @patch("ytdl_archiver.core.downloader.yt_dlp.YoutubeDL")
    def test_download_video_failure(self, mock_ydl, config, temp_dir):
        """Test video download failure."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value.__enter__ = Mock(return_value=mock_ydl_instance)
        mock_ydl.return_value.__exit__ = Mock(return_value=False)
        mock_ydl_instance.extract_info.side_effect = Exception("Download failed")

        downloader = YouTubeDownloader(config)

        output_template = str(temp_dir / "test.%(ext)s")
        with pytest.raises(Exception):
            downloader.download_video(
                "https://www.youtube.com/watch?v=test_video",
                output_template,
                temp_dir,
                "test_video",
            )

    @patch("ytdl_archiver.core.downloader.yt_dlp.YoutubeDL")
    def test_download_video_with_config(
        self, mock_ydl, config, temp_dir, mock_video_info
    ):
        """Test video download with custom config."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value.__enter__ = Mock(return_value=mock_ydl_instance)
        mock_ydl.return_value.__exit__ = Mock(return_value=False)
        mock_ydl_instance.extract_info.return_value = mock_video_info

        downloader = YouTubeDownloader(config)

        playlist_config = {"format": "best[height<=480]", "writesubtitles": False}

        result = downloader.download_video_with_config(
            "https://www.youtube.com/watch?v=test_video", temp_dir, playlist_config
        )

        assert result is not None

    def test_download_video_with_config_falls_back_when_metadata_fails(
        self, config, temp_dir, mocker
    ):
        """Test direct download fallback when metadata prefetch fails."""
        config._config["archive"]["delay_between_videos"] = 0
        downloader = YouTubeDownloader(config)

        mocker.patch.object(downloader, "get_metadata", return_value=None)
        direct_download = mocker.patch.object(
            downloader, "download_video", return_value={"id": "test_video"}
        )

        result = downloader.download_video_with_config(
            "https://www.youtube.com/watch?v=test_video",
            temp_dir,
            None,
        )

        assert result == {"id": "test_video"}
        assert direct_download.call_count == 1

        _, output_template, _, filename = direct_download.call_args.args
        assert "video-test_video_unknown-channel" in output_template
        assert filename == "video-test_video_unknown-channel"

    def test_runtime_options_include_cookiefile_when_configured(self, config, temp_dir):
        """Test runtime yt-dlp options include cookiefile when available."""
        cookie_file = temp_dir / "cookies.txt"
        cookie_file.write_text("# Netscape HTTP Cookie File\n")
        config._config["http"]["cookie_file"] = str(cookie_file)

        downloader = YouTubeDownloader(config)
        opts = downloader._build_runtime_ydl_options()

        assert opts["cookiefile"] == str(cookie_file)

    def test_is_short_vertical_video(self, config, mock_short_video_info):
        """Test short video detection for vertical aspect ratio."""
        from ytdl_archiver.core.utils import is_short

        # Vertical video should be detected as short
        assert is_short(mock_short_video_info) is True

    def test_is_short_horizontal_video(self, config, mock_video_info):
        """Test short video detection for horizontal aspect ratio."""
        from ytdl_archiver.core.utils import is_short

        # Horizontal video should not be detected as short
        assert is_short(mock_video_info) is False

    def test_is_short_no_dimensions(self, config):
        """Test short video detection with missing dimensions."""
        from ytdl_archiver.core.utils import is_short

        # Video without dimensions should not be detected as short
        video_info_no_dims = {"id": "test", "width": None, "height": None}
        assert is_short(video_info_no_dims) is False

    def test_is_short_custom_threshold(self, config, mock_video_info):
        """Test short video detection with custom threshold."""
        from ytdl_archiver.core.utils import is_short

        video_info = {
            "width": 800,
            "height": 1200,  # aspect ratio = 0.67
        }

        # Default threshold (0.7) should detect as short
        assert is_short(video_info) is True

        # With custom threshold of 0.5, should not detect as short
        assert is_short(video_info, aspect_ratio_threshold=0.5) is False

    def test_user_agent_configuration(self, config):
        """Test user agent is properly configured."""
        downloader = YouTubeDownloader(config)

        opts = downloader.ydl_opts
        assert "http_headers" in opts
        assert "User-Agent" in opts["http_headers"]
        assert opts["http_headers"]["User-Agent"] == config.get("http.user_agent")

    def test_timeout_configuration(self, config):
        """Test timeout values are properly configured."""
        downloader = YouTubeDownloader(config)

        opts = downloader.ydl_opts
        assert "socket_timeout" in opts
        assert "connect_timeout" in opts
        assert opts["socket_timeout"] == config.get("http.request_timeout")
        assert opts["connect_timeout"] == config.get("http.connect_timeout")

    def test_suppress_output_context_manager(self):
        """Test suppress_output context manager."""
        import sys
        from io import StringIO

        # Capture stdout/stderr before
        old_stdout = sys.stdout
        old_stderr = sys.stderr

        with suppress_output():
            # Inside context, stdout/stderr should be redirected to devnull
            pass

        # After context, should be restored
        assert sys.stdout is old_stdout
        assert sys.stderr is old_stderr


class TestProgressCallback:
    """Test cases for progress callback completion formatting."""

    def test_finished_events_emit_main_and_sidecar_once(self):
        """Test one main completion plus deduplicated sidecar completion."""
        formatter = Mock()
        formatter.video_complete.return_value = "main-line"
        formatter.artifact_complete.return_value = "sidecar-line"

        callback = ProgressCallback(formatter)

        with patch("ytdl_archiver.core.downloader.emit_rendered") as emit:
            callback(
                {
                    "status": "downloading",
                    "info_dict": {"title": "Sample Video"},
                    "_percent_str": "10%",
                    "_speed_str": "1MiB/s",
                    "_eta_str": "00:10",
                }
            )
            callback(
                {
                    "status": "finished",
                    "filename": "/tmp/sample-video.mp4",
                    "total_bytes_str": "100MiB",
                    "info_dict": {
                        "title": "Sample Video",
                        "height": 1080,
                        "width": 1920,
                        "ext": "mp4",
                    },
                }
            )
            callback(
                {
                    "status": "finished",
                    "filename": "/tmp/sample-video.en.srt",
                    "info_dict": {"title": "Sample Video", "ext": "srt"},
                }
            )
            callback(
                {
                    "status": "finished",
                    "filename": "/tmp/sample-video.es.srt",
                    "info_dict": {"title": "Sample Video", "ext": "srt"},
                }
            )

        formatter.video_complete.assert_called_once_with(
            "Sample Video", "1080p", ".mp4", "100mb"
        )
        formatter.artifact_complete.assert_called_once_with("Sample Video", ".srt")
        emitted = [call.args[0] for call in emit.call_args_list]
        assert emitted.count("main-line") == 1
        assert emitted.count("sidecar-line") == 1

    def test_extension_falls_back_to_info_dict_and_normalizes(self):
        """Test extension extraction normalizes uppercase ext without filename."""
        formatter = Mock()
        formatter.video_complete.return_value = "main-line"
        formatter.artifact_complete.return_value = "sidecar-line"

        callback = ProgressCallback(formatter)

        with patch("ytdl_archiver.core.downloader.emit_rendered"):
            callback(
                {
                    "status": "finished",
                    "info_dict": {
                        "title": "No Filename Video",
                        "height": 720,
                        "width": 1280,
                        "ext": "MP4",
                    },
                    "_total_bytes_str": "55MiB",
                }
            )

        formatter.video_complete.assert_called_once_with(
            "No Filename Video", "720p", ".mp4", "55mb"
        )

    def test_size_format_uses_decimals_only_for_gb(self):
        """Test gb uses decimals while mb is rounded to whole numbers."""
        formatter = Mock()
        formatter.video_complete.return_value = "main-line"
        callback = ProgressCallback(formatter)

        with patch("ytdl_archiver.core.downloader.emit_rendered"):
            callback(
                {
                    "status": "finished",
                    "filename": "/tmp/big-video.mp4",
                    "info_dict": {"title": "Big Video", "ext": "mp4"},
                    "total_bytes": int(1.25 * 1024**3),
                }
            )

        formatter.video_complete.assert_called_once_with(
            "Big Video", "", ".mp4", "1.25gb"
        )


class TestSuppressOutput:
    """Test cases for suppress_output context manager."""

    def test_suppress_output_captures_output(self):
        """Test that suppress_output captures stdout and stderr."""
        import sys
        from io import StringIO

        with suppress_output():
            # Print should not raise
            print("test")

    def test_suppress_output_restores_streams(self):
        """Test that streams are restored after context."""
        import sys

        original_stdout = sys.stdout
        original_stderr = sys.stderr

        with suppress_output():
            pass

        assert sys.stdout is original_stdout
        assert sys.stderr is original_stderr
