"""
search.py — Shared search logic.
Batch 3: #17 Hidden files toggle, #18 type: syntax filter
Batch 4: Fuzzy fallback, sub-keyword expansion, relevance scoring
"""

import json
import os
import re
import time
import sqlite3
import requests
import threading
from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

DB_PATH    = Path.home() / ".local" / "share" / "filefinder" / "index.db"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL      = "phi3:mini"

# ── Category map (#18) ────────────────────────────────────────────────────────
CATEGORY_MAP: dict[str, list[str]] = {
    "image":       ["jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "tiff", "ico"],
    "photo":       ["jpg", "jpeg", "png", "heic", "raw", "cr2"],
    "video":       ["mp4", "avi", "mkv", "mov", "wmv", "flv", "webm"],
    "audio":       ["mp3", "wav", "flac", "aac", "ogg", "m4a"],
    "document":    ["pdf", "doc", "docx", "odt", "txt", "md", "rtf"],
    "pdf":         ["pdf"],
    "code":        ["py", "js", "ts", "cpp", "c", "h", "java", "rs", "go", "sh"],
    "script":      ["py", "sh", "bash", "zsh", "fish"],
    "spreadsheet": ["xlsx", "xls", "csv", "ods"],
    "archive":     ["zip", "tar", "gz", "bz2", "xz", "7z", "rar"],
    "text":        ["txt", "md", "rst", "log"],
}

CATEGORY_WORDS = set(CATEGORY_MAP.keys()) | {
    "images", "photos", "videos", "audios", "documents",
    "scripts", "archives", "texts",
}

# ── Global hidden-files toggle (#17) ─────────────────────────────────────────
_show_hidden: bool = False


def toggle_hidden() -> bool:
    global _show_hidden
    _show_hidden = not _show_hidden
    return _show_hidden


def get_show_hidden() -> bool:
    return _show_hidden


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
        return f"{self.size/1024**2:.1f} MB"


# ── Type: syntax parser (#18) ─────────────────────────────────────────────────
def _extract_type_filter(query: str) -> tuple[Optional[list[str]], str]:
    """
    Parses 'type:image', 'type:video' etc from the query string.
    Returns (extensions_list_or_None, cleaned_query).
    """
    match = re.search(r'\btype:(\w+)', query, re.IGNORECASE)
    if match:
        category = match.group(1).lower().rstrip("s")
        extensions = CATEGORY_MAP.get(category) or CATEGORY_MAP.get(category + "s")
        cleaned = query[:match.start()].strip() + " " + query[match.end():].strip()
        return extensions, cleaned.strip()
    return None, query


# ── Natural language category detector ────────────────────────────────────────
def _detect_category(words: list[str]) -> tuple[Optional[list[str]], list[str]]:
    for word in words:
        w = word.lower().rstrip("s")
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
        atoms.extend([a.lower() for a in expanded if len(a) >= 1])
    seen = set()
    return [a for a in atoms if not (a in seen or seen.add(a))]


# ── SQLite search ─────────────────────────────────────────────────────────────
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

    if atoms:
        kw_clauses = [f"name LIKE ?" for _ in atoms]
        params.extend([f"%{a}%" for a in atoms])
        joiner = " OR " if use_or else " AND "
        clauses.append(f"({joiner.join(kw_clauses)})")

    if extensions:
        placeholders = ",".join("?" * len(extensions))
        clauses.append(f"extension IN ({placeholders})")
        params.extend([e.lower() for e in extensions])

    if directory:
        clauses.append("path LIKE ?")
        params.append(f"{directory}%")

    # Always exclude zero-byte
    clauses.append("size > 0")

    # (#17) Hidden files filter
    if not _show_hidden:
        clauses.append("name NOT LIKE '.%'")

    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT path, name, extension, size, mtime FROM files "
        f"WHERE {where} ORDER BY mtime DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    conn.close()
    return [FileResult(**dict(r)) for r in rows]


# ── Stale cleanup (#14) ───────────────────────────────────────────────────────
def _cleanup_stale(paths: list[str]) -> None:
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
    live = [r for r in results if os.path.exists(r.path)]
    stale = [r.path for r in results if not os.path.exists(r.path)]
    if stale:
        threading.Thread(target=_cleanup_stale, args=(stale,), daemon=True).start()
    return live


# ── Fuzzy search — typo/fragment fallback (Batch 4) ───────────────────────────
_fuzzy_cache: list[tuple[str, str, str, str, int, float]] = []
_fuzzy_cache_time: float = 0
FUZZY_CACHE_TTL = 300  # 5 minutes

_DELIM_RE = re.compile(r'[_\-\.\s]+')


def _normalize_for_fuzzy(name: str) -> str:
    """Strip filename delimiters for fuzzy comparison."""
    return _DELIM_RE.sub(' ', name).lower().strip()


def _fts_search(keywords: list[str],
                extensions: Optional[list[str]],
                directory: Optional[str] = None,
                limit: int = 15) -> list[FileResult]:
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    atoms = _normalize_keywords(keywords)
    if not atoms:
        conn.close()
        return []

    clean_atoms = []
    for a in atoms:
        clean = a.replace('"', '').strip()
        if clean:
            clean_atoms.append(f'"{clean}"')

    if not clean_atoms:
        conn.close()
        return []

    match_query = " ".join(clean_atoms)
    
    clauses = ["files_fts MATCH ?"]
    params = [match_query]

    if extensions:
        placeholders = ",".join("?" * len(extensions))
        clauses.append(f"files.extension IN ({placeholders})")
        params.extend([e.lower() for e in extensions])

    if directory:
        clauses.append("files.path LIKE ?")
        params.append(f"{directory}%")

    clauses.append("files.size > 0")

    if not _show_hidden:
        clauses.append("files.name NOT LIKE '.%'")

    where = " AND ".join(clauses)
    
    query_str = (
        f"SELECT files.path, files.name, files.extension, files.size, files.mtime "
        f"FROM files_fts "
        f"JOIN files ON files.rowid = files_fts.rowid "
        f"WHERE {where} ORDER BY bm25(files_fts) LIMIT ?"
    )
    
    try:
        rows = conn.execute(query_str, params + [limit]).fetchall()
        results = [FileResult(**dict(r)) for r in rows]
    except sqlite3.OperationalError:
        results = []
    finally:
        conn.close()
        
    return results


def _trigram_search(query: str, limit: int = 15) -> list[FileResult]:
    if not DB_PATH.exists():
        return []
        
    q_norm = _normalize_for_fuzzy(query)
    if len(q_norm) < 3:
        return []
        
    q_trigrams = [q_norm[i:i+3] for i in range(len(q_norm)-2)]
    if not q_trigrams:
        return []
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    placeholders = ",".join("?" * len(q_trigrams))
    hidden_clause = "AND files.name NOT LIKE '.%'" if not _show_hidden else ""
    
    query_str = f"""
        SELECT files.path, files.name, files.extension, files.size, files.mtime,
               (2.0 * count(*) / (? + max(1, length(files.name) - 2))) as similarity
        FROM name_trigrams
        JOIN files ON files.rowid = name_trigrams.file_id
        WHERE name_trigrams.trigram IN ({placeholders}) AND files.size > 0 {hidden_clause}
        GROUP BY name_trigrams.file_id
        HAVING similarity >= 0.35
        ORDER BY similarity DESC, files.mtime DESC
        LIMIT ?
    """
    
    try:
        params = [len(q_trigrams)] + q_trigrams + [limit]
        rows = conn.execute(query_str, params).fetchall()
        results = [FileResult(**dict(r)) for r in rows]
    except sqlite3.OperationalError:
        results = []
    finally:
        conn.close()
        
    return results


def _load_fuzzy_cache() -> list[tuple[str, str, str, str, int, float]]:
    """Lazy-load recent filenames into memory for fuzzy matching."""
    global _fuzzy_cache, _fuzzy_cache_time
    now = time.time()
    if _fuzzy_cache and (now - _fuzzy_cache_time) < FUZZY_CACHE_TTL:
        return _fuzzy_cache

    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT name, path, extension, size, mtime FROM files "
        "WHERE size > 0 AND length(name) >= 4 "
        "ORDER BY mtime DESC LIMIT 50000"
    ).fetchall()
    conn.close()

    seen: set[str] = set()
    cache: list[tuple[str, str, str, str, int, float]] = []
    for name, path, ext, size, mtime in rows:
        norm = _normalize_for_fuzzy(name)
        if norm not in seen:
            seen.add(norm)
            cache.append((norm, name, path, ext or "", size, mtime))

    _fuzzy_cache = cache
    _fuzzy_cache_time = now
    return cache


