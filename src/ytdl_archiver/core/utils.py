"""Utility functions for ytdl-archiver."""

import json
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any, Dict

import structlog


def setup_logging(config: Dict[str, Any]) -> None:
    """Setup structured logging with JSON output."""
    log_level = config.get("logging.level", "INFO")
    log_format = config.get("logging.format", "json")
    log_file = config.get("logging.file_path")
    max_file_size = config.get("logging.max_file_size", "10MB")
    backup_count = config.get("logging.backup_count", 5)

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

    # Configure standard logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()), format="%(message)s", handlers=[]
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        console_handler.setFormatter(JsonFormatter())
    else:
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
    logging.getLogger().addHandler(console_handler)

    # File handler with rotation
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
    elif size_str.endswith("MB"):
        return int(size_str[:-2]) * 1024 * 1024
    elif size_str.endswith("GB"):
        return int(size_str[:-2]) * 1024 * 1024 * 1024
    else:
        return int(size_str)


def sanitize_filename(name: str) -> str:
    """Sanitize filename for safe file system usage."""
    import re

    # Convert to lowercase and replace spaces with dashes
    name = name.lower().replace(" ", "-")
    # Remove or replace unwanted characters
    name = re.sub(r'[.\'()<>"|?*]|[^-\w]', "", name)
    # Remove any remaining dashes and spaces
    name = name.strip("-")
    return name


def is_short(metadata: Dict[str, Any], aspect_ratio_threshold: float = 0.7) -> bool:
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
    else:
        return False
