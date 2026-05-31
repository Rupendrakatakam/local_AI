# FileChat — Technical Requirements Document (TRD)

---

## Architecture Philosophy

FileChat is built on **layered retrieval with graceful degradation**. Each retrieval tier is independently functional, and the cascade ensures that if any tier fails or is unavailable, the next tier picks up.

This is NOT a microservices architecture — it is a cohesive local process with clean module boundaries. The guiding architectural principle: **add zero mandatory external dependencies post-installation.**

---

## Current Architecture Map

```
┌──────────────────────────────────────────────────────────────────┐
│  User Interfaces                                                  │
│  chat.py (CLI) ─── gui.py (Flask SPA) ─── tui.py (Textual)       │
└─────────────────────────┬────────────────────────────────────────┘
                          │ calls search(query)
┌─────────────────────────▼────────────────────────────────────────┐
│  search.py — 7-Tier Cascading Retrieval Engine                   │
│                                                                  │
│  Tier 0:   Alias check         → instant, no DB                  │
│  Tier 0a:  Exact name match    → WHERE name = ? COLLATE NOCASE   │
│  Tier 1:   FTS5 search         → BM25, <10ms                     │
│  Tier 2:   LLM intent + FTS5  → Ollama parsed, ~150ms           │
│  Tier 3–5: Relaxation cascade  → drop ext → drop dir → OR mode  │
│  Tier 6.5: Trigram fuzzy       → Dice coefficient, typos        │
│  Tier 7:   RapidFuzz           → last resort, WRatio            │
│                                                                  │
│  + Semantic search (LanceDB, parallel)                           │
│  + RRF fusion (keyword + semantic + content)                     │
│  + Behavioral boost (RFM + workspace affinity + time-of-day)    │
└──────┬─────────────────────┬────────────────────────────────────┘
       │                     │
┌──────▼──────┐    ┌─────────▼────────────────────────────────────┐
│ behavior.py │    │  SQLite Shard Pool                           │
│ behavior.db │    │  ~/.local/share/filefinder/index_<dir>.db    │
│             │    │  Tables per shard:                           │
│ opens       │    │  ├── files (PRIMARY: path)                   │
│ copies      │    │  ├── files_fts (FTS5 virtual)                │
│ searches    │    │  ├── name_trigrams                           │
│             │    │  ├── file_content_fts (FTS5 virtual)         │
│ RFM scoring │    │  ├── file_tags                               │
│ workspace   │    │  ├── file_hashes                             │
│ time-of-day │    │  └── embedding_hashes                        │
└─────────────┘    └────────────────────────────────────────────┘
                          ▲ writes
┌─────────────────────────┴────────────────────────────────────────┐
│  indexer.py — Watchdog Daemon (systemd service)                  │
│  full_scan() → upsert() → explicit DELETE + INSERT + trigrams    │
│  inotify / watchdog → Debouncer (500ms) → upsert / delete        │
│                                                                  │
│  embedder.py — Background Pipeline                               │
│  PriorityQueue → text extraction → MiniLM chunks → LanceDB       │
│  CLIP images → LanceDB image_chunks table                        │
│  Auto-tagger → separate queue → Ollama (lower priority)          │
└──────────────────────────────────────────────────────────────────┘
```

---

## Technology Decisions

### Frontend

| Component | Current | V1 Target | Rationale |
|-----------|---------|-----------|-----------|
| Framework | Vanilla JS + Fetch | React + Vite | Component reuse, live streaming results |
| State | In-memory JS object | Zustand | Lightweight, no Redux overhead |
| UI System | Custom CSS variables | Tailwind CSS (CDN) | Utility-first, no build step |
| Desktop App | Flask in browser | Tauri (Rust + WebView) | ~30MB vs ~150MB; near-zero startup |

### Backend

| Component | Decision | Rationale |
|-----------|----------|-----------|
| Language | Python 3.10+ | Type-hinted, strong ecosystem for ML and SQLite |
| Framework | Flask → FastAPI (Team Edition) | Flask sufficient for single-user; FastAPI async for concurrent API |
| API Design | REST + JSON | Simple resource model; GraphQL adds complexity without benefit |

### Database

| Role | Technology | Rationale |
|------|-----------|-----------|
| Primary index | SQLite (WAL mode, sharded) | Zero infra, ACID, FTS5 native, excellent read-concurrency under WAL |
| Filename search | SQLite FTS5 | Co-located with primary DB; BM25 ranking |
| Content search | SQLite FTS5 (`file_content_fts`) | Same shard file; rowid-based join for performance |
| Vector search | LanceDB | Columnar, local file, zero infra |
| Behavioral data | SQLite (`behavior.db`) | Separate file for clean privacy clearing |
| Query cache | In-memory Python dict (TTL=30s) | Single-user; Redis for Team Edition |
| Analytics (Team) | DuckDB | Columnar, fast aggregations, zero infra |

### Infrastructure

