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


def _rel(path_str: str, *bases: Path) -> str:
    p = Path(path_str)
    for base in bases:
        try:
            return str(p.relative_to(base))
        except ValueError:
            pass
    return path_str


def _format_size(size_bytes: int | None) -> str:
    """Format bytes as compact mb string."""
    if size_bytes is None:
        return ""
    return f"-{size_bytes / (1024 * 1024):.2f}mb"


def _file_ext(name: str) -> str:
    """Return multi-part extension (e.g. '.info.json', '.en.srt')."""
    lower = name.lower()
    for multi in (".info.json", ".metadata.json"):
        if lower.endswith(multi):
            return name[len(name) - len(multi):]
    p = Path(name)
    if len(p.suffixes) >= 2:
        from ytdl_archiver.core.dedupe import _SUBTITLE_EXTENSIONS, _LANGUAGE_TOKEN_RE
        if p.suffixes[-1].lower() in _SUBTITLE_EXTENSIONS and _LANGUAGE_TOKEN_RE.fullmatch(p.suffixes[-2]):
            return p.suffixes[-2] + p.suffixes[-1]
    return p.suffix


def _file_stem(name: str) -> str:
    """Return stem by stripping multi-part extension."""
    ext = _file_ext(name)
    return name[: len(name) - len(ext)] if ext else name


