"""Tests for utility functions."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ytdl_archiver.core.utils import (
    is_short,
    sanitize_filename,
    setup_logging,
    _parse_size,
)


class TestUtils:
    """Test cases for utility functions."""

    def test_is_short_vertical_video(self, mock_short_video_info):
        """Test short detection for vertical video."""
        result = is_short(mock_short_video_info)
        assert result is True

    def test_is_short_horizontal_video(self, mock_video_info):
        """Test short detection for horizontal video."""
        result = is_short(mock_video_info)
        assert result is False

    def test_is_short_square_video(self):
        """Test short detection for square video."""
        video_info = {
            "width": 1080,
            "height": 1080,
        }
        result = is_short(video_info)
        assert result is False

    def test_is_short_missing_dimensions(self):
        """Test short detection with missing dimensions."""
        video_info = {}
        result = is_short(video_info)
        assert result is False

    def test_is_short_none_dimensions(self):
        """Test short detection with None dimensions."""
        video_info = {
            "width": None,
            "height": None,
        }
        result = is_short(video_info)
        assert result is False

    def test_is_short_custom_threshold(self):
        """Test short detection with custom threshold."""
        video_info = {
            "width": 800,
            "height": 1200,  # aspect ratio = 0.67
        }
        
        # Default threshold (0.7) should detect as short
        assert is_short(video_info) is True
        
        # With custom threshold of 0.5, should not detect as short
        assert is_short(video_info, aspect_ratio_threshold=0.5) is False

    def test_is_short_zero_dimensions(self):
        """Test short detection with zero dimensions."""
        video_info = {
            "width": 0,
            "height": 0,
        }
        result = is_short(video_info)
        assert result is False

    def test_sanitize_filename_basic(self):
        """Test basic filename sanitization."""
        test_cases = [
            ("normal_video.mp4", "normal_video.mp4"),
            ("video with spaces.mp4", "video with spaces.mp4"),
            ("video-with-dashes.mp4", "video-with-dashes.mp4"),
            ("video_with_underscores.mp4", "video_with_underscores.mp4"),
        ]
        
        for input_name, expected in test_cases:
            result = sanitize_filename(input_name)
            assert result == expected

    def test_sanitize_filename_special_chars(self):
        """Test filename sanitization with special characters."""
        test_cases = [
            ("video<with>brackets.mp4", "videowithbrackets.mp4"),
            ("video:with:colons.mp4", "videowithcolons.mp4"),
            ('video"with"quotes.mp4', "videowithquotes.mp4"),
            ("video|with|pipes.mp4", "videowithpipes.mp4"),
            ("video?with?questions.mp4", "videowithquestions.mp4"),
            ("video*with*asterisks.mp4", "videowithasterisks.mp4"),
        ]
        
        for input_name, expected in test_cases:
            result = sanitize_filename(input_name)
            assert result == expected

    def test_sanitize_filename_path_traversal(self):
        """Test filename sanitization prevents path traversal."""
        test_cases = [
            ("../../../etc/passwd", ".....etcpasswd"),
            ("..\\..\\windows\\system", "windowswindowsystem"),
            ("video/../../../etc/passwd", "video.....etcpasswd"),
        ]
        
        for input_name, expected in test_cases:
            result = sanitize_filename(input_name)
            assert result == expected

    def test_sanitize_filename_empty(self):
        """Test filename sanitization with empty string."""
        result = sanitize_filename("")
        assert result == ""

    def test_sanitize_filename_unicode(self):
        """Test filename sanitization with Unicode characters."""
        unicode_name = "测试视频.mp4"
        result = sanitize_filename(unicode_name)
        assert result == unicode_name

    def test_sanitize_filename_very_long(self):
        """Test filename sanitization with very long names."""
        long_name = "a" * 300 + ".mp4"
        result = sanitize_filename(long_name)
        
        # Should be truncated to reasonable length
        assert len(result) < len(long_name)
        assert result.endswith(".mp4")

    def test_parse_size_bytes(self):
        """Test parsing file size in bytes."""
        result = _parse_size("1024")
        assert result == 1024

    def test_parse_size_kb(self):
        """Test parsing file size in kilobytes."""
        result = _parse_size("10KB")
        assert result == 10240

    def test_parse_size_mb(self):
        """Test parsing file size in megabytes."""
        result = _parse_size("5MB")
        assert result == 5 * 1024 * 1024

    def test_parse_size_gb(self):
        """Test parsing file size in gigabytes."""
        result = _parse_size("2GB")
        assert result == 2 * 1024 * 1024 * 1024

    def test_parse_size_mixed_case(self):
        """Test parsing file size with mixed case units."""
        test_cases = [
            ("10kb", 10240),
            ("5Mb", 5 * 1024 * 1024),
            ("1Gb", 1024 * 1024 * 1024),
        ]
        
        for input_size, expected in test_cases:
            result = _parse_size(input_size)
            assert result == expected

    def test_parse_size_with_spaces(self):
        """Test parsing file size with spaces."""
        result = _parse_size("  10 MB  ")
        assert result == 10 * 1024 * 1024

    def test_parse_size_invalid(self):
        """Test parsing invalid file size."""
        test_cases = [
            "invalid",
            "10XB",  # Invalid unit
            "abcMB",  # Invalid number
            "",  # Empty string
        ]
        
        for input_size in test_cases:
            with pytest.raises(ValueError):
                _parse_size(input_size)

    def test_setup_logging_default(self, temp_dir):
        """Test setting up default logging."""
        config = {
            "level": "INFO",
            "format": "json",
            "file_path": str(temp_dir / "test.log"),
            "max_file_size": "1MB",
            "backup_count": 3,
        }
        
        with patch('ytdl_archiver.core.utils.structlog') as mock_structlog:
            setup_logging(config)
            
            # Should configure structlog
            mock_structlog.configure.assert_called_once()

    def test_setup_logging_text_format(self, temp_dir):
        """Test setting up text format logging."""
        config = {
            "level": "DEBUG",
            "format": "text",
            "file_path": str(temp_dir / "test.log"),
            "max_file_size": "1MB",
            "backup_count": 3,
        }
        
        with patch('ytdl_archiver.core.utils.structlog') as mock_structlog:
            setup_logging(config)
            
            # Should configure with text processor
            call_args = mock_structlog.configure.call_args[1]
            assert "processors" in call_args

    def test_setup_logging_creates_directory(self, temp_dir):
        """Test that logging setup creates log directory."""
        log_path = temp_dir / "nested" / "test.log"
        config = {
            "level": "INFO",
            "format": "json",
            "file_path": str(log_path),
            "max_file_size": "1MB",
            "backup_count": 3,
        }
        
        setup_logging(config)
        
        # Should create parent directory
        assert log_path.parent.exists()

    def test_setup_logging_invalid_level(self, temp_dir):
        """Test setup logging with invalid level."""
        config = {
            "level": "INVALID",
            "format": "json",
            "file_path": str(temp_dir / "test.log"),
            "max_file_size": "1MB",
            "backup_count": 3,
        }
        
        # Should not raise exception, but use default level
        setup_logging(config)

    def test_setup_logging_no_file_path(self):
        """Test setup logging without file path."""
        config = {
            "level": "INFO",
            "format": "json",
            "file_path": "",
            "max_file_size": "1MB",
            "backup_count": 3,
        }
        
        # Should not raise exception
        setup_logging(config)