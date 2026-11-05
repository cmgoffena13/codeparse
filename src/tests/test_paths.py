"""Tests for repo-relative POSIX path normalization."""

from pathlib import Path

import pytest

from src.codeparse_mcp.list_importers import list_importers
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


def test_list_importers_notes_truncation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".gitignore").write_text("# test\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "target.py").write_text("def helper() -> int:\n    return 1\n", encoding="utf-8")
    (pkg / "a.py").write_text("from pkg.target import helper\n", encoding="utf-8")
    (pkg / "b.py").write_text("from pkg.target import helper\n", encoding="utf-8")
    monkeypatch.setattr("src.codeparse_mcp.list_importers._MAX_IMPORTER_FILES", 1)
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    try:
        out = list_importers(db, "pkg.target", include_tests=False)
        assert out.startswith("Showing 1 of 2 files\n")
        assert "└── pkg/\n    └── a.py\n" in out
        assert "b.py" not in out
    finally:
        db.close()


def test_list_importers_includes_relative_import(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sib.py").write_text("class Foo:\n    pass\n", encoding="utf-8")
    (pkg / "caller.py").write_text("from .sib import Foo\n", encoding="utf-8")
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    try:
        out = list_importers(db, "pkg.sib", include_tests=False)
        assert "└── pkg/\n    └── caller.py\n" in out
    finally:
        db.close()


def test_list_importers_finds_external_and_in_repo(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "target.py").write_text("def helper() -> int:\n    return 1\n", encoding="utf-8")
    (pkg / "importer.py").write_text(
        "from pkg.target import helper\nfrom pydantic import BaseModel\nimport sqlglot\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    try:
        out = list_importers(db, "pkg.target", include_tests=False)
        assert out.startswith("Total Files: 1\n")
        assert "└── pkg/\n    └── importer.py\n" in out
        assert "└── pkg/\n    └── importer.py\n" in list_importers(
            db, "pydantic", include_tests=False
        )
        assert "└── pkg/\n    └── importer.py\n" in list_importers(
            db, "sqlglot", include_tests=False
        )
        assert list_importers(db, "pydantic.BaseModel", include_tests=False) == (
            "No importers found."
        )
        assert list_importers(db, "missingpkg", include_tests=False) == "No importers found."
    finally:
        db.close()


def test_list_importers_rejects_blank_module_name(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test\n", encoding="utf-8")
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    try:
        assert list_importers(db, "  ", include_tests=False) == (
            "No module name given; pass a non-empty module_name."
        )
    finally:
        db.close()
