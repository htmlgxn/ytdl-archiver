"""Bridge for running the Rust ratatui setup wizard."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..core.cookies import SUPPORTED_BROWSERS
from .models import CookieSource, SetupAnswers

SETUP_CANCELLED_EXIT_CODE = 10
_BINARY_ENV = "YTDL_ARCHIVER_SETUP_TUI_BIN"
_BINARY_NAME = "ytdl-archiver-setup-tui"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _manifest_path() -> Path:
    return _repo_root() / "rust" / "setup_tui" / "Cargo.toml"


def _binary_candidates() -> list[Path]:
    crate_dir = _manifest_path().parent
    return [
        crate_dir / "target" / "release" / _BINARY_NAME,
        crate_dir / "target" / "debug" / _BINARY_NAME,
    ]


def _resolve_ratatui_binary() -> Path:
    override = os.environ.get(_BINARY_ENV, "").strip()
    if override:
        override_path = Path(override).expanduser()
        if not override_path.exists():
            raise FileNotFoundError(
                f"{_BINARY_ENV} points to missing binary: {override_path}"
            )
        return override_path

    for candidate in _binary_candidates():
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "Rust setup wizard binary not found. Build it with "
        "'cargo build --manifest-path rust/setup_tui/Cargo.toml --release' or "
        f"set {_BINARY_ENV}."
    )


def _normalized_answers(payload: dict[str, Any], defaults: SetupAnswers) -> SetupAnswers:
    cookie_source_raw = str(payload.get("cookie_source", defaults.cookie_source))
    cookie_source: CookieSource = (
        "browser" if cookie_source_raw == "browser" else "manual_file"
    )

    cookie_browser = str(payload.get("cookie_browser", defaults.cookie_browser)).lower()
    if cookie_browser not in SUPPORTED_BROWSERS:
        cookie_browser = defaults.cookie_browser

    archive_directory = str(
        payload.get("archive_directory", defaults.archive_directory)
    ).strip()
    if not archive_directory:
        archive_directory = defaults.archive_directory

    cookie_profile = str(payload.get("cookie_profile", defaults.cookie_profile)).strip()
    if cookie_source != "browser":
        cookie_profile = ""

    return SetupAnswers(
        archive_directory=archive_directory,
        cookie_source=cookie_source,
        cookie_browser=cookie_browser,
        cookie_profile=cookie_profile,
        write_subtitles=bool(
            payload.get("write_subtitles", defaults.write_subtitles),
        ),
        write_thumbnail=bool(
            payload.get("write_thumbnail", defaults.write_thumbnail),
        ),
        generate_nfo=bool(payload.get("generate_nfo", defaults.generate_nfo)),
    )


def run_ratatui_setup(defaults: SetupAnswers | None = None) -> SetupAnswers | None:
    """Run the Rust ratatui setup and return answers, or None if cancelled."""
    selected_defaults = defaults or SetupAnswers()
    binary = _resolve_ratatui_binary()
    with tempfile.TemporaryDirectory(prefix="ytdl-archiver-setup-") as tmpdir:
        defaults_path = Path(tmpdir) / "defaults.json"
        result_path = Path(tmpdir) / "result.json"
        defaults_path.write_text(json.dumps(asdict(selected_defaults)))

        command = [
            str(binary),
            "--defaults",
            str(defaults_path),
            "--result",
            str(result_path),
        ]
        completed = subprocess.run(command, check=False)

        if completed.returncode == SETUP_CANCELLED_EXIT_CODE:
            return None
        if completed.returncode != 0:
            raise RuntimeError(
                f"Ratatui setup failed (exit={completed.returncode})"
            )

        if not result_path.exists():
            raise ValueError("Ratatui setup did not produce a result file")

        raw_output = result_path.read_text().strip()
        if not raw_output:
            raise ValueError("Ratatui setup returned no output")

        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive parse guard
            raise ValueError(f"Ratatui setup produced invalid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise TypeError("Ratatui setup output must be a JSON object")
        return _normalized_answers(parsed, selected_defaults)
