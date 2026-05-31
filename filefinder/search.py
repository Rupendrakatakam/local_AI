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
from config_loader import get as cfg
from suggestions import get_suggestions
from db_utils import get_all_shard_paths
import concurrent.futures

DB_PATH    = Path.home() / ".local" / "share" / "filefinder" / "index.db"
OLLAMA_URL = cfg("ollama_url", "http://localhost:11434/api/generate")
MODEL      = cfg("ollama_model", "phi3:mini")
CACHE_TTL  = float(cfg("cache_ttl_seconds", 30))

# Update 69: Thread-local connection pool
_local = threading.local()

_shard_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=min(16, os.cpu_count() or 4),
    thread_name_prefix="shard_query"
)

# Update 70: Query result cache
_query_cache: dict[str, tuple[float, list, bool]] = {}
_cache_lock = threading.Lock()

def _cache_get(key: str):
    with _cache_lock:
        if key in _query_cache:
            ts, results, fuzzy = _query_cache[key]
            if time.time() - ts < CACHE_TTL:
                return results, fuzzy
            del _query_cache[key]
        return None

def _cache_set(key: str, results, fuzzy):
    with _cache_lock:
        if len(_query_cache) > 200:
            oldest = min(_query_cache, key=lambda k: _query_cache[k][0])
            del _query_cache[oldest]
        _query_cache[key] = (time.time(), results, fuzzy)

# Update 74: Ollama rate limiter
_ollama_semaphore = threading.Semaphore(cfg("ollama_max_concurrent", 3))
_ollama_last_call = 0.0
_OLLAMA_MIN_INTERVAL = cfg("ollama_rate_limit_ms", 100) / 1000.0

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
    score: float = 0.0

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


def _extract_content_filter(query: str) -> tuple[Optional[str], str]:
    """Parses 'content:"my text"' or 'content:text'."""
    match = re.search(r'\bcontent:(?:"([^"]+)"|(\S+))', query, re.IGNORECASE)
    if match:
        content_query = match.group(1) or match.group(2)
        cleaned = query[:match.start()].strip() + " " + query[match.end():].strip()
        return content_query, cleaned.strip()
    return None, query


def _extract_tag_filter(query: str) -> tuple[Optional[str], str]:
    """Parses 'tag:finance' or 'tag:"my tag"'."""
    match = re.search(r'\btag:(?:"([^"]+)"|(\S+))', query, re.IGNORECASE)
    if match:
        tag_query = match.group(1) or match.group(2)
        cleaned = query[:match.start()].strip() + " " + query[match.end():].strip()
        return tag_query.lower(), cleaned.strip()
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


# ── Keyword normalization & Expansion ───────────────────────────────────────────
def _normalize_keywords(keywords: list[str]) -> list[str]:
    atoms = []
    for kw in keywords:
        # If it looks like a filename (has a dot-extension), keep it intact
        if '.' in kw and ' ' not in kw and len(kw) > 2:
            atoms.append(kw.lower())
            continue
        parts = re.split(r'[\s_\-\.]+', kw)
        expanded = []
        for p in parts:
            expanded.extend(re.sub(r'([a-z])([A-Z])', r'\1 \2', p).split())
        atoms.extend([a.lower() for a in expanded if len(a) >= 1])
    seen = set()
    return [a for a in atoms if not (a in seen or seen.add(a))]


FALLBACK_SYNONYMS = {
    "car": ["vehicle", "automobile", "auto"],
    "ml": ["machine", "learning", "ai"],
    "ai": ["artificial", "intelligence", "ml"],
    "photo": ["image", "picture", "img"],
    "image": ["photo", "picture", "img"],
    "video": ["movie", "clip", "mp4"],
    "doc": ["document", "pdf", "word"],
    "text": ["txt", "log", "note"],
    "js": ["javascript"],
    "py": ["python"],
    "ts": ["typescript"]
}


