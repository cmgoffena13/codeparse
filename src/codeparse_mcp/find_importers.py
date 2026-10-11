"""Reverse-import lookup: which files import a given module."""

from src.codeparse_mcp.format_utils import bullet
from src.codeparse_mcp.paths import normalize_repo_file_path
from src.db import CodeDB

_MAX_IMPORTER_FILES = 100

_IMPORTERS_SQL = """
SELECT DISTINCT 
f.path AS importer_path
FROM imports AS i
INNER JOIN files AS f
    ON f.id = i.file_id
INNER JOIN files AS target
    ON target.id = i.imported_file_id
WHERE target.path = ?
{test_filter}
ORDER BY f.path
"""


def find_importers(db: CodeDB, file_path: str, *, include_tests: bool = False) -> str:
    """
    List files that import the module at ``file_path``.

    ``file_path`` is a repo-relative file path (e.g. ``pkg/mod.py``). Matching
    is by ``imports.imported_file_id``.

    By default skips importer files marked ``is_test``.
    """
    try:
        path = normalize_repo_file_path(file_path, db.root)
    except ValueError as exc:
        return str(exc)

    rows = list(
        db.connection.execute(
            _IMPORTERS_SQL.format(test_filter="" if include_tests else "  AND f.is_test = 0"),
            (path,),
        )
    )
    if not rows:
        return f"No importers of {path} were found."

    paths = [row["importer_path"] for row in rows]
    total = len(paths)
    lines_out = [
        f"Importers of {path} — {total} files",
        "",
        *(bullet(p) for p in paths[:_MAX_IMPORTER_FILES]),
    ]
    if total > _MAX_IMPORTER_FILES:
        lines_out.extend(["", f"...[{total - _MAX_IMPORTER_FILES} more importer files truncated]"])
    return "\n".join(lines_out).rstrip() + "\n"
