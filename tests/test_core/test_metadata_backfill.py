"""Tests for metadata backfill workflow."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import toml
import yt_dlp

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
    def __init__(
        self,
        opts,
        calls,
        crash_on_backfill_id: str | None = None,
        rate_limit_on_id: str | None = None,
    ):
        self._opts = opts
        self._calls = calls
        self._crash_on_backfill_id = crash_on_backfill_id
        self._rate_limit_on_id = rate_limit_on_id

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url: str, download: bool = False):
        video_id = _video_id_from_url(url)
        self._calls.append({"opts": self._opts, "url": url, "download": download})

        if video_id == self._rate_limit_on_id:
            raise yt_dlp.DownloadError(
                "This content isn't available, try again later. Your account has been rate-limited by YouTube for up to an hour."
            )

        if video_id == self._crash_on_backfill_id:
            raise RuntimeError("boom")

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
        assert len(calls) == 2
        assert (playlist_dir / "abc123.info.json").exists()
        assert (playlist_dir / "def456.info.json").exists()

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
        totals = backfiller.run(scope="info-json", refresh_existing=False)

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

        assert len(calls) == 1
        assert (playlist_dir / "legacy-abc123.info.json").exists()

    def test_backfill_tvshow_nfo_uses_playlist_name_for_any_playlist_type(
        self, config, temp_dir, mocker
    ):
        base_dir = temp_dir / "archive"
        playlist_dir = base_dir / "test_playlist"
        playlist_dir.mkdir(parents=True, exist_ok=True)
        (playlist_dir / ".archive.txt").write_text("", encoding="utf-8")
        _write_playlists(
            config,
            [
                {
                    "id": "UUW5OrUZ4SeUYkUg1XqcjFYA",
                    "path": "test_playlist",
                    "name": "GeoWizard",
                }
            ],
        )

        config._config["archive"]["base_directory"] = str(base_dir)

        calls: list[dict[str, object]] = []
        mocker.patch(
            "ytdl_archiver.core.metadata_backfill.yt_dlp.YoutubeDL",
            side_effect=lambda opts: _FakeYoutubeDL(opts, calls),
        )

        backfiller = MetadataBackfiller(config)
        totals = backfiller.run(scope="info-json")
        assert totals == {"updated": 0, "skipped_existing": 0, "failed": 0}

        tvshow_nfo = playlist_dir / "tvshow.nfo"
        assert tvshow_nfo.exists()
        assert "<title>GeoWizard</title>" in tvshow_nfo.read_text(encoding="utf-8")

    def test_backfill_tvshow_nfo_falls_back_to_playlist_path(
        self, config, temp_dir, mocker
    ):
        base_dir = temp_dir / "archive"
        playlist_dir = base_dir / "custom_folder"
        playlist_dir.mkdir(parents=True, exist_ok=True)
        (playlist_dir / ".archive.txt").write_text("", encoding="utf-8")
        _write_playlists(
            config,
            [{"id": "PLOgg6_QCO8CeFd55aR1RgzSQOOWhR12uj", "path": "custom_folder"}],
        )
        config._config["archive"]["base_directory"] = str(base_dir)

        calls: list[dict[str, object]] = []
        mocker.patch(
            "ytdl_archiver.core.metadata_backfill.yt_dlp.YoutubeDL",
            side_effect=lambda opts: _FakeYoutubeDL(opts, calls),
        )

        backfiller = MetadataBackfiller(config)
        backfiller.run(scope="info-json")

        tvshow_nfo = playlist_dir / "tvshow.nfo"
        assert tvshow_nfo.exists()
        assert "<title>custom_folder</title>" in tvshow_nfo.read_text(encoding="utf-8")

    def test_full_scope_writes_nfo_and_metadata_when_info_json_exists(
        self, config, temp_dir, mocker
    ):
        base_dir = temp_dir / "archive"
        playlist_path = "ExamplePlaylist"
        playlist_dir = base_dir / playlist_path
        playlist_dir.mkdir(parents=True, exist_ok=True)
        (playlist_dir / ".archive.txt").write_text("abc123\n", encoding="utf-8")
        (playlist_dir / "abc123.info.json").write_text("{}", encoding="utf-8")
        _write_playlists(config, [{"id": "PLx", "path": playlist_path, "name": "Named"}])
        config._config["archive"]["base_directory"] = str(base_dir)
        config._config["filename"]["tokens"] = ["video_id"]

        calls: list[dict[str, object]] = []
        mocker.patch(
            "ytdl_archiver.core.metadata_backfill.yt_dlp.YoutubeDL",
            side_effect=lambda opts: _FakeYoutubeDL(opts, calls),
        )

        backfiller = MetadataBackfiller(config)
        create_nfo_mock = mocker.patch.object(backfiller.metadata_generator, "create_nfo_file")
        write_metadata_mock = mocker.patch.object(
            backfiller.downloader, "_write_max_metadata_sidecar"
        )

        totals = backfiller.run(scope="full", refresh_existing=False)
        assert totals == {"updated": 1, "skipped_existing": 0, "failed": 0}
        create_nfo_mock.assert_called_once()
        write_metadata_mock.assert_called_once()
        assert len(calls) == 1

    def test_full_scope_respects_write_max_metadata_json_disabled(
        self, config, temp_dir, mocker
    ):
        base_dir = temp_dir / "archive"
        playlist_path = "ExamplePlaylist"
        playlist_dir = base_dir / playlist_path
        playlist_dir.mkdir(parents=True, exist_ok=True)
        (playlist_dir / ".archive.txt").write_text("abc123\n", encoding="utf-8")
        _write_playlists(config, [{"id": "PLx", "path": playlist_path, "name": "Named"}])
        config._config["archive"]["base_directory"] = str(base_dir)
        config._config["filename"]["tokens"] = ["video_id"]
        config._config["download"]["write_max_metadata_json"] = False

        calls: list[dict[str, object]] = []
        mocker.patch(
            "ytdl_archiver.core.metadata_backfill.yt_dlp.YoutubeDL",
            side_effect=lambda opts: _FakeYoutubeDL(opts, calls),
        )

        backfiller = MetadataBackfiller(config)
        write_metadata_mock = mocker.patch.object(
            backfiller.downloader, "_write_max_metadata_sidecar"
        )

        totals = backfiller.run(scope="full", refresh_existing=True)
        assert totals == {"updated": 1, "skipped_existing": 0, "failed": 0}
        write_metadata_mock.assert_not_called()

    def test_full_scope_renames_fallback_stem_to_canonical(
        self, config, temp_dir, mocker
    ):
        base_dir = temp_dir / "archive"
        playlist_path = "ExamplePlaylist"
        playlist_dir = base_dir / playlist_path
        playlist_dir.mkdir(parents=True, exist_ok=True)
        (playlist_dir / ".archive.txt").write_text("abc123\n", encoding="utf-8")
        _write_playlists(config, [{"id": "PLx", "path": playlist_path, "name": "Named"}])
        config._config["archive"]["base_directory"] = str(base_dir)
        config._config["archive"]["delay_between_videos"] = 0

        fallback_stem = "video-abc123_unknown-channel"
        (playlist_dir / f"{fallback_stem}.mp4").write_bytes(b"video")
        (playlist_dir / f"{fallback_stem}.info.json").write_text("{}", encoding="utf-8")
        (playlist_dir / f"{fallback_stem}.nfo").write_text("nfo", encoding="utf-8")

        calls: list[dict[str, object]] = []
        mocker.patch(
            "ytdl_archiver.core.metadata_backfill.yt_dlp.YoutubeDL",
            side_effect=lambda opts: _FakeYoutubeDL(opts, calls),
        )

        backfiller = MetadataBackfiller(config)
        write_metadata_mock = mocker.patch.object(
            backfiller.downloader, "_write_max_metadata_sidecar"
        )
        create_nfo_mock = mocker.patch.object(backfiller.metadata_generator, "create_nfo_file")

        totals = backfiller.run(scope="full", refresh_existing=False)
        assert totals == {"updated": 1, "skipped_existing": 0, "failed": 0}

        canonical_stem = "2025-01-31_video-abc123_test-channel"
        assert not (playlist_dir / f"{fallback_stem}.mp4").exists()
        assert (playlist_dir / f"{canonical_stem}.mp4").exists()
        assert (playlist_dir / f"{canonical_stem}.info.json").exists()
        assert (playlist_dir / f"{canonical_stem}.nfo").exists()
        write_metadata_mock.assert_called_once()
        create_nfo_mock.assert_called_once()

    def test_full_scope_skips_rename_on_conflict_and_warns(
        self, config, temp_dir, mocker
    ):
        base_dir = temp_dir / "archive"
        playlist_path = "ExamplePlaylist"
        playlist_dir = base_dir / playlist_path
        playlist_dir.mkdir(parents=True, exist_ok=True)
        (playlist_dir / ".archive.txt").write_text("abc123\n", encoding="utf-8")
        _write_playlists(config, [{"id": "PLx", "path": playlist_path, "name": "Named"}])
        config._config["archive"]["base_directory"] = str(base_dir)
        config._config["archive"]["delay_between_videos"] = 0

        fallback_stem = "video-abc123_unknown-channel"
        canonical_stem = "2025-01-31_video-abc123_test-channel"
        (playlist_dir / f"{fallback_stem}.mp4").write_bytes(b"video")
        (playlist_dir / f"{fallback_stem}.info.json").write_text("{}", encoding="utf-8")
        (playlist_dir / f"{canonical_stem}.info.json").write_text("{}", encoding="utf-8")

        calls: list[dict[str, object]] = []
        mocker.patch(
            "ytdl_archiver.core.metadata_backfill.yt_dlp.YoutubeDL",
            side_effect=lambda opts: _FakeYoutubeDL(opts, calls),
        )

        formatter = mocker.Mock()
        backfiller = MetadataBackfiller(config, formatter=formatter)
        mocker.patch.object(backfiller.downloader, "_write_max_metadata_sidecar")
        mocker.patch.object(backfiller.metadata_generator, "create_nfo_file")

        emit_msg = mocker.patch("ytdl_archiver.core.metadata_backfill.emit_formatter_message")
        totals = backfiller.run(scope="full", refresh_existing=True)

        assert totals == {"updated": 1, "skipped_existing": 0, "failed": 0}
        assert (playlist_dir / f"{fallback_stem}.mp4").exists()
        warning_calls = [
            call for call in emit_msg.call_args_list if call.args[1] == "warning"
        ]
        assert warning_calls
        assert "Rename skipped: target stem already exists" in warning_calls[-1].args[2]

    def test_backfill_applies_delay_between_videos(self, config, temp_dir, mocker):
        base_dir = temp_dir / "archive"
        playlist_path = "ExamplePlaylist"
        playlist_dir = base_dir / playlist_path
        playlist_dir.mkdir(parents=True, exist_ok=True)
        (playlist_dir / ".archive.txt").write_text("abc123\ndef456\n", encoding="utf-8")
        _write_playlists(config, [{"id": "PLx", "path": playlist_path}])

        config._config["archive"]["base_directory"] = str(base_dir)
        config._config["archive"]["delay_between_videos"] = 2
        calls: list[dict[str, object]] = []
        mocker.patch(
            "ytdl_archiver.core.metadata_backfill.yt_dlp.YoutubeDL",
            side_effect=lambda opts: _FakeYoutubeDL(opts, calls),
        )
        sleep_mock = mocker.patch("ytdl_archiver.core.metadata_backfill.time.sleep")

        backfiller = MetadataBackfiller(config)
        totals = backfiller.run(scope="info-json")

        assert totals == {"updated": 2, "skipped_existing": 0, "failed": 0}
        sleep_mock.assert_called_once_with(2.0)

    def test_backfill_rate_limit_continues_and_stops_playlist(
        self, config, temp_dir, mocker
    ):
        base_dir = temp_dir / "archive"
        playlist_path = "ExamplePlaylist"
        playlist_dir = base_dir / playlist_path
        playlist_dir.mkdir(parents=True, exist_ok=True)
        (playlist_dir / ".archive.txt").write_text("ok1\nratelimit\nlater3\n", encoding="utf-8")
        _write_playlists(config, [{"id": "PLx", "path": playlist_path}])
        config._config["archive"]["base_directory"] = str(base_dir)
        config._config["archive"]["delay_between_videos"] = 0

        calls: list[dict[str, object]] = []
        mocker.patch(
            "ytdl_archiver.core.metadata_backfill.yt_dlp.YoutubeDL",
            side_effect=lambda opts: _FakeYoutubeDL(opts, calls, rate_limit_on_id="ratelimit"),
        )
        formatter = mocker.Mock()
        emit_msg = mocker.patch("ytdl_archiver.core.metadata_backfill.emit_formatter_message")

        backfiller = MetadataBackfiller(config, formatter=formatter)
        totals = backfiller.run(scope="info-json", continue_on_error=True)

        assert totals == {"updated": 1, "skipped_existing": 0, "failed": 1}
        # Should not hammer third video after limit hit.
        assert len(calls) == 2
        warning_calls = [
            call for call in emit_msg.call_args_list if call.args[1] == "warning"
        ]
        assert warning_calls
        assert "YouTube rate limit detected during metadata backfill" in warning_calls[0].args[2]

    def test_backfill_rate_limit_fail_fast_raises(self, config, temp_dir, mocker):
        base_dir = temp_dir / "archive"
        playlist_path = "ExamplePlaylist"
        playlist_dir = base_dir / playlist_path
        playlist_dir.mkdir(parents=True, exist_ok=True)
        (playlist_dir / ".archive.txt").write_text("ratelimit\n", encoding="utf-8")
        _write_playlists(config, [{"id": "PLx", "path": playlist_path}])
        config._config["archive"]["base_directory"] = str(base_dir)

        calls: list[dict[str, object]] = []
        mocker.patch(
            "ytdl_archiver.core.metadata_backfill.yt_dlp.YoutubeDL",
            side_effect=lambda opts: _FakeYoutubeDL(opts, calls, rate_limit_on_id="ratelimit"),
        )
        backfiller = MetadataBackfiller(config)

        with pytest.raises(ArchiveError, match="Metadata backfill failed for ratelimit"):
            backfiller.run(scope="info-json", continue_on_error=False)
