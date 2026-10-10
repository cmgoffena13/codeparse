import hashlib
import os
import shutil
import sys
import tomllib
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    pass
else:
    load_dotenv()


def get_version() -> str:
    """Get the version of the application."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if not isinstance(meipass, str):
            raise RuntimeError("frozen build missing sys._MEIPASS")
        pyproject_path = Path(meipass) / "pyproject.toml"
        if not pyproject_path.exists():
            exe = Path(getattr(sys, "executable", None) or sys.argv[0])
            pyproject_path = exe.parent / "pyproject.toml"
    else:
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"

    if not pyproject_path.exists():
        raise FileNotFoundError(f"Could not find pyproject.toml at {pyproject_path}")

    with pyproject_path.open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def is_compiled() -> bool:
    """True when running as the Nuitka-compiled binary (Nuitka never sets ``sys.frozen``)."""
    return "__compiled__" in globals()


def binary_path() -> Path:
    """Absolute path to the codeparse executable.

    Nuitka onefile sets ``sys.argv[0]`` to the binary the user ran; ``sys.executable``
    is the Python unpacked into a temporary directory. A bare name from a PATH
    lookup is resolved with ``shutil.which``, and symlinks are followed.
    """
    invoked = Path(sys.argv[0])
    if not invoked.is_absolute():
        found = shutil.which(sys.argv[0])
        if found:
            invoked = Path(found)
    return invoked.resolve()


def ensure_dir(path: Path) -> Path:
    """Create a directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_code_parse_config_dir(*parts: str) -> Path:
    """
    Base directory for codeparse local config/data (indexes, etc.).

    Uses ``$CODE_PARSE_CONFIG_DIR`` when set; otherwise ``~/.config/codeparse``.

    If ``parts`` are provided, returns ``<base>/<parts...>`` and creates it.
    """
    override = os.environ.get("CODE_PARSE_CONFIG_DIR")
    base = Path(override) if override else Path.home() / ".config" / "codeparse"
    return ensure_dir(base.joinpath(*parts))


def db_path_for_index_root(index_root: Path) -> Path:
    """SQLite path for an indexed tree: ``<config>/indexes/<sha256(root)>.db``."""
    key = str(index_root.resolve()).encode()
    digest = hashlib.sha256(key).hexdigest()
    return get_code_parse_config_dir("indexes") / f"{digest}.db"
