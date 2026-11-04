from typing import NamedTuple

from tree_sitter import Node


class StackFrame(NamedTuple):
    symbol_id: int
    qualified_name: str
    kind: str
    is_test: bool
    name: str


def node_text(node: Node | None) -> str | None:
    result = None
    if node is not None and node.text is not None:
        result = node.text.decode("utf-8")
    return result
