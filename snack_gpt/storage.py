from dataclasses import dataclass
from pathlib import Path
import sqlite3
from types import TracebackType
from typing import Self


@dataclass(frozen=True)
class StorageHealth:
    schema_version: int
    writable: bool


class Storage:
    def __init__(self, database_path: Path) -> None:
        self._connection = sqlite3.connect(database_path)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._connection.close()

    def initialize(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (1)"
            )

    def health(self) -> StorageHealth:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()
        schema_version = int(row[0]) if row is not None else 0

        writable = True
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.rollback()
        except sqlite3.OperationalError:
            writable = False

        return StorageHealth(schema_version=schema_version, writable=writable)