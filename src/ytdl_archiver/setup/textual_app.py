"""Textual first-run setup app."""

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
)

from ..core.cookies import SUPPORTED_BROWSERS
from .models import SetupAnswers


class FirstRunSetupApp(App[SetupAnswers | None]):
    """Collect setup values in a themed Textual wizard."""

    CSS = """
    Screen {
        background: #141414;
        color: #eee8cf;
    }

    #wizard {
        width: 80;
        max-width: 96;
        margin: 1 2;
        padding: 1 2;
        border: round #e62f2f;
        background: #141414;
    }

    #title {
        color: #e62f2f;
        text-style: bold;
        margin-bottom: 1;
    }

    Label {
        color: #eee8cf;
        margin-top: 1;
    }

    Input, Select {
        margin-top: 0;
    }

    Checkbox {
        margin-top: 1;
    }

    #buttons {
        margin-top: 2;
        height: auto;
    }

    #buttons Button {
        margin-right: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("ctrl+c", "cancel", "Cancel")]

    def __init__(self, defaults: SetupAnswers) -> None:
        super().__init__()
        self.defaults = defaults

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="wizard"):
            yield Static("ytdl-archiver first-run setup", id="title")

            yield Label("Archive directory")
            yield Input(value=self.defaults.archive_directory, id="archive_directory")

            yield Label("Cookie source")
            yield Select[str](
                options=[
                    ("Browser auto-refresh (recommended: firefox)", "browser"),
                    ("Manual cookies.txt management", "manual_file"),
                ],
                value=self.defaults.cookie_source,
                id="cookie_source",
                allow_blank=False,
            )

            yield Label("Cookie browser", id="cookie_browser_label")
            yield Select[str](
                options=[
                    (
                        f"{browser} (recommended)" if browser == "firefox" else browser,
                        browser,
                    )
                    for browser in SUPPORTED_BROWSERS
                ],
                value=self.defaults.cookie_browser,
                id="cookie_browser",
                allow_blank=False,
            )

            yield Label("Browser profile (optional)", id="cookie_profile_label")
            yield Input(value=self.defaults.cookie_profile, id="cookie_profile")

            yield Checkbox(
                "Download subtitles",
                value=self.defaults.write_subtitles,
                id="write_subtitles",
            )
            yield Checkbox(
                "Download thumbnails",
                value=self.defaults.write_thumbnail,
                id="write_thumbnail",
            )
            yield Checkbox(
                "Generate NFO metadata",
                value=self.defaults.generate_nfo,
                id="generate_nfo",
            )

            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Create setup files", id="submit", variant="primary")

        yield Footer()

    def on_mount(self) -> None:
        self._toggle_cookie_fields()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "cookie_source":
            self._toggle_cookie_fields()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "cancel":
            self.exit(None)
            return
        if button_id != "submit":
            return

        source = str(self.query_one("#cookie_source", Select).value)
        browser = str(self.query_one("#cookie_browser", Select).value)
        profile = self.query_one("#cookie_profile", Input).value.strip()
        answers = SetupAnswers(
            archive_directory=self.query_one("#archive_directory", Input).value.strip(),
            cookie_source="browser" if source == "browser" else "manual_file",
            cookie_browser=browser or self.defaults.cookie_browser,
            cookie_profile=profile if source == "browser" else "",
            write_subtitles=self.query_one("#write_subtitles", Checkbox).value,
            write_thumbnail=self.query_one("#write_thumbnail", Checkbox).value,
            generate_nfo=self.query_one("#generate_nfo", Checkbox).value,
        )
        if not answers.archive_directory:
            answers.archive_directory = self.defaults.archive_directory
        self.exit(answers)

    def action_cancel(self) -> None:
        self.exit(None)

    def _toggle_cookie_fields(self) -> None:
        source = str(self.query_one("#cookie_source", Select).value)
        show_browser_fields = source == "browser"
        display_mode = "block" if show_browser_fields else "none"
        self.query_one("#cookie_browser_label", Label).styles.display = display_mode
        self.query_one("#cookie_browser", Select).styles.display = display_mode
        self.query_one("#cookie_profile_label", Label).styles.display = display_mode
        self.query_one("#cookie_profile", Input).styles.display = display_mode


def run_textual_setup(defaults: SetupAnswers | None = None) -> SetupAnswers | None:
    """Run Textual setup and return collected answers."""
    app = FirstRunSetupApp(defaults or SetupAnswers())
    result = app.run()
    if result is None:
        return None
    return result
