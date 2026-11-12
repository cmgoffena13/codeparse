import ast
import builtins
import typing

from tree_sitter import Node, Parser

from src.assigner import GlobalIDAssigner
from src.db import CodeDB, _ref_qn_is_indexed
from src.parsers.base import ParserBase
from src.parsers.class_catalog import ClassCatalog
from src.parsers.parser_utils import StackFrame, node_text

_IMPORT_ANCESTORS = frozenset({"import_statement", "import_from_statement"})
_TYPE_FIELD_ANCESTORS = frozenset(
    {
        "function_definition",
        "async_function_definition",
        "typed_parameter",
        "typed_default_parameter",
        "assignment",
        "annotated_assignment",
    }
)
_ALWAYS_SKIP_PARENTS = frozenset(
    {
        "parameters",
        "list_splat_pattern",
        "dictionary_splat_pattern",
        "global_statement",
        "nonlocal_statement",
    }
)
_SKIP_IDENTIFIER_FIELDS: dict[str, frozenset[str]] = {
    "assignment": frozenset({"left"}),
    "annotated_assignment": frozenset({"left"}),
    "augmented_assignment": frozenset({"left"}),
    "for_statement": frozenset({"left"}),
    "for_in_clause": frozenset({"left"}),
    "function_definition": frozenset({"name"}),
    "async_function_definition": frozenset({"name"}),
    "class_definition": frozenset({"name"}),
    "typed_parameter": frozenset({"name"}),
    "typed_default_parameter": frozenset({"name"}),
    "default_parameter": frozenset({"name"}),
    "named_expression": frozenset({"name"}),
    "keyword_argument": frozenset({"name"}),
    "attribute": frozenset({"attribute"}),
    "call": frozenset({"function"}),
    "as_pattern": frozenset({"alias"}),
}


