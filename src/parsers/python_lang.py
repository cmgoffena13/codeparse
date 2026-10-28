import ast
import builtins
import sys
import typing

from tree_sitter import Node, Parser

from src.assigner import GlobalIDAssigner
from src.db import CodeDB
from src.parsers.base import ParserBase
from src.parsers.parser_utils import StackFrame

_INHERIT_KINDS = frozenset({"method", "property", "variable"})


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
        self.std_module_names: set[str] = getattr(sys, "stdlib_module_names", set())
        self.stack: list[StackFrame] = []
        self.symbols: list[dict] = []
        self.imports: list[dict] = []
        self.symbol_references: list[dict] = []
        self.symbols_snapshot = {}
        self.symbols_references_snapshot = {}
        self.imports_snapshot = {}
        self._class_param_annos: dict[str, dict[str, str]] = {}
        self._func_param_annos: dict[str, dict[str, str]] = {}
        self._ref_root_module: dict[str, str] = {}
        self._import_qn: dict[str, str] = {}
        self._name_types: dict[str, str] = {}
        self._var_qns: dict[str, str] = {}
        self._module_qn: str = ""
        self._is_package: bool = False
        self._file_id = 0
        self.catalog: dict = {"by_qn": {}, "subclasses": {}}

    def parse(
        self,
        file_id: int,
        file_bytes: bytes,
        module_qn: str = "",
        is_package: bool = False,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        self.stack = []
        self._module_qn = module_qn
        self._is_package = is_package
        self._file_id = file_id
        self._class_param_annos = {}
        self._func_param_annos = {}
        self._ref_root_module = {}
        self._import_qn = {}
        self._name_types = {}
        self._var_qns = {}
        self.symbols = []
        self.imports = []
        self.symbol_references = []
        tree = self.parser.parse(file_bytes)
        root_node = tree.root_node
        self.symbols_snapshot = self.db.get_symbols_snapshot(file_id)
        self.symbols_references_snapshot = self.db.get_symbol_references_snapshot(file_id)
        self.imports_snapshot = self.db.get_imports_snapshot(file_id)
        self._walk(root_node, file_id, file_bytes)
        self._link_inherited_members()

        self.db.delete_symbol_references(self.symbols_references_snapshot)
        self.db.delete_symbols(self.symbols_snapshot)
        self.db.delete_imports(self.imports_snapshot)
        return self.symbols, self.imports, self.symbol_references

    def _catalog_register_class(self, cls: dict) -> None:
        qualified_name = cls["qualified_name"]
        for children in self.catalog["subclasses"].values():
            children.pop(qualified_name, None)
        for base_qn in cls["bases"]:
            bucket = self.catalog["subclasses"].setdefault(base_qn, {})
            bucket[qualified_name] = {
                "id": cls["id"],
                "name": cls["name"],
                "qualified_name": qualified_name,
            }

    def _catalog_put(self, symbol: dict, *, overwrite: bool = True) -> None:
        qualified_name = symbol["qualified_name"]
        skip = (not overwrite) and qualified_name in self.catalog["by_qn"]
        if not skip:
            self.catalog["by_qn"][qualified_name] = {
                "id": symbol["id"],
                "file_id": symbol["file_id"],
                "parent_id": symbol.get("parent_id"),
                "parent": symbol.get("parent"),
                "name": symbol["name"],
                "qualified_name": qualified_name,
                "kind": symbol["kind"],
                "line_start": symbol["line_start"],
                "line_end": symbol["line_end"],
                "line_count": symbol.get(
                    "line_count", symbol["line_end"] - symbol["line_start"] + 1
                ),
                "signature": symbol.get("signature") or "",
                "docstring": symbol.get("docstring"),
                "modifiers": symbol.get("modifiers"),
                "language": symbol.get("language") or "python",
                "is_test": symbol.get("is_test") or False,
                "is_inherited": bool(symbol.get("is_inherited")),
                "base_qualified_names": list(
                    symbol.get("base_qualified_names") or symbol.get("bases") or ()
                ),
            }
        if symbol["kind"] == "class":
            stored = self.catalog["by_qn"][qualified_name]
            self._catalog_register_class(
                {
                    "id": stored["id"],
                    "name": stored["name"],
                    "qualified_name": qualified_name,
                    "bases": list(stored.get("base_qualified_names") or symbol.get("bases") or ()),
                }
            )

    def _catalog_drop(self, qualified_name: str) -> None:
        self.catalog["by_qn"].pop(qualified_name, None)
        for children in self.catalog["subclasses"].values():
            children.pop(qualified_name, None)

    def _symbol_from_snapshot(self, qualified_name: str, kind: str, entry: dict) -> dict:
        leaf = qualified_name.rsplit(".", 1)[-1]
        parent_qn = qualified_name.rsplit(".", 1)[0] if "." in qualified_name else ""
        parent = self.catalog["by_qn"].get(parent_qn)
        parent_is_class = parent is not None and parent["kind"] == "class"
        return {
            "id": entry["id"],
            "file_id": self._file_id,
            "parent_id": parent["id"] if parent_is_class else None,
            "parent": parent["name"] if parent_is_class else None,
            "name": leaf,
            "qualified_name": qualified_name,
            "kind": kind,
            "line_start": entry["line_start"],
            "line_end": entry["line_end"],
            "line_count": entry["line_end"] - entry["line_start"] + 1,
            "signature": "",
            "docstring": None,
            "modifiers": None,
            "language": "python",
            "base_qualified_names": list(entry.get("base_qualified_names") or ()),
            "is_test": False,
        }

    def _ingest_snapshot_into_catalog(self) -> None:
        classes: list[tuple[str, str, dict]] = []
        others: list[tuple[str, str, dict]] = []
        for (qualified_name, kind), entry in self.symbols_snapshot.items():
            if kind == "class":
                classes.append((qualified_name, kind, entry))
            else:
                others.append((qualified_name, kind, entry))
        for qualified_name, kind, entry in classes + others:
            self._catalog_put(
                self._symbol_from_snapshot(qualified_name, kind, entry),
                overwrite=False,
            )

    def _classes_seen(self) -> list[dict]:
        by_id: dict[int, dict] = {}
        for (qualified_name, kind), entry in self.symbols_snapshot.items():
            if kind == "class" and entry["seen"]:
                by_id[entry["id"]] = {
                    "id": entry["id"],
                    "name": qualified_name.rsplit(".", 1)[-1],
                    "qualified_name": qualified_name,
                    "bases": list(entry.get("base_qualified_names") or ()),
                }
        for symbol in self.symbols:
            if symbol["kind"] == "class":
                by_id[symbol["id"]] = {
                    "id": symbol["id"],
                    "name": symbol["name"],
                    "qualified_name": symbol["qualified_name"],
                    "bases": list(symbol.get("base_qualified_names") or ()),
                }
        return list(by_id.values())

    def _member_from_symbol(self, symbol: dict) -> dict:
        return {
            "file_id": symbol["file_id"],
            "name": symbol["name"],
            "kind": symbol["kind"],
            "line_start": symbol["line_start"],
            "line_end": symbol["line_end"],
            "line_count": symbol.get("line_count", symbol["line_end"] - symbol["line_start"] + 1),
            "signature": symbol.get("signature") or "",
            "docstring": symbol.get("docstring"),
            "modifiers": symbol.get("modifiers"),
            "language": symbol.get("language") or "python",
            "is_test": symbol.get("is_test") or False,
        }

    def _members_of_class(self, class_qn: str) -> list[dict]:
        owner = next(
            (
                symbol
                for symbol in self.symbols
                if symbol["kind"] == "class" and symbol["qualified_name"] == class_qn
            ),
            self.catalog["by_qn"].get(class_qn),
        )
        by_name: dict[str, dict] = {}
        if owner is not None and owner.get("kind", "class") == "class":
            owner_id = owner["id"]
            prefix = f"{class_qn}."
            for symbol in self.catalog["by_qn"].values():
                if symbol.get("parent_id") == owner_id and symbol["kind"] in _INHERIT_KINDS:
                    by_name[symbol["name"]] = self._member_from_symbol(symbol)
            for (qualified_name, kind), entry in self.symbols_snapshot.items():
                leaf = qualified_name[len(prefix) :]
                if (
                    kind in _INHERIT_KINDS
                    and qualified_name.startswith(prefix)
                    and "." not in leaf
                    and not entry["seen"]
                ):
                    by_name.pop(leaf, None)
            for symbol in self.symbols:
                if symbol["parent_id"] == owner_id and symbol["kind"] in _INHERIT_KINDS:
                    by_name[symbol["name"]] = self._member_from_symbol(symbol)
        return list(by_name.values())

    def _owned_names(self, class_id: int) -> set[str]:
        names = {symbol["name"] for symbol in self.symbols if symbol["parent_id"] == class_id}
        names.update(
            symbol["name"]
            for symbol in self.catalog["by_qn"].values()
            if symbol.get("parent_id") == class_id and symbol["kind"] in _INHERIT_KINDS
        )
        return names

    def _keep_inherited_snapshot(self, qualified_name: str, kind: str) -> None:
        key = (qualified_name, kind)
        if key in self.symbols_snapshot:
            self.symbols_snapshot[key]["seen"] = True

    def _keep_foreign_inherited_copies(self) -> None:
        local_qns = {cls["qualified_name"] for cls in self._classes_seen()}
        local_leaves = {
            member["name"]
            for cls in self._classes_seen()
            for member in self._members_of_class(cls["qualified_name"])
        }
        for (qualified_name, kind), entry in self.symbols_snapshot.items():
            if kind not in _INHERIT_KINDS or "." not in qualified_name:
                continue
            parent_qn, leaf = qualified_name.rsplit(".", 1)
            if parent_qn not in local_qns and leaf in local_leaves:
                entry["seen"] = True

    def _unsee_inherited_without_parent(self) -> None:
        unseen_local_classes = {
            qualified_name
            for (qualified_name, kind), entry in self.symbols_snapshot.items()
            if kind == "class" and not entry["seen"]
        }
        for (qualified_name, kind), entry in self.symbols_snapshot.items():
            parent_qn = qualified_name.rsplit(".", 1)[0] if "." in qualified_name else ""
            skip = (
                (not entry["seen"])
                or kind not in _INHERIT_KINDS
                or parent_qn not in unseen_local_classes
            )
            if not skip:
                entry["seen"] = False
                self._catalog_drop(qualified_name)

    def _inherited_member_symbol(self, cls: dict, member: dict) -> dict:
        qualified_name = f"{cls['qualified_name']}.{member['name']}"
        key = (qualified_name, member["kind"])
        snapshot = self.symbols_snapshot.get(key)
        cataloged = self.catalog["by_qn"].get(qualified_name)
        symbol_id = (
            snapshot["id"]
            if snapshot is not None
            else cataloged["id"]
            if cataloged is not None
            else self.assigner.reserve("symbols", 1)[0]
        )
        self._keep_inherited_snapshot(qualified_name, member["kind"])
        return {
            "id": symbol_id,
            "file_id": member["file_id"],
            "parent_id": cls["id"],
            "parent": cls["name"],
            "name": member["name"],
            "qualified_name": qualified_name,
            "kind": member["kind"],
            "line_start": member["line_start"],
            "line_end": member["line_end"],
            "line_count": member["line_count"],
            "signature": member["signature"],
            "docstring": member["docstring"],
            "modifiers": member["modifiers"],
            "language": member["language"],
            "base_qualified_names": [],
            "is_test": member["is_test"],
            "is_inherited": True,
        }

    def _link_inherited_members(self) -> None:
        self._ingest_snapshot_into_catalog()
        classes = self._classes_seen()
        for cls in classes:
            self._catalog_register_class(cls)
            owned = self._owned_names(cls["id"])
            for base_qn in cls["bases"]:
                for member in self._members_of_class(base_qn):
                    inherited_qn = f"{cls['qualified_name']}.{member['name']}"
                    if member["name"] in owned:
                        self._keep_inherited_snapshot(inherited_qn, member["kind"])
                        continue
                    owned.add(member["name"])
                    self.symbols.append(self._inherited_member_symbol(cls, member))
        for cls in classes:
            children = self.catalog["subclasses"].get(cls["qualified_name"], {})
            for child in list(children.values()):
                owned = self._owned_names(child["id"])
                for member in self._members_of_class(cls["qualified_name"]):
                    inherited_qn = f"{child['qualified_name']}.{member['name']}"
                    if member["name"] in owned:
                        self._keep_inherited_snapshot(inherited_qn, member["kind"])
                        continue
                    owned.add(member["name"])
                    self.symbols.append(self._inherited_member_symbol(child, member))
        self._keep_foreign_inherited_copies()
        for (qualified_name, _kind), entry in self.symbols_snapshot.items():
            if not entry["seen"]:
                self._catalog_drop(qualified_name)
        self._unsee_inherited_without_parent()
        for symbol in self.symbols:
            self._catalog_put(symbol)

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
        if root in self._import_qn:
            bound = self._import_qn[root]
            return f"{bound}.{rest}" if rest else bound
        if not sep and target_name and self._module_qn:
            return f"{self._module_qn}.{target_name}"
        return target_name

    def _resolve_annotation_qn(self, type_name: str) -> str:
        root = type_name.split(".", 1)[0]
        resolved = type_name
        if root not in self.builtin_names:
            resolved = self._resolve_ref_qn(type_name)
        return resolved

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
        if current.text is None:
            return None
        return current.text.decode("utf-8")

    def _class_bases(self, node: Node) -> tuple[list[str], list[str]]:
        raw: list[str] = []
        resolved: list[str] = []
        seen: set[str] = set()
        for child in node.children:
            if child.type != "argument_list":
                continue
            for base in child.named_children:
                text = self._base_source_name(base)
                if not text:
                    continue
                raw.append(text)
                qn = self._resolve_ref_qn(text)
                if qn and qn not in seen:
                    seen.add(qn)
                    resolved.append(qn)
        return raw, resolved

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

    def _container_symbol_dict(
        self,
        symbol_id: int,
        file_id: int,
        name: str,
        qualified_name: str,
        kind: str,
        line_start: int,
        line_end: int,
        signature: str,
        docstring: str | None,
        modifiers: list,
        base_qualified_names: list[str],
        is_test: bool,
    ) -> dict:
        return {
            "id": symbol_id,
            "file_id": file_id,
            "parent_id": self.stack[-1].symbol_id if self.stack else None,
            "parent": self.stack[-1].name if self.stack else None,
            "name": name,
            "qualified_name": qualified_name,
            "kind": kind,
            "line_start": line_start,
            "line_end": line_end,
            "line_count": line_end - line_start + 1,
            "signature": signature,
            "docstring": docstring,
            "modifiers": str(modifiers) if modifiers else None,
            "language": "python",
            "base_qualified_names": base_qualified_names,
            "is_test": is_test,
            "is_inherited": False,
        }

    def _variable_symbol_dict(
        self,
        symbol_id: int,
        file_id: int,
        parent_id: int | None,
        name: str,
        qualified_name: str,
        line_start: int,
        line_end: int,
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
            "line_start": line_start,
            "line_end": line_end,
            "line_count": line_end - line_start + 1,
            "signature": signature,
            "docstring": None,
            "modifiers": None,
            "language": "python",
            "base_qualified_names": [],
            "is_test": is_test,
            "is_inherited": False,
        }

    def _record_import(
        self,
        file_id: int,
        module: str,
        import_path: str,
        imported_symbol: str,
        alias: str | None,
        line_number: int,
        import_type: str,
        import_scope: str,
        signature: str,
    ) -> None:
        key = (import_path, imported_symbol)
        row = {
            "file_id": file_id,
            "module": module,
            "import_path": import_path,
            "imported_symbol": imported_symbol,
            "alias": alias,
            "line_number": line_number,
            "import_type": import_type,
            "import_scope": import_scope,
            "signature": signature,
        }
        if key in self.imports_snapshot:
            self.imports_snapshot[key]["seen"] = True
            if self.imports_snapshot[key]["line_number"] != line_number:
                import_id = self.imports_snapshot[key]["id"]
                self.imports.append({"id": import_id, **row})
        else:
            import_id = self.assigner.reserve("imports", 1)[0]
            self.imports_snapshot[key] = {
                "id": import_id,
                "line_number": line_number,
                "seen": True,
            }
            self.imports.append({"id": import_id, **row})

    def _record_symbol_reference(
        self,
        file_id: int,
        target_name: str,
        ref_symbol_qualified_name: str,
        source_line: int,
        source_column: int,
        ref_kind: str,
        context: str,
        key: tuple[str, str, int, int],
    ) -> None:
        source_symbol_id = self.stack[-1].symbol_id if self.stack else None
        row = {
            "ref_symbol_name": target_name,
            "ref_symbol_qualified_name": ref_symbol_qualified_name,
            "source_file_id": file_id,
            "source_symbol_id": source_symbol_id,
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
                return
            # NOTE: Stay unseen so this file's delete removes the row and the
            # insert writes the same id back with the new source_symbol_id.
            stored_ref["seen"] = False
            self.symbol_references.append({"id": stored_ref["id"], **row})
            return
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
        """Map locals for stdlib filtering and for ref_symbol_qualified_name rewriting."""
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

        if import_type == "relative":
            return
        top = import_path.split(".", 1)[0] if import_path else ""
        if not top:
            return
        if imported_symbol:
            local = alias if alias else imported_symbol
            self._ref_root_module[local] = top
        else:
            if alias:
                self._ref_root_module[alias] = top
            else:
                root_local = import_path.split(".", 1)[0]
                self._ref_root_module[root_local] = top

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
    def _call_is_literal_receiver_method(func_node: Node) -> bool:
        if func_node.type != "attribute":
            return False
        obj = func_node.child_by_field_name("object")
        if obj is None:
            return False
        return obj.type in (
            "string",
            "integer",
            "float",
            "true",
            "false",
            "none",
        )

    def _should_skip_import_mapped_stdlib(self, root_id: str) -> bool:
        mod = self._ref_root_module.get(root_id)
        return bool(mod and mod in self.std_module_names)

    @staticmethod
    def _reference_root_identifier(target_name: str) -> str:
        """First identifier token (handles Path('.').resolve vs os.path.join)."""
        i = 0
        for ch in target_name:
            if ch.isalnum() or ch == "_":
                i += 1
            else:
                break
        if i > 0:
            return target_name[:i]
        return target_name.split(".", 1)[0]

    def _walk(self, node: Node, file_id: int, file_bytes: bytes) -> None:
        """Recursive DFS traversal."""
        # 1. Extract Data for CURRENT node
        self._process_node(node, file_id)

        # 2. Push to stack if it's a container (Class/Function)
        # We need to know the ID *before* recursing so children can use it as parent
        symbol_id = None
        scope_path = None
        pushed_stack = False
        kind: str | None = None
        is_test: bool = False

        if node.type in (
            "class_definition",
            "function_definition",
            "async_function_definition",
        ):
            # Extract symbol details first
            symbol_data = self._extract_symbol(node, file_id, file_bytes)
            name: str | None = None
            # Always push a stack frame for container defs when they exist in the DB
            # snapshot (even if we don't emit an updated row), otherwise nested
            # symbol/references lose parent context and churn ids across reparses.
            if symbol_data:
                symbol_id = symbol_data["id"]
                scope_path = symbol_data["qualified_name"] or symbol_data["name"]
                self.symbols.append(symbol_data)
                kind = symbol_data["kind"]
                is_test = symbol_data.get("is_test", False)
                name = symbol_data["name"]
            else:
                name_node = node.child_by_field_name("name")
                if name_node is not None and name_node.text is not None:
                    name = name_node.text.decode("utf-8")
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
                self.stack.append(StackFrame(symbol_id, scope_path, kind, is_test, name or ""))
                pushed_stack = True
            # Return annotations sit on the header. Record them after the push so
            # source_symbol_id is this function, not its parent.
            if node.type in ("function_definition", "async_function_definition"):
                return_type = node.child_by_field_name("return_type")
                if return_type is not None:
                    self._extract_reference(return_type, "type_annotation", file_id)
        elif node.type in (
            "assignment",
            "annotated_assignment",
            "augmented_assignment",
        ):
            # Variable symbols (module/class/function scope)
            for symbol_data in self._extract_variable_symbols(node, file_id, file_bytes):
                self.symbols.append(symbol_data)

        # 3. Recurse (import-first in statement suites so bindings exist before siblings)
        children = (
            self._children_import_first(node) if node.type in ("module", "block") else node.children
        )
        for child in children:
            self._walk(child, file_id, file_bytes)

        # 4. Pop from stack if we pushed
        if pushed_stack:
            popped = self.stack[-1]
            if popped.kind == "class":
                self._class_param_annos.pop(popped.qualified_name, None)
            elif popped.kind in ("function", "method"):
                self._func_param_annos.pop(popped.qualified_name, None)
            self.stack.pop()

    @staticmethod
    def _is_optional_type_value(node: Node) -> bool:
        if node.text is None:
            return False
        text = node.text.decode("utf-8")
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
            if node.text is None:
                return None
            return node.text.decode("utf-8")
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
                    if child.text is None:
                        return None
                    return child.text.decode("utf-8")
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
                    if child.text is None:
                        return None
                    return child.text.decode("utf-8")
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
                if c.type == "identifier" and param_name is None and c.text is not None:
                    param_name = c.text.decode("utf-8")
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
            if target is not None and target.type == "identifier" and target.text is not None:
                anno = self._annotation_type_name(node.child_by_field_name("type"))
                if anno:
                    self._name_types[target.text.decode("utf-8")] = anno
            return symbols

        # target is usually in field 'left' for assignment/augmented_assignment
        target = node.child_by_field_name("left") or node.child_by_field_name("target")
        if target is None:
            return symbols

        # symbol_leaf is the stable suffix for qualified_name (e.g. "llm").
        # name is the source spelling for the DB (e.g. "self.llm"), matching references.
        symbol_leaf = ""
        name = ""
        if target.type == "identifier" and target.text is not None:
            decoded = target.text.decode("utf-8")
            symbol_leaf = name = decoded
        elif target.type == "attribute" and target.text is not None:
            text = target.text.decode("utf-8")
            if text.startswith(("self.", "cls.")):
                symbol_leaf = text.split(".", 1)[1]
                name = text
        if not symbol_leaf:
            return symbols
        line_start = node.start_point.row + 1
        line_end = node.end_point.row + 1

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
                self._name_types[name] = anno

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
            if (line_start, line_end) != (
                self.symbols_snapshot[key]["line_start"],
                self.symbols_snapshot[key]["line_end"],
            ):
                symbol_id = self.symbols_snapshot[key]["id"]
                symbols.append(
                    self._variable_symbol_dict(
                        symbol_id,
                        file_id,
                        parent_id,
                        name,
                        qualified_name,
                        line_start,
                        line_end,
                        signature,
                        is_test,
                    )
                )
        else:
            symbol_id = self.assigner.reserve("symbols", 1)[0]
            self.symbols_snapshot[key] = {
                "id": symbol_id,
                "seen": True,
                "line_start": line_start,
                "line_end": line_end,
            }
            symbols.append(
                self._variable_symbol_dict(
                    symbol_id,
                    file_id,
                    parent_id,
                    name,
                    qualified_name,
                    line_start,
                    line_end,
                    signature,
                    is_test,
                )
            )

        return symbols

    def _process_node(self, node: Node, file_id: int) -> None:
        """Handle Imports and References."""
        # --- IMPORTS ---
        if node.type in ("import_statement", "import_from_statement"):
            self._extract_import(node, file_id)
            return  # Imports don't have children that are symbols

        # --- REFERENCES ---
        if node.type == "call":
            self._extract_reference(node, "call", file_id)
        elif node.type == "attribute":
            self._extract_reference(node, "access", file_id)
        elif node.type == "identifier":
            self._extract_identifier_reference(node, file_id)
        else:
            type_node = node.child_by_field_name("type")
            if type_node is not None:
                self._extract_reference(type_node, "type_annotation", file_id)

    def _extract_symbol(self, node: Node, file_id: int, file_bytes: bytes) -> dict | None:
        """Extract symbol definition (Class, Function, Variable)."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None

        if name_node.text is None:
            return None
        name = name_node.text.decode("utf-8")
        outer = (
            node.parent
            if node.parent is not None and node.parent.type == "decorated_definition"
            else None
        )
        line_start = outer.start_point.row + 1 if outer is not None else node.start_point.row + 1
        line_end = node.end_point.row + 1

        # Extract Modifiers (Decorators)
        modifiers = []
        if node.parent and node.parent.type == "decorated_definition":
            for child in node.parent.children:
                if child.type == "decorator":
                    if child.text is None:
                        continue
                    dec_text = child.text.decode("utf-8", errors="replace").strip()
                    if dec_text.startswith("@"):
                        dec_text = dec_text[1:].strip()
                    if dec_text:
                        modifiers.append(dec_text)

        kind = self._kind_for_definition(node)
        if kind == "method" and any(mod.split(".")[-1] == "property" for mod in modifiers):
            kind = "property"

        scope_path = self._qualify(name)

        # Extract Base Classes (for classes only). Raw text feeds is_test;
        # stored names are resolved qualified names.
        raw_bases: list[str] = []
        base_qualified_names: list[str] = []
        if kind == "class":
            raw_bases, base_qualified_names = self._class_bases(node)

        # Signature is the def/class header only. Decorators stay in modifiers.
        body_node = node.child_by_field_name("body")
        end_byte = body_node.start_byte if body_node is not None else node.end_byte
        sig_start_byte = node.start_byte
        signature = self._normalize_signature_bytes(
            file_bytes, sig_start_byte, end_byte, tail_rstrip=True
        )

        # A docstring is the first statement, or nothing.
        docstring = None
        if body_node is not None and body_node.named_children:
            stmt = body_node.named_children[0]
            str_node = None
            if stmt.type == "expression_statement" and stmt.named_children:
                candidate = stmt.named_children[0]
                if candidate.type == "string":
                    str_node = candidate
            elif stmt.type == "string":
                str_node = stmt
            if str_node is not None and str_node.text is not None:
                raw = str_node.text.decode("utf-8", errors="replace")
                try:
                    docstring = ast.literal_eval(raw)
                except ValueError, SyntaxError:
                    docstring = raw.strip("\"'")

        # Determine is_test (pytest + unittest)
        parent_is_test = self.stack[-1].is_test if self.stack else False
        is_test = False
        # Pytest
        if (
            (kind == "function" and name.startswith("test_"))
            or (kind == "class" and name.startswith("Test"))
            or (kind == "class" and any("TestCase" in bc for bc in raw_bases))
            or (kind == "method" and name.startswith("test_") and parent_is_test)
        ):
            is_test = True

        symbol_identity = scope_path
        qualified_name = symbol_identity
        key = (symbol_identity, kind)
        resolved_bases = tuple(base_qualified_names)
        if key in self.symbols_snapshot:
            self.symbols_snapshot[key]["seen"] = True
            # Only emit a row when something relevant changed; unchanged symbols still
            # need stack context, which is handled in _walk.
            prev = self.symbols_snapshot[key]
            prev_bases = tuple(prev.get("base_qualified_names", ()))
            if (line_start, line_end) != (
                prev["line_start"],
                prev["line_end"],
            ) or tuple(sorted(resolved_bases)) != tuple(sorted(prev_bases)):
                symbol_id = prev["id"]
                prev["line_start"] = line_start
                prev["line_end"] = line_end
                prev["base_qualified_names"] = resolved_bases
                return self._container_symbol_dict(
                    symbol_id,
                    file_id,
                    name,
                    qualified_name,
                    kind,
                    line_start,
                    line_end,
                    signature,
                    docstring,
                    modifiers,
                    base_qualified_names,
                    is_test,
                )
            return None
        symbol_id = self.assigner.reserve("symbols", 1)[0]
        self.symbols_snapshot[key] = {
            "id": symbol_id,
            "seen": True,
            "line_start": line_start,
            "line_end": line_end,
            "base_qualified_names": resolved_bases,
        }
        return self._container_symbol_dict(
            symbol_id,
            file_id,
            name,
            qualified_name,
            kind,
            line_start,
            line_end,
            signature,
            docstring,
            modifiers,
            base_qualified_names,
            is_test,
        )

    def _extract_import(self, node: Node, file_id: int) -> None:
        """Extract Import Statement."""
        line_number = node.start_point.row + 1
        if node.text is None:
            return
        signature = node.text.decode("utf-8")
        import_scope = "module" if not self.stack else "function"

        # Determine Type (Relative vs Absolute)
        if node.type == "import_from_statement":
            import_type = "absolute"
            import_path = ""

            # Relative imports come through as `relative_import` nodes, e.g. `.base` / `..pkg`
            relative_node = None
            for child in node.children:
                if child.type == "relative_import":
                    relative_node = child
                    break
            if relative_node is not None:
                import_type = "relative"
                if relative_node.text is None:
                    return
                import_path = relative_node.text.decode("utf-8")

            # Absolute import fallback (e.g. `from typing import X`)
            if not import_path:
                for child in node.children:
                    if child.type == "dotted_name":
                        if child.text is None:
                            continue
                        import_path = child.text.decode("utf-8")
                        break

            # Keep the source spelling in ``signature``. ``import_path`` is the
            # module key ``resolve_imports`` matches to ``files.normalized_path``.
            stored_path = import_path
            if import_type == "relative":
                resolved = self._resolve_relative_import_path(import_path)
                if resolved:
                    stored_path = resolved.lower()

            for child in node.children:
                imported_symbol = None
                alias = None
                if child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    if not name_node:
                        continue
                    if name_node.text is None:
                        continue
                    imported_symbol = name_node.text.decode("utf-8")
                    alias = (
                        alias_node.text.decode("utf-8")
                        if alias_node is not None and alias_node.text is not None
                        else None
                    )
                elif child.type == "dotted_name":
                    # Skip the module part (absolute dotted_name or relative_import's dotted_name)
                    if relative_node is not None and child.start_byte < relative_node.end_byte:
                        continue
                    if (
                        relative_node is None
                        and child.text is not None
                        and child.text.decode("utf-8") == import_path
                    ):
                        continue
                    if child.text is None:
                        continue
                    imported_symbol = child.text.decode("utf-8")

                if imported_symbol is None:
                    continue

                module = stored_path.split(".")[0]

                self._record_import(
                    file_id,
                    module,
                    stored_path,
                    imported_symbol,
                    alias,
                    line_number,
                    import_type,
                    import_scope,
                    signature,
                )
                self._register_import_ref_binding(import_path, imported_symbol, alias, import_type)

        elif node.type == "import_statement":
            import_type = "absolute"
            for child in node.children:
                import_path = None
                alias = None
                if child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    if not name_node:
                        continue
                    if name_node.text is None:
                        continue
                    import_path = name_node.text.decode("utf-8")
                    alias = (
                        alias_node.text.decode("utf-8")
                        if alias_node is not None and alias_node.text is not None
                        else None
                    )
                elif child.type == "dotted_name":
                    if child.text is None:
                        continue
                    import_path = child.text.decode("utf-8")

                if import_path is None:
                    continue

                module = import_path.split(".")[0]

                imported_symbol = ""
                self._record_import(
                    file_id,
                    module,
                    import_path,
                    imported_symbol,
                    alias,
                    line_number,
                    import_type,
                    import_scope,
                    signature,
                )
                self._register_import_ref_binding(import_path, imported_symbol, alias, import_type)

    def _extract_identifier_reference(self, node: Node, file_id: int) -> None:
        name = node.text.decode("utf-8") if node.text is not None else ""
        qualified = None
        if name and not self._identifier_is_skipped(node):
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
        skipped = parent is not None and self._parent_skips_identifier(parent, node)
        if not skipped:
            skipped = (
                self._node_is_under(node, ("import_statement", "import_from_statement"))
                or self._node_is_in_type(node)
                or self._node_is_class_base(node)
            )
        return skipped

    def _parent_skips_identifier(self, parent: Node, node: Node) -> bool:
        left = parent.child_by_field_name("left")
        name = parent.child_by_field_name("name")
        attribute = parent.child_by_field_name("attribute")
        function = parent.child_by_field_name("function")
        alias = parent.child_by_field_name("alias")
        binding_left = (
            parent.type
            in (
                "assignment",
                "annotated_assignment",
                "augmented_assignment",
                "for_statement",
                "for_in_clause",
            )
            and left == node
        )
        definition_name = (
            parent.type
            in (
                "function_definition",
                "async_function_definition",
                "class_definition",
                "typed_parameter",
                "typed_default_parameter",
                "default_parameter",
                "named_expression",
            )
            and name == node
        )
        pattern_name = parent.type in (
            "parameters",
            "list_splat_pattern",
            "dictionary_splat_pattern",
        )
        return (
            binding_left
            or definition_name
            or pattern_name
            or (parent.type == "attribute" and attribute == node)
            or (parent.type == "keyword_argument" and name == node)
            or (parent.type == "call" and function == node)
            or (parent.type == "as_pattern" and alias == node)
            or parent.type in ("global_statement", "nonlocal_statement")
        )

    def _node_is_under(self, node: Node, types: tuple[str, ...]) -> bool:
        found = False
        parent = node.parent
        while parent is not None and not found:
            if parent.type in types:
                found = True
            parent = parent.parent
        return found

    def _node_is_class_base(self, node: Node) -> bool:
        found = False
        parent = node.parent
        while parent is not None and not found:
            if parent.type == "class_definition":
                bases = parent.child_by_field_name("superclasses")
                if (
                    bases is not None
                    and bases.start_byte <= node.start_byte
                    and bases.end_byte >= node.end_byte
                ):
                    found = True
            parent = parent.parent
        return found

    def _node_is_in_type(self, node: Node) -> bool:
        found = False
        parent = node.parent
        while parent is not None and not found:
            for field_name in ("type", "return_type"):
                field = parent.child_by_field_name(field_name)
                if (
                    field is not None
                    and field.start_byte <= node.start_byte
                    and field.end_byte >= node.end_byte
                ):
                    found = True
            parent = parent.parent
        return found

    def _extract_reference(self, node: Node, ref_kind: str, file_id: int) -> None:
        """Extract Reference (Call, Access, Type)."""

        # Skip access nodes that are the function part of a call — the call already
        # captures this reference (call is a stricter access).
        if ref_kind == "access":
            parent = node.parent
            if (
                parent is not None
                and parent.type == "call"
                and parent.child_by_field_name("function") == node
            ):
                return

        target_name = ""

        if ref_kind == "call":
            # func() -> target is 'func'
            func_node = node.child_by_field_name("function")
            if func_node:
                if self._call_is_literal_receiver_method(func_node):
                    return
                if func_node.text is None:
                    return
                target_name = func_node.text.decode("utf-8")
        elif ref_kind == "access":
            # obj.attr -> target is full chain like "obj.attr" or "a.b.c"
            attr_node = node.child_by_field_name("attribute")
            obj_node = node.child_by_field_name("object")
            if not attr_node or attr_node.text is None:
                return

            leaf_name = attr_node.text.decode("utf-8")
            if obj_node is not None and obj_node.text is not None:
                obj_text = obj_node.text.decode("utf-8")
                target_name = f"{obj_text}.{leaf_name}" if obj_text else leaf_name
            else:
                target_name = leaf_name
        elif ref_kind == "type_annotation":
            # x: Type -> normalize annotation target
            if node.text is None:
                return
            target_name = node.text.decode("utf-8").strip()
            if target_name.endswith("]"):
                if target_name.startswith("Optional["):
                    target_name = target_name[len("Optional[") : -1].strip()
                elif target_name.startswith("typing.Optional["):
                    target_name = target_name[len("typing.Optional[") : -1].strip()
            if "[" in target_name:
                target_name = target_name.split("[", 1)[0].strip()

        if not target_name:
            return

        root_id = self._reference_root_identifier(target_name)
        if ref_kind == "type_annotation":
            if root_id in self.builtin_names:
                return
            if self._should_skip_import_mapped_stdlib(root_id):
                return
        else:
            if root_id in self.builtin_names or root_id in self.std_module_names:
                return
            if self._should_skip_import_mapped_stdlib(root_id):
                return

        # Resolved qualified_name for self./cls. when parent class is on the stack.
        resolved_qualified = None
        receiver_root = ""
        linked_variable = False
        if target_name.startswith(("self.", "cls.")):
            suffix = target_name.split(".", 1)[1]
            first_seg, _, rest_after_first = suffix.partition(".")
            for entry in reversed(self.stack):
                if entry.kind != "class":
                    continue
                class_qn = entry.qualified_name
                ctor_map = self._class_param_annos.get(class_qn)
                if ctor_map and first_seg in ctor_map:
                    type_qn = self._resolve_annotation_qn(ctor_map[first_seg])
                    resolved_qualified = (
                        f"{type_qn}.{rest_after_first}" if rest_after_first else type_qn
                    )
                else:
                    resolved_qualified = f"{class_qn}.{suffix}"
                break
            else:
                if self.stack:
                    resolved_qualified = f"{self.stack[-1].qualified_name}.{suffix}"
        else:
            root, sep, rest = target_name.partition(".")
            receiver_root = root
            if sep:
                type_name = None
                for entry in reversed(self.stack):
                    if entry.kind not in ("function", "method"):
                        continue
                    param_map = self._func_param_annos.get(entry.qualified_name)
                    if param_map and root in param_map:
                        type_name = param_map[root]
                    break
                if type_name is None:
                    type_name = self._name_types.get(root)
                    linked_variable = type_name is not None and root in self._var_qns
                if type_name:
                    type_qn = self._resolve_annotation_qn(type_name)
                    resolved_qualified = f"{type_qn}.{rest}" if rest else type_qn

        if resolved_qualified is not None:
            # class_qn / stack paths and param-rewritten QNs are already module-prefixed.
            ref_symbol_qualified_name = resolved_qualified
        else:
            ref_symbol_qualified_name = self._resolve_ref_qn(target_name)

        source_line = node.start_point.row + 1
        source_column = node.start_point.column
        context = node.text.decode("utf-8") if node.text is not None else ""
        rows = [(target_name, ref_symbol_qualified_name, ref_kind, context)]
        if ref_kind == "call" and linked_variable:
            rows.append((receiver_root, self._var_qns[receiver_root], "access", receiver_root))
        for name, qualified, kind, row_context in rows:
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
        return
