"""Optional, read-only access to a Microsoft Fabric Lakehouse SQL analytics endpoint.

Configuration comes only from environment variables. No password is ever read or stored:
authentication is Microsoft Entra interactive sign-in through the ODBC driver. Install the
optional dependency with ``pip install -e ".[fabric]"`` and the Microsoft ODBC Driver 18.
"""

from __future__ import annotations

from typing import Any

from .base import BackendUnavailable, Row, assert_read_only


class FabricBackend:
    name = "fabric"
    label = "Fabric SQL analytics endpoint (read-only)"
    read_only = True

    def __init__(self, server: str, database: str, user: str, driver: str) -> None:
        self.server = server
        self.database = database
        self.user = user
        self.driver = driver
        self._connection: Any = None

    def _connection_string(self) -> str:
        missing = [
            name
            for name, value in (
                ("FABRIC_SQL_SERVER", self.server),
                ("FABRIC_SQL_DATABASE", self.database),
                ("FABRIC_USER", self.user),
            )
            if not value
        ]
        if missing:
            raise BackendUnavailable(
                f"Fabric mode needs {', '.join(missing)} in the environment (see .env.example)."
            )
        return (
            f"Driver={{{self.driver}}};Server=tcp:{self.server},1433;"
            f"Database={self.database};Encrypt=yes;TrustServerCertificate=no;"
            f"Authentication=ActiveDirectoryInteractive;UID={self.user};"
            "ApplicationIntent=ReadOnly;Connection Timeout=30"
        )

    def _connect(self) -> Any:
        if self._connection is not None:
            return self._connection
        connection_string = self._connection_string()
        try:
            import pyodbc
        except ImportError as exc:
            raise BackendUnavailable(
                'Fabric mode needs pyodbc: pip install -e ".[fabric]" (and ODBC Driver 18).'
            ) from exc
        try:
            self._connection = pyodbc.connect(connection_string, autocommit=True)
        except pyodbc.Error as exc:
            # The driver message never contains a secret: no password is configured.
            raise BackendUnavailable(
                f"Could not connect to the Fabric SQL analytics endpoint {self.server}: {exc}. "
                "Switch to the DuckDB backend to continue offline."
            ) from exc
        return self._connection

    def query(self, sql: str) -> list[Row]:
        assert_read_only(sql)
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(sql)
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        except Exception as exc:
            self._connection = None
            raise BackendUnavailable(f"Fabric query failed: {exc}") from exc
