# CLI Reference

Authoritative implementation source: `src/ytdl_archiver/cli.py`.

## Invocation
Installed via tool/pip/script:
```bash
ytdl-archiver [OPTIONS] COMMAND [ARGS]...
```

From source checkout:
```bash
uv run ytdl-archiver [OPTIONS] COMMAND [ARGS]...
```

### Global options
- `-c, --config PATH`: path to configuration file
- `-v, --verbose`: structured technical diagnostics (debug/info) for troubleshooting; does not enable raw yt-dlp passthrough output
- `-q, --quiet`: minimal output (errors and failure-oriented summary)
- `--no-color`: disable colored text (symbols/emojis may still appear)

### Commands
- `archive`: archive YouTube playlists
- `metadata-backfill`: backfill metadata sidecars for already archived IDs
- `search`: search channels/playlists and append selected entries to playlists config
- `convert-playlists`: convert playlists JSON to TOML
- `init`: run first-run setup and generate template files

## First-run behavior
- If `config.toml` is missing and invocation is not a help flow, setup auto-runs and exits after setup completes.
- `init` always runs setup directly.
- Help commands bypass setup.

## `archive`
```bash
ytdl-archiver archive [OPTIONS]
```

Options:
- `-p, --playlists PATH`: playlists file (JSON or TOML)
- `-d, --directory PATH`: archive base directory override
- `--cookies-browser [firefox|chrome|chromium|brave|edge|opera|vivaldi|whale|safari]`: refresh cookies from browser before archive run
- `--cookies-profile TEXT`: browser profile name or full profile path

Notes:
- If `--cookies-browser` is omitted, cookie refresh can still happen from config (`cookies.source = "browser"` and `cookies.refresh_on_startup = true`).
- `--cookies-browser` and `--cookies-profile` override config for the current run.
- Default container policy avoids final `.webm` artifacts and prefers max-resolution outputs.
- By default, each successful download writes both `<stem>.info.json` (yt-dlp sidecar) and `<stem>.metadata.json` (project-owned full metadata payload), plus enriched per-video `.nfo` when enabled.

## `metadata-backfill`
```bash
ytdl-archiver metadata-backfill [OPTIONS]
```

Purpose:
- Backfill metadata sidecars for IDs already present in playlist `.archive.txt` files.
- Uses `[[playlists]].name` as `tvshow.nfo` title (fallback: `path`) to match archive behavior.

Options:
- `-p, --playlists PATH`: playlists file (JSON or TOML)
- `-d, --directory PATH`: archive base directory override
- `--cookies-browser [firefox|chrome|chromium|brave|edge|opera|vivaldi|whale|safari]`: refresh cookies from browser before metadata-backfill run
- `--cookies-profile TEXT`: browser profile name or full profile path for cookie extraction
- `--scope [full|info-json]`: sidecar scope (`full` includes additional artifacts, `info-json` only writes info JSON)
- `--refresh-existing / --no-refresh-existing`: refresh metadata sidecars when `.info.json` already exists
- `--limit-per-playlist INTEGER`: max archived videos to process per playlist
- `--continue-on-error / --fail-fast`: continue processing after errors or stop on first failure

Behavior notes:
- In `full` scope, backfill refreshes enriched per-video `.nfo` and project-owned `<stem>.metadata.json` sidecars (respecting config gates), in addition to `.info.json`.
- In `full` scope, backfill also repairs legacy fallback stems (for example `video-<id>_unknown-channel`) to canonical config-derived stems.
- If a canonical target stem already exists, backfill skips the rename and emits a warning (no overwrite).
- Backfill reuses `archive.delay_between_videos` as request pacing (inter-video delay and extractor request sleep).
- If YouTube rate-limiting is detected, backfill warns and pauses the rest of the current playlist when running with `--continue-on-error`.

## `search`
```bash
ytdl-archiver search [OPTIONS] [QUERY]
```

Purpose:
- Discover channels/playlists and append selected results to `playlists.toml`.

Options:
- `--include-playlists`: include playlist discovery in addition to channels

Behavior:
- If `QUERY` is omitted, CLI prompts for it.
- Uses `fzf` multi-select when available; otherwise falls back to a numbered prompt.
- Prompts for archive path per selected result before writing.

## `convert-playlists`
```bash
ytdl-archiver convert-playlists -i playlists.json -o playlists.toml
```

Options:
- `-i, --input PATH`: input JSON playlists file
- `-o, --output PATH`: output TOML file (default is input path with `.toml` suffix)

## `init`
```bash
ytdl-archiver init
```

Runs interactive setup and writes template files:
- `~/.config/ytdl-archiver/config.toml`
- `~/.config/ytdl-archiver/playlists.toml`

## Setup environment variables
Used by setup runtime bridge in `src/ytdl_archiver/setup/ratatui_bridge.py`.

- `YTDL_ARCHIVER_SETUP_TUI_BIN`: explicit path to setup wizard binary
- `YTDL_ARCHIVER_SETUP_TUI_AUTOBUILD`: enable/disable auto-build fallback (`1` default, `0` disables)
- `YTDL_ARCHIVER_SETUP_TUI_BUILD_TIMEOUT`: auto-build timeout in seconds (default `300`)

## Help commands
```bash
ytdl-archiver --help
ytdl-archiver archive --help
ytdl-archiver metadata-backfill --help
ytdl-archiver search --help
ytdl-archiver convert-playlists --help
ytdl-archiver init --help
```
