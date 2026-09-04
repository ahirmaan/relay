"""Fact extraction via an LLM — local Ollama for dev, a hosted provider for the deployed prototype.

Switch providers with the LLM_PROVIDER env var (default "ollama"). Cloud hosts
can't reach a laptop's localhost:11434, so the deployed instance sets
LLM_PROVIDER=openrouter (or groq) plus that provider's API key instead. Every
provider gets the same prompt and returns the same shape of response, so
app/core.py doesn't know or care which one is active.
"""

import os

import requests

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.2-1b-instruct")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

EXTRACTION_PROMPT = """You are a memory system that breaks raw input into atomic facts — small, self-contained details, not one long summary.

Read the input below and output one line per distinct detail, in the form:
category: content

Rules:
- category is a short lowercase label for what kind of detail this is (e.g. name, feature, decision, constraint, timeline, architecture, preference). Reuse an obvious category rather than inventing an overly specific one-off label.
- content is that single detail, written as a standalone statement (no preamble, no "the user said", no quotes around it).
- Split distinct details into separate lines instead of merging them into one sentence — e.g. the project's name, its type, and each of its features are separate lines, not one run-on line.
- Ignore any part of the input that's just an instruction to save/remember/note something (e.g. "could you save this") — that's a request about what to do with the facts, not a fact itself.
- Don't confuse the name of the memory tool being addressed (e.g. "save this to Relay") with the actual subject being described.
- Never output a line that just quotes or restates the whole raw input back — every line must be one specific, distilled detail, not the input itself.
- A plain question asked BY the user (e.g. "what's the market size of X?", "how does Y work?") contains no fact by itself, output NONE for it — asking about a topic is not a fact about that topic, and you must never invent an answer, a statistic, or a line like "X is unknown" just because a question was asked. Only extract from a question if it directly states or reveals a real detail on its own (e.g. "why did we pick SQLite over Postgres for this" reveals a decision even though it's phrased as a question).
- If there is no clear fact anywhere in the input, output exactly: NONE. This includes greetings and small talk with nothing specific in them ("hey, how's it going?", "thanks!") — don't invent a fact to avoid saying NONE.

Input:
\"\"\"{text}\"\"\"

Facts:"""

REPLY_PROMPT = """You are a helpful AI assistant chatting with a user about a project. Reply naturally and briefly (one or two sentences) to their message below.

Never say or imply that you saved, remembered, stored, or noted anything, whether that actually happens is decided by a separate step you have no visibility into, and claiming it here can be false. If the user asks you to save/remember something, just acknowledge the request itself (e.g. "Got it." / "Noted your request."), don't confirm the outcome.

Then, on a new line, always add one short, relevant follow-up question, even if your reply already felt complete. This is required for every reply, not optional, the only exception is if the user's message is clearly a goodbye. Do not end on a plain statement.

Output only the reply and the question, nothing else, no labels.

User message:
\"\"\"{message}\"\"\"
"""

# A separate yes/no gate before extraction was tried and measured directly
# against this deployment: it missed real content at roughly the same ~40%
# rate extract_facts() itself did on its own (see extract_facts's docstring),
# so it was pure extra latency and cost with no reliability benefit — cut
# rather than kept out of habit. extract_facts()'s own NONE handling plus its
# retry-once-on-empty is what actually carries this now.
#
# Explicit asks to remember something should always be saved, no need to ask
# the model to judge intent when the user already stated it directly. Checked
# after extraction — if it still finds nothing from an explicit ask, chat_turn
# falls back to a single deterministic "note" fact rather than saving nothing.
EXPLICIT_SAVE_TRIGGERS = (
    "save that", "save this", "remember that", "remember this",
    "note that", "note this", "please remember", "please save", "please note",
    "could you save", "can you save", "would you save", "save my",
    "could you remember", "can you remember",
)

# REPLY_PROMPT asks for a follow-up question on every reply, but a 1B-class
# model only complies ~60-70% of the time even with a firmly worded
# instruction, this isn't a wording problem, it's a capability ceiling. Rather
# than keep tuning the prompt, guarantee it deterministically: append a
# generic follow-up whenever the model's reply doesn't already end in one,
# skipping only for a clear goodbye.
FALLBACK_FOLLOWUP = "Anything else on your mind about this?"
FAREWELL_TRIGGERS = (
    "bye", "goodbye", "see you", "talk later", "gtg", "got to go",
    "that's all", "thats all", "nothing else", "no thanks", "no thank you",
)


def _extract_via_ollama(prompt: str, temperature: float) -> str:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            # Ollama defaults to a much higher temperature than this, which
            # made every judgment call here noticeably less consistent
            # locally than the same prompt run against a hosted model.
            "options": {"temperature": temperature},
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["response"].strip()


def _extract_via_chat_api(url: str, api_key: str, model: str, prompt: str, provider_label: str, temperature: float) -> str:
    if not api_key:
        raise RuntimeError(f"LLM_PROVIDER={provider_label} but its API key is not set")
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def _complete(prompt: str, temperature: float = 0.2) -> str:
    if LLM_PROVIDER == "openrouter":
        return _extract_via_chat_api(OPENROUTER_URL, OPENROUTER_API_KEY, OPENROUTER_MODEL, prompt, "openrouter", temperature)
    if LLM_PROVIDER == "groq":
        return _extract_via_chat_api(GROQ_URL, GROQ_API_KEY, GROQ_MODEL, prompt, "groq", temperature)
    return _extract_via_ollama(prompt, temperature)


