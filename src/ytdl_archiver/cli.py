"""Command line interface for ytdl-archiver."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import click
import toml

from . import __version__
from .config.settings import Config
from .core.archive import PlaylistArchiver
from .core.cookies import SUPPORTED_BROWSERS, BrowserCookieRefresher
from .core.dedupe import run_dedupe
from .core.metadata_backfill import MetadataBackfiller
from .core.playlist_writer import PlaylistEntry, PlaylistWriter
from .core.search import InvidiousSearchService, SearchResult
from .core.utils import setup_logging
from .exceptions import (
    ConfigurationError,
    CookieRefreshError,
    PlaylistWriteError,
    SearchError,
)
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
    help="Enable structured verbose diagnostics (no raw yt-dlp passthrough)",
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
    help="Disable colored text in output",
)
@click.pass_context
def cli(
    ctx: click.Context,
    config: Path | None,
    verbose: bool,
    quiet: bool,
    no_color: bool,
) -> None:
    """ytdl-archiver: Modern YouTube playlist archiver."""
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

        # Setup logging. Verbose mode enables debug diagnostics on console while
        # keeping info-level summary logs out of the way.
        console_output = output_mode.value == "verbose"
        console_level = "DEBUG" if console_output else "WARNING"
        setup_logging(
            ctx.obj["config"].as_dict(),
            console_output=console_output,
            console_level=console_level,
        )

        logger.info("ytdl-archiver started", extra={"version": __version__})
        if migrated_playlists:
            logger.info(
                "Migrated playlists file", extra={"path": str(migrated_playlists)}
            )
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
        emit_rendered(formatter.logo_header())
        emit_rendered(formatter.header(__version__))
        emit_rendered(formatter.archive_directory(str(config.get_archive_directory())))

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
                    f"Cookie refresh failed at startup "
                    f"(browser={normalized_browser}) - {e!s}"
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


@cli.command(name="metadata-backfill")
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
    help="Browser to refresh cookies from before metadata-backfill",
)
@click.option(
    "--cookies-profile",
    type=str,
    help="Browser profile name or full profile path for cookie extraction",
)
@click.option(
    "--scope",
    type=click.Choice(["full", "info-json"], case_sensitive=False),
    default="full",
    show_default=True,
    help="Metadata sidecar scope to fetch",
)
@click.option(
    "--refresh-existing/--no-refresh-existing",
    default=False,
    show_default=True,
    help="Refresh metadata sidecars when .info.json already exists",
)
@click.option(
    "--limit-per-playlist",
    type=click.IntRange(min=1),
    default=None,
    help="Maximum archived videos to process for each playlist",
)
@click.option(
    "--continue-on-error/--fail-fast",
    default=True,
    show_default=True,
    help="Continue processing remaining videos after a failure",
)
@click.pass_context
def metadata_backfill(
    ctx: click.Context,
    playlists: Path | None,
    directory: Path | None,
    cookies_browser: str | None,
    cookies_profile: str | None,
    scope: str,
    refresh_existing: bool,
    limit_per_playlist: int | None,
    continue_on_error: bool,
) -> None:
    """Backfill metadata sidecars for archived videos in .archive.txt."""
    formatter = None
    try:
        config = ctx.obj["config"]
        output_mode = ctx.obj.get("output_mode", "progress")
        use_colors = ctx.obj.get("use_colors", True)

        if playlists:
            config.set_playlists_file(playlists)
        if directory:
            config.set_archive_directory(directory)

        config.validate()
        config.ensure_playlists_file()

        formatter = get_formatter(use_colors, show_progress=False, mode=output_mode)

        emit_rendered(formatter.logo_header())
        emit_rendered(formatter.header(__version__))
        emit_rendered(formatter.archive_directory(str(config.get_archive_directory())))

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
            cookie_refresher.refresh_to_file(
                normalized_browser,
                effective_cookie_profile,
                cookie_target,
            )

        backfiller = MetadataBackfiller(config, formatter)
        backfiller.run(
            scope=scope.lower(),
            refresh_existing=refresh_existing,
            limit_per_playlist=limit_per_playlist,
            continue_on_error=continue_on_error,
        )

    except KeyboardInterrupt:
        if formatter:
            message = formatter.error("Operation cancelled by user")
            if message:
                click.echo(message, err=True)
        else:
            click.echo("Operation cancelled by user", err=True)
        sys.exit(130)
    except (ConfigurationError, CookieRefreshError, OSError, RuntimeError, ValueError) as e:
        if formatter:
            message = formatter.error(f"Metadata backfill failed - {e!s}")
            if message:
                click.echo(message, err=True)
        else:
            click.echo(f"Metadata backfill failed - {e!s}", err=True)
        sys.exit(1)


@cli.command(name="dedupe")
@click.argument("source_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument(
    "archive_dir",
    required=False,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option("--trash-dir", type=click.Path(file_okay=False, path_type=Path))
@click.option("--delete", is_flag=True, help="Permanently delete loser artifacts")
@click.option("--dry-run", is_flag=True, help="Print planned changes without modifying files")
@click.option("--verbose", is_flag=True, help="Show per-duplicate detail")
@click.pass_context
def dedupe_cmd(
    ctx: click.Context,
    source_dir: Path,
    archive_dir: Path | None,
    trash_dir: Path | None,
    delete: bool,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Merge videos from SOURCE_DIR into ARCHIVE_DIR."""
    if bool(trash_dir) == bool(delete):
        raise click.UsageError("Specify exactly one of --trash-dir or --delete.")

    formatter = None
    try:
        config = ctx.obj["config"]
        output_mode = ctx.obj.get("output_mode", "progress")
        use_colors = ctx.obj.get("use_colors", True)

        formatter = get_formatter(use_colors, show_progress=False, mode=output_mode)

        effective_dir1 = source_dir.expanduser().resolve()
        effective_dir2 = (
            archive_dir.expanduser().resolve()
            if archive_dir is not None
            else config.get_archive_directory().resolve()
        )
        if effective_dir1 == effective_dir2:
            raise click.UsageError(
                "SOURCE_DIR and ARCHIVE_DIR must resolve to different directories."
            )

        emit_rendered(formatter.logo_header())
        emit_rendered(formatter.header(__version__))
        emit_rendered(formatter.archive_directory(str(effective_dir2)))
        emit_rendered(f"Source directory: {effective_dir1}")

        summary = run_dedupe(
            effective_dir1,
            effective_dir2,
            trash_dir=trash_dir.expanduser() if trash_dir else None,
            delete=delete,
            dry_run=dry_run,
            verbose=verbose,
            config=config,
        )

        if dry_run:
            emit_rendered("Dry run: no files were modified.")

        for detail in summary["details"]:
            emit_rendered(f"{detail['action']}: {detail['match_method']}={detail['match_key']}")
            for operation in detail["operations"]:
                kind = str(operation["kind"]).upper().replace("_FILE", "")
                origin = str(operation["origin"]).upper()
                source_path = operation.get("source_path") or ""
                target_path = operation.get("target_path") or ""
                reason = operation.get("reason") or ""
                if target_path:
                    emit_rendered(
                        f"  {kind:<8} {origin:<7} {source_path} -> {target_path} ({reason})"
                    )
                else:
                    emit_rendered(
                        f"  {kind:<8} {origin:<7} {source_path} ({reason})"
                    )

        emit_rendered(
            "Dedupe complete. "
            f"processed: {summary['processed_sets']}, "
            f"imported: {summary['imported_sets']}, "
            f"replaced: {summary['replaced_sets']}, "
            f"merged: {summary['merged_sets']}, "
            f"sidecars copied: {summary['sidecars_copied']}, "
            f"archive renames: {summary['archive_winners_renamed']}"
        )

    except KeyboardInterrupt:
        if formatter:
            message = formatter.error("Operation cancelled by user")
            if message:
                click.echo(message, err=True)
        else:
            click.echo("Operation cancelled by user", err=True)
        sys.exit(130)
    except (ConfigurationError, OSError, RuntimeError, ValueError) as e:
        if formatter:
            message = formatter.error(f"Dedupe failed - {e!s}")
            if message:
                click.echo(message, err=True)
        else:
            click.echo(f"Dedupe failed - {e!s}", err=True)
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


