"""Tests for repo-relative POSIX path normalization."""

from pathlib import Path

import pytest

from src.codeparse_mcp.paths import normalize_repo_file_path


def test_normalize_relative_posix(tmp_path: Path) -> None:
    root = tmp_path
    assert normalize_repo_file_path("src/db.py", root) == "src/db.py"
    assert normalize_repo_file_path(r"src\db.py", root) == "src/db.py"
    assert normalize_repo_file_path("./src/db.py", root) == "src/db.py"


def test_normalize_absolute_under_root(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    abs_path = root / "pkg" / "mod.py"
    assert normalize_repo_file_path(str(abs_path), root) == "pkg/mod.py"


def test_normalize_rejects_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "other" / "x.py"
    with pytest.raises(ValueError, match="outside the workspace ROOT"):
        normalize_repo_file_path(str(outside), root)
    with pytest.raises(ValueError, match="outside the workspace ROOT"):
        normalize_repo_file_path("../other/x.py", root)


def test_normalize_rejects_empty(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        normalize_repo_file_path("  ", tmp_path)
