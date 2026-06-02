# FileChat — Master Execution Roadmap

> 80 updates across 5 phases. Each phase is split into **Batch A** (foundations) and **Batch B** (polish).
> Effort: XS=5–15min, S=30–60min, M=2–4hrs | Impact: HIGH/MED/LOW

---

## Phase 1: Foundation & Search Quality (20 updates)

### Batch 1A — Core Search Engine (IDs 1–12)

| # | File | Title | Effort | Impact |
|---|------|-------|--------|--------|
| 1 | indexer.py | Batch commit during full_scan | S | HIGH |
| 2 | indexer.py | FTS5 virtual table creation | S | HIGH |
| 3 | indexer.py | FTS5 INSERT trigger | S | HIGH |
| 4 | indexer.py | FTS5 DELETE trigger | S | HIGH |
| 5 | indexer.py | FTS5 UPDATE trigger | S | HIGH |
| 6 | indexer.py | Trigram table + index creation | S | MED |
| 7 | indexer.py | Populate trigrams on upsert | S | MED |
| 8 | indexer.py | Secure DB file permissions | XS | MED |
| 9 | indexer.py | Security entries in .filefinder_ignore | XS | MED |
| 10 | search.py | FTS5 search function | M | HIGH |
| 11 | search.py | Trigram fuzzy search function | M | HIGH |
| 12 | search.py | Route primary search to FTS5 | S | HIGH |

**Batch 1A Details:**

1. **Batch commit during full_scan** — Commit every 500 rows instead of per-file. Cuts initial scan from 8min → ~2min. Replace per-file upsert loop with executemany batches.
2. **FTS5 virtual table creation** — Add `CREATE VIRTUAL TABLE files_fts USING fts5(...)` in `get_db()`. Tokenize on `_`, `-`, `.`, space. Prerequisite for all FTS5 updates.
3. **FTS5 INSERT trigger** — `CREATE TRIGGER files_ai AFTER INSERT ON files` → populate files_fts. Keeps FTS index in sync automatically.
4. **FTS5 DELETE trigger** — `CREATE TRIGGER files_ad AFTER DELETE ON files` → remove from files_fts. Required for stale cleanup.
5. **FTS5 UPDATE trigger** — `CREATE TRIGGER files_au AFTER UPDATE ON files` → delete + re-insert in files_fts. Handles renames/mods.
6. **Trigram table + index creation** — `CREATE TABLE name_trigrams(trigram TEXT, file_id INTEGER)`. `CREATE INDEX idx_trigram`. For typo-tolerant fallback.
7. **Populate trigrams on upsert** — In `upsert()`, generate trigrams from filename and insert into name_trigrams. Delete old trigrams before insert on update.
8. **Secure DB file permissions** — After DB creation, chmod 600 on index.db and 700 on parent dir. One-line add to `get_db()`.
9. **Security entries in .filefinder_ignore** — Default ignore: `*.pem, *.key, *.env, id_rsa*, *secret*, *password*, *credentials*`.
10. **FTS5 search function** — New `_fts_search()` using `SELECT ... FROM files_fts JOIN files WHERE files_fts MATCH ?` with BM25. 5–10ms vs 180ms for LIKE.
11. **Trigram fuzzy search function** — New `_trigram_search()` — Dice coefficient on pre-built trigram table. Threshold 0.35. No rapidfuzz dependency.
12. **Route primary search to FTS5** — In `search()`, replace `_db_search()` tier-2 with `_fts_search()`. Fall back if FTS5 table doesn't exist.

### Batch 1B — Scoring & Polish (IDs 13–20)

| # | File | Title | Effort | Impact |
|---|------|-------|--------|--------|
| 13 | search.py | Fix single-char token filter | XS | LOW |
| 14 | search.py | LLM intent result caching (in-session) | S | MED |
| 15 | search.py | Path-component keyword search | S | MED |
| 16 | search.py | Relevance score — exact name match | XS | MED |
| 17 | search.py | Relevance score — path depth penalty | XS | LOW |
| 18 | search.py | Rapidfuzz install guard | XS | LOW |
| 19 | chat.py | Handle is_fuzzy flag in display | XS | LOW |
| 20 | indexer.py | One-time FTS5 rebuild for existing DBs | S | HIGH |

