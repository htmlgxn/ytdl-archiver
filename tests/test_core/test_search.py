"""Tests for multi-backend search service."""

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from ytdl_archiver.config.settings import Config
from ytdl_archiver.core.search import InvidiousSearchService, YouTubeHtmlBackend
from ytdl_archiver.exceptions import SearchError


class _FakeResponse:
    def __init__(self, *, payload=None, text: str = "", status_code: int = 200):
        self._payload = payload
        self.text = text
        self.status_code = status_code
        self.request = httpx.Request("GET", "https://example.invalid")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "request failed",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses, attempted):
        self._responses = responses
        self._attempted = attempted

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, params=None):
        key = (url, tuple(sorted((params or {}).items())))
        self._attempted.append(key)
        result = self._responses.get(key)
        if isinstance(result, Exception):
            raise result
        if result is None:
            return _FakeResponse(payload=[], text="")
        return result


def _config(temp_dir: Path) -> Config:
    config_path = temp_dir / "config.toml"
    config_path.write_text("[archive]\nbase_directory = '/tmp'\n")
    cfg = Config(config_path)
    cfg._config.setdefault("search", {})
    cfg._config["search"]["instances"] = ["https://inv.a", "https://inv.b"]
    cfg._config["search"]["max_results"] = 20
    cfg._config["search"]["backend_order"] = ["youtube_html", "yt_dlp", "invidious"]
    cfg._config["search"]["backend_strict"] = False
    cfg._config["search"]["fallback_enabled"] = False
    cfg._config["search"]["fallback_on_error"] = False
    cfg._config["search"]["fallback_on_zero_results"] = False
    cfg._config["search"]["yt_dlp_timeout_seconds"] = 10
    cfg._config["search"]["youtube_html_timeout_seconds"] = 8
    return cfg


def _youtube_html_fixture() -> str:
    section_contents = [
        {
            "channelRenderer": {
                "channelId": "UCCHAN123",
                "title": {"simpleText": "Art Chad Channel"},
                "subscriberCountText": {
                    "simpleText": "12.3K subscribers"
                },
                "videoCountText": {"simpleText": "250 videos"},
                "descriptionSnippet": {
                    "runs": [{"text": "Channel description"}]
                },
            }
        },
        {
            "playlistRenderer": {
                "playlistId": "PLART123",
                "title": {"simpleText": "Art Playlist"},
                "longBylineText": {
                    "runs": [{"text": "Art Curator"}]
                },
                "videoCount": "42",
                "descriptionSnippet": {
                    "runs": [{"text": "Playlist description"}]
                },
            }
        },
    ]
    for idx in range(1, 13):
        section_contents.append(
            {
                "videoRenderer": {
                    "videoId": f"vid-{idx}",
                    "ownerText": {
                        "runs": [
                            {
                                "text": f"Art Channel {idx}",
                                "navigationEndpoint": {
                                    "browseEndpoint": {
                                        "browseId": f"UCVIDEO{idx:03d}"
                                    }
                                },
                            }
                        ]
                    },
                }
            }
        )

    data = {
        "contents": {
            "twoColumnSearchResultsRenderer": {
                "primaryContents": {
                    "sectionListRenderer": {
                        "contents": [
                            {
                                "itemSectionRenderer": {
                                    "contents": section_contents
                                }
                            }
                        ]
                    }
                }
            }
        }
    }
    return f"<html><script>var ytInitialData = {json.dumps(data)};</script></html>"


