"""Command line interface for ytdl-archiver."""

import json
import sys
from pathlib import Path
from typing import Optional

import click
import toml

from .config.settings import Config
from .core.archive import PlaylistArchiver
from .core.utils import setup_logging
from .exceptions import YTDLArchiverError

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


@click.group()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose logging",
)
@click.pass_context
def cli(ctx: click.Context, config: Optional[Path], verbose: bool) -> None:
    """YTDL-Archiver: Modern YouTube playlist archiver."""
    try:
        ctx.ensure_object(dict)
        ctx.obj["config"] = Config(config)

        if verbose:
            ctx.obj["config"]._config["logging"]["level"] = "DEBUG"

        setup_logging(ctx.obj["config"]._config)

        logger.info("YTDL-Archiver started", version="2.0.0")

    except Exception as e:
        click.echo(f"Error initializing application: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--playlists",
    "-p",
    type=click.Path(exists=True, path_type=Path),
    help="Path to playlists file (JSON or TOML)",
)
@click.option(
    "--directory",
    "-d",
    type=click.Path(path_type=Path),
    help="Archive directory path",
)
@click.pass_context
def archive(
    ctx: click.Context, playlists: Optional[Path], directory: Optional[Path]
) -> None:
    """Archive YouTube playlists."""
    try:
        config = ctx.obj["config"]

        if playlists:
            config._config["playlists_file"] = str(playlists)
        if directory:
            config._config["archive"]["base_directory"] = str(directory)

        # Validate configuration
        config.validate()

        archiver = PlaylistArchiver(config)
        archiver.run()

    except YTDLArchiverError as e:
        logger.error("Archiving failed", error=str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Archiving interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error("Unexpected error", error=str(e))
        sys.exit(1)


@cli.command()
@click.option(
    "--input",
    "-i",
    type=click.Path(exists=True, path_type=Path),
    help="Input JSON playlists file",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output TOML playlists file",
)
def convert_playlists(input: Path, output: Optional[Path]) -> None:
    """Convert JSON playlists file to TOML format."""
    try:
        if output is None:
            output = input.with_suffix(".toml")
        
        # Load JSON playlists
        with open(input, "r") as f:
            playlists = json.load(f)
        
        # Convert to TOML format
        toml_data = {"playlists": playlists}
        
        # Write TOML file
        with open(output, "w") as f:
            toml.dump(toml_data, f)
        
        click.echo(f"Converted {input} to {output}")
        
    except Exception as e:
        click.echo(f"Error converting playlists: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output path for configuration file",
)
def init_config(output: Optional[Path]) -> None:
    """Initialize configuration file."""
    if output is None:
        output = Path.home() / ".config" / "ytdl-archiver" / "config.toml"

    output.parent.mkdir(parents=True, exist_ok=True)

    # Copy default configuration
    import toml

    defaults_path = Path(__file__).parent / "config" / "defaults.toml"

    try:
        with open(defaults_path, "r") as f:
            default_config = toml.load(f)

        with open(output, "w") as f:
            toml.dump(default_config, f)

        click.echo(f"Configuration file created at: {output}")
        click.echo("Edit this file to customize your archiver settings.")

    except Exception as e:
        click.echo(f"Error creating configuration file: {e}", err=True)
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
