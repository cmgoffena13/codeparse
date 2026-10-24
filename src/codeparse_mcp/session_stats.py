import sqlite3
import threading
import time
from pathlib import Path

from fastmcp import Context
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from pydantic import BaseModel

from src.codeparse_mcp.paths import normalize_repo_file_path
from src.utils import db_path_for_index_root

_FILE_TOOLS = frozenset({"get_file_symbols", "get_file_imports"})
_TRACKED_TOOLS = frozenset({"get_symbol", "get_symbol_at_lines"}) | _FILE_TOOLS

_SYMBOL_FILE_SQL = """
SELECT f.path
FROM symbols AS s
INNER JOIN files AS f
    ON f.id = s.file_id
WHERE s.qualified_name = ?
"""

_FILE_ID_SQL = "SELECT id FROM files WHERE path = ?"

_INSERT_SESSION_SQL = """
INSERT INTO session_stats (session_id, session_start_time)
VALUES (?, ?)
ON CONFLICT(session_id) DO NOTHING
"""

_SESSION_ROW_SQL = "SELECT id FROM session_stats WHERE session_id = ?"

_UPSERT_FILE_SQL = """
INSERT INTO session_stats_files (
    session_id,
    file_id,
    current_file_tokens,
    tool_call_count,
    output_tokens,
    total_if_read_tokens
)
VALUES (?, ?, ?, 1, ?, ?)
ON CONFLICT(session_id, file_id) DO UPDATE SET
    current_file_tokens = excluded.current_file_tokens,
    tool_call_count = session_stats_files.tool_call_count + 1,
    output_tokens = session_stats_files.output_tokens + excluded.output_tokens,
    total_if_read_tokens = session_stats_files.total_if_read_tokens + excluded.total_if_read_tokens
RETURNING id
"""

_WEEK_SECONDS = 7 * 24 * 60 * 60

_OLD_SESSION_IDS_SQL = "SELECT id FROM session_stats WHERE session_start_time < ?"

_INSERT_OUTPUT_SQL = """
INSERT INTO session_stats_tool_outputs (
    session_file_id,
    tool,
    tool_symbol_qualified_name,
    output_tokens,
    file_tokens
)
VALUES (?, ?, ?, ?, ?)
"""

_LOAD_SQL = """
SELECT
    s.session_id,
    f.path,
    sf.current_file_tokens,
    sf.tool_call_count,
    sf.output_tokens,
    sf.total_if_read_tokens,
    o.tool,
    o.tool_symbol_qualified_name,
    o.output_tokens AS call_output_tokens,
    o.file_tokens AS call_file_tokens
FROM session_stats_files AS sf
INNER JOIN session_stats AS s
    ON s.id = sf.session_id
INNER JOIN files AS f
    ON f.id = sf.file_id
LEFT JOIN session_stats_tool_outputs AS o
    ON o.session_file_id = sf.id
ORDER BY sf.id, o.id
"""

_REPORT_SQL = """
SELECT
    s.session_id,
    s.session_start_time,
    f.path,
    sf.tool_call_count,
    sf.output_tokens,
    sf.total_if_read_tokens
FROM session_stats_files AS sf
INNER JOIN session_stats AS s
    ON s.id = sf.session_id
INNER JOIN files AS f
    ON f.id = sf.file_id
ORDER BY s.session_start_time DESC, s.session_id, f.path
"""


class ToolOutput(BaseModel):
    tool: str
    tool_symbol_qualified_name: str | None
    output_tokens: int
    file_tokens: int


class FileToolStats(BaseModel):
    session_id: str
    file_path: str
    current_file_tokens: int
    tool_call_count: int
    output_tokens: int
    total_if_read_tokens: int
    outputs: list[ToolOutput]


def _tokens(length: int) -> int:
    return length // 4


def load_session_files(root: Path) -> list[FileToolStats]:
    grouped: dict[tuple[str, str], FileToolStats] = {}
    connection = _connect(root)
    if connection is not None:
        try:
            rows = connection.execute(_LOAD_SQL).fetchall()
        finally:
            connection.close()
        for row in rows:
            key = (str(row["session_id"]), str(row["path"]))
            stats = grouped.get(key)
            if stats is None:
                stats = FileToolStats(
                    session_id=key[0],
                    file_path=key[1],
                    current_file_tokens=int(row["current_file_tokens"]),
                    tool_call_count=int(row["tool_call_count"]),
                    output_tokens=int(row["output_tokens"]),
                    total_if_read_tokens=int(row["total_if_read_tokens"]),
                    outputs=[],
                )
                grouped[key] = stats
            if row["tool"] is not None:
                stats.outputs.append(
                    ToolOutput(
                        tool=str(row["tool"]),
                        tool_symbol_qualified_name=row["tool_symbol_qualified_name"],
                        output_tokens=int(row["call_output_tokens"]),
                        file_tokens=int(row["call_file_tokens"]),
                    )
                )
    return list(grouped.values())