def _fuzzy_search(query: str, limit: int = 15) -> list[FileResult]:
    """Fuzzy fallback: WRatio against cached normalized filenames."""
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return []

    cache = _load_fuzzy_cache()
    if not cache:
        return []

    q_norm = _normalize_for_fuzzy(query)
    norm_names = [entry[0] for entry in cache]

    matches = process.extract(
        q_norm, norm_names,
        scorer=fuzz.WRatio,
        limit=limit,
        score_cutoff=65,
    )

    if not matches:
        return []

    results: list[FileResult] = []
    for _, score, idx in matches:
        _norm, name, path, ext, size, mtime = cache[idx]
        if os.path.exists(path):
            results.append(FileResult(
                path=path, name=name, extension=ext,
                size=size, mtime=mtime,
            ))

    return results


# ── Sub-keyword expansion (Batch 4) ──────────────────────────────────────────
def _generate_sub_keywords(atoms: list[str]) -> list[str]:
    """Try splitting merged keywords into sub-words.

    Example: 'online' → ['on', 'line'] (3+4 char split)
    """
    expanded = list(atoms)
    for atom in atoms:
        if len(atom) >= 6:
            for i in range(3, len(atom) - 2):
                left, right = atom[:i], atom[i:]
                if len(left) >= 3 and len(right) >= 3:
                    expanded.extend([left, right])
    return list(set(expanded))