@lru_cache(maxsize=512)
def _get_synonyms(word: str) -> list[str]:
    """Return synonyms for a word (excluding the word itself). Cached for performance."""
    syns = set()
    try:
        from nltk.corpus import wordnet
        for syn in wordnet.synsets(word)[:3]:
            for lemma in syn.lemmas()[:3]:
                w = lemma.name().replace('_', ' ').lower()
                if w != word:
                    syns.add(w)
    except ImportError:
        pass
        
    if word in FALLBACK_SYNONYMS:
        syns.update(FALLBACK_SYNONYMS[word])
        
    return list(syns)


# ── SQLite search ─────────────────────────────────────────────────────────────
def _db_search(keywords: list[str],
               extensions: Optional[list[str]],
               directory: Optional[str] = None,
               limit: int = 15,
               use_or: bool = False) -> list[FileResult]:
    shards = get_all_shard_paths()
    if not shards:
        return []
    all_results = []
    futures = [_shard_executor.submit(_db_search_single, p, keywords, extensions, directory, limit, use_or) for p in shards]
    for f in concurrent.futures.as_completed(futures):
        all_results.extend(f.result())
    all_results.sort(key=lambda x: x.mtime, reverse=True)
    return all_results[:limit]

def _db_search_single(db_path: Path, keywords: list[str],
               extensions: Optional[list[str]],
               directory: Optional[str] = None,
               limit: int = 15,
               use_or: bool = False) -> list[FileResult]:
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except Exception:
        return []

    atoms = _normalize_keywords(keywords)
    clauses, params = [], []

    if atoms:
        if use_or:
            kw_clauses = [f"name LIKE ?" for _ in atoms]
            params.extend([f"%{a}%" for a in atoms])
            clauses.append(f"({' OR '.join(kw_clauses)})")
        else:
            for a in atoms:
                syns = [a] + _get_synonyms(a)
                sub_clauses = [f"name LIKE ?" for _ in syns]
                params.extend([f"%{s}%" for s in syns])
                clauses.append(f"({' OR '.join(sub_clauses)})")

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
    if not stale: return
    for db_path in get_all_shard_paths():
        try:
            conn = sqlite3.connect(db_path)
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
    shards = get_all_shard_paths()
    if not shards:
        return []
    all_results = []
    futures = [_shard_executor.submit(_fts_search_single, p, keywords, extensions, directory, limit) for p in shards]
    for f in concurrent.futures.as_completed(futures):
        all_results.extend(f.result())
    all_results.sort(key=lambda x: x.mtime, reverse=True)
    return all_results[:limit]

def _fts_search_single(db_path: Path, keywords: list[str],
                extensions: Optional[list[str]],
                directory: Optional[str] = None,
                limit: int = 15) -> list[FileResult]:
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except Exception:
        return []

    atoms = _normalize_keywords(keywords)
    if not atoms:
        conn.close()
        return []

    clean_groups = []
    for a in atoms:
        clean = a.replace('"', '').strip()
        if clean:
            syns = _get_synonyms(clean)
            if syns:
                group = " OR ".join([f'"{s}"' for s in [clean] + syns])
                clean_groups.append(f"({group})")
            else:
                clean_groups.append(f'"{clean}"')

    if not clean_groups:
        conn.close()
        return []

    match_query = " AND ".join(clean_groups)
    
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
    shards = get_all_shard_paths()
    if not shards:
        return []
    q_norm = _normalize_for_fuzzy(query)
    if len(q_norm) < 3: return []
    q_trigrams = [q_norm[i:i+3] for i in range(len(q_norm)-2)]
    if not q_trigrams: return []
    
    all_results = []
    futures = [_shard_executor.submit(_trigram_search_single, p, query, limit) for p in shards]
    for f in concurrent.futures.as_completed(futures):
        all_results.extend(f.result())
    all_results.sort(key=lambda x: x.mtime, reverse=True)
    return all_results[:limit]

