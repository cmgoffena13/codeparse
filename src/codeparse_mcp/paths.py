"""Normalize tool ``file_path`` args to workspace-relative POSIX paths."""

from pathlib import Path


def normalize_repo_file_path(file_path: str, root: Path) -> str:
    """
    Return ``file_path`` as a POSIX path relative to the workspace ROOT.

    Accepts repo-relative or absolute paths. Raises ``ValueError`` if empty or
    outside ROOT.
    """
    raw = file_path.strip().replace("\\", "/")
    if not raw:
        raise ValueError("file_path is empty")

    root = root.resolve()
    try:
        return (root / raw).resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"file_path {file_path.strip()!r} is outside the workspace ROOT {root}"
        ) from exc
