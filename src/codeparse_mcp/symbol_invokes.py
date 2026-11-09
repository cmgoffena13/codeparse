"""Outgoing call / access targets from a symbol."""

from collections import OrderedDict

from src.codeparse_mcp.format_utils import format_paged_file_entries
from src.db import CodeDB

_MAX_ENTRIES = 50

_INVOKES_SQL = """
SELECT
    f.path AS target_path,
    sr.ref_kind,
    sr.source_line,
    sr.ref_symbol_qualified_name AS target_qualified_name
FROM symbol_references AS sr
INNER JOIN files AS f
    ON f.id = sr.ref_symbol_file_id
WHERE sr.source_symbol_qualified_name = ?
  AND sr.ref_kind != 'type_annotation'
ORDER BY f.path, sr.source_line, sr.ref_symbol_qualified_name
"""


def _invoke_entries(rows: list) -> list[tuple[str, str, dict[str, int]]]:
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

    flat: list[tuple[str, str, dict[str, int]]] = []
    for path, entries in by_file.items():
        for qn, kind_counts in entries.items():
            flat.append((path, qn, kind_counts))
    return flat


def _format_invoke_rows(rows: list, *, page: int = 1) -> str:
    return format_paged_file_entries(
        _invoke_entries(rows),
        page=page,
        page_size=_MAX_ENTRIES,
        label="dependencies",
    )


def get_symbol_invokes(
    db: CodeDB,
    qualified_name: str,
    *,
    page: int = 1,
) -> str:
    """
    List symbols that ``qualified_name`` invokes, grouped by file then symbol.

    Each target shows ``(C)`` / ``(A)`` counts. ``page`` is 1-indexed over symbols.
    """
    key = qualified_name.strip()
    result = "No symbol name given; pass a non-empty qualified_name."
    if key:
        rows = list(db.connection.execute(_INVOKES_SQL, (key,)))
        result = _format_invoke_rows(rows, page=page) if rows else "No invokes found."
    return result
