"""Setup orchestration entry points."""

from pathlib import Path

from .fallback_prompts import (
    collect_non_interactive_answers,
    collect_prompt_answers,
    is_interactive_session,
)
from .models import SetupAnswers, SetupRunResult
from .ratatui_bridge import run_ratatui_setup
from .writer import write_setup_files


class SetupCancelled(RuntimeError):
    """Raised when the user cancels setup intentionally."""


def run_setup(config_path: Path, prefer_ratatui: bool = True) -> SetupRunResult:
    """Run first-run setup and write generated files."""
    defaults = SetupAnswers()
    ui_error: str | None = None

    if not is_interactive_session():
        answers = collect_non_interactive_answers(defaults)
        ui_mode = "non_interactive"
    elif prefer_ratatui:
        try:
            ratatui_answers = run_ratatui_setup(defaults)
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
            ui_error = str(exc)
            answers = collect_prompt_answers(defaults)
            ui_mode = "prompt"
        else:
            if ratatui_answers is None:
                raise SetupCancelled("Setup was cancelled")
            answers = ratatui_answers
            ui_mode = "ratatui"
    else:
        answers = collect_prompt_answers(defaults)
        ui_mode = "prompt"

    write_result = write_setup_files(config_path, answers)
    return SetupRunResult(
        answers=answers,
        write_result=write_result,
        ui_mode=ui_mode,
        ui_error=ui_error,
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
        "Run archive: ytdl-archiver archive",
        "Help: ytdl-archiver --help",
    ]

    if result.ui_mode == "non_interactive":
        lines.insert(
            2,
            "Interactive setup skipped (stdin/stdout not TTY); defaults were applied.",
        )

    if result.ui_error:
        lines.insert(
            2,
            f"Ratatui UI unavailable, used prompt fallback: {result.ui_error}",
        )
    return lines
