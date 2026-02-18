# ytdl-archiver

Modern Python CLI for archiving YouTube playlists with media-server-friendly sidecar files.

## Requirements
- Python 3.14+
- [`uv`](https://docs.astral.sh/uv/)
- FFmpeg on `PATH`
- Optional external JavaScript runtime (`deno` or Node.js) for full yt-dlp YouTube extraction compatibility

## Install
Quick install (Linux/macOS):
```bash
curl -fsSL https://raw.githubusercontent.com/htmlgxn/ytdl-archiver/main/install.sh | bash
```
This installs `uv`, prompts to install `deno` (recommended), Firefox (recommended), and FFmpeg (recommended), installs `ytdl-archiver`, then launches `ytdl-archiver`.

Quick install (Windows PowerShell):
```powershell
irm https://raw.githubusercontent.com/htmlgxn/ytdl-archiver/main/install.ps1 | iex
```
This installs `uv`, prompts to install `deno` (recommended), Firefox (recommended), and FFmpeg (recommended), installs `ytdl-archiver`, then launches `ytdl-archiver`.

Or with `uv` directly:
```bash
uv tool install ytdl-archiver
```

Or pip:
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
uv run ytdl-archiver archive
```

If `~/.config/ytdl-archiver/config.toml` is missing, setup runs automatically on non-help commands and generates:
- `~/.config/ytdl-archiver/config.toml`
- `~/.config/ytdl-archiver/playlists.toml`

Published wheels bundle prebuilt setup UI binaries for:
- `linux-x86_64`
- `linux-aarch64`
- `macos-aarch64`
- `windows-x86_64`

Note: Intel macOS (`macos-x86_64`) is temporarily excluded from bundled release artifacts due to current CI runner constraints.

Source installs keep the existing fallback behavior:
- With Rust installed, setup can auto-build the UI binary.
- Without Rust, setup falls back to prompt mode.

You can also run setup directly:
```bash
uv run ytdl-archiver init
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
uv run ytdl-archiver archive
```

## Core Commands
```bash
uv run ytdl-archiver --help
uv run ytdl-archiver archive --help
uv run ytdl-archiver convert-playlists --help
uv run ytdl-archiver init --help
```

## Documentation
- Docs index: `docs/index.md`
- CLI reference: `docs/cli.md`
- Configuration reference: `docs/configuration.md`
- Development/contributing: `docs/development.md`
- Migration notes: `MIGRATION.md`
- Terminal output modes: `docs/terminal-output.md`

## Optional systemd service
See `optional/ytdl-archiver.service`.
