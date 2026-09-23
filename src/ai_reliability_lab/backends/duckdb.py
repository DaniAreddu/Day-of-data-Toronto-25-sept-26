"""Local DuckDB replica of the Lakehouse: the offline conference fallback."""

from __future__ import annotations

from pathlib import Path

import duckdb

from .base import BackendUnavailable, Row


class DuckDBBackend:
    name = "duckdb"
    label = "DuckDB local replica (offline, synthetic data)"
    read_only = False

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.is_file()

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Read-write connection used by the local pipeline only."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(self.path))

    def delete(self) -> None:
        for candidate in (self.path, self.path.with_name(self.path.name + ".wal")):
            candidate.unlink(missing_ok=True)

    def query(self, sql: str) -> list[Row]:
        if not self.exists():
            raise BackendUnavailable(
                "The local lakehouse has not been built yet. Use 'Reset Broken Scenario'."
            )
        with duckdb.connect(str(self.path), read_only=True) as con:
            cursor = con.execute(sql)
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
