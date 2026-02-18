# ytdl-archiver

Modern Python CLI for archiving YouTube playlists with media-server-friendly sidecar files.

## Features
- Playlist archiving with rerun-safe `.archive.txt` tracking per playlist folder
- NFO metadata generation for media servers (Kodi/Emby style)
- Thumbnail and subtitle download support
- Playlist-specific yt-dlp overrides
- Output modes: progress (default), quiet, verbose
- Optional browser-cookie refresh before archive runs

## Requirements
- Python 3.14+
- [`uv`](https://docs.astral.sh/uv/)
- FFmpeg available on PATH

## Install
```bash
git clone https://github.com/htmlgxn/ytdl-archiver.git
cd ytdl-archiver
uv sync --dev
```

## Quick Start

### 1. Initialize config
```bash
uv run ytdl-archiver init-config
```

Default config path:
- `~/.config/ytdl-archiver/config.toml`

### 2. Define playlists
Create `~/.config/ytdl-archiver/playlists.toml` (or pass `-p/--playlists` at runtime).

```toml
[[playlists]]
id = "UUxxxxxxxxxxxxxxxxxxxxxx"
path = "Music/Example Channel"
name = "Example Music Channel"

[playlists.download]
format = "bestaudio"
writesubtitles = false
writethumbnail = true

[[playlists]]
id = "PLOggx_xxxxxxxxxxxxxxxxxx_xxxxxxxx"
path = "Tutorials/Example"
name = "Example Tutorials"

[playlists.download]
format = "bestvideo[height<=720]+bestaudio"
write_subtitles = true
subtitle_languages = ["en", "es"]
write_thumbnail = true
```

Notes:
- `[[playlists]]` entries are loaded from the `playlists` array.
- If both TOML and JSON exist in the config dir, TOML is preferred.
- Playlist overrides may use yt-dlp-style keys (`writesubtitles`, `writethumbnail`, etc.) or snake_case aliases (`write_subtitles`, `write_thumbnail`).

### 3. Run archiving
```bash
uv run ytdl-archiver archive
```

## CLI

### Global options
```bash
uv run ytdl-archiver --help
```

```text
Options:
  -c, --config PATH
  -v, --verbose
  -q, --quiet
  --no-color
```

### `archive`
```bash
uv run ytdl-archiver archive --help
```

```text
Options:
  -p, --playlists PATH
  -d, --directory PATH
  --cookies-browser [firefox|chrome|chromium|brave|edge|opera|vivaldi|whale|safari]
  --cookies-profile TEXT
```

Examples:
```bash
# Use custom playlists file
uv run ytdl-archiver archive -p /path/to/playlists.toml

# Use custom archive directory
uv run ytdl-archiver archive -d /path/to/archive

# Use custom config file
uv run ytdl-archiver -c /path/to/config.toml archive

# Refresh cookies from Firefox profile before run
uv run ytdl-archiver archive --cookies-browser firefox --cookies-profile default

# Verbose mode
uv run ytdl-archiver -v archive
```

### `convert-playlists`
```bash
uv run ytdl-archiver convert-playlists -i playlists.json -o playlists.toml
```

### `init-config`
```bash
uv run ytdl-archiver init-config -o /path/to/config.toml
```

## Configuration Reference

### File and precedence behavior
- Config file default: `~/.config/ytdl-archiver/config.toml`
- Playlists file resolution:
1. Explicit override (`--playlists` / `config.set_playlists_file`)
2. `~/.config/ytdl-archiver/playlists.toml`
3. `~/.config/ytdl-archiver/playlists.json` (legacy)
4. Fallback target path: `~/.config/ytdl-archiver/playlists.toml`
- Startup migration behavior:
  - If `playlists.toml` or `playlists.json` exists in the current working directory and config-dir `playlists.toml` does not, the file is moved into the config directory.

### Global defaults (`config.toml`)
```toml
[archive]
base_directory = "~/Videos/YouTube"
delay_between_videos = 10
delay_between_playlists = 30
max_retries = 3
retry_backoff_factor = 2.0

[download]
format = "bestvideo+bestaudio/best"
merge_output_format = "mp4"
write_subtitles = true
subtitle_format = "vtt"
convert_subtitles = "srt"
subtitle_languages = ["en"]
write_thumbnail = true
thumbnail_format = "jpg"
max_concurrent_downloads = 1

[shorts]
detect_shorts = true
shorts_subdirectory = "YouTube Shorts"
aspect_ratio_threshold = 0.7

[logging]
level = "INFO"
format = "json"
file_path = "~/.local/share/ytdl-archiver/logs/app.log"
max_file_size = "10MB"
backup_count = 5

[http]
user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
request_timeout = 30
connect_timeout = 10
cookie_file = "~/cookies.txt"

[media_server]
generate_nfo = true
nfo_format = "kodi"
```

## Systemd Service (optional)
See `optional/ytdl-archiver.service`.

## Development
See `docs/development.md`.