class TestBackendOrder:
    def test_youtube_html_first_success(self, temp_dir, mocker):
        cfg = _config(temp_dir)
        attempted = []
        html = _youtube_html_fixture()
        responses = {
            (
                "https://www.youtube.com/results",
                (("search_query", "art"),),
            ): _FakeResponse(text=html, payload={}),
            (
                "https://www.youtube.com/results",
                (("search_query", "art channel"),),
            ): _FakeResponse(text=html, payload={}),
        }
        mocker.patch(
            "ytdl_archiver.core.search.httpx.Client",
            side_effect=lambda **_kwargs: _FakeClient(responses, attempted),
        )
        mocker.patch(
            "ytdl_archiver.core.search.subprocess.run",
            return_value=type("P", (), {"returncode": 1, "stdout": "", "stderr": "fail"})(),
        )

        service = InvidiousSearchService(cfg)
        results = service.search("art")

        assert results
        assert service.last_backend_used == "youtube_html"
        assert results[0].instance == "youtube-html"
        assert not any("/api/v1/search" in url for url, _ in attempted)

    def test_invidious_empty_youtube_html_success(self, temp_dir, mocker):
        cfg = _config(temp_dir)
        attempted = []
        html = _youtube_html_fixture()
        responses = {
            (
                "https://www.youtube.com/results",
                (("search_query", "art"),),
            ): _FakeResponse(text=html, payload={}),
            (
                "https://www.youtube.com/results",
                (("search_query", "art channel"),),
            ): _FakeResponse(text=html, payload={}),
        }
        mocker.patch(
            "ytdl_archiver.core.search.httpx.Client",
            side_effect=lambda **_kwargs: _FakeClient(responses, attempted),
        )
        mocker.patch(
            "ytdl_archiver.core.search.subprocess.run",
            return_value=type("P", (), {"returncode": 1, "stdout": "", "stderr": "fail"})(),
        )

        service = InvidiousSearchService(cfg)
        results = service.search("art")

        assert results
        assert service.last_backend_used == "youtube_html"

    def test_youtube_html_fail_yt_dlp_success(self, temp_dir, mocker):
        cfg = _config(temp_dir)
        cfg._config["search"]["fallback_enabled"] = True
        cfg._config["search"]["fallback_on_error"] = True
        cfg._config["search"]["backend_order"] = ["youtube_html", "yt_dlp"]
        attempted = []
        responses = {
            (
                "https://www.youtube.com/results",
                (("search_query", "art"),),
            ): httpx.RequestError("yt blocked"),
            (
                "https://www.youtube.com/results",
                (("search_query", "art channel"),),
            ): httpx.RequestError("yt blocked"),
        }
        mocker.patch(
            "ytdl_archiver.core.search.httpx.Client",
            side_effect=lambda **_kwargs: _FakeClient(responses, attempted),
        )
        payload = {
            "entries": [
                {"channel_id": f"UCFALL{idx:03d}", "channel": f"Fallback {idx}"}
                for idx in range(1, 13)
            ]
        }
        mocker.patch(
            "ytdl_archiver.core.search.subprocess.run",
            return_value=type(
                "P",
                (),
                {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""},
            )(),
        )

        service = InvidiousSearchService(cfg)
        results = service.search("art")

        assert len(results) >= 10
        assert results[0].instance == "yt-dlp-fallback"
        assert service.last_backend_used == "yt_dlp"

    def test_backend_strict_stops_after_first_failure(self, temp_dir, mocker):
        cfg = _config(temp_dir)
        cfg._config["search"]["backend_strict"] = True
        attempted = []
        responses = {
            (
                "https://www.youtube.com/results",
                (("search_query", "strict"),),
            ): httpx.RequestError("down"),
        }
        mocker.patch(
            "ytdl_archiver.core.search.httpx.Client",
            side_effect=lambda **_kwargs: _FakeClient(responses, attempted),
        )
        subprocess_mock = mocker.patch("ytdl_archiver.core.search.subprocess.run")

        service = InvidiousSearchService(cfg)
        with pytest.raises(SearchError, match="strict"):
            service.search("strict")
        subprocess_mock.assert_not_called()
        assert attempted

    def test_channel_first_default_skips_playlist_calls(self, temp_dir, mocker):
        cfg = _config(temp_dir)
        attempted = []
        responses = {
            (
                "https://www.youtube.com/results",
                (("search_query", "art"),),
            ): _FakeResponse(text=_youtube_html_fixture(), payload={}),
            (
                "https://www.youtube.com/results",
                (("search_query", "art channel"),),
            ): _FakeResponse(text=_youtube_html_fixture(), payload={}),
        }
        mocker.patch(
            "ytdl_archiver.core.search.httpx.Client",
            side_effect=lambda **_kwargs: _FakeClient(responses, attempted),
        )
        service = InvidiousSearchService(cfg)
        results = service.search("art")
        assert len(results) >= 10
        assert all(result.result_type == "channel" for result in results)

    def test_include_playlists_enables_playlist_discovery(self, temp_dir, mocker):
        cfg = _config(temp_dir)
        attempted = []
        playlist_only_html = (
            "<html><script>var ytInitialData = "
            + json.dumps(
                {
                    "contents": {
                        "sectionListRenderer": {
                            "contents": [
                                {
                                    "itemSectionRenderer": {
                                        "contents": [
                                            {
                                                "playlistRenderer": {
                                                    "playlistId": "PLONLY",
                                                    "title": {"simpleText": "Only Playlist"},
                                                }
                                            }
                                        ]
                                    }
                                }
                            ]
                        }
                    }
                }
            )
            + ";</script></html>"
        )
        responses = {
            (
                "https://www.youtube.com/results",
                (("search_query", "art"),),
            ): _FakeResponse(text=playlist_only_html, payload={}),
            (
                "https://www.youtube.com/results",
                (("search_query", "art channel"),),
            ): _FakeResponse(text=playlist_only_html, payload={}),
        }
        mocker.patch(
            "ytdl_archiver.core.search.httpx.Client",
            side_effect=lambda **_kwargs: _FakeClient(responses, attempted),
        )
        service = InvidiousSearchService(cfg)
        results = service.search("art", include_playlists=True)
        assert len(results) == 1
        assert results[0].result_type == "playlist"


