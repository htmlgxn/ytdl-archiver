"""Tests for the Rust ratatui setup bridge."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from ytdl_archiver.setup.models import SetupAnswers
from ytdl_archiver.setup.ratatui_bridge import run_ratatui_setup


def test_run_ratatui_setup_success(monkeypatch, temp_dir):
    """Bridge returns parsed setup answers when subprocess succeeds."""
    fake_bin = temp_dir / "setup-ui"
    fake_bin.write_text("")
    monkeypatch.setenv("YTDL_ARCHIVER_SETUP_TUI_BIN", str(fake_bin))

    payload = {
        "archive_directory": "/tmp/media",
        "cookie_source": "browser",
        "cookie_browser": "firefox",
        "cookie_profile": "default",
        "write_subtitles": False,
        "write_thumbnail": True,
        "generate_nfo": False,
    }
    fake_run = Mock(
        return_value=subprocess.CompletedProcess(
            args=[str(fake_bin)],
            returncode=0,
        )
    )
    monkeypatch.setattr("ytdl_archiver.setup.ratatui_bridge.subprocess.run", fake_run)
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge.tempfile.TemporaryDirectory",
        _FakeTempDir.from_payload(temp_dir, payload),
    )

    result = run_ratatui_setup(SetupAnswers())

    assert result == SetupAnswers(
        archive_directory="/tmp/media",
        cookie_source="browser",
        cookie_browser="firefox",
        cookie_profile="default",
        write_subtitles=False,
        write_thumbnail=True,
        generate_nfo=False,
    )
    fake_run.assert_called_once()


def test_run_ratatui_setup_cancelled(monkeypatch, temp_dir):
    """Bridge returns None when setup exits with cancel status code."""
    fake_bin = temp_dir / "setup-ui"
    fake_bin.write_text("")
    monkeypatch.setenv("YTDL_ARCHIVER_SETUP_TUI_BIN", str(fake_bin))
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge.subprocess.run",
        Mock(
            return_value=subprocess.CompletedProcess(
                args=[str(fake_bin)],
                returncode=10,
            )
        ),
    )
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge.tempfile.TemporaryDirectory",
        _FakeTempDir.from_payload(temp_dir, None),
    )

    assert run_ratatui_setup(SetupAnswers()) is None


def test_run_ratatui_setup_invalid_json(monkeypatch, temp_dir):
    """Bridge raises ValueError for malformed result-file JSON."""
    fake_bin = temp_dir / "setup-ui"
    fake_bin.write_text("")
    monkeypatch.setenv("YTDL_ARCHIVER_SETUP_TUI_BIN", str(fake_bin))
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge.subprocess.run",
        Mock(
            return_value=subprocess.CompletedProcess(
                args=[str(fake_bin)],
                returncode=0,
            )
        ),
    )
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge.tempfile.TemporaryDirectory",
        _FakeTempDir.from_raw(temp_dir, "{not-json}"),
    )

    with pytest.raises(ValueError, match="invalid JSON"):
        run_ratatui_setup(SetupAnswers())


def test_run_ratatui_setup_nonzero_exit(monkeypatch, temp_dir):
    """Bridge raises RuntimeError when process exits with non-cancel error."""
    fake_bin = temp_dir / "setup-ui"
    fake_bin.write_text("")
    monkeypatch.setenv("YTDL_ARCHIVER_SETUP_TUI_BIN", str(fake_bin))
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge.subprocess.run",
        Mock(
            return_value=subprocess.CompletedProcess(
                args=[str(fake_bin)],
                returncode=2,
            )
        ),
    )
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge.tempfile.TemporaryDirectory",
        _FakeTempDir.from_payload(temp_dir, None),
    )

    with pytest.raises(RuntimeError, match="Ratatui setup failed"):
        run_ratatui_setup(SetupAnswers())


def test_run_ratatui_setup_missing_env_binary(monkeypatch):
    """Bridge fails fast when explicit binary override path does not exist."""
    missing = Path("/tmp/definitely-missing-binary-for-ratatui")
    monkeypatch.setenv("YTDL_ARCHIVER_SETUP_TUI_BIN", str(missing))

    with pytest.raises(FileNotFoundError, match="points to missing binary"):
        run_ratatui_setup(SetupAnswers())


def test_run_ratatui_setup_uses_cargo_fallback(monkeypatch):
    """Bridge does not attempt cargo fallback when binary is unavailable."""
    monkeypatch.delenv("YTDL_ARCHIVER_SETUP_TUI_BIN", raising=False)
    monkeypatch.setattr("ytdl_archiver.setup.ratatui_bridge._binary_candidates", lambda: [])

    with pytest.raises(FileNotFoundError, match="cargo build"):
        run_ratatui_setup(SetupAnswers())


def test_run_ratatui_setup_invokes_subprocess_without_pipes(monkeypatch, temp_dir):
    """Bridge executes subprocess with inherited stdio (no capture/input pipes)."""
    fake_bin = temp_dir / "setup-ui"
    fake_bin.write_text("")
    monkeypatch.setenv("YTDL_ARCHIVER_SETUP_TUI_BIN", str(fake_bin))
    payload = {
        "archive_directory": "~/Videos/media/youtube/",
        "cookie_source": "manual_file",
        "cookie_browser": "firefox",
        "cookie_profile": "",
        "write_subtitles": True,
        "write_thumbnail": True,
        "generate_nfo": True,
    }
    fake_run = Mock(
        return_value=subprocess.CompletedProcess(args=[str(fake_bin)], returncode=0)
    )
    monkeypatch.setattr("ytdl_archiver.setup.ratatui_bridge.subprocess.run", fake_run)
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge.tempfile.TemporaryDirectory",
        _FakeTempDir.from_payload(temp_dir, payload),
    )

    run_ratatui_setup(SetupAnswers())

    kwargs = fake_run.call_args.kwargs
    assert kwargs.get("check") is False
    assert "capture_output" not in kwargs
    assert "input" not in kwargs


def test_run_ratatui_setup_missing_result_file(monkeypatch, temp_dir):
    """Bridge raises when process succeeds without producing result output file."""
    fake_bin = temp_dir / "setup-ui"
    fake_bin.write_text("")
    monkeypatch.setenv("YTDL_ARCHIVER_SETUP_TUI_BIN", str(fake_bin))
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge.subprocess.run",
        Mock(return_value=subprocess.CompletedProcess(args=[str(fake_bin)], returncode=0)),
    )
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge.tempfile.TemporaryDirectory",
        _FakeTempDir.from_payload(temp_dir, None),
    )

    with pytest.raises(ValueError, match="did not produce a result file"):
        run_ratatui_setup(SetupAnswers())


class _FakeTempDir:
    def __init__(self, directory: Path, raw_result: str | None) -> None:
        self.directory = directory
        self.raw_result = raw_result

    def __enter__(self) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.raw_result is not None:
            (self.directory / "result.json").write_text(self.raw_result)
        return str(self.directory)

    def __exit__(self, *_args: object) -> None:
        return None

    @classmethod
    def from_payload(
        cls,
        temp_dir: Path,
        payload: dict[str, object] | None,
    ):
        raw = None if payload is None else json.dumps(payload)
        return lambda **_kwargs: cls(temp_dir / "fake-tempdir", raw)

    @classmethod
    def from_raw(cls, temp_dir: Path, raw_result: str):
        return lambda **_kwargs: cls(temp_dir / "fake-tempdir", raw_result)
