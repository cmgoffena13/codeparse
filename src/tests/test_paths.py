"""Tests for repo-relative POSIX path normalization."""

from pathlib import Path

import pytest

from src.codeparse_mcp.find_importers import find_importers
from src.codeparse_mcp.paths import normalize_repo_file_path
from src.db import CodeDB
from src.processor import CodeProcessor


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
    with pytest.raises(ValueError, match="outside the workspace root"):
        normalize_repo_file_path(str(outside), root)
    with pytest.raises(ValueError, match="outside the workspace root"):
        normalize_repo_file_path("../other/x.py", root)


def test_normalize_rejects_empty(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        normalize_repo_file_path("  ", tmp_path)


def test_find_importers_notes_truncation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".gitignore").write_text("# test\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "target.py").write_text("def helper() -> int:\n    return 1\n", encoding="utf-8")
    (pkg / "a.py").write_text("from pkg.target import helper\n", encoding="utf-8")
    (pkg / "b.py").write_text("from pkg.target import helper\n", encoding="utf-8")
    monkeypatch.setattr("src.codeparse_mcp.find_importers._MAX_IMPORTER_FILES", 1)
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    try:
        out = find_importers(db, "pkg/target.py")
        assert out.startswith("Showing 1 of 2 files\n")
        assert "pkg/a.py" in out
        assert "pkg/b.py" not in out
    finally:
        db.close()


def test_find_importers_accepts_absolute_path(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "target.py").write_text("def helper() -> int:\n    return 1\n", encoding="utf-8")
    (pkg / "importer.py").write_text("from pkg.target import helper\n", encoding="utf-8")
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    try:
        abs_target = str((tmp_path / "pkg" / "target.py").resolve())
        out = find_importers(db, abs_target)
        assert "pkg/importer.py" in out
        assert "Importers of" not in out
        assert "Showing" not in out
    finally:
        db.close()
