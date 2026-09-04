"""Submits a sequence of sample facts to one session, then prints the resulting chain.

Proves the append-only baton handoff: each new fact links to the previous one
via parent_fact_id instead of overwriting it. Requires the API to be running
(uvicorn app.main:app) and Ollama running locally with llama3.2:1b pulled.
"""

import requests

BASE_URL = "http://localhost:8000"
SESSION_ID = "test-session-001"

SAMPLE_INPUTS = [
    "We looked at three database options and decided to go with SQLite for the prototype "
    "since it needs zero setup and the dataset is small.",
    "Turns out SQLite's default threading mode was causing lock errors under concurrent "
    "writes, so we switched the connection to check_same_thread=False.",
    "Team agreed the API should only expose three endpoints for the hackathon MVP: "
    "POST /fact, GET /chain/{session_id}, GET /latest/{session_id}.",
    "After testing, we decided the dashboard UI will be built separately during the "
    "30-hour hackathon event instead of now, so today's scope stays backend-only.",
]


def main() -> None:
    print(f"Submitting {len(SAMPLE_INPUTS)} facts to session '{SESSION_ID}'...\n")

    for i, text in enumerate(SAMPLE_INPUTS, start=1):
        response = requests.post(
            f"{BASE_URL}/fact",
            json={"text": text, "session_id": SESSION_ID, "written_by": "llama3.2:1b"},
        )
        response.raise_for_status()
        facts = response.json()  # a list now — one input can yield several atomic facts
        print(f"[{i}] extracted {len(facts)} atomic fact(s):")
        for fact in facts:
            print(f"    id={fact['id']} parent={fact['parent_fact_id']} category={fact['category']}")
            print(f"    {fact['content']}\n")

    print("Fetching full chain...\n")
    chain_response = requests.get(f"{BASE_URL}/chain/{SESSION_ID}")
    chain_response.raise_for_status()
    chain = chain_response.json()

    print(f"Chain for session '{SESSION_ID}' ({len(chain)} facts, oldest -> newest):\n")
    for fact in chain:
        print(f"  id={fact['id']:<4} parent={str(fact['parent_fact_id']):<4} "
              f"by={fact['written_by']:<12} at={fact['timestamp']}")
        print(f"       {fact['content']}\n")

    latest_response = requests.get(f"{BASE_URL}/latest/{SESSION_ID}")
    latest_response.raise_for_status()
    latest = latest_response.json()
    print(f"Latest fact (id={latest['id']}): {latest['content']}")


if __name__ == "__main__":
    main()
