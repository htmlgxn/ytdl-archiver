"""Enhanced output formatters for ytdl-archiver CLI."""

import sys
from typing import Optional, Any, Dict
from enum import Enum

try:
    import colorama
    from tqdm import tqdm
    COLOR_SUPPORT = True
except ImportError:
    COLOR_SUPPORT = False


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
        PURPLE = colorama.Fore.MAGENTA
        ORANGE = colorama.Fore.LIGHTYELLOW_EX
        TEAL = colorama.Fore.CYAN
        RESET = colorama.Fore.RESET
        BOLD = colorama.Style.BRIGHT
    else:
        GREEN = BLUE = YELLOW = RED = PURPLE = ORANGE = TEAL = RESET = BOLD = ""


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


class ProgressFormatter:
    """Clean, colored output with progress bars for normal usage."""
    
    def __init__(self, use_colors: bool = True, show_progress: bool = True):
        self.use_colors = use_colors
        self.show_progress = show_progress
        self.playlist_progress = None
    
    def _colorize(self, text: str, color: str) -> str:
        """Apply color if enabled."""
        if self.use_colors and COLOR_SUPPORT:
            return f"{color}{text}{Colors.RESET}"
        return text
    
    def _symbolize(self, symbol: str) -> str:
        """Get symbol if colors enabled."""
        return symbol if self.use_colors else ""
    
    def header(self, version: str) -> str:
        """Print application header."""
        header = self._colorize(f"ytdl-archiver v{version}", Colors.PURPLE)
        return f"\n{Symbols.HEADER} {header}\n"
    
    def playlist_start(self, name: str, video_count: int) -> str:
        """Print playlist processing start."""
        playlist = self._colorize(f"Processing: {name} ({video_count} videos)", Colors.ORANGE)
        return f"{Symbols.PLAYLIST} {playlist}"
    
    def video_progress(self, title: str, progress_data: Dict[str, Any]) -> str:
        """Print video download progress."""
        if not self.show_progress:
            return ""
        
        # Extract progress information
        percent = progress_data.get('percent', 0)
        speed = progress_data.get('speed', '')
        eta = progress_data.get('eta', '')
        
        # Create progress bar
        bar_length = 20
        filled = int(bar_length * percent / 100)
        bar = '█' * filled + '░' * (bar_length - filled)
        
        progress = self._colorize(
            f"Download: {title} [{bar}] {percent}%",
            Colors.BLUE
        )
        
        details = []
        if speed:
            details.append(f"{speed}")
        if eta:
            details.append(f"ETA: {eta}")
        
        if details:
            progress += f" ({', '.join(details)})"
        
        return f"{Symbols.PROGRESS} {progress}"
    
    def video_complete(self, title: str, resolution: str = "", size: str = "") -> str:
        """Print video completion message."""
        complete = self._colorize("Downloaded:", Colors.GREEN)
        parts = [complete, title]
        
        if resolution:
            parts.append(f"[{resolution}]")
        if size:
            parts.append(f"{size}")
        
        return f"{Symbols.SUCCESS} {' '.join(parts)}"
    
    def file_generated(self, file_type: str) -> str:
        """Print file generation message."""
        generated = self._colorize("Generated:", Colors.GREEN)
        return f"{Symbols.SUCCESS} {generated} {file_type}"
    
    def warning(self, message: str) -> str:
        """Print warning message."""
        warn = self._colorize("Warning:", Colors.YELLOW)
        return f"{Symbols.WARNING} {warn} {message}"
    
    def error(self, message: str) -> str:
        """Print error message."""
        err = self._colorize("Error:", Colors.RED)
        return f"{Symbols.ERROR} {err} {message}"
    
    def js_runtime_warning(self) -> str:
        """Print JavaScript runtime warning."""
        warning = self._colorize("YouTube features limited", Colors.YELLOW)
        info = self._colorize("Install Deno/Node.js for full YouTube support", Colors.INFO)
        return f"{Symbols.WARNING} {warning} - JavaScript runtime unavailable\n{Symbols.INFO} {info}"
    
    def playlist_summary(self, stats: Dict[str, int]) -> str:
        """Print playlist completion summary."""
        summary = self._colorize("Playlist Complete:", Colors.TEAL)
        parts = []
        
        if stats.get('new', 0) > 0:
            parts.append(f"{stats['new']} new")
        if stats.get('skipped', 0) > 0:
            parts.append(f"{stats['skipped']} skipped")
        if stats.get('failed', 0) > 0:
            parts.append(f"{stats['failed']} failed")
        
        return f"{Symbols.SUMMARY} {summary} {', '.join(parts)}"


