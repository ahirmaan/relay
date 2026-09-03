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

EXTRACTION_PROMPT = """You are a memory system that distills raw input into a single durable fact.

Read the input below and summarize the key decision or state change it describes in one or two concise sentences. Write it as a standalone statement of fact (no preamble, no "the user said", no quotes around it). If the input contains no clear decision or state change, summarize its most important takeaway the same way.

Input:
\"\"\"{text}\"\"\"

Fact:"""

REPLY_PROMPT = """You are a helpful AI assistant chatting with a user about a project. Reply naturally and briefly (one or two sentences) to their message below.

Then, on a new line, always add one short, relevant follow-up question, even if your reply already felt complete. This is required for every reply, not optional, the only exception is if the user's message is clearly a goodbye. Do not end on a plain statement.

Output only the reply and the question, nothing else, no labels.

User message:
\"\"\"{message}\"\"\"
"""

DECISION_PROMPT = """Read the message below. If it describes or proposes a concrete decision or state change (for example "we chose X over Y", "switched from A to B", "decided to ship Z", "let's use X instead of Y", "going with X for this"), respond with that decision distilled into one standalone sentence. If it is just a question, greeting, or small talk with no decision in it, respond with exactly: NONE

Message:
\"\"\"{message}\"\"\"

Response:"""

# Explicit asks to remember something should always be saved, no need to ask
# a small model to judge intent when the user already stated it directly.
# Checked before the DECISION_PROMPT call, not folded into it, because
# combining "classify AND handle this special case" into one instruction
# made small models misfire on ordinary messages (see chat_turn).
EXPLICIT_SAVE_TRIGGERS = (
    "save that", "save this", "remember that", "remember this",
    "note that", "note this", "please remember", "please save", "please note",
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


def _extract_via_ollama(prompt: str) -> str:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            # Match the hosted providers' temperature (see _extract_via_chat_api).
            # Ollama defaults to a much higher temperature, which made the
            # decision-gate classification noticeably less consistent locally
            # than the same prompt run against a hosted model.
            "options": {"temperature": 0.2},
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["response"].strip()


def _extract_via_chat_api(url: str, api_key: str, model: str, prompt: str, provider_label: str) -> str:
    if not api_key:
        raise RuntimeError(f"LLM_PROVIDER={provider_label} but its API key is not set")
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def _complete(prompt: str) -> str:
    if LLM_PROVIDER == "openrouter":
        return _extract_via_chat_api(OPENROUTER_URL, OPENROUTER_API_KEY, OPENROUTER_MODEL, prompt, "openrouter")
    if LLM_PROVIDER == "groq":
        return _extract_via_chat_api(GROQ_URL, GROQ_API_KEY, GROQ_MODEL, prompt, "groq")
    return _extract_via_ollama(prompt)


def extract_fact(text: str) -> str:
    """Send raw input text to the configured LLM provider and return the extracted fact."""
    return _complete(EXTRACTION_PROMPT.format(text=text))


def chat_turn(message: str) -> tuple[str, str | None]:
    """Reply to a chat message, and separately let the model decide whether to
    save a fact from it — the model does the deciding, not the caller.

    Two focused completions rather than one compound one: small models (a
    local 1B, or the cheap hosted models used for the deployed instance)
    follow a single-purpose instruction far more reliably than a "reply AND
    classify AND extract, in this exact format" one.
    """
    reply = _complete(REPLY_PROMPT.format(message=message)).strip()

    is_farewell = any(t in message.lower() for t in FAREWELL_TRIGGERS)
    if "?" not in reply and not is_farewell:
        if reply and reply[-1] not in ".!?":
            reply += "."
        reply = (reply + " " + FALLBACK_FOLLOWUP).strip()

    if any(trigger in message.lower() for trigger in EXPLICIT_SAVE_TRIGGERS):
        fact = extract_fact(message)
    else:
        decision = _complete(DECISION_PROMPT.format(message=message)).strip()
        fact = None if decision.upper().startswith("NONE") else decision

    return reply, fact
