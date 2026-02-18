"""Enhanced output formatters for ytdl-archiver CLI."""

import sys
from enum import Enum
from typing import Any

try:
    import colorama
    from tqdm import tqdm

    COLOR_SUPPORT = True
except ImportError:
    COLOR_SUPPORT = False
    tqdm = None


class OutputMode(Enum):
    """Output verbosity modes."""

    PROGRESS = "progress"
    QUIET = "quiet"
    VERBOSE = "verbose"


class Colors:
    """Color constants for terminal output."""

    if COLOR_SUPPORT:
        colorama.init()
        GREEN = colorama.Fore.GREEN
        BLUE = colorama.Fore.BLUE
        YELLOW = colorama.Fore.YELLOW
        RED = colorama.Fore.RED
        GRAY = colorama.Fore.LIGHTBLACK_EX
        PURPLE = colorama.Fore.MAGENTA
        ORANGE = colorama.Fore.LIGHTYELLOW_EX
        TEAL = colorama.Fore.CYAN
        INFO = colorama.Fore.CYAN
        RESET = colorama.Fore.RESET
        BOLD = colorama.Style.BRIGHT
    else:
        GREEN = BLUE = YELLOW = RED = GRAY = PURPLE = ORANGE = TEAL = INFO = RESET = BOLD = ""


class Symbols:
    """Symbol constants for status indicators."""

    if COLOR_SUPPORT:
        SUCCESS = "✅"
        PROGRESS = "🔵"
        WARNING = "⚠️"
        ERROR = "❌"
        HEADER = "📺"
        PLAYLIST = "📋"
        SUMMARY = "📊"
        INFO = "ℹ️"
    else:
        SUCCESS = "[OK]"
        PROGRESS = "[>>]"
        WARNING = "[WARN]"
        ERROR = "[ERR]"
        HEADER = "[YTD]"
        PLAYLIST = "[PL]"
        SUMMARY = "[SUM]"
        INFO = "[INFO]"


