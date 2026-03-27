"""Sidecar file generation: metadata JSON, subtitles, thumbnails."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yt_dlp

from ..output import emit_formatter_message, emit_rendered
from .progress import SUBTITLE_EXTENSIONS

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    logger = logging.getLogger(__name__)


def normalize_extension(extension: str) -> str:
    """Normalize extension to .ext format."""
    ext = extension.strip().lower()
    if not ext:
        return ""
    if not ext.startswith("."):
        return f".{ext}"
    return ext


def subtitle_base_name(path: Path) -> str:
    """Return subtitle base name without lang/extension suffix."""
    parts = path.name.split(".")
    if len(parts) >= 3:
        return ".".join(parts[:-2])
    if len(parts) == 2:
        return parts[0]
    return path.stem


def subtitle_status_for_file(
    subtitle_path: Path,
    all_subtitles: list[Path],
    requested_subtitles: dict[str, Any] | None = None,
) -> str:
    """Build subtitle status text for formatter output."""
    ext = normalize_extension(subtitle_path.suffix)
    if ext == ".srt":
        base = subtitle_base_name(subtitle_path)
        source_exts = {
            normalize_extension(candidate.suffix)
            for candidate in all_subtitles
            if subtitle_base_name(candidate) == base
        }
        if ".vtt" in source_exts:
            return ".vtt -> .srt"

        if requested_subtitles:
            lang = subtitle_path.stem.split(".")[-1].lower()
            sub_info = requested_subtitles.get(lang)
            if isinstance(sub_info, dict):
                source_ext = normalize_extension(str(sub_info.get("ext") or ""))
                if source_ext and source_ext != ".srt":
                    return f"{source_ext} -> .srt"
        return ".srt"
    if ext:
        return ext
    return "subtitles"


def collect_existing_subtitles(
    output_directory: Path, filename: str
) -> tuple[list[Path], list[Path]]:
    """Collect preferred subtitle files and all subtitle candidates."""
    candidates: list[Path] = []
    for path in sorted(output_directory.glob(f"{filename}.*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in SUBTITLE_EXTENSIONS:
            candidates.append(path)

    preferred_by_key: dict[str, Path] = {}
    for candidate in candidates:
        key = subtitle_base_name(candidate)
        existing = preferred_by_key.get(key)
        if existing is None:
            preferred_by_key[key] = candidate
            continue

        candidate_ext = normalize_extension(candidate.suffix)
        existing_ext = normalize_extension(existing.suffix)
        if candidate_ext == ".srt" and existing_ext != ".srt":
            preferred_by_key[key] = candidate

    preferred = sorted(preferred_by_key.values(), key=lambda p: p.name)
    return preferred, candidates


def first_existing_thumbnail(
    output_directory: Path, filename: str
) -> tuple[Path, str] | None:
    """Find the first thumbnail file generated for a video."""
    thumbnail_extensions = (".jpg", ".jpeg", ".png", ".webp", ".gif")
    for extension in thumbnail_extensions:
        candidate = output_directory / f"{filename}{extension}"
        if candidate.exists():
            return candidate, extension
    return None


def iter_existing_result_filepaths(
    download_result: dict[str, Any] | None,
) -> list[Path]:
    """Extract existing local file paths from yt-dlp result payload."""
    if not isinstance(download_result, dict):
        return []

    paths: list[Path] = []
    requested_downloads = download_result.get("requested_downloads")
    if isinstance(requested_downloads, list):
        for entry in requested_downloads:
            if not isinstance(entry, dict):
                continue
            filepath = entry.get("filepath")
            if isinstance(filepath, str) and filepath.strip():
                path_obj = Path(filepath)
                if path_obj.exists() and path_obj.is_file():
                    paths.append(path_obj)

    fallback_filename = download_result.get("_filename")
    if isinstance(fallback_filename, str) and fallback_filename.strip():
        path_obj = Path(fallback_filename)
        if path_obj.exists() and path_obj.is_file():
            paths.append(path_obj)

    return paths


def resolve_final_media_path(
    output_directory: Path,
    filename: str,
    download_result: dict[str, Any] | None,
) -> Path | None:
    """Resolve the final primary media file path."""
    existing_result_paths = iter_existing_result_filepaths(download_result)
    if existing_result_paths:
        preferred_exts = (".mp4", ".mkv")
        for extension in preferred_exts:
            for path in existing_result_paths:
                if normalize_extension(path.suffix) == extension:
                    return path
        return existing_result_paths[0]

    for extension in (".mp4", ".mkv"):
        candidate = output_directory / f"{filename}{extension}"
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def resolve_output_base_path(
    output_directory: Path,
    filename: str,
    download_result: dict[str, Any] | None,
) -> Path:
    """Resolve base path used for sidecar outputs."""
    media_path = resolve_final_media_path(output_directory, filename, download_result)
    if media_path is not None:
        return media_path.with_suffix("")

    canonical_base = output_directory / filename
    return canonical_base


def extract_title(
    download_result: dict[str, Any] | None, metadata: dict[str, Any] | None
) -> str:
    """Extract best available title."""
    if download_result and download_result.get("title"):
        return str(download_result["title"])
    if metadata and metadata.get("title"):
        return str(metadata["title"])
    return "Unknown"


def extract_resolution_from_metadata(metadata: dict[str, Any] | None) -> str:
    """Extract display resolution from metadata."""
    if not metadata:
        return ""
    height = metadata.get("height")
    width = metadata.get("width")
    if height and width:
        return f"{height}p"
    return ""


def format_size_from_bytes(total_bytes: int) -> str:
    """Format bytes to mb/gb with requested precision rules."""
    if total_bytes <= 0:
        return ""

    gib = 1024**3
    mib = 1024**2

    if total_bytes >= gib:
        gb_value = total_bytes / gib
        formatted = f"{gb_value:.2f}".rstrip("0").rstrip(".")
        return f"{formatted}gb"

    mb_value = max(1, round(total_bytes / mib))
    return f"{int(mb_value)}mb"


def write_max_metadata_sidecar(
    *,
    base_path: Path,
    video_url: str,
    download_result: dict[str, Any] | None,
    formatter=None,
    verbose_debug=None,
) -> None:
    """Write full metadata sidecar as project-owned JSON payload."""
    if not isinstance(download_result, dict) or not download_result:
        return

    metadata_path = base_path.with_suffix(".metadata.json")
    tmp_path = metadata_path.with_suffix(".metadata.json.tmp")
    if verbose_debug:
        verbose_debug(
            "Writing metadata sidecar",
            metadata_path=str(metadata_path),
            video_url=video_url,
        )
    try:
        sanitized_info = yt_dlp.YoutubeDL.sanitize_info(download_result)
        payload = {
            "video_url": video_url,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "extractor": str(download_result.get("extractor") or ""),
            "metadata": sanitized_info,
        }
        try:
            serialized_payload = json.dumps(
                payload, indent=2, sort_keys=True, ensure_ascii=False
            )
        except (TypeError, ValueError):
            serialized_payload = json.dumps(
                payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
        tmp_path.write_text(
            serialized_payload + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(metadata_path)
        metadata_size = metadata_path.stat().st_size
        if verbose_debug:
            verbose_debug(
                "Metadata sidecar written",
                metadata_path=str(metadata_path),
                video_url=video_url,
                size_bytes=metadata_size,
            )
    except (OSError, TypeError, ValueError) as e:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        emit_formatter_message(
            formatter,
            "warning",
            f"Metadata sidecar not written ({type(e).__name__}: {e!s})",
        )
        if verbose_debug:
            verbose_debug(
                f"Failed to write metadata sidecar ({type(e).__name__}: {e!s})",
                metadata_path=str(metadata_path),
                video_url=video_url,
            )
        logger.warning(
            "Failed to write metadata sidecar",
            extra={"metadata_path": str(metadata_path), "error": str(e)},
        )


def emit_post_download_generated_lines(
    output_directory: Path,
    stem: str,
    download_result: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    formatter=None,
    emitted_subtitle_paths: set[str] | None = None,
) -> None:
    """Emit generated artifact lines based on actual files on disk."""
    if not formatter:
        return
    if emitted_subtitle_paths is None:
        emitted_subtitle_paths = set()

    title = extract_title(download_result, metadata)
    resolution = extract_resolution_from_metadata(download_result or metadata)

    thumbnail = first_existing_thumbnail(output_directory, stem)
    if thumbnail is not None:
        _, thumbnail_ext = thumbnail
        emit_rendered(formatter.thumbnail_generated(title, thumbnail_ext))

    media_path = resolve_final_media_path(output_directory, stem, download_result)
    if media_path is not None:
        media_size = format_size_from_bytes(media_path.stat().st_size)
        emit_rendered(
            formatter.container_generated(
                title, media_path.suffix, resolution, media_size
            )
        )

    subtitle_files, subtitle_candidates = collect_existing_subtitles(
        output_directory, stem
    )
    requested_subtitles: dict[str, Any] | None = None
    if isinstance(download_result, dict):
        raw_requested = download_result.get("requested_subtitles")
        if isinstance(raw_requested, dict):
            requested_subtitles = raw_requested
    for subtitle_path in subtitle_files:
        subtitle_key = str(subtitle_path.resolve())
        if subtitle_key in emitted_subtitle_paths:
            continue
        status = subtitle_status_for_file(
            subtitle_path, subtitle_candidates, requested_subtitles
        )
        emit_rendered(formatter.subtitle_downloaded(title, status))
        emitted_subtitle_paths.add(subtitle_key)
