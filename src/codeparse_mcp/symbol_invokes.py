"""Outgoing call / access / type-annotation targets from a symbol."""

from collections import OrderedDict, defaultdict
from typing import Literal

from src.codeparse_mcp.format_utils import bullet
from src.db import CodeDB

_MAX_PER_KIND = 50

_REFERENCE_TYPES = {
    "call": "call",
    "access": "access",
    "type": "type_annotation",
}

_INVOKES_SQL = """
SELECT
    f.path AS target_path,
    sr.ref_kind,
    sr.ref_symbol_qualified_name AS target_qualified_name
FROM symbol_references AS sr
INNER JOIN symbols AS src
    ON src.id = sr.source_symbol_id
INNER JOIN files AS f
    ON f.id = sr.ref_symbol_file_id
WHERE src.qualified_name = ?
{kind_filter}
ORDER BY sr.ref_kind, f.path, sr.ref_symbol_qualified_name
"""

_REF_KIND_SECTIONS: tuple[tuple[str, str], ...] = (
    ("call", "## Calls"),
    ("access", "## Access"),
    ("type_annotation", "## Type Annotations"),
)


def _section_lines(heading: str, total: int, rows: list) -> list[str]:
    by_file: OrderedDict[str, list[str]] = OrderedDict()
    seen = set()
    count = {}
    for r in rows:
        count[r["target_qualified_name"]] = count.get(r["target_qualified_name"], 0) + 1
        if r["target_qualified_name"] in seen:
            continue
        seen.add(r["target_qualified_name"])
        by_file.setdefault(r["target_path"], []).append(r["target_qualified_name"])

    shown = len(rows)
    count_label = f"{shown} of {total}" if shown < total else str(total)
    lines_out = [
        "",
        f"{heading} ({count_label})",
        "",
    ]
    for path_index, (path, names) in enumerate(by_file.items()):
        if path_index > 0:
            lines_out.append("")
        lines_out.append(path)
        for qn in names:
            lines_out.append(bullet(qn + f" ({count[qn]})"))
    return lines_out


def get_symbol_invokes(
    db: CodeDB,
    qualified_name: str,
    *,
    reference_type: Literal["call", "access", "type"] | None = None,
) -> str:
    """
    List symbols that ``qualified_name`` invokes, grouped by ``ref_kind`` then file.

    At most ``_MAX_PER_KIND`` rows are shown per kind. Targets in test files are
    skipped unless ``include_tests`` is true.
    ``reference_type`` may be ``call``, ``access``, or ``type`` to keep one kind.
    """
    key = qualified_name.strip()
    if not key:
        return "No symbol name given; pass a non-empty qualified_name."

    params: list[str] = [key]
    kind_filter = ""
    if reference_type is not None:
        kind_filter = "    AND sr.ref_kind = ?"
        params.append(_REFERENCE_TYPES[reference_type])
    rows = list(
        db.connection.execute(
            _INVOKES_SQL.format(
                kind_filter=kind_filter,
            ),
            params,
        )
    )
    if not rows:
        return "No invokes found."

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
