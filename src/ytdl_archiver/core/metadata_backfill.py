"""Metadata backfill workflow for archived YouTube videos."""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import yt_dlp

from ..exceptions import ArchiveError
from ..output import emit_formatter_message, emit_rendered
from .archive import ArchiveTracker
from .utils import build_output_filename

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    logger = logging.getLogger(__name__)


@dataclass
class PlaylistBackfillStats:
    """Track metadata backfill status for one playlist."""

    updated: int = 0
    skipped_existing: int = 0
    failed: int = 0


class MetadataBackfiller:
    """Backfill metadata sidecars for already archived videos."""

    _MEDIA_EXTENSIONS: ClassVar[set[str]] = {
        ".mp4",
        ".mkv",
        ".webm",
        ".mov",
        ".m4v",
        ".avi",
        ".flv",
        ".ts",
        ".m2ts",
        ".mpg",
        ".mpeg",
        ".wmv",
    }

    def __init__(self, config, formatter=None):
        self.config = config
        self.formatter = formatter

    def run(
        self,
        *,
        scope: str = "full",
        refresh_existing: bool = False,
        limit_per_playlist: int | None = None,
        continue_on_error: bool = True,
    ) -> dict[str, int]:
        """Backfill metadata for all configured playlists."""
        playlists = self.config.load_playlists()
        totals = PlaylistBackfillStats()

        for playlist in playlists:
            playlist_id = str(playlist.get("id") or "").strip()
            playlist_path = str(playlist.get("path") or "").strip()
            if not playlist_id or not playlist_path:
                self._emit("warning", "Invalid playlist entry - skipping")
                continue

            playlist_stats = self._process_playlist(
                playlist_path=playlist_path,
                scope=scope,
                refresh_existing=refresh_existing,
                limit_per_playlist=limit_per_playlist,
                continue_on_error=continue_on_error,
            )
            totals.updated += playlist_stats.updated
            totals.skipped_existing += playlist_stats.skipped_existing
            totals.failed += playlist_stats.failed

            playlist_summary = (
                f"Metadata backfill complete: {playlist_path} "
                f"(updated={playlist_stats.updated}, "
                f"skipped_existing={playlist_stats.skipped_existing}, "
                f"failed={playlist_stats.failed})"
            )
            self._emit("info", playlist_summary)

        final_summary = (
            "Metadata backfill totals: "
            f"updated={totals.updated}, "
            f"skipped_existing={totals.skipped_existing}, "
            f"failed={totals.failed}"
        )
        self._emit("info", final_summary)

        return {
            "updated": totals.updated,
            "skipped_existing": totals.skipped_existing,
            "failed": totals.failed,
        }

    def _emit(self, level: str, message: str) -> None:
        """Emit message through formatter, with fallback plain output."""
        if self.formatter:
            emit_formatter_message(self.formatter, level, message)
            return

        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)
            emit_rendered(message)

    def _process_playlist(
        self,
        *,
        playlist_path: str,
        scope: str,
        refresh_existing: bool,
        limit_per_playlist: int | None,
        continue_on_error: bool,
    ) -> PlaylistBackfillStats:
        """Backfill metadata for one playlist directory."""
        stats = PlaylistBackfillStats()
        playlist_directory = self.config.get_archive_directory() / playlist_path
        archive_file = playlist_directory / ".archive.txt"
        archived_ids = self._load_archived_video_ids(archive_file)

        if limit_per_playlist is not None:
            archived_ids = archived_ids[:limit_per_playlist]

        if self.formatter:
            emit_rendered(
                self.formatter.playlist_start(
                    playlist_path, len(archived_ids), include_videos_label=False
                )
            )

        for video_id in archived_ids:
            try:
                outcome = self._process_video(
                    video_id=video_id,
                    playlist_directory=playlist_directory,
                    scope=scope,
                    refresh_existing=refresh_existing,
                )
                if outcome == "updated":
                    stats.updated += 1
                elif outcome == "skipped_existing":
                    stats.skipped_existing += 1
                else:
                    stats.failed += 1
            except (yt_dlp.DownloadError, OSError, ValueError, RuntimeError) as e:
                stats.failed += 1
                self._emit(
                    "error",
                    f"Metadata backfill failed for {video_id} in {playlist_path}: {e!s}",
                )
                if not continue_on_error:
                    raise ArchiveError(
                        f"Metadata backfill failed for {video_id}: {e}"
                    ) from e

        # Create tvshow.nfo for Jellyfin TV show library treatment
        self._create_tvshow_nfo_if_needed(playlist_directory)

        return stats

    def _load_archived_video_ids(self, archive_file: Path) -> list[str]:
        """Read and normalize video IDs from archive file."""
        if not archive_file.exists():
            return []

        video_ids: list[str] = []
        seen: set[str] = set()
        for line in archive_file.read_text(encoding="utf-8").splitlines():
            candidates = ArchiveTracker._extract_video_id_candidates(line)
            for candidate in candidates:
                normalized = candidate.strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                video_ids.append(normalized)
        return video_ids

    def _process_video(
        self,
        *,
        video_id: str,
        playlist_directory: Path,
        scope: str,
        refresh_existing: bool,
    ) -> str:
        """Backfill sidecars for one archived video."""
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        metadata = self._fetch_metadata(video_url)
        if not metadata:
            return "failed"

        canonical_stem = build_output_filename(self.config, metadata, video_url)
        output_stem = self._resolve_output_stem(
            playlist_directory, canonical_stem, video_id
        )

        info_json_path = playlist_directory / f"{output_stem}.info.json"
        if info_json_path.exists() and not refresh_existing:
            return "skipped_existing"

        opts = self._build_metadata_only_opts(
            playlist_directory=playlist_directory,
            output_stem=output_stem,
            scope=scope,
            refresh_existing=refresh_existing,
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.extract_info(video_url, download=False)
        if not result:
            return "failed"
        return "updated"

    def _fetch_metadata(self, video_url: str) -> dict[str, Any] | None:
        """Fetch metadata without writing sidecars."""
        opts = self._build_common_opts()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            if isinstance(info, dict):
                return info
            return None

    def _resolve_output_stem(
        self, playlist_directory: Path, canonical_stem: str, video_id: str
    ) -> str:
        """Prefer existing media stem if present; otherwise use canonical stem."""
        if self._media_stem_exists(playlist_directory, canonical_stem):
            return canonical_stem

        for candidate in sorted(playlist_directory.glob("*")):
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in self._MEDIA_EXTENSIONS:
                continue
            if video_id in candidate.stem:
                return candidate.stem

        return canonical_stem

    def _media_stem_exists(self, playlist_directory: Path, stem: str) -> bool:
        for extension in self._MEDIA_EXTENSIONS:
            if (playlist_directory / f"{stem}{extension}").exists():
                return True
        return False

    def _build_common_opts(self) -> dict[str, Any]:
        """Build common yt-dlp options shared by metadata calls."""
        opts = {
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "no_color": True,
            "skip_download": True,
            "noplaylist": True,
            "http_headers": {"User-Agent": self.config.get("http.user_agent")},
            "socket_timeout": self.config.get("http.request_timeout"),
            "connect_timeout": self.config.get("http.connect_timeout"),
            "extractor_args": {"youtube": {"player_client": "default"}},
            # Use same format/sort settings as download for consistency
            "format": self.config.get("download.format"),
            "format_sort": self.config.get("download.format_sort"),
        }
        cookie_path = self.config.get_cookie_file_path()
        if cookie_path:
            opts["cookiefile"] = str(cookie_path)
        return {key: value for key, value in opts.items() if value is not None}

    def _build_metadata_only_opts(
        self,
        *,
        playlist_directory: Path,
        output_stem: str,
        scope: str,
        refresh_existing: bool,
    ) -> dict[str, Any]:
        """Build metadata-only yt-dlp options for sidecar generation."""
        output_base = str(playlist_directory / f"{output_stem}.%(ext)s")
        opts = self._build_common_opts()
        opts.update(
            {
                "writeinfojson": True,
                "outtmpl": {
                    "default": output_base,
                    "subtitle": str(
                        playlist_directory / f"{output_stem}.%(lang)s.%(ext)s"
                    ),
                    "thumbnail": output_base,
                },
                "nooverwrites": not refresh_existing,
            }
        )

        if scope == "full":
            opts.update(
                {
                    "writethumbnail": True,
                    "writesubtitles": True,
                    "writeautomaticsub": True,
                    "subtitleslangs": self.config.get("download.subtitle_languages"),
                    "subtitlesformat": self.config.get("download.subtitle_format"),
                    "writecomments": True,
                }
            )

        return {key: value for key, value in opts.items() if value is not None}

    def _create_tvshow_nfo_if_needed(
        self, playlist_directory: Path
    ) -> bool:
        """Create tvshow.nfo for Jellyfin TV show library treatment if not exists."""
        if not self.config.get("media_server.generate_nfo", True):
            return False

        tvshow_nfo_path = playlist_directory / "tvshow.nfo"
        if tvshow_nfo_path.exists():
            return False

        try:
            # Extract channel name from existing videos
            channel_name = self._extract_channel_name_from_existing_videos(
                playlist_directory
            )
            if channel_name:
                nfo_content = self._generate_tvshow_nfo_content(channel_name)
                tvshow_nfo_path.write_text(nfo_content, encoding="utf-8")
                logger.info(
                    "TV show NFO file created",
                    extra={"nfo_path": str(tvshow_nfo_path)},
                )
                return True
            return False

        except (OSError, ValueError, RuntimeError, TypeError) as e:
            logger.exception(
                "Failed to generate TV show NFO",
                extra={"error": str(e)},
            )
            return False

    def _extract_channel_name_from_existing_videos(
        self, playlist_directory: Path
    ) -> str | None:
        """Extract channel name from existing video NFO files."""
        # Look for existing episode NFO files and extract channel/studio name
        for nfo_file in playlist_directory.glob("*.nfo"):
            if nfo_file.name == "tvshow.nfo":
                continue

            try:
                content = nfo_file.read_text(encoding="utf-8")
                channel = self._extract_channel_from_nfo(content)
                if channel:
                    return channel
            except (OSError, UnicodeDecodeError):
                continue

        # Fallback: try to extract from info.json files
        for info_json in playlist_directory.glob("*.info.json"):
            try:
                data = json.loads(info_json.read_text(encoding="utf-8"))
                for key in ("channel", "uploader", "channel_id"):
                    value = data.get(key)
                    if value and isinstance(value, str) and value.strip():
                        return value.strip()
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue

        return None

    def _extract_channel_from_nfo(self, content: str) -> str | None:
        """Extract channel/studio name from NFO XML content."""
        # Try to extract <studio> tag from episodedetails
        match = re.search(r"<studio>([^<]+)</studio>", content)
        if match:
            return match.group(1).strip()

        # Try to extract <showtitle> tag
        match = re.search(r"<showtitle>([^<]+)</showtitle>", content)
        if match:
            return match.group(1).strip()

        return None

    def _generate_tvshow_nfo_content(self, channel_name: str) -> str:
        """Generate tvshow.nfo content from channel name."""
        # XML escaping
        escaped_name = (
            channel_name.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )
        return f"""<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<tvshow>
  <title>{escaped_name}</title>
</tvshow>
"""