class QuietFormatter:
    """Minimal output - errors and summary only."""
    
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
    
    def error(self, message: str) -> str:
        """Print error message only."""
        err = self._colorize("Error:", Colors.RED)
        return f"{self._symbolize(Symbols.ERROR)} {err} {message}"
    
    def warning(self, message: str) -> str:
        """Print warning message only."""
        warn = self._colorize("Warning:", Colors.YELLOW)
        return f"{self._symbolize(Symbols.WARNING)} {warn} {message}"
    
    def summary(self, stats: Dict[str, int]) -> str:
        """Print final summary."""
        summary = self._colorize("Summary:", Colors.TEAL)
        parts = []
        
        if stats.get('downloaded', 0) > 0:
            parts.append(f"{stats['downloaded']} downloaded")
        if stats.get('failed', 0) > 0:
            parts.append(f"{stats['failed']} failed")
        
        return f"{self._symbolize(Symbols.SUMMARY)} {summary} {', '.join(parts)}"


class VerboseFormatter:
    """Full technical output with yt-dlp details and colors."""
    
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
    
    def info(self, message: str) -> str:
        """Print informational message."""
        info = self._colorize("Info:", Colors.BLUE)
        return f"{self._symbolize(Symbols.INFO)} {info} {message}"
    
    def debug(self, message: str) -> str:
        """Print debug message."""
        debug = self._colorize("Debug:", Colors.PURPLE)
        return f"{self._symbolize(Symbols.HEADER)} {debug} {message}"
    
    def error(self, message: str) -> str:
        """Print error message."""
        err = self._colorize("Error:", Colors.RED)
        return f"{self._symbolize(Symbols.ERROR)} {err} {message}"
    
    def warning(self, message: str) -> str:
        """Print warning message."""
        warn = self._colorize("Warning:", Colors.YELLOW)
        return f"{self._symbolize(Symbols.WARNING)} {warn} {message}"
    
    def js_runtime_warning(self) -> str:
        """Print JavaScript runtime warning with technical details."""
        warning = self._colorize("JavaScript Runtime Warning", Colors.YELLOW)
        info = self._colorize("YouTube extraction without JS runtime has been deprecated", Colors.INFO)
        return f"{self._symbolize(Symbols.WARNING)} {warning}\n{self._symbolize(Symbols.INFO)} {info}"


def get_formatter(use_colors: bool = True, show_progress: bool = True, 
                mode: OutputMode = OutputMode.PROGRESS) -> Any:
    """Get appropriate formatter based on mode."""
    if mode == OutputMode.QUIET:
        return QuietFormatter(use_colors)
    elif mode == OutputMode.VERBOSE:
        return VerboseFormatter(use_colors)
    else:
        return ProgressFormatter(use_colors, show_progress)


def detect_output_mode(verbose: bool, quiet: bool) -> OutputMode:
    """Detect output mode from flags."""
    if quiet:
        return OutputMode.QUIET
    elif verbose:
        return OutputMode.VERBOSE
    else:
        return OutputMode.PROGRESS


def should_use_colors(no_color: bool) -> bool:
    """Determine if colors should be used."""
    if no_color:
        return False
    return COLOR_SUPPORT and sys.stdout.isatty()