def _render_dedupe_details(
    details: list[dict],
    source_dir: Path,
    archive_dir: Path,
    *,
    mode: str,
) -> list[str]:
    _OP_PRIORITY = {
        "replace_file": 0,
        "import_file": 1,
        "copy_file": 2,
        "trash_file": 3,
        "delete_file": 4,
        "skip_file": 5,
    }

    lines: list[str] = []
    first = True

    for detail in details:
        if not first:
            lines.append("---")
        first = False

        ops = detail.get("operations", [])
        match_key = detail.get("match_key", "")

        # Step 1 — classify operations
        source_files: dict[str, dict] = {}
        archive_kept: list[dict] = []
        archive_imported: list[dict] = []
        archive_removed: list[dict] = []
        # Track target paths that appear in kept/imported to avoid duplication
        arc_kept_targets: set[str] = set()

        for op in ops:
            kind = op.get("kind", "")
            origin = op.get("origin", "")
            sp = op.get("source_path", "")
            tp = op.get("target_path", "")

            if kind in ("rename_file", "block_file"):
                continue

            if origin == "source":
                # replace_file from source = winner going INTO archive
                if kind == "replace_file":
                    archive_kept.append(op)
                    if tp:
                        arc_kept_targets.add(tp)
                    # Also record in source_files for SRC display
                    if sp and sp not in source_files:
                        source_files[sp] = op
                    elif sp and sp in source_files:
                        existing = source_files[sp]
                        if _OP_PRIORITY.get(kind, 99) < _OP_PRIORITY.get(existing.get("kind", ""), 99):
                            source_files[sp] = op
                elif kind == "copy_file":
                    # Sidecar donated from source to archive
                    archive_imported.append(op)
                    if tp:
                        arc_kept_targets.add(tp)
                    # Also in source_files for SRC display
                    if sp and sp not in source_files:
                        source_files[sp] = op
                    elif sp and sp in source_files:
                        existing = source_files[sp]
                        if _OP_PRIORITY.get(kind, 99) < _OP_PRIORITY.get(existing.get("kind", ""), 99):
                            source_files[sp] = op
                else:
                    if sp and sp not in source_files:
                        source_files[sp] = op
                    elif sp and sp in source_files:
                        existing = source_files[sp]
                        if _OP_PRIORITY.get(kind, 99) < _OP_PRIORITY.get(existing.get("kind", ""), 99):
                            source_files[sp] = op
            elif origin == "archive":
                if kind == "keep_file":
                    archive_kept.append(op)
                    if sp:
                        arc_kept_targets.add(sp)
                elif kind == "copy_file":
                    # Archive sidecar restored (e.g. from staged_archive)
                    archive_kept.append(op)
                    if tp:
                        arc_kept_targets.add(tp)
                elif kind in ("trash_file", "delete_file"):
                    archive_removed.append(op)
                elif kind == "skip_file":
                    archive_kept.append(op)
                    if sp:
                        arc_kept_targets.add(sp)

        # Filter removed: exclude files whose target path is in kept/imported
        # (staged_archive files that were restored then disposed)
        archive_removed = [
            op for op in archive_removed
            if op.get("source_path", "") not in arc_kept_targets
        ]

        # Step 3 — VIDEO header
        lines.append(f"VIDEO: {match_key}")

        # Step 4 — SRC blocks
        src_by_dir: dict[str, list[tuple[str, dict]]] = {}
        for sp, op in source_files.items():
            p = Path(sp)
            parent = str(p.parent)
            src_by_dir.setdefault(parent, []).append((sp, op))

        for dir_path, file_ops in src_by_dir.items():
            rel_dir = _rel(dir_path, source_dir)
            lines.append(f"  SRC({rel_dir}) -> {mode}")

            # Group by stem
            stem_groups: dict[str, list[tuple[str, dict]]] = {}
            for sp, op in file_ops:
                name = Path(sp).name
                stem = _file_stem(name)
                stem_groups.setdefault(stem, []).append((sp, op))

            for stem, stem_ops_list in stem_groups.items():
                ext_parts: list[str] = []
                for sp, op in sorted(stem_ops_list, key=lambda x: Path(x[0]).name):
                    name = Path(sp).name
                    ext = _file_ext(name)
                    size = op.get("file_size_bytes")
                    kind = op.get("kind", "")
                    reason = op.get("reason", "")

                    ext_str = ext + _format_size(size) if _artifact_is_media(ext) else ext

                    if kind == "skip_file" and "already" in reason.lower():
                        ext_str += " [IGNORED -- archive exists]"

                    ext_parts.append(ext_str)

                lines.append(f"    {stem}  ({','.join(ext_parts)})")

        # Step 5 — ARC block
        renamed_to = detail.get("renamed_to")
        archive_dest = detail.get("archive_destination", "")
        blocked_canonical = detail.get("canonical_stem", "")
        rename_blocked = detail.get("rename_blocked", False)

        if renamed_to:
            canonical_path = Path(renamed_to)
        elif archive_dest:
            canonical_path = Path(archive_dest)
        else:
            canonical_path = None

        if canonical_path:
            arc_dir = str(canonical_path.parent)
            # Use the canonical stem for display even if blocked
            if rename_blocked and blocked_canonical:
                canonical_stem = blocked_canonical
                final_tag = f"FINAL:{canonical_stem} [BLOCKED]"
            elif renamed_to:
                canonical_stem = canonical_path.name
                final_tag = f"FINAL:{canonical_stem}"
            else:
                canonical_stem = canonical_path.name
                final_tag = f"FINAL:{canonical_stem}"

            rel_arc_dir = _rel(arc_dir, archive_dir)
            lines.append(f"  ARC({rel_arc_dir}) -> {final_tag}")

            # Determine winner info
            has_rename = renamed_to and renamed_to != archive_dest

            # kept sub-section
            if archive_kept:
                lines.append("    kept:")
                kept_by_stem: dict[str, list[tuple[str, dict]]] = {}
                for op in archive_kept:
                    kind = op.get("kind", "")
                    # For replace/copy ops, use target_path (archive destination)
                    # For keep/skip ops, use source_path (already in archive)
                    if kind in ("replace_file", "copy_file"):
                        display_path = op.get("target_path") or op.get("source_path") or ""
                    else:
                        display_path = op.get("source_path") or op.get("target_path") or ""
                    if not display_path:
                        continue
                    name = Path(display_path).name
                    stem = _file_stem(name)
                    kept_by_stem.setdefault(stem, []).append((display_path, op))

                for stem, kept_ops in kept_by_stem.items():
                    media_exts: list[str] = []
                    other_exts: list[str] = []
                    for sp, op in sorted(kept_ops, key=lambda x: Path(x[0]).name):
                        name = Path(sp).name
                        ext = _file_ext(name)
                        size = op.get("file_size_bytes")
                        kind = op.get("kind", "")
                        ext_str = ext + _format_size(size) if _artifact_is_media(ext) else ext
                        if kind in ("replace_file", "keep_file") and _artifact_is_media(ext):
                            tag = " [WINNER]"
                            if has_rename:
                                tag += " -> renamed"
                            media_exts.append(ext_str + tag)
                        else:
                            other_exts.append(ext_str)
                    if media_exts:
                        lines.append(f"      {stem}  ({','.join(media_exts)})")
                    if other_exts:
                        lines.append(f"      {stem}  ({','.join(other_exts)})")

            # imported sub-section
            if archive_imported:
                lines.append("    imported:")
                imp_by_stem: dict[str, list[tuple[str, dict]]] = {}
                for op in archive_imported:
                    # Use target_path (archive destination) for display
                    display_path = op.get("target_path") or op.get("source_path") or ""
                    if not display_path:
                        continue
                    name = Path(display_path).name
                    stem = _file_stem(name)
                    imp_by_stem.setdefault(stem, []).append((display_path, op))

                for stem, imp_ops in imp_by_stem.items():
                    ext_parts = []
                    for sp, op in sorted(imp_ops, key=lambda x: Path(x[0]).name):
                        name = Path(sp).name
                        ext = _file_ext(name)
                        size = op.get("file_size_bytes")
                        ext_str = ext + _format_size(size) if _artifact_is_media(ext) else ext
                        ext_parts.append(ext_str)
                    lines.append(f"      {stem}  ({','.join(ext_parts)})")

            # removed sub-section
            if archive_removed:
                lines.append("    removed:")
                rem_by_stem: dict[str, list[tuple[str, dict]]] = {}
                for op in archive_removed:
                    sp = op.get("source_path", "")
                    if not sp:
                        continue
                    name = Path(sp).name
                    stem = _file_stem(name)
                    rem_by_stem.setdefault(stem, []).append((sp, op))

                for stem, rem_ops in rem_by_stem.items():
                    ext_parts = []
                    for sp, op in sorted(rem_ops, key=lambda x: Path(x[0]).name):
                        name = Path(sp).name
                        ext = _file_ext(name)
                        size = op.get("file_size_bytes")
                        reason = op.get("reason", "")
                        ext_str = ext + _format_size(size) if _artifact_is_media(ext) else ext
                        if "duplicate archive copy not selected" in reason:
                            ext_str += " [DUPLICATE]"
                        ext_parts.append(ext_str)
                    lines.append(f"      {stem}  ({','.join(ext_parts)})")

    return lines


