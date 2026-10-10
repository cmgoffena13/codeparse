import os
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
from src.parsers.factory import FILE_EXTENSION_MAPPING, ParserFactory

T = TypeVar("T")


def file_path_is_test(relative_path: Path) -> bool:
    """True for conventional test *files*, not packages named ``test``.

    Matches ``tests/`` trees, ``test_*.py``, ``*_test.py``, and ``conftest.py``.
    A segment named ``test`` (e.g. ``sqlmesh/core/test/definition.py``) is not
    enough — that is product code.
    """
    if "tests" in relative_path.parts:
        return True
    name = relative_path.name
    if name == "conftest.py":
        return True
    if name.startswith("test_") and name.endswith(".py"):
        return True
    return name.endswith("_test.py")


class CodeProcessor:
    def __init__(self, db: CodeDB, root: Path):
        self.db = db
        self.assigner = GlobalIDAssigner(db)
        self.root = root.resolve()
        self._index_ignore_spec = path_spec_for_indexing(self.root)
        self.last_full_parse, self.last_incremental = self.db.get_watermark()
        self.db_batch_size = 1000
        self.db_batches: dict[str, list[dict]] = {}
        for table in TABLE_BATCH_MAP:
            self.db_batches[table] = []

        self.files_skipped: int = 0
        self.files_indexed: int = 0
        # One SQLite connection + mutable snapshots: serialize index + reads.
        self._lock = threading.RLock()

        self.directories_snapshot = self.db.get_directories_snapshot()
        self.files_snapshot = self.db.get_files_snapshot()

    def _process_directories(self, directory_names: list[str], directory_path: Path) -> None:
        for directory_name in directory_names:
            directory_relative_path = (directory_path / directory_name).relative_to(self.root)
            if directory_relative_path in self.directories_snapshot:
                self.directories_snapshot[directory_relative_path]["seen"] = True
                continue

            # NOTE: Assign a new ID for the directory.
            directory_id = self.assigner.reserve("directories", 1)[0]
            parent_row = self.directories_snapshot.get(directory_relative_path.parent)
            parent_id = None if parent_row is None else parent_row["id"]
            depth = len(directory_relative_path.parts) - 1
            self.db_batches["directories"].append(
                {
                    "id": directory_id,
                    "parent_id": parent_id,
                    "name": directory_name,
                    "path": str(directory_relative_path),
                    "depth": depth,
                }
            )
            self.directories_snapshot[directory_relative_path] = {
                "id": directory_id,
                "seen": True,
            }

    def _normalize_path(self, path: Path, language: str | None = None) -> str:
        posix = path.with_suffix("").as_posix().lower()
        if language == "python":
            posix = posix.replace("/", ".")
            posix = posix.removesuffix(".__init__")
        return posix

    def _process_file(self, file_name: str, directory_path: Path, full: bool) -> None:
        file_path = directory_path / file_name
        file_relative_path = file_path.relative_to(self.root)
        file_last_modified = file_path.lstat().st_mtime
        file_extension = file_relative_path.suffix

        if not file_extension and not file_path.is_file():
            return

        dir_path = file_path.parent.relative_to(self.root)
        directory_id = None if str(dir_path) == "." else self.directories_snapshot[dir_path]["id"]

        existed = file_relative_path in self.files_snapshot
        if existed:
            file_id = self.files_snapshot[file_relative_path]["id"]
            prior_hash = self.files_snapshot[file_relative_path]["content_hash"]
            prior_symbol_count = self.files_snapshot[file_relative_path]["symbol_count"]
        else:
            file_id = self.assigner.reserve("files", 1)[0]
            prior_hash = None
            prior_symbol_count = 0

        try:
            file_bytes = file_path.read_bytes()
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
            "path": str(file_relative_path),
            "normalized_path": self._normalize_path(file_relative_path, language=lang),
            "language": lang,
            "content_hash": file_hash,
            "line_count": line_count,
            "symbol_count": prior_symbol_count,
            "is_test": is_test,
        }
        if not existed or prior_hash != file_hash:
            self.db_batches["files"].append(file_row)
        snap = {
            "id": file_id,
            "directory_id": directory_id,
            "seen": True,
            "content_hash": file_hash,
            "line_count": line_count,
            "symbol_count": prior_symbol_count,
            "is_test": is_test,
        }
        self.files_snapshot[file_relative_path] = snap

        # NOTE: Two Gateway Checks for parsing: 1. Time 2. Content Hash.
        if full or (file_last_modified > self.last_incremental and file_hash != prior_hash):
            if file_extension not in FILE_EXTENSION_MAPPING:
                self.files_skipped += 1
                return

            parser = ParserFactory.get_parser(
                FILE_EXTENSION_MAPPING[file_extension], self.assigner, self.db
            )
            module_qn = (
                self._normalize_path(file_relative_path, language=lang) if lang == "python" else ""
            )
            is_package = lang == "python" and file_name == "__init__.py"
            symbols, imports, references = parser.parse(
                file_id, file_bytes, module_qn=module_qn, is_package=is_package
            )
            n = len(symbols)
            file_row["symbol_count"] = n
            snap["symbol_count"] = n
            self.db_batches["symbols"].extend(symbols)
            self.db_batches["imports"].extend(imports)
            self.db_batches["symbol_references"].extend(references)
            self.files_indexed += 1
            self._insert_batch()

    def _process_files(self, file_names: list[str], directory_path: Path, full: bool) -> None:
        for file_name in file_names:
            self._process_file(file_name, directory_path, full)

    def _insert_batch(self, final: bool = False) -> None:
        if not final and not any(
            len(batch) >= self.db_batch_size for batch in self.db_batches.values()
        ):
            return

        self.db.bulk_insert(self.db_batches)
        self.db_batches = {}
        for table in TABLE_BATCH_MAP:
            self.db_batches[table] = []

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
        start_time = time.time()
        for directory_path, directory_names, file_names in os.walk(self.root):
            directory_path = Path(directory_path)
            directory_names[:] = [
                directory
                for directory in directory_names
                if not relative_path_is_ignored(
                    (directory_path / directory).relative_to(self.root),
                    is_directory=True,
                    spec=self._index_ignore_spec,
                )
            ]
            file_names[:] = [
                file
                for file in file_names
                if not relative_path_is_ignored(
                    (directory_path / file).relative_to(self.root),
                    is_directory=False,
                    spec=self._index_ignore_spec,
                )
            ]

            self._process_directories(directory_names, directory_path)
            self._process_files(file_names, directory_path, full)

        self.db.delete_files(self.files_snapshot)
        self.db.delete_directories(self.directories_snapshot)
        self.directories_snapshot = {
            path: meta for path, meta in self.directories_snapshot.items() if meta["seen"]
        }
        self.files_snapshot = {
            path: meta for path, meta in self.files_snapshot.items() if meta["seen"]
        }

        self._insert_batch(final=True)

        time_now = time.time()
        end_epoch = int(time_now)
        if full:
            self.last_full_parse = end_epoch
            self.last_incremental = end_epoch
        else:
            self.last_full_parse = None
            self.last_incremental = end_epoch

        self.db.set_watermark(self.last_full_parse, self.last_incremental)
        self._bulk_operations(start_epoch, self.last_incremental)

        duration = time_now - start_time
        duration_ms = duration * 1000
        indexed = (
            f"Indexed {self.files_indexed} files incrementally"
            if not full
            else f"Indexed {self.files_indexed} files"
        )
        print(
            f"{indexed} in {duration_ms:.2f} ms (files_skipped: {self.files_skipped})",
            file=sys.stderr,  # NOTE: Print to stderr to avoid interfering with MCP output.
        )
