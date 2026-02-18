"""Command line interface for ytdl-archiver."""

import json
import sys
from pathlib import Path

import click
import toml

from . import __version__
from .config.settings import Config
from .core.archive import PlaylistArchiver
from .core.cookies import SUPPORTED_BROWSERS, BrowserCookieRefresher
from .core.utils import setup_logging
from .exceptions import ConfigurationError, CookieRefreshError
from .output import detect_output_mode, emit_rendered, get_formatter, should_use_colors
from .setup import SetupCancelled, render_setup_summary, run_setup

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


@click.group(invoke_without_command=True)
@click.option(
    "--config",
    "-c",
    type=click.Path(path_type=Path),
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
        help_requested = _is_help_invocation(ctx)
        config_path = config.expanduser() if config else Config.default_config_path()
        ctx.obj["config_path"] = config_path

        if ctx.invoked_subcommand == "init":
            return

        if not help_requested and not config_path.exists():
            try:
                setup_result = run_setup(config_path)
            except SetupCancelled:
                click.echo("Setup cancelled by user.", err=True)
                ctx.exit(130)
            except RuntimeError as e:
                click.echo(f"Error initializing application: {e}", err=True)
                ctx.exit(1)
            for line in render_setup_summary(setup_result):
                click.echo(line)
            ctx.exit(0)

        # Detect output mode and colors
        output_mode = detect_output_mode(verbose, quiet)
        use_colors = should_use_colors(no_color)

        # Store formatter and settings in context
        ctx.obj["config"] = Config(config_path)
        migrated_playlists = ctx.obj["config"].migrate_playlists_from_cwd()
        ctx.obj["output_mode"] = output_mode
        ctx.obj["use_colors"] = use_colors

        # Configure logging based on mode
        if verbose:
            ctx.obj["config"].set_logging_level("DEBUG")
        elif quiet:
            ctx.obj["config"].set_logging_level("ERROR")

        # Setup appropriate logging - no console output for clean formatter experience
        # Only enable console logging for verbose mode or errors
        console_output = output_mode.value == "verbose"
        setup_logging(ctx.obj["config"].as_dict(), console_output=console_output)

        logger.info("YTDL-Archiver started", version=__version__)
        if migrated_playlists:
            logger.info("Migrated playlists file", path=str(migrated_playlists))
        if ctx.invoked_subcommand is None and not help_requested:
            ctx.fail("Missing command.")

    except ConfigurationError as e:
        click.echo(f"Error initializing application: {e}", err=True)
        sys.exit(1)
    except (OSError, toml.TomlDecodeError, ValueError) as e:
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
@click.option(
    "--cookies-browser",
    type=click.Choice(SUPPORTED_BROWSERS, case_sensitive=False),
    help="Browser to refresh cookies from before archive",
)
@click.option(
    "--cookies-profile",
    type=str,
    help="Browser profile name or full profile path for cookie extraction",
)
@click.pass_context
def archive(
    ctx: click.Context,
    playlists: Path | None,
    directory: Path | None,
    cookies_browser: str | None,
    cookies_profile: str | None,
) -> None:
    """Archive YouTube playlists."""
    formatter = None
    try:
        config = ctx.obj["config"]
        output_mode = ctx.obj.get("output_mode", "progress")
        use_colors = ctx.obj.get("use_colors", True)

        if playlists:
            config.set_playlists_file(playlists)
        if directory:
            config.set_archive_directory(directory)

        # Validate configuration FIRST
        config.validate()

        # CRITICAL: Ensure playlists file exists BEFORE running archiver
        config.ensure_playlists_file()

        formatter = get_formatter(use_colors, show_progress=True, mode=output_mode)

        # Print header
        emit_rendered(formatter.header(__version__))

        cookie_refresher = None
        skip_initial_cookie_refresh = False
        normalized_browser = cookies_browser.lower() if cookies_browser else None
        effective_cookie_profile = cookies_profile

        if not normalized_browser:
            normalized_browser, configured_profile = _resolve_config_cookie_refresh(
                config,
                profile_override=cookies_profile,
            )
            effective_cookie_profile = configured_profile

        if normalized_browser:
            cookie_refresher = BrowserCookieRefresher()
            cookie_target = config.get_cookie_file_target_path()
            try:
                cookie_refresher.refresh_to_file(
                    normalized_browser,
                    effective_cookie_profile,
                    cookie_target,
                )
                skip_initial_cookie_refresh = True
            except (CookieRefreshError, OSError, ValueError, RuntimeError) as e:
                message = formatter.error(
                    f"Cookie refresh failed at startup (browser={normalized_browser}) - {e!s}"
                )
                if message:
                    click.echo(message, err=True)
                sys.exit(1)

        archiver = PlaylistArchiver(
            config,
            formatter,
            cookie_refresher=cookie_refresher,
            cookie_browser=normalized_browser,
            cookie_profile=effective_cookie_profile,
            skip_initial_cookie_refresh=skip_initial_cookie_refresh,
        )
        archiver.run()  # Will now safely load playlists from config directory

    except KeyboardInterrupt:
        if formatter:
            message = formatter.error("Operation cancelled by user")
            if message:
                click.echo(message, err=True)
        else:
            click.echo("Operation cancelled by user", err=True)
        sys.exit(130)
    except (ConfigurationError, CookieRefreshError, OSError, RuntimeError) as e:
        if formatter:
            message = formatter.error(f"Archive failed - {e!s}")
            if message:
                click.echo(message, err=True)
        else:
            click.echo(f"Archive failed - {e!s}", err=True)
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
        with input.open() as f:
            playlists = json.load(f)

        # Convert to TOML format
        toml_data = {"playlists": playlists}

        # Write TOML file
        with output.open("w") as f:
            toml.dump(toml_data, f)

        click.echo(f"Converted {input} to {output}")

    except (json.JSONDecodeError, OSError, toml.TomlDecodeError, ValueError) as e:
        click.echo(f"Error converting playlists: {e}", err=True)
        sys.exit(1)


@cli.command(name="init")
@click.pass_context
def init_setup(ctx: click.Context) -> None:
    """Run interactive setup and generate first-run template files."""
    try:
        config_path = Path(ctx.obj.get("config_path", Config.default_config_path()))
        setup_result = run_setup(config_path)
        for line in render_setup_summary(setup_result):
            click.echo(line)
    except SetupCancelled:
        click.echo("Setup cancelled by user.", err=True)
        sys.exit(130)
    except (OSError, RuntimeError, ValueError) as e:
        click.echo(f"Error running setup: {e}", err=True)
        sys.exit(1)


def _is_help_invocation(ctx: click.Context) -> bool:
    """Return True when invocation appears to be a help request."""
    help_flags = set(ctx.help_option_names)
    help_flags.add("-h")

    argv_tokens = list(sys.argv[1:])
    if any(token in help_flags for token in argv_tokens):
        return True

    parsed_tokens = list(ctx.args)
    return any(token in help_flags for token in parsed_tokens)


def _resolve_config_cookie_refresh(
    config: Config,
    profile_override: str | None,
) -> tuple[str | None, str | None]:
    """Resolve cookie refresh settings from config when CLI flag is absent."""
    cookie_source = str(config.get("cookies.source", "manual_file")).lower()
    refresh_on_startup = bool(config.get("cookies.refresh_on_startup", True))
    if cookie_source != "browser" or not refresh_on_startup:
        return None, None

    browser = config.get("cookies.browser")
    if not browser:
        return None, None

    profile = profile_override
    if profile is None:
        configured_profile = config.get("cookies.profile")
        if configured_profile:
            profile = str(configured_profile)

    return str(browser).lower(), profile


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
