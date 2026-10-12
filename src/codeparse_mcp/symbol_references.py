"""Call / access / type-annotation sites for a symbol."""

from collections import OrderedDict, defaultdict

from src.codeparse_mcp.format_utils import bullet
from src.db import CodeDB

_MAX_PER_KIND = 50

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
{test_filter}
ORDER BY sr.ref_kind, f.path, sr.source_line
"""

_REF_KIND_SECTIONS: tuple[tuple[str, str], ...] = (
    ("call", "## Calls"),
    ("access", "## Access"),
    ("type_annotation", "## Type Annotations"),
)


def _section_lines(heading: str, total: int, rows: list) -> list[str]:
    by_file: OrderedDict[str, list[tuple[int, str | None]]] = OrderedDict()
    for r in rows:
        by_file.setdefault(r["source_path"], []).append(
            (int(r["source_line"]), r["source_qualified_name"])
        )

    shown = len(rows)
    count_label = f"{shown} of {total}" if shown < total else str(total)
    lines_out = [
        "",
        f"{heading} ({count_label})",
        "",
    ]
    for path_index, (path, sites) in enumerate(by_file.items()):
        if path_index > 0:
            lines_out.append("")
        lines_out.append(path)
        for line_n, qn in sites:
            if qn:
                lines_out.append(bullet(f"L{line_n}  {qn}"))
            else:
                lines_out.append(bullet(f"L{line_n}"))
    return lines_out


def get_symbol_references(db: CodeDB, qualified_name: str, *, include_tests: bool = False) -> str:
    """
    List reference sites for ``qualified_name``, grouped by ``ref_kind`` then file.

    Each site shows the enclosing symbol stored on the reference. A module-level
    site has none. At most ``_MAX_PER_KIND`` rows are shown per kind. Test files
    are skipped unless ``include_tests`` is true.
    """
    key = qualified_name.strip()
    if not key:
        return "No symbol name given; pass a non-empty qualified_name."

    rows = list(
        db.connection.execute(
            _REFERENCES_SQL.format(test_filter="" if include_tests else "    AND f.is_test = 0"),
            (key,),
        )
    )
    if not rows:
        return f"No references to {key} were found."

    by_kind: defaultdict[str, list] = defaultdict(list)
    for row in rows:
        by_kind[row["ref_kind"]].append(row)

    lines: list[str] = []

    covered = {k for k, _ in _REF_KIND_SECTIONS}
    for kind, heading in _REF_KIND_SECTIONS:
        items = by_kind.get(kind, [])
        if not items:
            continue
        lines.extend(_section_lines(heading, len(items), items[:_MAX_PER_KIND]))

    for kind in sorted(k for k in by_kind if k not in covered):
        items = by_kind[kind]
        title = kind.replace("_", " ").title()
        lines.extend(_section_lines(f"## {title}", len(items), items[:_MAX_PER_KIND]))

    return "\n".join(lines).strip() + "\n"
