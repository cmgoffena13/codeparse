from src.db import CodeDB

_SYMBOL_ROW_SQL = """
SELECT
    s.line_start,
    s.line_end,
    f.path AS file_path
FROM symbols AS s
INNER JOIN files AS f
    ON f.id = s.file_id
WHERE s.qualified_name = ?
"""

_REF_KIND_COUNTS_SQL = """
SELECT ref_kind, COUNT(*) AS n
FROM symbol_references
WHERE ref_symbol_qualified_name = ?
GROUP BY ref_kind
"""

_REF_KIND_LABELS: tuple[tuple[str, str], ...] = (
    ("call", "Calls"),
    ("access", "Access"),
    ("type_annotation", "Type Annotations"),
)


def _definition_gutter_width(line_start: int, line_count: int) -> int:
    if line_count <= 0:
        return len(str(line_start))
    return len(str(line_start + line_count - 1))


def _reference_totals(db: CodeDB, qualified_name: str) -> tuple[int, list[str]]:
    counts = {
        row["ref_kind"]: int(row["n"])
        for row in db.connection.execute(_REF_KIND_COUNTS_SQL, (qualified_name,))
    }
    total = sum(counts.get(kind, 0) for kind, _ in _REF_KIND_LABELS)
    lines = [
        f"{label}: {count}"
        for kind, label in _REF_KIND_LABELS
        if (count := counts.get(kind, 0)) > 0
    ]
    return total, lines


def get_symbol_context(db: CodeDB, qualified_name: str) -> str:
    """
    Return symbol metadata, reference totals, and source for the symbol span.

    ``qualified_name`` must equal ``symbols.qualified_name`` (module-prefixed for
    Python). Bare names do not match. Use ``get_symbol_references`` for the
    individual call / access / type-annotation sites.
    """
    key = qualified_name.strip()
    if not key:
        return "No symbol name given; pass a non-empty qualified_name."

    row = db.connection.execute(_SYMBOL_ROW_SQL, (key,)).fetchone()
    if row is None:
        return f"No symbol with qualified_name {key!r} was found."

    path = row["file_path"]
    line_start = int(row["line_start"])
    line_end = int(row["line_end"])

    abs_path = db.root / path
    body_lines: list[str] = []
    try:
        raw_lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line_start < 1:
            body_lines.append("    (invalid line_start)")
        else:
            chunk = raw_lines[line_start - 1 : line_end]
            if not chunk:
                body_lines.append("    (no lines in range)")
            else:
                gutter = _definition_gutter_width(line_start, len(chunk))
                for index, ln in enumerate(chunk):
                    lineno = line_start + index
                    body_lines.append(f"L{lineno:<{gutter}} | {ln}")
    except OSError as e:
        body_lines.append(f"    (could not read source file: {e})")

    lines: list[str] = [
        f"File: {path}",
        "",
    ]
    lines.extend(body_lines)
    ref_total, ref_lines = _reference_totals(db, key)
    lines.extend(["", f"## References ({ref_total})", ""])
    lines.extend(ref_lines)

    return "\n".join(lines) + "\n"
