from src.codeparse_mcp.indexed_file import load_indexed_file
from src.db import CodeDB

_IMPORTS_SQL = """
SELECT
    line_number,
    signature
FROM imports
WHERE file_id = ?
ORDER BY line_number
"""


def _gutter_width(*line_numbers: int) -> int:
    positives = [n for n in line_numbers if n > 0]
    if not positives:
        return 1
    return len(str(max(positives)))


def get_file_imports(db: CodeDB, file_path: str) -> str:
    """
    Return import statements for one file.

    Imports use a padded ``L{n}`` gutter. ``file_path`` is normalized to a POSIX
    path relative to the workspace root (e.g. ``pkg/mod.py``).
    """
    error, file_row = load_indexed_file(db, file_path)
    result = error
    if file_row is not None:
        imp_rows = list(db.connection.execute(_IMPORTS_SQL, (file_row["id"],)))
        lines_out: list[str] = [
            f"Total Imports: {len(imp_rows)}",
            "",
        ]
        if not imp_rows:
            lines_out.append("No imports found.")
        else:
            seen_signatures: set[str] = set()
            import_lines: list[tuple[int, str]] = []
            for row in imp_rows:
                line_n = int(row["line_number"] or 0)
                sig = (row["signature"] or "").strip() or "—"
                if sig != "—" and sig in seen_signatures:
                    continue
                if sig != "—":
                    seen_signatures.add(sig)
                import_lines.append((line_n, sig))
            gutter = _gutter_width(*(n for n, _ in import_lines), int(file_row["line_count"] or 0))
            for line_n, sig in import_lines:
                if line_n > 0:
                    lines_out.append(f"L{line_n:<{gutter}}  {sig}")
                else:
                    lines_out.append(sig)
        result = "\n".join(lines_out) + "\n"
    return result
