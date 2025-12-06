# ytdl-archiver

A modern Python application for downloading YouTube **playlists** with thumbnails and generating metadata `.nfo` files for media servers.
Ideal for Jellyfin / Emby users + archivists.

Based on [ytdl-nfo](https://github.com/htmlgxn/ytdl-nfo) and [yt-dlp](https://github.com/yt-dlp/yt-dlp)

## Version 2.0 - Modern Architecture

This version has been completely modernized with:
- **Poetry** for dependency management
- **TOML** configuration files
- **Structured logging** with JSON output
- **Comprehensive testing** with pytest
- **Retry logic** with tenacity
- **Type hints** and mypy validation
- **CI/CD** with GitHub Actions
- **Modern CLI** with click

## Features
- Set the path to your YouTube archive
- Name folders within your archive (per playlist). Supports subpaths
- Downloads separate .mp4, .nfo, and .jpg file for media server readability
- Creates an .archive.txt file in each playlist folder to enable rerun and refresh of content efficiently
- YouTube Shorts save within a subfolder of each playlist path
- Loops on the hour to keep new videos in the playlist archived once the initial archive has been made

## Installation

### Requirements
- Python 3.10+
- Poetry (for dependency management)
- FFmpeg (for video processing)

### Quick Install
```bash
git clone https://github.com/htmlgxn/ytdl-archiver.git
cd ytdl-archiver
poetry install
```

### Development Install
```bash
git clone https://github.com/htmlgxn/ytdl-archiver.git
cd ytdl-archiver
poetry install --with dev
pre-commit install
```

## Usage

### 1. Initialize Configuration
```bash
poetry run ytdl-archiver init-config
```
This creates a configuration file at `~/.config/ytdl-archiver/config.toml`.

### 2. Configure Playlists
You can use either JSON (legacy) or TOML (recommended) format:

#### TOML Format (Recommended)
Create/edit `playlists.toml`:
```toml
[[playlist]]
id = "UUxxxxxxxxxxxxxxxxxxxxxx"
path = "Folder Name"
name = "Example Music Channel"

# Override download settings for this playlist
[playlist.download]
format = "bestaudio"  # Music only needs audio
writesubtitles = false  # Music doesn't need subtitles
write_thumbnail = true

[[playlist]]
id = "PLOggx_xxxxxxxxxxxxxxxxxx_xxxxxxxx"
path = "unlisted/cool_videos"
name = "Tutorial Channel"

[playlist.download]
format = "bestvideo[height<=720]+bestaudio"  # Lower quality for tutorials
writesubtitles = true  # Tutorials need subtitles
subtitle_languages = ["en", "es"]  # Multiple languages
write_thumbnail = true
```

#### JSON Format (Legacy)
Edit your `playlists.json` file:
```json
[
    {
        "id": "UUxxxxxxxxxxxxxxxxxxxxxx",
        "path": "Channel Name"
    },
    {
        "id": "PLOggx_xxxxxxxxxxxxxxxxxx_xxxxxxxx",
        "path": "unlisted/cool_videos"
    }
]
```

> **Note**: If both `playlists.toml` and `playlists.json` exist, TOML format will be used.

### 3. Run the Archiver
```bash
poetry run ytdl-archiver archive
```

### CLI Commands
```bash
# Archive with custom playlists file (JSON or TOML)
poetry run ytdl-archiver archive -p /path/to/playlists.toml

# Archive to custom directory
poetry run ytdl-archiver archive -d /path/to/archive

# Use custom config file
poetry run ytdl-archiver -c /path/to/config.toml archive

# Enable verbose logging
poetry run ytdl-archiver -v archive

# Convert JSON playlists to TOML format
poetry run ytdl-archiver convert-playlists -i playlists.json -o playlists.toml

# Show help
poetry run ytdl-archiver --help
```

## Setup as a Service
Follow these instructions for your system:

### Linux
[systemctl](docs/system-process/linux/systemctl.md)
### MacOS
Coming soon!

## Configuration

The new version uses TOML configuration files. Here are the main sections:

### 6. Playlist-Specific Settings
- Per-playlist yt-dlp customization
- Override global download settings
- Flexible configuration inheritance
- TOML playlist format support

#### Example: Different Settings per Playlist
```toml
# Music playlist - audio only
[[playlist]]
id = "music_channel_id"
path = "Music"
[playlist.download]
format = "bestaudio"
writesubtitles = false

# Tutorial playlist - video with subtitles
[[playlist]]
id = "tutorial_channel_id"
path = "Tutorials"
[playlist.download]
format = "bestvideo[height<=720]+bestaudio"
writesubtitles = true
subtitle_languages = ["en", "es"]
```

### Archive Settings
```toml
[archive]
base_directory = "~/Videos/YouTube"
delay_between_videos = 10
delay_between_playlists = 30
max_retries = 3
retry_backoff_factor = 2.0
```

### Download Settings
```toml
[download]
format = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4"
merge_output_format = "mp4"
write_subtitles = true
subtitle_format = "vtt"
convert_subtitles = "srt"
subtitle_languages = ["en"]
write_thumbnail = true
thumbnail_format = "jpg"
```

### YouTube Shorts
```toml
[shorts]
detect_shorts = true
shorts_subdirectory = "YouTube Shorts"
aspect_ratio_threshold = 0.7
```

### Logging
```toml
[logging]
level = "INFO"
format = "json"  # "json" or "console"
file_path = "~/.local/share/ytdl-archiver/logs/app.log"
max_file_size = "10MB"
backup_count = 5
```

## Development

### Running Tests
```bash
poetry run pytest
```

### Code Quality
```bash
poetry run black src tests
poetry run isort src tests
poetry run flake8 src tests
poetry run mypy src
```

### Project Structure
```
src/ytdl_archiver/
├── config/          # Configuration management
├── core/            # Core functionality
├── cli.py           # Command line interface
└── exceptions.py    # Custom exceptions

tests/
├── test_cli/         # CLI tests
├── test_config/       # Configuration tests
├── test_core/         # Core functionality tests
├── test_integration/  # Integration tests
└── conftest.py       # Test configuration
```