| Tier | Solution |
|------|----------|
| Single user | systemd user service |
| Team Edition | Docker Compose (indexer + API + Redis) |
| Enterprise | Kubernetes |
| CI/CD | GitHub Actions (matrix: Python 3.10/3.11/3.12, Ubuntu/macOS/Windows) |
| Monitoring (Team) | Prometheus + Grafana + Loki |

### AI Layer

| Component | Current | V1/V2 Upgrade |
|-----------|---------|---------------|
| LLM | Ollama / phi3:mini | Configurable; llama.cpp direct for lower latency |
| Text embeddings | all-mpnet-base-v2 (768-dim) | bge-large-en-v1.5 (1024-dim) for +10% accuracy |
| Image embeddings | clip-ViT-B-32 | Unchanged |
| Vector DB | LanceDB | Qdrant for Team Edition (distributed, HTTP API) |

---

## Service Architecture

### Current: Single-Process with Threads

```
Process 1: indexer.py (systemd service)
├── main thread: watchdog event loop
├── Debouncer threads (per-file timers, one Lock per shard)
├── EmbeddingPipeline worker thread (PriorityQueue)
├── EmbeddingPipeline tag worker thread (separate Queue)
└── WAL checkpoint thread (5-minute interval)

Process 2: gui.py / chat.py (user-initiated)
├── Flask app (main + request threads via gunicorn)
├── Module-level ThreadPoolExecutor (shard query parallelism)
└── search.py (shared library)

Shared resources:
├── SQLite shard files (WAL mode — concurrent readers safe)
├── LanceDB directory (single writer, multiple readers)
└── behavior.db (writes serialized via threading.Lock)
```

### V1 Target: Modular Monolith

```
FileChat Core Process
├── Indexer Module (watchdog, per-shard locks)
├── Search API Module (FastAPI, async)
├── Embedding Pipeline Module (async workers, separate tag queue)
└── Storage Layer
    ├── SQLite Shards
    ├── LanceDB
    ├── behavior.db
    └── aliases.json
```

### V3 Team Edition: Selective Microservices

Decompose only services with divergent scaling requirements:

```
Indexer Service (per host, writes to shared NFS)
Search API Service (horizontally scaled, stateless)
Embedding Service (GPU host, separate from CPU services)
    │
    └── Shared Storage (NFS / object store)
        ├── PostgreSQL (file metadata, sharded)
        ├── Qdrant (vector search, clustered)
        ├── Redis (query cache, pub/sub)
        └── ClickHouse (behavioral analytics, columnar)
```

**Rule:** Never decompose prematurely. Monolith → modular monolith → selective microservices only when a service has scaling requirements that differ from the rest.

---

## API Architecture

### REST Endpoints (Current)

```
GET  /api/search?q={query}&limit={n}
     Response: {results: [{path, name, extension, size, size_human, mtime}],
                is_fuzzy, query}

POST /api/open
     Body: {path, query}
     Response: {ok: bool}

GET  /api/preview?path={path}
     Response: {type: "text"|"pdf"|"image"|"table"|"unknown",
                content, extension, pages?}
     Security: path MUST be validated within WATCH_PATH (path traversal guard)

GET  /api/stats
     Response: {total, ready, embeddings: {done, total, pct, errors}, health}

GET  /api/analytics
     Response: {top_queries, top_files, hourly: [24 int values]}

GET  /api/duplicates
     Response: {duplicates: [{hash, count, wasted_size, files}]}

GET  /api/smart_folders
     Response: {suggestion: "<markdown html>"}

POST /api/chat
     Body: {message}
     Response: {reply: "<html>"}
```

### V1 Additions

```
POST   /api/alias          Body: {name, path}
DELETE /api/alias/{name}
GET    /api/alias

GET    /api/health         Full system health JSON

# Team Edition
POST   /auth/token         Returns JWT (RS256)
GET    /api/audit?from&to  Paginated audit log (tamper-evident)
```

### WebSocket (V1 — Streaming Results)

```
WS /ws/search

Client sends:  {q: "query", requestId: "uuid"}

Server streams:
  {requestId, tier: "fts5",     results: [...], done: false}  # <10ms
  {requestId, tier: "semantic", results: [...], done: false}  # ~60ms later
  {requestId, tier: "fused",    results: [...], done: true}   # final ranked
```

Eliminates the perception of waiting for Ollama — FTS5 results appear immediately while semantic loads in the background.

### Event Schema (V3 Team Edition — Redis Streams)

```json
{
  "event": "file.indexed",
  "timestamp": 1717000000.0,
  "payload": {
    "path": "/home/user/docs/report.pdf",
    "shard": "index_docs.db",
    "size": 204800,
    "extension": "pdf"
  },
  "version": "1.0"
}
```

Consumer groups:
- `embedding-workers` → consume `file.indexed`
- `tag-workers` → consume `file.indexed` (lower priority)
- `analytics` → consume all events → ClickHouse
- `cache-invalidator` → consume `file.indexed`/`file.deleted` → flush Redis cache

