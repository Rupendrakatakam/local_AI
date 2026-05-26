"""
search.py — Shared search logic.
Fixes:
  - Category detection: "image" → jpg/png/jpeg/etc, "video" → mp4/etc
  - Zero-byte files excluded at query time (covers pre-existing DB entries)
  - Cascading relaxation preserved
Batch 2:
  - #14: Stale file background cleanup
"""

import json
import os
import re
import sqlite3
import requests
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

DB_PATH    = Path.home() / ".local" / "share" / "filefinder" / "index.db"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL      = "phi3:mini"

# ── Category → extension map ──────────────────────────────────────────────────
CATEGORY_MAP: dict[str, list[str]] = {
    "image":    ["jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "tiff", "ico"],
    "photo":    ["jpg", "jpeg", "png", "heic", "raw", "cr2"],
    "video":    ["mp4", "avi", "mkv", "mov", "wmv", "flv", "webm"],
    "audio":    ["mp3", "wav", "flac", "aac", "ogg", "m4a"],
    "document": ["pdf", "doc", "docx", "odt", "txt", "md", "rtf"],
    "pdf":      ["pdf"],
    "code":     ["py", "js", "ts", "cpp", "c", "h", "java", "rs", "go", "sh"],
    "script":   ["py", "sh", "bash", "zsh", "fish"],
    "spreadsheet": ["xlsx", "xls", "csv", "ods"],
    "archive":  ["zip", "tar", "gz", "bz2", "xz", "7z", "rar"],
}

# Words that signal a category, not a keyword
CATEGORY_WORDS = set(CATEGORY_MAP.keys()) | {
    "images", "photos", "videos", "audios", "documents", "scripts", "archives"
}


@dataclass
class FileResult:
    path: str
    name: str
    extension: str
    size: int
    mtime: float

    @property
    def size_human(self) -> str:
        if self.size < 1024:
            return f"{self.size} B"
        elif self.size < 1024 ** 2:
            return f"{self.size/1024:.1f} KB"
        else:
            return f"{self.size/1024**2:.1f} MB"


# ── Category detection ────────────────────────────────────────────────────────
def _detect_category(words: list[str]) -> tuple[Optional[list[str]], list[str]]:
    """
    Scan words for category hints.
    Returns (extensions_list_or_None, remaining_keywords).
    """
    for word in words:
        w = word.lower().rstrip("s")   # "images" → "image"
        if w in CATEGORY_MAP:
            remaining = [kw for kw in words if kw.lower().rstrip("s") != w]
            return CATEGORY_MAP[w], remaining
        if word.lower() in CATEGORY_MAP:
            remaining = [kw for kw in words if kw.lower() != word.lower()]
            return CATEGORY_MAP[word.lower()], remaining
    return None, words


# ── Keyword normalization ─────────────────────────────────────────────────────
def _normalize_keywords(keywords: list[str]) -> list[str]:
    atoms = []
    for kw in keywords:
        parts = re.split(r'[\s_\-\.]+', kw)
        expanded = []
        for p in parts:
            expanded.extend(re.sub(r'([a-z])([A-Z])', r'\1 \2', p).split())
        atoms.extend([a.lower() for a in expanded if len(a) >= 2])
    seen = set()
    return [a for a in atoms if not (a in seen or seen.add(a))]


# ── SQLite helpers ────────────────────────────────────────────────────────────
def _db_search(keywords: list[str],
               extensions: Optional[list[str]],
               directory: Optional[str] = None,
               limit: int = 15,
               use_or: bool = False) -> list[FileResult]:
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    atoms = _normalize_keywords(keywords)
    clauses, params = [], []

    # Keyword clauses
    if atoms:
        kw_clauses = []
        for atom in atoms:
            kw_clauses.append("name LIKE ?")
            params.append(f"%{atom}%")
        joiner = " OR " if use_or else " AND "
        clauses.append(f"({joiner.join(kw_clauses)})")

    # Extension filter — supports multi-extension (category search)
    if extensions:
        placeholders = ",".join("?" * len(extensions))
        clauses.append(f"extension IN ({placeholders})")
        params.extend([e.lower() for e in extensions])

    # Directory scope
    if directory:
        clauses.append("path LIKE ?")
        params.append(f"{directory}%")

    # Always exclude zero-byte files (covers pre-existing DB entries)
    clauses.append("size > 0")

    where = " AND ".join(clauses) if clauses else "size > 0"
    rows = conn.execute(
        f"SELECT path, name, extension, size, mtime FROM files "
        f"WHERE {where} ORDER BY mtime DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    conn.close()
    return [FileResult(**dict(r)) for r in rows]


# ── Stale file background cleanup (#14) ──────────────────────────────────────
def _cleanup_stale(paths: list[str]) -> None:
    """Remove DB entries for files that no longer exist. Runs in background."""
    stale = [p for p in paths if not os.path.exists(p)]
    if not stale or not DB_PATH.exists():
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.executemany("DELETE FROM files WHERE path = ?", [(p,) for p in stale])
        conn.commit()
        conn.close()
    except Exception:
        pass


def _filter_and_clean(results: list[FileResult]) -> list[FileResult]:
    """Remove stale entries from results and schedule DB cleanup."""
    live = [r for r in results if os.path.exists(r.path)]
    stale_paths = [r.path for r in results if not os.path.exists(r.path)]
    if stale_paths:
        threading.Thread(target=_cleanup_stale, args=(stale_paths,), daemon=True).start()
    return live


# ── Ollama intent parser ──────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a file-search intent extractor.
Given a user query, return ONLY a JSON object — no explanation, no markdown.
Fields:
  "keywords"  : list of individual filename keywords (strings, lowercase).
                Split compound terms. Do NOT include: find, where, my, the, can, you, show, me, image, photo, video, audio, document, file, named, called.
  "extension" : single file extension without dot e.g. "py", "pdf", or null. Use null if the user says "image", "photo", "video" — those are categories not extensions.
  "directory" : folder name hint (e.g. "Downloads") or null
Example: "find the tax report pdf in Downloads" → {"keywords": ["tax", "report"], "extension": "pdf", "directory": "Downloads"}
Example: "where is my resume" → {"keywords": ["resume"], "extension": null, "directory": null}
Example: "can you find image named rupendra" → {"keywords": ["rupendra"], "extension": null, "directory": null}"""


def _parse_intent(query: str) -> dict:
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": f"{SYSTEM_PROMPT}\n\nQuery: {query}\nJSON:", "stream": False},
            timeout=15,
        )
        raw = resp.json()["response"].strip()
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start != -1 and end:
            return json.loads(raw[start:end])
    except Exception:
        pass
    filler = {"can", "you", "find", "the", "where", "is", "my", "show", "me",
              "a", "an", "that", "this", "named", "called", "in", "image",
              "photo", "video", "audio", "document", "file"}
    words = [w for w in query.lower().split() if w not in filler and len(w) >= 2]
    return {"keywords": words or query.split(), "extension": None, "directory": None}


def _resolve_directory(hint: Optional[str]) -> Optional[str]:
    if not hint:
        return None
    if hint.startswith("/"):
        return hint
    return str(Path.home() / hint)


# ── Public API ────────────────────────────────────────────────────────────────
def quick_search(query: str, limit: int = 15) -> list[FileResult]:
    results = _db_search([query], extensions=None, limit=limit)
    return _filter_and_clean(results)


def search(query: str, limit: int = 15) -> list[FileResult]:
    """
    Cascading search:
      0. Pre-pass: detect category words (image/video/audio/etc)
      1. Bare filename → quick_search
      2. LLM intent → SQLite (AND mode)
      3. Relax: drop extension
      4. Relax: drop directory
      5. Relax: top-2 keywords only
      6. Final: OR mode
    """
    stripped = query.strip()

    # 0. Detect category in original query before passing to LLM
    query_words = stripped.lower().split()
    category_extensions, non_category_words = _detect_category(query_words)

    # 1. Quick path for bare filenames
    if " " not in stripped:
        results = quick_search(stripped, limit)
        if results:
            return results

    # 2. LLM intent
    intent     = _parse_intent(stripped)
    keywords   = intent.get("keywords") or [w for w in stripped.split() if len(w) >= 2]
    extension  = intent.get("extension")
    directory  = _resolve_directory(intent.get("directory"))

    # Merge: category extensions override single LLM extension
    extensions = category_extensions if category_extensions else ([extension] if extension else None)

    # Remove category words from keywords
    if category_extensions:
        _, keywords = _detect_category(keywords)

    results = _db_search(keywords, extensions, directory, limit)
    if results:
        return _filter_and_clean(results)

    # 3. Drop extension
    if extensions:
        results = _db_search(keywords, None, directory, limit)
        if results:
            return _filter_and_clean(results)

    # 4. Drop directory
    if directory:
        results = _db_search(keywords, extensions, None, limit)
        if results:
            return _filter_and_clean(results)
        if extensions:
            results = _db_search(keywords, None, None, limit)
            if results:
                return _filter_and_clean(results)

    # 5. Top-2 most specific keywords
    if len(keywords) > 2:
        top_kw = sorted(keywords, key=len, reverse=True)[:2]
        results = _db_search(top_kw, extensions, None, limit)
        if results:
            return _filter_and_clean(results)

    # 6. OR mode fallback
    results = _db_search(keywords, extensions, None, limit, use_or=True)
    return _filter_and_clean(results)


def db_stats() -> dict:
    if not DB_PATH.exists():
        return {"total": 0, "db_path": str(DB_PATH), "ready": False}
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.close()
    return {"total": total, "db_path": str(DB_PATH), "ready": True}
