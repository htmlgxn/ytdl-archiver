"""Tests for configuration settings."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import toml

from ytdl_archiver.config.settings import Config
from ytdl_archiver.exceptions import ConfigurationError


class TestConfig:
    """Test cases for Config class."""

    def test_load_default_config(self, temp_config_dir):
        """Test loading default configuration."""
        # Create config with no user config file
        config_path = temp_config_dir / "nonexistent.toml"
        config = Config(config_path)
        
        # Test that default values are loaded
        assert config.get("archive.base_directory") == "~/Videos/YouTube"
        assert config.get("download.format") == "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4"
        assert config.get("logging.level") == "INFO"

    def test_load_user_config(self, sample_config_file):
        """Test loading user configuration overrides."""
        config = Config(sample_config_file)
        
        # Test that user config values are loaded
        assert config.get("http.user_agent") == "Mozilla/5.0 (Test Agent)"
        assert config.get("archive.delay_between_videos") == 1

    def test_config_merge(self, temp_config_dir):
        """Test configuration merging logic."""
        # Create a partial user config
        user_config = {
            "archive": {
                "delay_between_videos": 5,
                "new_setting": "test_value"
            },
            "new_section": {
                "new_key": "new_value"
            }
        }
        
        config_file = temp_config_dir / "config.toml"
        with open(config_file, "w") as f:
            toml.dump(user_config, f)
        
        config = Config(config_file)
        
        # Test that defaults are preserved
        assert config.get("archive.base_directory") == "~/Videos/YouTube"
        
        # Test that user overrides are applied
        assert config.get("archive.delay_between_videos") == 5
        assert config.get("archive.new_setting") == "test_value"
        assert config.get("new_section.new_key") == "new_value"

    def test_get_nested_config(self, sample_config_file):
        """Test getting nested configuration values."""
        config = Config(sample_config_file)
        
        # Test nested access
        assert config.get("download.subtitle_languages") == ["en"]
        assert config.get("shorts.aspect_ratio_threshold") == 0.7
        assert config.get("media_server.nfo_format") == "kodi"

    def test_get_nonexistent_key(self, sample_config_file):
        """Test getting non-existent configuration keys."""
        config = Config(sample_config_file)
        
        # Test non-existent key returns None
        assert config.get("nonexistent.key") is None
        
        # Test with default value
        assert config.get("nonexistent.key", "default") == "default"

    def test_invalid_toml_file(self, temp_config_dir):
        """Test handling of invalid TOML files."""
        # Create invalid TOML file
        config_file = temp_config_dir / "invalid.toml"
        with open(config_file, "w") as f:
            f.write("invalid toml content [")
        
        with pytest.raises(ConfigurationError, match="Failed to load user configuration"):
            Config(config_file)

    def test_missing_default_config(self, mocker):
        """Test handling of missing default configuration file."""
        # Mock the defaults path to non-existent file
        mock_path = mocker.patch("ytdl_archiver.config.settings.Path")
        mock_path.return_value = Path("/nonexistent/defaults.toml")
        
        with pytest.raises(ConfigurationError, match="Failed to load default configuration"):
            Config()

    def test_config_path_expansion(self, temp_dir):
        """Test configuration path expansion."""
        config = Config()
        
        # Test that paths are expanded using the helper methods
        base_dir = config.get_archive_directory()
        assert str(base_dir).startswith(str(Path.home()))
        
        log_path = config.get_log_file_path()
        assert str(log_path).startswith(str(Path.home()))

    def test_playlist_config_override(self, temp_config_dir):
        """Test playlist-specific configuration overrides."""
        # Create a playlists file with overrides
        playlists_config = [
            {
                "id": "test_playlist_id",
                "name": "Test Playlist",
                "download": {
                    "format": "best[height<=480]",
                    "write_subtitles": True
                }
            }
        ]
        
        playlists_file = temp_config_dir / "playlists.toml"
        with open(playlists_file, "w") as f:
            toml.dump({"playlist": playlists_config}, f)
        
        # Create config that points to this playlists file
        config = Config()
        
        # Mock the playlists file path
        config.get_playlists_file = lambda: playlists_file
        
        # Test playlist override
        playlist_config = config.get_playlist_config("test_playlist_id")
        assert playlist_config["format"] == "best[height<=480]"
        assert playlist_config["write_subtitles"] is True

    def test_get_playlist_config_nonexistent(self, sample_config_file):
        """Test getting config for non-existent playlist."""
        config = Config(sample_config_file)
        
        # Should return empty dict for non-existent playlist
        playlist_config = config.get_playlist_config("nonexistent_playlist")
        assert playlist_config == {}

    def test_config_validation(self, temp_config_dir):
        """Test configuration validation."""
        # Test invalid delay values
        invalid_config = {
            "archive": {
                "delay_between_videos": -1,  # Invalid negative delay
                "max_retries": "not_a_number"  # Invalid type
            }
        }
        
        config_file = temp_config_dir / "invalid.toml"
        with open(config_file, "w") as f:
            toml.dump(invalid_config, f)
        
        # Config should still load, validation happens at usage
        config = Config(config_file)
        assert config.get("archive.delay_between_videos") == -1
        assert config.get("archive.max_retries") == "not_a_number"

    def test_config_file_permissions(self, temp_config_dir):
        """Test handling of unreadable config files."""
        config_file = temp_config_dir / "unreadable.toml"
        
        # Create a file and make it unreadable
        config_file.write_text("test = 'value'")
        config_file.chmod(0o000)  # Remove all permissions
        
        try:
            with pytest.raises(ConfigurationError):
                Config(config_file)
        finally:
            # Restore permissions for cleanup
            config_file.chmod(0o644)

    def test_empty_config_file(self, temp_config_dir):
        """Test handling of empty configuration files."""
        config_file = temp_config_dir / "empty.toml"
        config_file.touch()  # Create empty file
        
        config = Config(config_file)
        
        # Should load defaults when user config is empty
        assert config.get("archive.base_directory") == "~/Videos/YouTube"

    def test_config_with_comments(self, temp_config_dir):
        """Test loading TOML files with comments."""
        config_content = """
# This is a comment
[archive]
base_directory = "~/Custom/Videos"  # Inline comment

[download]
format = "best[height<=1080]"
# Subtitles disabled for testing
write_subtitles = false
"""
        
        config_file = temp_config_dir / "with_comments.toml"
        config_file.write_text(config_content)
        
        config = Config(config_file)
        
        assert config.get("archive.base_directory") == "~/Custom/Videos"
        assert config.get("download.format") == "best[height<=1080]"
        assert config.get("download.write_subtitles") is False

    def test_config_reload(self, sample_config_file):
        """Test configuration reloading."""
        config = Config(sample_config_file)
        
        # Initial load
        assert config.get("archive.delay_between_videos") == 1
        
        # Modify config file
        modified_config = {
            "archive": {
                "delay_between_videos": 10
            }
        }
        with open(sample_config_file, "w") as f:
            toml.dump(modified_config, f)
        
        # Reload config
        config.load()
        
        # Should reflect new values
        assert config.get("archive.delay_between_videos") == 10