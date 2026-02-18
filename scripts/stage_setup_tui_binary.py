#!/usr/bin/env python3
"""Copy the built ratatui setup binary into the Python package tree."""

from __future__ import annotations

import argparse
import platform
import shutil
import stat
import sys
from pathlib import Path

BINARY_NAME = "ytdl-archiver-setup-tui"


def _platform_tag() -> str:
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
    return f"{os_name}-{arch}"


def _default_source() -> Path:
    suffix = ".exe" if sys.platform.startswith("win") else ""
    return Path("rust/setup_tui/target/release") / f"{BINARY_NAME}{suffix}"


def _default_destination() -> Path:
    ext = ".exe" if sys.platform.startswith("win") else ""
    tagged_name = f"{BINARY_NAME}-{_platform_tag()}{ext}"
    return Path("src/ytdl_archiver/setup/bin") / tagged_name


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage the setup TUI binary for packaging in wheels."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=_default_source(),
        help="Path to built binary (default: rust/setup_tui/target/release/...)",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=_default_destination(),
        help="Path under src/ to copy binary to.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    source = args.source
    destination = args.destination

    if not source.exists():
        print(f"error: source binary does not exist: {source}", file=sys.stderr)
        return 1
    if not source.is_file():
        print(f"error: source is not a file: {source}", file=sys.stderr)
        return 1

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if not sys.platform.startswith("win"):
        mode = destination.stat().st_mode
        destination.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"staged: {source} -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
