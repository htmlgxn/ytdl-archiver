"""yt-dlp option construction and logger suppression."""

import logging
from typing import Any

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    logger = logging.getLogger(__name__)


def configure_ytdlp_logging() -> None:
    """Suppress yt-dlp's own loggers to prevent unwanted console output."""
    for logger_name in [
        "yt_dlp",
        "yt_dlp.extractor",
        "yt_dlp.downloader",
        "yt_dlp.postprocessor",
    ]:
        ydl_logger = logging.getLogger(logger_name)
        ydl_logger.setLevel(logging.CRITICAL)
        ydl_logger.addHandler(logging.NullHandler())


# Run once at import time.
configure_ytdlp_logging()


class SilentYTDLPLogger:
    """Quiet logger for yt-dlp that routes warnings/errors to structlog debug."""

    def debug(self, msg: str) -> None:
        _ = msg

    def info(self, msg: str) -> None:
        _ = msg

    def warning(self, msg: str) -> None:
        logger.debug("yt-dlp warning: %s", msg)

    def error(self, msg: str) -> None:
        logger.debug("yt-dlp error: %s", msg)


def build_ydl_options(config, playlist_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build yt-dlp options from configuration with playlist-specific overrides."""
    if playlist_config is None:
        playlist_config = {}

    def first_defined(*keys: str) -> Any:
        for key in keys:
            value = playlist_config.get(key)
            if value is not None:
                return value
        for key in keys:
            value = config.get(f"download.{key}")
            if value is not None:
                return value
        return None

    opts: dict[str, Any] = {
        "format": first_defined("format"),
        "format_sort": first_defined("format_sort"),
        "merge_output_format": first_defined("merge_output_format"),
        "http_headers": {
            "User-Agent": config.get("http.user_agent"),
        },
        "socket_timeout": first_defined("socket_timeout")
        or config.get("http.request_timeout"),
        "connect_timeout": first_defined("connect_timeout")
        or config.get("http.connect_timeout"),
    }

    # Handle boolean options separately to preserve False values
    write_subtitles = first_defined("write_subtitles", "writesubtitles")
    if write_subtitles is not None:
        opts["writesubtitles"] = write_subtitles

    embed_subtitles = first_defined("embed_subtitles", "embedsubtitles")
    if embed_subtitles is not None:
        opts["embedsubtitles"] = embed_subtitles

    write_thumbnail = first_defined("write_thumbnail", "writethumbnail")
    if write_thumbnail is not None:
        opts["writethumbnail"] = write_thumbnail

    write_info_json = first_defined("write_info_json", "writeinfojson")
    if write_info_json is not None:
        opts["writeinfojson"] = write_info_json

    remux_video = first_defined("remux_video")
    if remux_video is not None:
        opts["remux_video"] = remux_video

    # Subtitle format options
    subtitle_format = first_defined("subtitle_format", "subtitlesformat")
    if subtitle_format is not None:
        opts["subtitlesformat"] = subtitle_format

    convert_subtitles = first_defined("convert_subtitles", "convertsubtitles")
    if convert_subtitles is not None:
        opts["convertsubtitles"] = convert_subtitles

    subtitle_languages = first_defined("subtitle_languages", "subtitleslangs")
    if subtitle_languages is not None:
        opts["subtitleslangs"] = subtitle_languages

    # Build postprocessors list
    postprocessors = _build_postprocessors(opts, first_defined)
    opts["postprocessors"] = postprocessors

    return {k: v for k, v in opts.items() if v is not None}


def _build_postprocessors(opts: dict[str, Any], first_defined) -> list[dict[str, Any]]:
    """Build the postprocessors list from options."""
    postprocessors: list[dict[str, Any]] = []
    container_policy = str(first_defined("container_policy") or "").strip()

    if opts.get("writesubtitles") and opts.get("convertsubtitles"):
        postprocessors.append(
            {
                "key": "FFmpegSubtitlesConvertor",
                "format": str(opts["convertsubtitles"]).lstrip("."),
            }
        )

    if opts.get("writesubtitles") and opts.get("embedsubtitles"):
        postprocessors.append(
            {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": True}
        )

    recode_video = first_defined("recode_video")
    merge_output_format = first_defined("merge_output_format")
    if recode_video and merge_output_format:
        postprocessors.append({
            "key": "FFmpegVideoConvertor",
            "preferedformat": merge_output_format,
        })
    elif opts.get("remux_video"):
        postprocessors.append(
            {
                "key": "FFmpegVideoRemuxer",
                "preferedformat": str(opts["remux_video"]),
            }
        )

    thumbnail_format = first_defined("thumbnail_format")
    if thumbnail_format:
        postprocessors.append({
            "key": "FFmpegThumbnailsConvertor",
            "format": thumbnail_format,
        })

    return postprocessors


def build_runtime_ydl_options(
    config,
    playlist_config: dict[str, Any] | None = None,
    *,
    include_progress_hooks: bool = False,
    formatter=None,
) -> dict[str, Any]:
    """Build effective yt-dlp options used at runtime."""
    from .progress import ProgressCallback

    opts = build_ydl_options(config, playlist_config)

    # Convert format_sort from comma-separated string to list for Python API
    format_sort = opts.get("format_sort")
    if format_sort and isinstance(format_sort, str):
        opts["format_sort"] = [s.strip() for s in format_sort.split(",")]

    opts.update(
        {
            "quiet": True,
            "no_warnings": True,
            "logger": SilentYTDLPLogger(),
            "progress": False,
            "extract_flat": False,
            "print_json": False,
            "simulate": False,
            "noplaylist": False,
            "extractaudio": False,
            "extractvideo": False,
            "no_color": True,
            "progress_with_newline": False,
            "xattr_set_filesize": False,
            "skip_unavailable_fragments": True,
            "ignoreerrors": "only_download",
            "socket_timeout": 60,
            "retries": 3,
            "fragment_retries": 3,
            "extractor_retries": 3,
            "file_access_retries": 3,
            "no_call_home": True,
            "no_update_check": True,
            "download_archive": None,
            "user_agent": None,
        }
    )

    if include_progress_hooks and formatter:
        opts["progress_hooks"] = [ProgressCallback(formatter)]
    else:
        opts["progress_hooks"] = []

    if config.get("http.no_check_certificates", False):
        opts["no_check_certificates"] = True

    cookie_path = config.get_cookie_file_path()
    if cookie_path:
        opts["cookiefile"] = str(cookie_path)

    opts["extractor_args"] = {"youtube": {"player_client": "default"}}

    return {k: v for k, v in opts.items() if v is not None}
