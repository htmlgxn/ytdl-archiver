"""Non-Textual setup collection helpers."""

import sys

import click

from ..core.cookies import SUPPORTED_BROWSERS
from .models import SetupAnswers


def is_interactive_session() -> bool:
    """Return True when both stdin and stdout are interactive terminals."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def collect_non_interactive_answers(
    defaults: SetupAnswers | None = None,
) -> SetupAnswers:
    """Return deterministic defaults for non-interactive environments."""
    return defaults or SetupAnswers()


def collect_prompt_answers(defaults: SetupAnswers | None = None) -> SetupAnswers:
    """Collect setup answers via Click prompts."""
    values = defaults or SetupAnswers()

    click.echo("First-run setup")
    click.echo("Press Enter to accept defaults.")

    archive_directory = click.prompt(
        "Archive directory",
        default=values.archive_directory,
        show_default=True,
    )

    cookie_source = click.prompt(
        "Cookie source",
        type=click.Choice(["browser", "manual_file"], case_sensitive=False),
        default=values.cookie_source,
        show_default=True,
    ).lower()

    cookie_browser = values.cookie_browser
    cookie_profile = values.cookie_profile
    if cookie_source == "browser":
        cookie_browser = click.prompt(
            "Browser for cookie refresh",
            type=click.Choice(list(SUPPORTED_BROWSERS), case_sensitive=False),
            default=values.cookie_browser,
            show_default=True,
        ).lower()
        cookie_profile = click.prompt(
            "Browser profile (optional, blank for auto)",
            default=values.cookie_profile,
            show_default=False,
        ).strip()
    else:
        cookie_profile = ""

    write_subtitles = click.confirm(
        "Download subtitles",
        default=values.write_subtitles,
        show_default=True,
    )
    write_thumbnail = click.confirm(
        "Download thumbnails",
        default=values.write_thumbnail,
        show_default=True,
    )
    generate_nfo = click.confirm(
        "Generate NFO metadata",
        default=values.generate_nfo,
        show_default=True,
    )

    return SetupAnswers(
        archive_directory=archive_directory,
        cookie_source=cookie_source,
        cookie_browser=cookie_browser,
        cookie_profile=cookie_profile,
        write_subtitles=write_subtitles,
        write_thumbnail=write_thumbnail,
        generate_nfo=generate_nfo,
    )
