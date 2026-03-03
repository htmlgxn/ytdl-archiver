"""Metadata backfill workflow for archived YouTube videos."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import yt_dlp

from ..exceptions import ArchiveError
from ..output import emit_formatter_message, emit_rendered
from .artifacts import rename_stem_artifacts, stem_looks_like_fallback
from .archive import ArchiveTracker
from .downloader import YouTubeDownloader
from .metadata import MetadataGenerator
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
        self.metadata_generator = MetadataGenerator(config)
        self.downloader = YouTubeDownloader(config, formatter)

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
            playlist_name = str(playlist.get("name") or "").strip() or None
            if not playlist_id or not playlist_path:
                self._emit("warning", "Invalid playlist entry - skipping")
                continue

            playlist_stats = self._process_playlist(
                playlist_id=playlist_id,
                playlist_path=playlist_path,
                playlist_name=playlist_name,
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
        playlist_id: str,
        playlist_path: str,
        playlist_name: str | None,
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
        playlist_config = self.config.get_playlist_config(playlist_id)

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
                    playlist_config=playlist_config,
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
        self._create_tvshow_nfo_if_needed(
            playlist_directory,
            playlist_name=playlist_name,
            playlist_path=playlist_path,
        )

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
        playlist_config: dict[str, Any],
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
        if scope == "full":
            output_stem = self._reconcile_existing_stem(
                playlist_directory=playlist_directory,
                source_stem=output_stem,
                target_stem=canonical_stem,
            )

        write_info_json = self._resolve_bool_setting(
            playlist_config, "write_info_json", "writeinfojson", default=True
        )
        write_max_metadata = self._resolve_bool_setting(
            playlist_config, "write_max_metadata_json", default=True
        )
        generate_nfo = bool(self.config.get("media_server.generate_nfo", True))

        info_json_path = playlist_directory / f"{output_stem}.info.json"
        nfo_path = playlist_directory / f"{output_stem}.nfo"
        metadata_json_path = playlist_directory / f"{output_stem}.metadata.json"

        needs_info_json = bool(
            write_info_json and (refresh_existing or not info_json_path.exists())
        )
        needs_nfo = bool(scope == "full" and generate_nfo)
        needs_metadata_json = bool(
            scope == "full"
            and write_max_metadata
            and (refresh_existing or not metadata_json_path.exists())
        )

        if not (needs_info_json or needs_nfo or needs_metadata_json):
            return "skipped_existing"

        extracted_result: dict[str, Any] = metadata
        if needs_info_json:
            opts = self._build_metadata_only_opts(
                playlist_directory=playlist_directory,
                output_stem=output_stem,
                scope=scope,
                refresh_existing=refresh_existing,
            )
            with yt_dlp.YoutubeDL(opts) as ydl:
                result = ydl.extract_info(video_url, download=False)
            if not isinstance(result, dict) or not result:
                return "failed"
            extracted_result = result

        if needs_nfo:
            self.metadata_generator.create_nfo_file(extracted_result, nfo_path)

        if needs_metadata_json:
            base_path = self.downloader._resolve_output_base_path(
                playlist_directory, output_stem, extracted_result
            )
            self.downloader._write_max_metadata_sidecar(
                base_path=base_path,
                video_url=video_url,
                download_result=extracted_result,
            )

        return "updated"

    def _reconcile_existing_stem(
        self,
        *,
        playlist_directory: Path,
        source_stem: str,
        target_stem: str,
    ) -> str:
        if not source_stem or not target_stem:
            return source_stem
        if source_stem == target_stem:
            return source_stem
        if stem_looks_like_fallback(target_stem) and not stem_looks_like_fallback(source_stem):
            return source_stem
        if stem_looks_like_fallback(source_stem) and stem_looks_like_fallback(target_stem):
            return source_stem

        rename_result = rename_stem_artifacts(
            playlist_directory, source_stem, target_stem
        )
        if rename_result.status == "renamed":
            return target_stem

        if rename_result.status == "conflict":
            self._emit(
                "warning",
                (
                    "Rename skipped: target stem already exists "
                    f"({source_stem} -> {target_stem})"
                ),
            )
            return source_stem

        if rename_result.status == "failed":
            self._emit(
                "warning",
                (
                    "Rename failed: could not reconcile artifact stem "
                    f"({source_stem} -> {target_stem})"
                ),
            )
            return source_stem

        return source_stem

    def _resolve_bool_setting(
        self,
        playlist_config: dict[str, Any],
        *keys: str,
        default: bool,
    ) -> bool:
        for key in keys:
            if key in playlist_config:
                return bool(playlist_config.get(key))
            value = self.config.get(f"download.{key}")
            if value is not None:
                return bool(value)
        return default

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
        self,
        playlist_directory: Path,
        *,
        playlist_name: str | None,
        playlist_path: str,
    ) -> bool:
        """Create tvshow.nfo for Jellyfin TV show library treatment if not exists."""
        if not self.config.get("media_server.generate_nfo", True):
            return False

        tvshow_nfo_path = playlist_directory / "tvshow.nfo"
        if tvshow_nfo_path.exists():
            return False

        try:
            tvshow_title = self._resolve_tvshow_title(
                playlist_directory=playlist_directory,
                playlist_name=playlist_name,
                playlist_path=playlist_path,
            )
            if tvshow_title:
                self.metadata_generator.create_tvshow_nfo(tvshow_title, tvshow_nfo_path)
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

    def _resolve_tvshow_title(
        self,
        *,
        playlist_directory: Path,
        playlist_name: str | None,
        playlist_path: str,
    ) -> str:
        configured_name = str(playlist_name or "").strip()
        if configured_name:
            return configured_name

        path_name = str(playlist_path or "").strip().rstrip("/\\")
        if path_name:
            return Path(path_name).name

        return playlist_directory.name.strip()
