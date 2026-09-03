"""Relay as an MCP server — lets an AI assistant write and read baton-chain
facts as tools during a live conversation, the same way Torqon-style memory
servers work.

Wraps the exact same app.core functions the HTTP API uses (add_fact,
get_chain, get_latest) — same SQLite table, same append-only linking, same
extraction prompt. This is just a second interface onto identical logic, not
a separate implementation.

Run directly for local testing, or register it as a project MCP server (see
README) so a connected assistant gets these as real tool calls.
"""

from mcp.server.fastmcp import FastMCP

from app.core import add_fact as _add_fact
from app.core import get_chain as _get_chain
from app.core import get_latest as _get_latest
from app.db import init_db

init_db()

mcp = FastMCP("relay")


@mcp.tool()
def relay_add_fact(text: str, session_id: str, written_by: str) -> dict:
    """Extract a fact from raw text and append it to a session's baton chain.

    Runs the input through the configured LLM to distill it into a single
    durable fact, then links it to the session's current latest fact as its
    parent — the same append-only handoff the HTTP API performs.

    Args:
        text: Raw input describing a decision or state change.
        session_id: Which chain this fact belongs to.
        written_by: Name of the model/assistant writing this fact.
    """
    return _add_fact(text, session_id, written_by)


@mcp.tool()
def relay_get_chain(session_id: str) -> list[dict]:
    """Return the full baton chain for a session, oldest to newest."""
    return _get_chain(session_id)


@mcp.tool()
def relay_get_latest(session_id: str) -> dict:
    """Return the most recent fact for a session, or an empty dict if none exist."""
    latest = _get_latest(session_id)
    return latest if latest is not None else {}


if __name__ == "__main__":
    mcp.run()
