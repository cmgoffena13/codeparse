"""Tests for file-level is_test helpers."""

from pathlib import Path

from src.db import CodeDB
from src.processor import CodeProcessor, file_path_is_test


def test_file_path_is_test_rules() -> None:
    assert file_path_is_test("tests/core/test_foo.py")
    assert file_path_is_test("test_foo.py")
    assert file_path_is_test("pkg/foo_test.py")
    assert file_path_is_test("tests/conftest.py")
    assert file_path_is_test("tests/helpers.py")
    # Package named test (not tests/) is not a suite root.
    assert not file_path_is_test("sqlmesh/core/test/definition.py")
    assert not file_path_is_test("sqlmesh/dbt/test.py")
    assert not file_path_is_test("sqlmesh/core/dialect.py")


def test_file_is_test_not_promoted_from_test_symbols(tmp_path: Path) -> None:
    """Framework modules with Test* / test_* symbols stay non-test files."""
    (tmp_path / ".gitignore").write_text("# fixture\n", encoding="utf-8")
    pkg = tmp_path / "core" / "test"
    pkg.mkdir(parents=True)
    (pkg / "definition.py").write_text(
        "class TestCase:\n"
        "    def test_run(self) -> None:\n"
        "        pass\n"
        "\n"
        "def test_helper() -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "dbt").mkdir()
    (tmp_path / "dbt" / "test.py").write_text(
        "class TestMacro:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_real.py").write_text(
        "def test_ok() -> None:\n    pass\n",
        encoding="utf-8",
    )

    db = CodeDB(tmp_path)
    try:
        CodeProcessor(db, tmp_path).process()
        rows = {
            row["path"]: bool(row["is_test"])
            for row in db.connection.execute("SELECT path, is_test FROM files")
        }
        assert rows["core/test/definition.py"] is False
        assert rows["dbt/test.py"] is False
        assert rows["tests/test_real.py"] is True
    finally:
        db.close()
