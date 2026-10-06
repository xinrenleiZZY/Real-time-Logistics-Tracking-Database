"""SQLite 数据访问（物流追踪实时库）"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from app.config import settings

_write_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS shipment_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id      TEXT NOT NULL,
    asin             TEXT NOT NULL,
    product_name     TEXT NOT NULL DEFAULT '',
    quantity         TEXT NOT NULL DEFAULT '',
    channel          TEXT NOT NULL DEFAULT '',
    tracking_numbers TEXT NOT NULL DEFAULT '',
    sailing_date     TEXT,
    eta_date         TEXT,
    inspection       TEXT NOT NULL DEFAULT '',
    source_file      TEXT NOT NULL DEFAULT '',
    first_seen_at    TEXT NOT NULL,
    last_updated_at  TEXT NOT NULL,
    UNIQUE (shipment_id, asin)
);
CREATE INDEX IF NOT EXISTS idx_shipment_items_asin
    ON shipment_items (asin);
CREATE INDEX IF NOT EXISTS idx_shipment_items_eta
    ON shipment_items (eta_date);
CREATE INDEX IF NOT EXISTS idx_shipment_items_shipment
    ON shipment_items (shipment_id);

-- 物流表原始行历史：每次 Excel 导入 / JSON 推送都追加一行，不做覆盖
CREATE TABLE IF NOT EXISTS logistics_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id      TEXT NOT NULL,
    asin             TEXT NOT NULL,
    product_name     TEXT NOT NULL DEFAULT '',
    quantity         TEXT NOT NULL DEFAULT '',
    channel          TEXT NOT NULL DEFAULT '',
    tracking_numbers TEXT NOT NULL DEFAULT '',
    sailing_date     TEXT,
    eta_date         TEXT,
    inspection       TEXT NOT NULL DEFAULT '',
    source_file      TEXT NOT NULL DEFAULT '',
    capture_at       TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_asin
    ON logistics_history (asin);
CREATE INDEX IF NOT EXISTS idx_history_shipment
    ON logistics_history (shipment_id);
CREATE INDEX IF NOT EXISTS idx_history_eta
    ON logistics_history (eta_date);
CREATE INDEX IF NOT EXISTS idx_history_source
    ON logistics_history (source_file);

CREATE TABLE IF NOT EXISTS import_batches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL DEFAULT 'excel',
    batch_id    TEXT,
    source      TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running',
    total       INTEGER NOT NULL DEFAULT 0,
    inserted    INTEGER NOT NULL DEFAULT 0,
    updated     INTEGER NOT NULL DEFAULT 0,
    skipped     INTEGER NOT NULL DEFAULT 0,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS push_batches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    push_id     TEXT NOT NULL,
    source      TEXT NOT NULL,
    received_at TEXT NOT NULL,
    total       INTEGER NOT NULL DEFAULT 0,
    inserted    INTEGER NOT NULL DEFAULT 0,
    updated     INTEGER NOT NULL DEFAULT 0,
    rejected    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source, push_id)
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_schema() -> None:
    import os

    db_dir = os.path.dirname(os.path.abspath(settings.db_path))
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with _write_lock, connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('arrival_offset_days', ?) "
            "ON CONFLICT(key) DO NOTHING",
            (str(settings.arrival_offset_days),),
        )


def execute(sql: str, *params: Any) -> int:
    if len(params) == 1 and isinstance(params[0], (list, tuple)):
        params = tuple(params[0])
    with _write_lock, connect() as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount


def fetchone(sql: str, *params: Any) -> Optional[dict]:
    if len(params) == 1 and isinstance(params[0], (list, tuple)):
        params = tuple(params[0])
    with connect() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def fetchall(sql: str, *params: Any) -> list[dict]:
    if len(params) == 1 and isinstance(params[0], (list, tuple)):
        params = tuple(params[0])
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    with _write_lock, connect() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
