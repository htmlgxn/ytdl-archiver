"""Setup orchestration entry points."""

from pathlib import Path
from typing import Never

from .fallback_prompts import (
    collect_non_interactive_answers,
    collect_prompt_answers,
    is_interactive_session,
)
from .models import SetupAnswers, SetupRunResult
from .writer import write_setup_files


def _raise_setup_cancelled() -> Never:
    raise RuntimeError("Setup was cancelled")


def run_setup(config_path: Path, prefer_textual: bool = True) -> SetupRunResult:
    """Run first-run setup and write generated files."""
    defaults = SetupAnswers()
    textual_error: str | None = None

    if not is_interactive_session():
        answers = collect_non_interactive_answers(defaults)
        ui_mode = "non_interactive"
    elif prefer_textual:
        try:
            from .textual_app import run_textual_setup

            textual_answers = run_textual_setup(defaults)
            if textual_answers is None:
                _raise_setup_cancelled()
            answers = textual_answers
            ui_mode = "textual"
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            textual_error = str(exc)
            answers = collect_prompt_answers(defaults)
            ui_mode = "prompt"
    else:
        answers = collect_prompt_answers(defaults)
        ui_mode = "prompt"

    write_result = write_setup_files(config_path, answers)
    return SetupRunResult(
        answers=answers,
        write_result=write_result,
        ui_mode=ui_mode,
        textual_error=textual_error,
    )


def render_setup_summary(result: SetupRunResult) -> list[str]:
    """Render user-facing setup summary lines."""
    cfg_state = "created" if result.write_result.created_config else "already exists"
    playlists_state = (
        "created" if result.write_result.created_playlists else "already exists"
    )
    archive_state = (
        "created"
        if result.write_result.created_archive_directory
        else "already existed"
    )

    lines = [
        "",
        "ytdl-archiver first-run setup complete",
        f"Config file ({cfg_state}): {result.write_result.config_path}",
        f"Playlists file ({playlists_state}): {result.write_result.playlists_path}",
        f"Archive directory ({archive_state}): {result.write_result.archive_directory}",
        "",
        f"Edit config: {result.write_result.config_path}",
        f"Add playlists: {result.write_result.playlists_path}",
        "",
        "Run archive: uv run ytdl-archiver archive",
        "Help: uv run ytdl-archiver --help",
    ]

    if result.textual_error:
        lines.insert(
            2,
            f"Textual UI unavailable, used prompt fallback: {result.textual_error}",
        )
    return lines
