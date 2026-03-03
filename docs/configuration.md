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

Playlist display metadata:
- `[[playlists]].name` is used as the `tvshow.nfo` title.
- If `name` is missing/empty, fallback uses `path`.
- This title rule is applied by both `archive` and `metadata-backfill`.

## Default config (`config.toml`)
```toml
[archive]
base_directory = "~/Videos/YouTube"
delay_between_videos = 10
delay_between_playlists = 30
max_retries = 3
retry_backoff_factor = 2.0

[download]
format = "bestvideo*+bestaudio/best"
format_sort = "res,br,fps,container"
merge_output_format = "mp4"
container_policy = "no_webm_prefer_mp4"
write_info_json = true
write_max_metadata_json = true
write_subtitles = true
embed_subtitles = true
subtitle_format = "srt/best"
convert_subtitles = "srt"
subtitle_languages = ["en"]
write_thumbnail = true
thumbnail_format = "jpg"
max_concurrent_downloads = 1

[filename]
tokens = ["upload_date", "title", "channel"]
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
user_agent = "Mozilla/5.0 (X11; Linux x86_64; rv:136.0) Gecko/20100101 Firefox/136.0"
request_timeout = 30
connect_timeout = 10
cookie_file = "~/cookies.txt"

[search]
backend_order = ["youtube_html"]
backend_strict = false
fallback_enabled = false
fallback_on_zero_results = false
fallback_on_error = false
target_channel_candidates = 60
max_backend_rounds = 2
instances = [
  "https://yewtu.be",
  "https://vid.puffyan.us",
  "https://inv.nadeko.net",
]
max_results = 20
youtube_html_timeout_seconds = 8
yt_dlp_timeout_seconds = 20

[cookies]
source = "browser"
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
- `format_sort`
- `container_policy`
- `write_info_json` or `writeinfojson`
- `write_max_metadata_json`
- `write_subtitles` or `writesubtitles`
- `embed_subtitles` or `embedsubtitles`
- `subtitle_format` or `subtitlesformat`
- `convert_subtitles` or `convertsubtitles`
- `subtitle_languages` or `subtitleslangs`
- `write_thumbnail` or `writethumbnail`
- `format`
- `merge_output_format`
- `thumbnail_format`

Key exception:
- `write_max_metadata_json` currently has canonical-key support only in playlist overrides.

Container policy values:
- `no_webm_prefer_mp4` (default): preserve max resolution, prefer mp4 when tied, avoid final webm by remuxing to mp4/mkv.
- `force_mp4`: always target mp4-first selection/remux behavior.
- `prefer_source`: keep source container unless other settings force conversion.

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
- subtitle sidecars use `<base>.<lang>.<ext>` naming (for example `video.en.srt`)
- subtitle conversion/embedding defaults target `.srt` sidecars and embedded subtitles while retaining sidecar files
- when embedding is enabled with subtitle writing, sidecar subtitle files are preserved for external player/server discovery
- archive runs write full yt-dlp metadata sidecars (`<base>.info.json`) by default
- archive runs also write project-owned full metadata sidecars (`<base>.metadata.json`) by default
- per-video NFO now includes episode-level tags (`showtitle`, `season`, `episode`, `aired`, `uniqueid`, runtime, ratings/tags/genres when available)

## Artifact lifecycle (default archive run)
Given output stem `<base>` for a downloaded video:
- `<base>.mp4` (or configured merged media output)
- `<base>.info.json` (yt-dlp metadata sidecar)
- `<base>.metadata.json` (project-owned full metadata payload + run context)
- `<base>.nfo` (when `media_server.generate_nfo = true`)
- `<base>.<lang>.srt` subtitle sidecars (with fallback extension when conversion is unavailable)
- `<base>.<image_ext>` thumbnail sidecar when thumbnail writing is enabled

Notes:
- Subtitles are embedded by default and sidecars are retained.
- Sidecar naming follows `<base>.<lang>.<ext>` for media player/media server auto-detection.
- NFO XML escapes entities by design (for example `People &amp; Blogs` in raw XML corresponds to `People & Blogs` when parsed).
- Archive runs now surface a warning in default mode when `<base>.metadata.json` cannot be written.
- `<base>.metadata.json` sidecars resolve from final media stem when available, with canonical-stem fallback alignment.
- Metadata sidecar serialization tolerates non-pickleable runtime objects from extractor results.
- Metadata backfill (`--scope full`) also refreshes per-video `.nfo` and `<base>.metadata.json` using the same config gates.
- Download runs reconcile fallback stems after completion when final metadata provides canonical token values.
- Metadata backfill `--scope full` repairs legacy fallback stems and skips conflicting rename targets with warnings.
- Metadata backfill reuses `archive.delay_between_videos` for pacing extractor requests and inter-video backfill cadence.
- When a rate-limit response is detected during metadata backfill, default continue mode warns and pauses remaining videos in the current playlist.
