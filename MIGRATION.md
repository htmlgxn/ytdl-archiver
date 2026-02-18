# Migration Guide: Legacy Setup to Current CLI

This guide covers migration from older `archive.py`/JSON-style setups to the current command-based CLI and TOML-first configuration.

## Breaking/Behavioral Changes

### 1. Entry point changed
Before:
```bash
python archive.py -j playlists.json -d /path/to/archive
```

After:
```bash
uv run ytdl-archiver archive -p /path/to/playlists.toml -d /path/to/archive
```

### 2. Configuration moved to TOML
Before: hardcoded/script-level values.

After: merged defaults + user config in `~/.config/ytdl-archiver/config.toml`.

### 3. Playlists are config-dir based by default
Current lookup order:
1. Explicit `--playlists` value
2. `~/.config/ytdl-archiver/playlists.toml`
3. `~/.config/ytdl-archiver/playlists.json` (legacy)
4. fallback target path `~/.config/ytdl-archiver/playlists.toml`

Startup migration behavior:
- If `playlists.toml` or `playlists.json` exists in the working directory and config-dir `playlists.toml` does not, the file is moved into the config directory.

## Migration Steps

### Step 1: Install dependencies
```bash
git clone https://github.com/htmlgxn/ytdl-archiver.git
cd ytdl-archiver
uv sync --dev
```

### Step 2: Initialize config
```bash
uv run ytdl-archiver init
```
You can also trigger first-run setup by running:
```bash
uv run ytdl-archiver archive
```
when `~/.config/ytdl-archiver/config.toml` does not exist.

### Step 3: Move/convert playlists
Option A (recommended): convert legacy JSON to TOML.
```bash
uv run ytdl-archiver convert-playlists -i playlists.json -o playlists.toml
```

Option B: continue using JSON (legacy supported).

### Step 4: Run archive
```bash
uv run ytdl-archiver archive
```

## Config Mapping (Legacy -> Current)

| Legacy idea | Global config key (snake_case) | yt-dlp option key | Playlist override keys accepted |
|---|---|---|---|
| Subtitles on/off | `download.write_subtitles` | `writesubtitles` | `writesubtitles` or `write_subtitles` |
| Subtitle format | `download.subtitle_format` | `subtitlesformat` | `subtitlesformat` or `subtitle_format` |
| Subtitle conversion | `download.convert_subtitles` | `convertsubtitles` | `convertsubtitles` or `convert_subtitles` |
| Subtitle languages | `download.subtitle_languages` | `subtitleslangs` | `subtitleslangs` or `subtitle_languages` |
| Thumbnail on/off | `download.write_thumbnail` | `writethumbnail` | `writethumbnail` or `write_thumbnail` |
| Container format | `download.merge_output_format` | `merge_output_format` | `merge_output_format` |
| Video format selection | `download.format` | `format` | `format` |

## CLI Surface (current)

### Top-level
```bash
uv run ytdl-archiver --help
```
Commands:
- `archive`
- `convert-playlists`
- `init`

Global options:
- `-c, --config PATH`
- `-v, --verbose`
- `-q, --quiet`
- `--no-color`

### Archive command
```bash
uv run ytdl-archiver archive --help
```
Options:
- `-p, --playlists PATH`
- `-d, --directory PATH`
- `--cookies-browser [firefox|chrome|chromium|brave|edge|opera|vivaldi|whale|safari]`
- `--cookies-profile TEXT`

## systemd migration note
If migrating from a direct Python script service, switch `ExecStart` to command form:
```ini
ExecStart=uv run ytdl-archiver archive
WorkingDirectory=/home/username/ytdl-archiver
```

## Troubleshooting

### Validate command availability
```bash
uv run ytdl-archiver --help
```

### Re-sync environment
```bash
uv sync --dev
```
