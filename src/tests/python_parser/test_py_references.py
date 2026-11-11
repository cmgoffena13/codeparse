from src.tests.python_parser._assertions import (
    assert_reference_shape,
    assert_symbol_references_invariants,
    assert_symbols_invariants,
    index_symbols,
)


def test_import_after_path_use_same_suite_still_rewrites_path_call(python_parser, fixture_bytes):
    """Import below Path(...) must still register before sibling refs (import-first walk)."""
    file_bytes = fixture_bytes("import_after_use_path.py")
    _, references = python_parser.parse(45, file_bytes)

    assert_symbol_references_invariants(references)
    assert any(
        r["ref_kind"] == "call" and r["ref_symbol_qualified_name"] == "pathlib.Path"
        for r in references
    )


def test_stdlib_package_calls_recorded_builtin_methods_filtered(python_parser, fixture_bytes):
    """Stdlib package uses are kept; builtin method calls stay filtered."""
    file_bytes = fixture_bytes("external_refs_filter.py")
    _, references = python_parser.parse(41, file_bytes)

    assert_symbol_references_invariants(references)
    assert any(
        r["ref_kind"] == "call" and r["ref_symbol_qualified_name"] == "pathlib.Path"
        for r in references
    )
    assert not any(r["ref_kind"] == "call" and "join" in r["ref_symbol_name"] for r in references)
    assert not any(
        r["ref_kind"] == "call" and r["ref_symbol_name"] == "files.values" for r in references
    )
    assert not any(r["ref_symbol_qualified_name"] == "dict.values" for r in references)


def test_expression_receiver_method_calls_are_not_recorded(python_parser) -> None:
    source = b"""
def run(macros_dir, parts):
    (macros_dir / "broken_jinja.sql").write_text("x")
    "__".join(parts).replace("-", "_")
    (defaults or {}).get("a")
"""
    _, references = python_parser.parse(91, source, module_qn="pkg.mod")
    assert not any("write_text" in r["ref_symbol_qualified_name"] for r in references)
    assert not any("replace" in r["ref_symbol_qualified_name"] for r in references)
    assert not any(r["ref_symbol_name"].endswith(".get") for r in references)
    assert not any("(" in r["ref_symbol_qualified_name"] for r in references)


def test_self_attr_call_resolves_via_init_param_annotation(python_parser, fixture_bytes):
    """self.dep.* resolves via __init__ param type (DependencyType)."""
    file_bytes = fixture_bytes("ctor_param_self_call.py")
    symbols, references = python_parser.parse(40, file_bytes)

    assert_symbols_invariants(symbols)
    assert_symbol_references_invariants(references)

    call = next(
        r
        for r in references
        if r["ref_kind"] == "call" and r["ref_symbol_name"] == "self.dep.invoke"
    )
    assert call["ref_symbol_qualified_name"] == "DependencyType.invoke"

    access = next(
        r for r in references if r["ref_kind"] == "access" and r["ref_symbol_name"] == "self.dep"
    )
    assert access["ref_symbol_qualified_name"] == "DependencyType"


