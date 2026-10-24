import asyncio
import time
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult

from src.codeparse_mcp.session_stats import (
    FileToolStats,
    format_session_stats_report,
    load_session_files,
    record_tool_call,
)
from src.db import CodeDB
from src.processor import CodeProcessor

_PROJECT = Path(__file__).resolve().parent / "test_project"


def _text(result: CallToolResult) -> str:
    assert result.is_error is False
    assert isinstance(result.data, str)
    return result.data


def _index_target(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "target.py").write_text("def helper() -> int:\n    return 1\n", encoding="utf-8")
    (pkg / "other.py").write_text("def other() -> int:\n    return 2\n", encoding="utf-8")
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process()
    db.close()


def _record(
    root: Path,
    session_id: str,
    file_path: str,
    tool: str,
    qualified_name: str,
    output: str,
    file_chars: int,
) -> None:
    record_tool_call(root, session_id, file_path, tool, qualified_name, output, file_chars)


def _wait_path(root: Path, file_path: str, calls: int) -> list[FileToolStats]:
    found: list[FileToolStats] = []
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        found = [item for item in load_session_files(root) if item.file_path == file_path]
        if sum(item.tool_call_count for item in found) >= calls:
            break
        time.sleep(0.01)
    return found


def _wait_file(root: Path, file_path: str, calls: int) -> FileToolStats | None:
    found: FileToolStats | None = None
    matches = _wait_path(root, file_path, calls)
    if matches and matches[0].tool_call_count >= calls:
        found = matches[0]
    return found


def test_record_groups_calls_by_file(tmp_path: Path) -> None:
    _index_target(tmp_path)

    _record(tmp_path, "window-a", "pkg/target.py", "get_file_symbols", "", "overview", 40)
    _record(
        tmp_path,
        "window-a",
        "pkg/target.py",
        "get_symbol",
        "pkg.target.helper",
        "symbol-body",
        40,
    )
    _record(
        tmp_path,
        "window-a",
        "pkg/other.py",
        "get_symbol_at_lines",
        "pkg.other.other",
        "other",
        8,
    )

    files = {item.file_path: item for item in load_session_files(tmp_path)}
    target = files["pkg/target.py"]
    assert target.session_id == "window-a"
    assert target.current_file_tokens == 10
    assert target.tool_call_count == 2
    assert target.output_tokens == len("overview") // 4 + len("symbol-body") // 4
    assert [
        (item.tool, item.tool_symbol_qualified_name, item.output_tokens, item.file_tokens)
        for item in target.outputs
    ] == [
        ("get_file_symbols", None, len("overview") // 4, 10),
        ("get_symbol", "pkg.target.helper", len("symbol-body") // 4, 10),
    ]
    assert files["pkg/other.py"].tool_call_count == 1
    assert files["pkg/other.py"].output_tokens == len("other") // 4


def test_format_session_stats_report_bullets_files(tmp_path: Path) -> None:
    _index_target(tmp_path)
    start_a = int(time.time()) - 120
    start_b = int(time.time()) - 60
    db = CodeDB(tmp_path)
    db.connection.execute(
        "INSERT INTO session_stats (session_id, session_start_time) VALUES (?, ?), (?, ?)",
        ("window-b", start_b, "window-a", start_a),
    )
    db.connection.commit()
    db.close()
    _record(
        tmp_path,
        "window-a",
        "pkg/target.py",
        "get_file_symbols",
        "",
        "overview",
        40,
    )
    _record(
        tmp_path,
        "window-a",
        "pkg/target.py",
        "get_symbol",
        "pkg.target.helper",
        "symbol-body",
        80,
    )
    _record(
        tmp_path,
        "window-a",
        "pkg/other.py",
        "get_symbol",
        "pkg.other.other",
        "xyzw",
        8,
    )
    _record(
        tmp_path,
        "window-b",
        "pkg/other.py",
        "get_symbol",
        "pkg.other.other",
        "other",
        8,
    )

    report = format_session_stats_report(tmp_path)
    started_a = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_a))
    started_b = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_b))
    header = "| file | tool_calls | latest_file_tokens | tool_output_tokens | tokens_saved |"
    rule = "| --- | --- | --- | --- | --- |"
    assert (
        f"window-a - {started_a}\n"
        f"{header}\n"
        f"{rule}\n"
        "| pkg/other.py | 1 | 2 | 1 | 1 |\n"
        "| pkg/target.py | 2 | 20 | 4 | 16 |\n"
        "| 2 files | 3 | 22 | 5 | 17 |\n"
    ) in report
    assert (
        f"window-b - {started_b}\n"
        f"{header}\n"
        f"{rule}\n"
        "| pkg/other.py | 1 | 2 | 1 | 1 |\n"
        "| 1 file | 1 | 2 | 1 | 1 |\n"
    ) in report
    assert report.index("window-b") < report.index("window-a")


def test_format_session_stats_report_empty(tmp_path: Path) -> None:
    _index_target(tmp_path)
    assert format_session_stats_report(tmp_path) == "No session stats recorded.\n"


