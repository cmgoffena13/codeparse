from typing import NamedTuple


class StackFrame(NamedTuple):
    symbol_id: int
    qualified_name: str
    kind: str
    is_test: bool
    name: str
