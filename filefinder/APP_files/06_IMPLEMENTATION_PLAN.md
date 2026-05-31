# FileChat — Implementation Plan

---

## Phase 0: Stabilization (Weeks 1–2)

### Goal
Fix all P1 critical bugs identified in the architecture audit before building any new features. A shaky foundation compounds every subsequent sprint.

### Deliverables

| Task | File | Effort | Impact |
|------|------|--------|--------|
| Wire `_cache_set` into `search()` wrapper | search.py | 15 min | 150ms → <1ms cached queries |
| Fix FTS5 tokenizer (`separators "_-."`) + rebuild | db_utils.py | 30 min + rebuild | Fixes 60% of FTS5 misses |
| Fix `INSERT OR REPLACE` → explicit `DELETE + INSERT` | indexer.py | 30 min | Stops FTS5 ghost row accumulation |
| Fix LanceDB path injection (`json.dumps(path)`) | embedder.py | 10 min | Prevents failures on `'` in filenames |
| Add path traversal guard to `/api/preview` | gui.py | 20 min | Security fix |
| Expand `test_lens.py` to 50 benchmark queries | test_lens.py | 2 hours | Regression baseline |

### Exit Criteria
All 5 P1 bugs resolved. Benchmark passes 200ms P95. `doctor.py` reports all green. `A(q(a,b)).nb` is findable by exact name.

---

## Phase 1: Foundation (Weeks 3–6)

### Goal
Fix all high-priority performance and correctness issues. Establish the stable base all future features build on.

### Sprint 1 (Week 3–4): Core Correctness

| Task | File | Notes |
|------|------|-------|
| Per-shard write locks (`defaultdict(threading.Lock)`) | indexer.py | Replaces global `db_lock` |
| Fix `flush_all()` deadlock | indexer.py | Collect under lock, release, then upsert |
| Fix WAL checkpoint (release write lock first) | indexer.py | Prevents 1–5s write stalls every 5 min |
| Fix VACUUM to use dedicated connections | indexer.py | Prevents `SQLITE_BUSY` under load |
| Persistent behavior.db connection | behavior.py | Module-level `_get_behavior_conn()` |
| `get_all_boosts_batch(paths)` | behavior.py | One DB call per search, not 150 |
| Update `_rerank()` to accept pre-fetched boosts | search.py | Wire batch boost into scoring |

**Sprint 1 Exit:** Behavior scoring latency <5ms (was 200–500ms). Write lock contention eliminated.

### Sprint 2 (Week 5–6): Performance

| Task | File | Notes |
|------|------|-------|
| Promote `ThreadPoolExecutor` to module level | search.py | Persistent pool, not per-call |
| Batch semantic hydration (`WHERE path IN (...)`) | search.py | 450 queries → ≤10 per search |
| Fix all connection leaks (`try/finally: conn.close()`) | search.py | Audit all `_*_single()` functions |
| Add named loggers to all modules | all | Replace bare `except: pass` with `log.debug()` |
| Parallel semantic + keyword search | search.py | Submit semantic to executor at search start |
| `content_fts` join on `rowid` (not `path` string) | db_utils.py + embedder.py | Proper B-tree join |

**Sprint 2 Exit:** Search P95 <150ms including Ollama. Connection pool stable under 1-hour soak test.

---

## Phase 2: MVP Polish (Weeks 7–12)

### Goal
Production-ready single-user experience. CLI and GUI are both excellent. Full test coverage.

### Sprint 3 (Week 7–8): Real-Time GUI

| Task | Description |
|------|-------------|
| WebSocket streaming search | FTS5 results appear <10ms; semantic streams in later |
| Skeleton loaders | Replace spinner — no layout shift during loading |
| Complete keyboard shortcut system | All actions reachable without mouse |
| Confidence bar color fix | Correct green/yellow/red thresholds |
| File type icon completeness | Cover all common extensions |
| Preview: syntax highlighting | highlight.js for code files |
| Preview: Markdown rendering | marked.js for .md files |
| Preview: CSV table view | Papa Parse for .csv files |