def test_multi_hop_self_attr_call_resolves_via_field_types(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("multi_hop_self_call.py")
    _, references = python_parser.parse(110, file_bytes, module_qn="pkg.mod")
    assert_symbol_references_invariants(references)
    call = next(
        r
        for r in references
        if r["ref_kind"] == "call" and r["ref_symbol_name"] == "self.context.engine.execute"
    )
    assert call["ref_symbol_qualified_name"] == "pkg.mod.Engine.execute"


def test_class_body_attr_call_resolves_via_annotation(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("class_body_attr_call.py")
    _, references = python_parser.parse(111, file_bytes, module_qn="pkg.mod")
    assert_symbol_references_invariants(references)
    call = next(
        r
        for r in references
        if r["ref_kind"] == "call" and r["ref_symbol_name"] == "self.engine.execute"
    )
    assert call["ref_symbol_qualified_name"] == "pkg.mod.Engine.execute"


def test_untyped_local_from_attr_resolves_method_call(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("untyped_local_from_attr.py")
    _, references = python_parser.parse(112, file_bytes, module_qn="pkg.mod")
    assert_symbol_references_invariants(references)
    call = next(
        r for r in references if r["ref_kind"] == "call" and r["ref_symbol_name"] == "ctx.plan"
    )
    assert call["ref_symbol_qualified_name"] == "pkg.mod.Context.plan"


def test_untyped_local_from_call_resolves_return_type(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("untyped_local_from_call.py")
    _, references = python_parser.parse(113, file_bytes, module_qn="pkg.mod")
    assert_symbol_references_invariants(references)
    call = next(
        r for r in references if r["ref_kind"] == "call" and r["ref_symbol_name"] == "node.apply"
    )
    assert call["ref_symbol_qualified_name"] == "pkg.mod.Plan.apply"


def test_second_assignment_clears_untyped_local_type(python_parser) -> None:
    source = b"""
class Context:
    def plan(self) -> None:
        pass

class HostClass:
    def __init__(self, context: Context) -> None:
        self.context = context

    def run(self, other) -> None:
        ctx = self.context
        ctx = other
        ctx.plan()
"""
    _, references = python_parser.parse(114, source, module_qn="pkg.mod")
    assert not any(r["ref_symbol_qualified_name"] == "pkg.mod.Context.plan" for r in references)
    assert not any(r["ref_symbol_qualified_name"] == "ctx.plan" for r in references)


def test_symbol_references_access_and_type_annotation(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("references_cases.py")
    symbols, references = python_parser.parse(4, file_bytes)

    assert len(symbols) == 6
    assert_symbols_invariants(symbols)
    assert_symbol_references_invariants(references)
    for r in references:
        assert_reference_shape(r, expected_file_id=4)

    assert any(
        r["ref_kind"] == "access" and r["ref_symbol_name"] == "self.value" for r in references
    )
    assert not any(
        r["ref_kind"] == "type_annotation" and r["ref_symbol_name"] == "int" for r in references
    )
    assert any(
        r["ref_kind"] == "call" and r["ref_symbol_qualified_name"] == "pathlib.Path"
        for r in references
    )


def test_symbol_references_ids_are_unique_with_repeated_calls(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("duplicate_reference_ids.py")
    symbols, references = python_parser.parse(5, file_bytes)

    assert len(symbols) == 2
    assert len(references) == 2
    assert_symbols_invariants(symbols)
    assert_symbol_references_invariants(references)
    for r in references:
        assert_reference_shape(r, expected_file_id=5)

    call_refs = [
        r for r in references if r["ref_kind"] == "call" and r["ref_symbol_name"] == "callee"
    ]
    assert len(call_refs) == 2
    assert {r["source_line"] for r in call_refs} == {6, 7}


def test_class_attr_name_shadowed_by_local_keeps_unique_ref_ids(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("class_attr_shadowed_by_local.py")
    symbols, references = python_parser.parse(186, file_bytes, module_qn="pkg.harness")

    assert_symbols_invariants(symbols)
    assert_symbol_references_invariants(references)
    for r in references:
        assert_reference_shape(r, expected_file_id=186)

    access_qn = "pkg.harness.HarnessResults.results"
    accesses = [
        r
        for r in references
        if r["ref_kind"] == "access" and r["ref_symbol_qualified_name"] == access_qn
    ]
    assert len(accesses) == 1
    assert accesses[0]["context"] == "results.results"
    assert any(
        r["ref_kind"] == "call"
        and r["ref_symbol_qualified_name"] == "pkg.harness.HarnessResults.results.append"
        for r in references
    )


def test_same_line_duplicate_calls_get_distinct_ids(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("same_line_duplicate_refs.py")
    symbols, references = python_parser.parse(55, file_bytes)

    assert_symbols_invariants(symbols)
    assert_symbol_references_invariants(references)
    for r in references:
        assert_reference_shape(r, expected_file_id=55)

    call_refs = [
        r for r in references if r["ref_kind"] == "call" and r["ref_symbol_name"] == "callee"
    ]
    assert len(call_refs) == 2
    assert call_refs[0]["source_line"] == call_refs[1]["source_line"] == 6
    assert call_refs[0]["source_column"] != call_refs[1]["source_column"]
    assert call_refs[0]["id"] != call_refs[1]["id"]


def test_same_module_simple_name_gets_module_prefix(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("ref_qn_same_module.py")
    _, references = python_parser.parse(50, file_bytes, module_qn="pkg.mod")

    assert_symbol_references_invariants(references)
    call = next(
        r for r in references if r["ref_kind"] == "call" and r["ref_symbol_name"] == "helper"
    )
    assert call["ref_symbol_qualified_name"] == "pkg.mod.helper"


def test_same_module_class_member_access_gets_module_prefix(python_parser) -> None:
    source = b"""
from enum import Enum

class ChunkType(Enum):
    JINJA_QUERY = 1
    SQL = 2

def parse(chunk_type):
    return chunk_type == ChunkType.JINJA_QUERY
"""
    _, references = python_parser.parse(92, source, module_qn="pkg.mod")
    access = next(
        r
        for r in references
        if r["ref_kind"] == "access" and r["ref_symbol_name"] == "ChunkType.JINJA_QUERY"
    )
    assert access["ref_symbol_qualified_name"] == "pkg.mod.ChunkType.JINJA_QUERY"


def test_forward_same_module_class_member_access_gets_module_prefix(python_parser) -> None:
    source = b"""
from enum import Enum

class ModelKindMixin:
    def is_seed(self):
        return self.model_kind_name == ModelKindName.SEED

class ModelKindName(str, ModelKindMixin, Enum):
    SEED = "seed"
"""
    _, references = python_parser.parse(96, source, module_qn="pkg.mod")
    access = next(
        r
        for r in references
        if r["ref_kind"] == "access" and r["ref_symbol_name"] == "ModelKindName.SEED"
    )
    assert access["ref_symbol_qualified_name"] == "pkg.mod.ModelKindName.SEED"
    assert not any(r["ref_symbol_qualified_name"] == "ModelKindName.SEED" for r in references)


def test_module_alias_assignment_rewrites_member_access(python_parser) -> None:
    source = b"""
from sqlglot import exp

DATA_TYPE = exp.DataType.Type

def run():
    return DATA_TYPE.BOOLEAN
"""
    _, references = python_parser.parse(93, source, module_qn="pkg.mod")
    access = next(
        r
        for r in references
        if r["ref_kind"] == "access" and r["ref_symbol_name"] == "DATA_TYPE.BOOLEAN"
    )
    assert access["ref_symbol_qualified_name"] == "sqlglot.exp.DataType.Type.BOOLEAN"


def test_constructor_assignment_skips_builtin_method_keeps_var_access(python_parser) -> None:
    source = b"""
from datetime import date

DATA_START_DATE = date(2022, 6, 1)
DATA_START_DATE_STR = DATA_START_DATE.strftime("%Y-%m-%d")
"""
    symbols, references = python_parser.parse(94, source, module_qn="pkg.mod")
    assert not any(r["ref_symbol_qualified_name"] == "DATA_START_DATE.strftime" for r in references)
    assert not any(r["ref_symbol_qualified_name"] == "date.strftime" for r in references)
    assert any(s["qualified_name"] == "pkg.mod.DATA_START_DATE" for s in symbols)


def test_factory_return_type_rewrites_instance_method_call(python_parser) -> None:
    source = b"""
from jinja2 import Environment

def environment() -> Environment:
    return Environment()

ENVIRONMENT = environment()

def run(jinja_str):
    return ENVIRONMENT.parse(jinja_str)
"""
    _, references = python_parser.parse(95, source, module_qn="pkg.mod")
    assert not any(r["ref_symbol_qualified_name"] == "ENVIRONMENT.parse" for r in references)
    call = next(
        r
        for r in references
        if r["ref_kind"] == "call" and r["ref_symbol_name"] == "ENVIRONMENT.parse"
    )
    assert call["ref_symbol_qualified_name"] == "jinja2.Environment.parse"


def test_absolute_from_import_rewrites_ref_qn(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("ref_qn_absolute_import.py")
    _, references = python_parser.parse(51, file_bytes, module_qn="app.main")

    assert_symbol_references_invariants(references)
    call = next(
        r for r in references if r["ref_kind"] == "call" and r["ref_symbol_name"] == "Thing.run"
    )
    assert call["ref_symbol_qualified_name"] == "pkg.mod.Thing.run"


def test_import_module_alias_rewrites_ref_qn(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("ref_qn_import_alias.py")
    _, references = python_parser.parse(52, file_bytes, module_qn="app.main")

    assert_symbol_references_invariants(references)
    call = next(
        r for r in references if r["ref_kind"] == "call" and r["ref_symbol_name"] == "m.Thing"
    )
    assert call["ref_symbol_qualified_name"] == "pkg.mod.Thing"


def test_relative_from_import_rewrites_ref_qn(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("ref_qn_relative_import.py")
    _, references = python_parser.parse(53, file_bytes, module_qn="pkg.sub.caller")

    assert_symbol_references_invariants(references)
    call = next(r for r in references if r["ref_kind"] == "call" and r["ref_symbol_name"] == "Foo")
    assert call["ref_symbol_qualified_name"] == "pkg.sub.sib.Foo"


def test_ctor_param_imported_type_rewrites_via_import_qn(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("ctor_param_imported_type.py")
    _, references = python_parser.parse(54, file_bytes, module_qn="pkg.host")

    assert_symbol_references_invariants(references)
    call = next(
        r
        for r in references
        if r["ref_kind"] == "call" and r["ref_symbol_name"] == "self.dep.invoke"
    )
    assert call["ref_symbol_qualified_name"] == "other.types.DependencyType.invoke"

    access = next(
        r for r in references if r["ref_kind"] == "access" and r["ref_symbol_name"] == "self.dep"
    )
    assert access["ref_symbol_qualified_name"] == "other.types.DependencyType"


def test_param_receiver_call_resolves_via_annotation(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("param_receiver_call.py")
    _, references = python_parser.parse(56, file_bytes, module_qn="pkg.mod")

    assert_symbol_references_invariants(references)
    calls = [
        r
        for r in references
        if r["ref_kind"] == "call"
        and r["ref_symbol_name"] == "deployability_index.is_representative"
    ]
    assert len(calls) == 3
    assert all(
        r["ref_symbol_qualified_name"] == "pkg.mod.DeployabilityIndex.is_representative"
        for r in calls
    )


def test_builtin_method_call_skips_builtin_qn_keeps_variable_access(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("builtin_method_variable.py")
    symbols, references = python_parser.parse(70, file_bytes, module_qn="pkg.mod")
    assert_symbol_references_invariants(references)
    by_qn = index_symbols(symbols)

    assert not any(r["ref_symbol_qualified_name"] == "dict.get" for r in references)
    assert not any(
        r["ref_kind"] == "call" and r["ref_symbol_name"] == "ITEMS.get" for r in references
    )

    accesses = [
        r
        for r in references
        if r["ref_kind"] == "access" and r["ref_symbol_qualified_name"] == "pkg.mod.ITEMS"
    ]
    assert len(accesses) == 1
    assert accesses[0]["ref_symbol_name"] == "ITEMS"
    assert accesses[0]["source_symbol_id"] == by_qn["pkg.mod.Box.run"]["id"]


def test_annotated_str_method_call_does_not_record_str_lower(python_parser) -> None:
    source = b"def run(value: str) -> str:\n    return value.lower()\n"
    _, references = python_parser.parse(90, source, module_qn="pkg.mod")
    assert not any(r["ref_symbol_qualified_name"] == "str.lower" for r in references)


def test_annotated_local_method_call_resolves_to_type(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("typed_local_call.py")
    _, references = python_parser.parse(80, file_bytes, module_qn="pkg.mod")
    call = next(
        r
        for r in references
        if r["ref_kind"] == "call" and r["ref_symbol_name"] == "worker.process"
    )
    assert call["ref_symbol_qualified_name"] == "pkg.mod.Worker.process"


def test_dict_literal_assignment_skips_builtin_method_keeps_var_access(python_parser):
    source = b"ITEMS = {}\n\ndef run():\n    return ITEMS.get('a')\n"
    _, references = python_parser.parse(71, source, module_qn="pkg.mod")
    assert not any(r["ref_symbol_qualified_name"] == "ITEMS.get" for r in references)
    assert not any(r["ref_symbol_qualified_name"] == "dict.get" for r in references)
    accesses = [
        r
        for r in references
        if r["ref_kind"] == "access" and r["ref_symbol_qualified_name"] == "pkg.mod.ITEMS"
    ]
    assert len(accesses) == 1
    assert accesses[0]["ref_symbol_name"] == "ITEMS"


def test_or_empty_dict_assignment_skips_dict_pop(python_parser) -> None:
    source = b"""
def load(project_yaml, package_name):
    all_variables = project_yaml.get("vars") or {}
    all_variables.update(all_variables.pop(package_name, None) or {})
"""
    _, references = python_parser.parse(100, source, module_qn="pkg.mod")
    assert not any(r["ref_symbol_qualified_name"] == "all_variables.pop" for r in references)
    assert not any(r["ref_symbol_qualified_name"] == "dict.pop" for r in references)
    assert not any(r["ref_symbol_qualified_name"] == "all_variables.update" for r in references)


def test_parse_argstring_assign_does_not_record_args_attrs(python_parser) -> None:
    source = b"""
from IPython.core.magic_arguments import parse_argstring

def init(line):
    args = parse_argstring(init, line)
    return args.engine
"""
    _, references = python_parser.parse(101, source, module_qn="pkg.mod")
    assert not any(r["ref_symbol_qualified_name"] == "args.engine" for r in references)
    assert not any(r["ref_symbol_qualified_name"] == "parse_argstring.engine" for r in references)


def test_method_factory_assign_does_not_type_as_callee_path(python_parser) -> None:
    source = b"""
def test_pool(config):
    adapter = config.create_engine_adapter()
    return adapter._connection_pool
"""
    _, references = python_parser.parse(102, source, module_qn="pkg.mod")
    assert not any(
        r["ref_symbol_qualified_name"] == "config.create_engine_adapter._connection_pool"
        for r in references
    )
    assert not any(r["ref_symbol_qualified_name"] == "adapter._connection_pool" for r in references)


def test_re_compile_assignment_skips_pattern_search(python_parser) -> None:
    source = b"""
import re

GATEWAY_PATTERN = re.compile(r"gateway:\\s*([^\\s]+)")

def load(source):
    return GATEWAY_PATTERN.search(source)
"""
    _, references = python_parser.parse(104, source, module_qn="pkg.mod")
    assert any(
        r["ref_kind"] == "call" and r["ref_symbol_qualified_name"] == "re.compile"
        for r in references
    )
    assert not any(r["ref_symbol_qualified_name"] == "GATEWAY_PATTERN.search" for r in references)
    assert not any("GATEWAY_PATTERN." in r["ref_symbol_qualified_name"] for r in references)


def test_union_type_annotation_splits_members(python_parser) -> None:
    source = b"""
import typing as t
from pkg.adapters import EngineAdapter

class SnapshotEvaluator:
    def __init__(self, adapters: EngineAdapter | t.Dict[str, EngineAdapter]) -> None:
        self.adapters = adapters
"""
    _, references = python_parser.parse(103, source, module_qn="pkg.mod")
    assert not any("|" in r["ref_symbol_qualified_name"] for r in references)
    assert any(
        r["ref_kind"] == "type_annotation"
        and r["ref_symbol_qualified_name"] == "pkg.adapters.EngineAdapter"
        for r in references
    )


def test_untyped_loop_var_method_call_is_not_recorded(python_parser) -> None:
    source = b"""
def run(pairs):
    return {(a.sql(), b.sql()) for (a, b), _ in pairs}
"""
    _, references = python_parser.parse(97, source, module_qn="pkg.mod")
    assert not any(r["ref_symbol_qualified_name"] == "a.sql" for r in references)
    assert not any(r["ref_symbol_qualified_name"] == "b.sql" for r in references)


def test_underscore_local_attr_access_is_not_recorded(python_parser) -> None:
    source = b"""
def run(diff):
    _row_diff = diff.row_diff()
    return _row_diff.joined_sample
"""
    _, references = python_parser.parse(98, source, module_qn="pkg.mod")
    assert not any(r["ref_symbol_qualified_name"] == "_row_diff.joined_sample" for r in references)


def test_factory_class_arg_rewrites_instance_method_call(python_parser) -> None:
    source = b"""
from pkg.adapters import NonTransactionalTruncateMixin

def make_mocked_engine_adapter(cls, name):
    return cls()

def test_truncate():
    adapter = make_mocked_engine_adapter(NonTransactionalTruncateMixin, "redshift")
    adapter._truncate_table(table_name="test_table")
"""
    _, references = python_parser.parse(99, source, module_qn="pkg.tests")
    assert not any(r["ref_symbol_qualified_name"] == "adapter._truncate_table" for r in references)
    call = next(
        r
        for r in references
        if r["ref_kind"] == "call" and r["ref_symbol_name"] == "adapter._truncate_table"
    )
    assert (
        call["ref_symbol_qualified_name"]
        == "pkg.adapters.NonTransactionalTruncateMixin._truncate_table"
    )


def test_variable_comparison_is_access(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("variable_comparison.py")
    symbols, references = python_parser.parse(73, file_bytes, module_qn="pkg.check")
    assert_symbol_references_invariants(references)
    by_qn = index_symbols(symbols)
    accesses = [
        r
        for r in references
        if r["ref_kind"] == "access" and r["ref_symbol_qualified_name"] == "pkg.flags.BACKFILL"
    ]
    assert {r["source_line"] for r in accesses} == {5, 7, 9}
    assert {r["ref_symbol_name"] for r in accesses} == {"BACKFILL"}
    assert {r["source_symbol_id"] for r in accesses} == {by_qn["pkg.check.run"]["id"]}


def test_bare_variable_uses_are_accesses(python_parser, fixture_bytes):
    file_bytes = fixture_bytes("variable_bare_uses.py")
    symbols, references = python_parser.parse(72, file_bytes, module_qn="pkg.mod")
    assert_symbol_references_invariants(references)
    by_qn = index_symbols(symbols)
    assert not any(r["source_line"] == 3 for r in references)

    items = [
        r
        for r in references
        if r["ref_kind"] == "access" and r["ref_symbol_qualified_name"] == "pkg.mod.ITEMS"
    ]
    assert len(items) == 4
    assert {r["source_line"] for r in items} == {7, 9, 11, 12}
    assert {r["ref_symbol_name"] for r in items} == {"ITEMS"}
    assert {r["source_symbol_id"] for r in items} == {by_qn["pkg.mod.run"]["id"]}

    imported = [
        r
        for r in references
        if r["ref_kind"] == "access" and r["ref_symbol_qualified_name"] == "pkg.data.ITEMS"
    ]
    assert len(imported) == 2
    assert {r["source_line"] for r in imported} == {16, 17}
    assert {r["ref_symbol_name"] for r in imported} == {"BOX"}
    assert {r["source_symbol_id"] for r in imported} == {by_qn["pkg.mod.imported"]["id"]}


def test_source_symbol_id_is_the_enclosing_container(python_parser):
    source = (
        b"def helper():\n"
        b"    return 1\n"
        b"\n"
        b"def outer():\n"
        b"    def inner():\n"
        b"        return helper()\n"
        b"    return helper()\n"
        b"\n"
        b"helper()\n"
        b"\n"
        b"class Box:\n"
        b"    def run(self) -> helper:\n"
        b"        return helper()\n"
    )
    symbols, references = python_parser.parse(1, source, module_qn="pkg.mod")
    by_qn = index_symbols(symbols)
    calls = {
        r["source_line"]: r["source_symbol_id"]
        for r in references
        if r["ref_kind"] == "call" and r["ref_symbol_name"] == "helper"
    }
    assert calls[6] == by_qn["pkg.mod.outer.inner"]["id"]
    assert calls[7] == by_qn["pkg.mod.outer"]["id"]
    assert calls[9] is None
    assert calls[13] == by_qn["pkg.mod.Box.run"]["id"]

    annotation = next(
        r
        for r in references
        if r["ref_kind"] == "type_annotation" and r["ref_symbol_name"] == "helper"
    )
    assert annotation["source_symbol_id"] == by_qn["pkg.mod.Box.run"]["id"]
