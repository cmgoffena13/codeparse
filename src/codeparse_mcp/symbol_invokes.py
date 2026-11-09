"""Outgoing call / access targets from a symbol."""

from collections import OrderedDict

from src.codeparse_mcp.format_utils import bullet, kind_count_suffix
from src.db import CodeDB

_MAX_ENTRIES = 50

_INVOKES_SQL = """
SELECT
    f.path AS target_path,
    sr.ref_kind,
    sr.source_line,
    sr.ref_symbol_qualified_name AS target_qualified_name
FROM symbol_references AS sr
INNER JOIN symbols AS src
    ON src.id = sr.source_symbol_id
INNER JOIN files AS f
    ON f.id = sr.ref_symbol_file_id
WHERE src.qualified_name = ?
  AND sr.ref_kind != 'type_annotation'
ORDER BY f.path, sr.source_line, sr.ref_symbol_qualified_name
"""


def _format_invoke_rows(rows: list) -> str:
    by_file: OrderedDict[str, OrderedDict[str, dict[str, int]]] = OrderedDict()
    for row in rows:
        path = row["target_path"]
        qn = row["target_qualified_name"]
        entries = by_file.setdefault(path, OrderedDict())
        kind_counts = entries.get(qn)
        if kind_counts is None:
            kind_counts = {}
            entries[qn] = kind_counts
        kind = row["ref_kind"]
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    lines_out: list[str] = []
    shown = 0
    truncated = False
    for path_index, (path, entries) in enumerate(by_file.items()):
        if truncated:
            break
        path_lines: list[str] = []
        for qn, kind_counts in entries.items():
            if shown >= _MAX_ENTRIES:
                truncated = True
                break
            path_lines.append(bullet(qn + kind_count_suffix(kind_counts)))
            shown += 1
        if path_lines:
            if path_index > 0 and lines_out:
                lines_out.append("")
            lines_out.append(path)
            lines_out.extend(path_lines)
    if truncated:
        lines_out.append(f"(truncated after {_MAX_ENTRIES} symbols)")
    return "\n".join(lines_out).strip() + "\n"


def get_symbol_invokes(
    db: CodeDB,
    qualified_name: str,
) -> str:
    """
    List symbols that ``qualified_name`` invokes, grouped by file then symbol.

    Each target shows ``(C)`` / ``(A)`` counts. At most ``_MAX_ENTRIES`` symbols
    are shown.
    """
    key = qualified_name.strip()
    result = "No symbol name given; pass a non-empty qualified_name."
    if key:
        rows = list(db.connection.execute(_INVOKES_SQL, (key,)))
        result = _format_invoke_rows(rows) if rows else "No invokes found."
    return result
