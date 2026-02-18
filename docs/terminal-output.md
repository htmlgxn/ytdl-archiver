# Terminal Output While Archiving a YouTube Playlist

## Normal/Progress Mode

### 1. Header
```
📺 ytdl-archiver v2026.2.7
```

### 2. Playlist Start
```
📋 Processing: <playlist-name> (<n> videos)
```

### 3. Per-Video Progress
During download, a tqdm progress bar shows:
```
🔵 <video-title> 45%|██████▌░░░░░| 45/100 [00:15<00:20, 1.2MB/s]
```

### 4. Video Completion (when done)
```
✅ Downloaded: <video-title> [1080p] <file-size>
```

### 5. Generated Files
```
✅ Generated: NFO metadata
✅ Generated: Thumbnail image
✅ Generated: Subtitle file (if subtitles downloaded)
```

### 6. Skipped Videos (already archived)
```
⚠️ Warning: Already downloaded: <video-title>
```

### 7. Playlist Summary
```
📊 Playlist Complete: <n> new, <n> skipped, <n> failed
```
(or `📊 Playlist Complete: already up to date` if nothing new)

---

## Other Modes

- **Quiet mode (`-q`)**: Only shows errors and final summary
- **Verbose mode (`-v`)**: Shows full yt-dlp debug output with detailed progress info
- **No colors (`--no-color`)**: Uses text symbols like `[OK]`, `[WARN]`, `[ERR]` instead of emojis
