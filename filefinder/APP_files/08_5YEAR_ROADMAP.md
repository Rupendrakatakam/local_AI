# FileChat — 5-Year Product Roadmap

---

## Year 1: Own the Filesystem

**Theme:** Nail the core. Make it indispensable for one persona (the power-user researcher/developer on Linux) before expanding.

### Product Evolution
- All critical architecture bugs fixed (FTS5 tokenizer, cache, RFM batching)
- macOS + Windows support
- Tauri desktop app with global `Super+Space` hotkey
- Code symbol indexing (`code:` prefix for function/class search)
- Browser extension (Chrome + Firefox)
- Pro tier launched ($8/month)
- `docs.filechat.dev` with full reference documentation

### Technical Evolution
- FTS5 fully correct (separators, ghost-row-free, rowid-based content join)
- Query cache functional (50× latency improvement for cached queries)
- WebSocket streaming (FTS5 results appear in <10ms)
- Module-level thread pool (persistent, not per-call)
- Batch behavior scoring (<5ms from 500ms)
- Full test suite with CI (Python 3.10/3.11/3.12 × Linux/macOS)
- Prometheus metrics endpoint

### AI Evolution
- Embedding-based synonym expansion (replaces static dict)
- `all-mpnet-base-v2` as default (better than MiniLM, same infra)
- Auto-tagging functional and visible in GUI
- Duplicate detection with hash-based grouping

### Revenue Evolution
- $0 → $25K MRR
- 1,000+ GitHub stars
- 300 Pro subscribers

### Team
- 1–2 engineers (1 backend, 1 part-time full-stack)
- No formal design resource yet (use the existing UI, improve incrementally)

---

## Year 2: Own the Desktop

**Theme:** Make FileChat the default file access method for knowledge workers, not just developers.

### Product Evolution
- Team Edition beta (shared NFS index, 10–50 users per deployment)
- VS Code extension (file context in the editor)
- FileChat API v1 (rate-limited, versioned, JWT-authenticated)
- Mobile companion app (iOS + Android, local network)
- Behavioral graph optional encrypted backup (Pro feature)
- Theming system (Monokai, Nord, Solarized, Gruvbox)
- Auto-update via built-in updater

### Technical Evolution
- FastAPI replaces Flask (async, better concurrent request handling)
- Redis cache for Team Edition (shared across workers)
- SAML 2.0 SSO (first enterprise prerequisite)
- SQLCipher encryption at rest (database AES-256)
- Audit logging (tamper-evident, hash-chained)
- PostgreSQL for team metadata (users, permissions, license data)
- Docker Compose deployment for Team Edition

### AI Evolution
- Learned reranker (logistic regression on implicit behavioral feedback)
- Semantic clustering for Smart Folders (HDBSCAN on embeddings)
- `multilingual-e5-large` available for non-English content (config.json)
- Image search via CLIP production-ready and documented

### Revenue Evolution
- $25K → $150K MRR
- First enterprise contract ($50K ACV)
- 5,000+ GitHub stars
- FileChat API in beta

### Team
- 5 engineers, 1 designer, 1 sales

---

## Year 3: Own Local Knowledge

**Theme:** Expand the indexed surface beyond files. FileChat becomes the universal query layer for everything on your machine.

### Product Evolution
- Team Edition GA
- Conversational File Assistant ("What was I working on last Tuesday?")
- Predictive file surfacing (proactive, not reactive)
- Local email indexing (Thunderbird `.mbox`, Apple Mail)
- Local calendar integration (`.ics` file parsing)
- Browser bookmark indexing
- Knowledge graph v1 (file–topic relationships, visual explorer)
- FileChat as MCP server (AI agent integration)
- Enterprise Edition: multi-site, air-gapped deployment option

### Technical Evolution
- MCP server interface registered in MCP directory
- Qdrant for Team Edition vector search (distributed, HTTP API)
- ClickHouse for team behavioral analytics (columnar, fast aggregations)
- Kubernetes for enterprise deployments (Helm chart)
- OpenTelemetry distributed tracing across services
- Fine-tuned intent extraction model (domain-specific: medical/legal/scientific)

