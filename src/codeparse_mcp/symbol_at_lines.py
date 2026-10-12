"""Resolve a file line range to the symbol that covers it."""

from src.codeparse_mcp.format_utils import bullet
from src.codeparse_mcp.paths import normalize_repo_file_path
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
    Return the qualified name of the symbol that covers the line range.

    ``line_end`` defaults to ``line_start``. A class and a method both cover a
    line inside the method; the method is returned because its span is smaller.
    A range that crosses two symbols, and sits inside neither, returns both.
    """
    if line_start < 1:
        return "line_start must be >= 1."
    end = line_start if line_end is None else line_end
    if end < line_start:
        return "line_end must be >= line_start."

    try:
        path = normalize_repo_file_path(file_path, db.root)
    except ValueError as exc:
        return str(exc)

    rows = list(db.connection.execute(_SYMBOL_AT_LINES_SQL, (path, end, line_start)))
    if not rows:
        span = str(line_start) if end == line_start else f"{line_start}-{end}"
        return f"No symbol in {path} covers line {span}."

    covering = [row for row in rows if row["line_start"] <= line_start and row["line_end"] >= end]
    if covering:
        tightest = min(row["line_end"] - row["line_start"] for row in covering)
        chosen = [row for row in covering if row["line_end"] - row["line_start"] == tightest]
    else:
        chosen = [row for row in rows if not any(_strictly_contains(other, row) for other in rows)]
    return "".join(f"{bullet(row['qualified_name'])}\n" for row in chosen)


def _strictly_contains(outer, inner) -> bool:
    if outer["qualified_name"] == inner["qualified_name"]:
        return False
    return outer["line_start"] <= inner["line_start"] and outer["line_end"] >= inner["line_end"]
