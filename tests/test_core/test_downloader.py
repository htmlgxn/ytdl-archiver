"""Tests for YouTube downloader functionality."""

from unittest.mock import Mock, patch

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

    def test_build_output_filename_supports_title_only_token(self, config):
        """Test filename builder supports token subsets."""
        config._config["filename"]["tokens"] = ["title"]
        downloader = YouTubeDownloader(config)

        filename = downloader._build_output_filename(
            {"title": "My Great Video", "uploader": "Channel Name"},
            "https://www.youtube.com/watch?v=abc123",
        )

        assert filename == "my-great-video"

    def test_build_output_filename_supports_channel_only_token(self, config):
        """Test filename builder supports single channel token."""
        config._config["filename"]["tokens"] = ["channel"]
        downloader = YouTubeDownloader(config)

        filename = downloader._build_output_filename(
            {"title": "My Great Video", "uploader": "Channel Name"},
            "https://www.youtube.com/watch?v=abc123",
        )

        assert filename == "channel-name"

    def test_build_output_filename_supports_upload_date_token(self, config):
        """Test filename builder renders upload_date token."""
        config._config["filename"]["tokens"] = ["upload_date", "title"]
        downloader = YouTubeDownloader(config)

        filename = downloader._build_output_filename(
            {"title": "My Great Video", "upload_date": "20250131"},
            "https://www.youtube.com/watch?v=abc123",
        )

        assert filename == "2025-01-31_my-great-video"

    def test_build_output_filename_supports_compact_upload_date(self, config):
        """Test compact yyyymmdd upload_date formatting."""
        config._config["filename"]["tokens"] = ["upload_date", "title", "channel"]
        config._config["filename"]["date_format"] = "yyyymmdd"
        downloader = YouTubeDownloader(config)

        filename = downloader._build_output_filename(
            {
                "title": "Title With Hyphens",
                "uploader": "Channel Name",
                "upload_date": "20250131",
            },
            "https://www.youtube.com/watch?v=abc123",
        )

        assert filename == "20250131_title-with-hyphens_channel-name"

    def test_build_output_filename_supports_underscore_upload_date(self, config):
        """Test yyyy_mm_dd upload_date formatting."""
        config._config["filename"]["tokens"] = ["upload_date", "title"]
        config._config["filename"]["date_format"] = "yyyy_mm_dd"
        downloader = YouTubeDownloader(config)

        filename = downloader._build_output_filename(
            {"title": "My Great Video", "upload_date": "20250131"},
            "https://www.youtube.com/watch?v=abc123",
        )

        assert filename == "2025_01_31_my-great-video"

    def test_build_output_filename_supports_dot_upload_date(self, config):
        """Test yyyy.mm.dd upload_date formatting."""
        config._config["filename"]["tokens"] = ["upload_date", "title"]
        config._config["filename"]["date_format"] = "yyyy.mm.dd"
        downloader = YouTubeDownloader(config)

        filename = downloader._build_output_filename(
            {"title": "My Great Video", "upload_date": "20250131"},
            "https://www.youtube.com/watch?v=abc123",
        )

        assert filename == "2025.01.31_my-great-video"

    def test_build_output_filename_omits_missing_upload_date(self, config):
        """Test missing date token is omitted when configured."""
        config._config["filename"]["tokens"] = ["upload_date", "title"]
        config._config["filename"]["missing_token_behavior"] = "omit"
        downloader = YouTubeDownloader(config)

        filename = downloader._build_output_filename(
            {"title": "My Great Video"},
            "https://www.youtube.com/watch?v=abc123",
        )

        assert filename == "my-great-video"

    def test_build_output_filename_omits_malformed_upload_date(self, config):
        """Test malformed upload_date token is omitted."""
        config._config["filename"]["tokens"] = ["upload_date", "title"]
        config._config["filename"]["date_format"] = "yyyymmdd"
        downloader = YouTubeDownloader(config)

        filename = downloader._build_output_filename(
            {"title": "My Great Video", "upload_date": "2025-01-31"},
            "https://www.youtube.com/watch?v=abc123",
        )

        assert filename == "my-great-video"

    def test_build_output_filename_supports_all_tokens_ordered(self, config):
        """Test full token set with explicit ordering."""
        config._config["filename"]["tokens"] = [
            "title",
            "upload_date",
            "channel",
            "video_id",
        ]
        downloader = YouTubeDownloader(config)

        filename = downloader._build_output_filename(
            {
                "title": "My Great Video",
                "uploader": "Channel Name",
                "upload_date": "20250131",
            },
            "https://www.youtube.com/watch?v=abc123",
        )

        assert filename == "my-great-video_2025-01-31_channel-name_abc123"

    def test_build_output_filename_supports_custom_joiner(self, config):
        """Test configurable token joiner."""
        config._config["filename"]["token_joiner"] = "."
        downloader = YouTubeDownloader(config)

        filename = downloader._build_output_filename(
            {"title": "My Great Video", "uploader": "Channel Name"},
            "https://www.youtube.com/watch?v=abc123",
        )

        assert filename == "my-great-video.channel-name"

    def test_build_output_filename_supports_per_token_case_modes(self, config):
        """Test per-token case mapping."""
        config._config["filename"]["tokens"] = ["title", "channel", "video_id"]
        config._config["filename"]["case"]["title"] = "upper"
        config._config["filename"]["case"]["channel"] = "preserve"
        config._config["filename"]["case"]["video_id"] = "upper"
        downloader = YouTubeDownloader(config)

        filename = downloader._build_output_filename(
            {"title": "My Great Video", "uploader": "Channel Name"},
            "https://www.youtube.com/watch?v=abc123",
        )

        assert filename == "MY-GREAT-VIDEO_Channel-Name_ABC123"

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
        formatter.artifact_complete.assert_called_once_with("Sample Video", ".srt", "")
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

    def test_thumbnail_artifact_is_not_emitted_as_sidecar(self):
        """Test thumbnail artifacts are no longer emitted as Downloaded sidecars."""
        formatter = Mock()
        formatter.video_complete.return_value = "main-line"
        callback = ProgressCallback(formatter)

        with patch("ytdl_archiver.core.downloader.emit_rendered"):
            callback(
                {
                    "status": "finished",
                    "filename": "/tmp/video.mp4",
                    "info_dict": {"title": "Video", "ext": "mp4"},
                }
            )
            callback(
                {
                    "status": "finished",
                    "filename": "/tmp/video.jpg",
                    "info_dict": {"title": "Video", "ext": "jpg"},
                }
            )

        formatter.artifact_complete.assert_not_called()

    def test_intermediate_webm_artifact_is_ignored(self):
        """Test intermediate media artifacts are not emitted as sidecars."""
        formatter = Mock()
        formatter.video_complete.return_value = "main-line"
        callback = ProgressCallback(formatter)

        with patch("ytdl_archiver.core.downloader.emit_rendered"):
            callback(
                {
                    "status": "finished",
                    "filename": "/tmp/video.mp4",
                    "info_dict": {"title": "Video", "ext": "mp4"},
                }
            )
            callback(
                {
                    "status": "finished",
                    "filename": "/tmp/video.webm",
                    "info_dict": {"title": "Video", "ext": "webm"},
                }
            )

        formatter.artifact_complete.assert_not_called()

    def test_download_video_with_config_emits_generated_lines(
        self, config, temp_dir, mocker
    ):
        """Test post-download generated lines for thumbnail and final mp4."""
        config._config["archive"]["delay_between_videos"] = 0
        downloader = YouTubeDownloader(config, formatter=Mock())
        downloader.formatter.thumbnail_generated.return_value = "thumbnail-line"
        downloader.formatter.mp4_generated.return_value = "mp4-line"

        metadata = {"title": "Test Video", "width": 1920, "height": 1080}
        mocker.patch.object(downloader, "get_metadata", return_value=metadata)
        mocker.patch.object(
            downloader,
            "_download_with_effective_config",
            return_value={"title": "Test Video", "width": 1920, "height": 1080},
        )

        filename = downloader._build_output_filename(
            metadata, "https://www.youtube.com/watch?v=test_video"
        )
        (temp_dir / f"{filename}.jpg").write_bytes(b"thumb")
        (temp_dir / f"{filename}.mp4").write_bytes(b"x" * (5 * 1024 * 1024))

        with patch("ytdl_archiver.core.downloader.emit_rendered") as emit:
            downloader.download_video_with_config(
                "https://www.youtube.com/watch?v=test_video",
                temp_dir,
                None,
            )

        downloader.formatter.thumbnail_generated.assert_called_once_with(
            "Test Video", ".jpg"
        )
        downloader.formatter.mp4_generated.assert_called_once_with(
            "Test Video", "1080p", "5mb"
        )
        emitted = [call.args[0] for call in emit.call_args_list]
        assert "thumbnail-line" in emitted
        assert "mp4-line" in emitted

    def test_download_video_with_config_emits_mp4_generated_only_when_mp4_exists(
        self, config, temp_dir, mocker
    ):
        """Test mp4 generated line is skipped when no final mp4 exists."""
        config._config["archive"]["delay_between_videos"] = 0
        downloader = YouTubeDownloader(config, formatter=Mock())
        downloader.formatter.thumbnail_generated.return_value = "thumbnail-line"
        downloader.formatter.mp4_generated.return_value = "mp4-line"

        metadata = {"title": "Test Video", "width": 1920, "height": 1080}
        mocker.patch.object(downloader, "get_metadata", return_value=metadata)
        mocker.patch.object(
            downloader,
            "_download_with_effective_config",
            return_value={"title": "Test Video", "width": 1920, "height": 1080},
        )

        filename = downloader._build_output_filename(
            metadata, "https://www.youtube.com/watch?v=test_video"
        )
        (temp_dir / f"{filename}.jpg").write_bytes(b"thumb")

        with patch("ytdl_archiver.core.downloader.emit_rendered"):
            downloader.download_video_with_config(
                "https://www.youtube.com/watch?v=test_video",
                temp_dir,
                None,
            )

        downloader.formatter.thumbnail_generated.assert_called_once_with(
            "Test Video", ".jpg"
        )
        downloader.formatter.mp4_generated.assert_not_called()


class TestSuppressOutput:
    """Test cases for suppress_output context manager."""

    def test_suppress_output_captures_output(self):
        """Test that suppress_output captures stdout and stderr."""

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
