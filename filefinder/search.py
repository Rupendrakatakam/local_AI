"""
search.py — Shared search logic used by both chat.py and the GUI.
  1. Quick path: pure SQLite fuzzy match (no LLM, instant)
  2. Smart path: phi3:mini parses natural language → SQLite
  3. Cascading relaxation: tight → relaxed → OR-mode fallback
"""

import json
import re
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


# ── Keyword normalization ──────────────────────────────────────────────────────
def _normalize_keywords(keywords: list[str]) -> list[str]:
    """
    Split multi-word keywords into atomic tokens and normalize delimiters.

    'online estimation' → ['online', 'estimation']
    'On-Line_Estimation' → ['on', 'line', 'estimation']
    'CamelCase' → ['camel', 'case']
    """
    atoms = []
    for kw in keywords:
        # Split on spaces, underscores, hyphens, dots
        parts = re.split(r'[\s_\-\.]+', kw)
        # Also split camelCase boundaries: "OnLine" → ["On", "Line"]
        expanded = []
        for p in parts:
            expanded.extend(re.sub(r'([a-z])([A-Z])', r'\1 \2', p).split())
        atoms.extend([a.lower() for a in expanded if len(a) >= 2])
    # Deduplicate while preserving order
    seen = set()
    return [a for a in atoms if not (a in seen or seen.add(a))]


# ── SQLite helpers ─────────────────────────────────────────────────────────────
def _db_search(keywords: list[str], extension: Optional[str],
               directory: Optional[str] = None, limit: int = 15,
               use_or: bool = False) -> list[FileResult]:
    """
    Search with delimiter-normalized atomic keywords.
    use_or=True switches from AND to OR matching (for final fallback).
    """
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Atomize keywords so "online estimation" → ["online", "estimation"]
    atoms = _normalize_keywords(keywords)

    clauses, params = [], []
    if atoms:
        kw_clauses = []
        for atom in atoms:
            kw_clauses.append("name LIKE ?")
            params.append(f"%{atom}%")
        joiner = " OR " if use_or else " AND "
        clauses.append(f"({joiner.join(kw_clauses)})")

    if extension:
        clauses.append("extension = ?")
        params.append(extension.lstrip(".").lower())

    if directory:
        clauses.append("path LIKE ?")
        params.append(f"{directory}%")

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
  "keywords"  : list of individual filename keywords (strings, lowercase).
                Split compound terms into separate entries (e.g. "on-line estimation" → ["on-line", "estimation"]).
                Do NOT include conversational words (find, where, my, the, can, you, show, me).
                Do NOT include directory/folder/path words.
  "extension" : file extension without dot, e.g. "py", "pdf", or null
  "directory" : directory or folder name hint from query (e.g. "Downloads", "Documents") or null
Example input : "find the tax report pdf in Downloads"
Example output: {"keywords": ["tax", "report"], "extension": "pdf", "directory": "Downloads"}
Example input : "where is my resume"
Example output: {"keywords": ["resume"], "extension": null, "directory": null}
Example input : "can you find on-line estimation pdf"
Example output: {"keywords": ["on-line", "estimation"], "extension": "pdf", "directory": null}"""


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
    # Fallback — treat every word as a keyword, strip conversational filler
    filler = {"can", "you", "find", "the", "where", "is", "my", "show", "me",
              "a", "an", "that", "this", "named", "called", "in"}
    words = [w for w in query.lower().split() if w not in filler and len(w) >= 2]
    return {"keywords": words or query.split(), "extension": None, "directory": None}


# ── Directory hint resolver ───────────────────────────────────────────────────
def _resolve_directory(hint: Optional[str]) -> Optional[str]:
    """Expand a directory hint like 'Downloads' to an absolute path."""
    if not hint:
        return None
    if hint.startswith("/"):
        return hint
    if hint.startswith("~"):
        return str(Path(hint).expanduser())
    # Assume it's relative to home
    return str(Path.home() / hint)


# ── Public API ─────────────────────────────────────────────────────────────────
def quick_search(query: str, limit: int = 15) -> list[FileResult]:
    """Fast SQLite-only search — no LLM. Good for exact/partial names."""
    return _db_search([query], extension=None, limit=limit)


def smart_search(query: str, limit: int = 15) -> list[FileResult]:
    """NL query → phi3:mini intent → SQLite search."""
    intent = _parse_intent(query)
    keywords  = intent.get("keywords") or [query]
    extension = intent.get("extension")
    directory = _resolve_directory(intent.get("directory"))
    return _db_search(keywords, extension, directory, limit)


def search(query: str, limit: int = 15) -> list[FileResult]:
    """
    Cascading search with progressive relaxation:
      1. Bare filename? → quick_search (instant, no LLM)
      2. LLM-assisted smart search (all keywords AND)
      3. Relax: drop extension filter
      4. Relax: drop directory filter
      5. Relax: top-2 most specific keywords only
      6. Final: OR-mode search (any keyword matches)
    """
    stripped = query.strip()

    # 1. Quick path for bare filenames (no spaces)
    if " " not in stripped:
        results = quick_search(stripped, limit)
        if results:
            return results

    # 2. LLM-assisted search
    intent = _parse_intent(stripped)
    keywords  = intent.get("keywords") or stripped.split()
    extension = intent.get("extension")
    directory = _resolve_directory(intent.get("directory"))

    results = _db_search(keywords, extension, directory, limit)
    if results:
        return results

    # 3. Relax: drop extension filter
    if extension:
        results = _db_search(keywords, None, directory, limit)
        if results:
            return results

    # 4. Relax: drop directory filter
    if directory:
        results = _db_search(keywords, extension, None, limit)
        if results:
            return results
        # Also try without both extension and directory
        if extension:
            results = _db_search(keywords, None, None, limit)
            if results:
                return results

    # 5. Relax: keep only the 2 longest (most specific) keywords
    if len(keywords) > 2:
        top_kw = sorted(keywords, key=len, reverse=True)[:2]
        results = _db_search(top_kw, extension, None, limit)
        if results:
            return results

    # 6. Final: OR-mode (any keyword matches)
    results = _db_search(keywords, extension, None, limit, use_or=True)
    return results


def db_stats() -> dict:
    """Return basic stats about the index."""
    if not DB_PATH.exists():
        return {"total": 0, "db_path": str(DB_PATH), "ready": False}
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.close()
    return {"total": total, "db_path": str(DB_PATH), "ready": True}
