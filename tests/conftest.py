"""Test configuration and fixtures for ytdl-archiver tests."""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from ytdl_archiver.config.settings import Config


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


@pytest.fixture
def test_config(temp_dir):
    """Create a test configuration."""
    config_data = {
        "archive": {
            "base_directory": str(temp_dir / "archive"),
            "delay_between_videos": 0,
            "delay_between_playlists": 0,
        },
        "download": {
            "format": "worst",
            "write_subtitles": False,
            "write_thumbnail": False,
        },
        "logging": {
            "level": "DEBUG",
            "format": "console",
        },
        "shorts": {
            "detect_shorts": False,
        },
    }

    config = Mock(spec=Config)
    config.get.side_effect = lambda key, default=None: _get_nested_value(
        config_data, key, default
    )
    config.get_archive_directory.return_value = temp_dir / "archive"
    config.get_log_file_path.return_value = temp_dir / "test.log"
    return config


def _get_nested_value(data: dict, key: str, default=None):
    """Get nested value from dict using dot notation."""
    keys = key.split(".")
    value = data
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    return value


@pytest.fixture
def mock_youtube_video():
    """Mock YouTube video metadata."""
    return {
        "id": "dQw4w9WgXcQ",
        "title": "Never Gonna Give You Up",
        "uploader": "Rick Astley",
        "upload_date": "20091025",
        "description": 'Official music video for "Never Gonna Give You Up"',
        "duration": 212,
        "width": 1920,
        "height": 1080,
    }


@pytest.fixture
def mock_playlist_response():
    """Mock YouTube playlist response."""
    return {
        "id": "PLrAXtmRdnEQy4QG1qJwYtJZ3FQJp5K3J",
        "title": "Test Playlist",
        "entries": [
            {"id": "dQw4w9WgXcQ", "title": "Never Gonna Give You Up"},
            {"id": "9bZkp7q19f0", "title": "Gangnam Style"},
        ],
    }
