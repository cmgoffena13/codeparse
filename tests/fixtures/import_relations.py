"""Synthetic package layouts for get_import_relations tests."""

from pathlib import Path

from src.db import CodeDB
from src.processor import CodeProcessor


def write_gitignore(root: Path) -> None:
    (root / ".gitignore").write_text("# test fixture\n", encoding="utf-8")


def index_internal_package(root: Path) -> Path:
    write_gitignore(root)
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "target.py").write_text(
        "FLAG = 1\n\n\ndef helper() -> int:\n    return FLAG\n\n\n"
        "class Worker:\n    def run(self) -> int:\n        return helper()\n",
        encoding="utf-8",
    )
    (pkg / "user.py").write_text(
        "from pkg.target import helper, Worker, FLAG\n\n\n"
        "def run() -> int:\n    Worker().run()\n    return helper() + FLAG\n\n\n"
        "helper()\n",
        encoding="utf-8",
    )
    (pkg / "mod_extra.py").write_text(
        "def noise() -> int:\n    return 0\n",
        encoding="utf-8",
    )
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_user.py").write_text(
        "from pkg.target import helper\n\n\ndef test_helper() -> None:\n    assert helper() == 1\n",
        encoding="utf-8",
    )
    db = CodeDB(root)
    CodeProcessor(db, root).process()
    db.close()
    return root


def index_directory_package(root: Path) -> Path:
    write_gitignore(root)
    pkg = root / "pkg"
    sub = pkg / "lib"
    sub.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (sub / "__init__.py").write_text("", encoding="utf-8")
    (sub / "a.py").write_text(
        "def alpha() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    (sub / "b.py").write_text(
        "from pkg.lib.a import alpha\n\n\ndef beta() -> int:\n    return alpha()\n",
        encoding="utf-8",
    )
    (pkg / "caller.py").write_text(
        "from pkg.lib.b import beta\n\n\ndef go() -> int:\n    return beta()\n",
        encoding="utf-8",
    )
    db = CodeDB(root)
    CodeProcessor(db, root).process()
    db.close()
    return root


def index_external_user(root: Path) -> Path:
    write_gitignore(root)
    (root / "app.py").write_text(
        "from sqlglot import Exp\n\n\ndef run() -> None:\n    Exp()\n",
        encoding="utf-8",
    )
    db = CodeDB(root)
    CodeProcessor(db, root).process(full=True)
    db.close()
    return root


def index_stdlib_user(root: Path) -> Path:
    write_gitignore(root)
    (root / "app.py").write_text(
        "import re\n\n\ndef run() -> None:\n    re.compile('x')\n    re.search('x', 'y')\n",
        encoding="utf-8",
    )
    db = CodeDB(root)
    CodeProcessor(db, root).process(full=True)
    db.close()
    return root
