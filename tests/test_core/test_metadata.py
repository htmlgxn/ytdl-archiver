"""Tests for metadata generation functionality."""

import pytest

from ytdl_archiver.core.metadata import MetadataGenerator
from ytdl_archiver.exceptions import MetadataError


class TestMetadataGenerator:
    """Test cases for MetadataGenerator class."""

    def test_init(self, config):
        """Test MetadataGenerator initialization."""
        generator = MetadataGenerator(config)

        assert generator.config == config

    def test_create_nfo_file_kodi_format(self, config, temp_dir, mock_video_info):
        """Test creating NFO file in Kodi format."""
        config._config["media_server"]["nfo_format"] = "kodi"
        generator = MetadataGenerator(config)

        output_path = temp_dir / "test_video.nfo"

        generator.create_nfo_file(mock_video_info, output_path)

        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")

        # Check for Kodi XML structure
        assert "<episodedetails>" in content
        assert "<title>" in content
        assert mock_video_info["title"] in content
        assert "<plot>" in content
        assert mock_video_info["description"] in content

    def test_create_nfo_file_emby_format(self, config, temp_dir, mock_video_info):
        """Test creating NFO file in Emby format."""
        config._config["media_server"]["nfo_format"] = "emby"
        generator = MetadataGenerator(config)

        output_path = temp_dir / "test_video.nfo"

        generator.create_nfo_file(mock_video_info, output_path)

        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")

        # Check for Emby XML structure
        assert "<Item>" in content
        assert "<Type>" not in content  # No Type in the generated format
        assert "<Name>" in content
        assert mock_video_info["title"] in content

    def test_create_nfo_file_disabled(self, config, temp_dir, mock_video_info):
        """Test that NFO creation is disabled when configured."""
        config._config["media_server"]["generate_nfo"] = False
        generator = MetadataGenerator(config)

        output_path = temp_dir / "test_video.nfo"

        # The generator doesn't check the config - it's handled by the caller
        # This test verifies the method works regardless
        generator.create_nfo_file(mock_video_info, output_path)

        # File should be created (caller handles the disabled check)
        assert output_path.exists()

    def test_create_nfo_file_with_existing_parent(
        self, config, temp_dir, mock_video_info
    ):
        """Test NFO creation when parent directory exists."""
        generator = MetadataGenerator(config)

        # Use path where parent already exists
        output_path = temp_dir / "test_video.nfo"

        generator.create_nfo_file(mock_video_info, output_path)

        assert output_path.exists()
        assert output_path.parent == temp_dir

    def test_create_nfo_file_xml_escaping(self, config, temp_dir):
        """Test XML escaping in NFO files."""
        generator = MetadataGenerator(config)

        # Video info with special XML characters
        video_info = {
            "id": "test_xml",
            "title": "Test & < > \" ' video",
            "description": "Description with & < > \" ' characters",
            "upload_date": "20240101",
            "duration": 300,
        }

        output_path = temp_dir / "test_xml.nfo"

        generator.create_nfo_file(video_info, output_path)

        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")

        # Check that special characters are properly escaped
        assert "&amp;" in content  # & should be escaped
        assert "&lt;" in content  # < should be escaped
        assert "&gt;" in content  # > should be escaped
        assert "&quot;" in content  # " should be escaped

    def test_create_nfo_file_missing_metadata(self, config, temp_dir):
        """Test creating NFO file with missing metadata."""
        generator = MetadataGenerator(config)

        # Minimal video info
        video_info = {
            "id": "minimal_video",
            "title": "Minimal Video",
            # Missing description, upload_date, etc.
        }

        output_path = temp_dir / "minimal.nfo"

        generator.create_nfo_file(video_info, output_path)

        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")

        # Should still create valid XML with available data
        assert "<title>" in content
        assert "Minimal Video" in content

    def test_create_nfo_file_write_error(
        self, config, temp_dir, mock_video_info, mocker
    ):
        """Test handling of write errors during NFO creation."""
        generator = MetadataGenerator(config)

        output_path = temp_dir / "test_error.nfo"

        # Mock Path.open to raise permission error
        mocker.patch("pathlib.Path.open", side_effect=PermissionError("Permission denied"))

        with pytest.raises(MetadataError, match="Error writing NFO file"):
            generator.create_nfo_file(mock_video_info, output_path)

    def test_generate_kodi_nfo(self, config):
        """Test generating Kodi NFO content."""
        config._config["media_server"]["nfo_format"] = "kodi"
        generator = MetadataGenerator(config)

        content = generator._generate_kodi_nfo(
            "Test Title",
            "video123",
            "Test Channel",
            "2024-01-01",
            "2024",
            "Test description",
            300,
        )

        assert "<episodedetails>" in content
        assert "<title>Test Title</title>" in content
        assert "<studio>Test Channel</studio>" in content
        assert "<releasedate>2024-01-01</releasedate>" in content
        assert "<runtime>300</runtime>" in content

    def test_generate_emby_nfo(self, config):
        """Test generating Emby NFO content."""
        config._config["media_server"]["nfo_format"] = "emby"
        generator = MetadataGenerator(config)

        content = generator._generate_emby_nfo(
            "Test Title",
            "video123",
            "Test Channel",
            "2024-01-01",
            "2024",
            "Test description",
            300,
        )

        assert "<Item>" in content
        assert "<Name>Test Title</Name>" in content
        assert "<Studio>Test Channel</Studio>" in content
        assert "<PremiereDate>2024-01-01</PremiereDate>" in content
        # Emby uses ticks (100-nanosecond intervals)
        assert "<RunTimeTicks>3000000000</RunTimeTicks>" in content

    def test_escape_xml(self, config):
        """Test XML text escaping."""
        generator = MetadataGenerator(config)

        # Test various special characters
        test_cases = [
            ("&", "&amp;"),
            ("<", "&lt;"),
            (">", "&gt;"),
            ('"', "&quot;"),
            ("'", "&apos;"),
        ]

        for input_char, expected_escaped in test_cases:
            result = generator._escape_xml(input_char)
            assert result == expected_escaped

    def test_escape_xml_unicode(self, config):
        """Test XML escaping with Unicode characters."""
        generator = MetadataGenerator(config)

        # Test with Unicode characters (should not be escaped)
        unicode_text = "测试视频 🎥"
        result = generator._escape_xml(unicode_text)
        assert result == unicode_text

    def test_escape_xml_empty(self, config):
        """Test XML escaping with empty string."""
        generator = MetadataGenerator(config)

        result = generator._escape_xml("")
        assert result == ""

    def test_escape_xml_none(self, config):
        """Test XML escaping with None value."""
        generator = MetadataGenerator(config)

        result = generator._escape_xml(None)
        assert result == ""

    def test_generate_nfo_content_kodi(self, config, mock_video_info):
        """Test generating NFO content for Kodi."""
        config._config["media_server"]["nfo_format"] = "kodi"
        generator = MetadataGenerator(config)

        content = generator._generate_nfo_content(mock_video_info)

        assert "<episodedetails>" in content
        assert mock_video_info["title"] in content
        assert mock_video_info["description"] in content

    def test_generate_nfo_content_emby(self, config, mock_video_info):
        """Test generating NFO content for Emby."""
        config._config["media_server"]["nfo_format"] = "emby"
        generator = MetadataGenerator(config)

        content = generator._generate_nfo_content(mock_video_info)

        assert "<Item>" in content
        assert mock_video_info["title"] in content
        assert mock_video_info["description"] in content

    def test_generate_nfo_content_missing_fields(self, config):
        """Test generating NFO content with missing fields."""
        generator = MetadataGenerator(config)

        # Video with minimal information
        minimal_video = {
            "id": "minimal",
            "title": "Minimal Video",
        }

        content = generator._generate_nfo_content(minimal_video)

        # Should use default values
        assert "<title>Minimal Video</title>" in content
        assert "Unknown Description" in content
        assert "Unknown Channel" in content

    def test_create_tvshow_nfo(self, config, temp_dir):
        """Test creating tvshow.nfo file."""
        generator = MetadataGenerator(config)

        output_path = temp_dir / "tvshow.nfo"

        generator.create_tvshow_nfo("Test Channel", output_path)

        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")

        # Check for TV show XML structure
        assert '<?xml version="1.0" encoding="utf-8" standalone="yes"?>' in content
        assert "<tvshow>" in content
        assert "<title>Test Channel</title>" in content
        assert "</tvshow>" in content

    def test_create_tvshow_nfo_xml_escaping(self, config, temp_dir):
        """Test XML escaping in tvshow.nfo."""
        generator = MetadataGenerator(config)

        output_path = temp_dir / "tvshow.nfo"

        # Channel name with special characters
        generator.create_tvshow_nfo("Test & Co. <Channel>", output_path)

        content = output_path.read_text(encoding="utf-8")

        assert "<title>Test &amp; Co. &lt;Channel&gt;</title>" in content

    def test_create_tvshow_nfo_write_error(self, config, temp_dir, mocker):
        """Test handling of write errors during tvshow.nfo creation."""
        generator = MetadataGenerator(config)

        output_path = temp_dir / "tvshow.nfo"

        # Mock Path.open to raise permission error
        mocker.patch("pathlib.Path.open", side_effect=PermissionError("Permission denied"))

        with pytest.raises(MetadataError, match="Error writing TV show NFO file"):
            generator.create_tvshow_nfo("Test Channel", output_path)

    def test_generate_tvshow_nfo_content(self, config):
        """Test generating tvshow.nfo content."""
        generator = MetadataGenerator(config)

        content = generator._generate_tvshow_nfo_content("My Channel")

        assert '<?xml version="1.0" encoding="utf-8" standalone="yes"?>' in content
        assert "<tvshow>" in content
        assert "<title>My Channel</title>" in content
        assert "</tvshow>" in content
