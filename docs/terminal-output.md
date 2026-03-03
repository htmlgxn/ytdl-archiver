# Terminal Output Reference

Output is formatter-driven and depends on mode.

## Progress mode (default)
Typical flow:
1. Header with app name/version
2. Playlist start line with playlist name and item count
3. Per-video progress updates
4. Download completion lines
5. Optional generated-artifact lines (thumbnail/mp4/NFO/subtitles when applicable)
6. Playlist summary (`new`, `failed`, or "already up to date")

Representative messages:
```text
📺 ytdl-archiver v<version>
🗂️ Archive directory: <path>/<directory>
📋 Processing: <playlist> (<n> videos)
🔵 <title> 45%|██████▌... [elapsed<remaining, rate]
✅ Downloaded: <title> [1080p, .mp4, 350mb]
✅ Downloaded subtitles: <title> [.srt]
✅ Downloaded subtitles: <title> [.vtt -> .srt]
✅ Thumbnail generated: <title> [.jpg]
✅ .mp4 generated: <title> [1080p, 350mb]
⚠️ Warning: <message>
📊 Playlist Complete: <n> new, <n> failed
```

## Quiet mode (`-q`)
- Suppresses normal progress and success lines.
- Shows errors/warnings and failure-oriented playlist summary lines.

## Verbose mode (`-v`)
- Emits additional structured technical informational/debug messages.
- Includes diagnostics for metadata prefetch, fallback paths, cookie refresh lifecycle,
  playlist metadata fetch, and retry/failure context.
- Does **not** pass through raw yt-dlp verbose output.

Default progress mode suppresses troubleshooting internals and keeps output focused on
progress, completions, warnings/errors, and summaries.
Subtitle sidecar completion lines reuse the active video title; they should not appear as
`Unknown` during normal downloads.
Subtitle lines are emitted from post-download file inspection, so they still appear even
when yt-dlp progress hook metadata is sparse.
When subtitle embedding is enabled, sidecars are still retained and counted for CLI subtitle
status lines.

## No color (`--no-color`)
- Disables colored text styling.
- Symbols/emojis may still appear depending on formatter and terminal support.
