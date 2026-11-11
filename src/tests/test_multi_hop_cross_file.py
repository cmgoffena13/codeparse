from pathlib import Path

from src.db import CodeDB
from src.parsers.class_catalog import ClassCatalog
from src.processor import CodeProcessor


def _write_multi_hop_repo(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    (tmp_path / "a_caller.py").write_text(
        "from z_types import Context\n"
        "\n"
        "\n"
        "class Host:\n"
        "    def __init__(self, context: Context) -> None:\n"
        "        self.context = context\n"
        "\n"
        "    def run(self) -> None:\n"
        "        self.context.engine.execute()\n",
        encoding="utf-8",
    )
    (tmp_path / "z_types.py").write_text(
        "class Engine:\n"
        "    def execute(self) -> None:\n"
        "        pass\n"
        "\n"
        "\n"
        "class Context:\n"
        "    engine: Engine\n",
        encoding="utf-8",
    )


def test_multi_hop_call_resolves_when_type_module_parses_after_caller(tmp_path: Path) -> None:
    _write_multi_hop_repo(tmp_path)
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)

    row = db.connection.execute(
        """
        SELECT sr.ref_symbol_qualified_name, s.qualified_name, sr.context
        FROM symbol_references AS sr
        INNER JOIN symbols AS s ON s.id = sr.ref_symbol_id
        WHERE sr.ref_kind = 'call'
          AND sr.context LIKE 'self.context.engine.execute%'
        """
    ).fetchone()
    assert row is not None
    assert row["ref_symbol_qualified_name"] == "z_types.Engine.execute"
    assert row["qualified_name"] == "z_types.Engine.execute"
    db.close()


def test_seed_from_db_loads_classes_and_signature_types_only(tmp_path: Path) -> None:
    _write_multi_hop_repo(tmp_path)
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)

    catalog = ClassCatalog()
    catalog.seed_from_db(db.connection)

    assert catalog.by_qualified_name["z_types.Context"]["kind"] == "class"
    assert catalog.by_qualified_name["z_types.Engine"]["kind"] == "class"
    assert "z_types.Engine.execute" not in catalog.by_qualified_name
    assert "z_types.Context.engine" not in catalog.by_qualified_name
    assert catalog.field_types["z_types.Context.engine"] == "z_types.Engine"
    assert (
        catalog.rewrite_pending_qualified_name("z_types.Context.engine.execute")
        == "z_types.Engine.execute"
    )
    db.close()


def test_multi_hop_through_package_reexport_resolves_to_defining_class(
    tmp_path: Path,
) -> None:
    (tmp_path / ".gitignore").write_text("# test fixture\n", encoding="utf-8")
    plan_pkg = tmp_path / "pkg" / "plan"
    plan_pkg.mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (plan_pkg / "definition.py").write_text(
        "class DeployabilityIndex:\n"
        "    def is_deployable(self) -> None:\n"
        "        pass\n"
        "\n"
        "\n"
        "class Plan:\n"
        "    deployability_index: DeployabilityIndex\n",
        encoding="utf-8",
    )
    (plan_pkg / "__init__.py").write_text(
        "from pkg.plan.definition import Plan as Plan\n",
        encoding="utf-8",
    )
    (tmp_path / "a_caller.py").write_text(
        "from pkg.plan import Plan\n"
        "\n"
        "\n"
        "class Record:\n"
        "    plan: Plan\n"
        "\n"
        "    def check(self) -> None:\n"
        "        self.plan.deployability_index.is_deployable()\n",
        encoding="utf-8",
    )

    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)

    row = db.connection.execute(
        """
        SELECT sr.ref_symbol_qualified_name, s.qualified_name
        FROM symbol_references AS sr
        INNER JOIN symbols AS s ON s.id = sr.ref_symbol_id
        WHERE sr.ref_kind = 'call'
          AND sr.context LIKE 'self.plan.deployability_index.is_deployable%'
        """
    ).fetchone()
    assert row is not None
    expected = "pkg.plan.definition.DeployabilityIndex.is_deployable"
    assert row["ref_symbol_qualified_name"] == expected
    assert row["qualified_name"] == expected
    db.close()


def test_cold_processor_resolves_multi_hop_from_seeded_types(tmp_path: Path) -> None:
    _write_multi_hop_repo(tmp_path)
    db = CodeDB(tmp_path)
    CodeProcessor(db, tmp_path).process(full=True)

    caller = tmp_path / "a_caller.py"
    caller.write_text(caller.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    CodeProcessor(db, tmp_path).process()

    row = db.connection.execute(
        """
        SELECT sr.ref_symbol_qualified_name
        FROM symbol_references AS sr
        WHERE sr.ref_kind = 'call'
          AND sr.context LIKE 'self.context.engine.execute%'
        """
    ).fetchone()
    assert row is not None
    assert row["ref_symbol_qualified_name"] == "z_types.Engine.execute"
    db.close()
