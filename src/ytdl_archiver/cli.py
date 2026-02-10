"""Command line interface for ytdl-archiver."""

import json
import sys
from pathlib import Path

import click
import toml

from .config.settings import Config
from .core.archive import PlaylistArchiver
from .core.utils import setup_logging
from .output import detect_output_mode, should_use_colors

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
    help="Enable verbose logging with full yt-dlp output",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Minimal output - errors and summary only",
)
@click.option(
    "--no-color",
    is_flag=True,
    help="Disable colors and emoji in output",
)
@click.pass_context
def cli(
    ctx: click.Context,
    config: Path | None,
    verbose: bool,
    quiet: bool,
    no_color: bool,
) -> None:
    """YTDL-Archiver: Modern YouTube playlist archiver."""
    try:
        ctx.ensure_object(dict)

        # Detect output mode and colors
        output_mode = detect_output_mode(verbose, quiet)
        use_colors = should_use_colors(no_color)

        # Store formatter and settings in context
        ctx.obj["config"] = Config(config)
        ctx.obj["output_mode"] = output_mode
        ctx.obj["use_colors"] = use_colors

        # Configure logging based on mode
        if verbose:
            ctx.obj["config"]._config["logging"]["level"] = "DEBUG"
        elif quiet:
            ctx.obj["config"]._config["logging"]["level"] = "ERROR"

        # Setup appropriate logging - no console output for clean formatter experience
        # Only enable console logging for verbose mode or errors
        console_output = verbose or ctx.obj.get("output_mode") == "verbose"
        setup_logging(ctx.obj["config"]._config, console_output=console_output)

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
def archive(ctx: click.Context, playlists: Path | None, directory: Path | None) -> None:
    """Archive YouTube playlists."""
    try:
        config = ctx.obj["config"]
        output_mode = ctx.obj.get("output_mode", "progress")
        use_colors = ctx.obj.get("use_colors", True)

        if playlists:
            config._config["playlists_file"] = str(playlists)
        if directory:
            config._config["archive"]["base_directory"] = str(directory)

        # Validate configuration FIRST
        config.validate()

        # CRITICAL: Ensure playlists file exists BEFORE running archiver
        config.ensure_playlists_file()

        # Get appropriate formatter
        from .output import get_formatter

        formatter = get_formatter(use_colors, show_progress=True, mode=output_mode)

        # Print header
        print(formatter.header("2.0.0"))

        archiver = PlaylistArchiver(config, formatter)
        archiver.run()  # Will now safely load playlists from config directory

    except KeyboardInterrupt:
        formatter.error("Operation cancelled by user")
        sys.exit(130)
    except Exception as e:
        formatter.error(f"Archive failed - {e!s}")
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
def convert_playlists(input: Path, output: Path | None) -> None:
    """Convert JSON playlists file to TOML format."""
    try:
        if output is None:
            output = input.with_suffix(".toml")

        # Load JSON playlists
        with open(input) as f:
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
def init_config(output: Path | None) -> None:
    """Initialize configuration file."""
    if output is None:
        output = Path.home() / ".config" / "ytdl-archiver" / "config.toml"

    output.parent.mkdir(parents=True, exist_ok=True)

    # Copy default configuration
    import toml

    defaults_path = Path(__file__).parent / "config" / "defaults.toml"

    try:
        with open(defaults_path) as f:
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
