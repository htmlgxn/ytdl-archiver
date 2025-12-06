"""Tests for metadata generation functionality."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

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
        content = output_path.read_text(encoding='utf-8')
        
        # Check for Kodi XML structure
        assert "<movie>" in content
        assert "<title>" in content
        assert mock_video_info["title"] in content
        assert "<plot>" in content
        assert mock_video_info["description"] in content

    def test_create_nfo_file_emby_format(self, config, temp_dir, mock_video_info):
        """Test creating NFO file in Emby format."""
        config._config["media_server"]["nfo_format"] = "emby"
        generator = MetadataGenerator(config)
        
        output_path = temp_dir / "test_video.nfo"
        
        generator.create_nfo_file(output_path, mock_video_info)
        
        assert output_path.exists()
        content = output_path.read_text(encoding='utf-8')
        
        # Check for Emby XML structure
        assert "<Item>" in content
        assert "<Type>" in content
        assert "Video" in content
        assert "<Name>" in content
        assert mock_video_info["title"] in content

    def test_create_nfo_file_disabled(self, config, temp_dir, mock_video_info):
        """Test that NFO creation is disabled when configured."""
        config._config["media_server"]["generate_nfo"] = False
        generator = MetadataGenerator(config)
        
        output_path = temp_dir / "test_video.nfo"
        
        generator.create_nfo_file(mock_video_info, output_path)
        
        # File should not be created
        assert not output_path.exists()

    def test_create_nfo_file_creates_directory(self, config, mock_video_info):
        """Test that NFO creation creates parent directories."""
        generator = MetadataGenerator(config)
        
        # Use nested path that doesn't exist
        output_path = Path("/tmp/test_nested/dir/test_video.nfo")
        
        generator.create_nfo_file(mock_video_info, output_path)
        
        assert output_path.exists()
        assert output_path.parent.exists()

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
        content = output_path.read_text(encoding='utf-8')
        
        # Check that special characters are properly escaped
        assert "&amp;" in content  # & should be escaped
        assert "&lt;" in content   # < should be escaped
        assert "&gt;" in content   # > should be escaped
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
        content = output_path.read_text(encoding='utf-8')
        
        # Should still create valid XML with available data
        assert "<title>" in content
        assert "Minimal Video" in content

    def test_create_nfo_file_write_error(self, config, temp_dir, mock_video_info, mocker):
        """Test handling of write errors during NFO creation."""
        generator = MetadataGenerator(config)
        
        output_path = temp_dir / "test_error.nfo"
        
        # Mock open to raise permission error
        mock_open = mocker.patch("builtins.open", side_effect=PermissionError("Permission denied"))
        
        with pytest.raises(MetadataError, match="Failed to create NFO file"):
            generator.create_nfo_file(mock_video_info, output_path)

    def test_format_date_kodi(self, config):
        """Test date formatting for Kodi format."""
        config._config["media_server"]["nfo_format"] = "kodi"
        generator = MetadataGenerator(config)
        
        # Test with valid date
        date_str = generator._format_date("20240101")
        assert date_str == "2024-01-01"
        
        # Test with None date
        date_str = generator._format_date(None)
        assert date_str == ""

    def test_format_date_emby(self, config):
        """Test date formatting for Emby format."""
        config._config["media_server"]["nfo_format"] = "emby"
        generator = MetadataGenerator(config)
        
        # Test with valid date
        date_str = generator._format_date("20240101")
        assert date_str == "2024-01-01"
        
        # Test with None date
        date_str = generator._format_date(None)
        assert date_str == ""

    def test_format_date_invalid_format(self, config):
        """Test date formatting with invalid date."""
        config._config["media_server"]["nfo_format"] = "kodi"
        generator = MetadataGenerator(config)
        
        # Test with invalid date format
        date_str = generator._format_date("invalid_date")
        # Should return the original string if parsing fails
        assert date_str == "invalid_date"

    def test_escape_xml_text(self, config):
        """Test XML text escaping."""
        generator = MetadataGenerator(config)
        
        # Test various special characters
        test_cases = [
            ("&", "&amp;"),
            ("<", "&lt;"),
            (">", "&gt;"),
            ("\"", "&quot;"),
            ("'", "&apos;"),
        ]
        
        for input_char, expected_escaped in test_cases:
            result = generator._escape_xml_text(input_char)
            assert result == expected_escaped

    def test_escape_xml_text_unicode(self, config):
        """Test XML escaping with Unicode characters."""
        generator = MetadataGenerator(config)
        
        # Test with Unicode characters (should not be escaped)
        unicode_text = "测试视频 🎥"
        result = generator._escape_xml_text(unicode_text)
        assert result == unicode_text

    def test_escape_xml_text_empty(self, config):
        """Test XML escaping with empty string."""
        generator = MetadataGenerator(config)
        
        result = generator._escape_xml_text("")
        assert result == ""

    def test_escape_xml_text_none(self, config):
        """Test XML escaping with None value."""
        generator = MetadataGenerator(config)
        
        result = generator._escape_xml_text(None)
        assert result == ""

    def test_build_kodi_xml(self, config, mock_video_info):
        """Test building Kodi XML structure."""
        config._config["media_server"]["nfo_format"] = "kodi"
        generator = MetadataGenerator(config)
        
        xml_content = generator._build_kodi_xml(mock_video_info)
        
        # Check for required Kodi elements
        assert "<movie>" in xml_content
        assert "</movie>" in xml_content
        assert "<title>" in xml_content
        assert mock_video_info["title"] in xml_content
        assert "<plot>" in xml_content
        assert mock_video_info["description"] in xml_content

    def test_build_emby_xml(self, config, mock_video_info):
        """Test building Emby XML structure."""
        config._config["media_server"]["nfo_format"] = "emby"
        generator = MetadataGenerator(config)
        
        xml_content = generator._build_emby_xml(mock_video_info)
        
        # Check for required Emby elements
        assert "<Item>" in xml_content
        assert "</Item>" in xml_content
        assert "<Type>Video</Type>" in xml_content
        assert "<Name>" in xml_content
        assert mock_video_info["title"] in xml_content

    def test_build_xml_with_missing_fields(self, config):
        """Test building XML with missing video fields."""
        config._config["media_server"]["nfo_format"] = "kodi"
        generator = MetadataGenerator(config)
        
        # Video with minimal information
        minimal_video = {
            "id": "minimal",
            "title": "Minimal Video",
        }
        
        xml_content = generator._build_kodi_xml(minimal_video)
        
        # Should still create valid XML structure
        assert "<movie>" in xml_content
        assert "</movie>" in xml_content
        assert "<title>Minimal Video</title>" in xml_content

    def test_get_output_path(self, config, temp_dir, mock_video_info):
        """Test getting NFO output path."""
        generator = MetadataGenerator(config)
        
        video_path = temp_dir / "test_video.mp4"
        
        nfo_path = generator.get_output_path(video_path)
        
        assert nfo_path == temp_dir / "test_video.nfo"

    def test_get_output_path_different_extension(self, config, temp_dir):
        """Test getting NFO output path with different video extension."""
        generator = MetadataGenerator(config)
        
        video_path = temp_dir / "test_video.webm"
        
        nfo_path = generator.get_output_path(video_path)
        
        assert nfo_path == temp_dir / "test_video.nfo"

    def test_get_output_path_nested_path(self, config):
        """Test getting NFO output path with nested video path."""
        generator = MetadataGenerator(config)
        
        video_path = Path("/tmp/nested/dir/test_video.mp4")
        
        nfo_path = generator.get_output_path(video_path)
        
        assert nfo_path == Path("/tmp/nested/dir/test_video.nfo")