class PythonParser(ParserBase):
    def __init__(
        self,
        assigner: GlobalIDAssigner,
        db: CodeDB,
        parser: Parser,
    ):
        self.parser = parser
        self.assigner = assigner
        self.db = db
        self.builtin_names: set[str] = set(dir(builtins))
        self.builtin_names.update(
            name for name in getattr(typing, "__all__", []) if isinstance(name, str)
        )
        self.stack: list[StackFrame] = []
        self.symbols: list[dict] = []
        self.symbol_references: list[dict] = []
        self.external_symbols: list[dict] = []
        self.symbols_snapshot = {}
        self.symbols_references_snapshot = {}
        self.external_symbols_snapshot = {}
        self._class_param_annos: dict[str, dict[str, str]] = {}
        self._func_param_annos: dict[str, dict[str, str]] = {}
        self._import_qn: dict[str, str] = {}
        self._local_defs: dict[str, str] = {}
        self._return_types: dict[str, str] = {}
        self._name_types: dict[str, str] = {}
        self._field_types: dict[str, str] = {}
        self._method_returns: dict[str, str] = {}
        self._var_qns: dict[str, str] = {}
        self._module_qn: str = ""
        self._is_package: bool = False
        self._file_id = 0
        self._skip_access_depth = 0
        self.class_catalog = ClassCatalog()

    def parse(
        self,
        file_id: int,
        file_bytes: bytes,
        module_qn: str = "",
        is_package: bool = False,
    ) -> tuple[list[dict], list[dict]]:
        self.stack = []
        self._module_qn = module_qn
        self._is_package = is_package
        self._file_id = file_id
        self._skip_access_depth = 0
        self._class_param_annos = {}
        self._func_param_annos = {}
        self._import_qn = {}
        self._local_defs = {}
        self._return_types = {}
        self._name_types = {}
        self._field_types = {}
        self._method_returns = {}
        self._var_qns = {}
        self.symbols = []
        self.symbol_references = []
        self.external_symbols = []
        tree = self.parser.parse(file_bytes)
        root_node = tree.root_node
        self.symbols_snapshot = self.db.get_symbols_snapshot(file_id)
        self.symbols_references_snapshot = self.db.get_symbol_references_snapshot(file_id)
        self.external_symbols_snapshot = self.db.get_external_symbols_snapshot(file_id)
        self._walk(root_node, file_id, file_bytes)
        self._rewrite_forward_local_refs()
        self.class_catalog.link(self.symbols, self.symbols_snapshot, file_id, self.assigner)
        self.class_catalog.absorb_member_types(self._field_types, self._method_returns)
        self._sync_external_symbols_ledger(file_id)

        self.db.delete_symbol_references(self.symbols_references_snapshot)
        self.db.delete_symbols(self.symbols_snapshot)
        return self.symbols, self.symbol_references

    def _sync_external_symbols_ledger(self, file_id: int) -> None:
        indexed = self.db._indexed_module_paths()
        seen_qns: set[str] = set()
        for ref in self.symbol_references:
            qualified_name = ref["ref_symbol_qualified_name"]
            if qualified_name in seen_qns:
                continue
            seen_qns.add(qualified_name)
            if _ref_qn_is_indexed(qualified_name, indexed):
                continue
            if qualified_name in self.external_symbols_snapshot:
                self.external_symbols_snapshot[qualified_name]["seen"] = True
            else:
                self.external_symbols.append({"file_id": file_id, "qualified_name": qualified_name})
        self.db.delete_unseen_external_symbols(file_id, self.external_symbols_snapshot)

    def _qualify(self, name: str) -> str:
        if self.stack:
            return f"{self.stack[-1].qualified_name}.{name}"
        if self._module_qn:
            return f"{self._module_qn}.{name}"
        return name

    def _current_package_parts(self) -> list[str]:
        parts = self._module_qn.split(".") if self._module_qn else []
        if self._is_package or not parts:
            return parts
        return parts[:-1]

    def _resolve_relative_import_path(self, relative: str) -> str | None:
        if not relative.startswith(".") or not self._module_qn:
            return None
        dots = 0
        while dots < len(relative) and relative[dots] == ".":
            dots += 1
        suffix = relative[dots:]
        pkg_parts = self._current_package_parts()
        levels_up = dots - 1
        if levels_up > len(pkg_parts):
            return None
        base = pkg_parts[: len(pkg_parts) - levels_up] if levels_up else list(pkg_parts)
        result = base + suffix.split(".") if suffix else base
        return ".".join(result) if result else None

    def _resolve_ref_qn(self, target_name: str) -> str:
        root, sep, rest = target_name.partition(".")
        bound = self._import_qn.get(root) or self._local_defs.get(root)
        if bound is not None:
            resolved = f"{bound}.{rest}" if rest else bound
        elif not sep and target_name and self._module_qn:
            resolved = f"{self._module_qn}.{target_name}"
        else:
            resolved = target_name
        return resolved

    def _rewrite_forward_local_refs(self) -> None:
        for ref in self.symbol_references:
            qn = ref["ref_symbol_qualified_name"]
            root, sep, rest = qn.partition(".")
            bound = self._local_defs.get(root)
            if not sep or bound is None or qn.startswith(f"{bound}."):
                continue
            ref["ref_symbol_qualified_name"] = f"{bound}.{rest}"

    def _is_unresolved_attribute_ref(self, target_name: str, qualified: str) -> bool:
        surface_root, sep, _ = target_name.partition(".")
        unresolved = bool(sep) and qualified.partition(".")[0] == surface_root
        if unresolved:
            known = surface_root in self._import_qn or surface_root in self._local_defs
            class_like = surface_root[:1].isupper() and any(c.islower() for c in surface_root)
            unresolved = not known and not class_like
        return unresolved

    def _resolve_annotation_qn(self, type_name: str) -> str:
        root = type_name.split(".", 1)[0]
        resolved = type_name
        if root not in self.builtin_names:
            resolved = self._resolve_ref_qn(type_name)
        return resolved

    def _lookup_field_type(self, owner_qn: str, member: str) -> str | None:
        key = f"{owner_qn}.{member}"
        found = self._field_types.get(key)
        if found is None:
            found = self.class_catalog.field_type(owner_qn, member)
        if found is not None:
            root = found.split(".", 1)[0]
            if root in self.builtin_names or found in self.builtin_names:
                found = None
        return found

    def _lookup_method_return(self, method_qn: str) -> str | None:
        found = self._method_returns.get(method_qn)
        if found is None:
            found = self.class_catalog.method_return(method_qn)
        if found is None:
            leaf = method_qn.rsplit(".", 1)[-1]
            bare = self._return_types.get(leaf)
            if bare is not None:
                found = self._resolve_annotation_qn(bare)
        return found

    def _walk_field_chain(self, type_qn: str, segments: list[str]) -> tuple[str, list[str]]:
        current = type_qn
        remaining = segments
        for index, seg in enumerate(segments):
            next_type = self._lookup_field_type(current, seg)
            if next_type is None:
                remaining = segments[index:]
                break
            current = next_type
            remaining = segments[index + 1 :]
        return current, remaining

    def _receiver_type_for_self_attr(self, class_qn: str, first_seg: str) -> str | None:
        type_qn = None
        constructor_map = self._class_param_annos.get(class_qn)
        if constructor_map and first_seg in constructor_map:
            type_qn = self._resolve_annotation_qn(constructor_map[first_seg])
        if type_qn is None:
            type_qn = self._lookup_field_type(class_qn, first_seg)
        return type_qn

    def _chain_from_type(self, type_qn: str, rest: str, *, as_call: bool) -> str:
        result = type_qn
        if rest:
            segments = rest.split(".")
            if as_call:
                current, remaining = self._walk_field_chain(type_qn, segments[:-1])
                leaf = segments[-1]
                if remaining:
                    result = f"{current}.{'.'.join([*remaining, leaf])}"
                else:
                    result = f"{current}.{leaf}"
            else:
                current, remaining = self._walk_field_chain(type_qn, segments)
                result = f"{current}.{'.'.join(remaining)}" if remaining else current
        return result

    def _resolve_chain(self, target_name: str, *, as_call: bool) -> str | None:
        resolved = None
        if target_name.startswith(("self.", "cls.")):
            suffix = target_name.split(".", 1)[1]
            first_seg, _, rest_after_first = suffix.partition(".")
            class_entry = next(
                (entry for entry in reversed(self.stack) if entry.kind == "class"), None
            )
            if class_entry is not None:
                type_qn = self._receiver_type_for_self_attr(class_entry.qualified_name, first_seg)
                if type_qn is not None:
                    resolved = self._chain_from_type(type_qn, rest_after_first, as_call=as_call)
        else:
            root, sep, rest = target_name.partition(".")
            type_name = None
            func_entry = next(
                (entry for entry in reversed(self.stack) if entry.kind in ("function", "method")),
                None,
            )
            if func_entry is not None:
                param_map = self._func_param_annos.get(func_entry.qualified_name)
                if param_map and root in param_map:
                    type_name = param_map[root]
            if type_name is None:
                type_name = self._name_types.get(root)
            if type_name is not None:
                type_qn = self._resolve_annotation_qn(type_name)
                resolved = self._chain_from_type(type_qn, rest, as_call=as_call) if sep else type_qn
        return resolved

    def _call_return_type_of(self, func_text: str) -> str | None:
        return_type = self._return_types.get(func_text)
        if return_type is not None:
            return_type = self._resolve_annotation_qn(return_type)
        else:
            callee = self._resolve_chain(func_text, as_call=True)
            if callee is not None:
                return_type = self._lookup_method_return(callee)
        return return_type

    def _base_source_name(self, node: Node) -> str | None:
        """Leftmost name of a base, peeling ``Generic[T]`` down to ``Generic``."""
        current = node
        while current.type == "subscript":
            value = current.child_by_field_name("value")
            if value is None:
                named = current.named_children
                value = named[0] if named else None
            if value is None:
                return None
            current = value
        if current.type not in ("identifier", "dotted_name", "attribute"):
            return None
        return node_text(current)

    def _class_bases(self, node: Node) -> list[str]:
        resolved: list[str] = []
        seen: set[str] = set()
        for child in node.children:
            if child.type == "argument_list":
                for base in child.named_children:
                    text = self._base_source_name(base)
                    if not text:
                        continue
                    qualified_name = self._resolve_ref_qn(text)
                    if qualified_name and qualified_name not in seen:
                        seen.add(qualified_name)
                        resolved.append(qualified_name)
        return sorted(resolved)

    @staticmethod
    def _normalize_signature_bytes(
        file_bytes: bytes, start_byte: int, end_byte: int, *, tail_rstrip: bool
    ) -> str:
        raw = file_bytes[start_byte:end_byte].decode("utf-8", errors="replace")
        text = raw.rstrip() if tail_rstrip else raw.strip()
        return " ".join(text.split())

    def _kind_for_definition(self, node: Node) -> str:
        if node.type == "class_definition":
            return "class"
        if node.type in ("function_definition", "async_function_definition"):
            return "method" if (self.stack and self.stack[-1].kind == "class") else "function"
        return "variable"

    def _snapshot_branch_is_test(self, kind: str, name: str) -> bool:
        base = self.stack[-1].is_test if self.stack else False
        if kind == "function" and name.startswith("test_"):
            return True
        if kind == "class" and name.startswith("Test"):
            return True
        if kind == "method" and name.startswith("test_") and base:
            return True
        return base

    def _variable_symbol_dict(
        self,
        symbol_id: int,
        file_id: int,
        parent_id: int | None,
        name: str,
        qualified_name: str,
        start_line: int,
        end_line: int,
        signature: str,
        is_test: bool,
    ) -> dict:
        return {
            "id": symbol_id,
            "file_id": file_id,
            "parent_id": parent_id,
            "parent": self.stack[-1].name if self.stack else None,
            "name": name,
            "qualified_name": qualified_name,
            "kind": "variable",
            "start_line": start_line,
            "end_line": end_line,
            "line_count": end_line - start_line + 1,
            "signature": signature,
            "docstring": None,
            "modifiers": None,
            "language": "python",
            "base_qualified_names": [],
            "is_test": is_test,
            "is_inherited": False,
        }

    def _record_symbol_reference(
        self,
        file_id: int,
        target_name: str,
        ref_symbol_qualified_name: str,
        source_line: int,
        source_column: int,
        ref_kind: str,
        context: str | None,
        key: tuple[str, str, int, int],
    ) -> None:
        source_symbol_id = self.stack[-1].symbol_id if self.stack else None
        source_symbol_qualified_name = self.stack[-1].qualified_name if self.stack else None
        row = {
            "ref_symbol_name": target_name,
            "ref_symbol_qualified_name": ref_symbol_qualified_name,
            "source_file_id": file_id,
            "source_symbol_id": source_symbol_id,
            "source_symbol_qualified_name": source_symbol_qualified_name,
            "source_line": source_line,
            "source_column": source_column,
            "ref_kind": ref_kind,
            "context": context,
        }
        if key in self.symbols_references_snapshot:
            stored_ref = self.symbols_references_snapshot[key]
            if (
                stored_ref["context"] == context
                and stored_ref["source_symbol_id"] == source_symbol_id
            ):
                stored_ref["seen"] = True
            else:
                stored_ref["context"] = context
                stored_ref["source_symbol_id"] = source_symbol_id
                new_row = {"id": stored_ref["id"], **row}
                replaced = False
                for index, existing in enumerate(self.symbol_references):
                    if existing["id"] == stored_ref["id"]:
                        self.symbol_references[index] = new_row
                        replaced = True
                        break
                if replaced:
                    stored_ref["seen"] = True
                else:
                    stored_ref["seen"] = False
                    self.symbol_references.append(new_row)
        else:
            symbol_reference_id = self.assigner.reserve("symbol_references", 1)[0]
            self.symbols_references_snapshot[key] = {
                "id": symbol_reference_id,
                "source_line": source_line,
                "source_column": source_column,
                "source_symbol_id": source_symbol_id,
                "context": context,
                "seen": True,
            }
            self.symbol_references.append({"id": symbol_reference_id, **row})

    def _register_import_ref_binding(
        self,
        import_path: str,
        imported_symbol: str,
        alias: str | None,
        import_type: str,
    ) -> None:
        """Map locals for ref_symbol_qualified_name rewriting."""
        abs_path: str | None
        if import_type == "relative":
            abs_path = self._resolve_relative_import_path(import_path)
        else:
            abs_path = import_path or None

        if abs_path:
            if imported_symbol:
                local = alias if alias else imported_symbol
                self._import_qn[local] = f"{abs_path}.{imported_symbol}"
            elif alias:
                self._import_qn[alias] = abs_path
            elif import_type != "relative":
                top = abs_path.split(".", 1)[0]
                self._import_qn[top] = top

    @staticmethod
    def _children_import_first(node: Node) -> list[Node]:
        """Statement suites: visit imports before siblings so ref filters see bindings."""
        imports = ("import_statement", "import_from_statement")
        first: list[Node] = []
        rest: list[Node] = []
        for ch in node.children:
            if ch.type in imports:
                first.append(ch)
            else:
                rest.append(ch)
        return first + rest

    @staticmethod
    def _is_simple_ref_path(node: Node) -> bool:
        current = node
        simple = True
        while current.type == "attribute":
            attribute = current.child_by_field_name("attribute")
            obj = current.child_by_field_name("object")
            if attribute is None or attribute.type != "identifier" or obj is None:
                simple = False
                break
            current = obj
        return simple and current.type in {"identifier", "dotted_name"}

    def _call_type_hint_from_args(self, call_node: Node) -> str | None:
        args = call_node.child_by_field_name("arguments")
        hint = None
        if args is not None:
            for child in args.named_children:
                if child.type == "keyword_argument":
                    continue
                if self._is_simple_ref_path(child):
                    text = node_text(child)
                    if text and text[:1].isupper():
                        hint = text
                        break
        return hint

    def _assignment_rhs_type_name(self, right: Node | None) -> str | None:
        type_name = None
        if right is not None:
            if right.type == "parenthesized_expression" and right.named_child_count == 1:
                type_name = self._assignment_rhs_type_name(right.named_children[0])
            elif right.type == "dictionary":
                type_name = "dict"
            elif right.type == "list":
                type_name = "list"
            elif right.type == "set":
                type_name = "set"
            elif right.type == "tuple":
                type_name = "tuple"
            elif right.type == "boolean_operator":
                literal_type = None
                other_type = None
                for child in right.named_children:
                    if child.type in {"dictionary", "list", "set", "tuple"}:
                        literal_type = self._assignment_rhs_type_name(child)
                    elif other_type is None:
                        other_type = self._assignment_rhs_type_name(child)
                type_name = literal_type or other_type
            elif self._is_simple_ref_path(right):
                text = node_text(right)
                if text is not None:
                    type_name = self._resolve_chain(text, as_call=False)
                    if type_name is None:
                        type_name = text
            elif right.type == "call":
                func = right.child_by_field_name("function")
                if func is not None and self._is_simple_ref_path(func):
                    ctor = node_text(func)
                    if ctor is not None:
                        type_name = self._call_return_type_of(ctor)
                        if type_name is None:
                            type_name = self._call_type_hint_from_args(right)
                        if type_name is None and "." not in ctor and ctor[:1].isupper():
                            type_name = ctor
        return type_name

    @staticmethod
    def _reference_root_identifier(target_name: str) -> str:
        """First identifier token (handles Path('.').resolve vs os.path.join)."""
        index = 0
        for ch in target_name:
            if ch.isalnum() or ch == "_":
                index += 1
            else:
                break
        if index > 0:
            return target_name[:index]
        return target_name.split(".", 1)[0]

    def _walk(self, node: Node, file_id: int, file_bytes: bytes) -> None:
        """Recursive DFS traversal."""
        if node.type == "decorated_definition":
            self._walk_decorated_definition(node, file_id, file_bytes)
            return

        self._process_node(node, file_id)

        pushed_stack = False
        if node.type in (
            "class_definition",
            "function_definition",
            "async_function_definition",
        ):
            pushed_stack = self._push_definition(node, file_id, file_bytes)
        elif node.type in (
            "assignment",
            "annotated_assignment",
            "augmented_assignment",
        ):
            for symbol_data in self._extract_variable_symbols(node, file_id, file_bytes):
                self.symbols.append(symbol_data)

        children = (
            self._children_import_first(node) if node.type in ("module", "block") else node.children
        )
        node_type = node.type
        skip_all = node_type in _IMPORT_ANCESTORS
        type_field = None
        return_type_field = None
        bases_field = None
        if node_type in _TYPE_FIELD_ANCESTORS:
            type_field = node.child_by_field_name("type")
            return_type_field = node.child_by_field_name("return_type")
        if node_type == "class_definition":
            bases_field = node.child_by_field_name("superclasses")
        for child in children:
            skip_child = skip_all or child in (type_field, return_type_field, bases_field)
            if skip_child:
                self._skip_access_depth += 1
            self._walk(child, file_id, file_bytes)
            if skip_child:
                self._skip_access_depth -= 1

        if pushed_stack:
            self._pop_definition()

    def _walk_decorated_definition(self, node: Node, file_id: int, file_bytes: bytes) -> None:
        definition = next(
            (
                child
                for child in node.named_children
                if child.type
                in (
                    "class_definition",
                    "function_definition",
                    "async_function_definition",
                )
            ),
            None,
        )
        if definition is None:
            for child in node.children:
                self._walk(child, file_id, file_bytes)
            return

        pushed_stack = self._push_definition(definition, file_id, file_bytes)
        for child in node.named_children:
            if child.type == "decorator":
                self._extract_decorator_references(child, file_id, file_bytes)

        node_type = definition.type
        type_field = None
        return_type_field = None
        bases_field = None
        if node_type in _TYPE_FIELD_ANCESTORS:
            type_field = definition.child_by_field_name("type")
            return_type_field = definition.child_by_field_name("return_type")
        if node_type == "class_definition":
            bases_field = definition.child_by_field_name("superclasses")
        for child in definition.children:
            skip_child = child in (type_field, return_type_field, bases_field)
            if skip_child:
                self._skip_access_depth += 1
            self._walk(child, file_id, file_bytes)
            if skip_child:
                self._skip_access_depth -= 1

        if pushed_stack:
            self._pop_definition()

    def _push_definition(self, node: Node, file_id: int, file_bytes: bytes) -> bool:
        symbol_id = None
        scope_path = None
        pushed_stack = False
        kind: str | None = None
        is_test: bool = False
        symbol_data = self._extract_symbol(node, file_id, file_bytes)
        name: str | None = None
        if symbol_data:
            symbol_id = symbol_data["id"]
            scope_path = symbol_data["qualified_name"] or symbol_data["name"]
            self.symbols.append(symbol_data)
            kind = symbol_data["kind"]
            is_test = symbol_data.get("is_test", False)
            name = symbol_data["name"]
        else:
            name_node = node.child_by_field_name("name")
            name = node_text(name_node)
            if name is not None:
                kind = self._kind_for_definition(node)
                scope_path = self._qualify(name)
                symbol_identity = scope_path
                key = (symbol_identity, kind)
                if key in self.symbols_snapshot:
                    symbol_id = self.symbols_snapshot[key]["id"]
                    is_test = self._snapshot_branch_is_test(kind, name)
        if symbol_id is not None and scope_path is not None and kind is not None:
            if kind in ("function", "method") and node.type in (
                "function_definition",
                "async_function_definition",
            ):
                annos = self._param_types_from_function(node)
                if annos:
                    self._func_param_annos[scope_path] = annos
                if (
                    name == "__init__"
                    and kind == "method"
                    and self.stack
                    and self.stack[-1].kind == "class"
                    and annos
                ):
                    self._class_param_annos[self.stack[-1].qualified_name] = annos
            if kind == "class" and name:
                self._local_defs[name] = scope_path
            self.stack.append(StackFrame(symbol_id, scope_path, kind, is_test, name or ""))
            pushed_stack = True
        if node.type in ("function_definition", "async_function_definition"):
            return_type = node.child_by_field_name("return_type")
            if return_type is not None:
                self._extract_reference(return_type, "type_annotation", file_id)
                if name:
                    anno = self._annotation_type_name(return_type)
                    if anno:
                        self._return_types[name] = anno
                        if scope_path is not None:
                            self._method_returns[scope_path] = self._resolve_annotation_qn(anno)
        return pushed_stack

    def _pop_definition(self) -> None:
        popped = self.stack[-1]
        if popped.kind == "class":
            self._class_param_annos.pop(popped.qualified_name, None)
        elif popped.kind in ("function", "method"):
            self._func_param_annos.pop(popped.qualified_name, None)
        self.stack.pop()

    def _extract_decorator_references(self, node: Node, file_id: int, file_bytes: bytes) -> None:
        expr = next(iter(node.named_children), None)
        if expr is None:
            return
        if expr.type == "call":
            self._extract_reference(expr, "call", file_id)
            arguments = expr.child_by_field_name("arguments")
            if arguments is not None:
                self._walk(arguments, file_id, file_bytes)
            return
        if not self._is_simple_ref_path(expr):
            return
        target_name = node_text(expr)
        if not target_name:
            return
        root_id = self._reference_root_identifier(target_name)
        if root_id in self.builtin_names:
            return
        resolved_qualified = self._resolve_chain(target_name, as_call=True)
        ref_symbol_qualified_name = (
            resolved_qualified
            if resolved_qualified is not None
            else self._resolve_ref_qn(target_name)
        )
        if self._is_unresolved_attribute_ref(target_name, ref_symbol_qualified_name):
            return
        qn_root = ref_symbol_qualified_name.split(".", 1)[0] if ref_symbol_qualified_name else ""
        if qn_root in self.builtin_names:
            return
        self._record_symbol_reference(
            file_id,
            target_name,
            ref_symbol_qualified_name,
            expr.start_point.row + 1,
            expr.start_point.column,
            "call",
            node_text(expr),
            (ref_symbol_qualified_name, "call", expr.start_point.row + 1, expr.start_point.column),
        )

    @staticmethod
    def _is_optional_type_value(node: Node) -> bool:
        text = node_text(node)
        return text in ("Optional", "typing.Optional", "t.Optional")

    def _annotation_type_name(self, type_node: Node | None) -> str | None:
        """Bare identifier/attribute, or inner type of Optional[...] /
        typing.Optional / t.Optional."""
        if type_node is None:
            return None
        node = type_node
        # ``type`` field wraps the expression; unwrap one level when needed.
        if node.type == "type" and node.named_child_count == 1:
            node = node.named_children[0]
        if node.type in ("identifier", "attribute", "dotted_name"):
            return node_text(node)
        if node.type == "binary_operator":
            chosen = None
            for child in node.named_children:
                name = self._annotation_type_name(child)
                if name and name != "None":
                    chosen = name
                    break
            return chosen
        if node.type == "subscript":
            value = node.child_by_field_name("value")
            if value is None:
                return None
            if not self._is_optional_type_value(value):
                return self._annotation_type_name(value)
            for child in node.named_children:
                if child == value:
                    continue
                if child.type in ("identifier", "attribute", "dotted_name"):
                    return node_text(child)
                if child.type == "type":
                    return self._annotation_type_name(child)
            return None
        if node.type == "generic_type":
            # Optional[X] (PEP 585-style tree): identifier + type_parameter
            if node.named_child_count < 2:
                return None
            head = node.named_children[0]
            if not self._is_optional_type_value(head):
                return self._annotation_type_name(head)
            type_param = node.named_children[1]
            if type_param.type != "type_parameter":
                return None
            for child in type_param.named_children:
                if child.type == "type":
                    return self._annotation_type_name(child)
                if child.type in ("identifier", "attribute", "dotted_name"):
                    return node_text(child)
            return None
        return None

    def _param_types_from_function(self, node: Node) -> dict[str, str]:
        """Map typed parameter names to annotation type names (Optional peeled)."""
        out: dict[str, str] = {}
        params = node.child_by_field_name("parameters")
        if params is None:
            return out
        for ch in params.named_children:
            if ch.type != "typed_parameter":
                continue
            param_name: str | None = None
            ann: Node | None = None
            for c in ch.children:
                if c.type == "identifier" and param_name is None:
                    param_name = node_text(c)
                elif c.type == "type":
                    ann = c
            if not param_name or param_name in ("self", "cls"):
                continue
            simple = self._annotation_type_name(ann)
            if simple:
                out[param_name] = simple
        return out

    def _extract_variable_symbols(self, node: Node, file_id: int, file_bytes: bytes) -> list[dict]:
        symbols: list[dict] = []

        # Only capture module/class plus __init__ assignments.
        if (
            self.stack
            and self.stack[-1].kind != "class"
            and not self.stack[-1].qualified_name.endswith(".__init__")
        ):
            target = node.child_by_field_name("left") or node.child_by_field_name("target")
            if target is not None and target.type == "identifier":
                decoded = node_text(target)
                if decoded is not None:
                    if decoded in self._var_qns:
                        del self._var_qns[decoded]
                    anno = self._annotation_type_name(node.child_by_field_name("type"))
                    if anno:
                        self._name_types[decoded] = self._resolve_annotation_qn(anno)
                    else:
                        rhs_type = self._assignment_rhs_type_name(node.child_by_field_name("right"))
                        if rhs_type:
                            self._name_types[decoded] = (
                                rhs_type
                                if "." in rhs_type or rhs_type in self.builtin_names
                                else self._resolve_annotation_qn(rhs_type)
                            )
                        else:
                            self._name_types.pop(decoded, None)
            return symbols

        # target is usually in field 'left' for assignment/augmented_assignment
        target = node.child_by_field_name("left") or node.child_by_field_name("target")
        if target is None:
            return symbols

        # symbol_leaf is the stable suffix for qualified_name (e.g. "llm").
        # name is the source spelling for the DB (e.g. "self.llm"), matching references.
        symbol_leaf = ""
        name = ""
        if target.type == "identifier":
            decoded = node_text(target)
            if decoded is not None:
                symbol_leaf = name = decoded
        elif target.type == "attribute":
            text = node_text(target) or ""
            if text.startswith(("self.", "cls.")):
                symbol_leaf = text.split(".", 1)[1]
                name = text
        if not symbol_leaf:
            return symbols
        start_line = node.start_point.row + 1
        end_line = node.end_point.row + 1

        if self.stack:
            parent_qn = self.stack[-1].qualified_name
            if target.type == "attribute" and parent_qn.endswith(".__init__"):
                parent_qn = parent_qn.rsplit(".", 1)[0]
            scope_path = f"{parent_qn}.{symbol_leaf}"
            parent_id = self.stack[-1].symbol_id
        else:
            scope_path = self._qualify(name)
            parent_id = None

        if target.type == "identifier" and name:
            self._var_qns[name] = scope_path
            anno = self._annotation_type_name(node.child_by_field_name("type"))
            if anno:
                resolved_anno = self._resolve_annotation_qn(anno)
                self._name_types[name] = resolved_anno
                if self.stack and self.stack[-1].kind == "class":
                    self._field_types[scope_path] = resolved_anno
            else:
                rhs_type = self._assignment_rhs_type_name(node.child_by_field_name("right"))
                if rhs_type:
                    resolved_rhs = (
                        rhs_type
                        if "." in rhs_type or rhs_type in self.builtin_names
                        else self._resolve_annotation_qn(rhs_type)
                    )
                    self._name_types[name] = resolved_rhs
                    if self.stack and self.stack[-1].kind == "class":
                        self._field_types[scope_path] = resolved_rhs
                else:
                    self._name_types.pop(name, None)

        if (
            target.type == "attribute"
            and symbol_leaf
            and self.stack
            and self.stack[-1].qualified_name.endswith(".__init__")
        ):
            class_qn = self.stack[-1].qualified_name.rsplit(".", 1)[0]
            field_qn = f"{class_qn}.{symbol_leaf}"
            field_type = self._receiver_type_for_self_attr(class_qn, symbol_leaf)
            if field_type is None:
                rhs_type = self._assignment_rhs_type_name(node.child_by_field_name("right"))
                if rhs_type is not None:
                    field_type = (
                        rhs_type
                        if "." in rhs_type or rhs_type in self.builtin_names
                        else self._resolve_annotation_qn(rhs_type)
                    )
            if field_type is not None:
                self._field_types[field_qn] = field_type

        signature = self._normalize_signature_bytes(
            file_bytes, node.start_byte, node.end_byte, tail_rstrip=False
        )

        kind = "variable"
        is_test = self.stack[-1].is_test if self.stack else False
        symbol_identity = scope_path
        qualified_name = symbol_identity
        key = (symbol_identity, kind)
        if key in self.symbols_snapshot:
            self.symbols_snapshot[key]["seen"] = True
            if (start_line, end_line) != (
                self.symbols_snapshot[key]["start_line"],
                self.symbols_snapshot[key]["end_line"],
            ):
                symbol_id = self.symbols_snapshot[key]["id"]
                symbols.append(
                    self._variable_symbol_dict(
                        symbol_id,
                        file_id,
                        parent_id,
                        name,
                        qualified_name,
                        start_line,
                        end_line,
                        signature,
                        is_test,
                    )
                )
        else:
            symbol_id = self.assigner.reserve("symbols", 1)[0]
            self.symbols_snapshot[key] = {
                "id": symbol_id,
                "seen": True,
                "start_line": start_line,
                "end_line": end_line,
            }
            symbols.append(
                self._variable_symbol_dict(
                    symbol_id,
                    file_id,
                    parent_id,
                    name,
                    qualified_name,
                    start_line,
                    end_line,
                    signature,
                    is_test,
                )
            )

        return symbols

    def _process_node(self, node: Node, file_id: int) -> None:
        """Handle Imports and References."""

        if node.type in ("import_statement", "import_from_statement"):
            self._extract_import(node)
            return  # NOTE: Imports don't have children that are symbols

        if node.type == "call":
            self._extract_reference(node, "call", file_id)
        elif node.type == "attribute":
            self._extract_reference(node, "access", file_id)
        elif node.type == "identifier":
            if self._skip_access_depth == 0:
                self._extract_identifier_reference(node, file_id)
        else:
            type_node = node.child_by_field_name("type")
            if type_node is not None:
                self._extract_reference(type_node, "type_annotation", file_id)

    def _extract_symbol(self, node: Node, file_id: int, file_bytes: bytes) -> dict | None:
        """
        Extract Symbol Dictionary:
            - Qualified Name
            - Modifiers
            - Symbol Kind
            - Line Start
            - Line End
            - Signature
            - Is Test
            - Base Qualified Names
        """
        name_node = node.child_by_field_name("name")
        body_node = node.child_by_field_name("body")
        name = node_text(name_node)
        if name is None:
            return None
        qualified_name = self._qualify(name)
        kind = self._kind_for_definition(node)

        modifiers: list[str] = []
        if node.parent is not None and node.parent.type == "decorated_definition":
            for child in node.parent.children:
                if child.type != "decorator" or child.text is None:
                    continue
                decorator_text = child.text.decode("utf-8", errors="replace").strip()
                if decorator_text.startswith("@"):
                    decorator_text = decorator_text[1:].strip()
                if kind == "method" and decorator_text.split(".")[-1] == "property":
                    kind = "property"
                if decorator_text:
                    modifiers.append(decorator_text)

            start_line = node.parent.start_point.row + 1
        else:
            start_line = node.start_point.row + 1
        end_line = node.end_point.row + 1

        # NOTE: Extract Signature. Decorators stay in modifiers.
        end_byte = body_node.start_byte if body_node is not None else node.end_byte
        signature_start_byte = node.start_byte
        signature = self._normalize_signature_bytes(
            file_bytes, signature_start_byte, end_byte, tail_rstrip=True
        )

        # NOTE: Determine if its a test symbol.
        parent_is_test = self.stack[-1].is_test if self.stack else False
        is_test = False
        if (
            (kind == "function" and name.startswith("test_"))
            or (kind == "class" and name.startswith("Test"))
            or (kind == "method" and name.startswith("test_") and parent_is_test)
        ):
            is_test = True

        # NOTE: Extract Docstring. First statement is a string.
        docstring = None
        if body_node is not None and body_node.named_children:
            statement = body_node.named_children[0]
            if statement.type == "expression_statement" and statement.named_children:
                statement = statement.named_children[0]
            if statement.type == "string" and statement.text is not None:
                raw = statement.text.decode("utf-8", errors="replace")
                try:
                    docstring = ast.literal_eval(raw)
                except ValueError, SyntaxError:
                    docstring = raw.strip("\"'")

        # NOTE: Extract Qualified Base Class Names.
        resolved_bases: list[str] = []
        if kind == "class":
            resolved_bases = self._class_bases(node)

        key = (qualified_name, kind)
        symbol = self.symbols_snapshot.get(key)

        # NOTE: Symbol record exists in Snapshot, check if it needs to be updated.
        if symbol is not None:
            symbol["seen"] = True
            record_bases = sorted(symbol.get("base_qualified_names", []))

            # Compare Line Start, Line End, and Base Qualified Names.
            if (start_line, end_line) != (
                symbol["start_line"],
                symbol["end_line"],
            ) or resolved_bases != record_bases:
                symbol_id = symbol["id"]
            else:
                # NOTE: Symbol record is up to date, no need to insert/update.
                return None

        else:
            # NOTE: Symbol record does not exist in Snapshot, create a new symbol record.
            symbol_id = self.assigner.reserve("symbols", 1)[0]
            self.symbols_snapshot[key] = {
                "id": symbol_id,
                "seen": True,
                "start_line": start_line,
                "end_line": end_line,
                "base_qualified_names": resolved_bases,
            }

        return {
            "id": symbol_id,
            "file_id": file_id,
            "parent_id": self.stack[-1].symbol_id if self.stack else None,
            "parent": self.stack[-1].name if self.stack else None,
            "name": name,
            "qualified_name": qualified_name,
            "kind": kind,
            "start_line": start_line,
            "end_line": end_line,
            "line_count": end_line - start_line + 1,
            "signature": signature,
            "docstring": docstring,
            "modifiers": str(modifiers) if modifiers else None,
            "language": "python",
            "base_qualified_names": resolved_bases,
            "is_test": is_test,
            "is_inherited": False,
        }

    def _extract_import(self, node: Node) -> None:
        """Bind import locals for reference rewriting; does not persist import rows."""
        if node.type not in ("import_from_statement", "import_statement"):
            return

        from_import = node.type == "import_from_statement"
        import_type = "absolute"  # NOTE: Default to absolute import.
        module_name = ""
        relative_node = None

        # "from typing import X"
        # "from .sib import Foo"
        # "from . import Foo".
        if from_import:
            relative_node = next(
                (child for child in node.children if child.type == "relative_import"), None
            )
            if relative_node is not None:
                module_name = node_text(relative_node)
                if module_name is None:
                    return

                # "from .sib import Foo" -> import_type = "relative", module_name = ".sib"
                # "from . import Foo" -> import_type = "relative", module_name = "."
                import_type = "relative"

            if not module_name:
                dotted = next(
                    (
                        child
                        for child in node.children
                        if child.type == "dotted_name" and node_text(child) is not None
                    ),
                    None,
                )
                # "from Foo import Bar" -> module_name = "Foo"
                decoded = node_text(dotted)
                if decoded is not None:
                    module_name = decoded

        for child in node.children:
            name_node = child
            alias = None
            # "from Foo import Bar as Baz" -> name_node = "Bar", alias = "Baz"
            # "import os as operating_system" -> name_node = "os", alias = "operating_system"
            if child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                alias = node_text(alias_node)
            # "from Foo import *", commas, and parentheses are not names.
            elif child.type != "dotted_name":
                continue
            # "from Foo import Bar" -> name = "Bar"
            # "import os" -> name = "os"
            name = node_text(name_node)
            if name is None:
                continue
            if from_import and child.type == "dotted_name":
                # "from .sib import Foo": "sib" starts inside ".sib", so skip the module.
                if relative_node is not None and child.start_byte < relative_node.end_byte:
                    continue
                # "from typing import typing" equals the module, so skip both names.
                if relative_node is None and name == module_name:
                    continue
            # "from Foo import Bar" -> child_path = "Foo"
            # "import os" -> child_path = "os"
            child_path = module_name if from_import else name
            # "from Foo import Bar" -> imported_symbol = "Bar"
            # "import os" -> imported_symbol = ""
            imported_symbol = name if from_import else ""
            self._register_import_ref_binding(child_path, imported_symbol, alias, import_type)

    def _extract_identifier_reference(self, node: Node, file_id: int) -> None:
        if not self._identifier_is_skipped(node):
            name = node_text(node)
            if name:
                qualified = self._var_qns.get(name)
                if qualified is None:
                    qualified = self._import_qn.get(name)
                if qualified is not None:
                    source_line = node.start_point.row + 1
                    source_column = node.start_point.column
                    self._record_symbol_reference(
                        file_id,
                        name,
                        qualified,
                        source_line,
                        source_column,
                        "access",
                        name,
                        (qualified, "access", source_line, source_column),
                    )

    def _identifier_is_skipped(self, node: Node) -> bool:
        parent = node.parent
        return self._skip_access_depth > 0 or (
            parent is not None and self._parent_skips_identifier(parent, node)
        )

    def _parent_skips_identifier(self, parent: Node, node: Node) -> bool:
        parent_type = parent.type
        skipped = parent_type in _ALWAYS_SKIP_PARENTS
        if not skipped:
            skip_fields = _SKIP_IDENTIFIER_FIELDS.get(parent_type)
            if skip_fields is not None:
                skipped = self._child_field_name(parent, node) in skip_fields
        return skipped

    def _child_field_name(self, parent: Node, node: Node) -> str | None:
        field = None
        for index, child in enumerate(parent.children):
            if child == node:
                field = parent.field_name_for_child(index)
                break
        return field

    def _extract_reference(self, node: Node, ref_kind: str, file_id: int) -> None:
        """Extract Reference (Call, Access, Type Annotation)."""
        parent = node.parent
        # "obj.method()" -> skip this access. "obj.method" -> keep the access.
        if (
            ref_kind == "access"
            and parent is not None
            and parent.type == "call"
            and parent.child_by_field_name("function") == node
        ):
            return

        target_name = ""
        if ref_kind == "call":
            func_node = node.child_by_field_name("function")
            target_name = node_text(func_node)
            if func_node is None or target_name is None or not self._is_simple_ref_path(func_node):
                return

        elif ref_kind == "access":
            if not self._is_simple_ref_path(node):
                return
            attribute_node = node.child_by_field_name("attribute")
            object_node = node.child_by_field_name("object")
            leaf_name = node_text(attribute_node)
            if leaf_name is None:
                return
            object_text = node_text(object_node) or ""
            target_name = f"{object_text}.{leaf_name}" if object_text else leaf_name

        elif ref_kind == "type_annotation":
            current = node
            if current.type == "type" and current.named_child_count == 1:
                current = current.named_children[0]
            if current.type == "binary_operator" and any(c.type == "|" for c in current.children):
                for child in current.named_children:
                    self._extract_reference(child, "type_annotation", file_id)
                return
            target_name = self._annotation_type_name(node)
            if target_name is None:
                raw = node_text(node)
                if raw is None:
                    return
                target_name = raw.strip()
                for prefix in ("typing.Optional[", "Optional["):
                    if target_name.startswith(prefix) and target_name.endswith("]"):
                        target_name = target_name[len(prefix) : -1].strip()
                        break
                target_name = target_name.split("[", 1)[0].strip()
                if "|" in target_name:
                    return
        if not target_name:
            return

        root_id = self._reference_root_identifier(target_name)
        if root_id in self.builtin_names:
            return

        receiver_root = ""
        linked_variable = False
        as_call = ref_kind == "call"
        resolved_qualified = self._resolve_chain(target_name, as_call=as_call)
        if resolved_qualified is None and target_name.startswith(("self.", "cls.")):
            suffix = target_name.split(".", 1)[1]
            class_entry = next(
                (entry for entry in reversed(self.stack) if entry.kind == "class"), None
            )
            if class_entry is not None:
                resolved_qualified = f"{class_entry.qualified_name}.{suffix}"
            elif self.stack:
                resolved_qualified = f"{self.stack[-1].qualified_name}.{suffix}"
        elif resolved_qualified is None:
            root, sep, _rest = target_name.partition(".")
            receiver_root = root
            if sep:
                type_name = self._name_types.get(root)
                linked_variable = type_name is not None and root in self._var_qns
                if type_name is None:
                    func_entry = next(
                        (
                            entry
                            for entry in reversed(self.stack)
                            if entry.kind in ("function", "method")
                        ),
                        None,
                    )
                    if func_entry is not None:
                        param_map = self._func_param_annos.get(func_entry.qualified_name)
                        if param_map and root in param_map:
                            type_name = param_map[root]
                if type_name is not None:
                    linked_variable = root in self._var_qns
        else:
            root, sep, _rest = target_name.partition(".")
            receiver_root = root
            linked_variable = (
                sep
                and not target_name.startswith(("self.", "cls."))
                and root in self._var_qns
                and root in self._name_types
            )

        ref_symbol_qualified_name = (
            resolved_qualified
            if resolved_qualified is not None
            else self._resolve_ref_qn(target_name)
        )
        if ref_kind != "type_annotation" and self._is_unresolved_attribute_ref(
            target_name, ref_symbol_qualified_name
        ):
            return

        source_line = node.start_point.row + 1
        source_column = node.start_point.column
        context = node_text(node)
        rows = [(target_name, ref_symbol_qualified_name, ref_kind, context)]
        if ref_kind == "call" and linked_variable:
            rows.append((receiver_root, self._var_qns[receiver_root], "access", receiver_root))

        for name, qualified, kind, row_context in rows:
            qn_root = qualified.split(".", 1)[0] if qualified else ""
            if qn_root in self.builtin_names:
                continue
            self._record_symbol_reference(
                file_id,
                name,
                qualified,
                source_line,
                source_column,
                kind,
                row_context,
                (qualified, kind, source_line, source_column),
            )
