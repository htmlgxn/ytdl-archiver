"""Safe append-only writer for playlists.toml entries."""

from dataclasses import dataclass
from pathlib import Path

import toml

from ..exceptions import PlaylistWriteError


@dataclass(frozen=True)
class PlaylistEntry:
    """Single playlists.toml entry."""

    id: str
    path: str
    name: str


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class PlaylistWriter:
    """Append entries to playlists.toml without rewriting existing content."""

    def __init__(self, playlists_path: Path):
        self.playlists_path = playlists_path.expanduser()

    def _existing_ids(self) -> set[str]:
        if not self.playlists_path.exists():
            return set()

        try:
            data = toml.loads(self.playlists_path.read_text(encoding="utf-8"))
        except (OSError, toml.TomlDecodeError, ValueError) as exc:
            raise PlaylistWriteError(
                f"Failed to parse existing playlists TOML: {exc}"
            ) from exc

        playlists = data.get("playlists", [])
        if not isinstance(playlists, list):
            raise PlaylistWriteError("Invalid playlists TOML schema: 'playlists' must be a list")

        ids: set[str] = set()
        for entry in playlists:
            if not isinstance(entry, dict):
                continue
            playlist_id = str(entry.get("id") or "").strip()
            if playlist_id:
                ids.add(playlist_id)
        return ids

    @staticmethod
    def _render_entry(entry: PlaylistEntry) -> str:
        return (
            "[[playlists]]\n"
            f"id = {_toml_str(entry.id)}\n"
            f"path = {_toml_str(entry.path)}\n"
            f"name = {_toml_str(entry.name)}\n"
        )

    def append_entries(self, entries: list[PlaylistEntry]) -> tuple[int, int]:
        """Append new entries, skipping duplicate playlist IDs."""
        normalized = []
        for entry in entries:
            playlist_id = entry.id.strip()
            playlist_path = entry.path.strip()
            playlist_name = entry.name.strip()
            if not playlist_id or not playlist_path or not playlist_name:
                raise PlaylistWriteError("Playlist entries require non-empty id, path, and name")
            normalized.append(
                PlaylistEntry(id=playlist_id, path=playlist_path, name=playlist_name)
            )

        existing_ids = self._existing_ids()
        entries_to_append: list[PlaylistEntry] = []
        skipped = 0
        for entry in normalized:
            if entry.id in existing_ids:
                skipped += 1
                continue
            entries_to_append.append(entry)
            existing_ids.add(entry.id)

        if not self.playlists_path.exists():
            try:
                self.playlists_path.parent.mkdir(parents=True, exist_ok=True)
                self.playlists_path.write_text("", encoding="utf-8")
            except OSError as exc:
                raise PlaylistWriteError(
                    f"Failed to create playlists file: {exc}"
                ) from exc

        if entries_to_append:
            try:
                existing_content = self.playlists_path.read_text(encoding="utf-8")
                needs_leading_newline = bool(existing_content) and not existing_content.endswith("\n")
                with self.playlists_path.open("a", encoding="utf-8") as handle:
                    if needs_leading_newline:
                        handle.write("\n")
                    if existing_content and existing_content.strip():
                        handle.write("\n")
                    for index, entry in enumerate(entries_to_append):
                        if index > 0:
                            handle.write("\n")
                        handle.write(self._render_entry(entry))
            except OSError as exc:
                raise PlaylistWriteError(
                    f"Failed to append playlists entries: {exc}"
                ) from exc

        return len(entries_to_append), skipped
