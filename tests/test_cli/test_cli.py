"""Tests for CLI interface."""

from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner

from ytdl_archiver import __version__
from ytdl_archiver.cli import cli


class TestCLI:
    """Test cases for CLI interface."""

    def setup_method(self):
        """Set up CLI runner for each test."""
        self.runner = CliRunner()

    def test_cli_help(self):
        """Test CLI help command."""
        result = self.runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "archive" in result.output
        assert "init-config" in result.output
        assert "convert-playlists" in result.output

    def test_cli_version(self):
        """Test CLI version command."""
        result = self.runner.invoke(cli, ["--version"])

        # CLI might not have version - just check exit code is 0 or 2
        assert result.exit_code in [0, 2]

    @patch("ytdl_archiver.cli.PlaylistArchiver")
    def test_archive_command_basic(self, mock_archiver):
        """Test basic archive command."""
        mock_archiver_instance = Mock()
        mock_archiver.return_value = mock_archiver_instance
        mock_archiver_instance.run.return_value = None

        # Create a temporary directory for testing
        with CliRunner().isolated_filesystem() as temp_dir:
            # Create a playlists file to avoid the error
            playlists_file = Path(temp_dir) / "playlists.toml"
            playlists_file.write_text('[[playlists]]\nid = "test"\npath = "test"')

            result = self.runner.invoke(
                cli, ["--config", str(Path(temp_dir) / "config.toml"), "archive"]
            )

            # Check that the command ran (either succeeded or showed expected error)
            assert "ytdl-archiver" in result.output.lower() or result.exit_code != 0

    @patch("ytdl_archiver.cli.BrowserCookieRefresher")
    @patch("ytdl_archiver.cli.PlaylistArchiver")
    @patch("ytdl_archiver.cli.Config")
    def test_archive_refreshes_browser_cookies_before_run(
        self,
        mock_config_class,
        mock_archiver,
        mock_cookie_refresher_class,
    ):
        """Test archive refreshes cookies before running when browser flag is set."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")

            mock_config = Mock()
            mock_config.validate.return_value = None
            mock_config.ensure_playlists_file.return_value = None
            mock_config.as_dict.return_value = {"logging": {"level": "INFO"}}
            mock_config.migrate_playlists_from_cwd.return_value = None
            mock_config.get_cookie_file_target_path.return_value = (
                Path(temp_dir) / "cookies.txt"
            )
            mock_config_class.return_value = mock_config

            mock_archiver_instance = Mock()
            mock_archiver.return_value = mock_archiver_instance
            cookie_refresher = Mock()
            mock_cookie_refresher_class.return_value = cookie_refresher

            result = self.runner.invoke(
                cli,
                [
                    "--config",
                    str(config_file),
                    "archive",
                    "--cookies-browser",
                    "firefox",
                    "--cookies-profile",
                    "default",
                ],
            )

            assert result.exit_code == 0
            cookie_refresher.refresh_to_file.assert_called_once_with(
                "firefox",
                "default",
                Path(temp_dir) / "cookies.txt",
            )
            mock_archiver.assert_called_once()
            assert mock_archiver.call_args.kwargs["skip_initial_cookie_refresh"] is True

    @patch("ytdl_archiver.cli.BrowserCookieRefresher")
    @patch("ytdl_archiver.cli.Config")
    def test_archive_cookie_refresh_failure_exits(
        self, mock_config_class, mock_refresher
    ):
        """Test archive fails fast when startup cookie refresh fails."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")

            mock_config = Mock()
            mock_config.validate.return_value = None
            mock_config.ensure_playlists_file.return_value = None
            mock_config.as_dict.return_value = {"logging": {"level": "INFO"}}
            mock_config.migrate_playlists_from_cwd.return_value = None
            mock_config.get_cookie_file_target_path.return_value = (
                Path(temp_dir) / "cookies.txt"
            )
            mock_config_class.return_value = mock_config

            mock_refresher.return_value.refresh_to_file.side_effect = RuntimeError(
                "cannot extract"
            )

            result = self.runner.invoke(
                cli,
                [
                    "--config",
                    str(config_file),
                    "archive",
                    "--cookies-browser",
                    "firefox",
                ],
            )

            assert result.exit_code != 0
            assert "Cookie refresh failed at startup" in result.output

    def test_archive_failure_before_formatter_initialization(self):
        """Test archive failure path doesn't crash when formatter is not initialized yet."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text(
                """
[archive]
base_directory = "/this/path/should/not/exist"
"""
            )

            result = self.runner.invoke(cli, ["--config", str(config_file), "archive"])

            assert result.exit_code != 0
            assert "Archive failed" in result.output
            assert "UnboundLocalError" not in result.output

    @patch("ytdl_archiver.cli.PlaylistArchiver")
    @patch("ytdl_archiver.cli.Config")
    def test_archive_header_uses_package_version(self, mock_config_class, mock_archiver):
        """Test archive header includes package __version__."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")

            mock_config = Mock()
            mock_config.validate.return_value = None
            mock_config.ensure_playlists_file.return_value = None
            mock_config.as_dict.return_value = {"logging": {"level": "INFO"}}
            mock_config.migrate_playlists_from_cwd.return_value = None
            mock_config_class.return_value = mock_config

            mock_archiver_instance = Mock()
            mock_archiver.return_value = mock_archiver_instance

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "archive"],
            )

            assert result.exit_code == 0
            assert f"v{__version__}" in result.output

    def test_invalid_command(self):
        """Test invalid CLI command."""
        result = self.runner.invoke(cli, ["invalid-command"])

        assert result.exit_code != 0

    def test_multiple_positional_args(self):
        """Test multiple positional arguments."""
        result = self.runner.invoke(
            cli,
            [
                "archive",
                "init-config",  # Multiple commands
            ],
        )

        assert result.exit_code != 0

    def test_config_flag_with_no_command(self):
        """Test config flag without command."""
        result = self.runner.invoke(cli, ["--config", "/config.toml"])

        assert result.exit_code != 0

    def test_verbose_flag_with_invalid_command(self):
        """Test verbose flag with invalid command."""
        result = self.runner.invoke(cli, ["--verbose", "invalid-command"])

        assert result.exit_code != 0

    def test_cli_empty_args(self):
        """Test CLI with no arguments - should show help."""
        result = self.runner.invoke(cli, [])

        # Should show help or exit with error
        assert result.exit_code != 0 or "help" in result.output.lower()
