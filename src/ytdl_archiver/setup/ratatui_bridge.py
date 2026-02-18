"""Bridge for running the Rust ratatui setup wizard."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from dataclasses import asdict
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from ..core.cookies import SUPPORTED_BROWSERS
from .models import CookieSource, SetupAnswers

SETUP_CANCELLED_EXIT_CODE = 10
_BINARY_ENV = "YTDL_ARCHIVER_SETUP_TUI_BIN"
_BINARY_NAME = "ytdl-archiver-setup-tui"
_BINARY_PACKAGE = "ytdl_archiver.setup.bin"
_AUTOBUILD_ENV = "YTDL_ARCHIVER_SETUP_TUI_AUTOBUILD"
_BUILD_TIMEOUT_ENV = "YTDL_ARCHIVER_SETUP_TUI_BUILD_TIMEOUT"
_DEFAULT_BUILD_TIMEOUT_SECONDS = 300


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


def _existing_local_binaries_by_newest() -> list[Path]:
    existing = [candidate for candidate in _binary_candidates() if candidate.exists()]
    return sorted(
        existing,
        key=lambda candidate: candidate.stat().st_mtime,
        reverse=True,
    )


def _packaged_binary_candidates() -> list[Traversable]:
    package_files = resources.files(_BINARY_PACKAGE)
    os_name = (
        "windows"
        if sys.platform.startswith("win")
        else "macos" if sys.platform == "darwin" else "linux"
    )
    machine = platform.machine().lower()
    arch = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }.get(machine, machine)
    platform_tag = f"{os_name}-{arch}"
    names = [
        f"{_BINARY_NAME}-{platform_tag}",
        f"{_BINARY_NAME}-{platform_tag}.exe",
    ]
    if sys.platform.startswith("win"):
        names.extend([f"{_BINARY_NAME}.exe", _BINARY_NAME])
    else:
        names.extend([_BINARY_NAME, f"{_BINARY_NAME}.exe"])
    return [package_files.joinpath(name) for name in names]


def _ensure_executable(path: Path) -> None:
    if sys.platform.startswith("win"):
        return
    try:
        mode = path.stat().st_mode
        path.chmod(mode | 0o111)
    except OSError:
        # Best-effort only; if this fails, subprocess will report exec error.
        return


def _autobuild_enabled() -> bool:
    value = os.environ.get(_AUTOBUILD_ENV, "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _build_timeout_seconds() -> int:
    raw = os.environ.get(_BUILD_TIMEOUT_ENV, "").strip()
    if not raw:
        return _DEFAULT_BUILD_TIMEOUT_SECONDS
    try:
        timeout = int(raw)
    except ValueError:
        return _DEFAULT_BUILD_TIMEOUT_SECONDS
    if timeout <= 0:
        return _DEFAULT_BUILD_TIMEOUT_SECONDS
    return timeout


def _attempt_autobuild_binary(timeout_seconds: int) -> None:
    manifest = _manifest_path()
    repo_root = _repo_root()
    stage_script = repo_root / "scripts" / "stage_setup_tui_binary.py"
    if not stage_script.exists():
        raise FileNotFoundError(f"Setup staging script is missing: {stage_script}")

    build_command = [
        "cargo",
        "build",
        "--manifest-path",
        str(manifest),
        "--release",
    ]
    stage_command = [sys.executable, str(stage_script)]

    try:
        build_result = subprocess.run(
            build_command,
            check=False,
            timeout=timeout_seconds,
            cwd=str(repo_root),
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            "Rust toolchain (cargo) is required to auto-build the setup wizard."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FileNotFoundError(
            f"Auto-build timed out after {timeout_seconds}s while running cargo."
        ) from exc

    if build_result.returncode != 0:
        raise FileNotFoundError(
            "Auto-build failed while compiling setup wizard "
            f"(cargo exit={build_result.returncode})."
        )

    try:
        stage_result = subprocess.run(
            stage_command,
            check=False,
            timeout=timeout_seconds,
            cwd=str(repo_root),
        )
    except subprocess.TimeoutExpired as exc:
        raise FileNotFoundError(
            f"Auto-build timed out after {timeout_seconds}s while staging binary."
        ) from exc

    if stage_result.returncode != 0:
        raise FileNotFoundError(
            "Auto-build failed while staging setup wizard binary "
            f"(stage exit={stage_result.returncode})."
        )


def _resolve_ratatui_binary(stack: ExitStack) -> Path:
    override = os.environ.get(_BINARY_ENV, "").strip()
    if override:
        override_path = Path(override).expanduser()
        if not override_path.exists():
            raise FileNotFoundError(
                f"{_BINARY_ENV} points to missing binary: {override_path}"
            )
        _ensure_executable(override_path)
        return override_path

    for candidate in _packaged_binary_candidates():
        if candidate.is_file():
            packaged_path = stack.enter_context(resources.as_file(candidate))
            _ensure_executable(packaged_path)
            return packaged_path

    for candidate in _existing_local_binaries_by_newest():
        _ensure_executable(candidate)
        return candidate

    if _autobuild_enabled():
        timeout_seconds = _build_timeout_seconds()
        _attempt_autobuild_binary(timeout_seconds)
        for candidate in _packaged_binary_candidates():
            if candidate.is_file():
                packaged_path = stack.enter_context(resources.as_file(candidate))
                _ensure_executable(packaged_path)
                return packaged_path
        for candidate in _existing_local_binaries_by_newest():
            _ensure_executable(candidate)
            return candidate
        raise FileNotFoundError(
            "Setup wizard auto-build completed, but no runnable binary was found."
        )

    raise FileNotFoundError(
        "Rust setup wizard binary not found. Auto-build is disabled "
        f"({_AUTOBUILD_ENV}=0). Install a wheel that bundles the setup binary, or "
        "build/stage it locally with "
        "'cargo build --manifest-path rust/setup_tui/Cargo.toml --release' and stage it "
        "with 'python scripts/stage_setup_tui_binary.py', or set "
        f"{_BINARY_ENV}."
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
    with ExitStack() as stack:
        binary = _resolve_ratatui_binary(stack)
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
