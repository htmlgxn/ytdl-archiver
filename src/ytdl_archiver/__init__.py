"""ytdl-archiver: Modern Python CLI for archiving YouTube playlists with media-server-friendly sidecar files."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


def _version_from_pyproject(anchor: Path | None = None) -> str | None:
    """Read project version from nearest pyproject.toml in parent directories."""
    start = (anchor or Path(__file__)).resolve()
    start_dir = start if start.is_dir() else start.parent

    for directory in (start_dir, *start_dir.parents):
        pyproject_path = directory / "pyproject.toml"
        if not pyproject_path.exists():
            continue

        try:
            data: dict[str, Any] = tomllib.loads(pyproject_path.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            return None

        project = data.get("project")
        if isinstance(project, dict):
            project_version = project.get("version")
            if isinstance(project_version, str) and project_version:
                return project_version
        return None

    return None

try:
    __version__ = version("ytdl-archiver")
except PackageNotFoundError:
    __version__ = _version_from_pyproject() or "0+unknown"

__author__ = "Ben Chitty"
__email__ = "htmlgxn@pm.me"
