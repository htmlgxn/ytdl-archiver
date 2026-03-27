"""yt-dlp progress callback and media type constants."""

import re
from pathlib import Path
from typing import Any, ClassVar

from ..output import emit_rendered

SUBTITLE_EXTENSIONS: set[str] = {
    ".srt",
    ".vtt",
    ".ass",
    ".ssa",
    ".ttml",
    ".srv1",
    ".srv2",
    ".srv3",
}

VIDEO_EXTENSIONS: set[str] = {
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
    ".m4a",
    ".mp3",
    ".aac",
    ".opus",
    ".wav",
    ".flac",
}

THUMBNAIL_EXTENSIONS: set[str] = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
}

INTERMEDIATE_MEDIA_EXTENSIONS: set[str] = {
    ".webm",
    ".m4a",
    ".mp4",
    ".mkv",
    ".mov",
    ".ts",
}


class ProgressCallback:
    """Progress callback for yt-dlp with formatter integration."""

    THUMBNAIL_EXTENSIONS: ClassVar[set[str]] = THUMBNAIL_EXTENSIONS
    INTERMEDIATE_MEDIA_EXTENSIONS: ClassVar[set[str]] = INTERMEDIATE_MEDIA_EXTENSIONS
    PRIMARY_VIDEO_EXTENSIONS: ClassVar[set[str]] = VIDEO_EXTENSIONS
    SUBTITLE_EXTENSIONS: ClassVar[set[str]] = SUBTITLE_EXTENSIONS

    def __init__(self, formatter):
        self.formatter = formatter
        self.current_video = None
        self._primary_emitted_for_current = False
        self._emitted_artifact_exts: set[str] = set()

    @staticmethod
    def _normalize_extension(extension: str) -> str:
        """Normalize extension to .ext lowercase format."""
        ext = extension.strip().lower()
        if not ext:
            return ""
        if not ext.startswith("."):
            return f".{ext}"
        return ext

    def _extract_extension(self, d: dict[str, Any]) -> str:
        """Extract extension from callback payload."""
        filename = str(d.get("filename") or "").strip()
        if filename:
            suffix = Path(filename).suffix
            if suffix:
                return self._normalize_extension(suffix)

        info_ext = str(d.get("info_dict", {}).get("ext") or "").strip()
        return self._normalize_extension(info_ext)

    @staticmethod
    def _format_size(total_bytes: int) -> str:
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

    @staticmethod
    def _parse_size_text(size_text: str) -> int | None:
        """Parse yt-dlp size strings like 100MiB/1.25GiB to bytes."""
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([KMGTP]?)i?B", size_text, re.I)
        if not match:
            return None

        value = float(match.group(1))
        prefix = match.group(2).upper()
        power = {"": 0, "K": 1, "M": 2, "G": 3, "T": 4, "P": 5}.get(prefix)
        if power is None:
            return None

        return int(value * (1024**power))

    def _extract_size(self, d: dict[str, Any]) -> str:
        """Extract and normalize size text from callback payload."""
        for key in ("total_bytes", "total_bytes_estimate", "downloaded_bytes"):
            raw_value = d.get(key)
            if isinstance(raw_value, (int, float)) and raw_value > 0:
                return self._format_size(int(raw_value))

        size_text = str(
            d.get("total_bytes_str") or d.get("_total_bytes_str") or ""
        ).strip()
        if not size_text:
            return ""

        parsed_bytes = self._parse_size_text(size_text)
        if parsed_bytes is None:
            return ""
        return self._format_size(parsed_bytes)

    @staticmethod
    def _extract_resolution(d: dict[str, Any]) -> str:
        """Extract display resolution from callback payload."""
        info = d.get("info_dict", {})
        height = info.get("height")
        width = info.get("width")
        if height and width:
            return f"{height}p"
        return ""

    def _reset_current_video_state(self, title: str) -> None:
        """Reset per-video completion tracking."""
        self.current_video = title
        self._primary_emitted_for_current = False
        self._emitted_artifact_exts = set()

    def _artifact_type_for_extension(self, extension: str) -> str:
        """Map known extension types to readable artifact labels."""
        if extension in self.THUMBNAIL_EXTENSIONS:
            return "thumbnail"
        return ""

    def _extract_subtitle_language(self, d: dict[str, Any]) -> str:
        """Extract subtitle language identifier for deduplication."""
        info = d.get("info_dict", {})
        for key in ("lang", "language", "subtitle_lang"):
            value = str(info.get(key) or "").strip()
            if value:
                return value.lower()

        filename = str(d.get("filename") or "").strip()
        if not filename:
            return ""

        stem = Path(filename).stem
        parts = stem.split(".")
        if len(parts) < 2:
            return ""

        candidate = parts[-1].strip().lower()
        if candidate and candidate != "na":
            return candidate
        return ""

    def __call__(self, d: dict[str, Any]) -> None:
        """Handle yt-dlp progress callback."""
        if d["status"] == "downloading" and self.formatter:
            title = d.get("info_dict", {}).get("title") or self.current_video or "Unknown"
            if self.current_video != title and title != "Unknown":
                self._reset_current_video_state(title)
                # Start new progress bar
                if hasattr(self.formatter, "start_video_progress"):
                    self.formatter.start_video_progress(title)
                else:
                    # Fallback to old behavior
                    start_msg = f"🔵 Starting download: {title}"
                    emit_rendered(start_msg)

            # Update progress bar
            if hasattr(self.formatter, "update_video_progress"):
                self.formatter.update_video_progress(
                    {
                        "percent": d.get("_percent_str", "0%"),
                        "speed": d.get("_speed_str", ""),
                        "eta": d.get("_eta_str", ""),
                    }
                )
            else:
                # Fallback to old behavior
                progress_msg = self.formatter.video_progress(
                    self.current_video,
                    {
                        "percent": d.get("_percent_str", "0%"),
                        "speed": d.get("_speed_str", ""),
                        "eta": d.get("_eta_str", ""),
                    },
                )
                if progress_msg:
                    emit_rendered(progress_msg)

        elif d["status"] == "finished" and self.formatter:
            title = (
                d.get("info_dict", {}).get("title") or self.current_video or "Unknown"
            )
            if self.current_video != title and title != "Unknown":
                self._reset_current_video_state(title)

            if hasattr(self.formatter, "close_video_progress"):
                self.formatter.close_video_progress()

            extension = self._extract_extension(d)
            resolution = self._extract_resolution(d)
            size = self._extract_size(d)
            primary_ext = self._normalize_extension(
                str(d.get("info_dict", {}).get("ext") or "")
            )

            candidate_primary = primary_ext or extension
            is_primary = (
                not self._primary_emitted_for_current
                and candidate_primary in self.PRIMARY_VIDEO_EXTENSIONS
                and extension in self.PRIMARY_VIDEO_EXTENSIONS
            )

            if is_primary:
                complete_msg = self.formatter.video_complete(
                    title, resolution, extension, size
                )
                emit_rendered(complete_msg)
                self._primary_emitted_for_current = True
            elif (
                extension
                and extension in self.SUBTITLE_EXTENSIONS
                and extension not in self.INTERMEDIATE_MEDIA_EXTENSIONS
                and extension not in self.THUMBNAIL_EXTENSIONS
            ):
                # Subtitle reporting is emitted from deterministic filesystem scans
                # after download completion to avoid missing/duplicate/unknown lines.
                return
