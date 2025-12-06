"""Configuration management for ytdl-archiver."""

from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
import toml
import json
from pathvalidate import sanitize_filename

from ..exceptions import ConfigurationError

logger = structlog.get_logger()


class Config:
    """Configuration manager for ytdl-archiver."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or self._get_default_config_path()
        self._config: Dict[str, Any] = {}
        self.load()

    def _get_default_config_path(self) -> Path:
        """Get default configuration file path."""
        return Path.home() / ".config" / "ytdl-archiver" / "config.toml"

    def load(self) -> None:
        """Load configuration from file with defaults."""
        # Load defaults
        defaults_path = Path(__file__).parent / "defaults.toml"
        try:
            self._config = toml.load(defaults_path)
        except Exception as e:
            raise ConfigurationError(f"Failed to load default configuration: {e}")

        # Override with user config if exists
        if self.config_path.exists():
            try:
                user_config = toml.load(self.config_path)
                self._merge_config(self._config, user_config)
                logger.info("Loaded user configuration", path=str(self.config_path))
            except Exception as e:
                logger.error("Failed to load user configuration", error=str(e))
                raise ConfigurationError(f"Failed to load user configuration: {e}")
        else:
            logger.info("No user configuration found, using defaults")

    def _merge_config(self, base: Dict[str, Any], override: Dict[str, Any]) -> None:
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

    def get_playlists_file(self) -> Path:
        """Get the playlists file path as Path object."""
        # Check for playlists.toml first (new format), then playlists.json (legacy)
        toml_file = Path("playlists.toml")
        json_file = Path("playlists.json")
        
        if toml_file.exists():
            return toml_file
        else:
            return json_file
    
    def load_playlists(self) -> List[Dict[str, Any]]:
        """Load playlists from file with playlist-specific overrides."""
        playlists_file = self.get_playlists_file()
        
        if not playlists_file.exists():
            raise ConfigurationError(f"Playlists file not found: {playlists_file}")
        
        try:
            if playlists_file.suffix.lower() == ".toml":
                with open(playlists_file, "r") as f:
                    playlists_data = toml.load(f)
                    return playlists_data.get("playlist", [])  # Changed from "playlists" to "playlist"
            else:
                with open(playlists_file, "r") as f:
                    playlists = json.load(f)
                    # Convert legacy format to new structure
                    return [{"id": p.get("id"), "path": p.get("path")} for p in playlists]
        except Exception as e:
            raise ConfigurationError(f"Failed to load playlists: {e}")
    
    def get_playlist_config(self, playlist_id: str) -> Dict[str, Any]:
        """Get merged configuration for a specific playlist."""
        playlists = self.load_playlists()
        
        # Find the playlist
        playlist_data = None
        for playlist in playlists:
            if playlist.get("id") == playlist_id:
                playlist_data = playlist
                break
        
        if not playlist_data:
            return {}
        
        # Start with global defaults
        merged_config = {}
        
        # Add global download settings
        for key in ["format", "merge_output_format", "writesubtitles", "subtitlesformat", 
                   "convertsubtitles", "subtitle_languages", "writethumbnail", 
                   "thumbnail_format"]:
            global_value = self.get(f"download.{key}")
            if global_value is not None:
                merged_config[key] = global_value
        
        # Override with playlist-specific settings
        playlist_overrides = playlist_data.get("download", {})
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

        logger.info("Configuration validated successfully")