### AI Evolution
- File Intelligence Agent (full conversational history, proactive recommendations)
- Organization Agent (semantic clustering + LLM suggestions + safe execution)
- Context Agent for VS Code (auto-surfaces related files on file open)
- MCP protocol: AI agents call FileChat for local file retrieval
- Morning briefing (calendar + behavior → proactive file recommendations)

### Revenue Evolution
- $150K → $500K MRR
- 10+ enterprise contracts
- FileChat API revenue begins (IDE plugin and agent ecosystem)
- $10M ARR target

### Team
- 12 engineers, 2 designers, 3 sales/CS

---

## Year 4: Platform

**Theme:** FileChat is infrastructure. Other developers build on top of it.

### Product Evolution
- FileChat SDK (Python + TypeScript)
- Plugin marketplace (community-built index types, ranking models)
- JetBrains plugin (IntelliJ, PyCharm, WebStorm)
- Neovim plugin
- File evolution timeline (version grouping: `thesis_v1.pdf` → `thesis_final.pdf`)
- Semantic diff between file versions
- Knowledge graph v2 (entity extraction: people, organizations, dates from content)

### Technical Evolution
- WASM port for browser-native deployments
- gRPC API option for high-throughput agent integrations
- Horizontal search API scaling (stateless workers + Qdrant)
- Edge deployment for air-gapped enterprise (no internet required at all)
- Fine-tuned embedding model on org data (Enterprise)
- Multi-model search (different models for different content types)

### AI Evolution
- Predictive intelligence production-ready (access pattern prediction)
- Knowledge graph with NER-based entity extraction (spaCy or local LLM)
- Multi-agent orchestration: FileChat coordinates with email/calendar/code agents
- Local RAG: FileChat provides document chunks to any agent that asks

### Revenue Evolution
- $500K → $2M MRR
- $10M → $25M ARR
- Series A funding
- SDK and API revenue >30% of total

### Team
- 30 engineers, 5 designers, 10 sales/CS

---

## Year 5: Category Definition

**Theme:** FileChat is the standard. Every AI agent that operates on a local machine uses FileChat for file access.

### Product Evolution
- FileChat is the MCP standard for local file retrieval (registered, documented, widely used)
- Every major IDE has a FileChat plugin
- Every knowledge-intensive enterprise has FileChat deployed
- AGI-ready layer: FileChat as episodic memory store for AI agents operating on a user's machine

### Technical Evolution
- Distributed index for multi-site enterprise (replicated across offices)
- Real-time collaborative file intelligence (shared behavioral model, team suggestions)
- Sub-10ms semantic search via approximate index (IVF-PQ quantization)
- Incremental knowledge graph updates (stream processing, not batch rebuild)
- Privacy-preserving federated behavioral model (aggregate team signal without sharing individual data)

### AI Evolution
- Autonomous file organization (agent executes approved suggestions automatically)
- Predictive caching (pre-load likely-needed files into VRAM before user searches)
- Cross-machine knowledge graph (optional: sync graph topology, not file content, across devices)
- FileChat as episodic memory: AI agents query "what has the user worked on related to X?" and get a structured answer grounded in real file history

### Revenue Evolution
- $50M ARR
- 100+ enterprise contracts ($50K–$500K ACV)
- Platform revenue (SDK, API, marketplace) >40% of total
- 100+ employees

---

## North Star Progression

| Year | WAR Target | Users | ARR |
|------|-----------|-------|-----|
| 1 | 35 WAR/user | 5K active | $300K |
| 2 | 55 WAR/user | 50K active | $2M |
| 3 | 70 WAR/user | 500K active | $10M |
| 4 | 80 WAR/user | 2M active | $25M |
| 5 | 80 WAR/user | 10M active | $50M |

**WAR plateaus at 80** because at that point FileChat handles all file access that was previously done via file manager or OS search. The growth lever shifts from per-user depth to new user acquisition and team/enterprise expansion.
