"""Tests for package version fallback resolution."""

from pathlib import Path

from ytdl_archiver import _version_from_pyproject


def test_version_from_pyproject_reads_project_version(tmp_path: Path) -> None:
    """Version is read from nearest parent pyproject.toml."""
    repo_root = tmp_path / "repo"
    package_file = repo_root / "src" / "ytdl_archiver" / "__init__.py"
    package_file.parent.mkdir(parents=True, exist_ok=True)
    package_file.write_text("# package marker\n")
    (repo_root / "pyproject.toml").write_text(
        '[project]\nname = "ytdl-archiver"\nversion = "9.8.7"\n'
    )

    assert _version_from_pyproject(package_file) == "9.8.7"


def test_version_from_pyproject_returns_none_without_file(tmp_path: Path) -> None:
    """Missing pyproject.toml yields no fallback version."""
    package_file = tmp_path / "src" / "ytdl_archiver" / "__init__.py"
    package_file.parent.mkdir(parents=True, exist_ok=True)
    package_file.write_text("# package marker\n")

    assert _version_from_pyproject(package_file) is None
