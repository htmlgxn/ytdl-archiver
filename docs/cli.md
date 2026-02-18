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
- `-v, --verbose`: verbose logging + detailed technical output
- `-q, --quiet`: minimal output (errors and failure-oriented summary)
- `--no-color`: disable colored text (symbols/emojis may still appear)

### Commands
- `archive`: archive YouTube playlists
- `convert-playlists`: convert playlists JSON to TOML
- `init`: run first-run setup and generate template files

## First-run behavior
- If `config.toml` is missing and invocation is not a help flow, setup is auto-launched and exits after setup completes.
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

## `convert-playlists`
```bash
ytdl-archiver convert-playlists -i playlists.json -o playlists.toml
```

Options:
- `-i, --input PATH`: input JSON playlists file (required in practice)
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
ytdl-archiver convert-playlists --help
ytdl-archiver init --help
```
