# FileChat — Product Requirements Document (PRD)

---

## Problem Definition

### User Pain Points

1. **The Lost File Problem.** The average knowledge worker spends 2.5 hours per week searching for files. Files exist — they simply cannot be found.
2. **The Name Forgetting Problem.** Users remember what a file was *about* but not what they named it. "That PDF about transformer architectures from 2022" is a semantic description, not a filename.
3. **The Typo Problem.** Real users mistype filenames. Existing tools return zero results for `reusme.pdf` — a UX failure when the system clearly knows what was meant.
4. **The Depth Problem.** Files buried 8 levels deep in a directory tree are effectively invisible to casual search. Native OS search degrades with depth.
5. **The Privacy Problem.** Windows Search indexes to the cloud. macOS Spotlight transmits query metadata via Siri suggestions. For users handling sensitive data (legal, medical, research, government), these tools are non-starters.
6. **The Context Blindness Problem.** No OS search tool knows you open `report.pdf` every Monday morning or that `thesis.tex` is your most critical file. All results are ranked by filename or recency — never by behavioral relevance.

### Existing Solutions and Gaps

| Solution         | What It Does                        | Critical Gap |
|------------------|-------------------------------------|-------------|
| `find` / `locate`| Exact filename match, fast          | No typo tolerance, no NL, no ranking |
| macOS Spotlight  | Content + filename, fast            | Privacy concerns, no behavioral learning, no semantic search |
| Windows Search   | Full-text, integrated               | Cloud telemetry, slow on large filesystems, no NL |
| Alfred / Raycast | Fast launcher with plugins          | Not a search engine, no AI, no content search |
| Everything (Win) | Blazing fast filename index         | Exact match only, no semantics, no NL |
| Recoll           | Full-text local search              | No NL, terrible UX, no behavioral learning |

### Market Gap

No tool combines: **local execution + NL understanding + semantic search + behavioral personalization + typo tolerance** in a single coherent product.

---

## User Personas

### Persona 1: Rupendra — The Graduate Researcher

- **Age/Role:** 26, PhD candidate, robotics/ML, Ubuntu Linux
- **File Volume:** 680K+ files — papers, code, datasets, notes
- **Technical Skill:** Expert — CLI, systemd, Python, SQLite
- **Goals:** Find papers by concept; locate code files by algorithm type; retrieve datasets referenced in notes from 6 months ago
- **Frustrations:** `find` is too rigid; Spotlight unavailable on Linux; file managers are slow at 680K files; cryptic convention filenames like `A(q(a,b)).nb` are unsearchable
- **Jobs To Be Done:**
  - "When I remember what a paper was *about*, find it."
  - "When I vaguely remember a function name, locate the file."
  - "Surface files I was working on last Tuesday without remembering their names."

### Persona 2: Priya — The Privacy-Conscious Developer

- **Age/Role:** 32, Senior Engineer at fintech, macOS + Linux
- **File Volume:** 200K+ files — client code, financial documents, configs
- **Technical Skill:** Expert
- **Goals:** Search code and documents with zero data leaving the machine; find files across multiple projects; build automation tools that query the local filesystem programmatically
- **Frustrations:** Cloud search tools violate her company's data handling policies; `grep -r` is slow and requires exact terms; no tool exposes a clean API for scripting
- **Jobs To Be Done:**
  - "Give me a search tool with a REST API I can call from automation scripts."
  - "Search my codebase by concept, not grep pattern."
  - "Prove to my security team no file metadata ever leaves this machine."

### Persona 3: Marcus — The Knowledge Worker

- **Age/Role:** 44, Senior Analyst at consulting firm, Windows + MacBook
- **File Volume:** 200K+ proposals, reports, client docs
- **Technical Skill:** Intermediate — GUI only, no CLI
- **Goals:** Find documents by topic or client name; surface files relevant to the current project; avoid remembering exact filenames
- **Frustrations:** Windows Search misses documents frequently; can't search *inside* PDFs from the launcher; no concept of "files related to this project"
- **Jobs To Be Done:**
  - "I remember writing a slide about market sizing for the APAC client — find it."
  - "Show me everything I touched this week related to the merger project."

### Persona 4: Elena — The IT/DevOps Admin

- **Age/Role:** 38, DevOps Lead, manages server filesystems and shared drives
- **Technical Skill:** Expert — systemd, Docker, Ansible
- **Goals:** Deploy FileChat for the engineering team on a shared NFS mount; audit file access patterns; ensure sensitive directories are never indexed
- **Jobs To Be Done:**
  - "Deploy one FileChat instance all 40 engineers can query."
  - "Show me an audit log of all file searches for compliance."
  - "Exclude `/secrets` and `/credentials` from indexing permanently."

---

