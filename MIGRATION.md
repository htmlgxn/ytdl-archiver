# Migration Guide: v1.x to v2.0

This guide helps you migrate from the legacy ytdl-archiver to the modern v2.0 architecture.

## Breaking Changes

### 1. Installation Method
**Before:**
```bash
git clone https://github.com/htmlgxn/ytdl-archiver.git
cd ytdl-archiver
python archive.py
```

**After:**
```bash
git clone https://github.com/yourusername/ytdl-archiver.git
cd ytdl-archiver
poetry install
poetry run ytdl-archiver archive
```

### 2. Configuration
**Before:** Hardcoded values in `archive.py`

**After:** TOML configuration file

### 3. CLI Interface
**Before:** Positional arguments
```bash
python archive.py -j playlists.json -d /path/to/archive
```

**After:** Modern CLI with commands
```bash
poetry run ytdl-archiver archive -p playlists.json -d /path/to/archive
```

## Migration Steps

### Step 1: Install Dependencies
Install Poetry if you haven't already:
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

### Step 2: Initialize Configuration
```bash
poetry run ytdl-archiver init-config
```

This creates `~/.config/ytdl-archiver/config.toml`.

### Step 3: Migrate Configuration
Your old settings need to be converted to TOML format:

**Old hardcoded settings:**
```python
# In archive.py
time.sleep(10)  # delay_between_videos
time.sleep(30)  # delay_between_playlists
```

**New TOML configuration:**
```toml
[archive]
delay_between_videos = 10
delay_between_playlists = 30
```

### Step 4: Update Playlists File
Your existing `playlists.json` file will work without changes:

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

### Step 5: Update Service Files
If you use systemd, update your service file:

**Before:**
```ini
ExecStart=/usr/bin/python /home/username/ytdl-archiver/archive.py
```

**After:**
```ini
ExecStart=/usr/bin/poetry run ytdl-archiver archive
WorkingDirectory=/home/username/ytdl-archiver
```

## New Features in v2.0

### 1. Structured Logging
- JSON format for better log parsing
- Configurable log levels
- File rotation support

### 2. Retry Logic
- Automatic retries with exponential backoff
- Configurable retry attempts

### 3. Better Error Handling
- Custom exception types
- Graceful error recovery

### 4. Configuration Validation
- Validates configuration on startup
- Clear error messages

### 5. Modern CLI
- Help system
- Command structure
- Verbose mode

## Configuration Mapping

| Old Setting | New TOML Path | Description |
|-------------|----------------|-------------|
| `time.sleep(10)` | `archive.delay_between_videos` | Delay between videos |
| `time.sleep(30)` | `archive.delay_between_playlists` | Delay between playlists |
| `ydl_opts['format']` | `download.format` | Video format |
| `writesubtitles: True` | `download.write_subtitles` | Download subtitles |
| `writethumbnail: True` | `download.write_thumbnail` | Download thumbnails |

## Troubleshooting

### Poetry Issues
If Poetry commands fail, ensure it's in your PATH:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Configuration Issues
Validate your configuration:
```bash
poetry run ytdl-archiver --help
```

### Dependency Issues
If you encounter dependency conflicts:
```bash
poetry install --no-dev
```

## Rollback Plan

If you need to rollback to v1.x:

1. Keep your old `archive.py` and `dependancies/` folder
2. Use the old command: `python archive.py`
3. Consider filing an issue for v2.0 problems

## Support

- Check the new documentation in README.md
- Use `poetry run ytdl-archiver --help`
- File issues on GitHub for migration problems