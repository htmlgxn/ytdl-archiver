"""Unit tests for utility functions."""

import pytest

from ytdl_archiver.core.utils import is_short, sanitize_filename


class TestUtils:
    """Test utility functions."""

    def test_sanitize_filename(self):
        """Test filename sanitization."""
        # Test basic sanitization
        assert sanitize_filename("Test Video") == "test-video"
        assert sanitize_filename("Video with spaces") == "video-with-spaces"

        # Test special character removal
        assert sanitize_filename("Video: Special!Chars?") == "video-specialchars"
        assert sanitize_filename("Video.with.dots") == "videowithdots"

        # Test edge cases
        assert sanitize_filename("") == ""
        assert sanitize_filename("   ") == ""
        assert sanitize_filename("Normal-Video_Name") == "normal-video_name"

    def test_is_short(self):
        """Test YouTube Short detection."""
        # Test vertical video (short)
        vertical_metadata = {"width": 720, "height": 1280}
        assert is_short(vertical_metadata, 0.7) is True

        # Test horizontal video (not short)
        horizontal_metadata = {"width": 1920, "height": 1080}
        assert is_short(horizontal_metadata, 0.7) is False

        # Test square video (not short)
        square_metadata = {"width": 1080, "height": 1080}
        assert is_short(square_metadata, 0.7) is False

        # Test missing dimensions
        incomplete_metadata = {"width": 1920}
        assert is_short(incomplete_metadata, 0.7) is False

        empty_metadata = {}
        assert is_short(empty_metadata, 0.7) is False

        # Test custom threshold
        vertical_metadata = {"width": 800, "height": 1000}  # ratio = 0.8
        assert is_short(vertical_metadata, 0.7) is False
        assert is_short(vertical_metadata, 0.9) is True
