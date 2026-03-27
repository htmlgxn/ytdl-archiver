"""Cross-directory duplicate reconciliation for archived artifacts."""

from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import collect_artifacts_for_stem, rename_stem_artifacts
from .utils import build_output_filename, extract_video_id

_MEDIA_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".webm",
    ".m4v",
    ".mov",
    ".avi",
    ".m4a",
    ".mp3",
    ".opus",
    ".flac",
    ".wav",
}
_SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa", ".lrc"}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_KNOWN_SINGLE_EXTENSIONS = (
    _MEDIA_EXTENSIONS
    | _SUBTITLE_EXTENSIONS
    | _IMAGE_EXTENSIONS
    | {".nfo", ".description", ".txt"}
)
_DATE_PREFIX_RE = re.compile(r"^(?:\d{8}|\d{4}[-_.]\d{2}[-_.]\d{2})[-_. ]*")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_LANGUAGE_TOKEN_RE = re.compile(r"\.[A-Za-z0-9-]+$")
_YOUTUBE_ID_RE = re.compile(r"[-_A-Za-z0-9]{11}")


@dataclass
class StemGroup:
    """Artifacts in one directory sharing a common filename stem."""

    directory: Path
    stem: str
    files: list[Path]
    video_id: str | None
    total_size: int
    canonical_metadata: dict[str, Any] | None = None
    canonical_video_url: str = ""
    canonical_stem: str | None = None


@dataclass
class DedupeSet:
    """Matching groups describing duplicate copies of the same video."""

    match_key: str
    match_method: str
    groups: list[StemGroup]


def _strip_known_suffix(name: str) -> str | None:
    lower_name = name.lower()
    if lower_name in {"tvshow.nfo"} or name.startswith("."):
        return None

    if lower_name.endswith(".metadata.json"):
        return name[: -len(".metadata.json")]
    if lower_name.endswith(".info.json"):
        return name[: -len(".info.json")]

    path = Path(name)
    suffixes = path.suffixes
    if not suffixes:
        return None

    if len(suffixes) >= 2 and suffixes[-1].lower() in _SUBTITLE_EXTENSIONS:
        lang_suffix = suffixes[-2]
        if _LANGUAGE_TOKEN_RE.fullmatch(lang_suffix):
            return name[: -(len(lang_suffix) + len(suffixes[-1]))]

    if suffixes[-1].lower() in _KNOWN_SINGLE_EXTENSIONS:
        return path.stem

    return path.stem


def _normalize_fallback_stem(stem: str) -> str:
    normalized = _DATE_PREFIX_RE.sub("", stem.strip().lower())
    normalized = _NON_ALNUM_RE.sub("-", normalized)
    return normalized.strip("-")


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if isinstance(data, dict):
        return data
    return None


def _metadata_candidates(group: StemGroup) -> list[tuple[dict[str, Any], str]]:
    candidates: list[tuple[dict[str, Any], str]] = []

    metadata_path = group.directory / f"{group.stem}.metadata.json"
    metadata_data = _safe_read_json(metadata_path)
    if metadata_data:
        metadata = metadata_data.get("metadata")
        if isinstance(metadata, dict):
            url = str(
                metadata_data.get("video_url")
                or metadata.get("webpage_url")
                or metadata.get("url")
                or ""
            )
            candidates.append((metadata, url))
        else:
            url = str(metadata_data.get("video_url") or metadata_data.get("webpage_url") or "")
            candidates.append((metadata_data, url))

    info_path = group.directory / f"{group.stem}.info.json"
    info_data = _safe_read_json(info_path)
    if info_data:
        url = str(
            info_data.get("webpage_url")
            or info_data.get("original_url")
            or info_data.get("url")
            or ""
        )
        candidates.append((info_data, url))

    return candidates


def extract_video_id_from_stem_group(group: StemGroup) -> str | None:
    """Extract a stable video ID from group sidecars or fallback filename."""
    for metadata, video_url in _metadata_candidates(group):
        metadata_id = str(metadata.get("id") or "").strip()
        if metadata_id:
            return metadata_id
        extracted = str(extract_video_id(video_url, metadata)).strip()
        if extracted and extracted != "unknown-video":
            return extracted

    nfo_path = group.directory / f"{group.stem}.nfo"
    if nfo_path.exists():
        try:
            root = ET.fromstring(nfo_path.read_text(encoding="utf-8"))
        except (ET.ParseError, OSError, UnicodeDecodeError):
            root = None
        if root is not None:
            for uniqueid in root.findall(".//uniqueid"):
                if uniqueid.attrib.get("type") == "youtube":
                    value = (uniqueid.text or "").strip()
                    if value:
                        return value

    stem = group.stem.strip()
    if "youtube.com/" in stem or "youtu.be/" in stem or "/shorts/" in stem:
        fallback_id = str(extract_video_id(stem)).strip()
        if fallback_id and fallback_id != "unknown-video":
            return fallback_id
    if _YOUTUBE_ID_RE.fullmatch(stem):
        return stem
    return None