**Batch 1B Details:**

13. **Fix single-char token filter** — In `_normalize_keywords()`, change `len(a) >= 2` to `len(a) >= 1`. Fixes queries like `v2`, `c++`, `r`.
14. **LLM intent result caching** — Cache `_parse_intent()` results keyed by query string. TTL=300s. Use `functools.lru_cache` or manual dict.
15. **Path-component keyword search** — Add `path LIKE '%keyword%'` as OR clause when name-only search returns 0. Handles directory-name queries.
16. **Relevance score — exact name match** — In `_score_result()`, add +100 bonus when `name.lower() == query atom` exactly.
17. **Relevance score — path depth penalty** — Subtract 0.5 per directory level beyond depth 3.
18. **Rapidfuzz install guard** — Wrap rapidfuzz import in try/except with clear install message.
19. **Handle is_fuzzy flag in display** — `search()` returns `(results, is_fuzzy)`. Show `🔍 Approximate matches` banner conditionally.
20. **One-time FTS5 rebuild** — On startup, check if `files_fts` exists. If not, run `INSERT INTO files_fts SELECT rowid, name, path FROM files`.

---

## Phase 2: Semantic & Multimodal (18 updates)

### Batch 2A — Embedding Pipeline (IDs 21–30)

| # | File | Title | Effort | Impact |
|---|------|-------|--------|--------|
| 21 | embedder.py [NEW] | Module scaffold | S | HIGH |
| 22 | embedder.py [NEW] | LanceDB schema + table creation | S | HIGH |
| 23 | embedder.py [NEW] | Text extractor — plain text | S | HIGH |
| 24 | embedder.py [NEW] | Text extractor — PDF (pymupdf) | S | HIGH |
| 25 | embedder.py [NEW] | Text extractor — DOCX (mammoth) | S | MED |
| 26 | embedder.py [NEW] | Chunker function (512 tokens, 128 overlap) | S | HIGH |
| 27 | embedder.py [NEW] | MiniLM batch embedder | M | HIGH |
| 28 | embedder.py [NEW] | LanceDB upsert function | S | HIGH |
| 29 | embedder.py [NEW] | Background embedding worker | M | HIGH |
| 30 | indexer.py | Embedding queue integration | S | MED |

### Batch 2B — Search Fusion & Extras (IDs 31–38)

| # | File | Title | Effort | Impact |
|---|------|-------|--------|--------|
| 31 | search.py | Semantic search function | M | HIGH |
| 32 | search.py | RRF hybrid fusion | S | HIGH |
| 33 | search.py | Query router — keyword vs semantic | S | MED |
| 34 | clip_embedder.py [NEW] | CLIP model loader | M | MED |
| 35 | clip_embedder.py [NEW] | Image embedding function | S | MED |
| 36 | ocr_worker.py [NEW] | OCR worker for scanned PDFs | M | LOW |
| 37 | embedder.py | Embedding progress tracker | S | LOW |
| 38 | chat.py | Semantic search status in stats | XS | LOW |

---

## Phase 3: Behavioral & Autonomy (12 updates)

### Batch 3A — Behavior Tracking (IDs 39–45)

| # | File | Title | Effort | Impact |
|---|------|-------|--------|--------|
| 39 | behavior.py [NEW] | behavior.db schema | S | HIGH |
| 40 | chat.py | Record open events | XS | HIGH |
| 41 | chat.py | Record copy events | XS | MED |
| 42 | behavior.py [NEW] | RFM score calculator | M | HIGH |
| 43 | behavior.py [NEW] | Workspace affinity tracker | M | MED |
| 44 | search.py | Integrate RFM boost into _score_result | S | HIGH |
| 45 | behavior.py [NEW] | Time-of-day pattern detector | M | LOW |

### Batch 3B — Smart Suggestions (IDs 46–50)

