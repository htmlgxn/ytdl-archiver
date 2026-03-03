"""Metadata generation for media servers."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..exceptions import MetadataError

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


@dataclass
class NFOFields:
    """Normalized fields shared across NFO renderers."""

    title: str
    showtitle: str
    season: int
    episode: int
    plot: str
    outline: str
    aired: str
    premiered: str
    releasedate: str
    year: str
    runtime: int
    thumb: str
    uniqueid: str
    studio: str
    genres: list[str]
    tags: list[str]
    rating: str
    votes: str


class MetadataGenerator:
    """Generate NFO files for media servers like Jellyfin/Emby."""

    _THUMBNAIL_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

    def __init__(self, config):
        self.config = config

    def create_nfo_file(self, metadata: dict[str, Any], nfo_path: Path) -> None:
        """Create an NFO file from video metadata."""
        try:
            nfo_content = self._generate_nfo_content(metadata, nfo_path=nfo_path)

            with nfo_path.open("w", encoding="utf-8") as nfo_file:
                nfo_file.write(nfo_content)

            logger.info("NFO file created", extra={"nfo_path": str(nfo_path)})

        except (OSError, UnicodeEncodeError, ValueError) as e:
            logger.exception(
                "Error writing NFO file",
                extra={"nfo_path": str(nfo_path), "error": str(e)},
            )
            raise MetadataError(f"Error writing NFO file {nfo_path}: {e}") from e

    def create_tvshow_nfo(self, channel_name: str, nfo_path: Path) -> None:
        """Create a tvshow.nfo file for Jellyfin TV show library treatment."""
        try:
            nfo_content = self._generate_tvshow_nfo_content(channel_name)

            with nfo_path.open("w", encoding="utf-8") as nfo_file:
                nfo_file.write(nfo_content)

            logger.info("TV show NFO file created", extra={"nfo_path": str(nfo_path)})

        except (OSError, UnicodeEncodeError, ValueError) as e:
            logger.exception(
                "Error writing TV show NFO file",
                extra={"nfo_path": str(nfo_path), "error": str(e)},
            )
            raise MetadataError(f"Error writing TV show NFO file {nfo_path}: {e}") from e

    def _generate_tvshow_nfo_content(self, channel_name: str) -> str:
        """Generate tvshow.nfo content from channel name."""
        return f"""<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<tvshow>
  <title>{self._escape_xml(channel_name)}</title>
