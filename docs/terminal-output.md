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
✅ Thumbnail generated: <title> [.jpg]
✅ .mp4 generated: <title> [1080p, 350mb]
⚠️ Warning: <message>
📊 Playlist Complete: <n> new, <n> failed
```

## Quiet mode (`-q`)
- Suppresses normal progress and success lines.
- Shows errors/warnings and failure-oriented playlist summary lines.

## Verbose mode (`-v`)
- Emits additional technical informational/debug messages.
- Includes detailed progress diagnostics useful for troubleshooting.

## No color (`--no-color`)
- Disables colored text styling.
- Symbols/emojis may still appear depending on formatter and terminal support.
