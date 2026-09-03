"""Minimal FastAPI surface over Relay's baton-handoff memory logic."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core import add_fact, append_fact, get_chain, get_latest, list_folders, reset_all
from app.db import init_db
from app.llm_client import chat_turn, extract_fact

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
    force_save: bool = False


@app.get("/")
def root():
    """Bare HTML page: chat with an assistant, watch it decide what to remember."""
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/chat")
def chat(payload: ChatIn):
    """Chat turn where the assistant — not the caller — decides what's worth saving.

    This is the demo path: a human sends a normal message, the model replies
    naturally, and separately decides whether the message describes a
    decision worth appending to the session's baton chain. Contrast with
    POST /fact, where the caller explicitly hands over text to extract.

    force_save exists for the dashboard's curated suggestion prompts only —
    text a human already vetted as a genuine decision, not something typed
    live. A 1B-class model's classification of those specific sentences was
    measurably flaky (occasionally NONE on a prompt that's unambiguously a
    decision), so trust the curation over the model for that one case rather
    than leaving it to chance. Freeform typed messages never set this — the
    model still makes the real, unpredictable call there, which is the
    actual point being demonstrated.
    """
    reply, fact = chat_turn(payload.message)
    if payload.force_save and not fact:
        fact = extract_fact(payload.message)
    saved = append_fact(fact, payload.session_id, "assistant") if fact else None
    return {"reply": reply, "saved_fact": saved}


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
    return add_fact(fact.text, fact.session_id, fact.written_by)


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
