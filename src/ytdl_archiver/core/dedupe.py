"""Directional dedupe and archive import helpers."""

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

    root: Path
    directory: Path
    relative_parent: Path
    stem: str
    files: list[Path]
    video_id: str | None
    total_size: int
    canonical_metadata: dict[str, Any] | None = None
    canonical_video_url: str = ""
    canonical_stem: str | None = None


def _strip_known_suffix(name: str) -> str | None:
    lower_name = name.lower()
    if lower_name in {"tvshow.nfo", ".archive.txt"} or name.startswith("."):
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
    return data if isinstance(data, dict) else None


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
            url = str(
                metadata_data.get("video_url") or metadata_data.get("webpage_url") or ""
            )
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


def scan_directory(root: Path) -> list[StemGroup]:
    """Recursively scan a tree into stem groups."""
    groups: dict[tuple[Path, str], list[Path]] = {}
    root = root.resolve()

    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file():
            continue
        stem = _strip_known_suffix(candidate.name)
        if not stem:
            continue
        relative_parent = candidate.parent.relative_to(root)
        groups.setdefault((relative_parent, stem), []).append(candidate)

    scanned: list[StemGroup] = []
    for (relative_parent, stem), files in sorted(groups.items(), key=lambda item: (str(item[0][0]), item[0][1])):
        directory = root / relative_parent
        actual_files = collect_artifacts_for_stem(directory, stem)
        if not actual_files:
            actual_files = sorted(files)
        group = StemGroup(
            root=root,
            directory=directory,
            relative_parent=relative_parent,
            stem=stem,
            files=actual_files,
            video_id=None,
            total_size=sum(path.stat().st_size for path in actual_files if path.exists()),
        )
        group.video_id = extract_video_id_from_stem_group(group)
        candidates = _metadata_candidates(group)
        if candidates:
            metadata, video_url = candidates[0]
            group.canonical_metadata = metadata
            group.canonical_video_url = video_url
        scanned.append(group)
    return scanned


def _match_key(group: StemGroup) -> tuple[str, str]:
    if group.video_id:
        return ("video_id", group.video_id)
    return ("filename", _normalize_fallback_stem(group.stem))


def _bucket_groups(groups: list[StemGroup]) -> dict[tuple[str, str], list[StemGroup]]:
    buckets: dict[tuple[str, str], list[StemGroup]] = {}
    for group in groups:
        key = _match_key(group)
        if not key[1]:
            continue
        buckets.setdefault(key, []).append(group)
    return buckets


def _group_sort_key(group: StemGroup) -> tuple[int, int, str, str]:
    return (
        -group.total_size,
        len(group.relative_parent.parts),
        str(group.relative_parent),
        group.stem,
    )


def select_archive_destination(groups: list[StemGroup]) -> StemGroup:
    """Choose the archive location to keep inside the archive tree."""
    return sorted(groups, key=_group_sort_key)[0]


def select_best_source(groups: list[StemGroup]) -> StemGroup:
    """Choose the strongest source group deterministically."""
    return sorted(groups, key=_group_sort_key)[0]


def _suffix_fragment(path: Path, stem: str) -> str:
    return path.name[len(stem) :]


def _is_sidecar(path: Path) -> bool:
    return path.suffix.lower() not in _MEDIA_EXTENSIONS


def _refresh_group_files(group: StemGroup) -> None:
    group.files = collect_artifacts_for_stem(group.directory, group.stem)
    group.total_size = sum(path.stat().st_size for path in group.files if path.exists())


def merge_missing_sidecars(target: StemGroup, donor: StemGroup, *, dry_run: bool) -> list[Path]:
    """Copy donor sidecars that are absent from the target stem."""
    copied: list[Path] = []
    existing = {path.name for path in target.files}
    for path in sorted(donor.files):
        if not _is_sidecar(path):
            continue
        target_path = target.directory / f"{target.stem}{_suffix_fragment(path, donor.stem)}"
        if target_path.name in existing or target_path.exists():
            continue
        copied.append(target_path)
        existing.add(target_path.name)
        if not dry_run:
            target.directory.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target_path)
    if copied and not dry_run:
        _refresh_group_files(target)
    return copied


def _canonical_rename_conflicts(group: StemGroup, canonical_stem: str) -> bool:
    if canonical_stem == group.stem:
        return False
    for artifact in group.files:
        target = group.directory / f"{canonical_stem}{_suffix_fragment(artifact, group.stem)}"
        if target.exists():
            return True
    return False


def rename_group_canonical(group: StemGroup, config: Any, *, dry_run: bool) -> str | None:
    """Rename a materialized archive group to the canonical stem when possible."""
    metadata = group.canonical_metadata
    if not metadata:
        return None

    canonical_stem = build_output_filename(config, metadata, group.canonical_video_url)
    if not canonical_stem:
        return None
    group.canonical_stem = canonical_stem
    if canonical_stem == group.stem:
        return canonical_stem
    if _canonical_rename_conflicts(group, canonical_stem):
        return None
    if dry_run:
        return canonical_stem

    result = rename_stem_artifacts(group.directory, group.stem, canonical_stem)
    if result.status != "renamed":
        return None
    group.stem = canonical_stem
    _refresh_group_files(group)
    return canonical_stem


