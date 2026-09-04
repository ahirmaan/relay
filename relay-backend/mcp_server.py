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

from app.core import add_facts as _add_facts
from app.core import get_chain as _get_chain
from app.core import get_latest as _get_latest
from app.db import init_db

init_db()

mcp = FastMCP("relay")


@mcp.tool()
def relay_add_facts(text: str, session_id: str, written_by: str) -> list[dict]:
    """Break raw text into atomic facts and append each to a session's chain.

    Runs the input through the configured LLM to split it into small,
    self-contained details (e.g. a project's name, type, and each feature as
    separate facts, not one blob), each linked independently to whichever
    prior fact in the same category it actually updates — the same
    append-only handoff the HTTP API performs. Returns an empty list if
    nothing worth remembering was found, which is a valid outcome.

    Args:
        text: Raw input describing one or more decisions or details.
        session_id: Which chain these facts belong to.
        written_by: Name of the model/assistant writing them.
    """
    return _add_facts(text, session_id, written_by)


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