def _artifact_is_media(ext: str) -> bool:
    """Check if extension is a media type that should show size."""
    from ytdl_archiver.core.dedupe import _MEDIA_EXTENSIONS
    return ext.lower() in _MEDIA_EXTENSIONS


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

        mode_label = "TRASH" if trash_dir else "DELETE"
        dry_label = "T" if dry_run else "F"
        emit_rendered(f"START DEDUPE | MODE:{mode_label} DRY:{dry_label}")
        tokens = config.get("filename.tokens", ["upload_date", "title", "channel"])
        sep = config.get("filename.token_joiner", "_")
        date_fmt = config.get("filename.date_format", "yyyymmdd")
        emit_rendered(f"CFG tokens=[{','.join(str(t) for t in tokens)}] sep=\"{sep}\" date={date_fmt}")
        emit_rendered("")

        summary = run_dedupe(
            effective_dir1,
            effective_dir2,
            trash_dir=trash_dir.expanduser() if trash_dir else None,
            delete=delete,
            dry_run=dry_run,
            verbose=verbose,
            config=config,
        )

        for line in _render_dedupe_details(
            summary["details"], effective_dir1, effective_dir2, mode=mode_label
        ):
            emit_rendered(line)

        disposed = summary.get("source_groups_disposed", 0) + summary.get("archive_groups_disposed", 0)
        emit_rendered(
            f"SUMMARY processed={summary['processed_sets']} "
            f"replaced={summary['replaced_sets']} "
            f"renamed={summary['archive_winners_renamed']} "
            f"{mode_label.lower()}={disposed}"
        )
        emit_rendered("DONE")

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