def _ensure_available_stem(directory: Path, preferred_stem: str) -> str:
    if not collect_artifacts_for_stem(directory, preferred_stem):
        return preferred_stem
    counter = 1
    while True:
        candidate = f"{preferred_stem}__dedupe_{counter}"
        if not collect_artifacts_for_stem(directory, candidate):
            return candidate
        counter += 1


def _trash_target_path(
    trash_dir: Path,
    *,
    origin: str,
    relative_parent: Path,
    file_name: str,
) -> Path:
    base_dir = trash_dir / origin / relative_parent
    target = base_dir / file_name
    if not target.exists():
        return target
    counter = 1
    while True:
        candidate = base_dir / f"{file_name}.dedupe-{counter}"
        if not candidate.exists():
            return candidate
        counter += 1


def dispose_group(
    group: StemGroup,
    *,
    trash_dir: Path | None,
    delete: bool,
    dry_run: bool,
    origin: str,
) -> None:
    """Dispose of a group after it has been consolidated."""
    if dry_run:
        return
    if trash_dir is not None:
        for path in sorted(group.files):
            if not path.exists():
                continue
            target = _trash_target_path(
                trash_dir,
                origin=origin,
                relative_parent=group.relative_parent,
                file_name=path.name,
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
        return
    if delete:
        for path in sorted(group.files):
            if path.exists():
                path.unlink()


def _build_group_from_paths(
    *,
    root: Path,
    directory: Path,
    relative_parent: Path,
    stem: str,
    files: list[Path],
    template: StemGroup,
) -> StemGroup:
    group = StemGroup(
        root=root,
        directory=directory,
        relative_parent=relative_parent,
        stem=stem,
        files=sorted(files),
        video_id=template.video_id,
        total_size=sum(path.stat().st_size for path in files if path.exists()),
        canonical_metadata=template.canonical_metadata,
        canonical_video_url=template.canonical_video_url,
    )
    return group


def materialize_source_group(
    source: StemGroup,
    *,
    archive_root: Path,
    target_parent: Path,
    target_stem: str,
    dry_run: bool,
) -> StemGroup:
    """Move a source group into the archive tree under the requested stem."""
    target_directory = archive_root / target_parent
    target_files = [
        target_directory / f"{target_stem}{_suffix_fragment(path, source.stem)}"
        for path in sorted(source.files)
    ]
    if not dry_run:
        target_directory.mkdir(parents=True, exist_ok=True)
        for path, target in zip(sorted(source.files), target_files, strict=True):
            if target.exists():
                raise RuntimeError(f"Archive target already exists: {target}")
            shutil.move(str(path), str(target))
    return _build_group_from_paths(
        root=archive_root,
        directory=target_directory,
        relative_parent=target_parent,
        stem=target_stem,
        files=target_files,
        template=source,
    )


def _replace_archive_group(
    source: StemGroup,
    destination: StemGroup,
    *,
    archive_root: Path,
    dry_run: bool,
) -> tuple[StemGroup, StemGroup | None]:
    temp_archived: StemGroup | None = None

    if dry_run:
        final_group = _build_group_from_paths(
            root=archive_root,
            directory=destination.directory,
            relative_parent=destination.relative_parent,
            stem=destination.stem,
            files=[
                destination.directory / f"{destination.stem}{_suffix_fragment(path, source.stem)}"
                for path in sorted(source.files)
            ],
            template=source,
        )
        temp_archived = _build_group_from_paths(
            root=archive_root,
            directory=destination.directory,
            relative_parent=destination.relative_parent,
            stem=destination.stem,
            files=list(destination.files),
            template=destination,
        )
        return final_group, temp_archived

    temp_stem = _ensure_available_stem(destination.directory, f"{destination.stem}__archived")
    rename_result = rename_stem_artifacts(destination.directory, destination.stem, temp_stem)
    if rename_result.status not in {"renamed", "noop"}:
        raise RuntimeError(
            f"Could not stage existing archive artifacts for replacement: {destination.directory / destination.stem}"
        )

    temp_archived = StemGroup(
        root=archive_root,
        directory=destination.directory,
        relative_parent=destination.relative_parent,
        stem=temp_stem,
        files=collect_artifacts_for_stem(destination.directory, temp_stem),
        video_id=destination.video_id,
        total_size=0,
        canonical_metadata=destination.canonical_metadata,
        canonical_video_url=destination.canonical_video_url,
    )
    temp_archived.total_size = sum(
        path.stat().st_size for path in temp_archived.files if path.exists()
    )

    final_group = materialize_source_group(
        source,
        archive_root=archive_root,
        target_parent=destination.relative_parent,
        target_stem=destination.stem,
        dry_run=False,
    )
    return final_group, temp_archived


def run_dedupe(
    source_dir: Path,
    archive_dir: Path,
    *,
    trash_dir: Path | None,
    delete: bool,
    dry_run: bool,
    verbose: bool,
    config: Any,
) -> dict[str, Any]:
    """Merge source artifacts into the archive tree."""
    source_groups = scan_directory(source_dir)
    archive_groups = scan_directory(archive_dir)
    source_buckets = _bucket_groups(source_groups)
    archive_buckets = _bucket_groups(archive_groups)

    summary: dict[str, Any] = {
        "processed_sets": 0,
        "imported_sets": 0,
        "replaced_sets": 0,
        "merged_sets": 0,
        "skipped_sets": 0,
        "source_groups_disposed": 0,
        "archive_groups_disposed": 0,
        "sidecars_copied": 0,
        "archive_winners_renamed": 0,
        "rename_blocked_sets": 0,
        "details": [],
    }

    for match_key in sorted(source_buckets):
        sources = source_buckets[match_key]
        archives = archive_buckets.get(match_key, [])
        best_source = select_best_source(sources)
        other_sources = [group for group in sources if group is not best_source]

        detail = {
            "match_method": match_key[0],
            "match_key": match_key[1],
            "action": "skip",
            "archive_destination": None,
            "source_origin": str(best_source.directory / best_source.stem),
            "archive_replaced": False,
            "copied": [],
            "renamed_to": None,
            "rename_blocked": False,
        }

        if archives:
            destination = select_archive_destination(archives)
            extra_archives = [group for group in archives if group is not destination]
            detail["archive_destination"] = str(destination.directory / destination.stem)
            final_group = destination
            staged_archive: StemGroup | None = None

            if best_source.total_size > destination.total_size:
                detail["action"] = "replace_archive"
                detail["archive_replaced"] = True
                final_group, staged_archive = _replace_archive_group(
                    best_source,
                    destination,
                    archive_root=archive_dir,
                    dry_run=dry_run,
                )
                summary["replaced_sets"] += 1
            else:
                detail["action"] = "merge_sidecars"
                summary["merged_sets"] += 1

            donors: list[tuple[str, StemGroup]] = []
            if staged_archive is not None:
                donors.append(("archive", staged_archive))
            donors.extend(("archive", group) for group in extra_archives)
            donors.extend(
                ("source", group)
                for group in sources
                if group is not best_source or not detail["archive_replaced"]
            )

            for origin, donor in donors:
                copied = merge_missing_sidecars(final_group, donor, dry_run=dry_run)
                detail["copied"].extend(str(path) for path in copied)
                summary["sidecars_copied"] += len(copied)

            original_stem = final_group.stem
            renamed_to = rename_group_canonical(final_group, config, dry_run=dry_run)
            if renamed_to and renamed_to != original_stem:
                detail["renamed_to"] = str(final_group.directory / renamed_to)
                summary["archive_winners_renamed"] += 1
            elif final_group.canonical_stem and final_group.canonical_stem != original_stem:
                detail["rename_blocked"] = True
                summary["rename_blocked_sets"] += 1

            for group in extra_archives:
                dispose_group(
                    group,
                    trash_dir=trash_dir,
                    delete=delete,
                    dry_run=dry_run,
                    origin="archive",
                )
                summary["archive_groups_disposed"] += 1
            if staged_archive is not None:
                dispose_group(
                    staged_archive,
                    trash_dir=trash_dir,
                    delete=delete,
                    dry_run=dry_run,
                    origin="archive",
                )
                summary["archive_groups_disposed"] += 1

            for group in sources:
                if detail["archive_replaced"] and group is best_source and not dry_run:
                    continue
                dispose_group(
                    group,
                    trash_dir=trash_dir,
                    delete=delete,
                    dry_run=dry_run,
                    origin="source",
                )
                summary["source_groups_disposed"] += 1
        else:
            detail["action"] = "import"
            target_parent = best_source.relative_parent
            target_directory = archive_dir / target_parent
            target_stem = _ensure_available_stem(target_directory, best_source.stem)
            final_group = materialize_source_group(
                best_source,
                archive_root=archive_dir,
                target_parent=target_parent,
                target_stem=target_stem,
                dry_run=dry_run,
            )
            detail["archive_destination"] = str(final_group.directory / final_group.stem)
            summary["imported_sets"] += 1

            for group in other_sources:
                copied = merge_missing_sidecars(final_group, group, dry_run=dry_run)
                detail["copied"].extend(str(path) for path in copied)
                summary["sidecars_copied"] += len(copied)

            original_stem = final_group.stem
            renamed_to = rename_group_canonical(final_group, config, dry_run=dry_run)
            if renamed_to and renamed_to != original_stem:
                detail["renamed_to"] = str(final_group.directory / renamed_to)
                summary["archive_winners_renamed"] += 1
            elif final_group.canonical_stem and final_group.canonical_stem != original_stem:
                detail["rename_blocked"] = True
                summary["rename_blocked_sets"] += 1

            for group in other_sources:
                dispose_group(
                    group,
                    trash_dir=trash_dir,
                    delete=delete,
                    dry_run=dry_run,
                    origin="source",
                )
                summary["source_groups_disposed"] += 1

        summary["processed_sets"] += 1
        if verbose or dry_run:
            summary["details"].append(detail)

    return summary
