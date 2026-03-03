"""Utility functions for ytdl-archiver."""

import json
import logging
import logging.handlers
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import structlog


class _VerboseConsoleFilter(logging.Filter):
    """Limit verbose console logging to technical diagnostics."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Suppress noisy info-level logs that duplicate formatter UX lines.
        return record.levelno != logging.INFO


def setup_logging(
    config: dict[str, Any],
    console_output: bool = False,
    console_level: str = "WARNING",
) -> None:
    """Setup structured logging with JSON output to file only."""
    logging_config = config.get("logging", {})
    if not isinstance(logging_config, dict):
        logging_config = {}

    def _cfg(name: str, default: Any) -> Any:
        if name in logging_config:
            return logging_config[name]
        dotted = f"logging.{name}"
        if dotted in config:
            return config[dotted]
        return config.get(name, default)

    log_level = _cfg("level", "INFO")
    log_format = _cfg("format", "json")
    log_file = _cfg("file_path", None)
    max_file_size = _cfg("max_file_size", "10MB")
    backup_count = _cfg("backup_count", 5)

    # Configure structlog
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard logging - no console output by default
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(message)s",
        handlers=[],
        force=True,
    )

    # Console handler - only add if explicitly requested
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        if log_format == "json":
            console_handler.setFormatter(JsonFormatter())
        else:
            console_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                )
            )
        console_handler.setLevel(getattr(logging, console_level.upper(), logging.WARNING))
        console_handler.addFilter(_VerboseConsoleFilter())
        logging.getLogger().addHandler(console_handler)

    # File handler with rotation - always enabled for debugging
    if log_file:
        log_path = Path(log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=_parse_size(max_file_size),
            backupCount=backup_count,
        )
        file_handler.setFormatter(JsonFormatter())
        logging.getLogger().addHandler(file_handler)


class JsonFormatter(logging.Formatter):
    """Simple JSON formatter for logging."""

    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if hasattr(record, "exc_info") and record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def _parse_size(size_str: str) -> int:
    """Parse size string like '10MB' to bytes."""
    size_str = size_str.upper()
    if size_str.endswith("KB"):
        return int(size_str[:-2]) * 1024
    if size_str.endswith("MB"):
        return int(size_str[:-2]) * 1024 * 1024
    if size_str.endswith("GB"):
        return int(size_str[:-2]) * 1024 * 1024 * 1024
    return int(size_str)


def sanitize_filename(
    name: str, *, lowercase: bool = True, preserve_dots: bool = False
) -> str:
    """Sanitize filename for safe file system usage."""
    if lowercase:
        name = name.lower()

    # Replace spaces with dashes
    name = name.replace(" ", "-")
    # Remove or replace unwanted characters.
    if preserve_dots:
        name = re.sub(r'[\'()<>"|?*]|[^-.\w]', "", name)
    else:
        name = re.sub(r'[.\'()<>"|?*]|[^-\w]', "", name)
    # Remove any remaining dashes and spaces
    return name.strip("-")


def extract_video_id(video_url: str, metadata: dict[str, Any] | None = None) -> str:
    """Extract a stable video id from URL and metadata fallbacks."""
    parsed = urlparse(video_url)
    query_id = parse_qs(parsed.query).get("v", [None])[0]
    if query_id:
        return str(query_id)

    path = parsed.path.strip("/")
    if path.startswith("shorts/"):
        short_id = path.split("/", 1)[1]
        if short_id:
            return short_id

    tail = path.split("/")[-1]
    if tail:
        return tail

    if metadata:
        metadata_id = str(metadata.get("id") or "").strip()
        if metadata_id:
            return metadata_id

    return "unknown-video"


def _apply_case_mode(value: str, mode: str) -> str:
    """Apply configured case transformation to a token value."""
    if mode == "lower":
        return value.lower()
    if mode == "upper":
        return value.upper()
    if mode == "title":
        return value.title()
    return value


def _format_upload_date(raw_upload_date: str, date_format: str) -> str:
    """Format upload date from YYYYMMDD to configured style."""
    if not re.fullmatch(r"\d{8}", raw_upload_date):
        return ""
    year = raw_upload_date[:4]
    month = raw_upload_date[4:6]
    day = raw_upload_date[6:8]
    if date_format == "yyyymmdd":
        return f"{year}{month}{day}"
    if date_format == "yyyy_mm_dd":
        return f"{year}_{month}_{day}"
    if date_format == "yyyy.mm.dd":
        return f"{year}.{month}.{day}"
    return f"{year}-{month}-{day}"


def build_output_filename(
    config: Any, metadata: dict[str, Any] | None, video_url: str
) -> str:
    """Build an output filename from config-driven token and formatting settings."""
    video_id = extract_video_id(video_url, metadata)
    fallback_title = f"video-{video_id}"

    tokens = config.get("filename.tokens", ["title", "channel"])
    token_joiner = str(config.get("filename.token_joiner", "_"))
    date_format = str(config.get("filename.date_format", "yyyy-mm-dd"))
    missing_token_behavior = str(config.get("filename.missing_token_behavior", "omit"))
    case_map = config.get("filename.case", {}) or {}

    title = metadata.get("title", fallback_title) if metadata else fallback_title
    channel = metadata.get("uploader", "unknown-channel") if metadata else "unknown-channel"
    upload_date_raw = str(metadata.get("upload_date", "") or "") if metadata else ""

    raw_token_values: dict[str, str] = {
        "title": str(title),
        "channel": str(channel),
        "upload_date": _format_upload_date(upload_date_raw, date_format),
        "video_id": video_id,
    }

    formatted_tokens: list[str] = []
    for token in tokens:
        raw_value = str(raw_token_values.get(token, "") or "")
        if not raw_value:
            if missing_token_behavior == "omit":
                continue
            continue

        case_mode = str(case_map.get(token, "preserve"))
        cased = _apply_case_mode(raw_value, case_mode)
        safe_value = sanitize_filename(
            cased,
            lowercase=False,
            preserve_dots=(token == "upload_date"),
        )
        if safe_value:
            formatted_tokens.append(safe_value)

    filename = token_joiner.join(formatted_tokens)
    if token_joiner:
        filename = re.sub(rf"{re.escape(token_joiner)}+", token_joiner, filename)
        filename = filename.strip(token_joiner)

    if filename:
        return filename

    return sanitize_filename(fallback_title, lowercase=False) or "video-unknown-video"


def is_short(metadata: dict[str, Any], aspect_ratio_threshold: float = 0.7) -> bool:
    """
    Check if the video is a YouTube Short based on its dimensions.

    Args:
        metadata: Video metadata from yt-dlp
        aspect_ratio_threshold: Threshold below which video is considered a short

    Returns:
        True if video is likely a YouTube Short
    """
    height = metadata.get("height")
    width = metadata.get("width")

    if height and width:
        aspect_ratio = width / height
        return aspect_ratio < aspect_ratio_threshold
    return False


@contextmanager
def suppress_output():
    """Context manager to suppress stdout and stderr."""
    with Path(os.devnull).open("w") as devnull:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        try:
            sys.stdout = devnull
            sys.stderr = devnull
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
