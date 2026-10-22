from sqlite3 import Row

from src.codeparse_mcp.paths import normalize_repo_file_path
from src.db import CodeDB


def load_indexed_file(db: CodeDB, file_path: str) -> tuple[str, Row | None]:
    error = ""
    row = None
    try:
        path = normalize_repo_file_path(file_path, db.root)
    except ValueError as exc:
        error = str(exc)
    else:
        found = db.connection.execute(
            "SELECT id, path, line_count FROM files WHERE path = ?",
            (path,),
        ).fetchone()
        if found is None:
            error = f"No file matches {path!r}."
        else:
            row = found
    return error, row
