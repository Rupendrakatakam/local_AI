# FileChat — Executive Product Strategy

---

## Vision

Every file ever created by a human should be findable in under 200 milliseconds, using nothing but natural language, with zero data leaving the machine.

## Mission

Build the world's most intelligent local file intelligence layer — a system that understands your files better than you do, surfaces the right one before you finish typing, and learns your working patterns without ever phoning home.

## North Star Metric

**Weekly Active Retrievals (WAR):** the number of successful file opens or path copies initiated through FileChat per user per week.

This measures real utility delivery — not searches, not sessions, but moments where FileChat replaced a manual filesystem hunt.

| Milestone | WAR Target |
|-----------|-----------|
| Month 1   | 10 WAR/user |
| Month 6   | 35 WAR/user |
| Year 2    | 80 WAR/user |

---

## Product Philosophy

The filesystem is the most underutilized intelligence surface on any computer. Every file has metadata, content, history, and behavioral context — and every OS ignores all of it. FileChat treats the filesystem as a first-class knowledge graph: queryable, learnable, and conversable, without requiring any cloud infrastructure.

## Product Principles

1. **Zero trust by architecture, not policy.** Privacy is not a feature toggle. The system is physically incapable of exfiltrating data — no cloud endpoints, no telemetry hooks.
2. **Sub-200ms or it doesn't ship.** Every new feature passes a latency gate. Features that break P95 latency move to background or parallel execution.
3. **Degrade gracefully, never fail silently.** Ollama offline → regex fallback. LanceDB missing → keyword-only mode. Every capability has a degraded path.
4. **Learn without asking.** Behavioral adaptation happens passively from open/copy events. Users are never prompted to rate results or teach the system.
5. **Own the local surface, then expand outward.** Start on the filesystem. Graduate to local databases, local email, local code. Never require cloud to unlock value.
6. **Modular at every layer.** Swap MiniLM for BGE. Swap Ollama for llama.cpp. Swap LanceDB for Chroma. The architecture is model-agnostic and vendor-agnostic by design.

---

## Market Positioning

FileChat occupies a currently empty quadrant: **local-first × AI-powered × developer-grade**.

| Tool            | Local | AI-Powered | Developer-Grade | Privacy          |
|-----------------|-------|------------|-----------------|------------------|
| macOS Spotlight | ✅    | ❌         | ❌              | ⚠️ metadata sent |
| Windows Search  | ✅    | ❌         | ❌              | ⚠️ cloud index   |
| Alfred / Raycast| ✅    | ❌         | ⚠️              | ✅               |
| Notion AI       | ❌    | ✅         | ⚠️              | ❌ cloud-only    |
| **FileChat**    | ✅    | ✅         | ✅              | ✅               |

FileChat is the Spotlight that went to grad school and never left your machine.

---

## Competitive Moat

**Layer 1 — Behavioral Graph:** The RFM + workspace affinity model learns each user's file access topology. After 90 days, the ranking model has a personalized signal no cold competitor can match on day one.

**Layer 2 — Indexing Depth:** FTS5 + trigram + semantic + content + image + code symbol indexing creates a retrieval surface no single-purpose tool matches.

**Layer 3 — Local LLM Pipeline:** As local LLM quality converges with cloud (Phi-4, Gemma 3, Llama 4), FileChat's architecture becomes more powerful over time with zero infrastructure cost increase. Cloud competitors face the opposite trajectory.

**Layer 4 — Developer Integration Surface:** CLI, REST API, browser extension, and IDE plugins create stickiness across every workflow touchpoint. Switching cost compounds as integrations multiply.

---

## Long-Term Expansion Strategy

| Phase | Timeline | Focus |
|-------|----------|-------|
| 1 | Months 0–12  | Own the filesystem (Linux, single-user) |
| 2 | Months 12–24 | Own the desktop (macOS + Windows, global hotkey, Tauri app) |
| 3 | Years 2–3    | Own the local knowledge graph (code, email, databases) |
| 4 | Years 3–4    | Team Edition (shared index, SSO, audit logs) |
| 5 | Years 4–5    | Platform (FileChat as MCP server, SDK, plugin ecosystem) |

---

## Revenue Model

| Tier | Price | Key Features |
|------|-------|-------------|
| Free (OSS) | $0 | Core retrieval, CLI, web GUI |
| Pro | $8/month | Global hotkey, macOS/Windows, better embeddings, encrypted backup |
| Team | $15/user/month | Shared index, SSO, audit log, admin dashboard |
| Enterprise | Contract | On-premise, custom models, SLA, HIPAA readiness |
| API | $0.001/query | Programmatic access for IDE plugins and AI agents |

---

## Data Flywheel

```
User searches → behavioral events recorded
→ RFM model improves → better rankings
→ user finds files faster → uses FileChat more
→ more behavioral events → cycle accelerates
```

The flywheel operates entirely locally. Each user's flywheel is independent — privacy is preserved while the model still improves.

## AI Flywheel

```
Better local LLMs released (Phi-4, Llama 4)
→ FileChat NL parsing improves with zero engineering work
→ more complex queries succeed → user trust increases
→ users attempt harder queries → query data improves prompt tuning
→ FileChat ships better defaults → accuracy improves further
```

---

## Business Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Ollama install friction | High adoption barrier | Bundle embedded LLM fallback requiring no separate install |
| Apple/Microsoft ship AI Spotlight | Direct competition | FileChat's open architecture + Linux market + team features are defensible |
| Model commoditization | NL advantage narrows | Behavioral layer is model-agnostic — retains value regardless |
| LanceDB API instability | Embedding pipeline breaks | EmbeddingPipeline abstraction makes vector DB swappable |
| SQLite at 2M+ files | Performance degradation | Sharded architecture already in place; DuckDB migration path available |

---

## Defensibility Summary

The core defensibility is **architecture**, not patents or brand. The multi-tier cascade cannot be replicated by a cloud tool without incurring per-query infrastructure cost for all five retrieval layers simultaneously. A local tool doing only one layer is slower and less accurate. FileChat's architecture is its moat.
