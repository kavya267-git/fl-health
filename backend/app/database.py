"""Database access.

A thin layer over DB-API so the same SQL runs on SQLite (local demo) and on
PostgreSQL (Supabase, via ``DATABASE_URL``). SQL is written with ``:name``
placeholders; JSON, boolean and timestamp columns are encoded and decoded here
so services work with plain Python values.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.models.tables import COLUMN_TYPES, TABLE_COLUMNS, add_column_statements, create_statements

logger = logging.getLogger("fl.database")

_NAMED_PARAM = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")


class DatabaseError(RuntimeError):
    pass


def _encode(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _decode_row(row: Dict[str, Any]) -> Dict[str, Any]:
    decoded = {}
    for key, value in row.items():
        kind = COLUMN_TYPES.get(key)
        if value is None:
            decoded[key] = None
        elif kind == "json" and isinstance(value, str):
            decoded[key] = json.loads(value)
        elif kind == "boolean":
            decoded[key] = bool(value)
        elif isinstance(value, memoryview):
            decoded[key] = bytes(value)
        elif isinstance(value, datetime):
            decoded[key] = value.isoformat()
        else:
            decoded[key] = value
    return decoded


class Database:
    def __init__(self, url: str):
        self.url = url
        self._local = threading.local()
        self._write_lock = threading.RLock()
        if url.startswith("sqlite:///"):
            self.dialect = "sqlite"
            self._sqlite_path = url[len("sqlite:///") :]
            if self._sqlite_path != ":memory:":
                Path(self._sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            self._memory_connection = None
            if self._sqlite_path == ":memory:":
                # One shared connection, serialised by the write lock.
                self._memory_connection = self._open_sqlite(check_same_thread=False)
        elif url.startswith(("postgres://", "postgresql://")):
            self.dialect = "postgres"
        else:
            raise DatabaseError("DATABASE_URL must start with sqlite:///, postgres:// or postgresql://")

    # ---------------------------------------------------------- connections
    def _open_sqlite(self, check_same_thread: bool = True) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._sqlite_path, timeout=30, isolation_level=None, check_same_thread=check_same_thread
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _connection(self):
        if self.dialect == "sqlite" and self._memory_connection is not None:
            return self._memory_connection
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            return connection
        if self.dialect == "sqlite":
            connection = self._open_sqlite()
        else:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise DatabaseError(
                    "A PostgreSQL DATABASE_URL needs the 'psycopg' package: pip install 'psycopg[binary]'"
                ) from exc
            connection = self._connect_postgres(psycopg, dict_row)
        self._local.connection = connection
        return connection

    #: Waits between attempts to reach PostgreSQL. A serverless database (e.g. Neon) that has scaled to zero
    #: takes a few seconds to wake on the first connection.
    CONNECT_RETRY_SECONDS = (1, 2, 4, 8, 15)

    def _connect_postgres(self, psycopg, dict_row):
        last = None
        for wait in (0, *self.CONNECT_RETRY_SECONDS):
            if wait:
                logger.warning("PostgreSQL not reachable yet (%s); retrying in %s s", last.__class__.__name__, wait)
                time.sleep(wait)
            try:
                # prepare_threshold=None: no server-side prepared statements, so the connection also works
                # through a transaction-mode pooler (Neon's pooled URL, Supabase's pooler).
                return psycopg.connect(
                    self.url, autocommit=True, row_factory=dict_row, prepare_threshold=None, connect_timeout=15
                )
            except psycopg.OperationalError as exc:
                last = exc
        raise DatabaseError(f"Cannot connect to PostgreSQL: {last}") from last

    def _sql(self, sql: str) -> str:
        if self.dialect == "postgres":
            return _NAMED_PARAM.sub(r"%(\1)s", sql)
        return sql

    # ------------------------------------------------------------ execution
    def _run(self, sql: str, params: Optional[Dict[str, Any]], fetch: bool, retried: bool = False):
        encoded = {key: _encode(value) for key, value in (params or {}).items()}
        try:
            with self._write_lock:
                cursor = self._connection().execute(self._sql(sql), encoded)
                if fetch:
                    return [_decode_row(dict(row)) for row in cursor.fetchall()]
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise DatabaseError(str(exc)) from exc
        except Exception as exc:  # psycopg errors
            if exc.__class__.__module__.startswith("psycopg"):
                self._local.connection = None  # drop a possibly stale connection; the next call reconnects
                # A pooled connection closed while idle (scale-to-zero, pooler restart): reconnect once and retry.
                # Never inside an explicit transaction: its earlier statements were on the lost connection.
                if (
                    not retried
                    and not getattr(self._local, "in_transaction", False)
                    and exc.__class__.__name__ in ("OperationalError", "InterfaceError")
                ):
                    return self._run(sql, params, fetch, retried=True)
                raise DatabaseError(str(exc)) from exc
            raise

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        return self._run(sql, params, fetch=False)

    def fetch_all(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._run(sql, params, fetch=True)

    def fetch_one(self, sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    # -------------------------------------------------------------- helpers
    def insert(self, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        columns = [c for c in row if c in TABLE_COLUMNS[table]]
        unknown = set(row) - set(columns)
        if unknown:
            raise DatabaseError(f"Unknown columns for {table}: {sorted(unknown)}")
        placeholders = ", ".join(f":{c}" for c in columns)
        sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) RETURNING *"
        return self.fetch_all(sql, {c: row[c] for c in columns})[0]

    def insert_many(self, table: str, rows: Iterable[Dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        columns = list(rows[0].keys())
        sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)})"
        with self.transaction():
            for row in rows:
                self.execute(sql, row)
        return len(rows)

    def update(self, table: str, values: Dict[str, Any], where: Dict[str, Any]) -> int:
        if not values:
            return 0
        assignments = ", ".join(f"{c} = :set_{c}" for c in values)
        conditions = " AND ".join(f"{c} = :where_{c}" for c in where)
        params = {f"set_{c}": v for c, v in values.items()}
        params.update({f"where_{c}": v for c, v in where.items()})
        return self.execute(f"UPDATE {table} SET {assignments} WHERE {conditions}", params)

    @contextmanager
    def transaction(self):
        """Group statements atomically. Holds the process-wide write lock."""
        with self._write_lock:
            connection = self._connection()
            if self.dialect == "sqlite":
                connection.execute("BEGIN IMMEDIATE")
                try:
                    yield
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
            else:
                self._local.in_transaction = True
                try:
                    with connection.transaction():
                        yield
                finally:
                    self._local.in_transaction = False

    def create_schema(self) -> None:
        for statement in create_statements(self.dialect):
            self.execute(statement)
        self.add_missing_columns()

    def add_missing_columns(self) -> None:
        """Add columns that were introduced after a database was created (nullable columns only)."""
        present = self.table_columns()
        for statement in add_column_statements(self.dialect, present):
            self.execute(statement)

    def table_columns(self) -> Dict[str, List[str]]:
        """Actual columns present in the database (used by the privacy checks)."""
        result: Dict[str, List[str]] = {}
        if self.dialect == "sqlite":
            tables = self.fetch_all("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
            for table in tables:
                rows = self.fetch_all(f"PRAGMA table_info({table['name']})")
                result[table["name"]] = [row["name"] for row in rows]
        else:
            rows = self.fetch_all(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
            )
            for row in rows:
                result.setdefault(row["table_name"], []).append(row["column_name"])
        return result

    def close(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None
        if getattr(self, "_memory_connection", None) is not None:
            self._memory_connection.close()
            self._memory_connection = None
