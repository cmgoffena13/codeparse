from src.assigner import GlobalIDAssigner

_INHERIT_KINDS = frozenset({"method", "property", "variable"})
_STORED_KINDS = frozenset({"class", "method", "property", "variable"})


class ClassCatalog:
    def __init__(self) -> None:
        self.by_qualified_name: dict[str, dict] = {}
        self.subclasses: dict[str, dict[str, dict]] = {}

    def put(self, symbol: dict, *, overwrite: bool = True) -> None:
        kind = symbol["kind"]
        if kind in _STORED_KINDS:
            qualified_name = symbol["qualified_name"]
            skip = (not overwrite) and qualified_name in self.by_qualified_name
            if not skip:
                self.by_qualified_name[qualified_name] = {
                    "id": symbol["id"],
                    "file_id": symbol["file_id"],
                    "parent_id": symbol.get("parent_id"),
                    "parent": symbol.get("parent"),
                    "name": symbol["name"],
                    "qualified_name": qualified_name,
                    "kind": kind,
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
        self.by_qualified_name.pop(qualified_name, None)
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
            "line_start": symbol["line_start"],
            "line_end": symbol["line_end"],
            "line_count": symbol.get("line_count", symbol["line_end"] - symbol["line_start"] + 1),
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
            for symbol in self.by_qualified_name.values():
                if symbol.get("parent_id") == owner_id and symbol["kind"] in _INHERIT_KINDS:
                    by_name[symbol["name"]] = self._member_from_symbol(symbol)
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
        names.update(
            symbol["name"]
            for symbol in self.by_qualified_name.values()
            if symbol.get("parent_id") == class_id and symbol["kind"] in _INHERIT_KINDS
        )
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
