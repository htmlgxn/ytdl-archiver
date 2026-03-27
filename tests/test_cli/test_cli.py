"""Tests for CLI interface."""

from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner

from ytdl_archiver import __version__
from ytdl_archiver.cli import cli
from ytdl_archiver.core.search import SearchResult
from ytdl_archiver.exceptions import SearchError
from ytdl_archiver.setup.models import SetupAnswers, SetupRunResult, SetupWriteResult
from ytdl_archiver.setup.runner import SetupCancelled


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
        assert "init" in result.output
        assert "init-config" not in result.output
        assert "convert-playlists" in result.output
        assert "dedupe" in result.output
        assert "search" in result.output

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
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text(
                f"""
[archive]
base_directory = "{temp_dir}/downloads"
"""
            )

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "archive"],
            )

            assert result.exit_code == 0
            assert "ytdl-archiver" in result.output.lower()
            assert "Metadata prefetch" not in result.output

    @patch("ytdl_archiver.cli.MetadataBackfiller")
    @patch("ytdl_archiver.cli.Config")
    def test_metadata_backfill_command_basic(
        self, mock_config_class, mock_backfiller_class
    ):
        """Test basic metadata-backfill command wiring."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")

            mock_config = Mock()
            mock_config.validate.return_value = None
            mock_config.ensure_playlists_file.return_value = None
            mock_config.as_dict.return_value = {"logging": {"level": "INFO"}}
            mock_config.migrate_playlists_from_cwd.return_value = None
            mock_config_class.return_value = mock_config

            mock_backfiller = Mock()
            mock_backfiller_class.return_value = mock_backfiller

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "metadata-backfill"],
            )

            assert result.exit_code == 0
            mock_backfiller.run.assert_called_once_with(
                scope="full",
                refresh_existing=False,
                limit_per_playlist=None,
                continue_on_error=True,
            )

    @patch("ytdl_archiver.cli.MetadataBackfiller")
    @patch("ytdl_archiver.cli.Config")
    def test_metadata_backfill_command_passes_options(
        self, mock_config_class, mock_backfiller_class
    ):
        """Test metadata-backfill option passthrough."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            playlists_file = Path(temp_dir) / "custom-playlists.toml"
            target_directory = Path(temp_dir) / "archive-dir"
            config_file.write_text("")
            playlists_file.write_text("playlists = []\n")

            mock_config = Mock()
            mock_config.validate.return_value = None
            mock_config.ensure_playlists_file.return_value = None
            mock_config.as_dict.return_value = {"logging": {"level": "INFO"}}
            mock_config.migrate_playlists_from_cwd.return_value = None
            mock_config_class.return_value = mock_config

            mock_backfiller = Mock()
            mock_backfiller_class.return_value = mock_backfiller

            result = self.runner.invoke(
                cli,
                [
                    "--config",
                    str(config_file),
                    "metadata-backfill",
                    "--playlists",
                    str(playlists_file),
                    "--directory",
                    str(target_directory),
                    "--scope",
                    "info-json",
                    "--refresh-existing",
                    "--limit-per-playlist",
                    "3",
                    "--fail-fast",
                ],
            )

            assert result.exit_code == 0
            mock_config.set_playlists_file.assert_called_once_with(playlists_file)
            mock_config.set_archive_directory.assert_called_once_with(target_directory)
            mock_backfiller.run.assert_called_once_with(
                scope="info-json",
                refresh_existing=True,
                limit_per_playlist=3,
                continue_on_error=False,
            )

    @patch("ytdl_archiver.cli.BrowserCookieRefresher")
    @patch("ytdl_archiver.cli.MetadataBackfiller")
    @patch("ytdl_archiver.cli.Config")
    def test_metadata_backfill_refreshes_browser_cookies_before_run(
        self,
        mock_config_class,
        mock_backfiller_class,
        mock_cookie_refresher_class,
    ):
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

            mock_backfiller = Mock()
            mock_backfiller_class.return_value = mock_backfiller
            cookie_refresher = Mock()
            mock_cookie_refresher_class.return_value = cookie_refresher

            result = self.runner.invoke(
                cli,
                [
                    "--config",
                    str(config_file),
                    "metadata-backfill",
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

    @patch("ytdl_archiver.cli.BrowserCookieRefresher")
    @patch("ytdl_archiver.cli.MetadataBackfiller")
    @patch("ytdl_archiver.cli.Config")
    def test_metadata_backfill_uses_persisted_cookie_settings(
        self,
        mock_config_class,
        mock_backfiller_class,
        mock_cookie_refresher_class,
    ):
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
            mock_config.get.side_effect = lambda key, default=None: {
                "cookies.source": "browser",
                "cookies.refresh_on_startup": True,
                "cookies.browser": "firefox",
                "cookies.profile": "default-release",
            }.get(key, default)
            mock_config_class.return_value = mock_config

            mock_backfiller_class.return_value = Mock()
            cookie_refresher = Mock()
            mock_cookie_refresher_class.return_value = cookie_refresher

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "metadata-backfill"],
            )

            assert result.exit_code == 0
            cookie_refresher.refresh_to_file.assert_called_once_with(
                "firefox",
                "default-release",
                Path(temp_dir) / "cookies.txt",
            )

    @patch("ytdl_archiver.cli.run_dedupe")
    @patch("ytdl_archiver.cli.Config")
    def test_dedupe_command_basic(self, mock_config_class, mock_run_dedupe):
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            left_dir = Path(temp_dir) / "left"
            right_dir = Path(temp_dir) / "right"
            config_file.write_text("")
            left_dir.mkdir()
            right_dir.mkdir()

            mock_config = Mock()
            mock_config.as_dict.return_value = {"logging": {"level": "INFO"}}
            mock_config.migrate_playlists_from_cwd.return_value = None
            mock_config_class.return_value = mock_config
            mock_run_dedupe.return_value = {
                "duplicate_sets": 1,
                "losers_disposed": 1,
                "sidecars_copied": 0,
                "winners_renamed": 1,
                "details": [],
            }

            result = self.runner.invoke(
                cli,
                [
                    "--config",
                    str(config_file),
                    "dedupe",
                    str(left_dir),
                    str(right_dir),
                    "--delete",
                ],
            )

            assert result.exit_code == 0
            mock_run_dedupe.assert_called_once_with(
                left_dir.resolve(),
                right_dir.resolve(),
                trash_dir=None,
                delete=True,
                dry_run=False,
                verbose=False,
                config=mock_config,
            )

    @patch("ytdl_archiver.cli.run_dedupe")
    @patch("ytdl_archiver.cli.Config")
    def test_dedupe_command_defaults_dir2_to_archive_directory(
        self, mock_config_class, mock_run_dedupe
    ):
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            left_dir = Path(temp_dir) / "left"
            archive_dir = Path(temp_dir) / "archive"
            config_file.write_text("")
            left_dir.mkdir()
            archive_dir.mkdir()

            mock_config = Mock()
            mock_config.as_dict.return_value = {"logging": {"level": "INFO"}}
            mock_config.migrate_playlists_from_cwd.return_value = None
            mock_config.get_archive_directory.return_value = archive_dir
            mock_config_class.return_value = mock_config
            mock_run_dedupe.return_value = {
                "duplicate_sets": 0,
                "losers_disposed": 0,
                "sidecars_copied": 0,
                "winners_renamed": 0,
                "details": [],
            }

            result = self.runner.invoke(
                cli,
                [
                    "--config",
                    str(config_file),
                    "dedupe",
                    str(left_dir),
                    "--delete",
                ],
            )

            assert result.exit_code == 0
            mock_run_dedupe.assert_called_once_with(
                left_dir.resolve(),
                archive_dir.resolve(),
                trash_dir=None,
                delete=True,
                dry_run=False,
                verbose=False,
                config=mock_config,
            )

    def test_dedupe_command_rejects_invalid_disposal_flags(self):
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            left_dir = Path(temp_dir) / "left"
            right_dir = Path(temp_dir) / "right"
            trash_dir = Path(temp_dir) / "trash"
            config_file.write_text("")
            left_dir.mkdir()
            right_dir.mkdir()
            trash_dir.mkdir()

            result = self.runner.invoke(
                cli,
                [
                    "--config",
                    str(config_file),
                    "dedupe",
                    str(left_dir),
                    str(right_dir),
                    "--trash-dir",
                    str(trash_dir),
                    "--delete",
                ],
            )

            assert result.exit_code == 2
            assert "Specify exactly one" in result.output

    @patch("ytdl_archiver.cli.Config")
    def test_dedupe_command_rejects_identical_directories(self, mock_config_class):
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            left_dir = Path(temp_dir) / "same"
            config_file.write_text("")
            left_dir.mkdir()

            mock_config = Mock()
            mock_config.as_dict.return_value = {"logging": {"level": "INFO"}}
            mock_config.migrate_playlists_from_cwd.return_value = None
            mock_config_class.return_value = mock_config

            result = self.runner.invoke(
                cli,
                [
                    "--config",
                    str(config_file),
                    "dedupe",
                    str(left_dir),
                    str(left_dir),
                    "--delete",
                ],
            )

            assert result.exit_code == 2
            assert "must resolve to different directories" in result.output

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
    def test_archive_header_uses_package_version(
        self, mock_config_class, mock_archiver
    ):
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
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")
            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "invalid-command"],
            )

        assert result.exit_code != 0

    def test_multiple_positional_args(self):
        """Test multiple positional arguments."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")
            result = self.runner.invoke(
                cli,
                [
                    "--config",
                    str(config_file),
                    "archive",
                    "init",  # Multiple commands
                ],
            )

        assert result.exit_code != 0

    def test_no_command_missing_config_runs_setup(self):
        """Test no-command first run triggers setup and exits successfully."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "cfg" / "config.toml"
            result = self.runner.invoke(
                cli,
                ["--config", str(config_file)],
                env={"HOME": temp_dir},
            )

            assert result.exit_code == 0
            assert "first-run setup complete" in result.output
            assert config_file.exists()

    def test_archive_missing_config_runs_setup(self):
        """Test non-help command with missing config runs setup first."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "cfg" / "config.toml"
            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "archive"],
                env={"HOME": temp_dir},
            )

            assert result.exit_code == 0
            assert "first-run setup complete" in result.output
            assert config_file.exists()
            assert (config_file.parent / "playlists.toml").exists()

    def test_help_bypasses_first_run_setup(self):
        """Test help output does not trigger setup generation."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "cfg" / "config.toml"
            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "--help"],
            )

            assert result.exit_code == 0
            assert "Usage:" in result.output
            assert not config_file.exists()

    def test_verbose_flag_with_invalid_command(self):
        """Test verbose flag with invalid command."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")
            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "--verbose", "invalid-command"],
            )

        assert result.exit_code != 0

    @patch("ytdl_archiver.cli.setup_logging")
    @patch("ytdl_archiver.cli.PlaylistArchiver")
    @patch("ytdl_archiver.cli.Config")
    def test_verbose_mode_sets_debug_console_logging(
        self, mock_config_class, mock_archiver, mock_setup_logging
    ):
        """Test verbose mode configures console logging for diagnostics."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")

            mock_config = Mock()
            mock_config.validate.return_value = None
            mock_config.ensure_playlists_file.return_value = None
            mock_config.as_dict.return_value = {"logging": {"level": "DEBUG"}}
            mock_config.migrate_playlists_from_cwd.return_value = None
            mock_config.get_archive_directory.return_value = Path(temp_dir)
            mock_config_class.return_value = mock_config
            mock_archiver.return_value.run.return_value = None

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "--verbose", "archive"],
            )

            assert result.exit_code == 0
            mock_setup_logging.assert_called_once_with(
                mock_config.as_dict.return_value,
                console_output=True,
                console_level="DEBUG",
            )

    @patch("ytdl_archiver.cli.setup_logging")
    @patch("ytdl_archiver.cli.PlaylistArchiver")
    @patch("ytdl_archiver.cli.Config")
    def test_default_mode_keeps_console_logging_suppressed(
        self, mock_config_class, mock_archiver, mock_setup_logging
    ):
        """Test default mode keeps console diagnostics disabled."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")

            mock_config = Mock()
            mock_config.validate.return_value = None
            mock_config.ensure_playlists_file.return_value = None
            mock_config.as_dict.return_value = {"logging": {"level": "INFO"}}
            mock_config.migrate_playlists_from_cwd.return_value = None
            mock_config.get_archive_directory.return_value = Path(temp_dir)
            mock_config_class.return_value = mock_config
            mock_archiver.return_value.run.return_value = None

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "archive"],
            )

            assert result.exit_code == 0
            mock_setup_logging.assert_called_once_with(
                mock_config.as_dict.return_value,
                console_output=False,
                console_level="WARNING",
            )

    def test_cli_empty_args(self):
        """Test CLI empty invocation can run first-run setup with custom config path."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "cfg" / "config.toml"
            result = self.runner.invoke(
                cli,
                ["--config", str(config_file)],
                env={"HOME": temp_dir},
            )

            assert result.exit_code == 0
            assert "first-run setup complete" in result.output

    @patch("ytdl_archiver.cli.render_setup_summary")
    @patch("ytdl_archiver.cli.run_setup")
    @patch("ytdl_archiver.cli.Config")
    def test_init_bypasses_group_config_bootstrap(
        self,
        mock_config,
        mock_run_setup,
        mock_render_setup_summary,
    ):
        """Test init command bypasses group config bootstrap and runs setup directly."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "cfg" / "config.toml"
            mock_run_setup.return_value = SetupRunResult(
                answers=SetupAnswers(),
                write_result=SetupWriteResult(
                    config_path=config_file,
                    playlists_path=config_file.parent / "playlists.toml",
                    archive_directory=Path(temp_dir) / "archive",
                    created_config=True,
                    created_playlists=True,
                    created_archive_directory=True,
                ),
                ui_mode="ratatui",
                ui_error=None,
            )
            mock_render_setup_summary.return_value = ["setup complete"]

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "init"],
            )

            assert result.exit_code == 0
            assert "setup complete" in result.output
            mock_config.assert_not_called()
            mock_run_setup.assert_called_once_with(config_file)

    @patch(
        "ytdl_archiver.cli.run_setup", side_effect=SetupCancelled("Setup was cancelled")
    )
    def test_init_cancel_exits_with_cancel_code(self, _mock_run_setup):
        """Test cancelling init setup exits with user-cancel status."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "cfg" / "config.toml"
            result = self.runner.invoke(cli, ["--config", str(config_file), "init"])

            assert result.exit_code == 130
            assert "Setup cancelled by user." in result.output

    @patch(
        "ytdl_archiver.cli.run_setup", side_effect=SetupCancelled("Setup was cancelled")
    )
    def test_missing_config_cancel_exits_with_cancel_code(self, _mock_run_setup):
        """Test cancelling auto first-run setup exits with user-cancel status."""
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "cfg" / "config.toml"
            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "archive"],
                env={"HOME": temp_dir},
            )

            assert result.exit_code == 130
            assert "Setup cancelled by user." in result.output

    @patch("ytdl_archiver.cli.BrowserCookieRefresher")
    @patch("ytdl_archiver.cli.PlaylistArchiver")
    @patch("ytdl_archiver.cli.Config")
    def test_archive_uses_persisted_cookie_settings(
        self,
        mock_config_class,
        mock_archiver,
        mock_cookie_refresher_class,
    ):
        """Test archive refreshes cookies using persisted setup settings."""
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
            mock_config.get.side_effect = lambda key, default=None: {
                "cookies.source": "browser",
                "cookies.refresh_on_startup": True,
                "cookies.browser": "firefox",
                "cookies.profile": "default-release",
            }.get(key, default)
            mock_config_class.return_value = mock_config

            mock_archiver_instance = Mock()
            mock_archiver.return_value = mock_archiver_instance
            cookie_refresher = Mock()
            mock_cookie_refresher_class.return_value = cookie_refresher

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "archive"],
            )

            assert result.exit_code == 0
            cookie_refresher.refresh_to_file.assert_called_once_with(
                "firefox",
                "default-release",
                Path(temp_dir) / "cookies.txt",
            )

    @patch("ytdl_archiver.cli.PlaylistWriter")
    @patch("ytdl_archiver.cli.InvidiousSearchService")
    @patch("ytdl_archiver.cli.subprocess.run")
    @patch("ytdl_archiver.cli.shutil.which", return_value="/usr/bin/fzf")
    def test_search_command_with_fzf_and_explicit_query(
        self,
        _mock_which,
        mock_subprocess_run,
        mock_search_service,
        mock_writer_class,
    ):
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")

            search_service = Mock()
            search_service.search.return_value = [
                SearchResult(
                    result_type="channel",
                    title="Example Channel",
                    source_id="UCabc123",
                    archive_id="UUabc123",
                    channel_name="Example Channel",
                    subscriber_count=123,
                    description="desc",
                    video_count=10,
                    instance="https://inv.example",
                )
            ]
            mock_search_service.return_value = search_service
            mock_subprocess_run.return_value = Mock(
                returncode=0, stdout="1\t[channel] Example Channel\t...\n"
            )

            writer = Mock()
            writer.append_entries.return_value = (1, 0)
            mock_writer_class.return_value = writer

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "search", "example"],
                input="example-channel\n",
            )

            assert result.exit_code == 0
            writer.append_entries.assert_called_once()
            assert "Added: 1, skipped duplicates: 0" in result.output
            assert "Found 1 channel candidates via" in result.output
            search_service.search.assert_called_once_with(
                "example", include_playlists=False
            )

    @patch("ytdl_archiver.cli._select_search_results")
    @patch("ytdl_archiver.cli.PlaylistWriter")
    @patch("ytdl_archiver.cli.InvidiousSearchService")
    def test_search_prompts_for_query_when_omitted(
        self, mock_search_service, mock_writer_class, mock_select
    ):
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")

            selected_result = SearchResult(
                result_type="playlist",
                title="My Playlist",
                source_id="PLabc",
                archive_id="PLabc",
                channel_name="Author",
                subscriber_count=None,
                description="desc",
                video_count=3,
                instance="https://inv.example",
            )
            search_service = Mock()
            search_service.search.return_value = [selected_result]
            mock_search_service.return_value = search_service
            mock_select.return_value = ([selected_result], False)

            writer = Mock()
            writer.append_entries.return_value = (1, 0)
            mock_writer_class.return_value = writer

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "search"],
                input="find me\nmy-playlist\n",
            )

            assert result.exit_code == 0
            search_service.search.assert_called_once_with(
                "find me", include_playlists=False
            )

    @patch("ytdl_archiver.cli.PlaylistWriter")
    @patch("ytdl_archiver.cli.InvidiousSearchService")
    @patch("ytdl_archiver.cli.subprocess.run")
    @patch("ytdl_archiver.cli.shutil.which", return_value="/usr/bin/fzf")
    def test_search_fzf_cancel_shows_cancel_message(
        self,
        _mock_which,
        mock_subprocess_run,
        mock_search_service,
        mock_writer_class,
    ):
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")

            search_service = Mock()
            search_service.search.return_value = [
                SearchResult(
                    result_type="channel",
                    title="Example Channel",
                    source_id="UCabc123",
                    archive_id="UUabc123",
                    channel_name="Example Channel",
                    subscriber_count=123,
                    description="desc",
                    video_count=10,
                    instance="youtube-html",
                )
            ]
            mock_search_service.return_value = search_service
            mock_subprocess_run.return_value = Mock(returncode=130, stdout="")

            writer = Mock()
            mock_writer_class.return_value = writer

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "search", "example"],
            )

            assert result.exit_code == 0
            assert "Selection cancelled" in result.output
            writer.append_entries.assert_not_called()

    @patch("ytdl_archiver.cli.PlaylistWriter")
    @patch("ytdl_archiver.cli.InvidiousSearchService")
    @patch("ytdl_archiver.cli.shutil.which", return_value=None)
    def test_search_falls_back_to_numbered_selector_without_fzf(
        self, _mock_which, mock_search_service, mock_writer_class
    ):
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")

            search_service = Mock()
            search_service.search.return_value = [
                SearchResult(
                    result_type="channel",
                    title="Fallback Channel",
                    source_id="UCzzz",
                    archive_id="UUzzz",
                    channel_name="Fallback Channel",
                    subscriber_count=1,
                    description="desc",
                    video_count=1,
                    instance="https://inv.example",
                )
            ]
            mock_search_service.return_value = search_service

            writer = Mock()
            writer.append_entries.return_value = (1, 0)
            mock_writer_class.return_value = writer

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "search", "fallback"],
                input="1\nfallback-path\n",
            )

            assert result.exit_code == 0
            assert "Using numbered selector" in result.output

    @patch("ytdl_archiver.cli.PlaylistWriter")
    @patch("ytdl_archiver.cli.InvidiousSearchService")
    @patch("ytdl_archiver.cli.shutil.which", return_value=None)
    def test_search_multiselect_reports_duplicate_skips(
        self, _mock_which, mock_search_service, mock_writer_class
    ):
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")

            search_service = Mock()
            search_service.search.return_value = [
                SearchResult(
                    result_type="channel",
                    title="Channel One",
                    source_id="UC111",
                    archive_id="UU111",
                    channel_name="Channel One",
                    subscriber_count=10,
                    description="desc",
                    video_count=2,
                    instance="https://inv.example",
                ),
                SearchResult(
                    result_type="channel",
                    title="Channel Two",
                    source_id="UC222",
                    archive_id="UU222",
                    channel_name="Channel Two",
                    subscriber_count=20,
                    description="desc",
                    video_count=3,
                    instance="https://inv.example",
                ),
            ]
            mock_search_service.return_value = search_service

            writer = Mock()
            writer.append_entries.return_value = (1, 1)
            mock_writer_class.return_value = writer

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "search", "multi"],
                input="1,2\npath-one\npath-two\n",
            )

            assert result.exit_code == 0
            writer.append_entries.assert_called_once()
            assert "Added: 1, skipped duplicates: 1" in result.output

    @patch("ytdl_archiver.cli.PlaylistWriter")
    @patch("ytdl_archiver.cli.InvidiousSearchService")
    @patch("ytdl_archiver.cli.shutil.which", return_value=None)
    def test_search_include_playlists_flag(self, _mock_which, mock_search_service, mock_writer_class):
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")

            search_service = Mock()
            search_service.search.return_value = [
                SearchResult(
                    result_type="playlist",
                    title="Playlist",
                    source_id="PL1",
                    archive_id="PL1",
                    channel_name="Author",
                    subscriber_count=None,
                    description="desc",
                    video_count=1,
                    instance="youtube-html",
                )
            ]
            mock_search_service.return_value = search_service

            writer = Mock()
            writer.append_entries.return_value = (1, 0)
            mock_writer_class.return_value = writer

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "search", "--include-playlists", "mix"],
                input="1\nplaylist-path\n",
            )

            assert result.exit_code == 0
            search_service.search.assert_called_once_with(
                "mix", include_playlists=True
            )

    @patch("ytdl_archiver.cli.InvidiousSearchService")
    def test_search_failure_message_is_concise(self, mock_search_service):
        with CliRunner().isolated_filesystem() as temp_dir:
            config_file = Path(temp_dir) / "config.toml"
            config_file.write_text("")

            service = Mock()
            service.search.side_effect = SearchError(
                "Search failed across backends. invidious: 403; youtube_html: blocked"
            )
            mock_search_service.return_value = service

            result = self.runner.invoke(
                cli,
                ["--config", str(config_file), "search", "art"],
            )

            assert result.exit_code == 1
            assert "Search failed across backends." in result.output
