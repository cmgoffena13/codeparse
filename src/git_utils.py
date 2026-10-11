from functools import lru_cache
from pathlib import Path

from pathspec import PathSpec

INDEX_ALWAYS_IGNORE_NAMES = frozenset(
    {
        ".git",
        ".venv",
        ".env",
        ".DS_Store",
        ".gitignore",
        "__pycache__",
        "dist",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".vscode",
    }
)


@lru_cache
def _path_spec_for_root(gitignore_path: Path, _gitignore_mtime: float) -> PathSpec:
    """Load ``.gitignore`` lines as Git ignore patterns. Mtime is only the cache key."""
    text = gitignore_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return PathSpec.from_lines("gitignore", lines)


def path_spec_for_indexing(root: Path) -> PathSpec:
    """Load ``<root>/.gitignore`` (paths relative to ``root``). Raises if the file is missing."""
    root = root.resolve()
    gitignore_path = root / ".gitignore"
    if not gitignore_path.is_file():
        raise FileNotFoundError(
            f".gitignore not found at {gitignore_path}; are you in a git repository?"
        )
    return _path_spec_for_root(gitignore_path, gitignore_path.stat().st_mtime)


def relative_path_is_ignored(
    relative: Path,
    is_directory: bool,
    spec: PathSpec,
) -> bool:
    if relative.is_absolute():
        raise ValueError("relative path must not be absolute")
    for part in relative.parts:
        if part in INDEX_ALWAYS_IGNORE_NAMES:
            return True
    rel_posix = relative.as_posix()
    if is_directory:
        return spec.match_file(rel_posix + "/") or spec.match_file(rel_posix)
    return spec.match_file(rel_posix)
