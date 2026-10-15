"""Resolve a file line range to the symbol that covers it."""

from src.codeparse_mcp.format_utils import bullet, line_span
from src.codeparse_mcp.paths import normalize_repo_file_path
from src.codeparse_mcp.symbol_context import get_symbol_context
from src.db import CodeDB

_SYMBOL_AT_LINES_SQL = """
SELECT
    s.qualified_name,
    s.line_start,
    s.line_end
FROM symbols AS s
INNER JOIN files AS f
    ON f.id = s.file_id
WHERE f.path = ?
  AND s.line_start <= ?
  AND s.line_end >= ?
ORDER BY s.line_start, s.qualified_name
"""


def get_symbol_at_lines(
    db: CodeDB,
    file_path: str,
    line_start: int,
    line_end: int | None = None,
) -> str:
    """
    Return ``get_symbol`` output for the tightest symbol containing the range,
    with ``Symbol:`` in place of ``File:``.

    ``line_end`` defaults to ``line_start``. A class and a method both cover a
    line inside the method; the method is returned because its span is smaller.
    A range that crosses two symbols, and sits inside neither, lists each
    qualified name and its line span.
    """
    result = ""
    end = line_start if line_end is None else line_end
    path = ""
    if line_start < 1:
        result = "line_start must be >= 1."
    elif end < line_start:
        result = "line_end must be >= line_start."
    else:
        try:
            path = normalize_repo_file_path(file_path, db.root)
        except ValueError as exc:
            result = str(exc)
    if result == "" and path:
        rows = list(db.connection.execute(_SYMBOL_AT_LINES_SQL, (path, end, line_start)))
        if not rows:
            result = "No symbol found."
        else:
            result = _format_hits(db, _chosen_rows(rows, line_start, end))
    return result


def _chosen_rows(rows, line_start: int, end: int):
    covering = [row for row in rows if row["line_start"] <= line_start and row["line_end"] >= end]
    chosen = [row for row in rows if not any(_strictly_contains(other, row) for other in rows)]
    if covering:
        tightest = min(row["line_end"] - row["line_start"] for row in covering)
        chosen = [row for row in covering if row["line_end"] - row["line_start"] == tightest]
    return chosen


def _format_hits(db: CodeDB, chosen) -> str:
    text = ""
    if len(chosen) == 1:
        name = str(chosen[0]["qualified_name"])
        body = get_symbol_context(db, name)
        rest = body.split("\n", 1)[1]
        text = f"Symbol: {name}\n{rest}"
    else:
        lines = ["Multiple symbols found:"]
        for row in chosen:
            span = line_span(int(row["line_start"]), int(row["line_end"]))
            name = row["qualified_name"]
            lines.append(bullet(f"{name} — {span}"))
        text = "\n".join(lines) + "\n"
    return text


def _strictly_contains(outer, inner) -> bool:
    same = outer["qualified_name"] == inner["qualified_name"]
    covers = outer["line_start"] <= inner["line_start"] and outer["line_end"] >= inner["line_end"]
    return (not same) and covers
