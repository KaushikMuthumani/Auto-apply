"""
forms/answers.py — Persistent answer store.

Stores your answers to form questions as key→value in data/answers.json.
The key is a normalised version of the question label.

Priority when answering a question:
  1. Exact match in answers.json (your saved answers — highest priority)
  2. Built-in static answers (name, email, phone, etc.)
  3. AI (Ollama) guess
  4. Ask you via Telegram bot → save reply → return it
"""
import json, os, re

ANSWERS_FILE = "data/answers.json"


def _norm(text: str) -> str:
    """Normalise a question label for use as a dict key."""
    t = text.lower().strip()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:100]


def load() -> dict:
    if os.path.exists(ANSWERS_FILE):
        try:
            with open(ANSWERS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save(data: dict):
    os.makedirs(os.path.dirname(ANSWERS_FILE), exist_ok=True)
    with open(ANSWERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get(label: str) -> str | None:
    """Look up a saved answer for this label. Returns None if not found."""
    key  = _norm(label)
    data = load()
    # Exact match
    if key in data:
        return data[key]
    # Partial match — question contains one of our keys
    for k, v in data.items():
        if k in key or key in k:
            return v
    return None


def store(label: str, answer: str):
    """Save an answer for this label."""
    key  = _norm(label)
    data = load()
    data[key] = answer
    save(data)
    print(f"  💾  Saved: '{key}' → '{answer[:60]}'")
