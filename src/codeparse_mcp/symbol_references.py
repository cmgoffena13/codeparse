"""Call / access / type-annotation sites for a symbol."""

from collections import OrderedDict, defaultdict

from src.codeparse_mcp.format_utils import bullet
from src.db import CodeDB

_MAX_PER_KIND = 50

_REFERENCES_SQL = """
SELECT
    f.path AS source_path,
    sr.source_file_id,
    sr.source_line,
    sr.ref_kind
FROM symbol_references AS sr
INNER JOIN files AS f
    ON f.id = sr.source_file_id
WHERE sr.ref_symbol_qualified_name = ?
{test_filter}
ORDER BY sr.ref_kind, f.path, sr.source_line
"""

_SYMBOLS_IN_FILE_SQL = """
SELECT qualified_name, line_start, line_end
FROM symbols
WHERE file_id = ?
"""

_REF_KIND_SECTIONS: tuple[tuple[str, str], ...] = (
    ("call", "## Calls"),
    ("access", "## Access"),
    ("type_annotation", "## Type Annotations"),
)


def _enclosing_qn(spans: list[tuple[str, int, int]], source_line: int) -> str | None:
    """Tightest symbol whose span covers ``source_line``, if any."""
    best: tuple[str, int, int] | None = None
    for qn, start, end in spans:
        if start <= source_line <= end:
            span = end - start
            if best is None or span < best[1] or (span == best[1] and start < best[2]):
                best = (qn, span, start)
    return best[0] if best else None


def _load_file_spans(db: CodeDB, file_ids: set[int]) -> dict[int, list[tuple[str, int, int]]]:
    by_file: dict[int, list[tuple[str, int, int]]] = {}
    for file_id in file_ids:
        by_file[file_id] = [
            (row["qualified_name"], int(row["line_start"]), int(row["line_end"]))
            for row in db.connection.execute(_SYMBOLS_IN_FILE_SQL, (file_id,))
        ]
    return by_file


def _section_lines(
    heading: str,
    total: int,
    rows: list,
    spans_by_file: dict[int, list[tuple[str, int, int]]],
) -> list[str]:
    by_file: OrderedDict[str, list[tuple[int, int]]] = OrderedDict()
    for r in rows:
        path = r["source_path"]
        by_file.setdefault(path, []).append((int(r["source_file_id"]), int(r["source_line"])))

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
        for file_id, line_n in sites:
            qn = _enclosing_qn(spans_by_file.get(file_id, []), line_n)
            if qn:
                lines_out.append(bullet(f"L{line_n}  {qn}"))
            else:
                lines_out.append(bullet(f"L{line_n}"))
    return lines_out


def get_symbol_references(db: CodeDB, qualified_name: str, *, include_tests: bool = False) -> str:
    """
    List reference sites for ``qualified_name``, grouped by ``ref_kind`` then file.

    Each site shows the tightest enclosing symbol (by line span) when one exists.
    At most ``_MAX_PER_KIND`` rows are shown per kind. Test files are skipped
    unless ``include_tests`` is true.
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

    spans_by_file = _load_file_spans(db, {int(r["source_file_id"]) for r in rows})

    by_kind: defaultdict[str, list] = defaultdict(list)
    for row in rows:
        by_kind[row["ref_kind"]].append(row)

    lines: list[str] = [
        "Legend: L = Line\n",
        f"References of {key} — {len(rows)} total",
    ]

    covered = {k for k, _ in _REF_KIND_SECTIONS}
    for kind, heading in _REF_KIND_SECTIONS:
        items = by_kind.get(kind, [])
        if not items:
            continue
        lines.extend(_section_lines(heading, len(items), items[:_MAX_PER_KIND], spans_by_file))

    for kind in sorted(k for k in by_kind if k not in covered):
        items = by_kind[kind]
        if not items:
            continue
        title = kind.replace("_", " ").title()
        lines.extend(
            _section_lines(f"## {title}", len(items), items[:_MAX_PER_KIND], spans_by_file)
        )

    return "\n".join(lines).rstrip() + "\n"
