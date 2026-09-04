"""Minimal FastAPI surface over Relay's baton-handoff memory logic."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core import add_facts, append_facts, get_chain, get_latest, list_folders, reset_all
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
    session_id: str


@app.get("/")
def root():
    """Bare HTML page: chat with an assistant, watch it decide what to remember."""
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/chat")
def chat(payload: ChatIn):
    """Chat turn where the assistant — not the caller — decides what's worth
    saving, and how many atomic facts (if any) that turns into. Contrast with
    POST /fact, where the caller explicitly hands over text to extract.
    """
    reply, facts = chat_turn(payload.message)
    saved = append_facts(facts, payload.session_id, "assistant") if facts else []
    return {"reply": reply, "saved_facts": saved}


@app.get("/folders")
def folders():
    """List existing folders (sessions), most recently active first, for the sidebar."""
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
    """Wipe every fact in every folder. Not linked from the UI on purpose —
    a deliberate call, for clearing dev/test data between demo runs."""
    deleted = reset_all()
    return {"deleted": deleted}
