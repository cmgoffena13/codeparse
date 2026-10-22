from pathlib import Path

from src.db import CodeDB
from src.processor import CodeProcessor


def _index(tmp_path: Path) -> Path:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "base.py").write_text(
        "class GenericContext:\n"
        "    flag = True\n"
        "\n"
        "    def plan(self):\n"
        "        return 1\n"
        "\n"
        "    @property\n"
        "    def size(self):\n"
        "        return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "child.py").write_text(
        "from base import GenericContext\n"
        "\n"
        "\n"
        "class Context(GenericContext):\n"
        "    def apply(self):\n"
        "        return self.plan()\n"
        "\n"
        "\n"
        "class ContextOverride(GenericContext):\n"
        "    def plan(self):\n"
        "        return 2\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)
    db.close()
    return tmp_path


def test_inherited_members_are_linked_on_the_subclass(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    try:
        rows = list(
            db.connection.execute(
                """
                SELECT qualified_name, kind, parent
                FROM symbols
                WHERE parent = 'Context'
                ORDER BY qualified_name
                """
            )
        )
        names = {row["qualified_name"]: row["kind"] for row in rows}
        inherited_flags = {
            row["qualified_name"]: bool(row["is_inherited"])
            for row in db.connection.execute(
                """
                SELECT qualified_name, is_inherited
                FROM symbols
                WHERE qualified_name IN (
                    'child.Context.apply',
                    'child.Context.plan',
                    'child.Context.flag',
                    'child.Context.size',
                    'child.ContextOverride.plan',
                    'base.GenericContext.plan'
                )
                """
            )
        }
        assert names["child.Context.apply"] == "method"
        assert names["child.Context.plan"] == "method"
        assert names["child.Context.flag"] == "variable"
        assert names["child.Context.size"] == "property"
        assert inherited_flags["child.Context.plan"] is True
        assert inherited_flags["child.Context.flag"] is True
        assert inherited_flags["child.Context.size"] is True
        assert inherited_flags["child.Context.apply"] is False
        assert inherited_flags["child.ContextOverride.plan"] is False
        assert inherited_flags["base.GenericContext.plan"] is False
        override = db.connection.execute(
            """
            SELECT line_start, file_id
            FROM symbols
            WHERE qualified_name = 'child.ContextOverride.plan'
            """
        ).fetchone()
        base_plan = db.connection.execute(
            """
            SELECT line_start, file_id
            FROM symbols
            WHERE qualified_name = 'base.GenericContext.plan'
            """
        ).fetchone()
        inherited = db.connection.execute(
            """
            SELECT line_start, file_id
            FROM symbols
            WHERE qualified_name = 'child.Context.plan'
            """
        ).fetchone()
        assert inherited["file_id"] == base_plan["file_id"]
        assert inherited["line_start"] == base_plan["line_start"]
        assert (
            override["file_id"] != base_plan["file_id"]
            or override["line_start"] != base_plan["line_start"]
        )
        override_count = db.connection.execute(
            """
            SELECT COUNT(*) AS c
            FROM symbols
            WHERE qualified_name = 'child.ContextOverride.plan'
            """
        ).fetchone()["c"]
        assert override_count == 1
        refs = list(
            db.connection.execute(
                """
                SELECT ref_symbol_qualified_name
                FROM symbol_references
                WHERE ref_symbol_qualified_name = 'child.Context.plan'
                """
            )
        )
        assert refs
    finally:
        db.close()


def test_inherited_link_is_idempotent(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    CodeProcessor(db, root).process(full=True)
    try:
        count = db.connection.execute(
            "SELECT COUNT(*) AS c FROM symbols WHERE qualified_name = 'child.Context.plan'"
        ).fetchone()["c"]
        assert count == 1
    finally:
        db.close()


def test_child_file_parsed_before_base_still_links(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "a_child.py").write_text(
        "from z_base import GenericContext\n"
        "\n"
        "\n"
        "class Context(GenericContext):\n"
        "    def apply(self):\n"
        "        return self.plan()\n",
        encoding="utf-8",
    )
    (tmp_path / "z_base.py").write_text(
        "class GenericContext:\n    def plan(self):\n        return 1\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)
    try:
        row = db.connection.execute(
            "SELECT qualified_name FROM symbols WHERE qualified_name = 'a_child.Context.plan'"
        ).fetchone()
        assert row is not None
    finally:
        db.close()


def test_base_gains_member_on_incremental(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "base.py").write_text(
        "class GenericContext:\n    def plan(self):\n        return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "child.py").write_text(
        "from base import GenericContext\n"
        "\n"
        "\n"
        "class Context(GenericContext):\n"
        "    def apply(self):\n"
        "        return self.plan()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    processor = CodeProcessor(db, tmp_path)
    try:
        processor.process(full=True)
        (tmp_path / "base.py").write_text(
            "class GenericContext:\n"
            "    def plan(self):\n"
            "        return 1\n"
            "\n"
            "    def reset(self):\n"
            "        return 0\n",
            encoding="utf-8",
        )
        processor.process()
        row = db.connection.execute(
            "SELECT kind FROM symbols WHERE qualified_name = 'child.Context.reset'"
        ).fetchone()
        assert row is not None
        assert row["kind"] == "method"
    finally:
        db.close()


def test_base_dropping_member_drops_inherited_copy(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "base.py").write_text(
        "class GenericContext:\n"
        "    def plan(self):\n"
        "        return 1\n"
        "\n"
        "    def reset(self):\n"
        "        return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "child.py").write_text(
        "from base import GenericContext\n"
        "\n"
        "\n"
        "class Context(GenericContext):\n"
        "    def apply(self):\n"
        "        return self.plan()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    processor = CodeProcessor(db, tmp_path)
    try:
        processor.process(full=True)
        (tmp_path / "base.py").write_text(
            "class GenericContext:\n    def reset(self):\n        return 0\n",
            encoding="utf-8",
        )
        processor.process()
        leftover = db.connection.execute(
            "SELECT qualified_name FROM symbols WHERE qualified_name = 'child.Context.plan'"
        ).fetchone()
        defined = db.connection.execute(
            "SELECT qualified_name FROM symbols WHERE qualified_name = 'base.GenericContext.plan'"
        ).fetchone()
        kept = db.connection.execute(
            "SELECT kind FROM symbols WHERE qualified_name = 'child.Context.reset'"
        ).fetchone()
        apply = db.connection.execute(
            "SELECT kind FROM symbols WHERE qualified_name = 'child.Context.apply'"
        ).fetchone()
        assert leftover is None
        assert defined is None
        assert kept is not None
        assert kept["kind"] == "method"
        assert apply is not None
    finally:
        db.close()


def test_deleting_child_file_drops_inherited_copies(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    processor = CodeProcessor(db, root)
    try:
        (root / "child.py").unlink()
        processor.process()
        leftover = db.connection.execute(
            "SELECT qualified_name FROM symbols WHERE qualified_name = 'child.Context.plan'"
        ).fetchone()
        defined = db.connection.execute(
            "SELECT qualified_name FROM symbols WHERE qualified_name = 'base.GenericContext.plan'"
        ).fetchone()
        assert leftover is None
        assert defined is not None
    finally:
        db.close()


def test_removing_subclass_drops_inherited_copies(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    processor = CodeProcessor(db, root)
    try:
        (root / "child.py").write_text(
            "from base import GenericContext\n",
            encoding="utf-8",
        )
        processor.process()
        leftover = db.connection.execute(
            "SELECT qualified_name FROM symbols WHERE qualified_name = 'child.Context.plan'"
        ).fetchone()
        defined = db.connection.execute(
            "SELECT qualified_name FROM symbols WHERE qualified_name = 'base.GenericContext.plan'"
        ).fetchone()
        assert leftover is None
        assert defined is not None
    finally:
        db.close()


def test_same_file_removed_subclass_drops_inherited_copies(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "mod.py").write_text(
        "class GenericContext:\n"
        "    def plan(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "class Context(GenericContext):\n"
        "    def apply(self):\n"
        "        return self.plan()\n",
        encoding="utf-8",
    )
    db = CodeDB(tmp_path)
    processor = CodeProcessor(db, tmp_path)
    try:
        processor.process(full=True)
        (tmp_path / "mod.py").write_text(
            "class GenericContext:\n    def plan(self):\n        return 1\n",
            encoding="utf-8",
        )
        processor.process()
        leftover = db.connection.execute(
            "SELECT qualified_name FROM symbols WHERE qualified_name = 'mod.Context.plan'"
        ).fetchone()
        defined = db.connection.execute(
            "SELECT qualified_name FROM symbols WHERE qualified_name = 'mod.GenericContext.plan'"
        ).fetchone()
        assert leftover is None
        assert defined is not None
    finally:
        db.close()


def test_reparsing_base_keeps_inherited_copy(tmp_path: Path) -> None:
    root = _index(tmp_path)
    db = CodeDB(root)
    processor = CodeProcessor(db, root)
    try:
        (root / "base.py").write_text(
            (root / "base.py").read_text(encoding="utf-8") + "\n# keep\n",
            encoding="utf-8",
        )
        processor.process()
        count = db.connection.execute(
            "SELECT COUNT(*) AS c FROM symbols WHERE qualified_name = 'child.Context.plan'"
        ).fetchone()["c"]
        assert count == 1
    finally:
        db.close()
