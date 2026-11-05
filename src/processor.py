import os
import re
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import xxhash

from src.assigner import GlobalIDAssigner
from src.db import TABLE_BATCH_MAP, CodeDB
from src.git_utils import path_spec_for_indexing, relative_path_is_ignored
from src.parsers.class_catalog import ClassCatalog
from src.parsers.factory import FILE_EXTENSION_MAPPING, ParserFactory

T = TypeVar("T")

_MAIN_GUARD = re.compile(r"""(?m)^[ \t]*if[ \t]+__name__[ \t]*==[ \t]*(['"])__main__\1[ \t]*:""")
_NAMED_PYTHON_ENTRY_FILES = frozenset({"app.py", "main.py"})


def file_has_main_guard(file_bytes: bytes) -> bool:
    return _MAIN_GUARD.search(file_bytes.decode("utf-8", errors="replace")) is not None


def file_path_is_test(relative_path: str) -> bool:
    """True for conventional test *files*, not packages named ``test``.

    Matches ``tests/`` trees, ``test_*.py``, ``*_test.py``, and ``conftest.py``.
    A segment named ``test`` (e.g. ``sqlmesh/core/test/definition.py``) is not
    enough — that is product code.
    """
    parts = relative_path.split("/")
    if "tests" in parts:
        return True
    name = parts[-1]
    if name == "conftest.py":
        return True
    if name.startswith("test_") and name.endswith(".py"):
        return True
    return name.endswith("_test.py")


def _join_rel(dir_rel: str, name: str) -> str:
    return name if not dir_rel else f"{dir_rel}/{name}"


