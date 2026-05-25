"""
search.py — Shared search logic used by both chat.py and the GUI.
  1. Quick path: pure SQLite fuzzy match (no LLM, instant)
  2. Smart path: phi3:mini parses natural language → SQLite
"""

import json
import sqlite3
import requests
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

DB_PATH    = Path.home() / ".local" / "share" / "filefinder" / "index.db"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL      = "phi3:mini"


@dataclass
class FileResult:
    path: str
    name: str
    extension: str
    size: int       # bytes
    mtime: float    # unix timestamp

    @property
    def size_human(self) -> str:
        if self.size < 1024:
            return f"{self.size} B"
        elif self.size < 1024 ** 2:
            return f"{self.size/1024:.1f} KB"
        else:
            return f"{self.size/1024**2:.1f} MB"


# ── SQLite helpers ─────────────────────────────────────────────────────────────
def _db_search(keywords: list[str], extension: Optional[str], limit: int = 15) -> list[FileResult]:
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    clauses, params = [], []
    for kw in keywords:
        clauses.append("name LIKE ?")
        params.append(f"%{kw}%")

    if extension:
        clauses.append("extension = ?")
        params.append(extension.lstrip(".").lower())

    where = " AND ".join(clauses) if clauses else "1=1"
    rows = conn.execute(
        f"SELECT path, name, extension, size, mtime FROM files WHERE {where} ORDER BY mtime DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    conn.close()

    return [FileResult(**dict(r)) for r in rows]


# ── Ollama intent parser ───────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a file-search intent extractor.
Given a user query, return ONLY a JSON object — no explanation, no markdown.
Fields:
  "keywords"  : list of filename keywords (strings, lowercase)
  "extension" : file extension without dot e.g. "py", "pdf", or null
Example input : "where is my tax pdf from last year"
Example output: {"keywords": ["tax"], "extension": "pdf"}"""


def _parse_intent(query: str) -> dict:
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": f"{SYSTEM_PROMPT}\n\nQuery: {query}\nJSON:", "stream": False},
            timeout=15,
        )
        raw = resp.json()["response"].strip()
        # Extract JSON robustly
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start != -1 and end:
            return json.loads(raw[start:end])
    except Exception:
        pass
    # Fallback — treat every word as a keyword
    return {"keywords": query.split(), "extension": None}


# ── Public API ─────────────────────────────────────────────────────────────────
def quick_search(query: str, limit: int = 15) -> list[FileResult]:
    """Fast SQLite-only search — no LLM. Good for exact/partial names."""
    return _db_search([query], extension=None, limit=limit)


def smart_search(query: str, limit: int = 15) -> list[FileResult]:
    """NL query → phi3:mini intent → SQLite search."""
    intent = _parse_intent(query)
    keywords  = intent.get("keywords") or [query]
    extension = intent.get("extension")
    return _db_search(keywords, extension, limit)


def search(query: str, limit: int = 15) -> list[FileResult]:
    """
    Auto-routing:
    - If query looks like a bare filename (no spaces, has extension) → quick_search
    - Otherwise → smart_search
    """
    stripped = query.strip()
    if " " not in stripped:
        results = quick_search(stripped, limit)
        if results:
            return results
    return smart_search(stripped, limit)


def db_stats() -> dict:
    """Return basic stats about the index."""
    if not DB_PATH.exists():
        return {"total": 0, "db_path": str(DB_PATH), "ready": False}
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.close()
    return {"total": total, "db_path": str(DB_PATH), "ready": True}
