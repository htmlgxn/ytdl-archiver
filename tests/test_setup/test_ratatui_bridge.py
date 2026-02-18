"""Tests for the Rust ratatui setup bridge."""

import json
import subprocess
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest

import ytdl_archiver.setup.ratatui_bridge as bridge
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


def test_run_ratatui_setup_fails_when_autobuild_disabled(monkeypatch):
    """Bridge fails with guidance when autobuild and all binary sources are absent."""
    monkeypatch.delenv("YTDL_ARCHIVER_SETUP_TUI_BIN", raising=False)
    monkeypatch.setenv("YTDL_ARCHIVER_SETUP_TUI_AUTOBUILD", "0")
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge._packaged_binary_candidates",
        lambda: [],
    )
    monkeypatch.setattr("ytdl_archiver.setup.ratatui_bridge._binary_candidates", lambda: [])

    with pytest.raises(FileNotFoundError, match=r"AUTOBUILD=0"):
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


def test_run_ratatui_setup_uses_packaged_binary_candidate(monkeypatch, temp_dir):
    """Bridge prefers packaged binary candidates when env override is absent."""
    fake_bin = temp_dir / "packaged-setup-ui"
    fake_bin.write_text("")
    monkeypatch.delenv("YTDL_ARCHIVER_SETUP_TUI_BIN", raising=False)
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge._packaged_binary_candidates",
        lambda: [fake_bin],
    )
    monkeypatch.setattr("ytdl_archiver.setup.ratatui_bridge._binary_candidates", lambda: [])
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge.resources.as_file",
        lambda candidate: nullcontext(candidate),
    )
    payload = {
        "archive_directory": "/tmp/media",
        "cookie_source": "browser",
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

    command = fake_run.call_args.args[0]
    assert command[0] == str(fake_bin)


def test_run_ratatui_setup_prefers_local_binary_over_packaged(monkeypatch, temp_dir):
    """Bridge should prefer local builds over packaged binaries in source checkouts."""
    local_bin = temp_dir / "local-setup-ui"
    packaged_bin = temp_dir / "packaged-setup-ui"
    local_bin.write_text("")
    packaged_bin.write_text("")
    monkeypatch.delenv("YTDL_ARCHIVER_SETUP_TUI_BIN", raising=False)
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge._binary_candidates",
        lambda: [local_bin],
    )
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge._packaged_binary_candidates",
        lambda: [packaged_bin],
    )
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge.resources.as_file",
        lambda candidate: nullcontext(candidate),
    )
    payload = {
        "archive_directory": "/tmp/media",
        "cookie_source": "browser",
        "cookie_browser": "firefox",
        "cookie_profile": "",
        "write_subtitles": True,
        "write_thumbnail": True,
        "generate_nfo": True,
    }
    fake_run = Mock(
        return_value=subprocess.CompletedProcess(args=[str(local_bin)], returncode=0)
    )
    monkeypatch.setattr("ytdl_archiver.setup.ratatui_bridge.subprocess.run", fake_run)
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge.tempfile.TemporaryDirectory",
        _FakeTempDir.from_payload(temp_dir, payload),
    )

    run_ratatui_setup(SetupAnswers())

    command = fake_run.call_args.args[0]
    assert command[0] == str(local_bin)


def test_run_ratatui_setup_rebuilds_stale_local_binary(monkeypatch, temp_dir):
    """Stale local binaries should trigger autobuild before running setup."""
    stale_bin = temp_dir / "stale-setup-ui"
    fresh_bin = temp_dir / "fresh-setup-ui"
    stale_bin.write_text("")
    monkeypatch.delenv("YTDL_ARCHIVER_SETUP_TUI_BIN", raising=False)
    monkeypatch.setenv("YTDL_ARCHIVER_SETUP_TUI_AUTOBUILD", "1")
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge._binary_candidates",
        lambda: [stale_bin, fresh_bin],
    )
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge._packaged_binary_candidates",
        lambda: [],
    )
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge._local_binary_is_stale",
        lambda candidate: candidate == stale_bin,
    )
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge._attempt_autobuild_binary",
        lambda _timeout: fresh_bin.write_text(""),
    )
    payload = {
        "archive_directory": "/tmp/media",
        "cookie_source": "browser",
        "cookie_browser": "firefox",
        "cookie_profile": "",
        "write_subtitles": True,
        "write_thumbnail": True,
        "generate_nfo": True,
    }
    fake_run = Mock(
        return_value=subprocess.CompletedProcess(args=[str(fresh_bin)], returncode=0)
    )
    monkeypatch.setattr("ytdl_archiver.setup.ratatui_bridge.subprocess.run", fake_run)
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge.tempfile.TemporaryDirectory",
        _FakeTempDir.from_payload(temp_dir, payload),
    )

    run_ratatui_setup(SetupAnswers())

    command = fake_run.call_args.args[0]
    assert command[0] == str(fresh_bin)


def test_run_ratatui_setup_attempts_autobuild_when_no_binary(monkeypatch, temp_dir):
    """Bridge tries autobuild path and then runs the newly-available binary."""
    fake_bin = temp_dir / "built-setup-ui"
    monkeypatch.delenv("YTDL_ARCHIVER_SETUP_TUI_BIN", raising=False)
    monkeypatch.setenv("YTDL_ARCHIVER_SETUP_TUI_AUTOBUILD", "1")
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge._packaged_binary_candidates",
        lambda: [],
    )
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge._binary_candidates",
        lambda: [fake_bin],
    )
    monkeypatch.setattr(
        "ytdl_archiver.setup.ratatui_bridge._attempt_autobuild_binary",
        lambda _timeout: fake_bin.write_text(""),
    )
    payload = {
        "archive_directory": "/tmp/media",
        "cookie_source": "browser",
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

    command = fake_run.call_args.args[0]
    assert command[0] == str(fake_bin)


def test_attempt_autobuild_binary_reports_missing_cargo(monkeypatch):
    """Autobuild reports missing cargo with a clear actionable message."""
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        Mock(side_effect=FileNotFoundError("cargo not found")),
    )
    with pytest.raises(FileNotFoundError, match="cargo"):
        bridge._attempt_autobuild_binary(300)


def test_attempt_autobuild_binary_reports_compile_failure(monkeypatch):
    """Autobuild surfaces compile command failure details."""
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        Mock(
            side_effect=[
                subprocess.CompletedProcess(args=["cargo"], returncode=2),
            ]
        ),
    )
    with pytest.raises(FileNotFoundError, match="cargo exit=2"):
        bridge._attempt_autobuild_binary(300)


def test_attempt_autobuild_binary_reports_stage_failure(monkeypatch):
    """Autobuild surfaces staging script failure details."""
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        Mock(
            side_effect=[
                subprocess.CompletedProcess(args=["cargo"], returncode=0),
                subprocess.CompletedProcess(args=["python"], returncode=3),
            ]
        ),
    )
    with pytest.raises(FileNotFoundError, match="stage exit=3"):
        bridge._attempt_autobuild_binary(300)


def test_attempt_autobuild_binary_reports_timeout(monkeypatch):
    """Autobuild reports command timeout clearly."""
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        Mock(side_effect=subprocess.TimeoutExpired(cmd=["cargo"], timeout=300)),
    )
    with pytest.raises(FileNotFoundError, match="timed out"):
        bridge._attempt_autobuild_binary(300)


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