class BaseFormatter:
    """Shared formatter behavior for all output modes."""

    def __init__(self, use_colors: bool = True):
        self.use_colors = use_colors

    def _colorize(self, text: str, color: str) -> str:
        """Apply color if enabled."""
        if self.use_colors and COLOR_SUPPORT:
            return f"{color}{text}{Colors.RESET}"
        return text

    def _symbolize(self, symbol: str) -> str:
        """Get symbol if colors enabled."""
        return symbol if self.use_colors else ""

    @staticmethod
    def _status_label_width() -> int:
        """Fixed width to align titles across status lines."""
        return len("Thumbnail generated:")

    def _status_label(self, text: str, color: str = Colors.GREEN) -> str:
        """Build a padded, colorized status label."""
        padded = f"{text:<{self._status_label_width()}}"
        return self._colorize(padded, color)

    def header(self, version: str) -> str:
        """Print application header."""
        app_name = self._colorize("ytdl-archiver", Colors.RED)
        app_version = self._colorize(f"v{version}", Colors.GRAY)
        header = f"{app_name} {app_version}"
        return f"\n{Symbols.HEADER} {header}\n"

    def playlist_start(
        self, name: str, video_count: int, include_videos_label: bool = True
    ) -> str:
        """Print playlist processing start."""
        count_display = (
            f"{video_count} videos" if include_videos_label else f"{video_count}"
        )
        playlist = self._colorize(
            f"Processing: {name} ({count_display})", Colors.ORANGE
        )
        return f"{Symbols.PLAYLIST} {playlist}"

    @staticmethod
    def _normalize_extension(extension: str) -> str:
        """Normalize extension to .ext format."""
        ext = extension.strip().lower()
        if not ext:
            return ""
        if not ext.startswith("."):
            return f".{ext}"
        return ext

    def video_complete(
        self, title: str, resolution: str = "", extension: str = "", size: str = ""
    ) -> str:
        """Print video completion message."""
        complete = self._status_label("Downloaded:")
        parts = [complete, title]

        ext = self._normalize_extension(extension)
        bracket_bits = []
        if resolution:
            bracket_bits.append(resolution)
        if ext:
            bracket_bits.append(ext)
        if size:
            bracket_bits.append(size)
        if bracket_bits:
            parts.append(f"[{', '.join(bracket_bits)}]")

        return f"{Symbols.SUCCESS} {' '.join(parts)}"

    def artifact_complete(
        self, title: str, extension: str = "", artifact_type: str = ""
    ) -> str:
        """Print sidecar artifact completion message."""
        complete = self._status_label("Downloaded:")
        parts = [complete, title]
        bracket_bits = []
        if artifact_type:
            bracket_bits.append(artifact_type)
        ext = self._normalize_extension(extension)
        if ext:
            bracket_bits.append(ext)
        if bracket_bits:
            parts.append(f"[{', '.join(bracket_bits)}]")
        return f"{Symbols.SUCCESS} {' '.join(parts)}"

    def thumbnail_generated(self, title: str, extension: str = "") -> str:
        """Print thumbnail generation message."""
        label = self._status_label("Thumbnail generated:")
        parts = [label, title]
        ext = self._normalize_extension(extension)
        if ext:
            parts.append(f"[{ext}]")
        return f"{Symbols.SUCCESS} {' '.join(parts)}"

    def mp4_generated(self, title: str, resolution: str = "", size: str = "") -> str:
        """Print final mp4 generation message."""
        label = self._status_label(".mp4 generated:")
        parts = [label, title]
        bracket_bits = []
        if resolution:
            bracket_bits.append(resolution)
        if size:
            bracket_bits.append(size)
        if bracket_bits:
            parts.append(f"[{', '.join(bracket_bits)}]")
        return f"{Symbols.SUCCESS} {' '.join(parts)}"

    def file_generated(self, file_type: str) -> str:
        """Print file generation message."""
        generated = self._colorize("Generated:", Colors.GREEN)
        return f"{Symbols.SUCCESS} {generated} {file_type}"

    def warning(self, message: str) -> str:
        """Print warning message."""
        warn = self._colorize("Warning:", Colors.YELLOW)
        return f"{Symbols.WARNING} {warn} {message}"

    def already_downloaded(self, count: int) -> str:
        """Print aggregated already-downloaded summary."""
        label = self._colorize("Already downloaded:", Colors.YELLOW)
        return f"{Symbols.WARNING} {label} {count} videos"

    def error(self, message: str) -> str:
        """Print error message."""
        err = self._colorize("Error:", Colors.RED)
        return f"{Symbols.ERROR} {err} {message}"

    def js_runtime_warning(self) -> str:
        """Print JavaScript runtime warning."""
        warning = self._colorize("YouTube features limited", Colors.YELLOW)
        info = self._colorize(
            "Install Deno/Node.js for full YouTube support", Colors.INFO
        )
        return (
            f"{Symbols.WARNING} {warning} - JavaScript runtime unavailable\n"
            f"{Symbols.INFO} {info}"
        )

    def playlist_summary(self, stats: dict[str, int]) -> str:
        """Print playlist completion summary."""
        summary = self._colorize("Playlist Complete:", Colors.TEAL)
        parts = []

        if stats.get("new", 0) > 0:
            parts.append(f"{stats['new']} new")
        if stats.get("failed", 0) > 0:
            parts.append(f"{stats['failed']} failed")

        if not parts:
            parts.append("already up to date")

        return f"{Symbols.SUMMARY} {summary} {', '.join(parts)}"


