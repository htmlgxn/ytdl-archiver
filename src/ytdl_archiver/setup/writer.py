"""Write setup outputs to disk."""

from pathlib import Path

from .models import SetupAnswers, SetupWriteResult
from .templates import render_config_template, render_playlists_template


def write_setup_files(config_path: Path, answers: SetupAnswers) -> SetupWriteResult:
    """Create config and playlists templates without overwriting existing files."""
    target_config = config_path.expanduser()
    target_dir = target_config.parent
    playlists_path = target_dir / "playlists.toml"

    target_dir.mkdir(parents=True, exist_ok=True)

    archive_directory = Path(answers.archive_directory).expanduser()
    archive_preexisting = archive_directory.exists()
    archive_directory.mkdir(parents=True, exist_ok=True)

    created_config = False
    if not target_config.exists():
        target_config.write_text(render_config_template(answers), encoding="utf-8")
        created_config = True

    created_playlists = False
    if not playlists_path.exists():
        playlists_path.write_text(render_playlists_template(), encoding="utf-8")
        created_playlists = True

    return SetupWriteResult(
        config_path=target_config,
        playlists_path=playlists_path,
        archive_directory=archive_directory,
        created_config=created_config,
        created_playlists=created_playlists,
        created_archive_directory=not archive_preexisting,
    )
