# Configuration Reference

## Source of truth
Do not hand-maintain duplicated config tables across docs. Configuration behavior is defined by:
- Defaults: `src/ytdl_archiver/config/defaults.toml`
- Merge/lookup/validation: `src/ytdl_archiver/config/settings.py`
- CLI override semantics: `src/ytdl_archiver/cli.py`

This document summarizes those sources.

## Files and precedence
- Config default path: `~/.config/ytdl-archiver/config.toml`
- Playlists resolution order:
1. Explicit CLI/config override (`--playlists`, `config.set_playlists_file`)
2. `~/.config/ytdl-archiver/playlists.toml`
3. `~/.config/ytdl-archiver/playlists.json` (legacy)
4. Fallback target: `~/.config/ytdl-archiver/playlists.toml`

Startup migration behavior:
- If `playlists.toml` or `playlists.json` exists in current working directory and config-dir `playlists.toml` does not, it is moved into the config directory.

## Default config (`config.toml`)
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

[filename]
tokens = ["title", "channel"]
token_joiner = "_"
date_format = "yyyy-mm-dd"
missing_token_behavior = "omit"

[filename.case]
title = "lower"
channel = "lower"
upload_date = "preserve"
video_id = "lower"

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

[cookies]
source = "manual_file"
browser = "firefox"
profile = ""
refresh_on_startup = true

[media_server]
generate_nfo = true
nfo_format = "kodi"
```

## Cookie refresh behavior
- `cookies.source` values:
  - `manual_file`: use `http.cookie_file` as maintained by user
  - `browser`: refresh from browser before archive runs
- When `cookies.source = "browser"`, `cookies.browser` must be one of:
  - `firefox`, `chrome`, `chromium`, `brave`, `edge`, `opera`, `vivaldi`, `whale`, `safari`
- CLI flags `--cookies-browser` and `--cookies-profile` override config for that run.

## Playlist download override aliases
Global defaults are documented in snake_case under `[download]`.

Per-playlist `[playlists.download]` accepts both canonical and yt-dlp-style keys:
- `write_subtitles` or `writesubtitles`
- `subtitle_format` or `subtitlesformat`
- `convert_subtitles` or `convertsubtitles`
- `subtitle_languages` or `subtitleslangs`
- `write_thumbnail` or `writethumbnail`
- `format`
- `merge_output_format`
- `thumbnail_format`

## Validation highlights
Runtime validation includes:
- archive parent directory exists
- valid logging level
- non-empty download format
- valid cookie source values (`manual_file`, `browser`)
- `cookies.refresh_on_startup` is boolean
- valid `cookies.browser` when browser mode is enabled
- filename token list is non-empty, unique, and only includes `title`, `channel`, `upload_date`, `video_id`
- `filename.token_joiner` is non-empty and cannot include `/` or `\`
- `filename.date_format` supports: `yyyy-mm-dd`, `yyyymmdd`, `yyyy_mm_dd`, `yyyy.mm.dd`
- `filename.missing_token_behavior` supports `omit` only (v1)
- per-token case modes support `preserve`, `lower`, `upper`, `title`
- malformed or missing upload dates result in the `upload_date` token being omitted
- legacy `filename.date_separator` is ignored when present
