"""Tests for first-run setup writer and runner."""

from ytdl_archiver.setup.models import SetupAnswers
from ytdl_archiver.setup.runner import SetupCancelled, render_setup_summary, run_setup
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
        assert 'source = "browser"' in content

    def test_setup_summary_includes_next_steps(self, temp_dir, monkeypatch):
        """Test setup summary includes required command guidance."""
        monkeypatch.setenv("HOME", str(temp_dir))
        result = run_setup(temp_dir / "cfg" / "config.toml")

        summary = "\n".join(render_setup_summary(result))
        assert "Interactive setup skipped" in summary
        assert "Edit config:" in summary
        assert "Add playlists:" in summary
        assert "ytdl-archiver archive" in summary
        assert "ytdl-archiver --help" in summary

    def test_run_setup_interactive_prefers_ratatui(self, temp_dir, monkeypatch):
        """Interactive setup uses ratatui answers when available."""
        config_path = temp_dir / "cfg" / "config.toml"
        answers = SetupAnswers(archive_directory=str(temp_dir / "archive"))
        monkeypatch.setattr(
            "ytdl_archiver.setup.runner.is_interactive_session", lambda: True
        )
        monkeypatch.setattr(
            "ytdl_archiver.setup.runner.run_ratatui_setup",
            lambda _defaults: answers,
        )

        result = run_setup(config_path)

        assert result.ui_mode == "ratatui"
        assert result.ui_error is None
        assert result.answers.archive_directory == str(temp_dir / "archive")
        assert config_path.exists()

    def test_run_setup_interactive_falls_back_to_prompt(self, temp_dir, monkeypatch):
        """Interactive setup falls back to prompt collection on ratatui errors."""
        config_path = temp_dir / "cfg" / "config.toml"
        monkeypatch.setattr(
            "ytdl_archiver.setup.runner.is_interactive_session", lambda: True
        )
        monkeypatch.setattr(
            "ytdl_archiver.setup.runner.run_ratatui_setup",
            lambda _defaults: (_ for _ in ()).throw(RuntimeError("bridge failed")),
        )
        monkeypatch.setattr(
            "ytdl_archiver.setup.runner.collect_prompt_answers",
            lambda defaults: SetupAnswers(archive_directory=defaults.archive_directory),
        )

        result = run_setup(config_path)

        assert result.ui_mode == "prompt"
        assert result.ui_error is not None
        assert "bridge failed" in result.ui_error

    def test_run_setup_interactive_cancel_does_not_fallback(
        self, temp_dir, monkeypatch
    ):
        """Interactive cancel exits setup flow without prompt fallback."""
        config_path = temp_dir / "cfg" / "config.toml"
        monkeypatch.setattr(
            "ytdl_archiver.setup.runner.is_interactive_session", lambda: True
        )
        monkeypatch.setattr(
            "ytdl_archiver.setup.runner.run_ratatui_setup",
            lambda _defaults: None,
        )
        prompt_mock = []
        monkeypatch.setattr(
            "ytdl_archiver.setup.runner.collect_prompt_answers",
            lambda _defaults: prompt_mock.append("called"),  # pragma: no cover
        )

        try:
            run_setup(config_path)
        except SetupCancelled:
            pass
        else:  # pragma: no cover - defensive test guard
            raise AssertionError("Expected SetupCancelled")

        assert prompt_mock == []
