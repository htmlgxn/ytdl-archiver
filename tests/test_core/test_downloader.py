"""Tests for YouTube downloader functionality."""

from unittest.mock import Mock, patch


from ytdl_archiver.core.downloader import YouTubeDownloader


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

    @patch("ytdl_archiver.core.downloader.yt_dlp.YoutubeDL")
    def test_extract_metadata_success(self, mock_ydl, config, mock_video_info):
        """Test successful metadata extraction."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.return_value = mock_video_info

        downloader = YouTubeDownloader(config)

        result = downloader.extract_metadata(
            "https://www.youtube.com/watch?v=test_video"
        )

        assert result == mock_video_info
        mock_ydl_instance.extract_info.assert_called_once()

    @patch("ytdl_archiver.core.downloader.yt_dlp.YoutubeDL")
    def test_extract_metadata_error(self, mock_ydl, config):
        """Test metadata extraction with error."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.side_effect = Exception("Network error")

        downloader = YouTubeDownloader(config)

        result = downloader.extract_metadata(
            "https://www.youtube.com/watch?v=test_video"
        )

        assert result is None

    @patch("ytdl_archiver.core.downloader.yt_dlp.YoutubeDL")
    def test_download_video_success(self, mock_ydl, config, temp_dir, mock_video_info):
        """Test successful video download."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.return_value = mock_video_info

        downloader = YouTubeDownloader(config)

        result = downloader.download_video(
            "https://www.youtube.com/watch?v=test_video", temp_dir
        )

        assert result is True
        mock_ydl_instance.extract_info.assert_called_once()

    @patch("ytdl_archiver.core.downloader.yt_dlp.YoutubeDL")
    def test_download_video_failure(self, mock_ydl, config, temp_dir):
        """Test video download failure."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.side_effect = Exception("Download failed")

        downloader = YouTubeDownloader(config)

        result = downloader.download_video(
            "https://www.youtube.com/watch?v=test_video", temp_dir
        )

        assert result is False

    @patch("ytdl_archiver.core.downloader.yt_dlp.YoutubeDL")
    def test_download_video_with_config(
        self, mock_ydl, config, temp_dir, mock_video_info
    ):
        """Test video download with custom config."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.return_value = mock_video_info

        downloader = YouTubeDownloader(config)

        playlist_config = {"format": "best[height<=480]", "writesubtitles": False}

        result = downloader.download_video_with_config(
            "https://www.youtube.com/watch?v=test_video", temp_dir, playlist_config
        )

        assert result is True
        # Verify that custom config was used
        mock_ydl.assert_called_once()
        call_kwargs = mock_ydl.call_args[1]
        assert call_kwargs["format"] == "best[height<=480]"
        assert call_kwargs["writesubtitles"] is False

    @patch("ytdl_archiver.core.downloader.yt_dlp.YoutubeDL")
    def test_get_playlist_info(self, mock_ydl, config, sample_playlist_data):
        """Test getting playlist information."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.return_value = sample_playlist_data

        downloader = YouTubeDownloader(config)

        result = downloader.get_playlist_info(
            "https://www.youtube.com/playlist?list=test_playlist"
        )

        assert result == sample_playlist_data
        mock_ydl_instance.extract_info.assert_called_once()

    @patch("ytdl_archiver.core.downloader.yt_dlp.YoutubeDL")
    def test_get_playlist_info_error(self, mock_ydl, config):
        """Test getting playlist info with error."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.side_effect = Exception("Network error")

        downloader = YouTubeDownloader(config)

        result = downloader.get_playlist_info(
            "https://www.youtube.com/playlist?list=test_playlist"
        )

        assert result is None

    def test_is_short_vertical_video(self, config, mock_short_video_info):
        """Test short video detection for vertical aspect ratio."""
        downloader = YouTubeDownloader(config)

        # Vertical video should be detected as short
        assert downloader._is_short(mock_short_video_info) is True

    def test_is_short_horizontal_video(self, config, mock_video_info):
        """Test short video detection for horizontal aspect ratio."""
        downloader = YouTubeDownloader(config)

        # Horizontal video should not be detected as short
        assert downloader._is_short(mock_video_info) is False

    def test_is_short_no_dimensions(self, config):
        """Test short video detection with missing dimensions."""
        downloader = YouTubeDownloader(config)

        # Video without dimensions should not be detected as short
        video_info_no_dims = {"id": "test", "width": None, "height": None}
        assert downloader._is_short(video_info_no_dims) is False

    def test_is_short_custom_threshold(self, config, mock_video_info):
        """Test short video detection with custom threshold."""
        # Set custom threshold
        config._config["shorts"]["aspect_ratio_threshold"] = 2.0

        downloader = YouTubeDownloader(config)

        # With high threshold, horizontal video should be detected as short
        assert downloader._is_short(mock_video_info) is True

    def test_get_output_path_regular_video(self, config, temp_dir, mock_video_info):
        """Test getting output path for regular video."""
        downloader = YouTubeDownloader(config)

        output_path = downloader._get_output_path(mock_video_info, temp_dir, {})

        expected_filename = f"{mock_video_info['id']}.mp4"
        assert output_path == temp_dir / expected_filename

    def test_get_output_path_short_video(self, config, temp_dir, mock_short_video_info):
        """Test getting output path for short video."""
        downloader = YouTubeDownloader(config)

        output_path = downloader._get_output_path(mock_short_video_info, temp_dir, {})

        # Should be in shorts subdirectory
        shorts_dir = temp_dir / "YouTube Shorts"
        expected_filename = f"{mock_short_video_info['id']}.mp4"
        assert output_path == shorts_dir / expected_filename

    def test_get_output_path_custom_format(self, config, temp_dir, mock_video_info):
        """Test getting output path with custom format."""
        downloader = YouTubeDownloader(config)

        playlist_config = {"merge_output_format": "webm"}

        output_path = downloader._get_output_path(
            mock_video_info, temp_dir, playlist_config
        )

        expected_filename = f"{mock_video_info['id']}.webm"
        assert output_path == temp_dir / expected_filename

    def test_retry_logic(self, config):
        """Test that retry logic is configured."""
        downloader = YouTubeDownloader(config)

        # Check that retry decorator is applied (indirectly through method existence)
        assert hasattr(downloader.extract_metadata, "__wrapped__")
        assert hasattr(downloader.download_video, "__wrapped__")

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