def _trigram_search_single(db_path: Path, query: str, limit: int = 15) -> list[FileResult]:
    q_norm = _normalize_for_fuzzy(query)
    q_trigrams = [q_norm[i:i+3] for i in range(len(q_norm)-2)]
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except Exception:
        return []
    
    placeholders = ",".join("?" * len(q_trigrams))
    hidden_clause = "AND files.name NOT LIKE '.%'" if not _show_hidden else ""
    
    query_str = f"""
        SELECT files.path, files.name, files.extension, files.size, files.mtime,
               (2.0 * count(*) / (? + max(1, length(files.name) - 2))) as similarity
        FROM name_trigrams
        JOIN files ON files.rowid = name_trigrams.file_id
        WHERE name_trigrams.trigram IN ({placeholders}) AND files.size > 0 {hidden_clause}
        GROUP BY name_trigrams.file_id
        HAVING similarity >= {cfg('trigram_threshold', 0.45)}
        ORDER BY similarity DESC, files.mtime DESC
        LIMIT ?
    """
    
    try:
        params = [len(q_trigrams)] + q_trigrams + [limit]
        rows = conn.execute(query_str, params).fetchall()
        results = [FileResult(path=r["path"], name=r["name"], extension=r["extension"],
                              size=r["size"], mtime=r["mtime"]) for r in rows]
    except sqlite3.OperationalError:
        results = []
    finally:
        conn.close()
        
    return results


def _content_search(query: str, limit: int = 15) -> list[FileResult]:
    shards = get_all_shard_paths()
    if not shards: return []
    all_results = []
    futures = [_shard_executor.submit(_content_search_single, p, query, limit) for p in shards]
    for f in concurrent.futures.as_completed(futures):
        all_results.extend(f.result())
    return all_results[:limit]

def _content_search_single(db_path: Path, query: str, limit: int = 15) -> list[FileResult]:
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except Exception:
        return []
    
    clean_atoms = []
    for a in query.replace('"', '').split():
        if a.strip():
            clean_atoms.append(f'"{a.strip()}"')
            
    if not clean_atoms:
        conn.close()
        return []
    
    # Use OR for content search — documents are long, partial matches are valuable
    match_query = " OR ".join(clean_atoms)
    
    query_str = """
        SELECT files.path, files.name, files.extension, files.size, files.mtime 
        FROM file_content_fts 
        JOIN files ON files.path = file_content_fts.path 
        WHERE file_content_fts MATCH ? AND files.size > 0
    """
    if not get_show_hidden():
        query_str += " AND files.name NOT LIKE '.%'"
        
    query_str += " ORDER BY bm25(file_content_fts) LIMIT ?"
    
    try:
        rows = conn.execute(query_str, [match_query, limit]).fetchall()
        results = [FileResult(**dict(r)) for r in rows]
    except sqlite3.OperationalError:
        results = []
    finally:
        conn.close()
    return results


def _tag_search(query: str, limit: int = 15) -> list[FileResult]:
    shards = get_all_shard_paths()
    if not shards: return []
    all_results = []
    futures = [_shard_executor.submit(_tag_search_single, p, query, limit) for p in shards]
    for f in concurrent.futures.as_completed(futures):
        all_results.extend(f.result())
    return all_results[:limit]

