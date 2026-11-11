import re
import sqlite3

from src.assigner import GlobalIDAssigner

_INHERIT_KINDS = frozenset({"method", "property", "variable"})
_STORED_KINDS = frozenset({"class", "method", "property", "variable"})
_RETURN_TYPE_RE = re.compile(r"->\s*([A-Za-z_][\w.]*)")
_VAR_ANNOTATION_RE = re.compile(r"(?:self\.|cls\.)?([A-Za-z_]\w*)\s*:\s*([A-Za-z_][\w.]*)")


class ClassCatalog:
    def __init__(self) -> None:
        self.by_qualified_name: dict[str, dict] = {}
        self.subclasses: dict[str, dict[str, dict]] = {}
        self.members_by_parent_id: dict[int, dict[str, dict]] = {}
        self.field_types: dict[str, str] = {}
        self.method_returns: dict[str, str] = {}

    def absorb_member_types(
        self, field_types: dict[str, str], method_returns: dict[str, str]
    ) -> None:
        self.field_types.update(field_types)
        self.method_returns.update(method_returns)

    def field_type(self, owner_qn: str, member: str) -> str | None:
        key = f"{owner_qn}.{member}"
        found = self.field_types.get(key)
        if found is None:
            entry = self.by_qualified_name.get(owner_qn)
            if entry is not None and entry["kind"] == "class":
                for base in entry.get("base_qualified_names") or ():
                    found = self.field_type(base, member)
                    if found is not None:
                        break
        return found

    def method_return(self, method_qn: str) -> str | None:
        return self.method_returns.get(method_qn)

    def _resolve_type_name(self, type_name: str, classes_by_leaf: dict[str, list[str]]) -> str:
        resolved = type_name
        if type_name not in self.by_qualified_name:
            matches = classes_by_leaf.get(type_name.rsplit(".", 1)[-1], [])
            if len(matches) == 1:
                resolved = matches[0]
        return resolved

    def seed_from_db(self, connection: sqlite3.Connection) -> None:
        classes_by_leaf: dict[str, list[str]] = {}
        bases_by_id: dict[int, list[str]] = {}
        for row in connection.execute("SELECT symbol_id, base_qualified_name FROM symbol_bases"):
            bases_by_id.setdefault(row["symbol_id"], []).append(row["base_qualified_name"])

        for row in connection.execute(
            """
            SELECT id, file_id, name, qualified_name, start_line, end_line
            FROM symbols
            WHERE kind = 'class'
            """
        ):
            bases = bases_by_id.get(row["id"], [])
            self.put(
                {
                    "id": row["id"],
                    "file_id": row["file_id"],
                    "parent_id": None,
                    "parent": None,
                    "name": row["name"],
                    "qualified_name": row["qualified_name"],
                    "kind": "class",
                    "start_line": row["start_line"],
                    "end_line": row["end_line"],
                    "line_count": row["end_line"] - row["start_line"] + 1,
                    "signature": "",
                    "docstring": None,
                    "modifiers": None,
                    "language": "python",
                    "is_test": False,
                    "is_inherited": False,
                    "base_qualified_names": bases,
                    "bases": bases,
                },
                overwrite=False,
            )
            classes_by_leaf.setdefault(row["name"], []).append(row["qualified_name"])
        for row in connection.execute(
            """
            SELECT qualified_name, kind, signature FROM symbols
            WHERE kind IN ('method', 'property', 'variable') AND signature != ''
            """
        ):
            signature = row["signature"]
            qualified_name = row["qualified_name"]
            if row["kind"] in ("method", "property"):
                match = _RETURN_TYPE_RE.search(signature)
                if match is not None:
                    self.method_returns[qualified_name] = self._resolve_type_name(
                        match.group(1), classes_by_leaf
                    )
            else:
                match = _VAR_ANNOTATION_RE.search(signature)
                if match is not None:
                    self.field_types[qualified_name] = self._resolve_type_name(
                        match.group(2), classes_by_leaf
                    )

    def rewrite_pending_qualified_name(self, qualified_name: str) -> str:
        parts = qualified_name.split(".")
        rewritten = qualified_name
        for class_end in range(len(parts) - 1, 0, -1):
            prefix = ".".join(parts[:class_end])
            entry = self.by_qualified_name.get(prefix)
            if entry is not None and entry["kind"] == "class":
                rest = parts[class_end:]
                if len(rest) >= 2 and self.field_type(prefix, rest[0]) is not None:
                    current = prefix
                    index = 0
                    while index < len(rest) - 1:
                        next_type = self.field_type(current, rest[index])
                        if next_type is None:
                            rewritten = f"{current}.{'.'.join(rest[index:])}"
                            break
                        current = next_type
                        index += 1
                    else:
                        rewritten = f"{current}.{rest[-1]}"
                break
        return rewritten

    def put(self, symbol: dict, *, overwrite: bool = True) -> None:
        kind = symbol["kind"]
        if kind in _STORED_KINDS:
            qualified_name = symbol["qualified_name"]
            skip = (not overwrite) and qualified_name in self.by_qualified_name
            if not skip:
                prior = self.by_qualified_name.get(qualified_name)
                if prior is not None and prior["kind"] in _INHERIT_KINDS:
                    prior_parent = prior.get("parent_id")
                    if prior_parent is not None:
                        bucket = self.members_by_parent_id.get(prior_parent)
                        if bucket is not None:
                            bucket.pop(prior["name"], None)
                            if not bucket:
                                self.members_by_parent_id.pop(prior_parent, None)
                stored = {
                    "id": symbol["id"],
                    "file_id": symbol["file_id"],
                    "parent_id": symbol.get("parent_id"),
                    "parent": symbol.get("parent"),
                    "name": symbol["name"],
                    "qualified_name": qualified_name,
                    "kind": kind,
                    "start_line": symbol["start_line"],
                    "end_line": symbol["end_line"],
                    "line_count": symbol.get(
                        "line_count", symbol["end_line"] - symbol["start_line"] + 1
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
                self.by_qualified_name[qualified_name] = stored
                parent_id = stored["parent_id"]
                if kind in _INHERIT_KINDS and parent_id is not None:
                    members = self.members_by_parent_id
                    if parent_id not in members:
                        members[parent_id] = {}
                    members[parent_id][stored["name"]] = stored
            if kind == "class":
                stored = self.by_qualified_name[qualified_name]
                self.register_class(
                    {
                        "id": stored["id"],
                        "name": stored["name"],
                        "qualified_name": qualified_name,
                        "bases": list(
                            stored.get("base_qualified_names") or symbol.get("bases") or ()
                        ),
                    }
                )

    def drop(self, qualified_name: str) -> None:
        cataloged = self.by_qualified_name.pop(qualified_name, None)
        self.field_types.pop(qualified_name, None)
        self.method_returns.pop(qualified_name, None)
        if cataloged is not None and cataloged["kind"] in _INHERIT_KINDS:
            parent_id = cataloged.get("parent_id")
            if parent_id is not None:
                bucket = self.members_by_parent_id.get(parent_id)
                if bucket is not None:
                    bucket.pop(cataloged["name"], None)
                    if not bucket:
                        self.members_by_parent_id.pop(parent_id, None)
        for children in self.subclasses.values():
            children.pop(qualified_name, None)

    def drop_file(self, file_id: int) -> None:
        for qualified_name, cataloged in list(self.by_qualified_name.items()):
            if cataloged.get("file_id") == file_id:
                self.drop(qualified_name)

    def register_class(self, cls: dict) -> None:
        qualified_name = cls["qualified_name"]
        for children in self.subclasses.values():
            children.pop(qualified_name, None)
        for base_qualified_name in cls["bases"]:
            bucket = self.subclasses.setdefault(base_qualified_name, {})
            bucket[qualified_name] = {
                "id": cls["id"],
                "name": cls["name"],
                "qualified_name": qualified_name,
            }

    def _symbol_from_snapshot(
        self, qualified_name: str, kind: str, entry: dict, file_id: int
    ) -> dict:
        leaf = qualified_name.rsplit(".", 1)[-1]
        parent_qn = qualified_name.rsplit(".", 1)[0] if "." in qualified_name else ""
        parent = self.by_qualified_name.get(parent_qn)
        parent_is_class = parent is not None and parent["kind"] == "class"
        return {
            "id": entry["id"],
            "file_id": file_id,
            "parent_id": parent["id"] if parent_is_class else None,
            "parent": parent["name"] if parent_is_class else None,
            "name": leaf,
            "qualified_name": qualified_name,
            "kind": kind,
            "start_line": entry["start_line"],
            "end_line": entry["end_line"],
            "line_count": entry["end_line"] - entry["start_line"] + 1,
            "signature": "",
            "docstring": None,
            "modifiers": None,
            "language": "python",
            "base_qualified_names": list(entry.get("base_qualified_names") or ()),
            "is_test": False,
        }

    def _ingest_snapshot(self, symbols_snapshot: dict, file_id: int) -> None:
        classes: list[tuple[str, str, dict]] = []
        others: list[tuple[str, str, dict]] = []
        for (qualified_name, kind), entry in symbols_snapshot.items():
            if kind == "class":
                classes.append((qualified_name, kind, entry))
            else:
                others.append((qualified_name, kind, entry))
        for qualified_name, kind, entry in classes + others:
            self.put(
                self._symbol_from_snapshot(qualified_name, kind, entry, file_id),
                overwrite=False,
            )

    def _classes_seen(self, symbols: list[dict], symbols_snapshot: dict) -> list[dict]:
        by_id: dict[int, dict] = {}
        for (qualified_name, kind), entry in symbols_snapshot.items():
            if kind == "class" and entry["seen"]:
                by_id[entry["id"]] = {
                    "id": entry["id"],
                    "name": qualified_name.rsplit(".", 1)[-1],
                    "qualified_name": qualified_name,
                    "bases": list(entry.get("base_qualified_names") or ()),
                }
        for symbol in symbols:
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
            "start_line": symbol["start_line"],
            "end_line": symbol["end_line"],
            "line_count": symbol.get("line_count", symbol["end_line"] - symbol["start_line"] + 1),
            "signature": symbol.get("signature") or "",
            "docstring": symbol.get("docstring"),
            "modifiers": symbol.get("modifiers"),
            "language": symbol.get("language") or "python",
            "is_test": symbol.get("is_test") or False,
        }

    def _members_of_class(
        self, class_qn: str, symbols: list[dict], symbols_snapshot: dict
    ) -> list[dict]:
        owner = next(
            (
                symbol
                for symbol in symbols
                if symbol["kind"] == "class" and symbol["qualified_name"] == class_qn
            ),
            self.by_qualified_name.get(class_qn),
        )
        by_name: dict[str, dict] = {}
        if owner is not None and owner.get("kind", "class") == "class":
            owner_id = owner["id"]
            prefix = f"{class_qn}."
            for name, symbol in self.members_by_parent_id.get(owner_id, {}).items():
                by_name[name] = self._member_from_symbol(symbol)
            for (qualified_name, kind), entry in symbols_snapshot.items():
                leaf = qualified_name[len(prefix) :]
                if (
                    kind in _INHERIT_KINDS
                    and qualified_name.startswith(prefix)
                    and "." not in leaf
                    and not entry["seen"]
                ):
                    by_name.pop(leaf, None)
            for symbol in symbols:
                if symbol["parent_id"] == owner_id and symbol["kind"] in _INHERIT_KINDS:
                    by_name[symbol["name"]] = self._member_from_symbol(symbol)
        return list(by_name.values())

    def _owned_names(self, class_id: int, symbols: list[dict]) -> set[str]:
        names = {symbol["name"] for symbol in symbols if symbol["parent_id"] == class_id}
        names.update(self.members_by_parent_id.get(class_id, {}))
        return names

    def _keep_inherited_snapshot(
        self, symbols_snapshot: dict, qualified_name: str, kind: str
    ) -> None:
        key = (qualified_name, kind)
        if key in symbols_snapshot:
            symbols_snapshot[key]["seen"] = True

    def _keep_foreign_inherited_copies(self, symbols: list[dict], symbols_snapshot: dict) -> None:
        classes = self._classes_seen(symbols, symbols_snapshot)
        local_qns = {cls["qualified_name"] for cls in classes}
        local_leaves = {
            member["name"]
            for cls in classes
            for member in self._members_of_class(cls["qualified_name"], symbols, symbols_snapshot)
        }
        for (qualified_name, kind), entry in symbols_snapshot.items():
            if kind not in _INHERIT_KINDS or "." not in qualified_name:
                continue
            parent_qn, leaf = qualified_name.rsplit(".", 1)
            if parent_qn not in local_qns and leaf in local_leaves:
                entry["seen"] = True

    def _unsee_inherited_without_parent(self, symbols_snapshot: dict) -> None:
        unseen_local_classes = {
            qualified_name
            for (qualified_name, kind), entry in symbols_snapshot.items()
            if kind == "class" and not entry["seen"]
        }
        for (qualified_name, kind), entry in symbols_snapshot.items():
            parent_qn = qualified_name.rsplit(".", 1)[0] if "." in qualified_name else ""
            skip = (
                (not entry["seen"])
                or kind not in _INHERIT_KINDS
                or parent_qn not in unseen_local_classes
            )
            if not skip:
                entry["seen"] = False
                self.drop(qualified_name)

    def _inherited_member_symbol(
        self,
        cls: dict,
        member: dict,
        symbols_snapshot: dict,
        assigner: GlobalIDAssigner,
    ) -> dict:
        qualified_name = f"{cls['qualified_name']}.{member['name']}"
        key = (qualified_name, member["kind"])
        snapshot = symbols_snapshot.get(key)
        cataloged = self.by_qualified_name.get(qualified_name)
        symbol_id = (
            snapshot["id"]
            if snapshot is not None
            else cataloged["id"]
            if cataloged is not None
            else assigner.reserve("symbols", 1)[0]
        )
        self._keep_inherited_snapshot(symbols_snapshot, qualified_name, member["kind"])
        return {
            "id": symbol_id,
            "file_id": member["file_id"],
            "parent_id": cls["id"],
            "parent": cls["name"],
            "name": member["name"],
            "qualified_name": qualified_name,
            "kind": member["kind"],
            "start_line": member["start_line"],
            "end_line": member["end_line"],
            "line_count": member["line_count"],
            "signature": member["signature"],
            "docstring": member["docstring"],
            "modifiers": member["modifiers"],
            "language": member["language"],
            "base_qualified_names": [],
            "is_test": member["is_test"],
            "is_inherited": True,
        }

    def link(
        self,
        symbols: list[dict],
        symbols_snapshot: dict,
        file_id: int,
        assigner: GlobalIDAssigner,
    ) -> None:
        self._ingest_snapshot(symbols_snapshot, file_id)
        classes = self._classes_seen(symbols, symbols_snapshot)

        for cls in classes:
            self.register_class(cls)
            owned = self._owned_names(cls["id"], symbols)
            for base_qualified_name in cls["bases"]:
                for member in self._members_of_class(
                    base_qualified_name, symbols, symbols_snapshot
                ):
                    inherited_qualified_name = f"{cls['qualified_name']}.{member['name']}"
                    if member["name"] in owned:
                        self._keep_inherited_snapshot(
                            symbols_snapshot, inherited_qualified_name, member["kind"]
                        )
                        continue
                    owned.add(member["name"])
                    symbols.append(
                        self._inherited_member_symbol(cls, member, symbols_snapshot, assigner)
                    )

        for cls in classes:
            children = self.subclasses.get(cls["qualified_name"], {})
            for child in list(children.values()):
                owned = self._owned_names(child["id"], symbols)
                for member in self._members_of_class(
                    cls["qualified_name"], symbols, symbols_snapshot
                ):
                    inherited_qualified_name = f"{child['qualified_name']}.{member['name']}"
                    if member["name"] in owned:
                        self._keep_inherited_snapshot(
                            symbols_snapshot, inherited_qualified_name, member["kind"]
                        )
                        continue
                    owned.add(member["name"])
                    symbols.append(
                        self._inherited_member_symbol(child, member, symbols_snapshot, assigner)
                    )

        self._keep_foreign_inherited_copies(symbols, symbols_snapshot)
        for (qualified_name, _kind), entry in symbols_snapshot.items():
            if not entry["seen"]:
                self.drop(qualified_name)
        self._unsee_inherited_without_parent(symbols_snapshot)
        for symbol in symbols:
            self.put(symbol)
