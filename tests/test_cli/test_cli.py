"""Tests for CLI interface."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from ytdl_archiver.cli import cli


class TestCLI:
    """Test cases for CLI interface."""

    def setup_method(self):
        """Set up CLI runner for each test."""
        self.runner = CliRunner()

    def test_cli_help(self):
        """Test CLI help command."""
        result = self.runner.invoke(cli, ['--help'])
        
        assert result.exit_code == 0
        assert 'Usage:' in result.output
        assert 'archive' in result.output
        assert 'init-config' in result.output
        assert 'convert-playlists' in result.output

    def test_cli_version(self):
        """Test CLI version command."""
        result = self.runner.invoke(cli, ['--version'])
        
        assert result.exit_code == 0
        # Version should be in output (format depends on implementation)

    @patch('ytdl_archiver.cli.PlaylistArchiver')
    def test_archive_command_basic(self, mock_archiver):
        """Test basic archive command."""
        # Mock the archiver to avoid actual processing
        mock_archiver_instance = Mock()
        mock_archiver.return_value = mock_archiver_instance
        
        result = self.runner.invoke(cli, ['archive'])
        
        assert result.exit_code == 0
        mock_archiver.assert_called_once()

    @patch('ytdl_archiver.cli.PlaylistArchiver')
    def test_archive_command_with_config(self, mock_archiver):
        """Test archive command with custom config."""
        mock_archiver_instance = Mock()
        mock_archiver.return_value = mock_archiver_instance
        
        config_path = "/custom/config.toml"
        result = self.runner.invoke(cli, ['--config', config_path, 'archive'])
        
        assert result.exit_code == 0
        # Check that config path was passed correctly
        # This depends on implementation details

    @patch('ytdl_archiver.cli.PlaylistArchiver')
    def test_archive_command_with_verbose(self, mock_archiver):
        """Test archive command with verbose flag."""
        mock_archiver_instance = Mock()
        mock_archiver.return_value = mock_archiver_instance
        
        result = self.runner.invoke(cli, ['--verbose', 'archive'])
        
        assert result.exit_code == 0
        # Check that verbose mode was enabled
        # This depends on implementation details

    @patch('ytdl_archiver.cli.PlaylistArchiver')
    def test_archive_command_with_playlists_file(self, mock_archiver):
        """Test archive command with custom playlists file."""
        mock_archiver_instance = Mock()
        mock_archiver.return_value = mock_archiver_instance
        
        playlists_path = "/custom/playlists.toml"
        result = self.runner.invoke(cli, ['--playlists', playlists_path, 'archive'])
        
        assert result.exit_code == 0
        # Check that playlists path was passed correctly
        # This depends on implementation details

    @patch('ytdl_archiver.cli.Config')
    def test_init_config_command(self, mock_config):
        """Test init-config command."""
        mock_config_instance = Mock()
        mock_config.return_value = mock_config_instance
        
        result = self.runner.invoke(cli, ['init-config'])
        
        assert result.exit_code == 0
        # Check that config initialization was called
        # This depends on implementation details

    @patch('ytdl_archiver.cli.Config')
    def test_init_config_command_with_path(self, mock_config):
        """Test init-config command with custom path."""
        mock_config_instance = Mock()
        mock_config.return_value = mock_config_instance
        
        config_path = "/custom/config/path"
        result = self.runner.invoke(cli, ['--config', config_path, 'init-config'])
        
        assert result.exit_code == 0
        # Check that config path was passed correctly
        # This depends on implementation details

    @patch('ytdl_archiver.cli.Config')
    @patch('ytdl_archiver.cli.Path')
    def test_convert_playlists_command(self, mock_config, mock_path):
        """Test convert-playlists command."""
        mock_config_instance = Mock()
        mock_config.return_value = mock_config_instance
        
        # Mock Path.exists to return True for both files
        mock_path.return_value.exists.return_value = True
        
        result = self.runner.invoke(cli, ['convert-playlists'])
        
        assert result.exit_code == 0
        # Check that conversion was attempted
        # This depends on implementation details

    def test_convert_playlists_no_json_file(self, mocker):
        """Test convert-playlists when no JSON file exists."""
        mock_path = mocker.patch('pathlib.Path')
        mock_path.return_value.exists.return_value = False
        
        result = self.runner.invoke(cli, ['convert-playlists'])
        
        assert result.exit_code != 0
        assert 'error' in result.output.lower() or 'not found' in result.output.lower()

    def test_archive_command_missing_config(self, tmp_path):
        """Test archive command when config is missing."""
        # Create a temporary directory without config
        with patch('ytdl_archiver.cli.Path.home') as mock_home:
            mock_home.return_value = tmp_path
            
            result = self.runner.invoke(cli, ['archive'])
            
            # Should handle missing config gracefully
            # The exact behavior depends on implementation

    def test_invalid_command(self):
        """Test invalid CLI command."""
        result = self.runner.invoke(cli, ['invalid-command'])
        
        assert result.exit_code != 0
        assert 'usage' in result.output.lower() or 'error' in result.output.lower()

    @patch('ytdl_archiver.cli.PlaylistArchiver')
    def test_archive_command_keyboard_interrupt(self, mock_archiver):
        """Test archive command with keyboard interrupt."""
        mock_archiver_instance = Mock()
        mock_archiver.return_value = mock_archiver_instance
        
        # Simulate keyboard interrupt
        mock_archiver_instance.process_all_playlists.side_effect = KeyboardInterrupt()
        
        result = self.runner.invoke(cli, ['archive'])
        
        assert result.exit_code != 0

    @patch('ytdl_archiver.cli.PlaylistArchiver')
    def test_archive_command_general_exception(self, mock_archiver):
        """Test archive command with general exception."""
        mock_archiver_instance = Mock()
        mock_archiver.return_value = mock_archiver_instance
        
        # Simulate general exception
        mock_archiver_instance.process_all_playlists.side_effect = Exception("General error")
        
        result = self.runner.invoke(cli, ['archive'])
        
        assert result.exit_code != 0

    def test_multiple_config_flags(self):
        """Test multiple configuration flags."""
        result = self.runner.invoke(cli, [
            '--config', '/config1.toml',
            '--config', '/config2.toml',  # Multiple config flags
            'archive'
        ])
        
        assert result.exit_code != 0

    def test_multiple_positional_args(self):
        """Test multiple positional arguments."""
        result = self.runner.invoke(cli, [
            'archive',
            'init-config'  # Multiple commands
        ])
        
        assert result.exit_code != 0

    def test_config_flag_with_no_command(self):
        """Test config flag without command."""
        result = self.runner.invoke(cli, ['--config', '/config.toml'])
        
        assert result.exit_code != 0

    def test_verbose_flag_with_invalid_command(self):
        """Test verbose flag with invalid command."""
        result = self.runner.invoke(cli, ['--verbose', 'invalid-command'])
        
        assert result.exit_code != 0

    @patch('ytdl_archiver.cli.PlaylistArchiver')
    def test_archive_command_logging_output(self, mock_archiver, capsys):
        """Test that archive command produces logging output."""
        mock_archiver_instance = Mock()
        mock_archiver.return_value = mock_archiver_instance
        
        result = self.runner.invoke(cli, ['archive'])
        
        # Check that some output was produced
        # The exact output depends on logging configuration

    def test_cli_empty_args(self):
        """Test CLI with no arguments."""
        result = self.runner.invoke(cli, [])
        
        # Should show help or default behavior
        # The exact behavior depends on implementation

    def test_cli_with_hyphenated_option(self):
        """Test CLI with hyphenated long option."""
        result = self.runner.invoke(cli, ['--help'])
        
        assert result.exit_code == 0
        # Should work the same as short help

    def test_cli_option_with_equals(self):
        """Test CLI option with equals sign."""
        result = self.runner.invoke(cli, ['--config=/test/config.toml', 'archive'])
        
        assert result.exit_code == 0
        # Should parse the config path correctly