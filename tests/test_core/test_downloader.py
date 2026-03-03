"""Tests for YouTube downloader functionality."""

import json
import threading
from unittest.mock import Mock, patch

import pytest
import yt_dlp

from ytdl_archiver.core.downloader import (
    ProgressCallback,
    YouTubeDownloader,
    suppress_output,
)
from ytdl_archiver.exceptions import DownloadError
from ytdl_archiver.output import ProgressFormatter, VerboseFormatter


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
        assert opts["embedsubtitles"] == config.get("download.embed_subtitles")
        assert opts["writeinfojson"] == config.get("download.write_info_json")
        assert opts["subtitlesformat"] == config.get("download.subtitle_format")
        postprocessor_keys = [pp["key"] for pp in opts["postprocessors"]]
        assert "FFmpegSubtitlesConvertor" in postprocessor_keys
        assert "FFmpegEmbedSubtitle" in postprocessor_keys
        assert "FFmpegVideoRemuxer" in postprocessor_keys
        embed_pp = next(
            pp for pp in opts["postprocessors"] if pp["key"] == "FFmpegEmbedSubtitle"
        )
        assert embed_pp["already_have_subtitle"] is True
        remux_pp = next(
            pp for pp in opts["postprocessors"] if pp["key"] == "FFmpegVideoRemuxer"
        )
        assert remux_pp["preferedformat"] == "mp4/mkv"
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
            "write_info_json": False,
            "write_subtitles": False,
            "embed_subtitles": False,
            "subtitle_languages": ["en", "es"],
            "write_thumbnail": False,
        }

        opts = downloader._build_ydl_options(playlist_config)

        assert opts["writeinfojson"] is False
        assert opts["writesubtitles"] is False
        assert opts["embedsubtitles"] is False
        assert opts["subtitleslangs"] == ["en", "es"]
        assert opts["writethumbnail"] is False

    def test_build_ydl_options_disables_embed_processor_when_configured(self, config):
        """Test subtitle embed postprocessor is omitted when disabled."""
        downloader = YouTubeDownloader(config)

        playlist_config = {
            "write_subtitles": True,
            "embed_subtitles": False,
            "convert_subtitles": "srt",
        }
        opts = downloader._build_ydl_options(playlist_config)
        postprocessor_keys = [pp["key"] for pp in opts["postprocessors"]]
        assert "FFmpegSubtitlesConvertor" in postprocessor_keys
        assert "FFmpegEmbedSubtitle" not in postprocessor_keys

    def test_resolve_strategy_prefers_mp4_when_available_at_max_resolution(self, config):
        """Test same-resolution candidates pick mp4 path before bitrate/fps tie-breaks."""
        downloader = YouTubeDownloader(config)
        metadata = {
            "formats": [
                {"height": 2160, "ext": "webm", "vcodec": "vp9", "fps": 60, "tbr": 15000},
                {"height": 2160, "ext": "mp4", "vcodec": "avc1", "fps": 30, "tbr": 9000},
            ]
        }

        overrides = downloader._resolve_download_strategy_overrides(metadata, {})

        assert "height=2160" in overrides["format"]
        assert "[ext=mp4]" in overrides["format"]
        assert overrides["remux_video"] == "mp4/mkv"

    def test_resolve_strategy_preserves_max_resolution_when_mp4_not_available(
        self, config
    ):
        """Test max resolution path stays selected when only lower-res mp4 exists."""
        downloader = YouTubeDownloader(config)
        metadata = {
            "formats": [
                {"height": 2160, "ext": "webm", "vcodec": "vp9", "fps": 60, "tbr": 15000},
                {"height": 1080, "ext": "mp4", "vcodec": "avc1", "fps": 30, "tbr": 5000},
            ]
        }

        overrides = downloader._resolve_download_strategy_overrides(metadata, {})

        assert "height=2160" in overrides["format"]
        assert "[ext=mp4]" not in overrides["format"]
        assert overrides["remux_video"] == "mp4/mkv"

    def test_force_mp4_policy_uses_mp4_selector_and_remux(self, config):
        """Test force_mp4 policy enforces mp4 selector/remux behavior."""
        downloader = YouTubeDownloader(config)
        metadata = {"formats": [{"height": 2160, "ext": "webm", "vcodec": "vp9"}]}

        overrides = downloader._resolve_download_strategy_overrides(
            metadata, {"container_policy": "force_mp4"}
        )

        assert "[ext=mp4]" in overrides["format"]
        assert overrides["remux_video"] == "mp4"

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
    def test_get_metadata_default_mode_emits_no_debug_output(
        self, mock_ydl, config, mock_video_info, capsys
    ):
        """Test default mode keeps metadata prefetch diagnostics suppressed."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value.__enter__ = Mock(return_value=mock_ydl_instance)
        mock_ydl.return_value.__exit__ = Mock(return_value=False)
        mock_ydl_instance.extract_info.return_value = mock_video_info

        downloader = YouTubeDownloader(
            config, formatter=ProgressFormatter(use_colors=False, show_progress=False)
        )
        downloader.get_metadata("https://www.youtube.com/watch?v=test_video")

        captured = capsys.readouterr()
        assert "Metadata prefetch" not in captured.out
        assert "DEBUG:" not in captured.out
        assert captured.err == ""

    @patch("ytdl_archiver.core.downloader.yt_dlp.YoutubeDL")
    def test_get_metadata_verbose_mode_emits_structured_debug(
        self, mock_ydl, config, mock_video_info, capsys
    ):
        """Test verbose mode emits structured metadata diagnostics."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value.__enter__ = Mock(return_value=mock_ydl_instance)
        mock_ydl.return_value.__exit__ = Mock(return_value=False)
        mock_ydl_instance.extract_info.return_value = mock_video_info

        config.set_logging_level("DEBUG")
        downloader = YouTubeDownloader(config, formatter=VerboseFormatter(use_colors=False))
        downloader.get_metadata("https://www.youtube.com/watch?v=test_video")

        captured = capsys.readouterr()
        assert "Debug:" in captured.out
        assert "Metadata prefetch started" in captured.out
        assert "Metadata prefetch succeeded" in captured.out

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
    def test_get_metadata_failure_debug_only_in_verbose(self, mock_ydl, config, capsys):
        """Test metadata fallback diagnostics are shown only in verbose mode."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value.__enter__ = Mock(return_value=mock_ydl_instance)
        mock_ydl.return_value.__exit__ = Mock(return_value=False)
        mock_ydl_instance.extract_info.side_effect = Exception("Network error")

        default_downloader = YouTubeDownloader(
            config, formatter=ProgressFormatter(use_colors=False, show_progress=False)
        )
        default_downloader.get_metadata("https://www.youtube.com/watch?v=test_video")
        default_captured = capsys.readouterr()
        assert "Metadata prefetch failed; falling back to direct download" not in (
            default_captured.out + default_captured.err
        )

        config.set_logging_level("DEBUG")
        verbose_downloader = YouTubeDownloader(
            config, formatter=VerboseFormatter(use_colors=False)
        )
        verbose_downloader.get_metadata("https://www.youtube.com/watch?v=test_video")
        verbose_captured = capsys.readouterr()
        assert "Metadata prefetch failed; falling back to direct download" in (
            verbose_captured.out
        )

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
        opts = mock_ydl.call_args.args[0]
        assert opts["outtmpl"]["subtitle"].endswith(".%(lang)s.%(ext)s")

    @patch("ytdl_archiver.core.downloader.yt_dlp.YoutubeDL")
    def test_download_video_failure(self, mock_ydl, config, temp_dir):
        """Test video download failure."""
        mock_ydl_instance = Mock()
        mock_ydl.return_value.__enter__ = Mock(return_value=mock_ydl_instance)
        mock_ydl.return_value.__exit__ = Mock(return_value=False)
        mock_ydl_instance.extract_info.side_effect = Exception("Download failed")

        downloader = YouTubeDownloader(config)

        output_template = str(temp_dir / "test.%(ext)s")
        with pytest.raises(DownloadError):
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
            downloader,
            "_download_with_effective_config",
            return_value={"id": "test_video"},
        )
        mocker.patch.object(downloader, "_emit_post_download_generated_lines")
        mocker.patch.object(downloader, "_write_max_metadata_sidecar")

        result = downloader.download_video_with_config(
            "https://www.youtube.com/watch?v=test_video",
            temp_dir,
            None,
        )

        assert result == {"id": "test_video"}
        assert direct_download.call_count == 1

        _, output_template, _, filename, _ = direct_download.call_args.args
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

    def test_runtime_options_write_info_json_enabled_by_default(self, config):
        """Test runtime yt-dlp options enable info JSON sidecars by default."""
        downloader = YouTubeDownloader(config)
        opts = downloader._build_runtime_ydl_options()

        assert opts["writeinfojson"] is True

    def test_download_video_with_config_writes_max_metadata_json_sidecar(
        self, config, temp_dir, mocker
    ):
        """Test downloader writes project-owned max metadata JSON sidecar."""
        config._config["archive"]["delay_between_videos"] = 0
        downloader = YouTubeDownloader(config)
        video_url = "https://www.youtube.com/watch?v=test_video"
        metadata = {
            "id": "test_video",
            "title": "Test Video",
            "uploader": "Test Channel",
            "upload_date": "20240101",
        }
        filename = downloader._build_output_filename(metadata, video_url)

        mocker.patch.object(downloader, "get_metadata", return_value=metadata)
        mocker.patch.object(
            downloader,
            "_download_with_effective_config",
            return_value={
                "id": "test_video",
                "title": "Test Video",
                "extractor": "youtube",
                "webpage_url": video_url,
            },
        )
        mocker.patch.object(downloader, "_emit_post_download_generated_lines")

        downloader.download_video_with_config(video_url, temp_dir, {})

        metadata_path = temp_dir / f"{filename}.metadata.json"
        assert metadata_path.exists()
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert payload["video_url"] == video_url
        assert payload["extractor"] == "youtube"
        assert payload["metadata"]["id"] == "test_video"
        assert "generated_at" in payload

    def test_download_video_with_config_writes_metadata_sidecar_from_result_filepath(
        self, config, temp_dir, mocker
    ):
        """Test metadata sidecar path resolves from final result filepath."""
        config._config["archive"]["delay_between_videos"] = 0
        downloader = YouTubeDownloader(config)
        video_url = "https://www.youtube.com/watch?v=test_video"
        metadata = {
            "id": "test_video",
            "title": "Test Video",
            "uploader": "Test Channel",
            "upload_date": "20240101",
        }
        base_name = downloader._build_output_filename(metadata, video_url)
        final_mkv = temp_dir / "custom-final-name.mkv"
        final_mkv.write_bytes(b"video")

        mocker.patch.object(downloader, "get_metadata", return_value=metadata)
        mocker.patch.object(
            downloader,
            "_download_with_effective_config",
            return_value={
                "id": "test_video",
                "title": "Test Video",
                "extractor": "youtube",
                "requested_downloads": [{"filepath": str(final_mkv)}],
            },
        )
        mocker.patch.object(downloader, "_emit_post_download_generated_lines")

        downloader.download_video_with_config(video_url, temp_dir, {})

        assert not (temp_dir / f"{base_name}.metadata.json").exists()
        resolved_path = temp_dir / "custom-final-name.metadata.json"
        assert resolved_path.exists()

    def test_download_video_with_config_writes_metadata_sidecar_with_canonical_stem_when_no_media(
        self, config, temp_dir, mocker
    ):
        """Test metadata sidecar falls back to canonical stem when media path is unavailable."""
        config._config["archive"]["delay_between_videos"] = 0
        downloader = YouTubeDownloader(config)
        video_url = "https://www.youtube.com/watch?v=test_video"
        metadata = {
            "id": "test_video",
            "title": "Test Video",
            "uploader": "Test Channel",
            "upload_date": "20240101",
        }
        filename = downloader._build_output_filename(metadata, video_url)
        (temp_dir / f"{filename}.info.json").write_text("{}", encoding="utf-8")

        mocker.patch.object(downloader, "get_metadata", return_value=metadata)
        mocker.patch.object(
            downloader,
            "_download_with_effective_config",
            return_value={"id": "test_video", "title": "Test Video"},
        )
        mocker.patch.object(downloader, "_emit_post_download_generated_lines")

        downloader.download_video_with_config(video_url, temp_dir, {})

        assert (temp_dir / f"{filename}.metadata.json").exists()

    def test_write_max_metadata_sidecar_emits_warning_on_failure(
        self, config, temp_dir, mocker
    ):
        """Test metadata sidecar failures surface a default-mode warning."""
        downloader = YouTubeDownloader(config, formatter=Mock())
        formatter = downloader.formatter
        assert formatter is not None
        formatter.warning.return_value = "warn-line"

        mocker.patch("pathlib.Path.write_text", side_effect=OSError("disk full"))

        with patch("ytdl_archiver.core.downloader.emit_formatter_message") as emit_msg:
            downloader._write_max_metadata_sidecar(
                base_path=temp_dir / "video",
                video_url="https://www.youtube.com/watch?v=test_video",
                download_result={"id": "test_video", "title": "Test Video"},
            )

        emit_msg.assert_any_call(
            formatter,
            "warning",
            "Metadata sidecar not written (OSError: disk full)",
        )

    def test_write_max_metadata_sidecar_handles_thread_lock_without_warning(
        self, config, temp_dir
    ):
        """Test sidecar writing tolerates non-pickleable lock objects."""
        downloader = YouTubeDownloader(config, formatter=Mock())
        formatter = downloader.formatter
        assert formatter is not None
        formatter.warning.return_value = "warn-line"

        result = {
            "id": "test_video",
            "title": "Test Video",
            "extractor": "youtube",
            "unsafe_lock": threading.Lock(),
        }
        base_path = temp_dir / "video"

        with patch("ytdl_archiver.core.downloader.emit_formatter_message") as emit_msg:
            downloader._write_max_metadata_sidecar(
                base_path=base_path,
                video_url="https://www.youtube.com/watch?v=test_video",
                download_result=result,
            )

        metadata_path = temp_dir / "video.metadata.json"
        assert metadata_path.exists()
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert payload["metadata"]["id"] == "test_video"
        warning_calls = [call for call in emit_msg.call_args_list if call.args[1] == "warning"]
        assert warning_calls == []

    def test_write_max_metadata_sidecar_uses_default_str_serialization_fallback(
        self, config, temp_dir, mocker
    ):
        """Test fallback serialization for non-JSON sanitized values."""
        downloader = YouTubeDownloader(config, formatter=Mock())
        formatter = downloader.formatter
        assert formatter is not None
        formatter.warning.return_value = "warn-line"

        class NonJsonValue:
            pass

        mocker.patch.object(
            yt_dlp.YoutubeDL,
            "sanitize_info",
            return_value={"id": "test_video", "non_json": NonJsonValue()},
        )
        base_path = temp_dir / "video-fallback"

        with patch("ytdl_archiver.core.downloader.emit_formatter_message") as emit_msg:
            downloader._write_max_metadata_sidecar(
                base_path=base_path,
                video_url="https://www.youtube.com/watch?v=test_video",
                download_result={"id": "test_video"},
            )

        metadata_path = temp_dir / "video-fallback.metadata.json"
        assert metadata_path.exists()
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert payload["metadata"]["id"] == "test_video"
        assert isinstance(payload["metadata"]["non_json"], str)
        warning_calls = [call for call in emit_msg.call_args_list if call.args[1] == "warning"]
        assert warning_calls == []

    def test_download_video_with_config_disables_max_metadata_json_when_configured(
        self, config, temp_dir, mocker
    ):
        """Test write_max_metadata_json disables only project metadata sidecar."""
        config._config["archive"]["delay_between_videos"] = 0
        config._config["download"]["write_max_metadata_json"] = False
        downloader = YouTubeDownloader(config)
        video_url = "https://www.youtube.com/watch?v=test_video"
        metadata = {
            "id": "test_video",
            "title": "Test Video",
            "uploader": "Test Channel",
            "upload_date": "20240101",
        }
        filename = downloader._build_output_filename(metadata, video_url)

        mocker.patch.object(downloader, "get_metadata", return_value=metadata)
        mocker.patch.object(
            downloader,
            "_download_with_effective_config",
            return_value={"id": "test_video", "title": "Test Video"},
        )
        mocker.patch.object(downloader, "_emit_post_download_generated_lines")

        downloader.download_video_with_config(video_url, temp_dir, {})

        assert not (temp_dir / f"{filename}.metadata.json").exists()
        opts = downloader._build_runtime_ydl_options()
        assert opts["writeinfojson"] is True

    def test_is_short_vertical_video(self, mock_short_video_info):
        """Test short video detection for vertical aspect ratio."""
        from ytdl_archiver.core.utils import is_short

        # Vertical video should be detected as short
        assert is_short(mock_short_video_info) is True

    def test_is_short_horizontal_video(self, mock_video_info):
        """Test short video detection for horizontal aspect ratio."""
        from ytdl_archiver.core.utils import is_short

        # Horizontal video should not be detected as short
        assert is_short(mock_video_info) is False

    def test_is_short_no_dimensions(self):
        """Test short video detection with missing dimensions."""
        from ytdl_archiver.core.utils import is_short

        # Video without dimensions should not be detected as short
        video_info_no_dims = {"id": "test", "width": None, "height": None}
        assert is_short(video_info_no_dims) is False

    def test_is_short_custom_threshold(self):
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
        """Test progress callback emits primary completion and defers subtitle lines."""
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
        formatter.artifact_complete.assert_not_called()
        emitted = [call.args[0] for call in emit.call_args_list]
        assert emitted.count("main-line") == 1
        assert emitted.count("sidecar-line") == 0

    def test_subtitle_event_before_video_suppresses_unknown_artifact_line(self):
        """Test subtitle completion is suppressed until a real title is known."""
        formatter = Mock()
        formatter.video_complete.return_value = "main-line"
        formatter.artifact_complete.return_value = "sidecar-line"
        callback = ProgressCallback(formatter)

        with patch("ytdl_archiver.core.downloader.emit_rendered"):
            callback(
                {
                    "status": "finished",
                    "filename": "/tmp/sample-video.en.vtt",
                    "info_dict": {"ext": "vtt"},
                }
            )

        formatter.video_complete.assert_not_called()
        formatter.artifact_complete.assert_not_called()

    def test_subtitle_event_reuses_current_video_title(self):
        """Test subtitle callback path does not emit sidecar completion lines."""
        formatter = Mock()
        formatter.video_complete.return_value = "main-line"
        formatter.artifact_complete.return_value = "sidecar-line"
        callback = ProgressCallback(formatter)

        with patch("ytdl_archiver.core.downloader.emit_rendered"):
            callback(
                {
                    "status": "downloading",
                    "info_dict": {"title": "Current Video"},
                    "_percent_str": "10%",
                    "_speed_str": "1MiB/s",
                    "_eta_str": "00:10",
                }
            )
            callback(
                {
                    "status": "finished",
                    "filename": "/tmp/current-video.en.vtt",
                    "info_dict": {"ext": "vtt"},
                }
            )

        formatter.artifact_complete.assert_not_called()

    def test_download_video_with_config_emits_subtitle_downloaded_converted_status(
        self, config, temp_dir, mocker
    ):
        """Test converted subtitle status is emitted from filesystem scan."""
        config._config["archive"]["delay_between_videos"] = 0
        downloader = YouTubeDownloader(config, formatter=Mock())
        formatter = downloader.formatter
        assert formatter is not None
        formatter.thumbnail_generated.return_value = "thumbnail-line"
        formatter.mp4_generated.return_value = "mp4-line"
        formatter.subtitle_downloaded.return_value = "subtitle-line"

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
        (temp_dir / f"{filename}.en.vtt").write_text("vtt")
        (temp_dir / f"{filename}.en.srt").write_text("srt")
        (temp_dir / f"{filename}.mp4").write_bytes(b"x")

        with patch("ytdl_archiver.core.downloader.emit_rendered") as emit:
            downloader.download_video_with_config(
                "https://www.youtube.com/watch?v=test_video",
                temp_dir,
                None,
            )

        formatter.subtitle_downloaded.assert_called_once_with(
            "Test Video", ".vtt -> .srt"
        )
        emitted = [call.args[0] for call in emit.call_args_list]
        assert "subtitle-line" in emitted

    def test_download_video_with_config_emits_subtitle_downloaded_native_srt_status(
        self, config, temp_dir, mocker
    ):
        """Test native .srt subtitle status is emitted from filesystem scan."""
        config._config["archive"]["delay_between_videos"] = 0
        downloader = YouTubeDownloader(config, formatter=Mock())
        formatter = downloader.formatter
        assert formatter is not None
        formatter.subtitle_downloaded.return_value = "subtitle-line"

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
        (temp_dir / f"{filename}.en.srt").write_text("srt")

        with patch("ytdl_archiver.core.downloader.emit_rendered"):
            downloader.download_video_with_config(
                "https://www.youtube.com/watch?v=test_video",
                temp_dir,
                None,
            )

        formatter.subtitle_downloaded.assert_called_once_with("Test Video", ".srt")

    def test_download_video_with_config_emits_subtitle_downloaded_fallback_status(
        self, config, temp_dir, mocker
    ):
        """Test fallback subtitle extension status is emitted from filesystem scan."""
        config._config["archive"]["delay_between_videos"] = 0
        downloader = YouTubeDownloader(config, formatter=Mock())
        formatter = downloader.formatter
        assert formatter is not None
        formatter.subtitle_downloaded.return_value = "subtitle-line"

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
        (temp_dir / f"{filename}.en.vtt").write_text("vtt")

        with patch("ytdl_archiver.core.downloader.emit_rendered"):
            downloader.download_video_with_config(
                "https://www.youtube.com/watch?v=test_video",
                temp_dir,
                None,
            )

        formatter.subtitle_downloaded.assert_called_once_with("Test Video", ".vtt")

    def test_download_video_with_config_dedupes_subtitle_lines_between_callback_and_scan(
        self, config, temp_dir, mocker
    ):
        """Test subtitle path dedupe suppresses duplicate per-file status lines."""
        config._config["archive"]["delay_between_videos"] = 0
        downloader = YouTubeDownloader(config, formatter=Mock())
        formatter = downloader.formatter
        assert formatter is not None
        formatter.subtitle_downloaded.return_value = "subtitle-line"

        metadata = {"title": "Test Video", "width": 1920, "height": 1080}
        filename = downloader._build_output_filename(
            metadata, "https://www.youtube.com/watch?v=test_video"
        )

        mocker.patch.object(downloader, "get_metadata", return_value=metadata)
        mocker.patch.object(
            downloader,
            "_download_with_effective_config",
            return_value={"title": "Test Video", "width": 1920, "height": 1080},
        )
        (temp_dir / f"{filename}.en.srt").write_text("srt")
        (temp_dir / f"{filename}.en.vtt").write_text("vtt")

        with patch("ytdl_archiver.core.downloader.emit_rendered"):
            downloader.download_video_with_config(
                "https://www.youtube.com/watch?v=test_video",
                temp_dir,
                None,
            )

        formatter.subtitle_downloaded.assert_called_once_with("Test Video", ".vtt -> .srt")

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
        formatter = downloader.formatter
        assert formatter is not None
        formatter.thumbnail_generated.return_value = "thumbnail-line"
        formatter.container_generated.return_value = "container-line"

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

        formatter.thumbnail_generated.assert_called_once_with("Test Video", ".jpg")
        formatter.container_generated.assert_called_once_with(
            "Test Video", ".mp4", "1080p", "5mb"
        )
        emitted = [call.args[0] for call in emit.call_args_list]
        assert "thumbnail-line" in emitted
        assert "container-line" in emitted

    def test_download_video_with_config_emits_mkv_generated_when_mp4_absent(
        self, config, temp_dir, mocker
    ):
        """Test generated line uses final mkv container when mp4 is absent."""
        config._config["archive"]["delay_between_videos"] = 0
        downloader = YouTubeDownloader(config, formatter=Mock())
        formatter = downloader.formatter
        assert formatter is not None
        formatter.thumbnail_generated.return_value = "thumbnail-line"
        formatter.container_generated.return_value = "container-line"

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
        (temp_dir / f"{filename}.mkv").write_bytes(b"x" * (6 * 1024 * 1024))

        with patch("ytdl_archiver.core.downloader.emit_rendered"):
            downloader.download_video_with_config(
                "https://www.youtube.com/watch?v=test_video",
                temp_dir,
                None,
            )

        formatter.thumbnail_generated.assert_called_once_with("Test Video", ".jpg")
        formatter.container_generated.assert_called_once_with(
            "Test Video", ".mkv", "1080p", "6mb"
        )


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