def format_session_stats_report(root: Path) -> str:
    lines: list[str] = []
    connection = _connect(root)
    rows: list[sqlite3.Row] = []
    if connection is not None:
        try:
            rows = list(connection.execute(_REPORT_SQL).fetchall())
        finally:
            connection.close()
    if not rows:
        lines.append("No session stats recorded.")
    header = "| file | tool_calls | if_read_file_tokens | tool_output_tokens | tokens_saved |"
    rule = "| --- | --- | --- | --- | --- |"
    current_session = ""
    session_files = 0
    session_calls = 0
    session_if_read = 0
    session_output = 0
    for row in rows:
        session_id = str(row["session_id"])
        calls = int(row["tool_call_count"])
        if_read = int(row["total_if_read_tokens"])
        output = int(row["output_tokens"])
        if session_id != current_session:
            if current_session:
                saved = session_if_read - session_output
                noun = "file" if session_files == 1 else "files"
                total = (
                    f"| {session_files} {noun} | {session_calls} | "
                    f"{session_if_read} | {session_output} | {saved} |"
                )
                lines.append(total)
                lines.append("")
            current_session = session_id
            session_files = 0
            session_calls = 0
            session_if_read = 0
            session_output = 0
            started = time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(int(row["session_start_time"])),
            )
            lines.append(f"{session_id} - {started}")
            lines.append(header)
            lines.append(rule)
        session_files += 1
        session_calls += calls
        session_if_read += if_read
        session_output += output
        lines.append(f"| {row['path']} | {calls} | {if_read} | {output} | {if_read - output} |")
    if current_session:
        saved = session_if_read - session_output
        noun = "file" if session_files == 1 else "files"
        total = (
            f"| {session_files} {noun} | {session_calls} | "
            f"{session_if_read} | {session_output} | {saved} |"
        )
        lines.append(total)
    return "\n".join(lines) + "\n"


def record_tool_call(
    root: Path,
    session_id: str,
    file_path: str,
    tool: str,
    qualified_name: str,
    output: str,
    file_chars: int,
) -> None:
    connection = _connect(root)
    if connection is not None:
        try:
            _write_tool_call(
                connection,
                session_id,
                file_path,
                tool,
                qualified_name,
                output,
                file_chars,
            )
        finally:
            connection.close()


def schedule_symbol_record(
    root: Path,
    session_id: str,
    qualified_name: str,
    output: str,
) -> None:
    _spawn(root, session_id, "get_symbol", qualified_name, "", output)


def schedule_file_record(
    root: Path,
    session_id: str,
    tool: str,
    file_path: str,
    output: str,
) -> None:
    _spawn(root, session_id, tool, "", file_path, output)


class SessionStatsMiddleware(Middleware):
    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: CallNext,
    ) -> ToolResult:
        result = await call_next(context)
        _schedule_from_call(context, result)
        return result


def _spawn(
    root: Path,
    session_id: str,
    tool: str,
    qualified_name: str,
    file_path: str,
    output: str,
) -> None:
    threading.Thread(
        target=_record,
        args=(root, session_id, tool, qualified_name, file_path, output),
        daemon=True,
    ).start()


def _schedule_from_call(context: MiddlewareContext, result: ToolResult) -> None:
    message = context.message
    tool = str(getattr(message, "name", "") or "")
    fastmcp_context = context.fastmcp_context
    if tool in _TRACKED_TOOLS and fastmcp_context is not None:
        processor = fastmcp_context.lifespan_context.get("processor")
        if processor is not None:
            arguments = getattr(message, "arguments", None)
            _spawn(
                processor.root,
                _connection_id(fastmcp_context),
                tool,
                _argument(arguments, "qualified_name"),
                _argument(arguments, "file_path"),
                _output_text(result),
            )


