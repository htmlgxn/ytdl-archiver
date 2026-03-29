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

    def test_run_dedupe_cross_bucket_filename_fallback_matching(self, config, temp_dir: Path):
        """Source .nfo gives video_id 'A', archive .info.json gives video_id 'B',
        but they share the same filename stem and should match via fallback."""
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Channel"
        archive_leaf = archive_dir / "Imports" / "Channel"
        config._config["filename"]["tokens"] = ["upload_date", "title", "channel"]
        config._config["filename"]["date_format"] = "yyyymmdd"

        _write_bytes(source_leaf / "20231018_video-title_channel.mp4", 5)
        (source_leaf / "20231018_video-title_channel.jpg").write_text("thumb", encoding="utf-8")
        _write_nfo(
            source_leaf / "20231018_video-title_channel.nfo",
            video_id="SOURCE_ID_A",
            title="Video Title",
            showtitle="Channel",
            releasedate="2023-10-18",
        )

        _write_bytes(archive_leaf / "20231018_video-title_channel.mp4", 15)
        _write_info_json(
            archive_leaf / "20231018_video-title_channel.info.json",
            video_id="ARCHIVE_ID_B",
            title="Video Title",
            uploader="Channel",
        )
        _write_metadata_json(
            archive_leaf / "20231018_video-title_channel.metadata.json",
            video_id="ARCHIVE_ID_B",
            title="Video Title",
            uploader="Channel",
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

        # They should match and merge, not import separately
        assert summary["imported_sets"] == 0
        assert summary["merged_sets"] == 1 or summary["replaced_sets"] == 1
        # Archive should have ONE copy with all sidecars (canonical stem uses archive metadata date)
        canonical_stem = "20250131_video-title_channel"
        assert (archive_leaf / f"{canonical_stem}.mp4").exists()
        assert (archive_leaf / f"{canonical_stem}.info.json").exists()
        assert (archive_leaf / f"{canonical_stem}.nfo").exists()
        assert (archive_leaf / f"{canonical_stem}.jpg").exists()
        # Source should be cleaned up
        assert not (source_leaf / "20231018_video-title_channel.mp4").exists()
        assert not (source_leaf / "20231018_video-title_channel.jpg").exists()
        assert not (source_leaf / "20231018_video-title_channel.nfo").exists()
        # No __dedupe_1 files
        dedupe_files = list(archive_leaf.glob("*__dedupe_*"))
        assert dedupe_files == []

    def test_run_dedupe_consolidates_undated_archive_duplicates(self, config, temp_dir: Path):
        """Archive has both dated and undated stems for the same video.
        The undated copy should be treated as extra_archive and disposed."""
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Channel"
        archive_leaf = archive_dir / "Imports" / "Channel"
        config._config["filename"]["tokens"] = ["upload_date", "title", "channel"]
        config._config["filename"]["date_format"] = "yyyymmdd"

        _write_bytes(source_leaf / "20231018_video-title_channel.mp4", 5)
        _write_nfo(
            source_leaf / "20231018_video-title_channel.nfo",
            video_id="SOURCE_ID_A",
            title="Video Title",
            showtitle="Channel",
            releasedate="2023-10-18",
        )

        # Dated archive with metadata
        _write_bytes(archive_leaf / "20231018_video-title_channel.mp4", 15)
        _write_info_json(
            archive_leaf / "20231018_video-title_channel.info.json",
            video_id="ARCHIVE_ID_B",
            title="Video Title",
            uploader="Channel",
        )
        _write_metadata_json(
            archive_leaf / "20231018_video-title_channel.metadata.json",
            video_id="ARCHIVE_ID_B",
            title="Video Title",
            uploader="Channel",
        )
        (archive_leaf / "20231018_video-title_channel.nfo").write_text(
            "<movie><uniqueid type=\"youtube\">ARCHIVE_ID_B</uniqueid></movie>",
            encoding="utf-8",
        )

        # Undated archive copy (same video, no metadata → different match key)
        _write_bytes(archive_leaf / "video-title_channel.mp4", 10)
        (archive_leaf / "video-title_channel.jpg").write_text("thumb", encoding="utf-8")

        summary = run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=True,
            config=config,
        )

        # Undated archive copy should be disposed as extra_archive
        assert summary["archive_groups_disposed"] >= 1
        # Archive should have exactly one set of files (renamed to canonical)
        mp4_files = list(archive_leaf.glob("*.mp4"))
        assert len(mp4_files) == 1, f"Expected 1 mp4, got {[f.name for f in mp4_files]}"
        # Undated files should be gone
        assert not (archive_leaf / "video-title_channel.mp4").exists()
        assert not (archive_leaf / "video-title_channel.jpg").exists()
        # Source should be cleaned up
        assert not (source_leaf / "20231018_video-title_channel.mp4").exists()
        # No __dedupe_1 files
        dedupe_files = list(archive_leaf.glob("*__dedupe_*"))
        assert dedupe_files == []

    def test_run_dedupe_disposes_best_source_non_video_files_in_replace_path(
        self, config, temp_dir: Path
    ):
        """When source replaces archive video, source's non-video files (jpg, nfo)
        should also be disposed after merge, not left behind."""
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Incoming" / "Channel"
        archive_leaf = archive_dir / "Playlists" / "Named"
        config._config["filename"]["tokens"] = ["title", "channel"]

        _write_bytes(source_leaf / "source-copy.mp4", 2000)
        _write_info_json(
            source_leaf / "source-copy.info.json",
            video_id="abc123",
            title="Canonical Video",
            uploader="Archive Channel",
        )
        (source_leaf / "source-copy.jpg").write_text("thumb", encoding="utf-8")
        (source_leaf / "source-copy.nfo").write_text(
            "<movie><uniqueid type=\"youtube\">abc123</uniqueid></movie>",
            encoding="utf-8",
        )

        _write_bytes(archive_leaf / "old-archive.mp4", 5)
        _write_metadata_json(
            archive_leaf / "old-archive.metadata.json",
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
            verbose=True,
            config=config,
        )

        final_stem = "canonical-video_archive-channel"
        assert summary["replaced_sets"] == 1
        # Source video and non-video files should all be gone
        assert not (source_leaf / "source-copy.mp4").exists()
        assert not (source_leaf / "source-copy.jpg").exists()
        assert not (source_leaf / "source-copy.nfo").exists()
        assert not (source_leaf / "source-copy.info.json").exists()
        # Archive should have the merged result
        assert (archive_leaf / f"{final_stem}.mp4").exists()
        assert (archive_leaf / f"{final_stem}.jpg").exists()
        assert (archive_leaf / f"{final_stem}.nfo").exists()

    def test_run_dedupe_dry_run_rename_not_blocked_by_disposed_files(
        self, config, temp_dir: Path
    ):
        """In dry_run, disposed files aren't actually deleted. Rename should
        still succeed because we skip filesystem checks in dry_run mode."""
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Channel"
        archive_leaf = archive_dir / "Imports" / "Channel"
        config._config["filename"]["tokens"] = ["upload_date", "title", "channel"]
        config._config["filename"]["date_format"] = "yyyymmdd"

        _write_bytes(source_leaf / "legacy.mp4", 5)
        _write_nfo(
            source_leaf / "legacy.nfo",
            video_id="abc123",
            title="Video Title",
            showtitle="Channel",
            releasedate="2023-10-18",
        )

        # Archive with undated stem that would block rename to dated canonical
        _write_bytes(archive_leaf / "video-title_channel.mp4", 15)
        _write_info_json(
            archive_leaf / "video-title_channel.info.json",
            video_id="abc123",
            title="Video Title",
            uploader="Channel",
        )

        summary = run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=True,
            verbose=True,
            config=config,
        )

        # Should rename to canonical (not be blocked)
        assert summary["archive_winners_renamed"] == 1
        assert summary["rename_blocked_sets"] == 0

    def test_part_files_ignored_entirely(self, config, temp_dir: Path):
        """Incomplete .part downloads should not be treated as video groups."""
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Channel"
        archive_dir.mkdir()

        (source_leaf).mkdir(parents=True)
        (source_leaf / "video.live_chat.json.part").write_text("partial", encoding="utf-8")
        (source_leaf / "video.live_chat.json.part-Frag0.part").write_text("frag", encoding="utf-8")

        groups = scan_directory(source_dir)
        assert len(groups) == 0

    def test_apostrophe_normalization_matches_variants(self, config, temp_dir: Path):
        """there's and theres should match via normalized filename."""
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Channel"
        archive_leaf = archive_dir / "Imports" / "Channel"
        config._config["filename"]["tokens"] = ["title", "channel"]

        _write_bytes(source_leaf / "there's-a-problem_channel.mp4", 5)
        _write_bytes(archive_leaf / "theres-a-problem_channel.mp4", 15)

        summary = run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=True,
            config=config,
        )

        assert summary["imported_sets"] == 0
        assert summary["merged_sets"] == 1

    def test_archive_only_undated_duplicates_consolidated(self, config, temp_dir: Path):
        """Undated archive duplicates should be disposed even without any source trigger."""
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        archive_leaf = archive_dir / "Channel"
        source_dir.mkdir(parents=True)
        config._config["filename"]["tokens"] = ["upload_date", "title", "channel"]
        config._config["filename"]["date_format"] = "yyyymmdd"

        # Dated archive copy with metadata
        _write_bytes(archive_leaf / "20231018_video-title_channel.mp4", 15)
        _write_info_json(
            archive_leaf / "20231018_video-title_channel.info.json",
            video_id="abc123",
            title="Video Title",
            uploader="Channel",
        )

        # Undated archive copy (no metadata)
        _write_bytes(archive_leaf / "video-title_channel.mp4", 10)
        (archive_leaf / "video-title_channel.jpg").write_text("thumb", encoding="utf-8")

        summary = run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=True,
            config=config,
        )

        # Undated copy should be disposed
        assert summary["archive_groups_disposed"] >= 1
        assert not (archive_leaf / "video-title_channel.mp4").exists()
        assert not (archive_leaf / "video-title_channel.jpg").exists()
        # Dated copy should remain (possibly renamed to canonical)
        mp4_files = list(archive_leaf.glob("*.mp4"))
        assert len(mp4_files) == 1

    def test_live_chat_json_imported_to_live_chats_subdir(self, config, temp_dir: Path):
        """Live chat json files should be moved to live-chats/ subdirectory."""
        source_dir = temp_dir / "source"
        archive_dir = temp_dir / "archive"
        source_leaf = source_dir / "Imports" / "Channel"
        archive_dir.mkdir()
        config._config["filename"]["tokens"] = ["upload_date", "title", "channel"]
        config._config["filename"]["date_format"] = "yyyymmdd"

        _write_bytes(source_leaf / "legacy.mp4", 8)
        _write_info_json(
            source_leaf / "legacy.info.json",
            video_id="abc123",
            title="Video Title",
            uploader="Channel",
        )
        (source_leaf / "legacy.live_chat.json").write_text('{"chat": []}', encoding="utf-8")

        summary = run_dedupe(
            source_dir,
            archive_dir,
            trash_dir=None,
            delete=True,
            dry_run=False,
            verbose=True,
            config=config,
        )

        assert summary["imported_sets"] == 1
        final_stem = "20250131_video-title_channel"
        archive_leaf = archive_dir / "Imports" / "Channel"
        assert (archive_leaf / f"{final_stem}.mp4").exists()
        assert (archive_leaf / "live-chats" / f"{final_stem}.live_chat.json").exists()
