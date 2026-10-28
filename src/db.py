import sqlite3
from pathlib import Path
from typing import Any

from src.utils import db_path_for_index_root, get_code_parse_config_dir

TABLE_BATCH_MAP = {
    "directories",
    "files",
    "symbols",
    "imports",
    "symbol_references",
    "entry_points",
}


def index_workspace_paths() -> list[tuple[Path, Path]]:
    """``(db file, workspace path)`` for each index that recorded a root."""
    records: list[tuple[Path, Path]] = []
    for db_file in sorted(get_code_parse_config_dir("indexes").glob("*.db")):
        connection = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        try:
            row = connection.execute("SELECT path FROM index_root WHERE id = 1").fetchone()
        except sqlite3.OperationalError:
            continue
        finally:
            connection.close()
        if row is not None and row[0]:
            records.append((db_file, Path(row[0])))
    return records


def remove_index_files() -> None:
    for db_file in sorted(get_code_parse_config_dir("indexes").glob("*.db")):
        db_file.unlink(missing_ok=True)
        db_file.with_suffix(".db-wal").unlink(missing_ok=True)
        db_file.with_suffix(".db-shm").unlink(missing_ok=True)
    print("Removed all index files.")


class CodeDB:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.db_file = db_path_for_index_root(self.root)
        self.connection = sqlite3.connect(str(self.db_file), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection_closed = False
        self._apply_schema()
        self._store_index_root()

    def _store_index_root(self) -> None:
        self.exec_tran(
            "INSERT OR REPLACE INTO index_root (id, path) VALUES (1, ?)",
            (str(self.root),),
        )

    def _script(self, name: str) -> None:
        path = Path(__file__).resolve().parent / name
        self.connection.executescript(path.read_text(encoding="utf-8"))

    def _apply_schema(self):
        self._script("schema.sql")

    def recreate_schema(self) -> None:
        """Drop every index table, then create them again from ``schema.sql``."""
        self._script("drop_schema.sql")
        self._apply_schema()
        self._store_index_root()

    def exec_tran(self, query: str, params: tuple) -> None:
        try:
            self.connection.execute(query, params)
            self.connection.commit()
        except sqlite3.Error:
            self.connection.rollback()
            raise

    def delete_ids(self, table: str, ids: list[int]) -> None:
        if not ids:
            return
        if table not in TABLE_BATCH_MAP:
            raise ValueError(f"unsupported table for delete_ids: {table}")
        placeholders = ",".join(["?"] * len(ids))
        query = f"DELETE FROM {table} WHERE id IN ({placeholders})"  # noqa: S608
        self.exec_tran(query, tuple(ids))

    def table_max_id(self, table: str) -> int:
        q = f"SELECT COALESCE(MAX(id), 0) AS max_id FROM {table}"  # noqa: S608
        return int(self.connection.execute(q).fetchone()["max_id"])

    def get_watermark(self) -> tuple[int, int]:
        row = self.connection.execute(
            "SELECT last_full_parse, last_incremental FROM watermarks WHERE id = 1"
        ).fetchone()
        return row["last_full_parse"], row["last_incremental"]

    def set_watermark(self, last_full_parse: int | None, last_incremental: int) -> None:
        if last_full_parse is not None:
            query = "UPDATE watermarks SET last_full_parse = ?, last_incremental = ? WHERE id = 1"
            params = (last_full_parse, last_incremental)
        else:
            query = "UPDATE watermarks SET last_incremental = ? WHERE id = 1"
            params = (last_incremental,)
        self.exec_tran(query, params)

    def get_directories_snapshot(self) -> dict[Path, dict[str, Any]]:
        cursor = self.connection.execute("SELECT id, path FROM directories")
        return {Path(row["path"]): {"id": row["id"], "seen": False} for row in cursor}

    def delete_directories(self, directories: dict[Path, dict[str, Any]]) -> None:
        dir_ids = [d["id"] for d in directories.values() if not d["seen"]]
        self.delete_ids("directories", dir_ids)

    def get_files_snapshot(self) -> dict[Path, dict[str, Any]]:
        cursor = self.connection.execute(
            "SELECT id, directory_id, path, content_hash, line_count, "
            "symbol_count, is_test FROM files"
        )
        return {
            Path(row["path"]): {
                "id": row["id"],
                "directory_id": row["directory_id"],
                "seen": False,
                "content_hash": row["content_hash"],
                "line_count": row["line_count"],
                "symbol_count": row["symbol_count"],
                "is_test": bool(row["is_test"]),
            }
            for row in cursor
        }

    def delete_files(self, files: dict[Path, dict[str, Any]]) -> None:
        file_ids = [int(file["id"]) for file in files.values() if not file["seen"]]
        if file_ids:
            placeholders = ",".join("?" for _ in file_ids)
            parameters = tuple(file_ids)
            with self.connection:
                self.connection.execute(
                    f"""
                    DELETE FROM symbols_fts
                    WHERE rowid IN (SELECT id FROM symbols WHERE file_id IN ({placeholders}))
                    """,  # noqa: S608
                    parameters,
                )
                self.connection.execute(
                    f"DELETE FROM entry_points WHERE id IN ({placeholders})",  # noqa: S608
                    parameters,
                )
                self.connection.execute(
                    f"DELETE FROM imports WHERE file_id IN ({placeholders})",  # noqa: S608
                    parameters,
                )
                self.connection.execute(
                    f"DELETE FROM files WHERE id IN ({placeholders})",  # noqa: S608
                    parameters,
                )

    def get_symbols_snapshot(self, file_id: int) -> dict[tuple[str, str], dict[str, Any]]:
        # NOTE: combine symbol_bases and symbols into a single query
        query = """
            SELECT
                s.id,
                s.qualified_name AS name,
                s.kind,
                s.line_start,
                s.line_end,
                sb.base_qualified_name
            FROM symbols AS s
            LEFT JOIN symbol_bases AS sb
                ON sb.symbol_id = s.id
            WHERE s.file_id = ?
            ORDER BY s.id, sb.base_qualified_name
            """
        rows = self.connection.execute(query, (file_id,)).fetchall()
        by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row["name"], row["kind"])
            entry: dict[str, Any] | None = by_key.get(key)
            if entry is None:
                entry = {
                    "id": row["id"],
                    "line_start": row["line_start"],
                    "line_end": row["line_end"],
                    "base_qualified_names": [],
                    "seen": False,
                }
                by_key[key] = entry
            base_qn = row["base_qualified_name"]
            if base_qn:
                names: list[str] = entry["base_qualified_names"]
                names.append(base_qn)
        return {
            key: {
                **entry,
                "base_qualified_names": tuple(entry["base_qualified_names"]),
            }
            for key, entry in by_key.items()
        }

    def delete_orphaned_inherited_symbols(self) -> list[str]:
        rows = list(
            self.connection.execute(
                """
                SELECT
                    inherited.id AS inherited_id,
                    inherited.qualified_name AS inherited_qualified_name
                FROM symbols AS inherited
                WHERE inherited.is_inherited = 1
                    AND NOT EXISTS (
                        SELECT 
                        1 
                        FROM symbols AS parent 
                        WHERE parent.id = inherited.parent_id
                    )
                """
            )
        )
        snapshot = {
            (row["inherited_qualified_name"], str(row["inherited_id"])): {
                "id": int(row["inherited_id"]),
                "seen": False,
            }
            for row in rows
        }
        names = [row["inherited_qualified_name"] for row in rows]
        self.delete_symbols(snapshot)
        return names

    def delete_symbols(self, symbols_snapshot: dict[tuple[str, str], dict[str, Any]]) -> None:
        symbol_ids = [symbol["id"] for symbol in symbols_snapshot.values() if not symbol["seen"]]
        if not symbol_ids:
            return
        with self.connection:
            ids_placeholder = ",".join(["?"] * len(symbol_ids))
            self.connection.execute(
                f"DELETE FROM symbol_bases WHERE symbol_id IN ({ids_placeholder})",  # noqa: S608
                symbol_ids,
            )
            self.connection.execute(
                f"DELETE FROM symbols WHERE id IN ({ids_placeholder})",  # noqa: S608
                symbol_ids,
            )
            self.connection.execute(
                f"DELETE FROM symbols_fts WHERE rowid IN ({ids_placeholder})",  # noqa: S608
                symbol_ids,
            )

    def get_symbol_references_snapshot(
        self, file_id: int
    ) -> dict[tuple[str, str, int, int], dict[str, Any]]:
        query = """
        SELECT
        id,
        ref_symbol_qualified_name AS name,
        ref_kind,
        source_line,
        source_column,
        source_symbol_id,
        context
        FROM symbol_references
        WHERE source_file_id = ?
        """
        cursor = self.connection.execute(query, (file_id,))
        return {
            (row["name"], row["ref_kind"], row["source_line"], row["source_column"]): {
                "id": row["id"],
                "source_line": row["source_line"],
                "source_column": row["source_column"],
                "source_symbol_id": row["source_symbol_id"],
                "context": row["context"],
                "seen": False,
            }
            for row in cursor
        }

    def delete_symbol_references(
        self,
        symbol_references_snapshot: dict[tuple[str, str, int, int], dict[str, Any]],
    ) -> None:
        symbol_reference_ids = [
            symbol_reference["id"]
            for symbol_reference in symbol_references_snapshot.values()
            if not symbol_reference["seen"]
        ]
        self.delete_ids("symbol_references", symbol_reference_ids)

    def get_imports_snapshot(self, file_id: int) -> dict[tuple[str, str], dict[str, Any]]:
        query = """
        SELECT
        id,
        import_path,
        imported_symbol,
        line_number
        FROM imports
        WHERE file_id = ?
        """
        cursor = self.connection.execute(query, (file_id,))
        return {
            (row["import_path"], row["imported_symbol"]): {
                "id": row["id"],
                "line_number": row["line_number"],
                "seen": False,
            }
            for row in cursor
        }

    def delete_imports(self, imports_snapshot: dict[tuple[str, str], dict[str, Any]]) -> None:
        import_ids = [i["id"] for i in imports_snapshot.values() if not i["seen"]]
        self.delete_ids("imports", import_ids)

    def bulk_insert(self, db_batches: dict[str, list[dict[str, Any]]]) -> None:
        directories = db_batches["directories"]
        files = db_batches["files"]
        entry_points = db_batches["entry_points"]
        symbols = db_batches["symbols"]
        symbol_references = db_batches["symbol_references"]
        imports = db_batches["imports"]
        with self.connection:
            self.connection.executemany(
                """
                INSERT INTO directories
                (id, parent_id, name, path, depth)
                VALUES (:id, :parent_id, :name, :path, :depth)
                """,
                directories,
            )

            self.connection.executemany(
                """
                INSERT OR REPLACE INTO files
                (id, directory_id, name, path, normalized_path, language,
                 content_hash, line_count, symbol_count, is_test)
                VALUES (:id, :directory_id, :name, :path, :normalized_path,
                        :language, :content_hash, :line_count, :symbol_count,
                        :is_test)
                """,
                files,
            )

            self.connection.executemany(
                """
                INSERT OR REPLACE INTO entry_points (id, has_main_guard, is_named_entry)
                VALUES (:id, :has_main_guard, :is_named_entry)
                """,
                entry_points,
            )

            base_rows: list[dict[str, Any]] = []
            for symbol in symbols:
                for base_qn in symbol.pop("base_qualified_names", ()):
                    base_rows.append(
                        {
                            "symbol_id": symbol["id"],
                            "base_qualified_name": base_qn,
                        }
                    )

            self.connection.executemany(
                """
                INSERT OR REPLACE INTO symbols
                (id, file_id, parent_id, name, parent, qualified_name, kind, line_start,
                 line_end, line_count, signature, docstring, modifiers, language,
                 is_test, is_inherited)
                VALUES (:id, :file_id, :parent_id, :name, :parent, :qualified_name, :kind,
                        :line_start, :line_end, :line_count, :signature,
                        :docstring, :modifiers, :language, :is_test, :is_inherited)
                """,
                symbols,
            )
            if symbols:
                symbol_ids = [symbol["id"] for symbol in symbols]
                placeholder = ",".join(["?"] * len(symbol_ids))
                self.connection.execute(
                    f"DELETE FROM symbol_bases WHERE symbol_id IN ({placeholder})",  # noqa: S608
                    symbol_ids,
                )
            if base_rows:
                self.connection.executemany(
                    """
                    INSERT INTO symbol_bases (base_qualified_name, symbol_id)
                    VALUES (:base_qualified_name, :symbol_id)
                    """,
                    base_rows,
                )

            fts_symbols = [
                (
                    s["id"],
                    s["name"],
                    s["parent"],
                )
                for s in symbols
            ]
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO symbols_fts
                (rowid, name, parent)
                VALUES (?, ?, ?)
                """,
                fts_symbols,
            )

            self.connection.executemany(
                """
                INSERT INTO symbol_references_staging
                (id, ref_symbol_name, ref_symbol_qualified_name, source_file_id,
                 source_symbol_id, source_line, source_column, ref_kind, context)
                VALUES (:id, :ref_symbol_name, :ref_symbol_qualified_name,
                        :source_file_id, :source_symbol_id, :source_line,
                        :source_column, :ref_kind, :context)
                """,
                symbol_references,
            )

            self.connection.executemany(
                """
                INSERT OR REPLACE INTO imports
                (id, file_id, import_path, imported_symbol, alias, line_number,
                 import_type, import_scope, signature)
                VALUES (:id, :file_id, :import_path, :imported_symbol, :alias,
                        :line_number, :import_type, :import_scope, :signature)
                """,
                imports,
            )

    def resolve_symbol_references(self) -> None:
        with self.connection:
            self.connection.execute("""
            INSERT INTO symbol_references
            (id, ref_symbol_id, ref_symbol_file_id, ref_symbol_name,
             ref_symbol_qualified_name, source_file_id, source_symbol_id,
             source_line, source_column, ref_kind, context)
            SELECT
            s.id,
            sy.id AS ref_symbol_id,
            sy.file_id AS ref_symbol_file_id,
            s.ref_symbol_name,
            s.ref_symbol_qualified_name,
            s.source_file_id,
            s.source_symbol_id,
            s.source_line,
            s.source_column,
            s.ref_kind,
            s.context
            FROM symbol_references_staging AS s
            INNER JOIN symbols AS sy
                ON s.ref_symbol_qualified_name = sy.qualified_name
            WHERE NOT EXISTS (SELECT 1 FROM symbol_references AS sr WHERE sr.id = s.id);
            """)
            self.connection.execute("DELETE FROM symbol_references_staging;")

    def resolve_imports(self, now: int, last_incremental: int) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE imports
                SET imported_file_id = f.id,
                    watermark = ?
                FROM files AS f
                WHERE f.normalized_path = imports.import_path
                    AND imports.watermark BETWEEN ? AND ?
                """,
                (last_incremental, now, last_incremental),
            )

    def close(self):
        if not self.connection_closed:
            self.connection.close()
            self.connection_closed = True

    def __del__(self):
        if not getattr(self, "connection_closed", True):
            conn = getattr(self, "connection", None)
            if conn is not None:
                conn.close()
            self.connection_closed = True
