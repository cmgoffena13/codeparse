"""Call / access sites for a symbol."""

from collections import OrderedDict

from src.codeparse_mcp.format_utils import bullet, kind_count_suffix
from src.db import CodeDB

_MAX_ENTRIES = 50

_REFERENCES_SQL = """
SELECT
    f.path AS source_path,
    sr.source_line,
    sr.ref_kind,
    src.qualified_name AS source_qualified_name
FROM symbol_references AS sr
INNER JOIN files AS f
    ON f.id = sr.source_file_id
LEFT JOIN symbols AS src
    ON src.id = sr.source_symbol_id
WHERE sr.ref_symbol_qualified_name = ?
  AND sr.ref_kind != 'type_annotation'
{test_filter}
ORDER BY f.path, sr.source_line
"""


def _format_reference_rows(rows: list) -> str:
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

    by_file: OrderedDict[str, list[tuple[str, str]]] = OrderedDict()
    for path, key_id in labels:
        by_file.setdefault(path, []).append((path, key_id))

    lines_out: list[str] = []
    shown = 0
    truncated = False
    for path_index, (path, keys) in enumerate(by_file.items()):
        if truncated:
            break
        path_lines: list[str] = []
        for key in keys:
            if shown >= _MAX_ENTRIES:
                truncated = True
                break
            path_lines.append(bullet(labels[key] + kind_count_suffix(counts[key])))
            shown += 1
        if path_lines:
            if path_index > 0 and lines_out:
                lines_out.append("")
            lines_out.append(path)
            lines_out.extend(path_lines)
    if truncated:
        lines_out.append(f"(truncated after {_MAX_ENTRIES} symbols)")
    return "\n".join(lines_out).strip() + "\n"


def get_symbol_references(
    db: CodeDB,
    qualified_name: str,
    *,
    include_tests: bool,
) -> str:
    """
    List reference sites for ``qualified_name``, grouped by file then symbol.

    Each site shows the enclosing symbol with ``(C)`` / ``(A)`` counts. A
    module-level site has none and shows its line number instead. At most
    ``_MAX_ENTRIES`` symbols are shown. Test files are skipped unless
    ``include_tests`` is true.
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
        result = _format_reference_rows(rows) if rows else "No references found."
    return result
