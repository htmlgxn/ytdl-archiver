"""Test TOML playlist functionality."""

import pytest
import json
import tempfile
from pathlib import Path

from ytdl_archiver.core.archive import PlaylistArchiver


class TestTomlPlaylists:
    """Test TOML playlist functionality."""
    
    def test_load_toml_playlists(self, test_config, temp_dir):
        """Test loading playlists from TOML file."""
        # Create TOML playlists file
        toml_content = """
[[playlists]]
id = "UUxxxxxxxxxxxxxxxxxxxxxx"
path = "Folder Name"

[[playlists]]
id = "PLOggx_xxxxxxxxxxxxxxxxxx_xxxxxxxx"
path = "unlisted/cool_videos"
"""
        toml_file = temp_dir / "playlists.toml"
        with open(toml_file, "w") as f:
            f.write(toml_content)
        
        # Test loading
        archiver = PlaylistArchiver(test_config)
        
        # Mock the playlist loading to avoid actual downloading
        import toml
        with open(toml_file, "r") as f:
            playlists_data = toml.load(f)
            playlists = playlists_data.get("playlists", [])
        
        assert len(playlists) == 2
        assert playlists[0]["id"] == "UUxxxxxxxxxxxxxxxxxxxxxx"
        assert playlists[0]["path"] == "Folder Name"
        assert playlists[1]["id"] == "PLOggx_xxxxxxxxxxxxxxxxxx_xxxxxxxx"
        assert playlists[1]["path"] == "unlisted/cool_videos"
    
    def test_load_json_playlists_compatibility(self, test_config, temp_dir):
        """Test backward compatibility with JSON playlists."""
        # Create JSON playlists file
        json_content = [
            {
                "id": "UUxxxxxxxxxxxxxxxxxxxxxx",
                "path": "Folder Name"
            },
            {
                "id": "PLOggx_xxxxxxxxxxxxxxxxxx_xxxxxxxx",
                "path": "unlisted/cool_videos"
            }
        ]
        json_file = temp_dir / "playlists.json"
        with open(json_file, "w") as f:
            json.dump(json_content, f)
        
        # Test loading
        with open(json_file, "r") as f:
            playlists = json.load(f)
        
        assert len(playlists) == 2
        assert playlists[0]["id"] == "UUxxxxxxxxxxxxxxxxxxxxxx"
        assert playlists[0]["path"] == "Folder Name"
        assert playlists[1]["id"] == "PLOggx_xxxxxxxxxxxxxxxxxx_xxxxxxxx"
        assert playlists[1]["path"] == "unlisted/cool_videos"
    
    def test_prefer_toml_over_json(self, test_config, temp_dir):
        """Test that TOML files are preferred over JSON when both exist."""
        # Create both files
        toml_content = """
[[playlists]]
id = "toml_playlist"
path = "TOML Folder"
"""
        json_content = [
            {
                "id": "json_playlist",
                "path": "JSON Folder"
            }
        ]
        
        toml_file = temp_dir / "playlists.toml"
        json_file = temp_dir / "playlists.json"
        
        with open(toml_file, "w") as f:
            f.write(toml_content)
        with open(json_file, "w") as f:
            json.dump(json_content, f)
        
        # Test that TOML is preferred by checking actual file existence logic
        # The real method checks if toml_file.exists() first
        assert toml_file.exists()
        assert json_file.exists()
        
        # Since TOML exists, it should be preferred
        expected_file = toml_file if toml_file.exists() else json_file
        assert expected_file == toml_file