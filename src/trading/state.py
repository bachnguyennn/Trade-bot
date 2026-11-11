"""Durable order and risk state in SQLite."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from src.contracts import PaperOrder

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    client_order_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS risk (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class OrderStateStore:
    """Orders keyed by `client_order_id`, which is unique: the basis of duplicate prevention."""

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self._path, check_same_thread=False)
        with self._tx() as cursor:
            cursor.executescript(_SCHEMA)

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cursor = self._connection.cursor()
            try:
                yield cursor
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            finally:
                cursor.close()

    def insert_new(self, order: PaperOrder) -> bool:
        """Insert an order. Returns False, changing nothing, if its id already exists."""
        with self._tx() as cursor:
            cursor.execute(
                "INSERT OR IGNORE INTO orders (client_order_id, created_at, payload) "
                "VALUES (?, ?, ?)",
                (order.client_order_id, order.created_at.isoformat(), order.model_dump_json()),
            )
            return cursor.rowcount == 1

    def update(self, order: PaperOrder) -> None:
        with self._tx() as cursor:
            cursor.execute(
                "UPDATE orders SET payload = ? WHERE client_order_id = ?",
                (order.model_dump_json(), order.client_order_id),
            )

    def get(self, client_order_id: str) -> PaperOrder | None:
        with self._tx() as cursor:
            row = cursor.execute(
                "SELECT payload FROM orders WHERE client_order_id = ?", (client_order_id,)
            ).fetchone()
        return PaperOrder.model_validate_json(row[0]) if row else None

    def list(self) -> list[PaperOrder]:
        with self._tx() as cursor:
            rows = cursor.execute(
                "SELECT payload FROM orders ORDER BY created_at, client_order_id"
            ).fetchall()
        return [PaperOrder.model_validate_json(row[0]) for row in rows]

    def get_value(self, key: str) -> str | None:
        with self._tx() as cursor:
            row = cursor.execute("SELECT value FROM risk WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_value(self, key: str, value: str) -> None:
        with self._tx() as cursor:
            cursor.execute(
                "INSERT INTO risk (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def set_value_if_absent(self, key: str, value: str) -> str:
        """Store a value only if the key is new. Returns the value now stored."""
        with self._tx() as cursor:
            cursor.execute("INSERT OR IGNORE INTO risk (key, value) VALUES (?, ?)", (key, value))
            row = cursor.execute("SELECT value FROM risk WHERE key = ?", (key,)).fetchone()
        return str(row[0])

    def close(self) -> None:
        self._connection.close()