def scan_directory(directory: Path) -> list[StemGroup]:
    """Scan a directory into artifact stem groups."""
    groups: dict[str, list[Path]] = {}
    for candidate in sorted(directory.iterdir()):
        if not candidate.is_file():
            continue
        stem = _strip_known_suffix(candidate.name)
        if not stem:
            continue
        groups.setdefault(stem, []).append(candidate)

    scanned: list[StemGroup] = []
    for stem, files in sorted(groups.items()):
        actual_files = collect_artifacts_for_stem(directory, stem)
        if not actual_files:
            actual_files = sorted(files)
        group = StemGroup(
            directory=directory,
            stem=stem,
            files=actual_files,
            video_id=None,
            total_size=sum(path.stat().st_size for path in actual_files if path.exists()),
        )
        group.video_id = extract_video_id_from_stem_group(group)
        metadata_candidates = _metadata_candidates(group)
        if metadata_candidates:
            metadata, video_url = metadata_candidates[0]
            group.canonical_metadata = metadata
            group.canonical_video_url = video_url
        scanned.append(group)
    return scanned


def find_duplicate_sets(groups_a: list[StemGroup], groups_b: list[StemGroup]) -> list[DedupeSet]:
    """Find duplicate sets across two directories only."""
    duplicates: list[DedupeSet] = []

    matched_a: set[int] = set()
    matched_b: set[int] = set()

    by_id_a: dict[str, list[int]] = {}
    by_id_b: dict[str, list[int]] = {}
    for index, group in enumerate(groups_a):
        if group.video_id:
            by_id_a.setdefault(group.video_id, []).append(index)
    for index, group in enumerate(groups_b):
        if group.video_id:
            by_id_b.setdefault(group.video_id, []).append(index)

    for video_id in sorted(set(by_id_a) & set(by_id_b)):
        left_indexes = by_id_a[video_id]
        right_indexes = by_id_b[video_id]
        matched_a.update(left_indexes)
        matched_b.update(right_indexes)
        duplicates.append(
            DedupeSet(
                match_key=video_id,
                match_method="video_id",
                groups=[groups_a[i] for i in left_indexes] + [groups_b[i] for i in right_indexes],
            )
        )

    by_name_a: dict[str, list[int]] = {}
    by_name_b: dict[str, list[int]] = {}
    for index, group in enumerate(groups_a):
        if index in matched_a or group.video_id:
            continue
        normalized = _normalize_fallback_stem(group.stem)
        if normalized:
            by_name_a.setdefault(normalized, []).append(index)
    for index, group in enumerate(groups_b):
        if index in matched_b or group.video_id:
            continue
        normalized = _normalize_fallback_stem(group.stem)
        if normalized:
            by_name_b.setdefault(normalized, []).append(index)

    for fallback_name in sorted(set(by_name_a) & set(by_name_b)):
        left_indexes = by_name_a[fallback_name]
        right_indexes = by_name_b[fallback_name]
        duplicates.append(
            DedupeSet(
                match_key=fallback_name,
                match_method="filename",
                groups=[groups_a[i] for i in left_indexes] + [groups_b[i] for i in right_indexes],
            )
        )

    return duplicates


def select_winner(groups: list[StemGroup], preferred_directory: Path) -> StemGroup:
    """Pick the best group by size and preferred directory tie-break."""
    return max(
        groups,
        key=lambda group: (
            group.total_size,
            1 if group.directory.resolve() == preferred_directory.resolve() else 0,
        ),
    )


def _suffix_fragment(path: Path, stem: str) -> str:
    return path.name[len(stem) :]


def _is_sidecar(path: Path) -> bool:
    return path.suffix.lower() not in _MEDIA_EXTENSIONS


def merge_missing_sidecars(winner: StemGroup, loser: StemGroup, *, dry_run: bool) -> list[Path]:
    """Copy loser sidecars that do not already exist for the winner stem."""
    copied: list[Path] = []
    existing = {path.name for path in winner.files}

    for path in sorted(loser.files):
        if not _is_sidecar(path):
            continue
        target = winner.directory / f"{winner.stem}{_suffix_fragment(path, loser.stem)}"
        if target.name in existing or target.exists():
            continue
        copied.append(target)
        existing.add(target.name)
        if not dry_run:
            shutil.copy2(path, target)
            winner.files.append(target)

    return copied


