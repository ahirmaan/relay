"""Core baton-handoff logic: append-only facts, each linked to the most recent
fact it's actually related to — not just whatever came before it in time.
"""

import re
from typing import Optional

from app.db import get_connection
from app.llm_client import extract_fact

# Generic words stripped before comparing facts for a shared topic. Trying an
# LLM to classify/label topics was tested here and rejected: a 1B-class model
# either drifted to a different label for the same topic on repeat runs, or
# blindly copied back whatever existing topic it was shown regardless of fit.
# Plain keyword overlap is deterministic, explainable, and good enough for
# linking "we're using SQLite" to a later "switched from SQLite to Postgres"
# while keeping it separate from an unrelated "switched providers" fact.
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "we", "you", "they", "it", "its",
    "to", "for", "and", "or", "but", "with", "on", "in", "of", "this", "that",
    "these", "those", "our", "us", "be", "been", "being", "will", "would", "should",
    "could", "can", "have", "has", "had", "do", "does", "did", "not", "no", "so",
    "just", "also", "then", "than", "let", "lets", "let's", "going", "use", "used",
    "using", "project", "team", "decided", "decide", "chose", "choose", "switching",
    "switch", "switched", "from", "about", "one", "two", "new", "old", "now",
    "need", "needed", "want", "wanted", "plan", "planning", "make", "making", "made",
})


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+.#]{2,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def append_fact(content: str, session_id: str, written_by: str) -> dict:
    """Insert an already-decided fact, linked to the most recent fact in this
    session that shares a keyword with it — not just the session's latest
    fact overall. A fact about switching database ties back to an earlier
    fact about that same database; an unrelated fact about a hosting
    provider starts its own thread (parent_fact_id = None) instead of
    looking like it grew out of the database decision just because it
    happened next chronologically.

    Used when the caller (e.g. the chat flow, where an assistant decides
    mid-conversation what's worth remembering) already has the fact text and
    doesn't need a separate extraction pass.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, content FROM facts WHERE session_id = %s ORDER BY id DESC",
                (session_id,),
            )
            rows = cur.fetchall()

            new_keywords = _keywords(content)
            parent_fact_id: Optional[int] = None
            if new_keywords:
                for row in rows:
                    if _keywords(row["content"]) & new_keywords:
                        parent_fact_id = row["id"]
                        break

            cur.execute(
                """
                INSERT INTO facts (content, written_by, parent_fact_id, session_id)
                VALUES (%s, %s, %s, %s)
                RETURNING *
                """,
                (content, written_by, parent_fact_id, session_id),
            )
            new_row = cur.fetchone()
        conn.commit()
        return dict(new_row)
    finally:
        conn.close()


def add_fact(text: str, session_id: str, written_by: str) -> dict:
    """Extract a fact from raw text and append it to the session's chain."""
    content = extract_fact(text)
    return append_fact(content, session_id, written_by)


def get_chain(session_id: str) -> list[dict]:
    """Return the full baton chain for a session, oldest to newest."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM facts WHERE session_id = %s ORDER BY id ASC",
                (session_id,),
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_latest(session_id: str) -> Optional[dict]:
    """Return the most recent fact for a session, or None if the session is empty."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM facts WHERE session_id = %s ORDER BY id DESC LIMIT 1",
                (session_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_folders() -> list[dict]:
    """List every session (folder), most recently active first, with a fact count.

    A "folder" is just a session_id, same as everywhere else in this file.
    The dashboard's sidebar calls this so a visitor picks an existing folder
    instead of the model guessing which one a message belongs to.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT session_id, COUNT(*) AS fact_count, MAX(timestamp) AS last_active
                FROM facts
                GROUP BY session_id
                ORDER BY last_active DESC
                """
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def reset_all() -> int:
    """Delete every fact in every folder. Returns how many rows were removed.

    For clearing dev/test data out of a demo instance between runs — there's
    no undo. Not exposed anywhere in the UI on purpose; it's a deliberate
    HTTP call, not a button someone can click by accident.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM facts")
            count = cur.fetchone()["n"]
            cur.execute("DELETE FROM facts")
        conn.commit()
        return count
    finally:
        conn.close()
