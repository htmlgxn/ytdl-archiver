"""Tests for browser cookie refresh support."""

import stat
from pathlib import Path

import pytest

from ytdl_archiver.core.cookies import BrowserCookieRefresher
from ytdl_archiver.exceptions import CookieRefreshError


class _DummyCookieJar:
    """Simple cookie jar stub used for testing save behavior."""

    def __init__(self, content: str):
        self.content = content

    def save(
        self,
        filename: str | None = None,
        ignore_discard: bool = True,
        ignore_expires: bool = True,
    ) -> None:
        del ignore_discard, ignore_expires
        if filename is None:
            raise RuntimeError("filename is required")
        Path(filename).write_text(self.content)


class TestBrowserCookieRefresher:
    """Test cases for BrowserCookieRefresher."""

    def test_refresh_to_file_success(self, temp_dir, mocker):
        """Test successful browser cookie refresh."""
        output_path = temp_dir / "cookies.txt"
        mocker.patch(
            "ytdl_archiver.core.cookies.extract_cookies_from_browser",
            return_value=_DummyCookieJar("# Netscape HTTP Cookie File\n"),
        )

        refresher = BrowserCookieRefresher()
        refresher.refresh_to_file("firefox", None, output_path)

        assert output_path.exists()
        assert output_path.read_text().startswith("# Netscape HTTP Cookie File")

    def test_refresh_to_file_replaces_existing_file_atomically(self, temp_dir, mocker):
        """Test refresh replaces existing cookie file content."""
        output_path = temp_dir / "cookies.txt"
        output_path.write_text("old-cookie-content\n")
        mocker.patch(
            "ytdl_archiver.core.cookies.extract_cookies_from_browser",
            return_value=_DummyCookieJar("# Netscape HTTP Cookie File\nnew-cookie\n"),
        )

        refresher = BrowserCookieRefresher()
        refresher.refresh_to_file("chrome", "Default", output_path)

        assert output_path.read_text() == "# Netscape HTTP Cookie File\nnew-cookie\n"
        assert not (temp_dir / ".cookies.txt.tmp").exists()

    def test_refresh_to_file_sets_permissions(self, temp_dir, mocker):
        """Test cookie file permissions are restricted."""
        output_path = temp_dir / "cookies.txt"
        mocker.patch(
            "ytdl_archiver.core.cookies.extract_cookies_from_browser",
            return_value=_DummyCookieJar("# Netscape HTTP Cookie File\n"),
        )

        refresher = BrowserCookieRefresher()
        refresher.refresh_to_file("edge", None, output_path)

        mode = stat.S_IMODE(output_path.stat().st_mode)
        assert mode == 0o600

    def test_refresh_to_file_extract_failure(self, temp_dir, mocker):
        """Test extraction failure raises deterministic exception."""
        output_path = temp_dir / "cookies.txt"
        mocker.patch(
            "ytdl_archiver.core.cookies.extract_cookies_from_browser",
            side_effect=RuntimeError("browser locked"),
        )

        refresher = BrowserCookieRefresher()
        with pytest.raises(CookieRefreshError, match="Failed to extract cookies"):
            refresher.refresh_to_file("firefox", None, output_path)

    def test_firefox_profile_name_resolves_to_profiles_ini_path(self, temp_dir, mocker):
        """Test firefox profile name resolves via profiles.ini hashed path."""
        root = temp_dir / "firefox"
        profile_dir = root / "ewth8420.default-release"
        profile_dir.mkdir(parents=True, exist_ok=True)
        (root / "profiles.ini").write_text(
            "\n".join(
                [
                    "[Install4F96D1932A9F858E]",
                    "Default=ewth8420.default-release",
                    "",
                    "[Profile0]",
                    "Name=default-release",
                    "IsRelative=1",
                    "Path=ewth8420.default-release",
                    "",
                    "[Profile1]",
                    "Name=default",
                    "IsRelative=1",
                    "Path=gtlo814o.default",
                    "Default=1",
                    "",
                ]
            )
            + "\n"
        )

        calls: list[str | None] = []

        def fake_extract(browser_name: str, profile: str | None = None):
            assert browser_name == "firefox"
            calls.append(profile)
            if profile == "default":
                raise FileNotFoundError("not found")
            if profile == str(root / "gtlo814o.default"):
                return _DummyCookieJar("# Netscape HTTP Cookie File\n")
            raise FileNotFoundError("not found")

        mocker.patch(
            "ytdl_archiver.core.cookies.extract_cookies_from_browser",
            side_effect=fake_extract,
        )

        refresher = BrowserCookieRefresher()
        mocker.patch.object(refresher, "_firefox_profile_roots", return_value=[root])

        output_path = temp_dir / "cookies.txt"
        refresher.refresh_to_file("firefox", "default", output_path)

        assert calls[0] == "default"
        assert str(root / "gtlo814o.default") in calls
        assert output_path.exists()

    def test_firefox_invalid_profile_falls_back_to_auto_discovery(
        self, temp_dir, mocker
    ):
        """Test invalid firefox profile token falls back to auto-discovery."""
        calls: list[str | None] = []

        def fake_extract(browser_name: str, profile: str | None = None):
            assert browser_name == "firefox"
            calls.append(profile)
            if profile == "does-not-exist":
                raise FileNotFoundError("no profile")
            if profile is None:
                return _DummyCookieJar("# Netscape HTTP Cookie File\n")
            raise FileNotFoundError("not found")

        mocker.patch(
            "ytdl_archiver.core.cookies.extract_cookies_from_browser",
            side_effect=fake_extract,
        )

        refresher = BrowserCookieRefresher()
        mocker.patch.object(refresher, "_firefox_profile_roots", return_value=[temp_dir])
        output_path = temp_dir / "cookies.txt"
        refresher.refresh_to_file("firefox", "does-not-exist", output_path)

        assert calls[:2] == ["does-not-exist", None]
        assert output_path.exists()

    def test_firefox_all_file_not_found_candidates_raise_deterministic_error(
        self, temp_dir, mocker
    ):
        """Test all file-not-found candidate failures raise deterministic error."""
        mocker.patch(
            "ytdl_archiver.core.cookies.extract_cookies_from_browser",
            side_effect=FileNotFoundError("not found in candidates"),
        )

        refresher = BrowserCookieRefresher()
        mocker.patch.object(refresher, "_firefox_profile_roots", return_value=[temp_dir])
        output_path = temp_dir / "cookies.txt"

        with pytest.raises(
            CookieRefreshError,
            match="attempted: requested:default, auto-discovery",
        ):
            refresher.refresh_to_file("firefox", "default", output_path)

    def test_firefox_non_path_error_fails_immediately(self, temp_dir, mocker):
        """Test non-FileNotFound firefox errors fail without fallback loop."""
        calls: list[str | None] = []

        def fake_extract(browser_name: str, profile: str | None = None):
            assert browser_name == "firefox"
            calls.append(profile)
            raise RuntimeError("sqlite unavailable")

        mocker.patch(
            "ytdl_archiver.core.cookies.extract_cookies_from_browser",
            side_effect=fake_extract,
        )

        refresher = BrowserCookieRefresher()
        output_path = temp_dir / "cookies.txt"

        with pytest.raises(
            CookieRefreshError,
            match="using requested:default",
        ):
            refresher.refresh_to_file("firefox", "default", output_path)

        assert calls == ["default"]
