"""Call / access sites for a symbol."""

from collections import OrderedDict

from src.codeparse_mcp.format_utils import format_paged_file_entries
from src.db import CodeDB

_MAX_ENTRIES = 50

_REFERENCES_SQL = """
SELECT
    f.path AS source_path,
    sr.source_line,
    sr.ref_kind,
    sr.source_symbol_qualified_name AS source_qualified_name
FROM symbol_references AS sr
INNER JOIN files AS f
    ON f.id = sr.source_file_id
WHERE sr.ref_symbol_qualified_name = ?
  AND sr.ref_kind != 'type_annotation'
{test_filter}
ORDER BY f.path, sr.source_line
"""


def _reference_entries(rows: list) -> list[tuple[str, str, dict[str, int]]]:
    labels: OrderedDict[tuple[str, str], str] = OrderedDict()
    counts: dict[tuple[str, str], dict[str, int]] = {}
    for row in rows:
        path = row["source_path"]
        qn = row["source_qualified_name"]
        key = (path, qn if qn else f"L{int(row['source_line'])}")
        if key not in labels:
            labels[key] = qn if qn else f"L{int(row['source_line'])}  (no symbol)"
            counts[key] = {}
        kind = row["ref_kind"]
        counts[key][kind] = counts[key].get(kind, 0) + 1

    entries: list[tuple[str, str, dict[str, int]]] = []
    for path, key_id in labels:
        entries.append((path, labels[(path, key_id)], counts[(path, key_id)]))
    return entries


def _format_reference_rows(rows: list, *, page: int = 1) -> str:
    return format_paged_file_entries(
        _reference_entries(rows),
        page=page,
        page_size=_MAX_ENTRIES,
        label="dependents",
    )


def get_symbol_references(
    db: CodeDB,
    qualified_name: str,
    *,
    include_tests: bool,
    page: int = 1,
) -> str:
    """
    List reference sites for ``qualified_name``, grouped by file then symbol.

    Each site shows the enclosing symbol with ``(C)`` / ``(A)`` counts. A
    module-level site has none and shows its line number instead. ``page`` is
    1-indexed over symbols. Test files are skipped unless ``include_tests`` is
    true.
    """
    key = qualified_name.strip()
    result = "No symbol name given; pass a non-empty qualified_name."
    if key:
        rows = list(
            db.connection.execute(
                _REFERENCES_SQL.format(
                    test_filter="" if include_tests else "    AND f.is_test = 0",
                ),
                (key,),
            )
        )
        result = _format_reference_rows(rows, page=page) if rows else "No references found."
    return result
