"""Tests for append-only playlists TOML writer."""

import pytest

from ytdl_archiver.core.playlist_writer import PlaylistEntry, PlaylistWriter
from ytdl_archiver.exceptions import PlaylistWriteError


class TestPlaylistWriter:
    def test_append_entries_adds_without_overwriting_existing_content(self, temp_dir):
        playlists_path = temp_dir / "playlists.toml"
        playlists_path.write_text(
            "# existing\n\n[[playlists]]\nid = \"PL1\"\npath = \"old\"\nname = \"Old\"\n",
            encoding="utf-8",
        )
        writer = PlaylistWriter(playlists_path)

        added, skipped = writer.append_entries(
            [PlaylistEntry(id="PL2", path="new-path", name="New Name")]
        )

        assert added == 1
        assert skipped == 0
        content = playlists_path.read_text(encoding="utf-8")
        assert "# existing" in content
        assert 'id = "PL1"' in content
        assert 'id = "PL2"' in content
        assert 'path = "new-path"' in content
        assert 'name = "New Name"' in content

    def test_append_entries_skips_duplicate_ids(self, temp_dir):
        playlists_path = temp_dir / "playlists.toml"
        playlists_path.write_text(
            "[[playlists]]\nid = \"PL1\"\npath = \"old\"\nname = \"Old\"\n",
            encoding="utf-8",
        )
        writer = PlaylistWriter(playlists_path)

        added, skipped = writer.append_entries(
            [
                PlaylistEntry(id="PL1", path="duplicate", name="Duplicate"),
                PlaylistEntry(id="PL2", path="new", name="New"),
            ]
        )

        assert added == 1
        assert skipped == 1
        content = playlists_path.read_text(encoding="utf-8")
        assert content.count('id = "PL1"') == 1
        assert content.count('id = "PL2"') == 1

    def test_append_entries_creates_missing_file(self, temp_dir):
        playlists_path = temp_dir / "new-playlists.toml"
        writer = PlaylistWriter(playlists_path)

        added, skipped = writer.append_entries(
            [PlaylistEntry(id="PLX", path="created", name="Created")]
        )

        assert added == 1
        assert skipped == 0
        assert playlists_path.exists()
        content = playlists_path.read_text(encoding="utf-8")
        assert "[[playlists]]" in content
        assert 'id = "PLX"' in content

    def test_append_entries_invalid_toml_raises(self, temp_dir):
        playlists_path = temp_dir / "playlists.toml"
        playlists_path.write_text("[[playlists]\n", encoding="utf-8")
        writer = PlaylistWriter(playlists_path)

        with pytest.raises(PlaylistWriteError, match="Failed to parse existing playlists TOML"):
            writer.append_entries([PlaylistEntry(id="PLX", path="x", name="X")])
