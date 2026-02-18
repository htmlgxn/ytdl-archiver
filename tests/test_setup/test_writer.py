"""Tests for first-run setup writer and runner."""

from ytdl_archiver.setup.models import SetupAnswers
from ytdl_archiver.setup.runner import render_setup_summary, run_setup
from ytdl_archiver.setup.writer import write_setup_files


class TestSetupWriter:
    """Test setup file generation behavior."""

    def test_write_setup_files_creates_expected_outputs(self, temp_dir):
        """Test setup creates config, playlists, and archive directories."""
        config_path = temp_dir / "cfg" / "config.toml"
        answers = SetupAnswers(
            archive_directory=str(temp_dir / "downloads"),
            cookie_source="browser",
            cookie_browser="firefox",
            cookie_profile="default",
        )

        result = write_setup_files(config_path, answers)

        assert result.created_config is True
        assert result.created_playlists is True
        assert result.created_archive_directory is True
        assert config_path.exists()
        assert (config_path.parent / "playlists.toml").exists()
        assert (temp_dir / "downloads").exists()

        content = config_path.read_text()
        assert 'base_directory = "' in content
        assert 'source = "browser"' in content
        assert 'browser = "firefox"' in content
        assert 'profile = "default"' in content

    def test_write_setup_files_never_overwrites_existing(self, temp_dir):
        """Test setup keeps existing templates unchanged."""
        config_path = temp_dir / "cfg" / "config.toml"
        playlists_path = config_path.parent / "playlists.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("existing-config\n")
        playlists_path.write_text("existing-playlists\n")

        result = write_setup_files(
            config_path,
            SetupAnswers(archive_directory=str(temp_dir / "downloads")),
        )

        assert result.created_config is False
        assert result.created_playlists is False
        assert config_path.read_text() == "existing-config\n"
        assert playlists_path.read_text() == "existing-playlists\n"

    def test_run_setup_non_interactive_uses_defaults(self, temp_dir, monkeypatch):
        """Test non-interactive setup writes default templates."""
        config_path = temp_dir / "cfg" / "config.toml"
        monkeypatch.setenv("HOME", str(temp_dir))

        result = run_setup(config_path)

        assert result.ui_mode == "non_interactive"
        assert result.write_result.created_config is True
        assert config_path.exists()
        content = config_path.read_text()
        assert 'base_directory = "~/Videos/media/youtube/"' in content
        assert 'source = "manual_file"' in content

    def test_setup_summary_includes_next_steps(self, temp_dir, monkeypatch):
        """Test setup summary includes required command guidance."""
        monkeypatch.setenv("HOME", str(temp_dir))
        result = run_setup(temp_dir / "cfg" / "config.toml")

        summary = "\n".join(render_setup_summary(result))
        assert "Edit config:" in summary
        assert "Add playlists:" in summary
        assert "uv run ytdl-archiver archive" in summary
        assert "uv run ytdl-archiver --help" in summary