### Sprint 4 (Week 9–10): Testing & CI

| Task | Description |
|------|-------------|
| Full regression test suite | 100 queries with expected results; `pytest test_search.py` |
| GitHub Actions CI | Matrix: Python 3.10/3.11/3.12, Ubuntu/macOS |
| Type checking | `mypy search.py indexer.py behavior.py embedder.py` |
| Linting | `ruff check .` with pre-commit hook |
| `setup.sh` hardened | Idempotent; checks Python version; handles pip failures gracefully |
| `doctor.py --repair` enhanced | Handles content FTS + embedding hash rebuilds |

### Sprint 5 (Week 11–12): Features & UX

| Task | Description |
|------|-------------|
| Chat assistant polish | File path pills (clickable), conversation history, clear button |
| Duplicate detector UI | Group display, wasted space summary, reveal-in-files button |
| Smart folders UI | Folder analysis table + LLM suggestions + export |
| Auto-tag display in preview | Show tags in preview panel sidebar |
| Behavioral analytics dashboard | Charts wired to `/api/analytics` |
| Alias management in GUI | Create/delete/list aliases from web UI |
| Stats dashboard complete | All metrics live, Prometheus endpoint |

**Phase 2 Exit:** GUI scores >4.0/5 in user testing (5 participants). All user stories CS-001 through CS-005 pass acceptance criteria.

---

## Phase 3: Cross-Platform (Weeks 13–20)

### Goal
macOS support. Tauri desktop app. Global hotkey. Code symbol indexing.

### Sprint 6 (Week 13–14): macOS Port

| Task | Notes |
|------|-------|
| Platform detection layer | `platform.system()` → route to OS backends |
| macOS: launchd plist | Replaces systemd; auto-starts on login |
| macOS: `open` command | Replaces `xdg-open` |
| macOS: `pbcopy` | Replaces `xclip`/`xsel` |
| macOS: FSEvents via watchdog | Already supported; verify inotify-equivalent |
| Windows foundation | `os.startfile()`, `pyperclip`, `ReadDirectoryChangesW` |
| pathlib audit | Confirm all path operations are cross-platform |

### Sprint 7 (Week 15–16): Tauri Desktop App

| Task | Notes |
|------|-------|
| Tauri project scaffold | `cargo create-tauri-app filechat` |
| Port Flask GUI HTML into Tauri WebView | Minimal changes — same HTML/JS |
| Global hotkey plugin | `tauri-plugin-global-shortcut`: `Super+Space` |
| Floating search window | Frameless overlay mode, centered, auto-dismiss on Escape |
| System tray in Tauri | Replace `pystray` with Tauri tray API |
| App icon + installer | `.dmg` (macOS), `.AppImage` (Linux), `.msi` (Windows) |

### Sprint 8 (Week 17–18): Code & Search Extensions

| Task | Notes |
|------|-------|
| tree-sitter integration | Parse `.py`, `.js`, `.ts`, `.cpp`, `.rs`, `.go` |
| `code_symbols` FTS5 table | Stores function/class/variable names |
| `code:` search prefix | Routes to `code_symbols` table |
| Browser extension (Chrome) | Calls `localhost:5000/api/search` |
| Firefox extension port | Same manifest, different build target |
| API rate limiting | `flask-limiter` for `/api/search` (external callers) |

### Sprint 9 (Week 19–20): Beta

| Task | Notes |
|------|-------|
| Beta program: 50 users | Linux + macOS, mix of personas |
| Telemetry-free bug reporting | GitHub issue template with `doctor.py` output |
| Hotfix cycle | Weekly patch releases |
| Documentation site | `docs.filechat.dev` with search, getting started, config reference |

**Phase 3 Exit:** macOS full test suite passes. Global hotkey reliable across 3 desktop environments. Beta users report <2 critical bugs.

---

## Phase 4: Public Launch (Weeks 21–26)

### Sprint 10 (Week 21–22): Pro Tier

