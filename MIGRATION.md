# Migration Guide

## Scope
This guide covers migration from `0.2.x` to `0.3.0`.

## Highlights in 0.3.0
- Documentation now treats `archive`, `metadata-backfill`, and `search` as first-class workflows.
- Verbose output contract is explicitly structured diagnostics only (no raw yt-dlp passthrough).
- Default container policy now prioritizes max resolution and avoids final `.webm` outputs (prefers mp4 when tied, otherwise remux to mp4/mkv).
- Archive metadata sidecar behavior is documented as default:
  - `<stem>.info.json`
  - `<stem>.metadata.json`
- Per-video `.nfo` coverage is expanded for media-server usage.
- Subtitle pipeline defaults are documented as:
  - language-suffixed sidecars (`<stem>.<lang>.<ext>`)
  - conversion target `.srt`
  - embedding enabled with sidecar retention.

## If you are coming from older `archive.py`/JSON-first usage
### Entry point changed
Before:
```bash
python archive.py -j playlists.json -d /path/to/archive
```

After:
```bash
ytdl-archiver archive -p /path/to/playlists.toml -d /path/to/archive
```
or
```bash
uv run ytdl-archiver archive -p /path/to/playlists.toml -d /path/to/archive
```

### Configuration and playlists location
- Primary config: `~/.config/ytdl-archiver/config.toml`
- Default playlists: `~/.config/ytdl-archiver/playlists.toml`
- Legacy JSON playlists remain supported: `~/.config/ytdl-archiver/playlists.json`

### Playlists migration from working directory
On startup, if `playlists.toml` or `playlists.json` exists in the current working directory and config-dir `playlists.toml` does not, the file is moved into the config directory.

## 0.2.x to 0.3.0 checklist
1. Verify dependencies/environment:
```bash
uv sync --dev
```
2. Validate command surface:
```bash
ytdl-archiver --help
ytdl-archiver archive --help
ytdl-archiver metadata-backfill --help
ytdl-archiver search --help
```
3. Review/adjust config defaults in `~/.config/ytdl-archiver/config.toml`.
4. Confirm desired metadata artifacts and sidecars are enabled.
5. Run a small archive sample and verify expected sidecars (`.info.json`, `.metadata.json`, `.nfo`, subtitles).

## Reference docs
- Quickstart: `README.md`
- CLI reference: `docs/cli.md`
- Configuration reference: `docs/configuration.md`
- Terminal output: `docs/terminal-output.md`
- Development/release checks: `docs/development.md`
- v0.3.0 release notes: `docs/releases/0.3.0.md`
