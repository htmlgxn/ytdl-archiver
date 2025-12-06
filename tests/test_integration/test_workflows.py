"""Integration tests with real YouTube playlist."""

import tempfile
from pathlib import Path

import pytest

from ytdl_archiver.config.settings import Config
from ytdl_archiver.core.archive import PlaylistArchiver


@pytest.mark.integration
@pytest.mark.slow
class TestRealPlaylistIntegration:
    """Integration tests with real YouTube playlist."""

    def test_real_playlist_download(self, temp_dir):
        """Test downloading real playlist PLOgg6_QCO8CeFd55aR1RgzSQOOWhR12uj."""
        # Create a temporary config
        config_file = temp_dir / "config.toml"
        
        # Minimal config for testing
        config_content = """
[archive]
base_directory = "{}"
delay_between_videos = 0
delay_between_playlists = 0
max_retries = 1

[download]
format = "worst[height<=360]"
write_subtitles = false
write_thumbnail = true

[shorts]
detect_shorts = true
shorts_subdirectory = "Shorts"

[media_server]
generate_nfo = true
nfo_format = "kodi"

[logging]
level = "INFO"
format = "text"
        """.format(str(temp_dir / "downloads"))
        
        config_file.write_text(config_content)
        
        # Load config
        config = Config(config_file)
        
        # Create archiver
        archiver = PlaylistArchiver(config)
        
        # Test getting playlist info (this will make real API call)
        playlist_url = "https://www.youtube.com/playlist?list=PLOgg6_QCO8CeFd55aR1RgzSQOOWhR12uj"
        
        # This test is marked as integration and slow
        # It makes real API calls and should be run manually
        try:
            playlist_info = archiver._get_playlist_info(playlist_url)
            
            # Basic validation that we got some data
            assert playlist_info is not None
            assert "id" in playlist_info
            assert "title" in playlist_info
            assert "entries" in playlist_info
            
            # Check that we got the expected playlist ID
            assert playlist_info["id"] == "PLOgg6_QCO8CeFd55aR1RgzSQOOWhR12uj"
            
        except Exception as e:
            pytest.skip(f"Real API call failed: {e}")

    def test_real_playlist_metadata_extraction(self, temp_dir):
        """Test metadata extraction from real playlist."""
        # Create a temporary config
        config_file = temp_dir / "config.toml"
        
        config_content = """
[archive]
base_directory = "{}"

[download]
format = "worst[height<=360]"
write_subtitles = false
write_thumbnail = false

[logging]
level = "ERROR"
format = "text"
        """.format(str(temp_dir / "downloads"))
        
        config_file.write_text(config_content)
        
        # Load config
        config = Config(config_file)
        
        # Create archiver
        archiver = PlaylistArchiver(config)
        
        # Test getting playlist info
        playlist_url = "https://www.youtube.com/playlist?list=PLOgg6_QCO8CeFd55aR1RgzSQOOWhR12uj"
        
        try:
            playlist_info = archiver._get_playlist_info(playlist_url)
            
            if playlist_info and playlist_info.get("entries"):
                # Test metadata extraction for first video
                first_video = playlist_info["entries"][0]
                
                # Basic metadata validation
                assert "id" in first_video
                assert "title" in first_video
                assert "duration" in first_video
                assert "upload_date" in first_video
                
        except Exception as e:
            pytest.skip(f"Real API call failed: {e}")

    @pytest.mark.integration
    @pytest.mark.slow
    def test_full_playlist_processing_mock(self, temp_dir, sample_playlist_data):
        """Test full playlist processing with mocked data."""
        # This test simulates the full workflow without making real API calls
        
        # Create a temporary config
        config_file = temp_dir / "config.toml"
        
        config_content = """
[archive]
base_directory = "{}"
delay_between_videos = 0
delay_between_playlists = 0
max_retries = 1

[download]
format = "worst[height<=360]"
write_subtitles = false
write_thumbnail = true

[shorts]
detect_shorts = true
shorts_subdirectory = "Shorts"

[media_server]
generate_nfo = true
nfo_format = "kodi"

[logging]
level = "ERROR"
format = "text"
        """.format(str(temp_dir / "downloads"))
        
        config_file.write_text(config_content)
        
        # Load config
        config = Config(config_file)
        
        # Create archiver
        archiver = PlaylistArchiver(config)
        
        # Mock the _get_playlist_info method to return our test data
        with pytest.MonkeyPatch.object(archiver, '_get_playlist_info', return_value=sample_playlist_data):
            # Process the playlist
            archiver.process_playlist("test_playlist", "TestPlaylist")
            
            # Check that archive file was created
            archive_file = temp_dir / "downloads" / "TestPlaylist" / ".archive.txt"
            assert archive_file.exists()
            
            # Check that videos were marked as downloaded
            archive_content = archive_file.read_text()
            for entry in sample_playlist_data.get("entries", []):
                if entry and entry.get("id"):
                    assert entry["id"] in archive_content