"""Resolve a file line range to the symbol that covers it."""

from src.codeparse_mcp.format_utils import bullet, line_span
from src.codeparse_mcp.paths import normalize_repo_file_path
from src.codeparse_mcp.symbol import get_symbol
from src.db import CodeDB

_SYMBOL_AT_LINES_SQL = """
SELECT
    s.qualified_name,
    s.start_line,
    s.end_line,
    s.is_inherited
FROM symbols AS s
INNER JOIN files AS f
    ON f.id = s.file_id
WHERE f.path = ?
  AND s.start_line <= ?
  AND s.end_line >= ?
ORDER BY s.start_line, s.qualified_name
"""


def get_symbol_at_lines(
    db: CodeDB,
    file_path: str,
    start_line: int,
    end_line: int | None,
    *,
    include_tests: bool,
) -> str:
    """
    Return ``get_symbol`` output for the tightest symbol containing the range,
    with ``Symbol:`` in place of ``File:``.

    ``end_line`` defaults to ``start_line``. Test references are omitted unless
    ``include_tests`` is true. A class and a method both cover a
    line inside the method; the method is returned because its span is smaller.
    A range that crosses two symbols, and sits inside neither, lists each
    qualified name and its line span.
    """
    result = ""
    end = start_line if end_line is None else end_line
    path = ""
    if start_line < 1:
        result = "start_line must be >= 1."
    elif end < start_line:
        result = "end_line must be >= start_line."
    else:
        try:
            path = normalize_repo_file_path(file_path, db.root)
        except ValueError as exc:
            result = str(exc)
    if result == "" and path:
        rows = list(db.connection.execute(_SYMBOL_AT_LINES_SQL, (path, end, start_line)))
        if not rows:
            result = "No symbol found."
        else:
            result = _format_hits(
                db, _chosen_rows(rows, start_line, end), include_tests=include_tests
            )
    return result


def _chosen_rows(rows, start_line: int, end: int):
    covering = [row for row in rows if row["start_line"] <= start_line and row["end_line"] >= end]
    chosen = [row for row in rows if not any(_strictly_contains(other, row) for other in rows)]
    if covering:
        tightest = min(row["end_line"] - row["start_line"] for row in covering)
        chosen = [row for row in covering if row["end_line"] - row["start_line"] == tightest]
    return chosen


def _format_hits(db: CodeDB, chosen, *, include_tests: bool) -> str:
    text = ""
    if len(chosen) == 1:
        name = str(chosen[0]["qualified_name"])
        inherited = bool(chosen[0]["is_inherited"])
        body = get_symbol(db, name, include_tests=include_tests)
        rest = body.split("\n", 1)[1]
        text = rest if inherited else f"Symbol: {name}\n{rest}"
    else:
        lines = ["Multiple symbols found:"]
        for row in chosen:
            span = line_span(int(row["start_line"]), int(row["end_line"]))
            name = row["qualified_name"]
            suffix = " (inherits)" if row["is_inherited"] else ""
            lines.append(bullet(f"{name} — {span}{suffix}"))
        text = "\n".join(lines) + "\n"
    return text


def _strictly_contains(outer, inner) -> bool:
    same = outer["qualified_name"] == inner["qualified_name"]
    covers = outer["start_line"] <= inner["start_line"] and outer["end_line"] >= inner["end_line"]
    return (not same) and covers
