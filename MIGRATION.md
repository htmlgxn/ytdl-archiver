# Migration Guide: Legacy Setup to Current CLI

This file is intentionally minimal and only documents migration deltas from older `archive.py`/JSON-first workflows.

## What changed

### Entry point changed
Before:
```bash
python archive.py -j playlists.json -d /path/to/archive
```

After:
```bash
ytdl-archiver archive -p /path/to/playlists.toml -d /path/to/archive
```

### Configuration moved to TOML in config directory
- Primary config: `~/.config/ytdl-archiver/config.toml`
- Default playlist file: `~/.config/ytdl-archiver/playlists.toml`
- Legacy JSON remains supported: `~/.config/ytdl-archiver/playlists.json`

### Playlists migration from working directory
On startup, if `playlists.toml` or `playlists.json` exists in the current working directory and config-dir `playlists.toml` does not, the file is moved into the config directory.

### Setup UI behavior
First-run setup uses a Rust `ratatui` wizard with a centered one-page progressive form in normal terminals, and a paged step-by-step fallback in small terminals.

## Minimal migration steps
1. Install/sync environment:
```bash
uv sync --dev
```
2. Initialize or trigger setup:
```bash
ytdl-archiver init
```
3. Convert legacy playlists JSON if needed:
```bash
ytdl-archiver convert-playlists -i playlists.json -o playlists.toml
```
4. Run archive:
```bash
ytdl-archiver archive
```

## Reference docs
- Quickstart: `README.md`
- CLI reference: `docs/cli.md`
- Configuration reference: `docs/configuration.md`
- Development: `docs/development.md`