class CodeProcessor:
    def __init__(self, db: CodeDB, root: Path):
        self.db = db
        self.assigner = GlobalIDAssigner(db)
        self.root = root.resolve()
        self._index_ignore_spec = path_spec_for_indexing(self.root)
        self.last_full_parse, self.last_incremental = self.db.get_watermark()
        self.db_batch_size = 1000
        self.db_batches = self._new_batches()

        self.files_skipped: int = 0
        self.files_indexed: int = 0
        # One SQLite connection + mutable snapshots: serialize index + reads.
        self._lock = threading.RLock()

        self.directories_snapshot = self.db.get_directories_snapshot()
        self.files_snapshot = self.db.get_files_snapshot()
        self.class_catalog = ClassCatalog()

    def _process_directories(self, directory_names: list[str], dir_rel: str) -> None:
        for directory_name in directory_names:
            directory_relative_path = _join_rel(dir_rel, directory_name)
            if directory_relative_path in self.directories_snapshot:
                self.directories_snapshot[directory_relative_path]["seen"] = True
                continue

            directory_id = self.assigner.reserve("directories", 1)[0]
            parent_key = dir_rel if dir_rel else None
            parent_row = None if parent_key is None else self.directories_snapshot.get(parent_key)
            parent_id = None if parent_row is None else parent_row["id"]
            depth = directory_relative_path.count("/")
            self.db_batches["directories"].append(
                {
                    "id": directory_id,
                    "parent_id": parent_id,
                    "name": directory_name,
                    "path": directory_relative_path,
                    "depth": depth,
                }
            )
            self.directories_snapshot[directory_relative_path] = {
                "id": directory_id,
                "seen": True,
            }

    def _python_import_path(self, relative: str) -> str:
        """Start the module path at the outermost package.

        A directory is a package when it contains ``__init__.py``. Leading
        directories that are not packages are dropped, so
        ``src/fundamentals/xxx.py`` becomes ``fundamentals/xxx.py``. A path
        with no package keeps every directory.
        """
        parts = relative.split("/")
        dirs = parts[:-1]
        for index in range(len(dirs)):
            package = self.root.joinpath(*dirs[: index + 1])
            if (package / "__init__.py").is_file():
                return "/".join(parts[index:])
        return relative

    def _normalize_path(self, path: str, language: str | None = None) -> str:
        if language == "python":
            path = self._python_import_path(path)
        dot = path.rfind(".")
        slash = path.rfind("/")
        stem = path[:dot] if dot > slash else path
        posix = stem.lower()
        if language == "python":
            posix = posix.replace("/", ".")
            posix = posix.removesuffix(".__init__")
        return posix

    def _process_file(self, file_name: str, directory_path: str, dir_rel: str, full: bool) -> None:
        file_relative_path = _join_rel(dir_rel, file_name)
        file_abs = f"{directory_path}{os.sep}{file_name}"
        try:
            file_stat = os.lstat(file_abs)
        except OSError:
            self.files_skipped += 1
            return
        mtime_ns = file_stat.st_mtime_ns
        size_bytes = file_stat.st_size
        dot = file_name.rfind(".")
        file_extension = file_name[dot:] if dot != -1 else ""

        if not file_extension and not os.path.isfile(file_abs):  # noqa: PTH113
            return

        directory_id = None if not dir_rel else self.directories_snapshot[dir_rel]["id"]

        existed = file_relative_path in self.files_snapshot
        if existed:
            prior = self.files_snapshot[file_relative_path]
            file_id = prior["id"]
            prior_hash = prior["content_hash"]
            prior_mtime_ns = prior["mtime_ns"]
            prior_size_bytes = prior["size_bytes"]
            prior_symbol_count = prior["symbol_count"]
            prior_line_count = prior["line_count"]
            prior_is_test = prior["is_test"]
        else:
            file_id = self.assigner.reserve("files", 1)[0]
            prior_hash = None
            prior_mtime_ns = None
            prior_size_bytes = None
            prior_symbol_count = 0
            prior_line_count = 0
            prior_is_test = False

        if not full and existed and prior_mtime_ns == mtime_ns and prior_size_bytes == size_bytes:
            self.files_snapshot[file_relative_path] = {
                "id": file_id,
                "directory_id": directory_id,
                "seen": True,
                "content_hash": prior_hash,
                "mtime_ns": mtime_ns,
                "size_bytes": size_bytes,
                "line_count": prior_line_count,
                "symbol_count": prior_symbol_count,
                "is_test": prior_is_test,
            }
            return

        try:
            with open(file_abs, "rb") as handle:  # noqa: PTH123
                file_bytes = handle.read()
            file_hash = xxhash.xxh128(file_bytes).hexdigest()
            line_count = file_bytes.count(b"\n") + 1 if file_bytes else 0
        except OSError:
            self.files_skipped += 1
            return

        lang = FILE_EXTENSION_MAPPING.get(file_extension)
        is_test = file_path_is_test(file_relative_path)
        file_row = {
            "id": file_id,
            "directory_id": directory_id,
            "name": file_name,
            "path": file_relative_path,
            "normalized_path": self._normalize_path(file_relative_path, language=lang),
            "language": lang,
            "content_hash": file_hash,
            "mtime_ns": mtime_ns,
            "size_bytes": size_bytes,
            "line_count": line_count,
            "symbol_count": prior_symbol_count,
            "is_test": is_test,
        }
        if (
            not existed
            or prior_hash != file_hash
            or prior_mtime_ns != mtime_ns
            or prior_size_bytes != size_bytes
        ):
            self.db_batches["files"].append(file_row)
        snap = {
            "id": file_id,
            "directory_id": directory_id,
            "seen": True,
            "content_hash": file_hash,
            "mtime_ns": mtime_ns,
            "size_bytes": size_bytes,
            "line_count": line_count,
            "symbol_count": prior_symbol_count,
            "is_test": is_test,
        }
        self.files_snapshot[file_relative_path] = snap

        if full or file_hash != prior_hash:
            if file_extension not in FILE_EXTENSION_MAPPING:
                self.files_skipped += 1
                return

            self._record_entry_point(
                file_id,
                file_name=file_name,
                lang=lang,
                is_test=is_test,
                file_bytes=file_bytes,
            )
            parser = ParserFactory.get_parser(
                FILE_EXTENSION_MAPPING[file_extension], self.assigner, self.db
            )
            parser.class_catalog = self.class_catalog
            module_qn = (
                self._normalize_path(file_relative_path, language=lang) if lang == "python" else ""
            )
            is_package = lang == "python" and file_name == "__init__.py"
            symbols, imports, references = parser.parse(
                file_id,
                file_bytes,
                module_qn=module_qn,
                is_package=is_package,
            )
            n = len(symbols)
            file_row["symbol_count"] = n
            snap["symbol_count"] = n
            self.db_batches["symbols"].extend(symbols)
            self.db_batches["imports"].extend(imports)
            self.db_batches["symbol_references"].extend(references)
            self.files_indexed += 1
            self._insert_batch()

    def _new_batches(self) -> dict[str, list[dict]]:
        return {table: [] for table in TABLE_BATCH_MAP}

    def _record_entry_point(
        self,
        file_id: int,
        *,
        file_name: str,
        lang: str | None,
        is_test: bool,
        file_bytes: bytes,
    ) -> None:
        if lang != "python" or is_test:
            return
        has_guard = file_has_main_guard(file_bytes)
        is_named = file_name in _NAMED_PYTHON_ENTRY_FILES
        if not has_guard and not is_named:
            self.db.delete_ids("entry_points", [file_id])
            return
        self.db_batches["entry_points"].append(
            {
                "id": file_id,
                "has_main_guard": has_guard,
                "is_named_entry": is_named,
            }
        )

    def cleanup_deleted_file_symbols(self) -> None:
        for file_meta in self.files_snapshot.values():
            if file_meta["seen"] == False:
                file_id = int(file_meta["id"])
                references = self.db.get_symbol_references_snapshot(file_id)
                for reference in references.values():
                    reference["seen"] = False
                self.db.delete_symbol_references(references)
                symbols = self.db.get_symbols_snapshot(file_id)
                for symbol in symbols.values():
                    symbol["seen"] = False
                self.db.delete_symbols(symbols)

                self.class_catalog.drop_file(file_id)

    def cleanup_orphaned_inherited_symbols(self) -> None:
        for qualified_name in self.db.delete_orphaned_inherited_symbols():
            self.class_catalog.drop(qualified_name)

    def _process_files(
        self, file_names: list[str], directory_path: str, dir_rel: str, full: bool
    ) -> None:
        for file_name in file_names:
            self._process_file(file_name, directory_path, dir_rel, full)

    def _insert_batch(self, final: bool = False) -> None:
        if not final and not any(
            len(batch) >= self.db_batch_size for batch in self.db_batches.values()
        ):
            return

        self.db.bulk_insert(self.db_batches)
        self.db_batches = self._new_batches()

    def _bulk_operations(self, now: int, last_incremental: int) -> None:
        self.db.resolve_symbol_references()
        self.db.resolve_imports(now, last_incremental)

    def _reset_run_state(self) -> None:
        self.files_skipped = 0
        self.files_indexed = 0
        for entry in self.directories_snapshot.values():
            entry["seen"] = False
        for entry in self.files_snapshot.values():
            entry["seen"] = False

    def process(self, full: bool = False) -> None:
        with self._lock:
            self._process_unlocked(full)

    def run_query(self, fn: Callable[[CodeDB], T], *, full: bool = False) -> T:
        """Refresh the index then run ``fn`` while holding the processor lock."""
        with self._lock:
            self._process_unlocked(full)
            return fn(self.db)

    def _process_unlocked(self, full: bool = False) -> None:
        self._reset_run_state()
        start_epoch = int(time.time())
        start_time = time.perf_counter()
        root_s = str(self.root)
        for directory_path, directory_names, file_names in os.walk(root_s):
            dir_rel = (
                ""
                if directory_path == root_s
                else os.path.relpath(directory_path, root_s).replace(os.sep, "/")
            )
            directory_names[:] = [
                directory
                for directory in directory_names
                if not relative_path_is_ignored(
                    _join_rel(dir_rel, directory),
                    is_directory=True,
                    spec=self._index_ignore_spec,
                )
            ]
            file_names[:] = [
                file
                for file in file_names
                if not relative_path_is_ignored(
                    _join_rel(dir_rel, file),
                    is_directory=False,
                    spec=self._index_ignore_spec,
                )
            ]

            self._process_directories(directory_names, dir_rel)
            self._process_files(file_names, directory_path, dir_rel, full)

        self.cleanup_deleted_file_symbols()
        self.db.delete_files(self.files_snapshot)
        self.db.delete_directories(self.directories_snapshot)
        self.directories_snapshot = {
            path: meta for path, meta in self.directories_snapshot.items() if meta["seen"]
        }
        self.files_snapshot = {
            path: meta for path, meta in self.files_snapshot.items() if meta["seen"]
        }

        self._insert_batch(final=True)
        self.cleanup_orphaned_inherited_symbols()

        end_epoch = int(time.time())
        if full:
            self.last_full_parse = end_epoch
            self.last_incremental = end_epoch
        else:
            self.last_full_parse = None
            self.last_incremental = end_epoch

        self.db.set_watermark(self.last_full_parse, self.last_incremental)
        self._bulk_operations(start_epoch, self.last_incremental)

        duration_ms = round((time.perf_counter() - start_time) * 1000)
        indexed = (
            f"Indexed {self.files_indexed} files incrementally"
            if not full
            else f"Indexed {self.files_indexed} files"
        )
        print(
            f"{indexed} in {duration_ms}ms (files_skipped: {self.files_skipped})",
            file=sys.stderr,  # NOTE: Print to stderr to avoid interfering with MCP output.
        )