def _connection_id(fastmcp_context: Context) -> str:
    connection = ""
    try:
        connection = fastmcp_context.session_id
    except RuntimeError:
        connection = ""
    return connection


def _argument(arguments: object, key: str) -> str:
    value = ""
    if isinstance(arguments, dict):
        raw = arguments.get(key)
        if isinstance(raw, str):
            value = raw.strip()
    return value


def _output_text(result: ToolResult) -> str:
    parts: list[str] = []
    for block in result.content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _record(
    root: Path,
    session_id: str,
    tool: str,
    qualified_name: str,
    file_path: str,
    output: str,
) -> None:
    relative = _relative_path(root, tool, qualified_name, file_path)
    if relative:
        file_chars = _file_chars(root / relative)
        if file_chars is not None:
            record_tool_call(
                root,
                session_id,
                relative,
                tool,
                _symbol_name(tool, qualified_name, output),
                output,
                file_chars,
            )


def _symbol_name(tool: str, qualified_name: str, output: str) -> str:
    name = qualified_name
    if tool in _FILE_TOOLS:
        name = ""
    elif tool == "get_symbol_at_lines":
        first = output.split("\n", 1)[0]
        prefix = "Symbol: "
        name = first[len(prefix) :] if first.startswith(prefix) else ""
    return name


def _relative_path(root: Path, tool: str, qualified_name: str, file_path: str) -> str:
    relative = ""
    if tool == "get_symbol":
        relative = _symbol_path(root, qualified_name)
    else:
        try:
            relative = normalize_repo_file_path(file_path, root)
        except ValueError:
            relative = ""
    return relative


def _symbol_path(root: Path, qualified_name: str) -> str:
    relative = ""
    connection = _connect(root)
    if qualified_name and connection is not None:
        try:
            row = connection.execute(_SYMBOL_FILE_SQL, (qualified_name,)).fetchone()
        finally:
            connection.close()
        if row is not None and row[0]:
            relative = str(row[0])
    return relative


def _file_chars(path: Path) -> int | None:
    size: int | None = None
    try:
        size = len(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        size = None
    return size


def _delete_old_sessions(connection: sqlite3.Connection, cutoff: int) -> None:
    ids = [int(row["id"]) for row in connection.execute(_OLD_SESSION_IDS_SQL, (cutoff,)).fetchall()]
    if ids:
        placeholders = ", ".join("?" for _ in ids)
        parameters = tuple(ids)
        connection.execute(
            f"""
            DELETE FROM session_stats_tool_outputs
            WHERE session_file_id IN (
                SELECT id FROM session_stats_files WHERE session_id IN ({placeholders})
            )
            """,  # noqa: S608
            parameters,
        )
        connection.execute(
            f"DELETE FROM session_stats_files WHERE session_id IN ({placeholders})",  # noqa: S608
            parameters,
        )
        connection.execute(
            f"DELETE FROM session_stats WHERE id IN ({placeholders})",  # noqa: S608
            parameters,
        )


def _connect(root: Path) -> sqlite3.Connection | None:
    db_file = db_path_for_index_root(root)
    connection = None
    if db_file.exists():
        connection = sqlite3.connect(db_file)
        connection.row_factory = sqlite3.Row
    return connection


def _write_tool_call(
    connection: sqlite3.Connection,
    session_id: str,
    file_path: str,
    tool: str,
    qualified_name: str,
    output: str,
    file_chars: int,
) -> None:
    file_row = connection.execute(_FILE_ID_SQL, (file_path,)).fetchone()
    if file_row is not None:
        output_tokens = _tokens(len(output))
        file_tokens = _tokens(file_chars)
        connection.execute("BEGIN IMMEDIATE")
        _delete_old_sessions(connection, int(time.time()) - _WEEK_SECONDS)
        connection.execute(_INSERT_SESSION_SQL, (session_id, int(time.time())))
        session_row = connection.execute(_SESSION_ROW_SQL, (session_id,)).fetchone()
        file_stats = None
        if session_row is not None:
            file_stats = connection.execute(
                _UPSERT_FILE_SQL,
                (
                    int(session_row["id"]),
                    int(file_row["id"]),
                    file_tokens,
                    output_tokens,
                    file_tokens,
                ),
            ).fetchone()
        if file_stats is not None:
            connection.execute(
                _INSERT_OUTPUT_SQL,
                (int(file_stats["id"]), tool, qualified_name or None, output_tokens, file_tokens),
            )
            connection.commit()