| Task | Notes |
|------|-------|
| License key system | Signed JWT with expiry; offline-capable validation |
| Stripe integration | One-time + subscription billing |
| Pro feature gates | `bge-large-en-v1.5` embeddings, encrypted backup |
| Behavioral graph backup | Encrypted `behavior.db` backup to configurable path |
| Auto-update mechanism | `--update` flag checks GitHub releases; downloads + verifies signature |

### Sprint 11 (Week 23–24): Launch Prep

| Task | Notes |
|------|-------|
| Documentation site complete | All features documented with examples |
| 3-minute demo video | "Find any file in 10 seconds" |
| GitHub README rewrite | Compelling, scannable, with benchmarks |
| Product Hunt assets | Screenshots, GIF, tagline, first comment |
| HN "Show HN" draft | Technical depth — this audience needs the architecture story |

### Sprint 12 (Week 25–26): Launch

| Task | Notes |
|------|-------|
| Load test license server | 1000 concurrent validations |
| Launch: HN + PH simultaneously | Monday 9am PT for maximum upvote window |
| 48-hour monitoring | On-call rotation, rollback plan ready |
| Post-launch: triage and fix | Top 3 reported issues in first week |

**Phase 4 Exit:** 1,000 GitHub stars in 2 weeks. 100 Pro subscribers in 30 days.

---

## Phase 5: Scale (Months 7–12)

| Milestone | Description |
|-----------|-------------|
| Windows installer GA | NSIS installer, Windows Service, full test suite |
| FileChat API v1 | JWT auth, rate limiting, versioned endpoints |
| VS Code extension | Calls FileChat API for file context suggestions |
| 1M+ file support | Bloom filter pre-screening for trigram search |
| BGE-large default (Pro) | Better semantic accuracy; configurable in config.json |
| Usage analytics (local only) | Self-hosted ClickHouse or DuckDB for Pro users |

---

## Phase 6: Enterprise (Year 2)

| Milestone | Description |
|-----------|-------------|
| Team Edition GA | Shared NFS index, per-user behavioral models |
| JWT auth service | FastAPI + RS256, 8-hour expiry |
| SAML 2.0 SSO | Enterprise identity provider integration |
| SQLCipher encryption | AES-256 on index.db and behavior.db |
| Audit logging | Tamper-evident append-only log (hash chain) |
| Admin dashboard | User management, index health, search analytics |
| First enterprise contract | $50K+ ACV, dedicated support, SLA |

---

## Phase 7: AI Expansion (Year 3)

| Milestone | Description |
|-----------|-------------|
| MCP server interface | `filefinder://search?q=...` for AI agents |
| Conversational file assistant | Full chat history, proactive suggestions |
| Predictive file surfacing | Calendar + behavior → proactive recommendations |
| Learned reranker | Logistic regression on implicit feedback (opens/skips) |
| Fine-tuned intent extraction | Domain-specific model for medical/legal/scientific |
| Knowledge graph | File–entity–concept relationships; visual explorer |

---

## Phase 8: Platform (Years 4–5)

| Milestone | Description |
|-----------|-------------|
| FileChat SDK (Python + TypeScript) | For IDE plugin and agent developers |
| Plugin marketplace | Community-built index types, custom ranking models |
| JetBrains plugin | IntelliJ/PyCharm file context integration |
| FileChat as MCP standard | Register in MCP server directory; reach out to Anthropic, Cursor, Continue.dev |
| Enterprise API tier | Usage-based billing ($0.001/query) |
| Distributed index | Multi-site enterprise deployment |

---

## Team Scaling Plan

| Phase | Team |
|-------|------|
| Phase 0–2 | 1 senior backend engineer |
| Phase 3–4 | + 1 full-stack, + 0.5 designer |
| Phase 5 | + 1 backend (API/infra), + 1 QA |
| Phase 6 | + 1 sales, + 1 customer success |
| Phase 7–8 | Total ~12 engineers, 2 designers, 3 sales/CS |