# ── Relevance scoring (Batch 4) ──────────────────────────────────────────────
def _score_result(query_atoms: list[str], result: FileResult) -> float:
    """Score a result by relevance to query, not just recency."""
    name_lower = result.name.lower()
    name_norm = _normalize_for_fuzzy(result.name)
    score = 0.0

    # Keyword coverage (0–50 points)
    matched = sum(1 for a in query_atoms if a in name_lower or a in name_norm)
    score += (matched / max(len(query_atoms), 1)) * 50

    # Path component keyword search / match bonus (0–10 points)
    path_parts = Path(result.path).parent.parts
    path_matched = 0
    for a in query_atoms:
        for part in path_parts:
            if a in part.lower():
                path_matched += 1
                break
    if query_atoms:
        score += (path_matched / len(query_atoms)) * 10

    # Exact name match bonus (30 points)
    base_name_lower = Path(result.name).stem.lower()
    for a in query_atoms:
        if a == base_name_lower or a == name_lower:
            score += 30
            break

    # Prefix bonus (0–20 points) — filename starts with a query keyword
    for a in query_atoms:
        if name_lower.startswith(a) or name_norm.startswith(a):
            score += 20
            break

    # Name length penalty — shorter names more likely the target
    score += max(0, 15 - len(result.name) / 10)

    # Recency bonus (0–15 points)
    days_old = (time.time() - result.mtime) / 86400
    score += max(0, 15 - days_old / 30)

    # Path depth penalty (-2 points per directory level)
    depth = len(Path(result.path).parts) - 1
    score -= depth * 2

    return score


def _rerank(query_atoms: list[str], results: list[FileResult]) -> list[FileResult]:
    """Re-rank results by relevance score instead of just mtime."""
    if not query_atoms or len(results) <= 1:
        return results
    return sorted(results, key=lambda r: _score_result(query_atoms, r), reverse=True)