</tvshow>
"""

    def _first_thumbnail_sidecar(self, nfo_path: Path | None) -> str:
        if nfo_path is None:
            return ""
        for extension in self._THUMBNAIL_EXTENSIONS:
            thumbnail = nfo_path.with_suffix(extension)
            if thumbnail.exists():
                return thumbnail.name
        return ""

    @staticmethod
    def _parse_date(date_raw: str) -> datetime | None:
        raw = str(date_raw or "").strip()
        if len(raw) != 8 or not raw.isdigit():
            return None
        try:
            return datetime.strptime(raw, "%Y%m%d")
        except ValueError:
            return None

    @staticmethod
    def _coerce_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_float_str(value: Any) -> str:
        try:
            return f"{float(value):.2f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _coerce_str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for entry in value:
            item = str(entry or "").strip()
            if item:
                out.append(item)
        return out

    def _build_nfo_fields(
        self, metadata: dict[str, Any], nfo_path: Path | None = None
    ) -> NFOFields:
        title = str(metadata.get("title") or "Unknown Title")
        showtitle = str(
            metadata.get("channel")
            or metadata.get("uploader")
            or metadata.get("uploader_id")
            or "Unknown Channel"
        )
        description = str(metadata.get("description") or "Unknown Description")
        outline = " ".join(description.strip().split())
        outline = outline[:197] + "..." if len(outline) > 200 else outline

        date_value = self._parse_date(
            str(metadata.get("upload_date") or metadata.get("release_date") or "")
        )
        aired = date_value.strftime("%Y-%m-%d") if date_value else ""
        year = date_value.strftime("%Y") if date_value else ""

        playlist_index = self._coerce_int(metadata.get("playlist_index"), default=0)
        if playlist_index > 0:
            season = 1
            episode = playlist_index
        elif date_value is not None:
            season = date_value.year
            episode = date_value.timetuple().tm_yday
        else:
            season = 1
            episode = 0

        duration = max(0, self._coerce_int(metadata.get("duration"), default=0))
        video_id = str(metadata.get("id") or "Unknown ID")

        thumb = self._first_thumbnail_sidecar(nfo_path)
        if not thumb:
            thumb = str(metadata.get("thumbnail") or "")

        like_count = self._coerce_int(metadata.get("like_count"), default=0)
        view_count = self._coerce_int(metadata.get("view_count"), default=0)
        votes = str(like_count if like_count > 0 else max(0, view_count))
        if votes == "0":
            votes = ""

        return NFOFields(
            title=title,
            showtitle=showtitle,
            season=season,
            episode=episode,
            plot=description,
            outline=outline,
            aired=aired,
            premiered=aired,
            releasedate=aired,
            year=year,
            runtime=duration,
            thumb=thumb,
            uniqueid=video_id,
            studio=showtitle,
            genres=self._coerce_str_list(metadata.get("categories")),
            tags=self._coerce_str_list(metadata.get("tags")),
            rating=self._coerce_float_str(metadata.get("average_rating")),
            votes=votes,
        )

    def _generate_nfo_content(
        self, metadata: dict[str, Any], nfo_path: Path | None = None
    ) -> str:
        """Generate NFO content from metadata."""
        fields = self._build_nfo_fields(metadata, nfo_path=nfo_path)
        nfo_format = self.config.get("media_server.nfo_format", "kodi")

        if nfo_format == "kodi":
            return self._generate_kodi_nfo(fields)
        return self._generate_emby_nfo(fields)

    def _generate_kodi_nfo(self, fields: NFOFields) -> str:
        """Generate Kodi-compatible NFO content."""
        lines = [
            '<?xml version="1.0" encoding="utf-8" standalone="yes"?>',
            "<episodedetails>",
            f"  <title>{self._escape_xml(fields.title)}</title>",
            f"  <showtitle>{self._escape_xml(fields.showtitle)}</showtitle>",
            f"  <season>{fields.season}</season>",
            f"  <episode>{fields.episode}</episode>",
            f"  <id>{self._escape_xml(fields.uniqueid)}</id>",
            (
                f'  <uniqueid type="youtube" default="true">'
                f"{self._escape_xml(fields.uniqueid)}</uniqueid>"
            ),
            f"  <studio>{self._escape_xml(fields.studio)}</studio>",
            f"  <plot>{self._escape_xml(fields.plot)}</plot>",
            f"  <outline>{self._escape_xml(fields.outline)}</outline>",
            f"  <runtime>{fields.runtime}</runtime>",
        ]
        if fields.releasedate:
            lines.append(f"  <releasedate>{self._escape_xml(fields.releasedate)}</releasedate>")
        if fields.aired:
            lines.append(f"  <aired>{self._escape_xml(fields.aired)}</aired>")
            lines.append(f"  <premiered>{self._escape_xml(fields.premiered)}</premiered>")
        if fields.year:
            lines.append(f"  <year>{self._escape_xml(fields.year)}</year>")
        if fields.thumb:
            lines.append(f"  <thumb>{self._escape_xml(fields.thumb)}</thumb>")
        if fields.rating:
            lines.append(f"  <rating>{self._escape_xml(fields.rating)}</rating>")
        if fields.votes:
            lines.append(f"  <votes>{self._escape_xml(fields.votes)}</votes>")
        for genre in fields.genres:
            lines.append(f"  <genre>{self._escape_xml(genre)}</genre>")
        for tag in fields.tags:
            lines.append(f"  <tag>{self._escape_xml(tag)}</tag>")
        lines.append("</episodedetails>")
        lines.append("")
        return "\n".join(lines)

    def _generate_emby_nfo(self, fields: NFOFields) -> str:
        """Generate Emby-compatible NFO content."""
        lines = [
            '<?xml version="1.0" encoding="utf-8" standalone="yes"?>',
            "<Item>",
            f"  <Name>{self._escape_xml(fields.title)}</Name>",
            f"  <Id>{self._escape_xml(fields.uniqueid)}</Id>",
            f"  <SeriesName>{self._escape_xml(fields.showtitle)}</SeriesName>",
            f"  <SeasonNumber>{fields.season}</SeasonNumber>",
            f"  <EpisodeNumber>{fields.episode}</EpisodeNumber>",
            f"  <Studio>{self._escape_xml(fields.studio)}</Studio>",
            f"  <Overview>{self._escape_xml(fields.plot)}</Overview>",
            f"  <ShortOverview>{self._escape_xml(fields.outline)}</ShortOverview>",
            f"  <RunTimeTicks>{fields.runtime * 10000000}</RunTimeTicks>",
        ]
        if fields.premiered:
            lines.append(f"  <PremiereDate>{self._escape_xml(fields.premiered)}</PremiereDate>")
        if fields.year:
            lines.append(f"  <ProductionYear>{self._escape_xml(fields.year)}</ProductionYear>")
        if fields.thumb:
            lines.append(f"  <Thumb>{self._escape_xml(fields.thumb)}</Thumb>")
        if fields.rating:
            lines.append(f"  <CommunityRating>{self._escape_xml(fields.rating)}</CommunityRating>")
        if fields.votes:
            lines.append(f"  <VoteCount>{self._escape_xml(fields.votes)}</VoteCount>")
        for genre in fields.genres:
            lines.append(f"  <Genre>{self._escape_xml(genre)}</Genre>")
        for tag in fields.tags:
            lines.append(f"  <Tag>{self._escape_xml(tag)}</Tag>")
        lines.append("</Item>")
        lines.append("")
        return "\n".join(lines)

    def _escape_xml(self, text: str | None) -> str:
        """Escape XML special characters."""
        if not text:
            return ""

        text = text.replace("&", "&amp;")
        text = text.replace("<", "&lt;")
        text = text.replace(">", "&gt;")
        text = text.replace('"', "&quot;")
        return text.replace("'", "&apos;")
