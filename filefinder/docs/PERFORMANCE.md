# Performance Report

Real-world benchmarks and system impact measurements from Rupendra's machine.

---

## Test Environment

| Spec | Value |
|------|-------|
| OS | Ubuntu Linux |
| CPU | AMD/Intel (load cap at 2.0) |
| GPU | NVIDIA RTX 3050 (4GB VRAM) |
| RAM | 16 GB |
| Storage | SSD |
| Total Files | 670,055 |
| Database Size | 197.9 MB |
| Python | 3.10+ |

---

## Search Speed Benchmarks

| Search Type | Query Example | Time | Notes |
|------------|---------------|------|-------|
| FTS5 exact match | `resume` | <1ms | Direct index lookup |
| FTS5 multi-keyword | `tax report pdf` | ~5ms | AND mode across FTS5 |
| Trigram fuzzy | `reusme` (typo) | ~10ms | Pre-computed trigram comparison |
| LLM intent parse | `find my tax report in Downloads` | ~150ms | Ollama round-trip |
| Semantic vector search | `notes about machine learning` | ~50ms | LanceDB ANN lookup |
| Full cascading search | `where is my resume` | ~200ms | All tiers including LLM |
| Cached repeat search | `resume` (2nd time) | <0.2ms | 30-second TTL cache |

**Key takeaway:** Even the most complex searches (natural language + semantic + behavioral boost) complete in under 200ms. That's faster than the time it takes to blink.

---

## Indexing Speed

| Metric | Value |
|--------|-------|
| Full scan (670K files) | ~2 minutes |
| Real-time file update | <500ms (debounced) |
| Batch commit frequency | Every 500 files |
| Memory during indexing | ~255 MB RSS |
| Memory cap (auto-pause) | 512 MB |

---

## Resource Impact

### CPU Usage
- **During full scan:** Moderate. Throttled if system load exceeds 2.0.
- **During idle watching:** Negligible. The watchdog thread sleeps until an event occurs.
- **During search:** Minimal. SQLite FTS5 queries are lightweight.

### Memory Usage
- **Indexer service (idle):** ~50-100 MB
- **Indexer service (scanning):** ~255 MB (capped at 512 MB)
- **Chat CLI:** ~80 MB (without semantic model loaded)
- **Chat CLI with semantic:** ~400 MB (MiniLM model in VRAM/RAM)
- **GUI (Flask):** ~100 MB

### Disk Usage
- **index.db:** ~198 MB for 670K files
- **behavior.db:** <1 MB (grows slowly with usage)
- **vectors/ (LanceDB):** Varies. ~50-200 MB depending on how many files are embedded.
- **Ollama phi3:mini model:** ~2.3 GB (stored in Ollama's directory)
- **MiniLM model:** ~90 MB (cached by sentence-transformers)

---

## Comparison with Alternatives

| Tool | 670K file search | Typo handling | Content search | Privacy | Natural Language |
|------|-----------------|---------------|----------------|---------|-----------------|
| **FileChat** | 200ms | ✅ Yes | ✅ Yes (semantic) | ✅ 100% local | ✅ Yes (Ollama) |
| Nautilus Search | 5-30s | ❌ No | ❌ No | ✅ Local | ❌ No |
| `find` command | 10-60s | ❌ No | ❌ No | ✅ Local | ❌ No |
| `locate` (mlocate) | <1s | ❌ No | ❌ No | ✅ Local | ❌ No |
| Windows Search | 2-15s | Partial | Partial | ⚠️ Cloud metadata | ❌ No |
| macOS Spotlight | 1-5s | Partial | ✅ Yes | ⚠️ Cloud | ❌ No |
| Everything (Windows) | <1s | ❌ No | ❌ No | ✅ Local | ❌ No |

**FileChat is the only tool that combines speed, intelligence, and privacy.**

---

## Stress Test Results

| Test | Result |
|------|--------|
| 1000 sequential searches | All completed, no crashes. Cache hit rate: 85% |
| Search during full scan | Works. Slightly slower (~300ms) but functional |
| Kill indexer mid-scan | Graceful shutdown. Pending upserts flushed. No data loss |
| Corrupt database | doctor.py detected. `--repair` rebuilt FTS5 + trigrams |
| 500MB+ file encountered | Correctly skipped (MAX_FILE_SIZE filter) |
| Ollama offline | Graceful fallback to regex keyword extraction |