@cli.command()
@click.argument("query", required=False)
@click.option(
    "--include-playlists",
    is_flag=True,
    help="Include playlist discovery in search results",
)
@click.pass_context
def search(ctx: click.Context, query: str | None, include_playlists: bool) -> None:
    """Search channels/playlists and add selected entries to playlists.toml."""
    formatter = None
    try:
        config = ctx.obj["config"]
        output_mode = ctx.obj.get("output_mode", "progress")
        use_colors = ctx.obj.get("use_colors", True)
        formatter = get_formatter(use_colors, show_progress=False, mode=output_mode)

        search_query = (query or "").strip()
        if not search_query:
            search_query = click.prompt("Search query", type=str).strip()
        if not search_query:
            message = formatter.error("Search query cannot be empty")
            if message:
                click.echo(message, err=True)
            sys.exit(1)

        service = InvidiousSearchService(config)
        results = service.search(search_query, include_playlists=include_playlists)
        if not results:
            emit_rendered(formatter.warning("No matching channels or playlists found"))
            return
        backend_used = service.last_backend_used or "unknown"
        channel_candidates = sum(
            1 for result in results if result.result_type == "channel"
        )
        formatter_info = getattr(formatter, "info", None)
        summary = f"Found {channel_candidates} channel candidates via {backend_used}"
        if callable(formatter_info):
            info_line = formatter_info(summary)
            if info_line:
                emit_rendered(info_line)
        else:
            emit_rendered(summary)

        selected, cancelled = _select_search_results(results)
        if cancelled:
            emit_rendered(formatter.warning("Selection cancelled"))
            return
        if not selected:
            emit_rendered(formatter.warning("No results selected"))
            return

        entries: list[PlaylistEntry] = []
        for item in selected:
            default_path = _slugify_path(item.channel_name or item.title)
            prompted = click.prompt(
                f'Archive path for "{item.title}"',
                default=default_path,
                show_default=True,
                type=str,
            )
            entries.append(
                PlaylistEntry(
                    id=item.archive_id,
                    path=prompted.strip() or default_path,
                    name=item.title,
                )
            )

        writer = PlaylistWriter(config.get_playlists_file())
        added, skipped = writer.append_entries(entries)
        emit_rendered(
            f"Search selection complete. Added: {added}, "
            f"skipped duplicates: {skipped}"
        )

    except KeyboardInterrupt:
        if formatter:
            message = formatter.error("Operation cancelled by user")
            if message:
                click.echo(message, err=True)
        else:
            click.echo("Operation cancelled by user", err=True)
        sys.exit(130)
    except (SearchError, PlaylistWriteError, OSError, ValueError, RuntimeError) as e:
        if formatter:
            message = formatter.error(f"Search failed - {e!s}")
            if message:
                click.echo(message, err=True)
        else:
            click.echo(f"Search failed - {e!s}", err=True)
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