## User Stories

### Core Stories

| ID | Story | Priority | Acceptance Criteria |
|----|-------|----------|---------------------|
| CS-001 | As a researcher, I want to type a partial filename and get the correct file as result #1 within 200ms | P0 | `estimation inertial` returns `On-Line_Estimation_of_Inertial_Parameters.pdf` as #1 |
| CS-002 | As a user, I want to describe a file in natural language and get relevant results even if the filename doesn't match | P0 | Ollama parses intent; results include name OR content matches; graceful regex fallback if Ollama offline |
| CS-003 | As a user, I want typos to be corrected so `reusme` finds `Resume_Final.pdf` | P0 | Trigram similarity ≥0.45 triggers match; result marked with fuzzy indicator |
| CS-004 | As a GUI user, I want results to appear as I type with <300ms debounce | P0 | Keystroke → debounce → API → render total <500ms; cached queries <50ms |
| CS-005 | As a user, I want `/open 3` to open the third result in its default application | P0 | File opens via xdg-open; open event recorded in behavior.db |

### Power User Stories

| ID | Story | Priority | Acceptance Criteria |
|----|-------|----------|---------------------|
| PU-001 | As a developer, I want `/re .*LQR.*\.pdf$` regex search bypassing the LLM | P1 | No Ollama call; results within 50ms |
| PU-002 | As a power user, I want `/alias set thesis ~/Research/thesis.docx` for instant access | P1 | Alias lookup before all search tiers; returns exact file instantly |
| PU-003 | As a developer, I want `content:"Kalman filter"` to find documents containing that text | P1 | Routes to `file_content_fts`; results within 100ms for indexed files |
| PU-004 | As a privacy user, I want `.filefinder_ignore` to permanently exclude directories | P1 | Matching paths never inserted into index; existing entries removed on next scan |

### Admin Stories

| ID | Story | Priority | Acceptance Criteria |
|----|-------|----------|---------------------|
| AD-001 | As an admin, `python3 doctor.py` gives a pass/fail health report | P1 | All 9 checks run; `--repair` rebuilds FTS5 + trigrams |
| AD-002 | As an admin, `/rebuild` regenerates FTS5 and trigram tables non-destructively | P1 | Rebuilds from existing `files` table data without data loss |
| AD-003 | As an enterprise admin, sensitive directory exclusions apply system-wide | P2 | Managed config enforced across all machines |

### Enterprise Stories

| ID | Story | Priority |
|----|-------|----------|
| EN-001 | Deploy FileChat as a systemd service indexing a shared NFS mount | P1 |
| EN-002 | Audit log of every search query and file access for GDPR compliance | P2 |
| EN-003 | Database encrypted at rest via SQLCipher (V2) | P2 |

### Future Stories

| ID | Story | Phase |
|----|-------|-------|
| FU-001 | "What was I working on last Tuesday?" → natural language file activity summary | V3 |
| FU-002 | VS Code plugin calls FileChat API for contextual file suggestions | V3 |
| FU-003 | AI agent calls `GET /api/search` to retrieve local file context | V3 |

---

## Functional Requirements

### MVP Features

#### MVP-1: FTS5 Full-Text Filename Search
- **Description:** SQLite FTS5 virtual table indexing filenames and paths, tokenized on `_`, `-`, `.`, and space separators.
- **Purpose:** Sub-millisecond exact and prefix-based filename retrieval across 670K+ files with BM25 ranking.
- **Dependencies:** SQLite 3.35+, FTS5 module compiled in.
- **Critical Requirement:** Tokenizer must use `separators "_-."` — default `unicode61` does NOT split on underscores, breaking search for 60%+ of technical filenames.
- **Risks:** Ghost row accumulation if using `INSERT OR REPLACE` instead of explicit `DELETE + INSERT` on updates.
- **Scalability:** Handles 2M files per shard.

#### MVP-2: Trigram Fuzzy Search
- **Description:** Pre-computed character trigrams in `name_trigrams` table. Dice coefficient similarity for typo tolerance. Threshold: 0.45.
- **Purpose:** Catch queries like `reusme`, `estimaton`, `roboitcs`.
- **Dependencies:** Triggered only when FTS5 + LIKE tiers return 0 results.
- **Scalability:** 670K files × 15 avg trigrams = ~10M rows ≈ 200MB. Acceptable to 5M files.

#### MVP-3: LLM Intent Parsing
- **Description:** Natural language queries sent to local Ollama (phi3:mini). Extracts `{keywords, extension, directory}` as JSON.
- **Purpose:** Enable queries like "find my tax report PDF in Downloads" without manual syntax.
- **Dependencies:** Ollama at `localhost:11434`. Regex fallback if offline.
- **Risks:** LLM output format inconsistency — requires robust JSON extraction with fallback parsing. Rate limited to 3 concurrent calls.

