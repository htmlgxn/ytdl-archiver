"""Data models for interactive first-run setup."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CookieSource = Literal["manual_file", "browser"]
SetupUiMode = Literal["ratatui", "prompt", "non_interactive"]

DEFAULT_ARCHIVE_DIRECTORY = "~/Videos/media/youtube/"
DEFAULT_COOKIE_BROWSER = "firefox"


@dataclass(slots=True)
class SetupAnswers:
    """Collected setup values used to render template files."""

    archive_directory: str = DEFAULT_ARCHIVE_DIRECTORY
    cookie_source: CookieSource = "manual_file"
    cookie_browser: str = DEFAULT_COOKIE_BROWSER
    cookie_profile: str = ""
    write_subtitles: bool = True
    write_thumbnail: bool = True
    generate_nfo: bool = True


@dataclass(slots=True)
class SetupWriteResult:
    """Result details for setup file generation."""

    config_path: Path
    playlists_path: Path
    archive_directory: Path
    created_config: bool
    created_playlists: bool
    created_archive_directory: bool


@dataclass(slots=True)
class SetupRunResult:
    """Combined setup interaction and file-generation result."""

    answers: SetupAnswers
    write_result: SetupWriteResult
    ui_mode: SetupUiMode
    ui_error: str | None = None
