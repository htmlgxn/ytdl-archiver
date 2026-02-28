"""Search backends for interactive channel/playlist discovery."""

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Protocol

import httpx

from ..config.settings import Config
from ..exceptions import SearchError

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResult:
    """Structured channel/playlist search result."""

    result_type: Literal["channel", "playlist"]
    title: str
    source_id: str
    archive_id: str
    channel_name: str
    subscriber_count: int | None
    description: str
    video_count: int | None
    instance: str


class SearchBackend(Protocol):
    """Search backend contract."""

    name: str

    def search_channels(self, query: str, limit: int) -> list[SearchResult]:
        """Return matching channel-style search results."""

    def search_playlists(self, query: str, limit: int) -> list[SearchResult]:
        """Return matching playlist-style search results."""


def _sanitize_error(error: Exception) -> str:
    """Condense verbose dependency errors for user-facing output."""
    text = str(error).replace("\n", " ").strip()
    text = re.sub(r"For more information check:\s*\S+", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def _text(value: Any) -> str:
    """Extract readable text from YouTube/Invidious structures."""
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    simple = value.get("simpleText")
    if isinstance(simple, str):
        return simple.strip()
    runs = value.get("runs")
    if isinstance(runs, list):
        parts = []
        for item in runs:
            if isinstance(item, dict):
                part = item.get("text")
                if isinstance(part, str) and part:
                    parts.append(part)
        return "".join(parts).strip()
    return ""


def _parse_compact_number(raw: str) -> int | None:
    """Parse values like 1.2K/3M plus plain digit strings."""
    text = raw.strip().lower().replace(",", "")
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([kmb])?", text)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2) or ""
    factor = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[suffix]
    return int(number * factor)


def _walk_json(node: Any):
    """Yield all nested JSON objects recursively."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_json(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_json(item)


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _tokenize(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if token}


def _match_score(query: str, candidate: str, *, bonus: int = 0) -> int:
    query_norm = _normalize_text(query)
    candidate_norm = _normalize_text(candidate)
    score = bonus
    if not candidate_norm or not query_norm:
        return score
    if candidate_norm == query_norm:
        score += 200
    if candidate_norm.startswith(query_norm):
        score += 80
    if query_norm in candidate_norm:
        score += 40
    query_tokens = _tokenize(query_norm)
    if query_tokens:
        overlap = len(query_tokens.intersection(_tokenize(candidate_norm)))
        score += overlap * 15
    return score


def _prefer_result(current: SearchResult, candidate: SearchResult) -> bool:
    if current.subscriber_count is None and candidate.subscriber_count is not None:
        return True
    if current.video_count is None and candidate.video_count is not None:
        return True
    return len(candidate.description) > len(current.description)


class InvidiousBackend:
    """Search via Invidious /api/v1 endpoints with instance rotation."""

    name = "invidious"

    def __init__(
        self,
        *,
        instances: list[str],
        timeout: httpx.Timeout,
        headers: dict[str, str],
        max_rounds: int,
    ):
        self.instances = instances
        self._timeout = timeout
        self._headers = headers
        self._preferred_index = 0
        self._max_rounds = max(1, max_rounds)

    def _ordered_instances(self) -> list[str]:
        if not self.instances:
            return []
        offset = self._preferred_index % len(self.instances)
        return self.instances[offset:] + self.instances[:offset]

    def _request_json(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> tuple[list[dict[str, Any]] | dict[str, Any], str]:
        attempted: list[str] = []
        failures: list[str] = []
        last_error: Exception | None = None

        for instance in self._ordered_instances():
            attempted.append(instance)
            url = f"{instance}{path}"
            try:
                with httpx.Client(timeout=self._timeout, headers=self._headers) as client:
                    response = client.get(url, params=params)
                    response.raise_for_status()
                    payload = response.json()
            except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
                last_error = exc
                failures.append(f"{instance}: {_sanitize_error(exc)}")
                logger.debug(
                    "Invidious request failed",
                    extra={"instance": instance, "path": path, "error": str(exc)},
                )
                continue

            self._preferred_index = self.instances.index(instance)
            return payload, instance

        details = "; ".join(failures)
        raise SearchError(
            "All configured Invidious instances failed "
            f"({', '.join(attempted)}). Failures: {details}"
        ) from last_error

    def _resolve_channel_uploads_playlist(self, channel_id: str) -> str:
        candidate = channel_id.strip()
        if candidate.upper().startswith("UC") and len(candidate) >= 3:
            return f"UU{candidate[2:]}"

        payload, _ = self._request_json(f"/api/v1/channels/{candidate}")
        if not isinstance(payload, dict):
            raise SearchError(f"Unexpected channel payload for id: {candidate}")

        resolved = str(
            payload.get("authorId") or payload.get("ucid") or payload.get("id") or ""
        ).strip()
        if resolved.upper().startswith("UC") and len(resolved) >= 3:
            return f"UU{resolved[2:]}"
        raise SearchError(f"Could not resolve uploads playlist id for channel: {candidate}")

    def _search_by_type(self, query: str, search_type: str, limit: int) -> list[SearchResult]:
        payload, instance = self._request_json(
            "/api/v1/search",
            params={"q": query, "type": search_type, "page": 1},
        )
        if not isinstance(payload, list):
            raise SearchError("Unexpected Invidious search payload shape")

        output: list[SearchResult] = []
        for item in payload:
            if not isinstance(item, dict):
                continue

            if search_type == "channel":
                channel_id = str(item.get("authorId") or "").strip()
                if not channel_id:
                    continue
                archive_id = self._resolve_channel_uploads_playlist(channel_id)
                channel_name = str(item.get("author") or channel_id).strip()
                output.append(
                    SearchResult(
                        result_type="channel",
                        title=channel_name,
                        source_id=channel_id,
                        archive_id=archive_id,
                        channel_name=channel_name,
                        subscriber_count=_int_or_none(item.get("subCount")),
                        description=str(item.get("description") or "").strip(),
                        video_count=_int_or_none(item.get("videoCount")),
                        instance=f"invidious:{instance}",
                    )
                )
            else:
                playlist_id = str(item.get("playlistId") or "").strip()
                if not playlist_id:
                    continue
                title = str(item.get("title") or playlist_id).strip()
                channel_name = str(item.get("author") or "").strip()
                output.append(
                    SearchResult(
                        result_type="playlist",
                        title=title,
                        source_id=playlist_id,
                        archive_id=playlist_id,
                        channel_name=channel_name,
                        subscriber_count=None,
                        description=str(item.get("description") or "").strip(),
                        video_count=_int_or_none(item.get("videoCount")),
                        instance=f"invidious:{instance}",
                    )
                )

            if len(output) >= limit:
                break
        return output

    def search_channels(self, query: str, limit: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()
        for page in range(1, self._max_rounds + 1):
            payload, instance = self._request_json(
                "/api/v1/search",
                params={"q": query, "type": "video", "page": page},
            )
            if not isinstance(payload, list):
                raise SearchError("Unexpected Invidious video search payload shape")
            if not payload:
                break

            for item in payload:
                if not isinstance(item, dict):
                    continue
                channel_id = str(item.get("authorId") or "").strip()
                channel_name = str(item.get("author") or "").strip()
                if not channel_id or not channel_name or channel_id in seen:
                    continue
                if not (channel_id.upper().startswith("UC") and len(channel_id) >= 3):
                    continue

                description = str(item.get("description") or "").strip()
                results.append(
                    SearchResult(
                        result_type="channel",
                        title=channel_name,
                        source_id=channel_id,
                        archive_id=f"UU{channel_id[2:]}",
                        channel_name=channel_name,
                        subscriber_count=None,
                        description=description,
                        video_count=None,
                        instance=f"invidious:{instance}",
                    )
                )
                seen.add(channel_id)
                if len(results) >= limit:
                    return results
        return results

    def search_playlists(self, query: str, limit: int) -> list[SearchResult]:
        return self._search_by_type(query, "playlist", limit)


class YouTubeHtmlBackend:
    """Search by parsing ytInitialData from YouTube search HTML."""

    name = "youtube_html"

    def __init__(self, *, timeout: httpx.Timeout, headers: dict[str, str]):
        self._timeout = timeout
        self._headers = headers
        self._cache: dict[tuple[tuple[str, str], ...], dict[str, Any]] = {}

    @staticmethod
    def _extract_initial_data(html: str) -> dict[str, Any]:
        marker = "ytInitialData"
        idx = html.find(marker)
        if idx < 0:
            raise SearchError("youtube-html: ytInitialData marker missing")

        start = html.find("{", idx)
        if start < 0:
            raise SearchError("youtube-html: ytInitialData JSON start missing")

        depth = 0
        in_string = False
        escape = False
        end = -1
        for pos in range(start, len(html)):
            char = html[pos]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = pos + 1
                    break

        if end < 0:
            raise SearchError("youtube-html: ytInitialData JSON end missing")

        try:
            return json.loads(html[start:end])
        except json.JSONDecodeError as exc:
            raise SearchError(f"youtube-html: invalid ytInitialData JSON ({exc})") from exc

    def _search_data(self, params: dict[str, str]) -> dict[str, Any]:
        cache_key = tuple(sorted((key, str(value)) for key, value in params.items()))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            with httpx.Client(timeout=self._timeout, headers=self._headers) as client:
                response = client.get("https://www.youtube.com/results", params=params)
                response.raise_for_status()
                html = response.text
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise SearchError(f"youtube-html request failed: {_sanitize_error(exc)}") from exc

        parsed = self._extract_initial_data(html)
        self._cache[cache_key] = parsed
        return parsed

    def search_channels(self, query: str, limit: int) -> list[SearchResult]:
        candidates: dict[str, tuple[int, int, SearchResult]] = {}
        order = 0
        passes = [
            {"search_query": query},
            {"search_query": f"{query} channel"},
        ]
        for pass_index, params in enumerate(passes):
            data = self._search_data(params)
            for node in _walk_json(data):
                renderer = node.get("videoRenderer")
                if isinstance(renderer, dict):
                    owner = renderer.get("ownerText") or renderer.get("longBylineText") or {}
                    channel_name = _text(owner)
                    channel_id = ""
                    if isinstance(owner, dict):
                        runs = owner.get("runs")
                        if isinstance(runs, list):
                            for run in runs:
                                if not isinstance(run, dict):
                                    continue
                                browse = run.get("navigationEndpoint", {}).get("browseEndpoint", {})
                                if isinstance(browse, dict):
                                    candidate = str(browse.get("browseId") or "").strip()
                                    if candidate:
                                        channel_id = candidate
                                        break
                    if channel_id and channel_id.upper().startswith("UC") and len(channel_id) >= 3:
                        result = SearchResult(
                            result_type="channel",
                            title=channel_name or channel_id,
                            source_id=channel_id,
                            archive_id=f"UU{channel_id[2:]}",
                            channel_name=channel_name or channel_id,
                            subscriber_count=None,
                            description="",
                            video_count=None,
                            instance="youtube-html",
                        )
                        label = f"{result.title} {result.channel_name}"
                        score = _match_score(query, label, bonus=8 if pass_index == 0 else 12)
                        existing = candidates.get(channel_id)
                        if existing is None:
                            candidates[channel_id] = (score, order, result)
                            order += 1
                        else:
                            prev_score, prev_order, prev_result = existing
                            if score > prev_score or (
                                score == prev_score and _prefer_result(prev_result, result)
                            ):
                                candidates[channel_id] = (score, prev_order, result)

                renderer = node.get("channelRenderer")
                if not isinstance(renderer, dict):
                    continue
                channel_id = str(renderer.get("channelId") or "").strip()
                if not (channel_id.upper().startswith("UC") and len(channel_id) >= 3):
                    continue
                title = _text(renderer.get("title")) or channel_id
                subs_text = _text(renderer.get("subscriberCountText"))
                result = SearchResult(
                    result_type="channel",
                    title=title,
                    source_id=channel_id,
                    archive_id=f"UU{channel_id[2:]}",
                    channel_name=title,
                    subscriber_count=_parse_compact_number(subs_text) if subs_text else None,
                    description=_text(renderer.get("descriptionSnippet")),
                    video_count=_parse_compact_number(_text(renderer.get("videoCountText")) or ""),
                    instance="youtube-html",
                )
                label = f"{result.title} {result.channel_name}"
                score = _match_score(query, label, bonus=25 if pass_index == 0 else 30)
                existing = candidates.get(channel_id)
                if existing is None:
                    candidates[channel_id] = (score, order, result)
                    order += 1
                else:
                    prev_score, prev_order, prev_result = existing
                    should_replace = score > prev_score or (
                        score == prev_score and _prefer_result(prev_result, result)
                    )
                    if should_replace:
                        candidates[channel_id] = (score, prev_order, result)

            if len(candidates) >= limit:
                break

        ranked = sorted(candidates.values(), key=lambda item: (-item[0], item[1]))
        return [item[2] for item in ranked[:limit]]

    def search_playlists(self, query: str, limit: int) -> list[SearchResult]:
        data = self._search_data({"search_query": query})
        results: list[SearchResult] = []
        for node in _walk_json(data):
            renderer = node.get("playlistRenderer")
            if not isinstance(renderer, dict):
                continue

            playlist_id = str(renderer.get("playlistId") or "").strip()
            if not playlist_id:
                continue
            title = _text(renderer.get("title")) or playlist_id
            channel_name = _text(renderer.get("longBylineText"))
            description = _text(renderer.get("descriptionSnippet"))
            video_count = _parse_compact_number(_text(renderer.get("videoCount")) or "")

            results.append(
                SearchResult(
                    result_type="playlist",
                    title=title,
                    source_id=playlist_id,
                    archive_id=playlist_id,
                    channel_name=channel_name,
                    subscriber_count=None,
                    description=description,
                    video_count=video_count,
                    instance="youtube-html",
                )
            )
            if len(results) >= limit:
                break
        return results


class YtDlpBackend:
    """Search fallback backed by yt-dlp metadata."""

    name = "yt_dlp"

    def __init__(self, *, timeout_seconds: int, max_rounds: int):
        self.timeout_seconds = max(3, int(timeout_seconds))
        self.max_rounds = max(1, max_rounds)

    def _run_search(self, query: str, count: int) -> list[dict[str, Any]]:
        try:
            process = subprocess.run(
                [
                    "yt-dlp",
                    "--dump-single-json",
                    "--socket-timeout",
                    str(max(3, self.timeout_seconds // 2)),
                    "--retries",
                    "1",
                    "--extractor-retries",
                    "1",
                    f"ytsearch{max(1, count)}:{query}",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise SearchError("yt-dlp fallback timed out") from exc

        if process.returncode != 0:
            error_text = process.stderr.strip() or process.stdout.strip() or "yt-dlp failed"
            raise SearchError(f"yt-dlp fallback failed: {_sanitize_error(Exception(error_text))}")

        try:
            payload = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise SearchError(f"yt-dlp fallback returned invalid JSON: {exc}") from exc

        entries = payload.get("entries", []) if isinstance(payload, dict) else []
        return entries if isinstance(entries, list) else []

    def search_channels(self, query: str, limit: int) -> list[SearchResult]:
        entries: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        count = max(20, min(200, limit * 4))
        for _ in range(self.max_rounds):
            entries = self._run_search(query, count)
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                channel_id = str(
                    entry.get("channel_id")
                    or entry.get("uploader_id")
                    or entry.get("channel_url", "").rstrip("/").split("/")[-1]
                    or ""
                ).strip()
                if channel_id and channel_id.upper().startswith("UC"):
                    seen_ids.add(channel_id)
            if len(seen_ids) >= limit or count == 200:
                break
            count = min(200, count * 2)

        seen: set[str] = set()
        results: list[SearchResult] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            channel_id = str(
                entry.get("channel_id")
                or entry.get("uploader_id")
                or entry.get("channel_url", "").rstrip("/").split("/")[-1]
                or ""
            ).strip()
            if not channel_id or channel_id in seen:
                continue
            if not (channel_id.upper().startswith("UC") and len(channel_id) >= 3):
                continue

            channel_name = str(entry.get("channel") or entry.get("uploader") or channel_id)
            results.append(
                SearchResult(
                    result_type="channel",
                    title=channel_name.strip(),
                    source_id=channel_id,
                    archive_id=f"UU{channel_id[2:]}",
                    channel_name=channel_name.strip(),
                    subscriber_count=None,
                    description=str(entry.get("description") or "").strip(),
                    video_count=None,
                    instance="yt-dlp-fallback",
                )
            )
            seen.add(channel_id)
            if len(results) >= limit:
                break
        return results

    def search_playlists(self, query: str, limit: int) -> list[SearchResult]:
        _ = (query, limit)
        return []


class InvidiousSearchService:
    """Search orchestrator with ytfzf-style backend order fallback."""

    BACKEND_ALIASES: ClassVar[dict[str, str]] = {
        "invidious": "invidious",
        "youtube_html": "youtube_html",
        "youtube-html": "youtube_html",
        "yt_dlp": "yt_dlp",
        "yt-dlp": "yt_dlp",
        "ytdlp": "yt_dlp",
    }

    def __init__(self, config: Config):
        self.config = config
        self.max_results = int(config.get("search.max_results", 20))
        self.target_channel_candidates = int(
            config.get("search.target_channel_candidates", 60)
        )
        self.max_backend_rounds = int(config.get("search.max_backend_rounds", 2))
        self.last_backend_used: str | None = None
        self.backend_strict = bool(config.get("search.backend_strict", False))
        self.fallback_enabled = bool(config.get("search.fallback_enabled", False))
        self.fallback_on_error = bool(config.get("search.fallback_on_error", False))
        self.fallback_on_zero_results = bool(
            config.get("search.fallback_on_zero_results", False)
        )

        request_timeout = float(config.get("http.request_timeout", 30))
        connect_timeout = float(config.get("http.connect_timeout", 10))
        user_agent = str(config.get("http.user_agent", "")).strip()
        headers = {"User-Agent": user_agent} if user_agent else {}

        youtube_html_timeout = httpx.Timeout(
            timeout=float(config.get("search.youtube_html_timeout_seconds", 8)),
            connect=connect_timeout,
        )
        self._backends: dict[str, SearchBackend] = {
            "youtube_html": YouTubeHtmlBackend(timeout=youtube_html_timeout, headers=headers),
        }
        requested_order = self._load_backend_order(config)
        if "youtube_html" in requested_order:
            requested_order = ["youtube_html"] + [
                name for name in requested_order if name != "youtube_html"
            ]
        else:
            requested_order = ["youtube_html", *requested_order]

        if self.fallback_enabled:
            if "yt_dlp" in requested_order:
                self._backends["yt_dlp"] = YtDlpBackend(
                    timeout_seconds=int(config.get("search.yt_dlp_timeout_seconds", 20)),
                    max_rounds=self.max_backend_rounds,
                )
            if "invidious" in requested_order:
                inv_instances = self._load_instances(config)
                invidious_timeout = httpx.Timeout(
                    timeout=request_timeout,
                    connect=connect_timeout,
                )
                self._backends["invidious"] = InvidiousBackend(
                    instances=inv_instances,
                    timeout=invidious_timeout,
                    headers=headers,
                    max_rounds=self.max_backend_rounds,
                )
            self.backend_order = [name for name in requested_order if name in self._backends]
        else:
            self.backend_order = ["youtube_html"]

    @staticmethod
    def _load_instances(config: Config) -> list[str]:
        raw_instances = config.get("search.instances", [])
        if not isinstance(raw_instances, list):
            raise SearchError("Invalid search.instances configuration; expected list")
        cleaned = [str(item).strip().rstrip("/") for item in raw_instances if str(item).strip()]
        if not cleaned:
            raise SearchError("No Invidious instances configured in [search].instances")
        return cleaned

    def _load_backend_order(self, config: Config) -> list[str]:
        raw = config.get("search.backend_order", ["youtube_html"])
        if not isinstance(raw, list):
            raise SearchError("Invalid search.backend_order configuration; expected list")

        normalized: list[str] = []
        for value in raw:
            alias = self.BACKEND_ALIASES.get(str(value).strip().lower())
            if alias and alias not in normalized:
                normalized.append(alias)
        if not normalized:
            normalized = ["youtube_html"]
        return normalized

    def resolve_channel_uploads_playlist(self, channel_id: str) -> str:
        """Resolve known channel id to uploads playlist id."""
        value = channel_id.strip()
        if value.upper().startswith("UC") and len(value) >= 3:
            return f"UU{value[2:]}"
        raise SearchError(f"Unsupported channel id format: {channel_id}")

    def _execute_backend(
        self,
        backend: SearchBackend,
        query: str,
        limit: int,
        *,
        include_playlists: bool,
    ) -> list[SearchResult]:
        channels = backend.search_channels(query, limit)
        if channels:
            if include_playlists:
                playlists = backend.search_playlists(query, self.max_results)
                # Preserve channel pool size and append playlists as extra options.
                return channels[:limit] + playlists[: self.max_results]
            return channels[:limit]
        if include_playlists:
            return backend.search_playlists(query, limit)[:limit]
        return []

    def search(
        self,
        query: str,
        max_results: int | None = None,
        *,
        include_playlists: bool = False,
    ) -> list[SearchResult]:
        normalized = query.strip()
        if not normalized:
            raise SearchError("Search query cannot be empty")

        if max_results is None:
            limit = self.target_channel_candidates if not include_playlists else self.max_results
        else:
            limit = int(max_results)
        if limit <= 0:
            return []

        failures: list[str] = []
        for backend_name in self.backend_order:
            backend = self._backends[backend_name]
            try:
                results = self._execute_backend(
                    backend, normalized, limit, include_playlists=include_playlists
                )
            except SearchError as exc:
                failures.append(f"{backend_name}: {_sanitize_error(exc)}")
                if self.backend_strict:
                    raise SearchError(f"Search failed ({backend_name} strict): {_sanitize_error(exc)}") from exc
                if backend_name == "youtube_html" and not self.fallback_on_error:
                    break
                continue

            if results:
                self.last_backend_used = backend_name
                return results

            failures.append(f"{backend_name}: empty")
            if backend_name == "youtube_html" and not self.fallback_on_zero_results:
                break

        if not failures:
            return []
        only_empty = all(item.endswith(": empty") for item in failures)
        if only_empty:
            return []
        summary = "; ".join(failures)
        raise SearchError(f"Search failed across backends. {summary}")
