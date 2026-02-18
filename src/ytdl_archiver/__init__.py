"""YTDL-Archiver: Modern YouTube playlist archiver."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ytdl-archiver")
except PackageNotFoundError:
    __version__ = "0+unknown"

__author__ = "Ben Chitty / @htmlgxn"
__email__ = "htmlgxn@pm.me"
