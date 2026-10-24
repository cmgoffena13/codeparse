"""Repo map: largest directories and where the program starts."""

import tomllib
from pathlib import Path

from src.codeparse_mcp.format_utils import bullet, file_label
from src.db import CodeDB

_TOP_DIRECTORIES = 10

_DIRECTORIES_SQL = """
SELECT
    d.path,
    COUNT(f.id) AS file_count,
    SUM(f.line_count) AS line_count,
    SUM(f.symbol_count) AS symbol_count
FROM files AS f
LEFT JOIN directories AS d
    ON d.id = f.directory_id
WHERE f.is_test = 0
GROUP BY d.path
HAVING SUM(f.symbol_count) > 0
ORDER BY symbol_count DESC, d.path
LIMIT ?
"""

_PYTHON_ENTRY_POINTS_SQL = """
SELECT
    f.path,
    f.line_count,
    f.symbol_count,
    e.has_main_guard,
    e.is_named_entry
FROM files AS f
INNER JOIN entry_points AS e
    ON e.id = f.id
ORDER BY f.path
"""

_MODULE_FILES_SQL = """
SELECT path, normalized_path, line_count, symbol_count
FROM files
WHERE normalized_path IN ({placeholders})
"""


def _script_targets(root: Path) -> tuple[list[tuple[str, str]], str | None]:
    """Return ``(command, qualified_name)`` pairs, plus a parse error if any."""
    path = root / "pyproject.toml"
    if not path.is_file():
        return [], None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return [], f"pyproject.toml could not be parsed: {exc}"
    scripts = data.get("project", {}).get("scripts", {})
    if not isinstance(scripts, dict):
        return [], None
    targets: list[tuple[str, str]] = []
    for name in sorted(scripts):
        target = scripts[name]
        if not isinstance(target, str) or not target.strip():
            continue
        targets.append((name, target.strip().replace(":", ".", 1)))
    return targets, None


def _entry_point_lines(db: CodeDB) -> list[str]:
    """One line per file. Scripts, then ``app.py`` / ``main.py``, then ``__main__``."""
    file_stats: dict[str, tuple[int, int]] = {}
    named: set[str] = set()
    guards: set[str] = set()
    for row in db.connection.execute(_PYTHON_ENTRY_POINTS_SQL):
        path = row["path"]
        file_stats[path] = (int(row["line_count"]), int(row["symbol_count"]))
        if row["is_named_entry"]:
            named.add(path)
        if row["has_main_guard"]:
            guards.add(path)

    scripts, _error = _script_targets(db.root)
    modules = [
        (qualified.rsplit(".", 1)[0] if "." in qualified else qualified).lower()
        for _command, qualified in scripts
    ]
    by_module = {}
    if modules:
        placeholders = ",".join("?" * len(modules))
        for row in db.connection.execute(
            _MODULE_FILES_SQL.format(placeholders=placeholders),
            modules,
        ):
            by_module[row["normalized_path"]] = row

    lines: list[str] = []
    claimed: set[str] = set()
    for module in modules:
        row = by_module.get(module)
        if row is None or row["path"] in claimed:
            continue
        path = row["path"]
        file_stats[path] = (int(row["line_count"]), int(row["symbol_count"]))
        claimed.add(path)
        lines.append(bullet(file_label(path, *file_stats[path])))

    for path in sorted(named - claimed):
        lines.append(bullet(file_label(path, *file_stats[path])))
        claimed.add(path)

    for path in sorted(guards - claimed):
        lines.append(bullet(file_label(path, *file_stats[path])))

    return lines or ["No entry points."]


def get_project_overview(db: CodeDB) -> str:
    """
    Top directories by symbol count, plus entry points from ``pyproject.toml``
    scripts, ``app.py`` / ``main.py``, and ``if __name__ == "__main__"``.

    Counts use files that sit directly in each directory. Test files are skipped.
    """
    directories = list(db.connection.execute(_DIRECTORIES_SQL, (_TOP_DIRECTORIES,)).fetchall())
    entry_points = _entry_point_lines(db)

    lines = [
        "Directories - Top 10",
        "",
    ]
    if directories:
        for row in directories:
            symbols = int(row["symbol_count"])
            line_count = int(row["line_count"])
            files = int(row["file_count"])
            directory = row["path"] or "root"
            lines.append(bullet(f"{directory} ({line_count}L, {symbols}S, {files}F)"))
    else:
        lines.append("No directories found.")

    lines.extend(["", "Entrypoints", ""])
    lines.extend(entry_points)

    return "\n".join(lines).rstrip() + "\n"