def _result_type_label(result_type: str) -> str:
    if result_type == "channel":
        return "channel"
    return "playlist"


def _format_result_metric(result: SearchResult) -> str:
    if result.result_type == "channel":
        if result.subscriber_count is not None:
            return f"subs:{result.subscriber_count}"
        return "subs:unknown"
    if result.video_count is not None:
        return f"videos:{result.video_count}"
    return "videos:unknown"


def _short_description(text: str, limit: int = 60) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _format_result_row(index: int, result: SearchResult) -> str:
    return (
        f"{index}\t"
        f"[{_result_type_label(result.result_type)}] {result.title}\t"
        f"{result.channel_name}\t"
        f"{_format_result_metric(result)}\t"
        f"{result.archive_id}\t"
        f"{_short_description(result.description)}"
    )


def _select_with_fzf(
    results: list[SearchResult]
) -> tuple[list[SearchResult], bool] | None:
    if not shutil.which("fzf"):
        return None

    rows = [_format_result_row(idx, result) for idx, result in enumerate(results, start=1)]
    payload = "\n".join(rows) + "\n"
    process = subprocess.run(
        [
            "fzf",
            "-m",
            "--delimiter=\t",
            "--with-nth=2..",
            "--prompt=Select channels/playlists > ",
        ],
        input=payload,
        text=True,
        stdout=subprocess.PIPE,
        stderr=None,
        check=False,
    )
    if process.returncode == 130:
        return [], True
    if process.returncode != 0:
        return [], False
    if not process.stdout.strip():
        return [], False

    selected_indexes: list[int] = []
    for line in process.stdout.splitlines():
        first_col = line.split("\t", 1)[0].strip()
        if first_col.isdigit():
            selected_indexes.append(int(first_col))

    mapped: list[SearchResult] = []
    for index in selected_indexes:
        if 1 <= index <= len(results):
            mapped.append(results[index - 1])
    return mapped, False


def _select_with_numbered_menu(results: list[SearchResult]) -> list[SearchResult]:
    emit_rendered("fzf not found (or no selection). Using numbered selector:")
    for index, result in enumerate(results, start=1):
        emit_rendered(f"{index}. [{_result_type_label(result.result_type)}] {result.title} -> {result.archive_id}")

    raw = click.prompt(
        "Select one or more entries (comma-separated numbers)",
        default="",
        show_default=False,
        type=str,
    ).strip()
    if not raw:
        return []

    values = [token.strip() for token in raw.split(",") if token.strip()]
    selected: list[SearchResult] = []
    seen: set[int] = set()
    for token in values:
        if not token.isdigit():
            continue
        index = int(token)
        if index in seen or index < 1 or index > len(results):
            continue
        selected.append(results[index - 1])
        seen.add(index)
    return selected


def _select_search_results(results: list[SearchResult]) -> tuple[list[SearchResult], bool]:
    selected = _select_with_fzf(results)
    if selected is not None:
        return selected
    return _select_with_numbered_menu(results), False


def _slugify_path(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = normalized.strip("-")
    return slug or "untitled"


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
