"""Tests for `.gitignore`-driven indexing rules (`git_utils` + `CodeProcessor`)."""

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from pathspec import PathSpec

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.db import CodeDB
from src.git_utils import path_spec_for_indexing, relative_path_is_ignored
from src.processor import CodeProcessor


def test_relative_path_rejects_absolute() -> None:
    spec = PathSpec.from_lines("gitignore", [])
    with pytest.raises(ValueError, match="relative path must not be absolute"):
        relative_path_is_ignored(Path("/abs/foo.py"), False, spec)


def test_always_ignore_path_segment() -> None:
    spec = PathSpec.from_lines("gitignore", [])
    assert relative_path_is_ignored(Path(".git/HEAD"), False, spec)
    assert relative_path_is_ignored(Path("src/.git"), True, spec)


def test_glob_and_negation_from_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*.log\n!important.log\n", encoding="utf-8")
    spec = path_spec_for_indexing(tmp_path)
    assert relative_path_is_ignored(Path("noise.log"), False, spec)
    assert not relative_path_is_ignored(Path("important.log"), False, spec)


def test_root_anchored_pattern(tmp_path: Path) -> None:
    # Use `out` not `dist` — `dist` is in INDEX_ALWAYS_IGNORE_NAMES and would match any segment.
    (tmp_path / ".gitignore").write_text("/out\n", encoding="utf-8")
    spec = path_spec_for_indexing(tmp_path)
    assert relative_path_is_ignored(Path("out"), True, spec)
    assert not relative_path_is_ignored(Path("nested/out"), True, spec)


def test_directory_only_trailing_slash(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("out/\n", encoding="utf-8")
    spec = path_spec_for_indexing(tmp_path)
    assert relative_path_is_ignored(Path("out"), True, spec)
    assert not relative_path_is_ignored(Path("out"), False, spec)


def test_path_spec_for_indexing_outside_git_repo_raises(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)
    with pytest.raises(FileNotFoundError, match="are you in a git repository"):
        path_spec_for_indexing(tmp_path)


def test_path_spec_for_indexing_without_gitignore(tmp_path: Path) -> None:
    spec = path_spec_for_indexing(tmp_path)
    assert not relative_path_is_ignored(Path("keep.py"), False, spec)


def test_processor_prunes_ignored_dirs_and_files(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n",
        encoding="utf-8",
    )
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "keep.py").write_text("x = 1\n", encoding="utf-8")
    cache = pkg / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"")
    (pkg / "skip.pyc").write_bytes(b"")

    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)

    conn = sqlite3.connect(str(db.db_file))
    try:
        paths = [r[0] for r in conn.execute("SELECT path FROM files").fetchall()]
    finally:
        conn.close()

    assert any("keep.py" in p for p in paths)
    assert not any("__pycache__" in p for p in paths)
    assert not any(p.endswith("skip.pyc") for p in paths)


@pytest.mark.skipif(not shutil.which("git"), reason="git not on PATH")
def test_git_check_ignore_parity_glob(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    (tmp_path / "a.tmp").write_text("", encoding="utf-8")
    (tmp_path / "keep.py").write_text("", encoding="utf-8")
    init = subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if init.returncode != 0:
        pytest.skip(f"git init failed: {init.stderr or init.stdout}")
    r_ignored = subprocess.run(
        ["git", "check-ignore", "-q", "a.tmp"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    r_ok = subprocess.run(
        ["git", "check-ignore", "-q", "keep.py"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert r_ignored.returncode == 0
    assert r_ok.returncode != 0

    spec = path_spec_for_indexing(tmp_path)
    assert relative_path_is_ignored(Path("a.tmp"), False, spec)
    assert not relative_path_is_ignored(Path("keep.py"), False, spec)
