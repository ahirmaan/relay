"""Minimal FastAPI surface over Relay's baton-handoff memory logic."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
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
    folder: str = "general"


def client_ip(request: Request) -> str:
    """Best-effort real client IP. Behind Vercel (and most proxies/hosts)
    the actual visitor address is in X-Forwarded-For, not request.client,
    which would otherwise just be the proxy's own address."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def scoped_session(ip: str, folder: str) -> str:
    """The dashboard's actual session_id: an IP address plus a folder name
    the visitor picks, e.g. "1.2.3.4::pomodoro-app". Scoping by IP (instead
    of the old browser-localStorage random id) means the same visitor sees
    the same memory across a page refresh or a different browser, as long
    as they're on the same network — the tradeoff is that a shared network
    (an office, a shared hotspot) shares one identity too. Folder is just a
    namespace under that IP, same idea as the old per-category sub-sessions,
    generalized to any name the visitor wants, not a fixed category list.
    """
    return f"{ip}::{folder or 'general'}"


@app.get("/")
def root():
    """Bare HTML page: chat with an assistant, watch it decide what to remember."""
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/chat")
def chat(payload: ChatIn, request: Request):
    """Chat turn where the assistant — not the caller — decides what's worth
    saving, and how many atomic facts (if any) that turns into. Session
    identity is the caller's IP plus the folder they picked, not something
    the client can spoof by sending an arbitrary session_id. Contrast with
    POST /fact, where the caller explicitly hands over text and a raw
    session_id to extract into (used by the MCP server, not the dashboard).
    """
    session_id = scoped_session(client_ip(request), payload.folder)
    reply, facts = chat_turn(payload.message)
    saved = append_facts(facts, session_id, "assistant") if facts else []
    return {"reply": reply, "saved_facts": saved, "folder": payload.folder or "general"}


@app.get("/my-folders")
def my_folders(request: Request):
    """List this visitor's own folders (by IP), most recently active first —
    unlike GET /folders, this never shows another visitor's folder names."""
    prefix = client_ip(request) + "::"
    return [
        {**f, "folder": f["session_id"][len(prefix):]}
        for f in list_folders()
        if f["session_id"].startswith(prefix)
    ]


@app.get("/my-memory/{folder}")
def my_memory(folder: str, request: Request):
    """This visitor's chain for one of their own folders, by IP + folder
    name — the dashboard's read path, mirroring POST /chat's write path."""
    return get_chain(scoped_session(client_ip(request), folder))


@app.get("/folders")
def folders():
    """List every folder (session) across every visitor, most recently
    active first. Not used by the dashboard (see /my-folders); kept for
    direct inspection while testing, e.g. via /docs or curl."""
    return list_folders()


@app.get("/whoami")
def whoami(request: Request):
    """Diagnostic: what IP this dashboard currently sees you as, and the raw
    X-Forwarded-For header it came from. Hit this before and after a refresh
    — if the ip differs, that's a genuinely different session by design (see
    scoped_session's docstring), not a bug losing data."""
    return {
        "ip": client_ip(request),
        "x_forwarded_for_raw": request.headers.get("x-forwarded-for"),
    }


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
