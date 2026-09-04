"""Postgres (Supabase) connection for Relay's append-only facts table.

Moved off SQLite so the same database is reachable from both local dev and
a serverless deploy (Vercel functions have no persistent disk between
invocations, unlike Railway's mounted volume). One DATABASE_URL, same
database everywhere, no more separate local-vs-deployed storage path.
"""

import os

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    written_by TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    parent_fact_id INTEGER REFERENCES facts(id),
    session_id TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general'
);
ALTER TABLE facts ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'general';
"""


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set — point it at your Supabase connection "
            "string (Project Settings -> Database -> Connection string -> "
            "the pooled URI, port 6543)."
        )
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        conn.commit()
    finally:
        conn.close()