def _tag_search_single(db_path: Path, query: str, limit: int = 15) -> list[FileResult]:
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except Exception:
        return []
    
    clean_query = f"%{query}%"
    
    query_str = """
        SELECT files.path, files.name, files.extension, files.size, files.mtime 
        FROM file_tags 
        JOIN files ON files.path = file_tags.path 
        WHERE file_tags.tags LIKE ? AND files.size > 0
    """
    if not get_show_hidden():
        query_str += " AND files.name NOT LIKE '.%'"
        
    query_str += " LIMIT ?"
    
    try:
        rows = conn.execute(query_str, [clean_query, limit]).fetchall()
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

    shards = get_all_shard_paths()
    all_rows = []
    
    def fetch_rows(db_path):
        try:
            conn = sqlite3.connect(db_path)
            res = conn.execute(
                "SELECT name, path, extension, size, mtime FROM files "
                "WHERE size > 0 AND length(name) >= 4 "
                "ORDER BY mtime DESC LIMIT 50000"
            ).fetchall()
            conn.close()
            return res
        except: return []

    futures = [_shard_executor.submit(fetch_rows, p) for p in shards]
    for f in concurrent.futures.as_completed(futures):
        all_rows.extend(f.result())
            
    all_rows.sort(key=lambda x: x[4], reverse=True)
    rows = all_rows[:50000]

    seen: set[str] = set()
    cache: list[tuple[str, str, str, str, int, float]] = []
    for name, path, ext, size, mtime in rows:
        norm = _normalize_for_fuzzy(name)
        if norm not in seen:
            seen.add(norm)
            cache.append((norm, name, path, ext or "", size, mtime))

    with _fuzzy_cache_lock:
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
        score_cutoff=cfg("fuzzy_score_cutoff", 65),
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
def _score_result(query_atoms: list[str], result: FileResult, requested_extensions: Optional[list[str]] = None) -> float:
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

    # Behavioral boost (Phase 3) — 0 to 40 points
    try:
        from behavior import get_all_behavior_boosts
        score += get_all_behavior_boosts(result.path)
    except ImportError:
        pass

    # Extension priority boost
    if requested_extensions and result.extension and result.extension.lower() in requested_extensions:
        score += 80.0  # Massive priority boost for matching the requested format

    return score


def _rerank(query_atoms: list[str], results: list[FileResult], requested_extensions: Optional[list[str]] = None) -> list[FileResult]:
    """Re-rank results by relevance score instead of just mtime."""
    if not query_atoms or len(results) <= 1:
        return results
    for r in results:
        r.score = _score_result(query_atoms, r, requested_extensions)
    return sorted(results, key=lambda r: r.score, reverse=True)


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


@lru_cache(maxsize=cfg("lru_cache_maxsize", 256))
def _parse_intent(query: str) -> dict:
    global _ollama_last_call
    try:
        with _ollama_semaphore:
            now = time.time()
            wait = _OLLAMA_MIN_INTERVAL - (now - _ollama_last_call)
            if wait > 0:
                time.sleep(wait)
            _ollama_last_call = time.time()
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
def _semantic_search(query: str, extensions: Optional[list[str]] = None, limit: int = 15) -> list[FileResult]:
    """Search by meaning using vector similarity in LanceDB (Text + Image)."""
    try:
        from embedder import get_pipeline
        pipeline = get_pipeline()
        
        file_results = []
        seen = {}
        
        # 1. Text Semantic Search
        model = pipeline._get_text_model()
        table = pipeline._get_db()
        if model is not None and table is not None:
            try:
                q_vec = model.encode([query], normalize_embeddings=True, show_progress_bar=False).tolist()[0]
                # Pull more results if filtering by extension to ensure we have enough after SQLite rehydration
                fetch_limit = limit * (10 if extensions else 3)
                results = table.search(q_vec).limit(fetch_limit).to_pandas()
                for _, row in results.iterrows():
                    p = row["path"]
                    if p not in seen:
                        seen[p] = True
                        file_results.append(p)
            except Exception:
                pass
                
        # 2. Image Semantic Search (Feature 1.3)
        image_table = getattr(pipeline, "_image_table", None)
        if image_table is not None:
            # Load CLIP for image text query
            clip_model = pipeline._get_clip_model()
            if clip_model is not None:
                try:
                    img_q_vec = clip_model.encode([query], convert_to_numpy=True, show_progress_bar=False)[0]
                    import numpy as np
                    img_q_vec = img_q_vec / np.linalg.norm(img_q_vec)
                    
                    fetch_limit = limit * (10 if extensions else 3)
                    img_results = image_table.search(img_q_vec.tolist()).limit(fetch_limit).to_pandas()
                    for _, row in img_results.iterrows():
                        p = row["path"]
                        if p not in seen:
                            seen[p] = True
                            file_results.append(p)
                except Exception:
                    pass
        
        # Hydrate paths into FileResults from ALL shards (not just legacy DB)
        final_results = []
        seen_paths = set()
        paths_to_query = file_results[:limit*3]
        if not paths_to_query:
            return []
            
        for shard_path in get_all_shard_paths():
            try:
                conn = sqlite3.connect(shard_path)
                conn.row_factory = sqlite3.Row
                
                paths_to_query = [p for p in paths_to_query if p not in seen_paths]
                if not paths_to_query:
                    conn.close()
                    break
                    
                path_placeholders = ",".join("?" * len(paths_to_query))
                
                if extensions:
                    ext_placeholders = ",".join("?" * len(extensions))
                    ext_params = [e.lower() for e in extensions]
                    query = f"SELECT path, name, extension, size, mtime FROM files WHERE path IN ({path_placeholders}) AND extension IN ({ext_placeholders})"
                    rows = conn.execute(query, tuple(paths_to_query) + tuple(ext_params)).fetchall()
                else:
                    query = f"SELECT path, name, extension, size, mtime FROM files WHERE path IN ({path_placeholders})"
                    rows = conn.execute(query, tuple(paths_to_query)).fetchall()
                    
                for r in rows:
                    final_results.append(FileResult(**dict(r)))
                    seen_paths.add(r["path"])
                    
                conn.close()
            except Exception:
                pass
        return final_results[:limit]
    except Exception as e:
        import logging
        logging.getLogger("search").debug(f"Semantic search failed: {e}")
        return []


