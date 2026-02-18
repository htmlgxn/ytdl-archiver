"""Tests for custom exceptions."""

import pytest

from ytdl_archiver.exceptions import (
    YTDLArchiverError,
    DownloadError,
    ArchiveError,
    MetadataError,
    ConfigurationError,
)


class TestExceptions:
    """Test cases for custom exceptions."""

    def test_ytdl_archiver_error(self):
        """Test YTDLArchiverError base exception."""
        error = YTDLArchiverError("Test error")
        assert str(error) == "Test error"
        assert issubclass(YTDLArchiverError, Exception)

    def test_download_error(self):
        """Test DownloadError exception."""
        error = DownloadError("Download failed")
        assert str(error) == "Download failed"
        assert issubclass(DownloadError, YTDLArchiverError)

    def test_archive_error(self):
        """Test ArchiveError exception."""
        error = ArchiveError("Archive error")
        assert str(error) == "Archive error"
        assert issubclass(ArchiveError, YTDLArchiverError)

    def test_metadata_error(self):
        """Test MetadataError exception."""
        error = MetadataError("Metadata error")
        assert str(error) == "Metadata error"
        assert issubclass(MetadataError, YTDLArchiverError)

    def test_configuration_error(self):
        """Test ConfigurationError exception."""
        error = ConfigurationError("Config error")
        assert str(error) == "Config error"
        assert issubclass(ConfigurationError, YTDLArchiverError)

    def test_exception_inheritance(self):
        """Test all exceptions inherit from YTDLArchiverError."""
        assert issubclass(DownloadError, YTDLArchiverError)
        assert issubclass(ArchiveError, YTDLArchiverError)
        assert issubclass(MetadataError, YTDLArchiverError)
        assert issubclass(ConfigurationError, YTDLArchiverError)

    def test_exception_message_formatting(self):
        """Test exception messages."""
        error = DownloadError("Failed to download video: example.com")
        assert "example.com" in str(error)

    def test_exception_with_original_cause(self):
        """Test exception chaining."""
        original = ValueError("Invalid value")
        error = DownloadError("Download failed")
        error.__cause__ = original
        assert error.__cause__ is original
