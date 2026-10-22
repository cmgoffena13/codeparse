from src.tests.python_parser._assertions import index_symbols


def test_same_module_subclass_gets_base_members(python_parser) -> None:
    source = (
        b"class GenericContext:\n"
        b"    flag = True\n"
        b"\n"
        b"    def plan(self):\n"
        b"        return 1\n"
        b"\n"
        b"    @property\n"
        b"    def size(self):\n"
        b"        return 0\n"
        b"\n"
        b"class Context(GenericContext):\n"
        b"    def apply(self):\n"
        b"        return self.plan()\n"
    )
    symbols, _, refs = python_parser.parse(1, source, module_qn="mod")
    by_qn = index_symbols(symbols)
    assert by_qn["mod.Context.plan"]["kind"] == "method"
    assert by_qn["mod.Context.flag"]["kind"] == "variable"
    assert by_qn["mod.Context.size"]["kind"] == "property"
    assert by_qn["mod.Context.plan"]["file_id"] == by_qn["mod.GenericContext.plan"]["file_id"]
    assert by_qn["mod.Context.plan"]["line_start"] == by_qn["mod.GenericContext.plan"]["line_start"]
    assert by_qn["mod.Context.plan"]["parent_id"] == by_qn["mod.Context"]["id"]
    assert by_qn["mod.Context.plan"]["is_inherited"] is True
    assert by_qn["mod.Context.flag"]["is_inherited"] is True
    assert by_qn["mod.Context.size"]["is_inherited"] is True
    assert by_qn["mod.Context.apply"]["is_inherited"] is False
    assert by_qn["mod.GenericContext.plan"]["is_inherited"] is False
    assert any(ref["ref_symbol_qualified_name"] == "mod.Context.plan" for ref in refs)


def test_same_module_override_is_not_replaced(python_parser) -> None:
    source = (
        b"class GenericContext:\n"
        b"    def plan(self):\n"
        b"        return 1\n"
        b"\n"
        b"class Context(GenericContext):\n"
        b"    def plan(self):\n"
        b"        return 2\n"
    )
    symbols, _, _ = python_parser.parse(1, source, module_qn="mod")
    plans = [symbol for symbol in symbols if symbol["qualified_name"] == "mod.Context.plan"]
    assert len(plans) == 1
    assert plans[0]["line_start"] != index_symbols(symbols)["mod.GenericContext.plan"]["line_start"]
    assert plans[0]["is_inherited"] is False


def test_same_module_later_base_still_links(python_parser) -> None:
    source = (
        b"class Context(GenericContext):\n"
        b"    def apply(self):\n"
        b"        return self.plan()\n"
        b"\n"
        b"class GenericContext:\n"
        b"    def plan(self):\n"
        b"        return 1\n"
    )
    symbols, _, _ = python_parser.parse(1, source, module_qn="mod")
    assert "mod.Context.plan" in index_symbols(symbols)
