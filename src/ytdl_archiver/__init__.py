"""ytdl-archiver: Modern Python CLI for archiving YouTube playlists with media-server-friendly sidecar files"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ytdl-archiver")
except PackageNotFoundError:
    __version__ = "0+unknown"

__author__ = "Ben Chitty"
__email__ = "htmlgxn@pm.me"
