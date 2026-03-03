"""Artifact stem utilities for post-download/backfill reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass
class StemRenameResult:
    """Result information for stem rename operations."""

    status: str
    source_stem: str
    target_stem: str
    renamed_count: int = 0
    conflict_path: Path | None = None


def stem_looks_like_fallback(stem: str) -> bool:
    """Return True when a filename stem matches fallback naming pattern."""
    lowered = stem.strip().lower()
    return lowered.startswith("video-") and lowered.endswith("_unknown-channel")


def _belongs_to_stem(path: Path, stem: str) -> bool:
    return path.name == stem or path.name.startswith(f"{stem}.")


def collect_artifacts_for_stem(directory: Path, stem: str) -> list[Path]:
    """Collect file artifacts in a directory belonging to a given stem."""
    if not stem:
        return []

    artifacts: list[Path] = []
    for candidate in sorted(directory.glob(f"{stem}*")):
        if not candidate.is_file():
            continue
        if _belongs_to_stem(candidate, stem):
            artifacts.append(candidate)
    return artifacts


def rename_stem_artifacts(
    directory: Path, source_stem: str, target_stem: str
) -> StemRenameResult:
    """Rename all stem-associated files within a directory.

    Uses a two-phase temp rename to avoid partial collisions.
    """
    source = source_stem.strip()
    target = target_stem.strip()
    if not source or not target:
        return StemRenameResult("invalid", source, target, 0)
    if source == target:
        return StemRenameResult("noop", source, target, 0)

    artifacts = collect_artifacts_for_stem(directory, source)
    if not artifacts:
        return StemRenameResult("noop", source, target, 0)

    targets: list[Path] = []
    for artifact in artifacts:
        suffix_part = artifact.name[len(source) :]
        target_path = directory / f"{target}{suffix_part}"
        if target_path.exists():
            return StemRenameResult(
                "conflict",
                source,
                target,
                0,
                conflict_path=target_path,
            )
        targets.append(target_path)

    temp_paths: list[Path] = []
    renamed_temp = 0
    try:
        for artifact in artifacts:
            temp_path = directory / f".__rename_tmp_{uuid4().hex}{artifact.suffix}"
            artifact.rename(temp_path)
            temp_paths.append(temp_path)
            renamed_temp += 1

        renamed_final = 0
        for temp_path, target_path in zip(temp_paths, targets, strict=True):
            temp_path.rename(target_path)
            renamed_final += 1

        return StemRenameResult("renamed", source, target, renamed_final)
    except OSError:
        # Best-effort rollback of temporary files to original paths.
        rollback_pairs = zip(temp_paths, artifacts, strict=False)
        for temp_path, original_path in rollback_pairs:
            if temp_path.exists() and not original_path.exists():
                try:
                    temp_path.rename(original_path)
                except OSError:
                    pass
        return StemRenameResult("failed", source, target, renamed_temp)