def _canonical_rename_conflicts(winner: StemGroup, canonical_stem: str) -> bool:
    if canonical_stem == winner.stem:
        return False

    for artifact in winner.files:
        target = winner.directory / f"{canonical_stem}{_suffix_fragment(artifact, winner.stem)}"
        if target.exists():
            return True
    return False


def rename_winner_canonical(winner: StemGroup, config: Any, *, dry_run: bool) -> str | None:
    """Rename winner artifacts to the canonical stem when metadata is available."""
    metadata = winner.canonical_metadata
    if not metadata:
        return None

    canonical_stem = build_output_filename(config, metadata, winner.canonical_video_url)
    if not canonical_stem:
        return None
    winner.canonical_stem = canonical_stem

    if canonical_stem == winner.stem:
        return canonical_stem
    if _canonical_rename_conflicts(winner, canonical_stem):
        return None
    if dry_run:
        return canonical_stem

    result = rename_stem_artifacts(winner.directory, winner.stem, canonical_stem)
    if result.status != "renamed":
        return None

    winner.stem = canonical_stem
    winner.files = collect_artifacts_for_stem(winner.directory, canonical_stem)
    winner.total_size = sum(path.stat().st_size for path in winner.files if path.exists())
    return canonical_stem


def _trash_target_path(trash_dir: Path, path: Path) -> Path:
    target = trash_dir / path.name
    if not target.exists():
        return target

    counter = 1
    while True:
        candidate = trash_dir / f"{path.name}.dedupe-{counter}"
        if not candidate.exists():
            return candidate
        counter += 1


def dispose_loser(
    loser: StemGroup,
    *,
    trash_dir: Path | None,
    delete: bool,
    dry_run: bool,
) -> None:
    """Dispose of loser artifacts by moving them to trash or deleting them."""
    if dry_run:
        return
    if trash_dir is not None:
        trash_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(loser.files):
            if not path.exists():
                continue
            shutil.move(str(path), str(_trash_target_path(trash_dir, path)))
        return
    if delete:
        for path in sorted(loser.files):
            if path.exists():
                path.unlink()


def run_dedupe(
    dir_a: Path,
    dir_b: Path,
    *,
    trash_dir: Path | None,
    delete: bool,
    dry_run: bool,
    verbose: bool,
    config: Any,
) -> dict[str, Any]:
    """Run cross-directory dedupe and return a summary."""
    groups_a = scan_directory(dir_a)
    groups_b = scan_directory(dir_b)
    duplicate_sets = find_duplicate_sets(groups_a, groups_b)

    summary: dict[str, Any] = {
        "duplicate_sets": len(duplicate_sets),
        "losers_disposed": 0,
        "sidecars_copied": 0,
        "winners_renamed": 0,
        "rename_blocked_sets": 0,
        "details": [],
    }

    preferred_directory = dir_b.resolve()
    for duplicate_set in duplicate_sets:
        winner = select_winner(duplicate_set.groups, preferred_directory)
        losers = [
            group
            for group in duplicate_set.groups
            if group is not winner
        ]
        set_detail = {
            "match_key": duplicate_set.match_key,
            "match_method": duplicate_set.match_method,
            "winner": str(winner.directory / winner.stem),
            "losers": [str(group.directory / group.stem) for group in losers],
            "copied": [],
            "renamed_to": None,
            "rename_blocked": False,
        }

        for loser in losers:
            copied = merge_missing_sidecars(winner, loser, dry_run=dry_run)
            set_detail["copied"].extend(str(path) for path in copied)
            summary["sidecars_copied"] += len(copied)

        original_stem = winner.stem
        renamed_to = rename_winner_canonical(winner, config, dry_run=dry_run)
        if renamed_to and renamed_to != original_stem:
            if dry_run:
                set_detail["renamed_to"] = str(winner.directory / renamed_to)
                summary["winners_renamed"] += 1
            elif winner.stem == renamed_to:
                set_detail["renamed_to"] = str(winner.directory / renamed_to)
                summary["winners_renamed"] += 1
        elif winner.canonical_stem and winner.canonical_stem != original_stem:
            set_detail["rename_blocked"] = True
            summary["rename_blocked_sets"] += 1

        if not set_detail["rename_blocked"]:
            for loser in losers:
                dispose_loser(loser, trash_dir=trash_dir, delete=delete, dry_run=dry_run)
                summary["losers_disposed"] += 1

        if verbose or dry_run:
            summary["details"].append(set_detail)

    return summary