class TestYouTubeHtmlParsing:
    def test_extracts_channels_from_ytinitialdata(self, mocker):
        backend = YouTubeHtmlBackend(
            timeout=httpx.Timeout(timeout=10, connect=5),
            headers={"User-Agent": "test-agent"},
        )
        html = _youtube_html_fixture()
        mocker.patch.object(backend, "_search_data", return_value=json.loads(html.split("=", 1)[1].split(";</script>")[0].strip()))

        channels = backend.search_channels("art", 10)

        assert len(channels) == 10
        assert any(item.source_id == "UCCHAN123" for item in channels)
        assert any(item.source_id.startswith("UCVIDEO") for item in channels)

    def test_extracts_playlists_from_ytinitialdata(self, mocker):
        backend = YouTubeHtmlBackend(
            timeout=httpx.Timeout(timeout=10, connect=5),
            headers={"User-Agent": "test-agent"},
        )
        html = _youtube_html_fixture()
        mocker.patch.object(backend, "_search_data", return_value=json.loads(html.split("=", 1)[1].split(";</script>")[0].strip()))

        playlists = backend.search_playlists("art", 10)

        assert len(playlists) == 1
        assert playlists[0].source_id == "PLART123"
        assert playlists[0].archive_id == "PLART123"

    def test_search_data_uses_query_cache(self, mocker):
        backend = YouTubeHtmlBackend(
            timeout=httpx.Timeout(timeout=10, connect=5),
            headers={"User-Agent": "test-agent"},
        )
        html = _youtube_html_fixture()
        attempted = []
        responses = {
            (
                "https://www.youtube.com/results",
                (("search_query", "art"),),
            ): _FakeResponse(text=html, payload={}),
            (
                "https://www.youtube.com/results",
                (("search_query", "art channel"),),
            ): _FakeResponse(text=html, payload={}),
        }
        mocker.patch(
            "ytdl_archiver.core.search.httpx.Client",
            side_effect=lambda **_kwargs: _FakeClient(responses, attempted),
        )

        channels = backend.search_channels("art", 10)
        playlists = backend.search_playlists("art", 10)

        assert channels
        assert playlists
        assert len(attempted) == 1


class TestErrorFormatting:
    def test_aggregated_error_is_concise(self, temp_dir, mocker):
        cfg = _config(temp_dir)
        cfg._config["search"]["fallback_enabled"] = True
        cfg._config["search"]["fallback_on_error"] = True
        attempted = []
        responses = {
            (
                "https://inv.a/api/v1/search",
                (("page", 1), ("q", "err"), ("type", "channel")),
            ): _FakeResponse(status_code=403),
            (
                "https://inv.b/api/v1/search",
                (("page", 1), ("q", "err"), ("type", "channel")),
            ): _FakeResponse(status_code=502),
            (
                "https://www.youtube.com/results",
                (("search_query", "err"),),
            ): httpx.RequestError("youtube blocked"),
            (
                "https://www.youtube.com/results",
                (("search_query", "err channel"),),
            ): httpx.RequestError("youtube blocked"),
        }
        mocker.patch(
            "ytdl_archiver.core.search.httpx.Client",
            side_effect=lambda **_kwargs: _FakeClient(responses, attempted),
        )
        mocker.patch(
            "ytdl_archiver.core.search.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="yt-dlp", timeout=5),
        )

        service = InvidiousSearchService(cfg)
        with pytest.raises(SearchError) as exc_info:
            service.search("err")

        message = str(exc_info.value)
        assert "Search failed across backends." in message
        assert "For more information check" not in message


