"""Configuration management for ytdl-archiver."""

import json
import shutil
from pathlib import Path
from typing import Any

import structlog
import toml

from ..exceptions import ConfigurationError

logger = structlog.get_logger()


class Config:
    """Configuration manager for ytdl-archiver."""

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or self.default_config_path()
        self._config: dict[str, Any] = {}

        self.load()

    def migrate_playlists_from_cwd(self) -> Path | None:
        """Migrate legacy playlists file from CWD into config directory.

        Migration runs only when a config-dir playlists TOML file does not already exist.
        Returns the destination path when a move occurred, else None.
        """
        cwd_toml = Path("playlists.toml")
        cwd_json = Path("playlists.json")
        config_dir = self.config_path.parent
        config_toml = config_dir / "playlists.toml"

        if not (cwd_toml.exists() or cwd_json.exists()):
            return None
        if config_toml.exists():
            return None

        config_dir.mkdir(parents=True, exist_ok=True)
        if cwd_toml.exists():
            destination = config_toml
            shutil.move(str(cwd_toml), str(destination))
            logger.info(
                "Migrated playlists.toml to config directory",
                extra={"from_path": str(cwd_toml), "to_path": str(destination)},
            )
            return destination
        if cwd_json.exists():
            destination = config_dir / "playlists.json"
            shutil.move(str(cwd_json), str(destination))
            logger.info(
                "Migrated playlists.json to config directory",
                extra={"from_path": str(cwd_json), "to_path": str(destination)},
            )
            return destination
        return None

    @staticmethod
    def default_config_path() -> Path:
        """Get default configuration file path."""
        return Path.home() / ".config" / "ytdl-archiver" / "config.toml"

    def load(self) -> None:
        """Load configuration from file with defaults."""
        # Load defaults
        defaults_path = Path(__file__).parent / "defaults.toml"
        try:
            self._config = toml.load(defaults_path)
        except (toml.TomlDecodeError, OSError) as e:
            raise ConfigurationError(
                f"Failed to load default configuration: {e}"
            ) from e

        # Override with user config if exists
        if self.config_path.exists():
            try:
                user_config = toml.load(self.config_path)
                self._merge_config(self._config, user_config)
                logger.info(
                    "Loaded user configuration", extra={"path": str(self.config_path)}
                )
            except (toml.TomlDecodeError, OSError) as e:
                logger.exception(
                    "Failed to load user configuration", extra={"error": str(e)}
                )
                raise ConfigurationError(
                    f"Failed to load user configuration: {e}"
                ) from e
        else:
            logger.info("No user configuration found, using defaults")

    def _merge_config(self, base: dict[str, Any], override: dict[str, Any]) -> None:
        """Recursively merge configuration dictionaries."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value using dot notation."""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def get_archive_directory(self) -> Path:
        """Get the archive directory as Path object."""
        path_str = self.get("archive.base_directory", "~/Videos/YouTube")
        return Path(path_str).expanduser()

    def get_log_file_path(self) -> Path:
        """Get the log file path as Path object."""
        path_str = self.get(
            "logging.file_path", "~/.local/share/ytdl-archiver/logs/app.log"
        )
        return Path(path_str).expanduser()

    def get_cookie_file_path(self) -> Path | None:
        """Get the cookie file path as Path object, or None if not configured."""
        cookie_path = self.get("http.cookie_file")
        if not cookie_path:
            return None
        path = Path(cookie_path).expanduser()
        return path if path.exists() else None

    def get_cookie_file_target_path(self) -> Path:
        """Get configured cookie file target path even if it does not exist."""
        cookie_path = self.get("http.cookie_file", "~/cookies.txt")
        return Path(str(cookie_path)).expanduser()

    def get_playlists_file(self) -> Path:
        """Get the playlists file path in the config directory."""
        override = self.get("playlists_file")
        if override:
            if isinstance(override, Path):
                return override.expanduser()
            return Path(str(override)).expanduser()

        config_dir = self.config_path.parent
        toml_file = config_dir / "playlists.toml"
        json_file = config_dir / "playlists.json"  # Legacy support

        if toml_file.exists():
            return toml_file
        if json_file.exists():
            return json_file
        return toml_file  # Default to TOML for new installations

    def set_playlists_file(self, playlists_file: Path) -> None:
        """Set an explicit playlists file override."""
        self._config["playlists_file"] = str(playlists_file.expanduser())

    def set_archive_directory(self, directory: Path | str) -> None:
        """Set the archive base directory."""
        archive_config = self._config.setdefault("archive", {})
        archive_config["base_directory"] = str(Path(directory).expanduser())

    def set_logging_level(self, level: str) -> None:
        """Set the logging level."""
        logging_config = self._config.setdefault("logging", {})
        logging_config["level"] = level.upper()

    def as_dict(self) -> dict[str, Any]:
        """Return the full merged configuration dictionary."""
        return self._config

    def ensure_playlists_file(self) -> None:
        """Create a skeleton playlists.toml file if it doesn't exist."""
        playlists_file = self.get_playlists_file()

        if not playlists_file.exists():
            skeleton = """# YouTube playlists to archive
# Format: each playlist needs an id (from URL) and path (relative to archive directory)

[[playlists]]
id = "YOUR_PLAYLIST_ID_HERE"
path = "My Playlist"

# Example with playlist-specific overrides:
# [[playlists]]
# id = "UC_x5XG1OV2P6uZZ5FSM9Ttw"
# path = "Google Developers"
# [playlists.download]
# format = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
# write_subtitles = true
# subtitle_languages = ["en", "es"]
"""
            playlists_file.parent.mkdir(parents=True, exist_ok=True)
            playlists_file.write_text(skeleton.strip() + "\n")
            logger.info(
                "Created skeleton playlists file", extra={"path": str(playlists_file)}
            )

    def load_playlists(self) -> list[dict[str, Any]]:
        """Load playlists from file with playlist-specific overrides."""
        playlists_file = self.get_playlists_file()

        if not playlists_file.exists():
            # Try to be helpful before failing
            self.ensure_playlists_file()
            raise ConfigurationError(
                f"Playlists file not found. A skeleton file has been created at {playlists_file}. "
                "Please edit it with your playlist IDs and paths."
            )

        try:
            if playlists_file.suffix.lower() == ".toml":
                with playlists_file.open(encoding="utf-8") as f:
                    playlists_data = toml.load(f)
                    return playlists_data.get("playlists", [])
            else:
                # Legacy JSON handling...
                with playlists_file.open(encoding="utf-8") as f:
                    playlists = json.load(f)
                    return [
                        {"id": p.get("id"), "path": p.get("path")} for p in playlists
                    ]
        except (toml.TomlDecodeError, json.JSONDecodeError, OSError) as e:
            raise ConfigurationError(f"Failed to load playlists: {e}") from e

    def get_playlist_config(
        self, playlist_id: str, playlist_path: str | None = None
    ) -> dict[str, Any]:
        """Get merged configuration for a specific playlist."""
        playlists = self.load_playlists()

        # Find the playlist; prefer exact (id, path) match when path is available.
        matches = [
            playlist for playlist in playlists if playlist.get("id") == playlist_id
        ]
        if not matches:
            return {}

        playlist_data = matches[0]
        if playlist_path is not None:
            for playlist in matches:
                if playlist.get("path") == playlist_path:
                    playlist_data = playlist
                    break

        # Start with global defaults using canonical keys.
        merged_config: dict[str, Any] = {}
        download_aliases = {
            "format": ("format",),
            "merge_output_format": ("merge_output_format",),
            "write_info_json": ("write_info_json", "writeinfojson"),
            "write_max_metadata_json": ("write_max_metadata_json",),
            "write_subtitles": ("write_subtitles", "writesubtitles"),
            "embed_subtitles": ("embed_subtitles", "embedsubtitles"),
            "subtitle_format": ("subtitle_format", "subtitlesformat"),
            "convert_subtitles": ("convert_subtitles", "convertsubtitles"),
            "subtitle_languages": ("subtitle_languages", "subtitleslangs"),
            "write_thumbnail": ("write_thumbnail", "writethumbnail"),
            "thumbnail_format": ("thumbnail_format",),
        }
        for canonical_key, aliases in download_aliases.items():
            for alias in aliases:
                global_value = self.get(f"download.{alias}")
                if global_value is not None:
                    merged_config[canonical_key] = global_value
                    break

        # Override with playlist-specific settings (normalize alias keys first)
        playlist_overrides_raw = playlist_data.get("download", {})
        playlist_overrides: dict[str, Any] = dict(playlist_overrides_raw)
        for canonical_key, aliases in download_aliases.items():
            for alias in aliases:
                if alias in playlist_overrides_raw:
                    playlist_overrides[canonical_key] = playlist_overrides_raw[alias]
        merged_config.update(playlist_overrides)

        return merged_config

    def validate(self) -> None:
        """Validate configuration settings."""
        # Validate archive directory
        archive_dir = self.get_archive_directory()
        if not archive_dir.parent.exists():
            raise ConfigurationError(
                f"Archive parent directory does not exist: {archive_dir.parent}"
            )

        # Validate logging configuration
        log_level = self.get("logging.level", "INFO")
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if log_level.upper() not in valid_levels:
            raise ConfigurationError(
                f"Invalid log level: {log_level}. Valid levels: {valid_levels}"
            )

        # Validate download format
        download_format = self.get("download.format")
        if not download_format:
            raise ConfigurationError("Download format cannot be empty")

        for key in ("download.write_info_json", "download.write_max_metadata_json"):
            value = self.get(key)
            if not isinstance(value, bool):
                raise ConfigurationError(
                    f"Invalid {key} value; expected true or false"
                )

        # Validate cookie refresh settings
        cookie_source = str(self.get("cookies.source", "manual_file")).lower()
        valid_sources = {"manual_file", "browser"}
        if cookie_source not in valid_sources:
            raise ConfigurationError(
                f"Invalid cookies.source: {cookie_source}. Valid values: {sorted(valid_sources)}"
            )

        refresh_on_startup = self.get("cookies.refresh_on_startup", True)
        if not isinstance(refresh_on_startup, bool):
            raise ConfigurationError(
                "Invalid cookies.refresh_on_startup value; expected true or false"
            )

        if cookie_source == "browser":
            from ..core.cookies import SUPPORTED_BROWSERS

            browser = self.get("cookies.browser")
            if not browser:
                raise ConfigurationError(
                    "cookies.browser is required when cookies.source is 'browser'"
                )
            browser_value = str(browser).lower()
            if browser_value not in SUPPORTED_BROWSERS:
                raise ConfigurationError(
                    f"Invalid cookies.browser: {browser_value}. "
                    f"Valid values: {list(SUPPORTED_BROWSERS)}"
                )

        # Validate filename formatting settings
        valid_tokens = {"title", "channel", "upload_date", "video_id"}
        tokens = self.get("filename.tokens", ["title", "channel"])
        if not isinstance(tokens, list) or not tokens:
            raise ConfigurationError(
                "filename.tokens must be a non-empty list of token names"
            )
        if len(tokens) != len(set(tokens)):
            raise ConfigurationError("filename.tokens cannot contain duplicates")
        unknown_tokens = [token for token in tokens if token not in valid_tokens]
        if unknown_tokens:
            raise ConfigurationError(
                f"Invalid filename token(s): {unknown_tokens}. "
                f"Valid values: {sorted(valid_tokens)}"
            )

        token_joiner = str(self.get("filename.token_joiner", "_"))
        if not token_joiner.strip():
            raise ConfigurationError("filename.token_joiner cannot be empty")
        if "/" in token_joiner or "\\" in token_joiner:
            raise ConfigurationError(
                "filename.token_joiner cannot contain path separators"
            )

        # Legacy compatibility: this key is no longer used.
        legacy_date_separator = self.get("filename.date_separator")
        if legacy_date_separator is not None:
            logger.warning(
                "Ignoring deprecated filename.date_separator; use filename.date_format"
            )

        missing_behavior = str(self.get("filename.missing_token_behavior", "omit"))
        if missing_behavior != "omit":
            raise ConfigurationError(
                "Invalid filename.missing_token_behavior: "
                f"{missing_behavior}. Valid values: ['omit']"
            )

        date_format = str(self.get("filename.date_format", "yyyy-mm-dd"))
        valid_date_formats = {"yyyy-mm-dd", "yyyymmdd", "yyyy_mm_dd", "yyyy.mm.dd"}
        if date_format not in valid_date_formats:
            raise ConfigurationError(
                "Invalid filename.date_format: "
                f"{date_format}. Valid values: {sorted(valid_date_formats)}"
            )

        case_map = self.get("filename.case", {}) or {}
        valid_case_modes = {"preserve", "lower", "upper", "title"}
        if not isinstance(case_map, dict):
            raise ConfigurationError("filename.case must be a table")
        for token in valid_tokens:
            mode = str(case_map.get(token, "preserve"))
            if mode not in valid_case_modes:
                raise ConfigurationError(
                    f"Invalid filename.case.{token}: {mode}. "
                    f"Valid values: {sorted(valid_case_modes)}"
                )

        logger.info("Configuration validated successfully")
