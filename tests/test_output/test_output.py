"""Tests for output formatters."""

from unittest.mock import patch

from ytdl_archiver.output import (
    Colors,
    OutputMode,
    ProgressFormatter,
    QuietFormatter,
    Symbols,
    VerboseFormatter,
    detect_output_mode,
    get_formatter,
    should_use_colors,
)


class TestColors:
    """Test cases for Colors class."""

    def test_colors_initialized(self):
        """Test Colors class is initialized."""
        # Just check that the class can be accessed
        assert hasattr(Colors, "GREEN")
        assert hasattr(Colors, "RED")
        assert hasattr(Colors, "RESET")

    def test_colors_strings(self):
        """Test color strings are defined."""
        # Check they're strings
        assert isinstance(Colors.GREEN, str)
        assert isinstance(Colors.RESET, str)


class TestSymbols:
    """Test cases for Symbols class."""

    def test_symbols_initialized(self):
        """Test Symbols class is initialized."""
        assert hasattr(Symbols, "SUCCESS")
        assert hasattr(Symbols, "ERROR")
        assert hasattr(Symbols, "PROGRESS")

    def test_symbols_strings(self):
        """Test symbol strings are defined."""
        assert isinstance(Symbols.SUCCESS, str)
        assert isinstance(Symbols.ERROR, str)


class TestProgressFormatter:
    """Test cases for ProgressFormatter class."""

    def test_init(self):
        """Test ProgressFormatter initialization."""
        formatter = ProgressFormatter(use_colors=True, show_progress=True)
        assert formatter.use_colors is True
        assert formatter.show_progress is True

    def test_init_no_colors(self):
        """Test ProgressFormatter initialization without colors."""
        formatter = ProgressFormatter(use_colors=False, show_progress=False)
        assert formatter.use_colors is False
        assert formatter.show_progress is False

    def test_header(self):
        """Test header output."""
        formatter = ProgressFormatter(use_colors=False)
        result = formatter.header("1.0.0")
        assert "ytdl-archiver" in result
        assert "1.0.0" in result

    def test_playlist_start(self):
        """Test playlist start output."""
        formatter = ProgressFormatter(use_colors=False)
        result = formatter.playlist_start("Test Playlist", 10)
        assert "Test Playlist" in result
        assert "(10 videos)" in result

    def test_playlist_start_without_videos_suffix(self):
        """Test playlist start output without videos suffix."""
        formatter = ProgressFormatter(use_colors=False)
        result = formatter.playlist_start(
            "all playlists", 5, include_videos_label=False
        )
        assert "all playlists" in result
        assert "(5)" in result
        assert "videos" not in result

    def test_archive_directory(self):
        """Test archive directory output."""
        formatter = ProgressFormatter(use_colors=False)
        result = formatter.archive_directory("/tmp/archive")
        assert "Archive directory:" in result
        assert "/tmp/archive" in result

    def test_video_progress(self):
        """Test video progress output."""
        formatter = ProgressFormatter(use_colors=False, show_progress=True)
        result = formatter.video_progress(
            "Test Video", {"percent": "50%", "speed": "1MB/s", "eta": "10s"}
        )
        assert "Test Video" in result
        assert "50%" in result

    def test_video_progress_invalid_percent(self):
        """Test video progress handles invalid percent values."""
        formatter = ProgressFormatter(use_colors=False, show_progress=True)
        result = formatter.video_progress(
            "Test Video", {"percent": None, "speed": "1MB/s", "eta": "10s"}
        )
        assert "Test Video" in result
        assert "0%" in result

    def test_video_progress_no_show(self):
        """Test video progress when show_progress is False."""
        formatter = ProgressFormatter(use_colors=False, show_progress=False)
        result = formatter.video_progress(
            "Test Video", {"percent": "50%", "speed": "1MB/s", "eta": "10s"}
        )
        assert result == ""

    def test_video_complete(self):
        """Test video complete output."""
        formatter = ProgressFormatter(use_colors=False)
        result = formatter.video_complete("Test Video", "1080p", ".mp4", "100mb")
        assert "Test Video" in result
        assert "[1080p, .mp4, 100mb]" in result

    def test_artifact_complete(self):
        """Test artifact completion output."""
        formatter = ProgressFormatter(use_colors=False)
        result = formatter.artifact_complete("Test Video", ".srt")
        assert "Downloaded:" in result
        assert "Test Video" in result
        assert "[.srt]" in result

    def test_artifact_complete_with_type(self):
        """Test artifact completion output with artifact label."""
        formatter = ProgressFormatter(use_colors=False)
        result = formatter.artifact_complete("Test Video", ".jpg", "thumbnail")
        assert "Downloaded:" in result
        assert "Test Video" in result
        assert "[thumbnail, .jpg]" in result

    def test_thumbnail_generated(self):
        """Test thumbnail generated output."""
        formatter = ProgressFormatter(use_colors=False)
        result = formatter.thumbnail_generated("Test Video", ".jpg")
        assert "Thumbnail generated:" in result
        assert "Test Video" in result
        assert "[.jpg]" in result

    def test_mp4_generated(self):
        """Test mp4 generated output with bracket stats."""
        formatter = ProgressFormatter(use_colors=False)
        result = formatter.mp4_generated("Test Video", "1080p", "100mb")
        assert ".mp4 generated:" in result
        assert "Test Video" in result
        assert "[1080p, 100mb]" in result

    def test_warning(self):
        """Test warning output."""
        formatter = ProgressFormatter(use_colors=False)
        result = formatter.warning("Something went wrong")
        assert "Something went wrong" in result

    def test_already_downloaded(self):
        """Test already downloaded summary output."""
        formatter = ProgressFormatter(use_colors=False)
        result = formatter.already_downloaded(7)
        assert "Already downloaded:" in result
        assert "7 videos" in result

    def test_error(self):
        """Test error output."""
        formatter = ProgressFormatter(use_colors=False)
        result = formatter.error("Critical error")
        assert "Critical error" in result

    def test_playlist_summary(self):
        """Test playlist summary output."""
        formatter = ProgressFormatter(use_colors=False)
        result = formatter.playlist_summary({"new": 5, "skipped": 2, "failed": 1})
        assert "5" in result
        assert "1" in result
        assert "Already downloaded:" not in result

    def test_playlist_summary_empty(self):
        """Test playlist summary with no activity."""
        formatter = ProgressFormatter(use_colors=False)
        result = formatter.playlist_summary({})
        assert "up to date" in result