class ProgressFormatter(BaseFormatter):
    """Clean, colored output with progress bars for normal usage."""

    def __init__(self, use_colors: bool = True, show_progress: bool = True):
        super().__init__(use_colors)
        self.show_progress = show_progress
        self._current_progress_bar = None
        self._current_video_title = None

    def video_progress(self, title: str, progress_data: dict[str, Any]) -> str:
        """Print video download progress."""
        if not self.show_progress:
            return ""

        percent_str = str(progress_data.get("percent") or "0%")
        try:
            percent = float(percent_str.replace("%", ""))
        except (ValueError, AttributeError):
            percent = 0

        speed = progress_data.get("speed", "").strip()
        eta = progress_data.get("eta", "").strip()

        bar_length = 15
        filled = int(bar_length * percent / 100)
        bar = "█" * filled + "░" * (bar_length - filled)

        max_title_len = 30
        if len(title) > max_title_len:
            title = title[: max_title_len - 3] + "..."

        progress = self._colorize(f"{title} [{bar}] {percent_str}", Colors.BLUE)

        details = []
        if speed:
            details.append(speed)
        if eta:
            details.append(f"ETA: {eta}")

        if details:
            progress += f" {', '.join(details)}"

        return f"{Symbols.PROGRESS} {progress}"

    def start_video_progress(self, title: str) -> None:
        """Start a new video download progress bar using tqdm."""
        if not self.show_progress or tqdm is None:
            return

        self.close_video_progress()

        max_title_len = 40
        display_title = title
        if len(title) > max_title_len:
            display_title = title[: max_title_len - 3] + "..."

        self._current_video_title = title
        self._current_progress_bar = tqdm(
            total=100,
            desc=f"{Symbols.PROGRESS} {display_title}",
            bar_format="{desc} {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
            ncols=100,
            unit="%",
            position=0,
            leave=False,
            file=sys.stdout,
        )

    def update_video_progress(self, progress_data: dict[str, Any]) -> None:
        """Update the current video download progress bar."""
        if not self.show_progress or self._current_progress_bar is None:
            return

        percent_str = str(progress_data.get("percent") or "0%")
        try:
            percent = float(percent_str.replace("%", ""))
        except (ValueError, AttributeError):
            percent = 0

        self._current_progress_bar.n = percent

        speed = progress_data.get("speed", "").strip()
        if speed:
            self._current_progress_bar.set_postfix_str(speed)

        self._current_progress_bar.update(0)

    def close_video_progress(self) -> None:
        """Close the current video download progress bar."""
        if self._current_progress_bar is not None:
            self._current_progress_bar.close()
            self._current_progress_bar = None
            self._current_video_title = None


class QuietFormatter(BaseFormatter):
    """Minimal output - errors and summary only."""

    def error(self, message: str) -> str:
        """Print error message only."""
        err = self._colorize("Error:", Colors.RED)
        return f"{self._symbolize(Symbols.ERROR)} {err} {message}"

    def warning(self, message: str) -> str:
        """Print warning message only."""
        warn = self._colorize("Warning:", Colors.YELLOW)
        return f"{self._symbolize(Symbols.WARNING)} {warn} {message}"

    def already_downloaded(self, count: int) -> str:
        """Print aggregated already-downloaded summary."""
        label = self._colorize("Already downloaded:", Colors.YELLOW)
        return f"{self._symbolize(Symbols.WARNING)} {label} {count} videos"

    def summary(self, stats: dict[str, int]) -> str:
        """Print final summary."""
        summary = self._colorize("Summary:", Colors.TEAL)
        parts = []

        if stats.get("downloaded", 0) > 0:
            parts.append(f"{stats['downloaded']} downloaded")
        if stats.get("failed", 0) > 0:
            parts.append(f"{stats['failed']} failed")

        return f"{self._symbolize(Symbols.SUMMARY)} {summary} {', '.join(parts)}"

    def header(self, version: str) -> str:
        """Print application header (quiet mode - minimal)."""
        _ = version
        return ""

    def playlist_start(
        self, name: str, video_count: int, include_videos_label: bool = True
    ) -> str:
        """Print playlist processing start (quiet mode - minimal)."""
        _ = (name, video_count, include_videos_label)
        return ""

    def start_video_progress(self, title: str) -> None:
        """Start video progress tracking (quiet mode - no-op)."""
        _ = title

    def update_video_progress(self, progress_data: dict[str, Any]) -> None:
        """Update video progress (quiet mode - no-op)."""
        _ = progress_data

    def close_video_progress(self) -> None:
        """Close video progress (quiet mode - no-op)."""

    def video_complete(
        self, title: str, resolution: str = "", extension: str = "", size: str = ""
    ) -> str:
        """Print video completion (quiet mode - minimal)."""
        _ = (title, resolution, extension, size)
        return ""

    def artifact_complete(
        self, title: str, extension: str = "", artifact_type: str = ""
    ) -> str:
        """Print artifact completion (quiet mode - minimal)."""
        _ = (title, extension, artifact_type)
        return ""

    def thumbnail_generated(self, title: str, extension: str = "") -> str:
        """Print thumbnail generation (quiet mode - minimal)."""
        _ = (title, extension)
        return ""

    def mp4_generated(self, title: str, resolution: str = "", size: str = "") -> str:
        """Print mp4 generation (quiet mode - minimal)."""
        _ = (title, resolution, size)
        return ""

    def file_generated(self, file_type: str) -> str:
        """Print file generation (quiet mode - minimal)."""
        _ = file_type
        return ""

    def playlist_summary(self, stats: dict[str, int]) -> str:
        """Print playlist completion summary (quiet mode - errors only)."""
        if stats.get("failed", 0) > 0:
            return f"Failed: {stats['failed']} videos"
        return ""


