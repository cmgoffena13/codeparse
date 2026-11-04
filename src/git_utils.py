import os
import subprocess
from functools import lru_cache
from pathlib import Path

from pathspec import PathSpec

_GIT_TIMEOUT_S = 5

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


def is_git_controlled(path: Path) -> bool:
    env = os.environ.copy()
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    controlled = False
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],  # noqa: S607
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
            timeout=_GIT_TIMEOUT_S,
            env=env,
        )
        controlled = bool(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        controlled = False
    return controlled


def path_spec_for_indexing(root: Path) -> PathSpec:
    """Load ``<root>/.gitignore`` when ``root`` is inside a git work tree."""
    root = root.resolve()
    gitignore_path = root / ".gitignore"
    if not is_git_controlled(root):
        raise FileNotFoundError(f"{root} is not a git repository; are you in a git repository?")
    return (
        _path_spec_for_root(gitignore_path, gitignore_path.stat().st_mtime)
        if gitignore_path.is_file()
        else PathSpec.from_lines("gitignore", [])
    )


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
