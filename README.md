# ytdl-archiver

<p align="center">
  <img src="assets/branding/title-banner.png" alt="ytdl-archiver" width="900">
</p>

Modern Python CLI for archiving YouTube playlists with media-server-friendly sidecar files.

## Dependencies
- Python 3.14+
- [`uv`](https://docs.astral.sh/uv/)
- FFmpeg on `PATH`
- (Recommended) External JavaScript runtime (`deno` or `Node.js`) for full yt-dlp extraction compatibility
- (Recommended) Firefox recommended for cookie extraction
- (Optional) Rust for setup TUI

## Install
Install with uv (recommended):
```bash
uv tool install ytdl-archiver
```

Or with pip:
```bash
pip install ytdl-archiver
```

From source (development):
```bash
git clone https://github.com/htmlgxn/ytdl-archiver.git
cd ytdl-archiver
uv sync
```

## Quick Start

### 1. Run first-time setup
```bash
ytdl-archiver archive
```

If `~/.config/ytdl-archiver/config.toml` is missing, setup runs automatically on non-help commands and generates:
- `~/.config/ytdl-archiver/config.toml`
- `~/.config/ytdl-archiver/playlists.toml`

You can also run setup directly:
```bash
ytdl-archiver init
```

### 2. Define playlists
Edit `~/.config/ytdl-archiver/playlists.toml`:

```toml
[[playlists]]
id = "UUxxxxxxxxxxxxxxxxxxxxxx"
path = "Music/Example Channel"
name = "Example Music Channel"

[playlists.download]
format = "bestaudio"
write_subtitles = false
write_thumbnail = true
```

Notes:
- `[[playlists]]` entries are loaded from the `playlists` array.
- If both `playlists.toml` and `playlists.json` exist in the config directory, TOML is preferred.
- Playlist download overrides accept canonical snake_case keys and yt-dlp-style aliases (for example `write_subtitles` and `writesubtitles`).

### 3. Run archive
```bash
ytdl-archiver archive
```

## Core Commands
```bash
ytdl-archiver --help
ytdl-archiver archive --help
ytdl-archiver convert-playlists --help
ytdl-archiver init --help
```

## Documentation
- Docs index: `docs/index.md`
- CLI reference: `docs/cli.md`
- Configuration reference: `docs/configuration.md`
- Development/contributing: `docs/development.md`
- Migration notes: `MIGRATION.md`
- Terminal output modes: `docs/terminal-output.md`