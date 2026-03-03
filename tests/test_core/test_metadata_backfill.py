"""Tests for metadata backfill workflow."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import toml

from ytdl_archiver.core.metadata_backfill import MetadataBackfiller
from ytdl_archiver.exceptions import ArchiveError


def _write_playlists(config, playlists: list[dict[str, str]]) -> Path:
    playlists_path = config.config_path.parent / "playlists.toml"
    playlists_path.parent.mkdir(parents=True, exist_ok=True)
    playlists_path.write_text(toml.dumps({"playlists": playlists}), encoding="utf-8")
    return playlists_path


def _video_id_from_url(url: str) -> str:
    return parse_qs(urlparse(url).query).get("v", [""])[0]


class _FakeYoutubeDL:
    def __init__(self, opts, calls, crash_on_backfill_id: str | None = None):
        self._opts = opts
        self._calls = calls
        self._crash_on_backfill_id = crash_on_backfill_id

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url: str, download: bool = False):
        video_id = _video_id_from_url(url)
        self._calls.append({"opts": self._opts, "url": url, "download": download})

        if self._opts.get("writeinfojson") and video_id == self._crash_on_backfill_id:
            raise RuntimeError("boom")

        if self._opts.get("writeinfojson"):
            return {"id": video_id}

        return {
            "id": video_id,
            "title": f"Video {video_id}",
            "uploader": "Test Channel",
            "upload_date": "20250131",
        }


class TestMetadataBackfiller:
    def test_backfill_archived_ids_with_metadata_only_options(self, config, temp_dir, mocker):
        base_dir = temp_dir / "archive"
        playlist_path = "ExamplePlaylist"
        playlist_dir = base_dir / playlist_path
        playlist_dir.mkdir(parents=True, exist_ok=True)
        (playlist_dir / ".archive.txt").write_text(
            "youtube abc123\nhttps://youtu.be/def456\n", encoding="utf-8"
        )
        _write_playlists(config, [{"id": "PLx", "path": playlist_path}])

        config._config["archive"]["base_directory"] = str(base_dir)
        config._config["filename"]["tokens"] = ["video_id"]
        config._config["archive"]["delay_between_videos"] = 0

        calls: list[dict[str, object]] = []
        mocker.patch(
            "ytdl_archiver.core.metadata_backfill.yt_dlp.YoutubeDL",
            side_effect=lambda opts: _FakeYoutubeDL(opts, calls),
        )

        backfiller = MetadataBackfiller(config)
        totals = backfiller.run(scope="full")

        assert totals == {"updated": 2, "skipped_existing": 0, "failed": 0}
        assert all(call["download"] is False for call in calls)

        sidecar_opts = [call["opts"] for call in calls if call["opts"].get("writeinfojson")]
        assert len(sidecar_opts) == 2
        for opts in sidecar_opts:
            assert opts["skip_download"] is True
            assert opts["writesubtitles"] is True
            assert opts["writeautomaticsub"] is True
            assert opts["writethumbnail"] is True
            assert opts["writecomments"] is True
            assert opts["outtmpl"]["subtitle"].endswith(".%(lang)s.%(ext)s")

    def test_backfill_skips_existing_info_json_when_refresh_disabled(
        self, config, temp_dir, mocker
    ):
        base_dir = temp_dir / "archive"
        playlist_path = "ExamplePlaylist"
        playlist_dir = base_dir / playlist_path
        playlist_dir.mkdir(parents=True, exist_ok=True)
        (playlist_dir / ".archive.txt").write_text("abc123\n", encoding="utf-8")
        (playlist_dir / "abc123.info.json").write_text("{}", encoding="utf-8")
        _write_playlists(config, [{"id": "PLx", "path": playlist_path}])

        config._config["archive"]["base_directory"] = str(base_dir)
        config._config["filename"]["tokens"] = ["video_id"]

        calls: list[dict[str, object]] = []
        mocker.patch(
            "ytdl_archiver.core.metadata_backfill.yt_dlp.YoutubeDL",
            side_effect=lambda opts: _FakeYoutubeDL(opts, calls),
        )

        backfiller = MetadataBackfiller(config)
        totals = backfiller.run(scope="full", refresh_existing=False)

        assert totals == {"updated": 0, "skipped_existing": 1, "failed": 0}
        assert not any(call["opts"].get("writeinfojson") for call in calls)

    def test_backfill_continue_on_error_toggle(self, config, temp_dir, mocker):
        base_dir = temp_dir / "archive"
        playlist_path = "ExamplePlaylist"
        playlist_dir = base_dir / playlist_path
        playlist_dir.mkdir(parents=True, exist_ok=True)
        (playlist_dir / ".archive.txt").write_text("good1\nbad2\n", encoding="utf-8")
        _write_playlists(config, [{"id": "PLx", "path": playlist_path}])

        config._config["archive"]["base_directory"] = str(base_dir)
        config._config["filename"]["tokens"] = ["video_id"]

        calls: list[dict[str, object]] = []
        mocker.patch(
            "ytdl_archiver.core.metadata_backfill.yt_dlp.YoutubeDL",
            side_effect=lambda opts: _FakeYoutubeDL(
                opts, calls, crash_on_backfill_id="bad2"
            ),
        )

        backfiller = MetadataBackfiller(config)
        totals = backfiller.run(scope="info-json", continue_on_error=True)
        assert totals == {"updated": 1, "skipped_existing": 0, "failed": 1}

        with pytest.raises(ArchiveError, match="Metadata backfill failed for bad2"):
            backfiller.run(scope="info-json", continue_on_error=False)

    def test_backfill_prefers_existing_media_stem_when_video_id_matches(
        self, config, temp_dir, mocker
    ):
        base_dir = temp_dir / "archive"
        playlist_path = "ExamplePlaylist"
        playlist_dir = base_dir / playlist_path
        playlist_dir.mkdir(parents=True, exist_ok=True)
        (playlist_dir / ".archive.txt").write_text("abc123\n", encoding="utf-8")
        (playlist_dir / "legacy-abc123.mp4").write_bytes(b"video")
        _write_playlists(config, [{"id": "PLx", "path": playlist_path}])

        config._config["archive"]["base_directory"] = str(base_dir)
        config._config["filename"]["tokens"] = ["video_id"]

        calls: list[dict[str, object]] = []
        mocker.patch(
            "ytdl_archiver.core.metadata_backfill.yt_dlp.YoutubeDL",
            side_effect=lambda opts: _FakeYoutubeDL(opts, calls),
        )

        backfiller = MetadataBackfiller(config)
        totals = backfiller.run(scope="info-json")
        assert totals == {"updated": 1, "skipped_existing": 0, "failed": 0}

        sidecar_calls = [call for call in calls if call["opts"].get("writeinfojson")]
        assert len(sidecar_calls) == 1
        default_outtmpl = sidecar_calls[0]["opts"]["outtmpl"]["default"]
        assert "legacy-abc123.%(ext)s" in default_outtmpl
