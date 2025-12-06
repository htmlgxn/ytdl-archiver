"""Custom exceptions for ytdl-archiver."""


class YTDLArchiverError(Exception):
    """Base exception for ytdl-archiver."""

    pass


class ConfigurationError(YTDLArchiverError):
    """Configuration related errors."""

    pass


class DownloadError(YTDLArchiverError):
    """Download related errors."""

    pass


class MetadataError(YTDLArchiverError):
    """Metadata generation errors."""

    pass


class ArchiveError(YTDLArchiverError):
    """Archive tracking errors."""

    pass