# Categories the model sometimes emits when it echoes the raw input back as
# a "fact" instead of distilling it (seen in practice: "input: \"\"\"...\"\"\"").
# Blocked outright rather than just asked not to in the prompt — a prompt
# instruction reduces how often this happens, it doesn't guarantee it never
# does, and a fact that's just the whole raw message restated is worse than
# no fact at all.
_META_CATEGORIES = frozenset({"input", "raw", "raw input", "message", "original", "text"})

# Two more shapes of the same underlying problem (inventing an "answer" to a
# question that stated no real fact), each caught directly in testing:
# a bare non-answer as the entire content, and the model leaking its own
# reasoning about why it thinks a non-answer counts. The prompt already says
# not to do either — these exist because it still sometimes did, and a
# fabricated "fact" slipping past a wording fix is worse than a stricter
# filter occasionally dropping something borderline.
_NON_ANSWERS = frozenset({
    "unknown", "n/a", "na", "not specified", "unspecified", "unclear",
    "not available", "tbd", "not sure", "no information", "not provided",
})
_REASONING_LEAK_PHRASES = (
    "the only fact", "can be extracted", "the input is a question",
    "no fact", "no clear fact", "as an ai", "i cannot", "i can't determine",
    "is unknown", "are unknown", "remains unknown", "is not specified", "is unclear",
)


def _parse_facts(raw: str, original_text: str = "") -> list[tuple[str, str]]:
    """Parse EXTRACTION_PROMPT's "category: content" lines into pairs, tolerant
    of minor formatting drift (a stray leading "-" or "*" bullet, blank lines,
    extra whitespace) since even an 8B model doesn't follow a format exactly
    every time.
    """
    raw = raw.strip()
    if not raw or raw.upper().startswith("NONE"):
        return []
    original_normalized = original_text.strip().strip('"').strip().lower()
    facts = []
    for line in raw.splitlines():
        line = line.strip().lstrip("-*•").strip()
        if not line or line.upper() == "NONE" or ":" not in line:
            continue
        category, content = line.split(":", 1)
        category = category.strip().lower()
        content = content.strip().strip('"').strip()
        if not category or not content:
            continue
        if category in _META_CATEGORIES:
            continue
        # a fact that's just the whole input restated verbatim isn't atomic
        if original_normalized and content.lower() == original_normalized:
            continue
        content_lower = content.strip(".").lower()
        if content_lower in _NON_ANSWERS:
            continue
        if any(phrase in content_lower for phrase in _REASONING_LEAK_PHRASES):
            continue
        facts.append((category, content))
    return facts


def extract_facts(text: str) -> list[tuple[str, str]]:
    """Send raw input text to the configured LLM provider and return the
    atomic (category, content) facts it contains — possibly more than one,
    possibly none.

    Retries once if the first attempt comes back empty. Measured directly
    against this deployment: even at temperature=0, the same unambiguous
    input came back NONE roughly 40% of the time on a single call — that's
    inference-level non-determinism from the hosted provider, not something
    prompt wording fixes. One retry on an empty result cuts a false "nothing
    here" down to roughly 15-20% instead of accepting a coin-flip as the
    real answer, at the cost of one extra call only in the empty case.

    The retry is skipped for a plain question ("what's the market size of
    X?"). Also measured directly: a question correctly comes back NONE most
    of the time, but a retry occasionally hallucinated a fake fact like "the
    market size is unknown" out of nothing — exactly the "invented answer to
    a question" failure the prompt already warns against, just reintroduced
    by giving it a second roll of the dice. A real, save-worthy detail
    embedded in a question (see the prompt's own example) still gets caught
    on the first attempt, it doesn't need the retry's help the way genuine
    missed statements do.
    """
    stripped = text.strip()
    is_plain_question = stripped.endswith("?")

    facts = _parse_facts(_complete(EXTRACTION_PROMPT.format(text=text)), original_text=text)
    if not facts and not is_plain_question:
        facts = _parse_facts(_complete(EXTRACTION_PROMPT.format(text=text)), original_text=text)
    return facts


def chat_turn(message: str) -> tuple[str, list[tuple[str, str]]]:
    """Reply to a chat message, and only save something if the user
    explicitly asked to (EXPLICIT_SAVE_TRIGGERS). Returns the reply plus a
    list of (category, content) facts, which is empty unless the message
    contained an explicit ask.

    Auto-detecting "worth remembering" from freeform chat was tried at
    length (see extract_facts's own docstring for the reliability work that
    went into it) and still produced real false positives even after every
    fix, e.g. a plain "hello, who are you?" getting extracted as a fact
    named "Relay" — a save that never should have happened, not a rare
    fluke. Auto-detection's failure mode is invisible until you notice
    something wrong in Memory later; asking the user to say "save this" is
    the deterministic fix, the same reasoning behind EXPLICIT_SAVE_TRIGGERS
    itself, just applied to the whole feature instead of one edge case.
    """
    reply = _complete(REPLY_PROMPT.format(message=message)).strip()

    is_farewell = any(t in message.lower() for t in FAREWELL_TRIGGERS)
    if "?" not in reply and not is_farewell:
        if reply and reply[-1] not in ".!?":
            reply += "."
        reply = (reply + " " + FALLBACK_FOLLOWUP).strip()

    facts: list[tuple[str, str]] = []
    if any(trigger in message.lower() for trigger in EXPLICIT_SAVE_TRIGGERS):
        facts = extract_facts(message)
        if not facts:
            # The user explicitly asked to save something, but extraction
            # still found nothing — don't silently save nothing when the
            # intent was unambiguous. No extra model call, just the raw ask.
            facts = [("note", message.strip())]

    return reply, facts
