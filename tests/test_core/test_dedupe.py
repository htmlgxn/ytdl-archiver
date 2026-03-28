"""Tests for directional archive dedupe workflow."""

from __future__ import annotations

import json
from pathlib import Path

from ytdl_archiver.core.dedupe import run_dedupe, scan_directory


def _write_bytes(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _write_info_json(
    path: Path,
    *,
    video_id: str,
    title: str = "Video",
    uploader: str = "Channel",
) -> None:
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


def _write_nfo(
    path: Path,
    *,
    video_id: str,
    title: str = "Video",
    showtitle: str = "",
    studio: str = "",
    releasedate: str = "",
    aired: str = "",
) -> None:
    channel_bits = ""
    if showtitle:
        channel_bits += f"<showtitle>{showtitle}</showtitle>"
    if studio:
        channel_bits += f"<studio>{studio}</studio>"
    date_bits = ""
    if releasedate:
        date_bits += f"<releasedate>{releasedate}</releasedate>"
    if aired:
        date_bits += f"<aired>{aired}</aired>"

    path.write_text(
        (
            "<?xml version=\"1.0\" encoding=\"utf-8\" standalone=\"yes\"?>"
            "<episodedetails>"
            f"<title>{title}</title>"
            f"{channel_bits}"
            f"{date_bits}"
            f"<uniqueid type=\"youtube\" default=\"true\">{video_id}</uniqueid>"
            "</episodedetails>"
        ),
        encoding="utf-8",
    )


class TestDedupe:
    def test_scan_directory_recurses_into_nested_playlist_folders(self, temp_dir: Path):
        root = temp_dir / "source"
        nested = root / "Channel Name" / "Uploads"
        nested.mkdir(parents=True)
        _write_bytes(nested / "video.mp4", 4)
        _write_info_json(nested / "video.info.json", video_id="abc123")

        groups = scan_directory(root)

        assert len(groups) == 1
        assert groups[0].relative_parent == Path("Channel Name") / "Uploads"
        assert groups[0].video_id == "abc123"

    def test_run_dedupe_imports_source_only_video_into_archive_relative_parent(
        self, config, temp_dir: Path
    ):
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Channel A"
        archive_dir.mkdir()
        config._config["filename"]["tokens"] = ["title", "channel"]

        _write_bytes(source_leaf / "legacy.mp4", 8)
        _write_info_json(
            source_leaf / "legacy.info.json",
            video_id="abc123",
            title="Imported Video",
            uploader="Source Channel",
        )
        (source_leaf / "legacy.en.srt").write_text("subtitle", encoding="utf-8")

        summary = run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=True,
            config=config,
        )

        final_stem = "imported-video_source-channel"
        assert summary["processed_sets"] == 1
        assert summary["imported_sets"] == 1
        assert (archive_dir / "Imports" / "Channel A" / f"{final_stem}.mp4").exists()
        assert (archive_dir / "Imports" / "Channel A" / f"{final_stem}.en.srt").exists()
        assert (archive_dir / "Imports" / "Channel A" / f"{final_stem}.info.json").exists()
        assert not (source_leaf / "legacy.mp4").exists()

    def test_run_dedupe_renames_nfo_only_import_using_config_rules(
        self, config, temp_dir: Path
    ):
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Channel A"
        archive_leaf = archive_dir / "Imports" / "Channel A"
        archive_dir.mkdir()
        config._config["filename"]["tokens"] = ["upload_date", "title", "channel"]
        config._config["filename"]["date_format"] = "yyyymmdd"

        _write_bytes(source_leaf / "legacy.mp4", 8)
        _write_nfo(
            source_leaf / "legacy.nfo",
            video_id="abc123",
            title="Imported Video",
            showtitle="Source Channel",
            releasedate="2025-01-31",
        )

        summary = run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=True,
            config=config,
        )

        final_stem = "20250131_imported-video_source-channel"
        assert summary["archive_winners_renamed"] == 1
        assert (archive_dir / "Imports" / "Channel A" / f"{final_stem}.mp4").exists()
        assert (archive_dir / "Imports" / "Channel A" / f"{final_stem}.nfo").exists()

    def test_run_dedupe_nfo_prefers_showtitle_and_releasedate_over_fallbacks(
        self, config, temp_dir: Path
    ):
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Channel A"
        archive_dir.mkdir()
        config._config["filename"]["tokens"] = ["upload_date", "title", "channel"]
        config._config["filename"]["date_format"] = "yyyymmdd"

        _write_bytes(source_leaf / "legacy.mp4", 8)
        _write_nfo(
            source_leaf / "legacy.nfo",
            video_id="abc123",
            title="Imported Video",
            showtitle="Primary Channel",
            studio="Fallback Studio",
            releasedate="2025-01-31",
            aired="2020-02-03",
        )

        run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=False,
            config=config,
        )

        assert (
            archive_dir / "Imports" / "Channel A" / "20250131_imported-video_primary-channel.mp4"
        ).exists()

    def test_run_dedupe_nfo_falls_back_to_studio_and_aired(self, config, temp_dir: Path):
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Channel A"
        archive_dir.mkdir()
        config._config["filename"]["tokens"] = ["upload_date", "title", "channel"]
        config._config["filename"]["date_format"] = "yyyymmdd"

        _write_bytes(source_leaf / "legacy.mp4", 8)
        _write_nfo(
            source_leaf / "legacy.nfo",
            video_id="abc123",
            title="Imported Video",
            studio="Fallback Studio",
            aired="2025-02-01",
        )

        run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=False,
            config=config,
        )

        assert (
            archive_dir / "Imports" / "Channel A" / "20250201_imported-video_fallback-studio.mp4"
        ).exists()

    def test_run_dedupe_json_metadata_outranks_nfo_for_rename(self, config, temp_dir: Path):
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Channel A"
        archive_dir.mkdir()
        config._config["filename"]["tokens"] = ["upload_date", "title", "channel"]
        config._config["filename"]["date_format"] = "yyyymmdd"

        _write_bytes(source_leaf / "legacy.mp4", 8)
        _write_info_json(
            source_leaf / "legacy.info.json",
            video_id="abc123",
            title="Json Video",
            uploader="Json Channel",
        )
        _write_nfo(
            source_leaf / "legacy.nfo",
            video_id="abc123",
            title="Nfo Video",
            showtitle="Nfo Channel",
            releasedate="2020-01-01",
        )

        run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=False,
            config=config,
        )

        assert (
            archive_dir / "Imports" / "Channel A" / "20250131_json-video_json-channel.mp4"
        ).exists()

    def test_run_dedupe_replaces_archive_media_but_keeps_archive_subdirectory(
        self, config, temp_dir: Path
    ):
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Loose" / "Folder"
        archive_leaf = archive_dir / "Playlists" / "Target"
        config._config["filename"]["tokens"] = ["title", "channel"]

        _write_bytes(source_leaf / "source-copy.mp4", 2000)
        _write_info_json(
            source_leaf / "source-copy.info.json",
            video_id="abc123",
            title="Canonical Video",
            uploader="Archive Channel",
        )
        (source_leaf / "source-copy.en.srt").write_text("subtitle", encoding="utf-8")

        _write_bytes(archive_leaf / "old-archive.mp4", 5)
        _write_metadata_json(
            archive_leaf / "old-archive.metadata.json",
            video_id="abc123",
            title="Canonical Video",
            uploader="Archive Channel",
        )
        (archive_leaf / "old-archive.nfo").write_text(
            "<movie><uniqueid type=\"youtube\">abc123</uniqueid></movie>",
            encoding="utf-8",
        )

        summary = run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=True,
            config=config,
        )

        final_stem = "canonical-video_archive-channel"
        assert summary["replaced_sets"] == 1
        assert summary["archive_groups_disposed"] == 1
        assert (archive_leaf / f"{final_stem}.mp4").exists()
        assert (archive_leaf / f"{final_stem}.en.srt").exists()
        assert (archive_leaf / f"{final_stem}.nfo").exists()
        assert (archive_leaf / f"{final_stem}.metadata.json").exists()
        assert (archive_leaf / f"{final_stem}.info.json").exists()
        assert not (source_leaf / "source-copy.mp4").exists()
        assert not (archive_leaf / "old-archive.mp4").exists()

    def test_run_dedupe_keeps_archive_media_when_archive_copy_is_best(
        self, config, temp_dir: Path
    ):
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Incoming" / "Channel"
        archive_leaf = archive_dir / "Playlists" / "Named"
        config._config["filename"]["tokens"] = ["title", "channel"]

        _write_bytes(source_leaf / "source-copy.mp4", 5)
        _write_info_json(
            source_leaf / "source-copy.info.json",
            video_id="abc123",
            title="Canonical Video",
            uploader="Archive Channel",
        )
        (source_leaf / "source-copy.en.srt").write_text("subtitle", encoding="utf-8")

        _write_bytes(archive_leaf / "archived.mp4", 15)
        _write_metadata_json(
            archive_leaf / "archived.metadata.json",
            video_id="abc123",
            title="Canonical Video",
            uploader="Archive Channel",
        )

        summary = run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=False,
            config=config,
        )

        final_stem = "canonical-video_archive-channel"
        assert summary["merged_sets"] == 1
        assert (archive_leaf / f"{final_stem}.mp4").exists()
        assert (archive_leaf / f"{final_stem}.metadata.json").exists()
        assert (archive_leaf / f"{final_stem}.en.srt").exists()
        assert (archive_leaf / f"{final_stem}.info.json").exists()
        assert not (source_leaf / "source-copy.mp4").exists()

    def test_run_dedupe_merges_missing_metadata_sidecars_when_archive_wins(self, config, temp_dir: Path):
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Incoming" / "Channel"
        archive_leaf = archive_dir / "Playlists" / "Named"
        config._config["filename"]["tokens"] = ["title", "channel"]

        _write_bytes(source_leaf / "source-copy.mp4", 5)
        _write_info_json(
            source_leaf / "source-copy.info.json",
            video_id="abc123",
            title="Canonical Video",
            uploader="Archive Channel",
        )
        (source_leaf / "source-copy.nfo").write_text(
            "<movie><uniqueid type=\"youtube\">abc123</uniqueid></movie>",
            encoding="utf-8",
        )

        _write_bytes(archive_leaf / "archived.mp4", 2000)
        _write_metadata_json(
            archive_leaf / "archived.metadata.json",
            video_id="abc123",
            title="Canonical Video",
            uploader="Archive Channel",
        )

        summary = run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=False,
            config=config,
        )

        final_stem = "canonical-video_archive-channel"
        assert summary["merged_sets"] == 1
        assert (archive_leaf / f"{final_stem}.mp4").exists()
        assert (archive_leaf / f"{final_stem}.metadata.json").exists()
        assert (archive_leaf / f"{final_stem}.info.json").exists()
        assert (archive_leaf / f"{final_stem}.nfo").exists()
        assert not (source_leaf / "source-copy.mp4").exists()
        assert not (source_leaf / "source-copy.info.json").exists()
        assert not (source_leaf / "source-copy.nfo").exists()

    def test_run_dedupe_imports_source_only_video_with_metadata_sidecars(self, config, temp_dir: Path):
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Channel A"
        archive_dir.mkdir()
        config._config["filename"]["tokens"] = ["upload_date", "title", "channel"]
        config._config["filename"]["date_format"] = "yyyymmdd"

        _write_bytes(source_leaf / "legacy.webm", 8)
        (source_leaf / "legacy.jpg").write_text("jpg", encoding="utf-8")
        (source_leaf / "legacy.webp").write_text("webp", encoding="utf-8")
        (source_leaf / "legacy.en.srt").write_text("subtitle", encoding="utf-8")
        _write_info_json(
            source_leaf / "legacy.info.json",
            video_id="abc123",
            title="Imported Video",
            uploader="Source Channel",
        )
        _write_metadata_json(
            source_leaf / "legacy.metadata.json",
            video_id="abc123",
            title="Imported Video",
            uploader="Source Channel",
        )
        _write_nfo(
            source_leaf / "legacy.nfo",
            video_id="abc123",
            title="Imported Video",
            showtitle="Source Channel",
            releasedate="2025-01-31",
        )

        run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=False,
            config=config,
        )

        final_base = archive_dir / "Imports" / "Channel A" / "20250131_imported-video_source-channel"
        assert final_base.with_suffix(".webm").exists()
        assert final_base.with_suffix(".jpg").exists()
        assert (archive_dir / "Imports" / "Channel A" / "20250131_imported-video_source-channel.en.srt").exists()
        assert not final_base.with_suffix(".webp").exists()
        assert final_base.with_suffix(".info.json").exists()
        assert final_base.with_suffix(".metadata.json").exists()
        assert final_base.with_suffix(".nfo").exists()

    def test_run_dedupe_treats_mp4_and_webm_as_same_media_slot(self, config, temp_dir: Path):
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Incoming" / "Channel"
        archive_leaf = archive_dir / "Playlists" / "Named"
        config._config["filename"]["tokens"] = ["title", "channel"]

        _write_bytes(source_leaf / "source-copy.mp4", 5)
        _write_info_json(
            source_leaf / "source-copy.info.json",
            video_id="abc123",
            title="Canonical Video",
            uploader="Archive Channel",
        )

        _write_bytes(archive_leaf / "archived.webm", 15)
        _write_metadata_json(
            archive_leaf / "archived.metadata.json",
            video_id="abc123",
            title="Canonical Video",
            uploader="Archive Channel",
        )

        run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=False,
            config=config,
        )

        final_stem = "canonical-video_archive-channel"
        assert (archive_leaf / f"{final_stem}.webm").exists()
        assert not (archive_leaf / f"{final_stem}.mp4").exists()

    def test_run_dedupe_collapses_source_only_duplicates_with_same_canonical_target(
        self, config, temp_dir: Path
    ):
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Channel A"
        archive_dir.mkdir()
        config._config["filename"]["tokens"] = ["upload_date", "title", "channel"]
        config._config["filename"]["date_format"] = "yyyymmdd"

        _write_bytes(source_leaf / "you-re.mp4", 8)
        _write_nfo(
            source_leaf / "you-re.nfo",
            video_id="abc123",
            title="You're Not A Broken Person",
            showtitle="Art Chad",
            releasedate="2022-03-30",
        )

        _write_bytes(source_leaf / "youre.mp4", 4)
        _write_nfo(
            source_leaf / "youre.nfo",
            video_id="def456",
            title="Youre Not A Broken Person",
            showtitle="Art Chad",
            releasedate="2022-03-30",
        )

        summary = run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=True,
            verbose=False,
            config=config,
        )

        assert summary["imported_sets"] == 1
        assert summary["skipped_sets"] == 1
        skip_detail = next(
            detail for detail in summary["details"] if detail["action"] == "skip_duplicate_source"
        )
        assert any(
            operation["reason"] == "lower-priority duplicate for same canonical archive target"
            for operation in skip_detail["operations"]
        )

    def test_run_dedupe_reports_preexisting_rename_conflict_explicitly(
        self, config, temp_dir: Path
    ):
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Channel A"
        archive_leaf = archive_dir / "Imports" / "Channel A"
        archive_dir.mkdir()
        config._config["filename"]["tokens"] = ["upload_date", "title", "channel"]
        config._config["filename"]["date_format"] = "yyyymmdd"

        _write_bytes(source_leaf / "first.mp4", 8)
        _write_nfo(
            source_leaf / "first.nfo",
            video_id="abc123",
            title="Canonical Video",
            showtitle="Art Chad",
            releasedate="2022-03-30",
        )
        _write_bytes(archive_leaf / "20220330_canonical-video_art-chad.mp4", 1)

        summary = run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=True,
            verbose=False,
            config=config,
        )

        detail = next(detail for detail in summary["details"] if detail["action"] == "import")
        blocked = [
            operation
            for operation in detail["operations"]
            if operation["kind"] == "block_file"
        ]
        assert blocked
        assert blocked[0]["reason"] == "blocked_preexisting_target"

    def test_run_dedupe_uses_filename_fallback_recursively(self, config, temp_dir: Path):
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Folder"
        archive_leaf = archive_dir / "Playlists" / "Named"

        _write_bytes(source_leaf / "2025-01-31_Same Title_Channel.mp4", 4)
        _write_bytes(archive_leaf / "same-title-channel.mp4", 7)

        summary = run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=False,
            config=config,
        )

        assert summary["processed_sets"] == 1
        assert summary["merged_sets"] == 1
        assert (archive_leaf / "same-title-channel.mp4").exists()
        assert not (source_leaf / "2025-01-31_Same Title_Channel.mp4").exists()

    def test_run_dedupe_trashes_source_and_extra_archive_with_relative_paths(
        self, config, temp_dir: Path
    ):
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        trash_dir = temp_dir / "trash"
        source_leaf = source_dir / "Incoming" / "Channel"
        archive_primary = archive_dir / "Playlists" / "Primary"
        archive_extra = archive_dir / "Playlists" / "Duplicate"
        config._config["filename"]["tokens"] = ["title", "channel"]

        _write_bytes(source_leaf / "source-copy.mp4", 5)
        _write_info_json(
            source_leaf / "source-copy.info.json",
            video_id="abc123",
            title="Canonical Video",
            uploader="Archive Channel",
        )

        _write_bytes(archive_primary / "archived.mp4", 15)
        _write_metadata_json(
            archive_primary / "archived.metadata.json",
            video_id="abc123",
            title="Canonical Video",
            uploader="Archive Channel",
        )
        _write_bytes(archive_extra / "duplicate.mp4", 3)
        _write_info_json(
            archive_extra / "duplicate.info.json",
            video_id="abc123",
            title="Canonical Video",
            uploader="Archive Channel",
        )

        summary = run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=trash_dir,
            delete=False,
            dry_run=False,
            verbose=False,
            config=config,
        )

        assert summary["source_groups_disposed"] == 1
        assert summary["archive_groups_disposed"] == 1
        assert (trash_dir / "source" / "Incoming" / "Channel" / "source-copy.mp4").exists()
        assert (trash_dir / "archive" / "Playlists" / "Duplicate" / "duplicate.mp4").exists()