class TestYtDlpOverfetch:
    def test_overfetch_increases_count_when_unique_channels_low(self, temp_dir, mocker):
        cfg = _config(temp_dir)
        cfg._config["search"]["fallback_enabled"] = True
        cfg._config["search"]["fallback_on_error"] = True
        cfg._config["search"]["backend_order"] = ["yt_dlp"]
        run_calls = []
        attempted = []

        responses = {
            (
                "https://www.youtube.com/results",
                (("search_query", "art"),),
            ): httpx.RequestError("blocked"),
            (
                "https://www.youtube.com/results",
                (("search_query", "art channel"),),
            ): httpx.RequestError("blocked"),
        }
        mocker.patch(
            "ytdl_archiver.core.search.httpx.Client",
            side_effect=lambda **_kwargs: _FakeClient(responses, attempted),
        )

        def _fake_run(cmd, **_kwargs):
            run_calls.append(cmd)
            query_arg = cmd[-1]
            if query_arg.startswith("ytsearch20:"):
                payload = {
                    "entries": [
                        {"channel_id": "UCONE", "channel": "One"},
                        {"channel_id": "UCONE", "channel": "One again"},
                    ]
                }
            else:
                payload = {
                    "entries": [
                        {"channel_id": "UCONE", "channel": "One"},
                        {"channel_id": "UCTWO", "channel": "Two"},
                    ]
                }
            return type("P", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

        mocker.patch("ytdl_archiver.core.search.subprocess.run", side_effect=_fake_run)

        service = InvidiousSearchService(cfg)
        results = service.search("art", max_results=2)

        assert len(results) == 2
        assert len(run_calls) >= 2

    def test_fallback_on_zero_results_disabled_by_default(self, temp_dir, mocker):
        cfg = _config(temp_dir)
        attempted = []
        responses = {
            (
                "https://www.youtube.com/results",
                (("search_query", "none"),),
            ): _FakeResponse(text="<html><script>var ytInitialData = {};</script></html>", payload={}),
            (
                "https://www.youtube.com/results",
                (("search_query", "none channel"),),
            ): _FakeResponse(text="<html><script>var ytInitialData = {};</script></html>", payload={}),
        }
        mocker.patch(
            "ytdl_archiver.core.search.httpx.Client",
            side_effect=lambda **_kwargs: _FakeClient(responses, attempted),
        )
        subprocess_mock = mocker.patch("ytdl_archiver.core.search.subprocess.run")
        service = InvidiousSearchService(cfg)
        assert service.search("none") == []
        subprocess_mock.assert_not_called()

    def test_fallback_on_zero_results_enabled_uses_next_backend(self, temp_dir, mocker):
        cfg = _config(temp_dir)
        cfg._config["search"]["fallback_enabled"] = True
        cfg._config["search"]["fallback_on_zero_results"] = True
        cfg._config["search"]["backend_order"] = ["youtube_html", "yt_dlp"]
        attempted = []
        responses = {
            (
                "https://www.youtube.com/results",
                (("search_query", "none"),),
            ): _FakeResponse(text="<html><script>var ytInitialData = {};</script></html>", payload={}),
            (
                "https://www.youtube.com/results",
                (("search_query", "none channel"),),
            ): _FakeResponse(text="<html><script>var ytInitialData = {};</script></html>", payload={}),
        }
        mocker.patch(
            "ytdl_archiver.core.search.httpx.Client",
            side_effect=lambda **_kwargs: _FakeClient(responses, attempted),
        )
        payload = {"entries": [{"channel_id": "UCFALL000", "channel": "Fallback"}]}
        mocker.patch(
            "ytdl_archiver.core.search.subprocess.run",
            return_value=type(
                "P",
                (),
                {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""},
            )(),
        )

        service = InvidiousSearchService(cfg)
        results = service.search("none", max_results=1)
        assert len(results) == 1
        assert results[0].instance == "yt-dlp-fallback"
