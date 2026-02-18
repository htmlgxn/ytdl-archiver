# Terminal Output Reference

Output is formatter-driven and varies by mode.

## Progress mode (default)
Typical flow:
1. Header with app name/version
2. Playlist start line with playlist name and item count
3. Per-video progress (tqdm bar when available)
4. Video completion line
5. Sidecar generation lines (NFO/thumbnail/subtitle when applicable)
6. Playlist summary (`new`, `skipped`, `failed` or "already up to date")

Representative messages:
```text
📺 ytdl-archiver v<version>
📋 Processing: <playlist> (<n> videos)
🔵 <title> 45%|██████▌... [elapsed<remaining, rate]
✅ Downloaded: <title> [1080p] <size>
✅ Generated: NFO metadata
✅ Generated: Thumbnail image
⚠️ Warning: Already downloaded: <title>
📊 Playlist Complete: <n> new, <n> skipped, <n> failed
```

## Quiet mode (`-q`)
- Suppresses normal progress output.
- Shows errors/warnings and failure-oriented summary output.

## Verbose mode (`-v`)
- Emits detailed informational/debug-style lines during download.
- Includes additional technical output for troubleshooting.

## No color (`--no-color`)
- Disables colored text and emoji-oriented presentation.
- Output keeps core message text with plain, unsymbolized formatting.