---

## Security Architecture

### Authentication

| Tier | Method |
|------|--------|
| Single-user | None (127.0.0.1 binding only) |
| Team Edition | JWT (RS256), 8-hour expiry, httpOnly refresh cookies |
| Enterprise | SAML 2.0 SSO |

### Authorization (Team Edition)

```
Roles: admin | analyst (read+search) | readonly (search only)

Permissions example:
{
  "resource_pattern": "/projects/confidential/*",
  "action": "search",
  "allowed_roles": ["admin"]
}
```

### Encryption

| Layer | Solution |
|-------|----------|
| In transit | HTTPS (self-signed for local Tauri app; Let's Encrypt for team server) |
| At rest (V2) | SQLCipher AES-256 on index.db + behavior.db |
| Vectors | LanceDB files protected by filesystem encryption (LUKS/FileVault) |
| Secrets | OS keychain via `keyring` library — never in config files |

### Threat Model

| Threat | Severity | Mitigation |
|--------|----------|-----------|
| LanceDB SQL injection via apostrophe in filename | Medium | `json.dumps(path)` for all delete operations |
| `/api/preview` path traversal | High | Validate `resolved.relative_to(watch_path)` before serving |
| FTS5 query injection | Low | All queries use parameterized `MATCH ?` |
| Behavior DB readable by other users | Medium | `chmod 600 behavior.db`, `chmod 700` parent |
| Ollama returning malicious JSON | Low | JSON extracted by position (`raw.find("{")`); only structured fields used |
| Credential files indexed | High | Default `.filefinder_ignore` blocks `*.key`, `*.env`, `id_rsa*`, `*secret*` |

---

## Scalability Architecture

### 1K Users — Current State
Single-user per machine. SQLite WAL handles concurrent reads from CLI + GUI simultaneously. No concurrency concerns.

### 10K Users — V2 (Parallel Deployments)
Still single-user per machine. 10K independent deployments. Challenge: distribution and updates. Solution: auto-update mechanism (`--update` flag checking GitHub releases, offline-capable via signed JWT license keys).

### 100K Users — V2 Pro
Desktop app distribution. No server-side search scaling needed (each user's search is local). Server infrastructure only handles license validation + optional encrypted behavioral backup.
Target infra cost: <$0.01/user/month.

### 1M Users — V3 Team Edition
Team Edition deployments. Each team runs their own server. Central infrastructure serves license validation only (stateless auth + Postgres).
**Key insight:** FileChat's architecture is fundamentally single-user-per-machine. Scaling to 1M users means 1M independent machines doing their own search — not 1M queries hitting one server.

### 10M Users — V4 Platform (FileChat API)
Read-heavy API workload from IDE plugins and AI agents. Requires:
- Edge caching for common query patterns
- Horizontally scaled search API workers
- Qdrant for distributed vector search
- ClickHouse for behavioral analytics

---

## Critical Known Issues (Must Fix Before Production)

| ID | Issue | Impact | Fix |
|----|-------|--------|-----|
| P1.1 | `_cache_set()` never called — cache is dead code | Every search hits Ollama, even repeated queries | Wrap search() in `_search_uncached()`, call `_cache_set()` on every return |
| P1.2 | FTS5 tokenizer `unicode61` doesn't split `_` or `-` | FTS5 misses 60%+ of technical filenames | Change to `tokenize='unicode61 separators "_-."'` + rebuild |
| P1.3 | `INSERT OR REPLACE` causes FTS5 ghost rows on updates | DB corruption accumulates over weeks | Change to explicit `DELETE` then `INSERT` |
| P1.4 | LanceDB `f'path = "{path}"'` SQL injection | Silent failures for filenames with apostrophes | Use `f"path = {json.dumps(path)}"` |
| P2.1 | 150 SQLite connections opened per search (3 per result × 50 results) | 200–500ms added to every search ranking pass | Persistent behavior.db connection + `get_all_boosts_batch()` |
| P2.2 | ThreadPoolExecutor created per search call (not module-level) | Thread spawn overhead on every search | Promote to module-level persistent executor |
| P2.3 | Debouncer `flush_all()` deadlock (holds self._lock while calling upsert()) | Hangs on shutdown under concurrent indexing | Collect pending under lock, release lock, then call upsert() |
| P3.1 | Global write lock serializes ALL shard writes | No parallel writes to different shards | `defaultdict(threading.Lock)` keyed by shard path |
| P3.2 | VACUUM holds write lock for seconds | All writes stall every 5 minutes | Checkpoint/VACUUM on dedicated connections outside write lock |
| P3.3 | Semantic hydration is O(N×M) single-row queries | 450 DB calls for 45 candidates across 10 shards | Batch with `WHERE path IN (...)` |
| P3.4 | Connection leaks in `_content_search_single()` | File descriptor exhaustion over time | Wrap all DB operations in `try/finally: conn.close()` |
