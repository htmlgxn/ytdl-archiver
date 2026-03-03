"""Browser cookie refresh support."""

import configparser
import os
from pathlib import Path
from typing import Any

import structlog
from yt_dlp.cookies import extract_cookies_from_browser

from ..exceptions import CookieRefreshError

logger = structlog.get_logger()

SUPPORTED_BROWSERS = (
    "firefox",
    "chrome",
    "chromium",
    "brave",
    "edge",
    "opera",
    "vivaldi",
    "whale",
    "safari",
)


class BrowserCookieRefresher:
    """Refresh cookies from a browser into a Netscape cookie file."""

    def _is_path_like(self, value: str) -> bool:
        """Return True when a profile token looks like a filesystem path."""
        if value.startswith("~"):
            return True
        return any(sep in value for sep in (os.path.sep, os.path.altsep) if sep)

    def _firefox_profile_roots(self) -> list[Path]:
        """Get firefox profile roots in deterministic search order."""
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
        return [
            config_home / "mozilla/firefox",
            Path("~/.mozilla/firefox").expanduser(),
            Path("~/.var/app/org.mozilla.firefox/config/mozilla/firefox").expanduser(),
            Path("~/.var/app/org.mozilla.firefox/.mozilla/firefox").expanduser(),
            Path("~/snap/firefox/common/.mozilla/firefox").expanduser(),
        ]

    def _read_firefox_profiles_ini(
        self,
    ) -> tuple[list[dict[str, Any]], list[Path], list[Path]]:
        """Read profile metadata, install defaults, and default-marked profiles."""
        profiles: list[dict[str, Any]] = []
        install_defaults: list[Path] = []
        default_profiles: list[Path] = []

        for root in self._firefox_profile_roots():
            ini_path = root / "profiles.ini"
            if not ini_path.exists():
                continue

            parser = configparser.ConfigParser()
            parser.read(ini_path, encoding="utf-8")

            for section in parser.sections():
                data = parser[section]
                if section.startswith("Profile"):
                    raw_path = data.get("Path")
                    if not raw_path:
                        continue

                    is_relative = data.get("IsRelative", "1") == "1"
                    path = (
                        (root / raw_path).expanduser()
                        if is_relative
                        else Path(raw_path).expanduser()
                    )
                    profile_data = {
                        "name": data.get("Name", ""),
                        "path": path,
                    }
                    profiles.append(profile_data)
                    if data.get("Default", "0") == "1":
                        default_profiles.append(path)

                if section.startswith("Install"):
                    install_default = data.get("Default")
                    if install_default:
                        install_defaults.append((root / install_default).expanduser())

        return profiles, install_defaults, default_profiles

    def _dedupe_candidates(
        self, candidates: list[tuple[str | None, str]]
    ) -> list[tuple[str | None, str]]:
        """Remove duplicate candidate values while preserving order."""
        seen: set[str] = set()
        unique: list[tuple[str | None, str]] = []
        for value, label in candidates:
            key = "<auto>" if value is None else value
            if key in seen:
                continue
            seen.add(key)
            unique.append((value, label))
        return unique

    def _build_firefox_profile_candidates(
        self, profile: str | None
    ) -> list[tuple[str | None, str]]:
        """Build ordered firefox extraction candidates."""
        candidates: list[tuple[str | None, str]] = []

        if profile:
            candidates.append((profile, f"requested:{profile}"))
            if self._is_path_like(profile):
                expanded = str(Path(profile).expanduser())
                candidates.append((expanded, f"expanded-path:{expanded}"))
            else:
                token = profile.strip().lower()
                profiles, install_defaults, default_profiles = (
                    self._read_firefox_profiles_ini()
                )

                for item in profiles:
                    if item["name"].strip().lower() == token:
                        candidates.append(
                            (str(item["path"]), f"profiles.ini name:{item['name']}")
                        )
                for item in profiles:
                    if item["path"].name.strip().lower() == token:
                        candidates.append(
                            (
                                str(item["path"]),
                                f"profiles.ini path:{item['path'].name}",
                            )
                        )

                for install_path in install_defaults:
                    candidates.append(
                        (str(install_path), "profiles.ini install-default")
                    )
                for default_path in default_profiles:
                    candidates.append(
                        (str(default_path), "profiles.ini profile-default")
                    )

        candidates.append((None, "auto-discovery"))
        return self._dedupe_candidates(candidates)

    def _extract_firefox_cookie_jar(self, profile: str | None) -> tuple[Any, str]:
        """Extract firefox cookies using profile resolution and fallback logic."""
        candidates = self._build_firefox_profile_candidates(profile)
        logger.info(
            "Resolving firefox cookie profile",
            requested_profile=profile or "",
            candidates=[label for _, label in candidates],
        )

        last_not_found: FileNotFoundError | None = None
        attempted: list[str] = []

        for candidate, label in candidates:
            attempted.append(label)
            try:
                jar = extract_cookies_from_browser("firefox", profile=candidate)
                logger.info(
                    "Using firefox cookie profile",
                    requested_profile=profile or "",
                    source=label,
                )
                return jar, label
            except FileNotFoundError as e:
                last_not_found = e
                logger.debug(
                    "Firefox cookie candidate not found",
                    source=label,
                    error=str(e),
                )
                continue
            except (OSError, ValueError, RuntimeError, TypeError) as e:
                raise CookieRefreshError(
                    "Failed to extract cookies from browser 'firefox' "
                    f"using {label}: {e!s}"
                ) from e

        message = (
            "Failed to extract cookies from browser 'firefox' "
            f"(requested profile: {profile or '<none>'}; attempted: {', '.join(attempted)})"
        )
        if last_not_found is not None:
            message += f": {last_not_found!s}"
        raise CookieRefreshError(message)

    def refresh_to_file(
        self, browser: str, profile: str | None, output_path: Path
    ) -> None:
        """Extract browser cookies and atomically replace output file."""
        normalized_browser = browser.strip().lower()
        target_path = output_path.expanduser()
        logger.debug(
            "Cookie refresh starting",
            extra={
                "browser": normalized_browser,
                "profile": profile,
                "target_path": str(target_path),
                "target_absolute": str(target_path.absolute()),
            },
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = target_path.with_name(f".{target_path.name}.tmp")
        if temp_path.exists():
            temp_path.unlink()

        try:
            if normalized_browser == "firefox":
                cookie_jar, source = self._extract_firefox_cookie_jar(profile)
            else:
                cookie_jar = extract_cookies_from_browser(
                    normalized_browser,
                    profile=profile,
                )
                source = f"requested:{profile}" if profile else "auto-discovery"
        except CookieRefreshError:
            raise
        except (OSError, ValueError, RuntimeError, TypeError) as e:
            raise CookieRefreshError(
                f"Failed to extract cookies from browser '{normalized_browser}': {e!s}"
            ) from e

        try:
            cookie_jar.save(
                filename=str(temp_path),
                ignore_discard=True,
                ignore_expires=True,
            )
            temp_path.chmod(0o600)
            temp_path.replace(target_path)
            target_path.chmod(0o600)
            logger.info(
                "Refreshed cookies from browser",
                browser=normalized_browser,
                source=source,
                path=str(target_path),
            )
        except OSError as e:
            if temp_path.exists():
                temp_path.unlink()
            raise CookieRefreshError(
                f"Failed to write refreshed cookies to {target_path}: {e!s}"
            ) from e
