"""Minimal FastAPI surface over Relay's baton-handoff memory logic."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core import add_facts, append_facts, get_chain, get_latest, list_folders, reset_all, reset_session
from app.db import init_db
from app.llm_client import chat_turn

app = FastAPI(title="Relay")

init_db()

STATIC_DIR = Path(__file__).resolve().parent / "static"


class FactIn(BaseModel):
    text: str
    session_id: str
    written_by: str


class ChatIn(BaseModel):
    message: str
    folder: str = "general"
    client_id: str


def scoped_session(client_id: str, folder: str) -> str:
    """The dashboard's actual session_id: a stable id the browser generates
    once and stores in localStorage, plus a folder name the visitor picks,
    e.g. "9f3a2c1b::pomodoro-app".

    This used to be the caller's IP address instead of a stored client id.
    Switched after a real, reported bug: a visitor's facts appeared to
    vanish when switching folders, and it couldn't be reproduced under
    stable-IP testing no matter how fast folders were switched — pointing at
    the visitor's actual IP not being stable request-to-request (common on
    mobile data, some Wi-Fi, corporate NAT), which silently changes identity
    on every single request, not just across a refresh. A browser-stored id
    doesn't have that failure mode; the tradeoff is it resets if the visitor
    clears site data or switches browsers, same as any localStorage-based
    approach. Folder is a namespace under that id, same idea as the old
    per-category sub-sessions, generalized to any name the visitor wants.
    """
    return f"{client_id}::{folder or 'general'}"


@app.get("/")
def root():
    """Bare HTML page: chat with an assistant, watch it decide what to remember."""
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/chat")
def chat(payload: ChatIn):
    """Chat turn where the assistant — not the caller — decides what's worth
    saving, and how many atomic facts (if any) that turns into. Session
    identity is the browser's stored client_id plus the folder picked, not
    something guessable/spoofable in a meaningful way since it's just a
    random id nobody else has. Contrast with POST /fact, where the caller
    explicitly hands over text and a raw session_id to extract into (used by
    the MCP server, not the dashboard).

    Also fetches this folder's existing chain first and hands it to
    chat_turn as context, so "what did I save about X" or "fetch Y from
    memory" can actually be answered — this used to be write-only, the
    reply had no visibility into anything already saved.
    """
    session_id = scoped_session(payload.client_id, payload.folder)
    existing = get_chain(session_id)
    memory_context = "\n".join(f"{f['category']}: {f['content']}" for f in existing)
    reply, facts = chat_turn(payload.message, memory_context=memory_context)
    saved = append_facts(facts, session_id, "assistant") if facts else []
    return {"reply": reply, "saved_facts": saved, "folder": payload.folder or "general"}


@app.get("/my-folders")
def my_folders(client_id: str):
    """List this visitor's own folders (by client_id), most recently active
    first — unlike GET /folders, this never shows another visitor's folder
    names."""
    prefix = client_id + "::"
    return [
        {**f, "folder": f["session_id"][len(prefix):]}
        for f in list_folders()
        if f["session_id"].startswith(prefix)
    ]


@app.get("/my-memory/{folder}")
def my_memory(folder: str, client_id: str):
    """This visitor's chain for one of their own folders, by client_id +
    folder name — the dashboard's read path, mirroring POST /chat's write
    path."""
    return get_chain(scoped_session(client_id, folder))


@app.delete("/my-memory/{folder}")
def delete_my_memory(folder: str, client_id: str):
    """Wipe just this visitor's one folder — scoped, unlike DELETE /reset
    below which wipes every visitor's data. Prefer this for clearing test
    data on a live, shared deployment."""
    deleted = reset_session(scoped_session(client_id, folder))
    return {"deleted": deleted}


@app.get("/folders")
def folders():
    """List every folder (session) across every visitor, most recently
    active first. Not used by the dashboard (see /my-folders); kept for
    direct inspection while testing, e.g. via /docs or curl."""
    return list_folders()


@app.get("/info")
def info():
    return {
        "service": "Relay",
        "description": "Append-only, layered AI memory — baton handoff backend prototype",
        "endpoints": ["POST /fact", "GET /chain/{session_id}", "GET /latest/{session_id}"],
        "docs": "/docs",
    }


@app.post("/fact")
def post_fact(fact: FactIn):
    """Extract whatever atomic facts are in the given text and append them
    all. Returns a list — possibly more than one fact, possibly empty."""
    return add_facts(fact.text, fact.session_id, fact.written_by)


@app.get("/chain/{session_id}")
def get_chain_endpoint(session_id: str):
    return get_chain(session_id)


@app.get("/latest/{session_id}")
def get_latest_endpoint(session_id: str):
    latest = get_latest(session_id)
    if latest is None:
        raise HTTPException(status_code=404, detail="No facts for this session")
    return latest


@app.delete("/reset")
def reset():
    """Wipe every fact for every visitor, globally. Not linked from the UI
    on purpose. Prefer DELETE /my-memory/{folder} instead on any deployment
    with real visitors — this one has real collateral-damage risk, it can
    silently delete someone else's live session, not just your own test
    data."""
    deleted = reset_all()
    return {"deleted": deleted}
