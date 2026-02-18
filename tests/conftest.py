"""Pytest configuration and fixtures for ytdl-archiver tests."""

import sys
from pathlib import Path
from typing import Any

import pytest
import toml

# Add src directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for tests."""
    return tmp_path


@pytest.fixture
def temp_config_dir(temp_dir: Path) -> Path:
    """Create a temporary configuration directory."""
    config_dir = temp_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


@pytest.fixture
def sample_config(temp_dir: Path) -> dict[str, Any]:
    """Sample configuration dictionary for testing."""
    return {
        "archive": {
            "base_directory": str(temp_dir / "Videos" / "YouTube"),
            "delay_between_videos": 1,
            "delay_between_playlists": 5,
            "max_retries": 2,
            "retry_backoff_factor": 1.5,
        },
        "download": {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
            "merge_output_format": "mp4",
            "write_subtitles": True,
            "subtitle_format": "vtt",
            "convert_subtitles": "srt",
            "subtitle_languages": ["en"],
            "write_thumbnail": True,
            "thumbnail_format": "jpg",
            "max_concurrent_downloads": 1,
        },
        "shorts": {
            "detect_shorts": True,
            "shorts_subdirectory": "YouTube Shorts",
            "aspect_ratio_threshold": 0.7,
        },
        "logging": {
            "level": "INFO",
            "format": "json",
            "file_path": "~/.local/share/ytdl-archiver/logs/app.log",
            "max_file_size": "10MB",
            "backup_count": 5,
        },
        "http": {
            "user_agent": "Mozilla/5.0 (Test Agent)",
            "request_timeout": 30,
            "connect_timeout": 10,
        },
        "media_server": {
            "generate_nfo": True,
            "nfo_format": "kodi",
        },
    }


@pytest.fixture
def sample_config_file(temp_config_dir: Path, sample_config: dict[str, Any]) -> Path:
    """Create a sample configuration file."""
    config_file = temp_config_dir / "config.toml"
    with open(config_file, "w") as f:
        toml.dump(sample_config, f)
    return config_file


@pytest.fixture
def config(sample_config_file: Path):
    """Create a Config instance with sample configuration."""
    from ytdl_archiver.config.settings import Config

    return Config(sample_config_file)


@pytest.fixture
def sample_playlist_data() -> dict[str, Any]:
    """Sample playlist metadata from YouTube API."""
    return {
        "id": "PLOgg6_QCO8CeFd55aR1RgzSQOOWhR12uj",
        "title": "Test Playlist",
        "description": "A test playlist for ytdl-archiver",
        "uploader": "Test Channel",
        "uploader_id": "test_channel",
        "uploader_url": "https://www.youtube.com/channel/test",
        "webpage_url": "https://www.youtube.com/playlist?list=PLOgg6_QCO8CeFd55aR1RgzSQOOWhR12uj",
        "entries": [
            {
                "id": "test_video_1",
                "title": "Test Video 1",
                "description": "First test video",
                "uploader": "Test Channel",
                "duration": 300,
                "upload_date": "20240101",
                "webpage_url": "https://www.youtube.com/watch?v=test_video_1",
                "thumbnail": "https://img.youtube.com/vi/test_video_1/maxresdefault.jpg",
                "width": 1920,
                "height": 1080,
            },
            {
                "id": "test_video_2",
                "title": "Test Video 2 (Short)",
                "description": "Second test video - short format",
                "uploader": "Test Channel",
                "duration": 30,
                "upload_date": "20240102",
                "webpage_url": "https://www.youtube.com/watch?v=test_video_2",
                "thumbnail": "https://img.youtube.com/vi/test_video_2/maxresdefault.jpg",
                "width": 1080,
                "height": 1920,  # Vertical video (short)
            },
        ],
    }


@pytest.fixture
def sample_playlist_config() -> list[dict[str, Any]]:
    """Sample playlist configuration."""
    return [
        {
            "id": "PLOgg6_QCO8CeFd55aR1RgzSQOOWhR12uj",
            "name": "Test Playlist",
            "download_format": "best[height<=720]",
            "write_subtitles": False,
        }
    ]


@pytest.fixture
def archive_file(temp_dir: Path) -> Path:
    """Create a temporary archive file."""
    archive_file = temp_dir / ".archive.txt"
    archive_file.touch()
    return archive_file


@pytest.fixture
def archive_tracker(archive_file: Path):
    """Create an ArchiveTracker instance."""
    from ytdl_archiver.core.archive import ArchiveTracker

    return ArchiveTracker(archive_file)


@pytest.fixture
def mock_yt_dlp(mocker):
    """Mock yt-dlp module."""
    mock = mocker.patch("ytdl_archiver.core.downloader.yt_dlp")
    mock.YoutubeDL.return_value.extract_info.return_value = sample_playlist_data()
    return mock


@pytest.fixture
def downloader(config):
    """Create a YouTubeDownloader instance."""
    from ytdl_archiver.core.downloader import YouTubeDownloader

    return YouTubeDownloader(config)


@pytest.fixture
def metadata_generator(config):
    """Create a MetadataGenerator instance."""
    from ytdl_archiver.core.metadata import MetadataGenerator

    return MetadataGenerator(config)


@pytest.fixture
def playlist_archiver(config, temp_dir: Path):
    """Create a PlaylistArchiver instance."""
    from ytdl_archiver.core.archive import PlaylistArchiver

    return PlaylistArchiver(config, temp_dir)


@pytest.fixture
def mock_video_info() -> dict[str, Any]:
    """Mock video information for testing."""
    return {
        "id": "test_video_123",
        "title": "Test Video Title",
        "description": "This is a test video description",
        "uploader": "Test Channel Name",
        "duration": 300,
        "upload_date": "20240101",
        "webpage_url": "https://www.youtube.com/watch?v=test_video_123",
        "thumbnail": "https://img.youtube.com/vi/test_video_123/maxresdefault.jpg",
        "width": 1920,
        "height": 1080,
        "format": "137+140",
        "filesize": 50000000,
        "ext": "mp4",
        "acodec": "mp4a.40.2",
        "vcodec": "avc1.640028",
        "uploader_id": "test_channel_id",
        "uploader_url": "https://www.youtube.com/channel/test_channel_id",
        "like_count": 1000,
        "view_count": 50000,
        "tags": ["test", "video", "ytdl-archiver"],
        "categories": ["Technology"],
        "release_date": "20240101",
        "timestamp": 1704067200,  # 2024-01-01 00:00:00 UTC
    }


@pytest.fixture
def mock_short_video_info() -> dict[str, Any]:
    """Mock short video information for testing."""
    return {
        "id": "test_short_456",
        "title": "Test Short Video",
        "description": "This is a test short video",
        "uploader": "Test Channel Name",
        "duration": 30,
        "upload_date": "20240102",
        "webpage_url": "https://www.youtube.com/watch?v=test_short_456",
        "thumbnail": "https://img.youtube.com/vi/test_short_456/maxresdefault.jpg",
        "width": 1080,
        "height": 1920,  # Vertical aspect ratio
        "format": "137+140",
        "filesize": 10000000,
        "ext": "mp4",
        "acodec": "mp4a.40.2",
        "vcodec": "avc1.640028",
        "uploader_id": "test_channel_id",
        "uploader_url": "https://www.youtube.com/channel/test_channel_id",
        "like_count": 500,
        "view_count": 10000,
        "tags": ["short", "test"],
        "categories": ["Entertainment"],
        "release_date": "20240102",
        "timestamp": 1704153600,  # 2024-01-02 00:00:00 UTC
    }


# Test markers
pytest_plugins = []


# Add custom markers
def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")
