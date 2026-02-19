"""Metadata generation for media servers."""

from pathlib import Path
from typing import Any

from ..exceptions import MetadataError

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


class MetadataGenerator:
    """Generate NFO files for media servers like Jellyfin/Emby."""

    def __init__(self, config):
        self.config = config

    def create_nfo_file(self, metadata: dict[str, Any], nfo_path: Path) -> None:
        """Create an NFO file from video metadata."""
        try:
            nfo_content = self._generate_nfo_content(metadata)

            with nfo_path.open("w", encoding="utf-8") as nfo_file:
                nfo_file.write(nfo_content)

            logger.info("NFO file created", extra={"nfo_path": str(nfo_path)})

        except (OSError, UnicodeEncodeError, ValueError) as e:
            logger.exception(
                "Error writing NFO file",
                extra={"nfo_path": str(nfo_path), "error": str(e)},
            )
            raise MetadataError(f"Error writing NFO file {nfo_path}: {e}") from e

    def _generate_nfo_content(self, metadata: dict[str, Any]) -> str:
        """Generate NFO content from metadata."""
        title = metadata.get("title", "Unknown Title")
        channel = metadata.get("uploader", "Unknown Channel")
        upload_date = metadata.get("upload_date", "")
        formatted_date = (
            f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
            if upload_date
            else "Unknown Date"
        )
        upload_year = f"{upload_date[:4]}" if upload_date else "Unknown Year"
        description = metadata.get("description", "Unknown Description")
        video_id = metadata.get("id", "Unknown ID")
        duration = metadata.get("duration", 0)

        nfo_format = self.config.get("media_server.nfo_format", "kodi")

        if nfo_format == "kodi":
            return self._generate_kodi_nfo(
                title,
                video_id,
                channel,
                formatted_date,
                upload_year,
                description,
                duration,
            )
        return self._generate_emby_nfo(
            title,
            video_id,
            channel,
            formatted_date,
            upload_year,
            description,
            duration,
        )

    def _generate_kodi_nfo(
        self,
        title: str,
        video_id: str,
        channel: str,
        formatted_date: str,
        upload_year: str,
        description: str,
        duration: int,
    ) -> str:
        """Generate Kodi-compatible NFO content."""
        return f"""<episodedetails>
  <title>{self._escape_xml(title)}</title>
  <id>{self._escape_xml(video_id)}</id>
  <studio>{self._escape_xml(channel)}</studio>
  <releasedate>{self._escape_xml(formatted_date)}</releasedate>
  <year>{self._escape_xml(upload_year)}</year>
  <plot>{self._escape_xml(description)}</plot>
  <runtime>{duration}</runtime>
</episodedetails>
"""

    def _generate_emby_nfo(
        self,
        title: str,
        video_id: str,
        channel: str,
        formatted_date: str,
        upload_year: str,
        description: str,
        duration: int,
    ) -> str:
        """Generate Emby-compatible NFO content."""
        return f"""<Item>
  <Name>{self._escape_xml(title)}</Name>
  <Id>{self._escape_xml(video_id)}</Id>
  <Studio>{self._escape_xml(channel)}</Studio>
  <PremiereDate>{self._escape_xml(formatted_date)}</PremiereDate>
  <ProductionYear>{self._escape_xml(upload_year)}</ProductionYear>
  <Overview>{self._escape_xml(description)}</Overview>
  <RunTimeTicks>{duration * 10000000}</RunTimeTicks>
</Item>
"""

    def _escape_xml(self, text: str | None) -> str:
        """Escape XML special characters."""
        if not text:
            return ""

        # Basic XML escaping
        text = text.replace("&", "&amp;")
        text = text.replace("<", "&lt;")
        text = text.replace(">", "&gt;")
        text = text.replace('"', "&quot;")
        return text.replace("'", "&apos;")
