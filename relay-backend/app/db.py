"""SQLite setup for Relay's append-only facts table."""

import os
import sqlite3
from pathlib import Path

_default_path = Path(__file__).resolve().parent.parent / "relay.db"
DB_PATH = Path(os.environ.get("RELAY_DB_PATH", _default_path))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    written_by TEXT NOT NULL,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    parent_fact_id INTEGER REFERENCES facts(id),
    session_id TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.execute(SCHEMA)
        conn.commit()
    finally:
        conn.close()