class TestQuietFormatter:
    """Test cases for QuietFormatter class."""

    def test_init(self):
        """Test QuietFormatter initialization."""
        formatter = QuietFormatter(use_colors=True)
        assert formatter.use_colors is True

    def test_header_returns_empty(self):
        """Test header returns empty in quiet mode."""
        formatter = QuietFormatter()
        result = formatter.header("1.0.0")
        assert result == ""

    def test_playlist_start_returns_empty(self):
        """Test playlist start returns empty in quiet mode."""
        formatter = QuietFormatter()
        result = formatter.playlist_start("Test", 10)
        assert result == ""

    def test_archive_directory_returns_empty(self):
        """Test archive directory returns empty in quiet mode."""
        formatter = QuietFormatter()
        result = formatter.archive_directory("/tmp/archive")
        assert result == ""

    def test_video_complete_returns_empty(self):
        """Test video complete returns empty in quiet mode."""
        formatter = QuietFormatter()
        result = formatter.video_complete("Test Video")
        assert result == ""

    def test_error_returns_message(self):
        """Test error returns message in quiet mode."""
        formatter = QuietFormatter(use_colors=False)
        result = formatter.error("Error message")
        assert "Error message" in result

    def test_warning_returns_message(self):
        """Test warning returns message in quiet mode."""
        formatter = QuietFormatter(use_colors=False)
        result = formatter.warning("Warning message")
        assert "Warning message" in result


class TestVerboseFormatter:
    """Test cases for VerboseFormatter class."""

    def test_init(self):
        """Test VerboseFormatter initialization."""
        formatter = VerboseFormatter(use_colors=True)
        assert formatter.use_colors is True

    def test_header(self):
        """Test header output."""
        formatter = VerboseFormatter(use_colors=False)
        result = formatter.header("1.0.0")
        assert "ytdl-archiver" in result
        assert "verbose" in result.lower()

    def test_info(self):
        """Test info output."""
        formatter = VerboseFormatter(use_colors=False)
        result = formatter.info("Test info")
        assert "Test info" in result

    def test_debug(self):
        """Test debug output."""
        formatter = VerboseFormatter(use_colors=False)
        result = formatter.debug("Test debug")
        assert "Test debug" in result


class TestGetFormatter:
    """Test cases for get_formatter function."""

    def test_get_progress_formatter(self):
        """Test getting progress formatter."""
        formatter = get_formatter(mode=OutputMode.PROGRESS)
        assert isinstance(formatter, ProgressFormatter)

    def test_get_quiet_formatter(self):
        """Test getting quiet formatter."""
        formatter = get_formatter(mode=OutputMode.QUIET)
        assert isinstance(formatter, QuietFormatter)

    def test_get_verbose_formatter(self):
        """Test getting verbose formatter."""
        formatter = get_formatter(mode=OutputMode.VERBOSE)
        assert isinstance(formatter, VerboseFormatter)


class TestDetectOutputMode:
    """Test cases for detect_output_mode function."""

    def test_verbose_mode(self):
        """Test detecting verbose mode."""
        mode = detect_output_mode(verbose=True, quiet=False)
        assert mode == OutputMode.VERBOSE

    def test_quiet_mode(self):
        """Test detecting quiet mode."""
        mode = detect_output_mode(verbose=False, quiet=True)
        assert mode == OutputMode.QUIET

    def test_default_mode(self):
        """Test detecting default mode."""
        mode = detect_output_mode(verbose=False, quiet=False)
        assert mode == OutputMode.PROGRESS

    def test_quiet_overrides_verbose(self):
        """Test quiet mode overrides verbose."""
        mode = detect_output_mode(verbose=True, quiet=True)
        assert mode == OutputMode.QUIET


class TestShouldUseColors:
    """Test cases for should_use_colors function."""

    def test_no_color_flag_disables(self):
        """Test --no-color flag disables colors."""
        result = should_use_colors(no_color=True)
        assert result is False

    @patch("ytdl_archiver.output.sys.stdout.isatty")
    def test_tty_enables_colors(self, mock_isatty):
        """Test TTY enables colors."""
        mock_isatty.return_value = True
        assert isinstance(should_use_colors(no_color=False), bool)

    @patch("ytdl_archiver.output.sys.stdout.isatty")
    def test_non_tty_disables_colors(self, mock_isatty):
        """Test non-TTY disables colors."""
        mock_isatty.return_value = False
        result = should_use_colors(no_color=False)
        assert result is False