| # | File | Title | Effort | Impact |
|---|------|-------|--------|--------|
| 46 | suggestions.py [NEW] | Query suggestion from history | M | MED |
| 47 | aliases.py [NEW] | Auto-alias system | M | MED |
| 48 | chat.py | /alias command | S | MED |
| 49 | search.py | Alias lookup in search() | S | MED |
| 50 | health.py [NEW] | Weekly index health report | M | LOW |

---

## Phase 4: GUI & UX Surface (17 updates)

### Batch 4A — Flask Backend + React Shell (IDs 51–58)

| # | File | Title | Effort | Impact |
|---|------|-------|--------|--------|
| 51 | gui.py [NEW] | Flask backend scaffold | M | HIGH |
| 52 | gui.py [NEW] | Flask /search endpoint | S | HIGH |
| 53 | gui.py [NEW] | Flask /open endpoint | XS | MED |
| 54 | gui.py [NEW] | Flask /preview endpoint | M | HIGH |
| 55 | templates/index.html [NEW] | React app scaffold | M | HIGH |
| 56 | templates/index.html | Search bar component | S | HIGH |
| 57 | templates/index.html | Results table component | M | HIGH |
| 58 | static/icons.js [NEW] | File type icon set | S | MED |

### Batch 4B — Preview + Polish (IDs 59–67)

| # | File | Title | Effort | Impact |
|---|------|-------|--------|--------|
| 59 | templates/index.html | Confidence score bar | S | MED |
| 60 | templates/index.html | Preview panel — text snippet | S | HIGH |
| 61 | gui.py | Preview panel — image thumbnail | S | MED |
| 62 | gui.py | Preview panel — PDF first page | S | MED |
| 63 | templates/index.html | Keyboard shortcut system | S | HIGH |
| 64 | tray.py [NEW] | System tray icon (pystray) | M | MED |
| 65 | filechat-gui [NEW] | App launcher script | XS | HIGH |
| 66 | templates/index.html | Dark/light mode toggle | S | LOW |
| 67 | templates/index.html | GUI stats dashboard | M | LOW |

---

## Phase 5: Stability & Hardening (13 updates)

### Batch 5A — Performance & Safety (IDs 68–75)

| # | File | Title | Effort | Impact |
|---|------|-------|--------|--------|
| 68 | indexer.py | WAL checkpoint optimization | XS | MED |
| 69 | search.py | SQLite connection pooling | S | MED |
| 70 | search.py | Query result cache (TTL=30s) | S | MED |
| 71 | indexer.py | DB integrity check on startup | XS | MED |
| 72 | indexer.py | Graceful shutdown — flush pending | S | MED |
| 73 | search.py | Fuzzy cache memory limit | XS | LOW |
| 74 | search.py | Ollama rate limiter | S | MED |
| 75 | indexer.py | Max file size filter | XS | LOW |

### Batch 5B — Tooling & Config (IDs 76–80)

| # | File | Title | Effort | Impact |
|---|------|-------|--------|--------|
| 76 | chat.py | /rebuild command | S | MED |
| 77 | setup.sh | rapidfuzz + pymupdf install | XS | MED |
| 78 | indexer.py | Indexer memory cap | S | MED |
| 79 | doctor.py [NEW] | filefinder-doctor CLI | M | LOW |
| 80 | config.json [NEW] | Centralized settings | S | MED |

---

## Dependency Graph

```
Phase 1 (Search Quality) ← no deps, start here
Phase 2 (Semantic)       ← depends on P1 (FTS5 infrastructure)
Phase 3 (Behavioral)     ← depends on P1 (scoring system)
Phase 4 (GUI)            ← depends on P1+P2 (search APIs)
Phase 5 (Hardening)      ← depends on P1+P2+P3 (all features exist)
```

## Progress Tracking

- [x] Phase 1 Batch A (12 items)
- [x] Phase 1 Batch B (8 items)
- [x] Phase 2 Batch A (10 items)
- [x] Phase 2 Batch B (8 items)
- [x] Phase 3 Batch A (7 items)
- [x] Phase 3 Batch B (5 items)
- [x] Phase 4 Batch A (8 items)
- [x] Phase 4 Batch B (9 items)
- [x] Phase 5 Batch A (8 items)
- [x] Phase 5 Batch B (5 items)