def test_record_keeps_each_call_file_size(tmp_path: Path) -> None:
    _index_target(tmp_path)

    _record(tmp_path, "window-a", "pkg/target.py", "get_symbol", "pkg.target.helper", "first", 10)
    _record(tmp_path, "window-a", "pkg/target.py", "get_symbol", "pkg.target.helper", "second", 25)

    target = load_session_files(tmp_path)[0]
    assert target.current_file_tokens == 25 // 4
    assert [item.file_tokens for item in target.outputs] == [10 // 4, 25 // 4]
    assert target.output_tokens == len("first") // 4 + len("second") // 4


def test_record_separates_connections_in_one_workspace(tmp_path: Path) -> None:
    _index_target(tmp_path)

    _record(tmp_path, "window-a", "pkg/target.py", "get_symbol", "pkg.target.helper", "a", 40)
    _record(tmp_path, "window-b", "pkg/target.py", "get_symbol", "pkg.target.helper", "b", 80)

    rows = {
        (item.session_id, item.file_path, item.current_file_tokens)
        for item in load_session_files(tmp_path)
    }
    assert rows == {
        ("window-a", "pkg/target.py", 10),
        ("window-b", "pkg/target.py", 20),
    }


def test_record_deletes_sessions_older_than_a_week(tmp_path: Path) -> None:
    _index_target(tmp_path)
    started = int(time.time())
    week = 7 * 24 * 60 * 60
    db = CodeDB(tmp_path)
    file_row = db.connection.execute(
        "SELECT id FROM files WHERE path = ?",
        ("pkg/target.py",),
    ).fetchone()
    file_id = int(file_row[0])
    for session_id, start in (("old", started - week - 1), ("recent", started - week + 60)):
        db.connection.execute(
            "INSERT INTO session_stats (session_id, session_start_time) VALUES (?, ?)",
            (session_id, start),
        )
        session_row_id = int(
            db.connection.execute(
                "SELECT id FROM session_stats WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
        )
        cursor = db.connection.execute(
            """
            INSERT INTO session_stats_files (
                session_id, file_id, current_file_tokens, tool_call_count, output_tokens
            )
            VALUES (?, ?, 4, 1, 2)
            """,
            (session_row_id, file_id),
        )
        session_file_id = cursor.lastrowid
        assert session_file_id is not None
        db.connection.execute(
            """
            INSERT INTO session_stats_tool_outputs (
                session_file_id, tool, tool_symbol_qualified_name, output_tokens, file_tokens
            )
            VALUES (?, 'get_symbol', 'pkg.target.helper', 2, 4)
            """,
            (session_file_id,),
        )
    db.connection.commit()
    db.close()

    _record(tmp_path, "fresh", "pkg/target.py", "get_symbol", "pkg.target.helper", "now", 40)

    assert {item.session_id for item in load_session_files(tmp_path)} == {"recent", "fresh"}


def test_record_stays_in_the_workspace_database(tmp_path: Path) -> None:
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    _index_target(one)
    _index_target(two)

    _record(one, "window-a", "pkg/target.py", "get_symbol", "pkg.target.helper", "a", 40)

    assert [item.session_id for item in load_session_files(one)] == ["window-a"]
    assert load_session_files(two) == []


def test_schedule_records_after_the_caller_continues(tmp_path: Path) -> None:
    from src.codeparse_mcp.session_stats import schedule_file_record, schedule_symbol_record

    _index_target(tmp_path)
    source = (tmp_path / "pkg" / "target.py").read_text(encoding="utf-8")

    schedule_symbol_record(tmp_path, "window-a", "pkg.target.helper", "symbol")
    schedule_file_record(tmp_path, "window-a", "get_file_symbols", "pkg/target.py", "overview")

    recorded = _wait_file(tmp_path, "pkg/target.py", 2)
    assert recorded is not None
    assert recorded.session_id == "window-a"
    assert recorded.current_file_tokens == len(source) // 4
    assert recorded.output_tokens == len("symbol") // 4 + len("overview") // 4
    assert {item.tool for item in recorded.outputs} == {"get_symbol", "get_file_symbols"}
    assert {item.tool_symbol_qualified_name for item in recorded.outputs} == {
        None,
        "pkg.target.helper",
    }


def test_schedule_skips_a_missing_symbol(tmp_path: Path) -> None:
    from src.codeparse_mcp.session_stats import schedule_symbol_record

    _index_target(tmp_path)

    schedule_symbol_record(tmp_path, "window-a", "pkg.target.missing", "missing")
    time.sleep(0.05)

    assert load_session_files(tmp_path) == []


def test_client_writes_tool_sizes_to_the_workspace_database(
    mcp_client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE", str(_PROJECT))
    child = (_PROJECT / "pkg" / "child.py").read_text(encoding="utf-8")

    async def run() -> None:
        async with mcp_client:
            overview = _text(
                await mcp_client.call_tool("get_file_symbols", {"file_path": "pkg/child.py"})
            )
            symbol = _text(
                await mcp_client.call_tool("get_symbol", {"qualified_name": "pkg.child.Child"})
            )
            at_lines = _text(
                await mcp_client.call_tool(
                    "get_symbol_at_lines",
                    {"file_path": "pkg/child.py", "line_start": 4},
                )
            )
            await mcp_client.call_tool("search_symbols", {"query": "Child", "limit": 5})
            recorded = _wait_path(_PROJECT, "pkg/child.py", 3)

        assert sum(item.tool_call_count for item in recorded) == 3
        assert all(item.session_id for item in recorded)
        assert {item.current_file_tokens for item in recorded} == {len(child) // 4}
        outputs = [call for item in recorded for call in item.outputs]
        assert sum(call.output_tokens for call in outputs) == (
            len(overview) // 4 + len(symbol) // 4 + len(at_lines) // 4
        )
        assert {(call.tool, call.tool_symbol_qualified_name) for call in outputs} == {
            ("get_file_symbols", None),
            ("get_symbol", "pkg.child.Child"),
            ("get_symbol_at_lines", "pkg.child.Child"),
        }

    asyncio.run(run())