def _rrf_fusion(query_atoms: list[str], *result_lists: list[FileResult], requested_extensions: Optional[list[str]] = None, k: int = 60) -> list[FileResult]:
    """Merge any number of result lists using Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    path_to_result: dict[str, FileResult] = {}
    
    for results in result_lists:
        for rank, r in enumerate(results):
            scores[r.path] = scores.get(r.path, 0.0) + 1.0 / (k + rank + 1)
            path_to_result[r.path] = r
            
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if not ranked:
        return []
        
    max_rrf = ranked[0][1]
    
    final_results = []
    # RRF scores are typically very small, multiply by 100 for display
    for p, s in ranked:
        r = path_to_result[p]
        # Base score from keyword matching (0-100)
        kw_score = _score_result(query_atoms, r, requested_extensions)
        # Semantic/RRF contribution relative to the best semantic hit
        rrf_score = (s / max_rrf) * 85 if max_rrf > 0 else 0
        r.score = max(kw_score, rrf_score)
        final_results.append(r)
        
    return sorted(final_results, key=lambda x: getattr(x, 'score', 0), reverse=True)


def _looks_like_filename(query: str) -> bool:
    """True if query looks like a direct filename (has extension, no spaces)."""
    q = query.strip()
    if ' ' in q:
        return False
    # Must have a dot followed by 1-10 chars (extension)
    parts = q.rsplit('.', 1)
    if len(parts) == 2 and 1 <= len(parts[1]) <= 10:
        return True
    return False


def _needs_semantic(query: str) -> bool:
    """Heuristic: use semantic search for abstract/NL queries."""
    words = query.split()
    if any(w.startswith("type:") for w in words):
        return False
    # Single filename-like token → no semantic search needed
    if _looks_like_filename(query):
        return False
    if "." in query and " " not in query:
        return False
    # Only trigger semantic for genuinely abstract/NL queries (3+ non-trivial words)
    filler = {"find", "search", "locate", "show", "me", "my", "the", "a", "an",
              "where", "is", "get", "can", "you"}
    meaningful_words = [w for w in words if w.lower() not in filler]
    if len(meaningful_words) >= 3:
        return True
    abstract_signals = {"about", "related", "similar", "like", "with",
                        "containing", "regarding", "notes", "report", "what", "how"}
    if any(w.lower() in abstract_signals for w in meaningful_words):
        return True
    return False


# ── Exact name search (Tier 0) ────────────────────────────────────────────────
def _exact_name_search(name: str, limit: int = 15) -> list[FileResult]:
    """Direct WHERE name = ? search — O(1) via index. Guaranteed to find exact filenames."""
    shards = get_all_shard_paths()
    if not shards:
        return []
    all_results = []
    for shard_path in shards:
        try:
            conn = sqlite3.connect(shard_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT path, name, extension, size, mtime FROM files "
                "WHERE name = ? COLLATE NOCASE AND size > 0 "
                "ORDER BY mtime DESC LIMIT ?",
                (name, limit),
            ).fetchall()
            conn.close()
            all_results.extend([FileResult(**dict(r)) for r in rows])
        except Exception:
            pass
    all_results.sort(key=lambda x: x.mtime, reverse=True)
    return all_results[:limit]


# ── Command prefix stripper ───────────────────────────────────────────────────
_COMMAND_PREFIXES = [
    "find me ", "find ", "search for ", "search ", "locate ",
    "show me ", "where is my ", "where is ", "where's my ", "where's ",
    "can you find ", "please find ", "look for ",
]

def _strip_command_prefix(query: str) -> str:
    """Remove conversational prefixes like 'find', 'search for', 'show me' etc."""
    q = query.strip()
    lower = q.lower()
    for prefix in _COMMAND_PREFIXES:
        if lower.startswith(prefix):
            return q[len(prefix):].strip()
    return q


# ── Public API ────────────────────────────────────────────────────────────────
def quick_search(query: str, limit: int = 15) -> list[FileResult]:
    results = _fts_search([query], extensions=None, limit=limit)
    if not results:
        results = _db_search([query], extensions=None, limit=limit)
    return _filter_and_clean(results)


def search(query: str, limit: int = 15) -> tuple[list[FileResult], bool]:
    stripped = query.strip()

    cached = _cache_get(stripped)
    if cached:
        return cached

    result = _search_uncached(stripped, limit)

    _cache_set(
        stripped,
        result[0],
        result[1]
    )

    return result


def _search_uncached(query: str, limit: int = 15) -> tuple[list[FileResult], bool]:
    """
    Cascading search with FTS5, trigram fallback, fuzzy fallback and relevance scoring.
    Returns (results, is_fuzzy) — is_fuzzy=True when results came from
    the trigram or rapidfuzz fallback layers (approximate matches).

    Tiers:
      0. Exact name match (WHERE name = ?)
      0a. Alias check
      0b. Parse type:/content:/tag: filters
      0c. Detect category words in natural language
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

    # Strip conversational command prefixes: "find X" → "X"
    stripped = _strip_command_prefix(stripped)
    
    # ── Tier 0: Exact name match ──────────────────────────────────────────
    # If the cleaned query looks like a filename, try exact match first
    if _looks_like_filename(stripped):
        exact = _exact_name_search(stripped, limit)
        if exact:
            for r in exact:
                r.score = 100.0  # Perfect match
            return exact, False
    
    # 0a. Alias check (Phase 3)
    try:
        from aliases import get_alias
        alias_path = get_alias(stripped)
        if alias_path:
            # Search all shards for the aliased file
            for shard_path in get_all_shard_paths():
                try:
                    conn = sqlite3.connect(shard_path)
                    conn.row_factory = sqlite3.Row
                    r = conn.execute("SELECT path, name, extension, size, mtime FROM files WHERE path=?", (alias_path,)).fetchone()
                    conn.close()
                    if r:
                        return [FileResult(**dict(r))], False
                except Exception:
                    pass
    except ImportError:
        pass

    # 0a. Explicit extension extraction from NL queries (e.g., "list down all .cpp files")
    explicit_exts = []
    new_words = []
    for word in stripped.split():
        if word.startswith('.') and len(word) > 1 and all(c.isalnum() for c in word[1:]):
            explicit_exts.append(word[1:].lower())
        else:
            new_words.append(word)
    
    if explicit_exts:
        stripped = " ".join(new_words)

    # 0b. Explicit content: syntax
    content_query, stripped = _extract_content_filter(stripped)
    if content_query and not stripped:
        results = _content_search(content_query, limit)
        return _filter_and_clean(results), False
        
    tag_query, stripped = _extract_tag_filter(stripped)
    if tag_query and not stripped:
        results = _tag_search(tag_query, limit)
        return _filter_and_clean(results), False

    # 0b. Explicit type: syntax (#18) — e.g. "type:image rupendra"
    type_extensions, stripped = _extract_type_filter(stripped)

    if explicit_exts:
        type_extensions = (type_extensions or []) + explicit_exts

    # 0c. NL category detection — e.g. "find image named rupendra"
    query_words = stripped.lower().split()
    nl_extensions, _ = _detect_category(query_words)
    category_extensions = type_extensions or nl_extensions

    # 1. Quick path for bare filenames (no spaces)
    if " " not in stripped and not type_extensions:
        # Try exact name match first
        exact = _exact_name_search(stripped, limit)
        if exact:
            for r in exact:
                r.score = 100.0
            return exact, False
            
        # Extract implicit extension if present (e.g. A(q(a,b)).nb -> ext: nb, base: A(q(a,b)))
        implicit_ext = None
        base_name = stripped
        if '.' in stripped:
            parts = stripped.rsplit('.', 1)
            if len(parts) == 2 and 1 <= len(parts[1]) <= 10:
                base_name = parts[0]
                implicit_ext = parts[1].lower()
                
        if implicit_ext:
            results = _db_search([base_name], [implicit_ext], None, limit)
            if results:
                atoms = _normalize_keywords([base_name])
                
                # relaxed search pool for priority 2
                relaxed = quick_search(base_name, limit)
                seen = {r.path for r in results}
                for r in relaxed:
                    if r.path not in seen:
                        results.append(r)
                        seen.add(r.path)
                        
                return _rerank(atoms, _filter_and_clean(results), [implicit_ext]), False
            
            # If not found exactly, pass it down to the full pipeline but WITH the extension!
            stripped = base_name
            category_extensions = [implicit_ext]
        else:
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
    
    # Priority 2: Pool relaxed results if an extension was requested
    if extensions:
        relaxed = _fts_search(keywords, None, directory, limit)
        if not relaxed:
            relaxed = _db_search(keywords, None, directory, limit)
        seen = {r.path for r in keyword_results}
        for r in _filter_and_clean(relaxed):
            if r.path not in seen:
                keyword_results.append(r)
                seen.add(r.path)
    
    semantic_future = None
    if _needs_semantic(stripped):
        semantic_future = _shard_executor.submit(_semantic_search, stripped, extensions, limit)

    content_results = []
    if content_query:
        content_results = _content_search(content_query, limit)
    elif len(stripped.split()) > 1:
        content_results = _content_search(stripped, limit)
        
    semantic_results = []
    if semantic_future:
        try:
            semantic_results = semantic_future.result(timeout=0.5)
        except Exception:
            pass
        
    if semantic_results or content_results:
        fused = _rrf_fusion(atoms, keyword_results, semantic_results, content_results, requested_extensions=extensions)
        if fused:
            return fused, False
            
    if keyword_results:
        return _rerank(atoms, keyword_results, requested_extensions=extensions), False

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
    shards = get_all_shard_paths()
    if not shards:
        return {"total": 0, "db_path": "No shards found", "ready": False}
    total = 0
    for db_path in shards:
        try:
            conn = sqlite3.connect(db_path)
            total += conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            conn.close()
        except:
            pass
    return {"total": total, "db_path": f"{len(shards)} shards", "ready": True}
