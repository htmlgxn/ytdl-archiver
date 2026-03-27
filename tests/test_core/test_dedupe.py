"""Tests for archive dedupe workflow."""

from __future__ import annotations

import json
from pathlib import Path

from ytdl_archiver.core.dedupe import (
    find_duplicate_sets,
    run_dedupe,
    scan_directory,
)


def _write_bytes(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _write_info_json(path: Path, *, video_id: str, title: str = "Video", uploader: str = "Channel") -> None:
    path.write_text(
        json.dumps(
            {
                "id": video_id,
                "title": title,
                "uploader": uploader,
                "upload_date": "20250131",
                "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
            }
        ),
        encoding="utf-8",
    )


def _write_metadata_json(
    path: Path,
    *,
    video_id: str,
    title: str = "Video",
    uploader: str = "Channel",
) -> None:
    path.write_text(
        json.dumps(
            {
                "video_url": f"https://www.youtube.com/watch?v={video_id}",
                "metadata": {
                    "id": video_id,
                    "title": title,
                    "uploader": uploader,
                    "upload_date": "20250131",
                },
            }
        ),
        encoding="utf-8",
    )


class TestDedupe:
    def test_find_duplicate_sets_groups_n_way_video_id_matches(self, temp_dir: Path):
        dir_a = temp_dir / "a"
        dir_b = temp_dir / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        _write_bytes(dir_a / "legacy-one.mp4", 10)
        _write_info_json(dir_a / "legacy-one.info.json", video_id="abc123")
        _write_bytes(dir_b / "legacy-two.mp4", 8)
        _write_metadata_json(dir_b / "legacy-two.metadata.json", video_id="abc123")
        _write_bytes(dir_b / "legacy-three.mp4", 6)
        _write_info_json(dir_b / "legacy-three.info.json", video_id="abc123")

        duplicate_sets = find_duplicate_sets(scan_directory(dir_a), scan_directory(dir_b))

        assert len(duplicate_sets) == 1
        duplicate_set = duplicate_sets[0]
        assert duplicate_set.match_method == "video_id"
        assert duplicate_set.match_key == "abc123"
        assert sorted(group.stem for group in duplicate_set.groups) == [
            "legacy-one",
            "legacy-three",
            "legacy-two",
        ]

    def test_run_dedupe_copies_sidecars_renames_winner_and_trashes_losers(
        self, config, temp_dir: Path
    ):
        dir_a = temp_dir / "left"
        dir_b = temp_dir / "right"
        trash_dir = temp_dir / "trash"
        dir_a.mkdir()
        dir_b.mkdir()
        config._config["filename"]["tokens"] = ["title", "channel"]

        _write_bytes(dir_a / "legacy-low.mp4", 4)
        _write_info_json(dir_a / "legacy-low.info.json", video_id="abc123")
        (dir_a / "legacy-low.en.srt").write_text("subtitle", encoding="utf-8")

        _write_bytes(dir_b / "legacy-high.mp4", 12)
        _write_metadata_json(
            dir_b / "legacy-high.metadata.json",
            video_id="abc123",
            title="Canonical Video",
            uploader="Archive Channel",
        )

        summary = run_dedupe(
            dir_a,
            dir_b,
            trash_dir=trash_dir,
            delete=False,
            dry_run=False,
            verbose=True,
            config=config,
        )

        canonical_stem = "canonical-video_archive-channel"
        assert summary["duplicate_sets"] == 1
        assert summary["sidecars_copied"] == 2
        assert summary["winners_renamed"] == 1
        assert summary["losers_disposed"] == 1
        assert (dir_b / f"{canonical_stem}.mp4").exists()
        assert (dir_b / f"{canonical_stem}.metadata.json").exists()
        assert (dir_b / f"{canonical_stem}.info.json").exists()
        assert (dir_b / f"{canonical_stem}.en.srt").exists()
        assert not (dir_a / "legacy-low.mp4").exists()
        assert (trash_dir / "legacy-low.mp4").exists()

    def test_run_dedupe_preserves_loser_when_canonical_rename_conflicts(
        self, config, temp_dir: Path
    ):
        dir_a = temp_dir / "left"
        dir_b = temp_dir / "right"
        dir_a.mkdir()
        dir_b.mkdir()
        config._config["filename"]["tokens"] = ["title", "channel"]

        _write_bytes(dir_a / "legacy-low.mp4", 4)
        _write_info_json(dir_a / "legacy-low.info.json", video_id="abc123")

        _write_bytes(dir_b / "legacy-high.mp4", 12)
        _write_metadata_json(
            dir_b / "legacy-high.metadata.json",
            video_id="abc123",
            title="Canonical Video",
            uploader="Archive Channel",
        )
        _write_bytes(dir_b / "canonical-video_archive-channel.mp4", 1)

        summary = run_dedupe(
            dir_a,
            dir_b,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=True,
            config=config,
        )

        assert summary["rename_blocked_sets"] == 1
        assert summary["losers_disposed"] == 0
        assert (dir_a / "legacy-low.mp4").exists()
        assert (dir_b / "legacy-high.mp4").exists()

    def test_run_dedupe_uses_filename_fallback_when_sidecars_are_missing(
        self, config, temp_dir: Path
    ):
        dir_a = temp_dir / "left"
        dir_b = temp_dir / "right"
        dir_a.mkdir()
        dir_b.mkdir()

        _write_bytes(dir_a / "2025-01-31_Same Title_Channel.mp4", 3)
        _write_bytes(dir_b / "same-title-channel.mp4", 8)

        summary = run_dedupe(
            dir_a,
            dir_b,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=False,
            config=config,
        )

        assert summary["duplicate_sets"] == 1
        assert summary["losers_disposed"] == 1
        assert not (dir_a / "2025-01-31_Same Title_Channel.mp4").exists()
        assert (dir_b / "same-title-channel.mp4").exists()

    def test_run_dedupe_renames_trash_collision_targets(self, config, temp_dir: Path):
        dir_a = temp_dir / "left"
        dir_b = temp_dir / "right"
        trash_dir = temp_dir / "trash"
        dir_a.mkdir()
        dir_b.mkdir()
        trash_dir.mkdir()
        (trash_dir / "legacy-low.mp4").write_bytes(b"old")

        _write_bytes(dir_a / "legacy-low.mp4", 4)
        _write_info_json(dir_a / "legacy-low.info.json", video_id="abc123")
        _write_bytes(dir_b / "legacy-high.mp4", 12)
        _write_info_json(dir_b / "legacy-high.info.json", video_id="abc123")

        run_dedupe(
            dir_a,
            dir_b,
            trash_dir=trash_dir,
            delete=False,
            dry_run=False,
            verbose=False,
            config=config,
        )

        assert (trash_dir / "legacy-low.mp4").exists()
        assert (trash_dir / "legacy-low.mp4.dedupe-1").exists()