# ── Ollama intent parser ──────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a file-search intent extractor.
Return ONLY a JSON object — no explanation, no markdown.
Fields:
  "keywords"  : filename keywords (lowercase). Split compound terms. Exclude: find, where, my, the, can, you, show, me, image, photo, video, audio, document, file, named, called.
  "extension" : single extension without dot e.g. "py", "pdf", or null. Use null for category words like image/photo/video.
  "directory" : folder name hint or null
Examples:
  "find tax report pdf in Downloads" → {"keywords": ["tax", "report"], "extension": "pdf", "directory": "Downloads"}
  "where is my resume" → {"keywords": ["resume"], "extension": null, "directory": null}
  "find image named rupendra" → {"keywords": ["rupendra"], "extension": null, "directory": null}"""


@lru_cache(maxsize=512)
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


# ── Semantic Search & Fusion (Phase 2) ───────────────────────────────────────
def _semantic_search(query: str, limit: int = 15) -> list[FileResult]:
    """Search by meaning using vector similarity in LanceDB."""
    try:
        from embedder import get_pipeline
        pipeline = get_pipeline()
        model = pipeline._get_text_model()
        table = pipeline._get_db()
        if model is None or table is None:
            return []
            
        q_vec = model.encode([query], normalize_embeddings=True, show_progress_bar=False).tolist()[0]
        results = table.search(q_vec).limit(limit * 3).to_pandas()
        
        seen = {}
        for _, row in results.iterrows():
            p = row["path"]
            if p not in seen:
                seen[p] = row
                
        file_results = []
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        for p, row in list(seen.items())[:limit]:
            r = conn.execute(
                "SELECT path, name, extension, size, mtime FROM files WHERE path=?", (p,)
            ).fetchone()
            if r:
                file_results.append(FileResult(**dict(r)))
        conn.close()
        return file_results
    except Exception:
        return []


def _rrf_fusion(keyword_results: list[FileResult], semantic_results: list[FileResult], k: int = 60) -> list[FileResult]:
    """Merge keyword and semantic results using Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    path_to_result: dict[str, FileResult] = {}
    
    for rank, r in enumerate(keyword_results):
        scores[r.path] = scores.get(r.path, 0.0) + 1.0 / (k + rank + 1)
        path_to_result[r.path] = r
        
    for rank, r in enumerate(semantic_results):
        scores[r.path] = scores.get(r.path, 0.0) + 1.0 / (k + rank + 1)
        path_to_result[r.path] = r
        
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [path_to_result[p] for p, _ in ranked]


def _needs_semantic(query: str) -> bool:
    """Heuristic: use semantic search for abstract/NL queries."""
    words = query.split()
    if any(w.startswith("type:") for w in words):
        return False
    if "." in query and " " not in query:
        return False
    if len(words) >= 3:
        return True
        
    abstract_signals = {"find", "show", "get", "about", "related", "similar",
                        "like", "with", "containing", "regarding", "notes", "report", "what", "how"}
    if any(w.lower() in abstract_signals for w in words):
        return True
    return False


# ── Public API ────────────────────────────────────────────────────────────────
def quick_search(query: str, limit: int = 15) -> list[FileResult]:
    results = _fts_search([query], extensions=None, limit=limit)
    if not results:
        results = _db_search([query], extensions=None, limit=limit)
    return _filter_and_clean(results)


