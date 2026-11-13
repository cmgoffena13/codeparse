from src.codeparse_mcp.format_utils import tree_glyphs
from src.db import CodeDB

_MAX_NODES = 100

_EDGES_SQL = """
SELECT
    s.qualified_name AS child_qn,
    sb.base_qualified_name AS base_qn,
    f.is_test AS child_is_test
FROM symbol_bases AS sb
INNER JOIN symbols AS s
    ON s.id = sb.symbol_id
INNER JOIN files AS f
    ON f.id = s.file_id
"""


def _load_graph(
    db: CodeDB,
) -> tuple[dict[str, list[str]], dict[str, list[str]], set[str]]:
    parents: dict[str, list[str]] = {}
    children: dict[str, list[str]] = {}
    test_nodes: set[str] = set()
    for row in db.connection.execute(_EDGES_SQL):
        child_qn = str(row["child_qn"])
        base_qn = str(row["base_qn"])
        if row["child_is_test"]:
            test_nodes.add(child_qn)
        bases = parents.setdefault(child_qn, [])
        if base_qn not in bases:
            bases.append(base_qn)
        kids = children.setdefault(base_qn, [])
        if child_qn not in kids:
            kids.append(child_qn)
    for bases in parents.values():
        bases.sort()
    for kids in children.values():
        kids.sort()
    return parents, children, test_nodes


def _ancestor_chain(parents: dict[str, list[str]], qualified_name: str) -> list[str]:
    chain = [qualified_name]
    seen = {qualified_name}
    current = qualified_name
    while True:
        bases = parents.get(current)
        if not bases:
            break
        base = bases[0]
        if base in seen:
            break
        chain.append(base)
        seen.add(base)
        current = base
    chain.reverse()
    return chain


def _descendant_lines(
    children: dict[str, list[str]],
    parent: str,
    branch_prefix: str,
    *,
    test_nodes: set[str],
    include_tests: bool,
    budget: list[int],
) -> list[str]:
    lines: list[str] = []
    siblings = [
        child for child in children.get(parent, ()) if include_tests or child not in test_nodes
    ]
    last_index = len(siblings) - 1
    for index, child in enumerate(siblings):
        if budget[0] <= 0:
            lines.append(f"{branch_prefix}...[truncated]")
            budget[0] = -1
            break
        budget[0] -= 1
        is_last_child = index == last_index
        connector, continuation = tree_glyphs(is_last_child, wide=True)
        lines.append(f"{branch_prefix}{connector}{child}")
        next_prefix = branch_prefix + continuation
        lines.extend(
            _descendant_lines(
                children,
                child,
                next_prefix,
                test_nodes=test_nodes,
                include_tests=include_tests,
                budget=budget,
            )
        )
    return lines


def get_class_tree(db: CodeDB, qualified_name: str, *, include_tests: bool) -> str:
    key = qualified_name.strip()
    if not key:
        return "No symbol name given; pass a non-empty qualified_name."

    parents, children, test_nodes = _load_graph(db)
    chain = _ancestor_chain(parents, key)
    lines = [chain[0]]
    prefix = ""
    for name in chain[1:]:
        connector, continuation = tree_glyphs(True, wide=True)
        lines.append(f"{prefix}{connector}{name}")
        prefix = prefix + continuation

    budget = [_MAX_NODES]
    lines.extend(
        _descendant_lines(
            children,
            key,
            prefix,
            test_nodes=test_nodes,
            include_tests=include_tests,
            budget=budget,
        )
    )
    return "\n".join(lines) + "\n"