class VerboseFormatter(BaseFormatter):
    """Full technical output with yt-dlp details and colors."""

    def info(self, message: str) -> str:
        """Print informational message."""
        info = self._colorize("Info:", Colors.BLUE)
        return f"{self._symbolize(Symbols.INFO)} {info} {message}"

    def debug(self, message: str) -> str:
        """Print debug message."""
        debug = self._colorize("Debug:", Colors.PURPLE)
        return f"{self._symbolize(Symbols.HEADER)} {debug} {message}"

    def js_runtime_warning(self) -> str:
        """Print JavaScript runtime warning with technical details."""
        warning = self._colorize("JavaScript Runtime Warning", Colors.YELLOW)
        info = self._colorize(
            "YouTube extraction without JS runtime has been deprecated", Colors.INFO
        )
        return (
            f"{self._symbolize(Symbols.WARNING)} {warning}\n"
            f"{self._symbolize(Symbols.INFO)} {info}"
        )

    def header(self, version: str) -> str:
        """Print application header."""
        header = self._colorize(
            f"ytdl-archiver v{version} (verbose mode)", Colors.PURPLE
        )
        return f"\n{Symbols.HEADER} {header}\n"

    def start_video_progress(self, title: str) -> None:
        """Start video progress tracking (verbose mode uses info messages)."""
        max_title_len = 40
        display_title = title
        if len(title) > max_title_len:
            display_title = title[: max_title_len - 3] + "..."
        print(self.info(f"Starting download: {display_title}"))

    def update_video_progress(self, progress_data: dict[str, Any]) -> None:
        """Update video progress (verbose mode shows detailed info)."""
        percent = progress_data.get("percent", "0%")
        speed = progress_data.get("speed", "").strip()
        eta = progress_data.get("eta", "").strip()

        details = []
        if speed:
            details.append(f"speed: {speed}")
        if eta:
            details.append(f"eta: {eta}")

        if details:
            print(self.debug(f"Download progress: {percent} ({', '.join(details)})"))

    def close_video_progress(self) -> None:
        """Close video progress (verbose mode - no-op)."""


def render_formatter_message(formatter: Any, level: str, message: str) -> str:
    """Render a formatter message if a level method exists."""
    if not formatter:
        return ""

    formatter_fn = getattr(formatter, level, None)
    if formatter_fn is None:
        return ""

    rendered = formatter_fn(message)
    if not rendered:
        return ""

    return str(rendered)


def emit_formatter_message(formatter: Any, level: str, message: str) -> None:
    """Render and print a formatter message if available."""
    rendered = render_formatter_message(formatter, level, message)
    if rendered:
        for line in str(rendered).splitlines():
            if tqdm is not None:
                tqdm.write(line)
            else:
                print(line)


def emit_rendered(message: str) -> None:
    """Print a pre-rendered message when non-empty."""
    if message:
        for line in str(message).splitlines():
            if tqdm is not None:
                tqdm.write(line)
            else:
                print(line)


def get_formatter(
    use_colors: bool = True,
    show_progress: bool = True,
    mode: OutputMode = OutputMode.PROGRESS,
) -> Any:
    """Get appropriate formatter based on mode."""
    if mode == OutputMode.QUIET:
        return QuietFormatter(use_colors)
    if mode == OutputMode.VERBOSE:
        return VerboseFormatter(use_colors)
    return ProgressFormatter(use_colors, show_progress)


def detect_output_mode(verbose: bool, quiet: bool) -> OutputMode:
    """Detect output mode from flags."""
    if quiet:
        return OutputMode.QUIET
    if verbose:
        return OutputMode.VERBOSE
    return OutputMode.PROGRESS


def should_use_colors(no_color: bool) -> bool:
    """Determine if colors should be used."""
    if no_color:
        return False
    return COLOR_SUPPORT and sys.stdout.isatty()