#### MVP-4: Background Real-Time Indexing
- **Description:** `indexer.py` as systemd user service. watchdog/inotify events. 500ms debounce. Batch commits every 500 files.
- **Purpose:** Index always current — new file saved → searchable within 500ms.
- **Risks:** inotify watch limit. Auto-fallback to PollingObserver with logged warning.

#### MVP-5: Behavioral Ranking (RFM)
- **Description:** Record open/copy events. RFM score = recency × frequency × monetary value. Applied as 0–25 point boost in reranking.
- **Critical Requirement:** Must use a persistent DB connection — opening 3 new connections per result (×50 results) adds 200–500ms latency per search.
- **Purpose:** Files you use most rank higher automatically.

#### MVP-6: Flask Web GUI
- **Description:** Single-page app at `localhost:5000`. Live search with 300ms debounce. File type icons, confidence bars, preview panel.
- **Purpose:** Accessible interface for non-CLI users.
- **Risks:** Flask dev mode is single-threaded. Production needs gunicorn/waitress.

---

### V1 Features

| Feature | Description |
|---------|-------------|
| Semantic Vector Search | MiniLM/MPNet embeddings in LanceDB; RRF fusion with keyword results |
| Image Semantic Search | CLIP embeddings; text-to-image retrieval |
| Content FTS | Extracted document text in FTS5; `content:` prefix search |
| Tauri Desktop App | Native Rust app replacing Flask-in-browser; ~30MB binary |
| Global Hotkey | `Super+Space` floating search window from anywhere on desktop |
| macOS Support | launchd, `open`, `pbcopy`, FSEvents |
| Streaming Search Results | WebSocket: FTS5 results in <10ms while semantic loads in background |

### V2 Features

| Feature | Description |
|---------|-------------|
| Code Symbol Indexing | tree-sitter parsing of .py/.js/.cpp etc; `code:` prefix |
| Windows Support | Windows Service, os.startfile(), ReadDirectoryChangesW |
| Encrypted Database | SQLCipher AES-256 on index.db and behavior.db |
| Team Edition | Shared NFS index, per-user behavioral models, JWT auth, admin dashboard |
| Browser Extension | Chrome/Firefox; `fc <query>` in address bar |

### V3 Features

| Feature | Description |
|---------|-------------|
| Conversational File Assistant | "What was I working on last Tuesday?" via full chat interface |
| Duplicate Detection Dashboard | MD5/SHA256 grouping; cleanup recommendations |
| FileChat API (External) | Authenticated REST; enables IDE plugins and AI agents |
| MCP Server Interface | AI agents call `filefinder://search?q=...` |
| Mobile Companion App | Flutter app on local network calling FileChat API |

---

## Non-Functional Requirements

### Performance

| Metric | Target |
|--------|--------|
| P50 search (cached) | <1ms |
| P50 search (FTS5, uncached) | <10ms |
| P95 search (full cascade + Ollama) | <250ms |
| Full scan (670K files) | <3 minutes |
| Real-time index update | <500ms post-event |
| GUI search debounce | 300ms |
| Memory (indexer idle) | <100MB RSS |
| Memory (indexer scanning) | <512MB RSS (enforced cap) |

### Reliability
- Indexer: 99.5% uptime via systemd `Restart=on-failure`, 5s backoff
- DB integrity checked on every startup via `PRAGMA integrity_check`
- FTS5 and trigrams auto-rebuilt if empty on startup
- Graceful shutdown: pending upserts flushed before exit
- WAL mode + periodic checkpoint: no committed write can be lost

### Security
- Zero outbound network connections (excluding Ollama on localhost)
- DB files: `chmod 600`; DB directory: `chmod 700`
- Default `.filefinder_ignore` excludes `*.pem`, `*.key`, `*.env`, `id_rsa*`, `*secret*`, `*password*`, `*credentials*`
- No telemetry, no crash reporting, no analytics pipeline
- `/api/preview` must validate path is within `WATCH_PATH` (path traversal prevention)
- All LanceDB delete operations use `json.dumps(path)` — no f-string SQL construction with raw paths

### Compliance
- **GDPR:** All data local-only. `/privacy clear` deletes `behavior.db` entirely. Right to erasure honored.
- **CCPA:** No data sold or shared.
- **HIPAA (Enterprise V3):** Encryption at rest, audit logs, access control.

### Accessibility
- WCAG 2.1 AA for GUI
- Full keyboard navigation (all actions reachable without mouse)
- Screen-reader-compatible terminal output via Rich
- Color contrast ≥4.5:1 for all text
- `prefers-reduced-motion` disables all animations
- Dark/light mode responding to OS preference
