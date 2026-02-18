"""Custom exceptions for ytdl-archiver."""


class YTDLArchiverError(Exception):
    """Base exception for ytdl-archiver."""
    ...


class ConfigurationError(YTDLArchiverError):
    """Configuration related errors."""
    ...


class DownloadError(YTDLArchiverError):
    """Download related errors."""
    ...


class MetadataError(YTDLArchiverError):
    """Metadata generation errors."""
    ...


class ArchiveError(YTDLArchiverError):
    """Archive tracking errors."""
    ...


class CookieRefreshError(YTDLArchiverError):
    """Browser cookie refresh errors."""
    ...
