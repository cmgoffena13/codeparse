from pathlib import Path

import pytest

from src.db import CodeDB


def test_delete_ids_rejects_unknown_table(tmp_path: Path) -> None:
    db = CodeDB(tmp_path)
    with pytest.raises(ValueError, match="unsupported table"):
        db.delete_ids("nope", [1])
    db.close()


def test_delete_ids_noop_on_empty(tmp_path: Path) -> None:
    db = CodeDB(tmp_path)
    db.delete_ids("files", [])
    db.close()


def test_close_is_idempotent(tmp_path: Path) -> None:
    db = CodeDB(tmp_path)
    db.close()
    db.close()


def test_recreate_schema_drops_session_stats_before_their_parents(tmp_path: Path) -> None:
    db = CodeDB(tmp_path)
    db.recreate_schema()
    names = {
        row[0]
        for row in db.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {
        "session_stats",
        "session_stats_files",
        "session_stats_tool_outputs",
    } <= names
    db.close()


def test_index_root_links_the_database_back_to_the_workspace(tmp_path: Path) -> None:
    from src.db import index_workspace_paths

    workspace = tmp_path / "proj"
    workspace.mkdir()
    db = CodeDB(workspace)
    db_file = db.db_file
    db.recreate_schema()
    db.close()

    assert index_workspace_paths() == [(db_file, workspace.resolve())]


def test_delete_files_leaves_session_stats_for_that_file(tmp_path: Path) -> None:
    db = CodeDB(tmp_path)
    db.connection.execute(
        """
        INSERT INTO files (id, name, path, normalized_path, content_hash)
        VALUES (10, 'drop.py', 'pkg/drop.py', 'pkg.drop', 'abc'),
               (11, 'keep.py', 'pkg/keep.py', 'pkg.keep', 'def')
        """
    )
    db.connection.execute(
        "INSERT INTO session_stats (id, session_id, session_start_time) VALUES (1, 'window-a', 1)"
    )
    db.connection.execute(
        """
        INSERT INTO session_stats_files (
            id, session_id, file_id, current_file_tokens, tool_call_count, output_tokens
        )
        VALUES (100, 1, 10, 4, 1, 2),
               (101, 1, 11, 8, 1, 3)
        """
    )
    db.connection.execute(
        """
        INSERT INTO session_stats_tool_outputs (
            session_file_id, tool, tool_symbol_qualified_name, output_tokens, file_tokens
        )
        VALUES (100, 'get_symbol', 'pkg.drop.drop', 2, 4),
               (101, 'get_symbol', 'pkg.keep.keep', 3, 8)
        """
    )
    db.connection.commit()
    snapshot = db.get_files_snapshot()
    for path, meta in snapshot.items():
        meta["seen"] = path != Path("pkg/drop.py")

    db.delete_files(snapshot)

    assert {row["path"] for row in db.connection.execute("SELECT path FROM files")} == {
        "pkg/keep.py"
    }
    assert [
        row["file_id"] for row in db.connection.execute("SELECT file_id FROM session_stats_files")
    ] == [10, 11]
    assert [
        row["tool_symbol_qualified_name"]
        for row in db.connection.execute(
            "SELECT tool_symbol_qualified_name FROM session_stats_tool_outputs"
        )
    ] == ["pkg.drop.drop", "pkg.keep.keep"]
    assert [
        row["session_id"] for row in db.connection.execute("SELECT session_id FROM session_stats")
    ] == ["window-a"]
    db.close()


def test_exec_tran_rolls_back_on_error(tmp_path: Path) -> None:
    db = CodeDB(tmp_path)
    with pytest.raises(Exception):  # noqa: B017, PT011
        db.exec_tran("NOT VALID SQL", ())
    db.close()