def search(query: str, limit: int = 15) -> tuple[list[FileResult], bool]:
    """
    Cascading search with FTS5, trigram fallback, fuzzy fallback and relevance scoring.
    Returns (results, is_fuzzy) — is_fuzzy=True when results came from
    the trigram or rapidfuzz fallback layers (approximate matches).

    Tiers:
      0. Parse type: filter (#18)
      0b. Detect category words in natural language
      1. Bare filename → quick_search
      2. LLM intent → AND mode
      3. Relax: drop extension
      4. Relax: drop directory
      5. Relax: top-2 keywords
      6. OR mode fallback
      6.5 Sub-keyword expansion (Batch 4)
      6.6 Trigram fuzzy fallback (Update 11)
      7. Fuzzy fallback (Batch 4)
    """
    stripped = query.strip()

    # 0. Explicit type: syntax (#18) — e.g. "type:image rupendra"
    type_extensions, stripped = _extract_type_filter(stripped)

    # 0b. NL category detection — e.g. "find image named rupendra"
    query_words = stripped.lower().split()
    nl_extensions, _ = _detect_category(query_words)
    category_extensions = type_extensions or nl_extensions

    # 1. Quick path for bare filenames
    if " " not in stripped and not type_extensions:
        results = quick_search(stripped, limit)
        if results:
            atoms = _normalize_keywords([stripped])
            return _rerank(atoms, results), False

    # 2. LLM intent
    intent    = _parse_intent(stripped)
    keywords  = intent.get("keywords") or [w for w in stripped.split() if len(w) >= 2]
    extension = intent.get("extension")
    directory = _resolve_directory(intent.get("directory"))

    extensions = category_extensions if category_extensions else ([extension] if extension else None)

    # Remove category words from keywords
    if category_extensions:
        _, keywords = _detect_category(keywords)

    # Build atoms once for scoring
    atoms = _normalize_keywords(keywords)

    results = _fts_search(keywords, extensions, directory, limit)
    if not results:
        results = _db_search(keywords, extensions, directory, limit)
        
    keyword_results = _filter_and_clean(results)
    
    if _needs_semantic(stripped):
        semantic_results = _semantic_search(stripped, limit)
        if semantic_results:
            fused = _rrf_fusion(keyword_results, semantic_results)
            return fused, False
            
    if keyword_results:
        return _rerank(atoms, keyword_results), False

    # 3. Drop extension
    if extensions:
        results = _fts_search(keywords, None, directory, limit)
        if not results:
            results = _db_search(keywords, None, directory, limit)
        if results:
            return _rerank(atoms, _filter_and_clean(results)), False

    # 4. Drop directory
    if directory:
        results = _fts_search(keywords, extensions, None, limit)
        if not results:
            results = _db_search(keywords, extensions, None, limit)
        if results:
            return _rerank(atoms, _filter_and_clean(results)), False
        if extensions:
            results = _fts_search(keywords, None, None, limit)
            if not results:
                results = _db_search(keywords, None, None, limit)
            if results:
                return _rerank(atoms, _filter_and_clean(results)), False

    # 5. Top-2 keywords
    if len(keywords) > 2:
        top_kw = sorted(keywords, key=len, reverse=True)[:2]
        results = _fts_search(top_kw, extensions, None, limit)
        if not results:
            results = _db_search(top_kw, extensions, None, limit)
        if results:
            return _rerank(atoms, _filter_and_clean(results)), False

    # 6. OR mode
    results = _db_search(keywords, extensions, None, limit, use_or=True)
    results = _filter_and_clean(results)
    if results:
        return _rerank(atoms, results), False

    # 6.5 Sub-keyword expansion — e.g. "online" → LIKE '%on%' AND '%line%'
    sub_kw = _generate_sub_keywords(atoms)
    if len(sub_kw) > len(atoms):
        results = _db_search(sub_kw, extensions, None, limit, use_or=True)
        results = _filter_and_clean(results)
        if results:
            return _rerank(atoms, results), False

    # 6.6 Trigram fuzzy fallback (Update 11)
    results = _trigram_search(stripped, limit)
    if results:
        return _filter_and_clean(results), True

    # 7. Fuzzy fallback — handles typos and fragments
    results = _fuzzy_search(stripped, limit)
    if results:
        return results, True

    return [], False


def db_stats() -> dict:
    if not DB_PATH.exists():
        return {"total": 0, "db_path": str(DB_PATH), "ready": False}
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.close()
    return {"total": total, "db_path": str(DB_PATH), "ready": True}
