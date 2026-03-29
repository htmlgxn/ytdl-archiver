# Changelog

## v0.5.0
- **New dedupe features**: Enhanced `dedupe` command with archive consolidation, cross-bucket filename fallback matching, and improved output rendering
- Consolidate undated archive duplicates automatically
- Dispose source non-video files after replace operations
- Detailed operation output with SRC/ARC/FINAL blocks showing file movements
- Archive-only consolidation for undated duplicates sharing normalized filenames
- Live chat JSON files imported to `live-chats/` subdirectory
- Apostrophe normalization for filename matching (e.g., "there's" matches "theres")
- Part files (`.part`) ignored during scan

## v0.4.0
- Major refactoring of core dedupe and archive logic
- Major bug fixes including:
  - Skipping videos that should be processed
  - Selecting incorrect audio language
  - Selecting inconsistent video stream
- More testing likely needed for stability

## v0.3.0
- Full documentation refresh for release readiness.
- Removed drift between docs and runtime CLI/config behavior.
- Documented all first-class commands (`archive`, `metadata-backfill`, `search`, `convert-playlists`, `init`).
- Clarified verbose mode contract as structured diagnostics without raw yt-dlp passthrough.
- Documented default metadata artifact contract (`.info.json`, `.metadata.json`, enriched `.nfo`).
- Updated migration guidance for `0.2.x -> 0.3.0`.
