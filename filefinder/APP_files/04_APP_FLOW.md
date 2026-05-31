# FileChat — App Flow Document

---

## Core Search Flow (All Interfaces)

```
User types query
      │
      ▼
[Tier 0] Alias check → exact match? → return instantly (0ms)
      │ no
      ▼
[Tier 0a] _looks_like_filename? → WHERE name = ? COLLATE NOCASE (<1ms)
      │ no results
      ▼
[Tier 0b] Strip command prefixes ("find me", "where is", "can you find")
      │
      ▼
[Tier 0c] Parse type:/content:/tag: syntax filters
      │
      ▼
[Tier 0d] Detect NL category words ("show me images of rupendra")
      │
      ▼
[Tier 1] Quick search (FTS5 + LIKE) for single-word queries (<5ms)
      │ no results
      ▼
[Tier 2] Ollama intent parsing → {keywords, extension, directory} (~150ms)
         [PARALLEL] Launch semantic search in background executor
      │
      ▼
[Tier 2a] FTS5 search with extracted keywords (<10ms)
      │
      ▼
[Tier 3] Relax: drop extension filter → FTS5 retry
      │ still no results
      ▼
[Tier 4] Relax: drop directory filter → FTS5 retry
      │
      ▼
[Tier 5] Top-2 longest keywords only → FTS5 retry
      │
      ▼
[Tier 6] OR-mode LIKE search (any keyword matches)
      │
      ▼
[Tier 6.5] Sub-keyword expansion ("online" → LIKE '%on%' AND '%line%')
      │
      ▼
[Tier 6.6] Trigram fuzzy search (Dice coefficient ≥ 0.45)
      │
      ▼
[Tier 7]  RapidFuzz WRatio (last resort, 50K cached filenames)
      │
      ▼
Collect semantic search results (from background, timeout 500ms)
      │
      ▼
RRF fusion (keyword results + semantic results + content results)
      │
      ▼
Batch behavioral boost query (single DB call for all result paths)
      │
      ▼
Rerank by composite score (keyword coverage + recency + depth + RFM)
      │
      ▼
Return top-N results → render in UI
      │
      ▼
User selects result:
├── /open N → xdg-open → record_open(query, path) → behavior.db
└── /copy N → clipboard → record_copy(path) → behavior.db
```

---

## Screen 1: CLI Chat Interface (`chat.py`)

### Purpose
Primary interface for developer/power users. Terminal-native, keyboard-only workflow.

### Components
- Header panel: "FileChat | powered by phi3:mini"
- Status row: Ollama online/offline, file count badge, hidden files indicator
- Boot progress bar (during initial scan): spinner + count + elapsed
- Prompt: `[count H] You ❯ ` with live file count badge
- Results table: `#` | `File Name` | `Path` | `Size` | `Modified` | `Match %`
- Pagination footer: `Page N/M (X–Y of Z) — n next | p prev | q done`
- Fuzzy warning banner: `⚠ No exact matches. Showing fuzzy/approximate results`

### States

| State | Visual |
|-------|--------|
| Empty / ready | Prompt only, badge shows current count |
| Searching | `[cyan]Searching…[/cyan]` spinner |
| Ollama offline | Yellow warning panel; "Fast regex fallback active" |
| Index not found | `⚠ Index not found. Is the indexer running?` |
| Results found | Rich table rendered |
| Fuzzy results | Yellow ⚠ banner above table |
| Boot scanning | Progress bar with live file count |
| Paginating | Pagination footer; waits for n/p/q input |

### Full Command Reference

| Command | Action |
|---------|--------|
| `help` | Show usage guide |
| `stats` | Index size, Ollama status, embedding progress |
| `/open N` | Open result N in default app |
| `/copy N` | Copy path of result N to clipboard |
| `/hidden` | Toggle hidden dotfiles on/off |
| `/re <pattern>` | Regex search — bypasses LLM entirely |
| `/alias set NAME PATH` | Create file shortcut |
| `/alias list` | Show all shortcuts |
| `/alias rm NAME` | Delete shortcut |
| `/rebuild` | Rebuild FTS5 + trigrams across all shards |
| `/privacy clear` | Wipe all behavioral tracking data |
| `/service` | Show systemd indexer service status |
| `exit` | Quit FileChat |
| `n` / `p` / `q` | Pagination: next / previous / quit |

### Analytics Events
- `search_executed {query_length, result_count, is_fuzzy, tier_resolved, latency_ms}`
- `file_opened {path, rank, query, match_score}`
- `file_copied {path}`
- `alias_used {alias_name, path}`
- `regex_search_executed {pattern_length}`

### Edge Cases
- Empty query → no action
- `/open N` with N out of range → `No result #N.`
- xdg-open not found → error + install hint
- `/re` with invalid regex → `Invalid regex: <error>`
- `/alias set` without PATH → usage hint
- Ctrl+C or Ctrl+D → clean exit, "Goodbye."

---

## Screen 2: Web GUI — Search Home

### Purpose
Visual interface for non-CLI users. Primary file discovery surface.

### Layout
```
┌──────────────────────────────────────────────────────────────┐
│  🔍 FileChat                                   🌓  📊        │
│──────────────────────────────────────────────────────────────│
│                                                              │
│         ┌──────────────────────────────────────┐            │
│         │  🔍  Search your files...            │            │
│         └──────────────────────────────────────┘            │
│                                                              │
│  ┌─────────────────────────────────────────────────┐        │
│  │ 🐍  resume_final.pdf   ~/Documents    ████ 98% │        │
│  │ 📕  tax_report_2024.pdf ~/Downloads   ███░ 87% │        │
│  │ 📝  thesis_draft_v3.docx ~/Research  ██░░ 81% │        │
│  └─────────────────────────────────────────────────┘        │
│                           ┌─────────────────────────┐       │
│                           │  PREVIEW PANEL           │       │
│                           │  [file content here]     │       │
│                           └─────────────────────────┘       │
└──────────────────────────────────────────────────────────────┘
```

### Components
- Search bar (autofocus on page load, re-focus on `/` key)
- Results list: file type icon + name + truncated path + confidence bar + match %
- Confidence bar: green (≥60%) | yellow (30–60%) | red (<30%)
- Preview panel: right side, lazy-loaded on click or keyboard selection
- Fuzzy badge: orange "~Approximate" on affected result cards
- Stats modal (📊 icon)
- Dark/light toggle (🌓 icon)

### States

| State | Behavior |
|-------|----------|
| Empty | Search bar with placeholder, no results |
| Loading | Skeleton cards (5 items, no spinner) |
| Results | Staggered fade-in, 40ms per card |
| Fuzzy results | Orange badge on approximate matches |
| No results | "No files found" with suggestions to try `/hidden`, regex, or broader terms |
| Preview loading | Skeleton in preview panel |
| Preview error | Inline error message in panel |

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `/` | Focus search bar |
| `↑` / `↓` | Navigate results |
| `Enter` | Open selected file |
| `Escape` | Clear search / close preview |
| `Ctrl+C` | Copy path of selected result |

### Micro Animations
- Search bar: subtle border glow on focus (200ms ease)
- Results: staggered fade-in (40ms delay per item, max 300ms total)
- Confidence bar: animated fill on render (300ms ease-out)
- Preview panel: slide in from right (150ms ease-out)
- Theme toggle: cross-fade (200ms)
- All animations disabled when `prefers-reduced-motion: reduce`

### Analytics Events
- `search_typed {query_length, debounce_fired}`
- `result_clicked {path, rank, confidence_pct}`
- `preview_opened {path, extension}`
- `file_opened_from_gui {path, query}`
- `theme_toggled {new_theme}`

---

## Screen 3: Web GUI — Stats Dashboard

### Purpose
System health and behavioral insights.

### Components
- Total files indexed (live count, updates every 60s)
- Database size (MB across all shards)
- Shard count
- Embedding progress bar (done / total / %)
- Ollama status + current model
- Top 5 searched queries (horizontal bar chart)
- Top 5 opened files (list with open count)
- Hourly activity heatmap (24-bar chart, opens + searches combined)

### States
- Loading: skeleton charts
- Behavior data empty: "No activity recorded yet. Start searching to build your profile."

---

## Screen 4: Web GUI — Chat Assistant

### Purpose
Conversational interface for complex file history queries ("What was I working on last Tuesday?").

### Components
- Chat message list (user bubbles right, assistant bubbles left)
- File path pills (clickable — opens file via `/api/open`)
- Input field with send button
- "Thinking…" typing indicator (3-dot animation)
- Clear conversation button

### States
- Empty: welcome message with 3 example prompts
- Loading: typing indicator
- Error (Ollama offline): "The local AI is not running. Start it with: `ollama serve`"

### Message Format
Assistant responses use markdown rendered as HTML. File paths in backticks are converted to clickable pills by the frontend via regex: `` /`(\/[^`]+)`/g ``.

---

## Screen 5: Web GUI — Duplicate Detector

### Purpose
Find identical or near-identical files wasting disk space.

### Components
- Summary bar: "X duplicate groups found, Y MB wasted"
- Group list: hash fingerprint → list of matching file paths with sizes and mtimes
- "Reveal in Files" per-file button (calls `/api/open` with file directory)
- Wasted space sorted descending (biggest savings first)

### States
- Loading: spinner + "Computing duplicate groups..."
- No duplicates: "No duplicate files found."
- Empty hashes table: "Hashes not yet computed. Run a full scan or wait for the indexer."

---

## Screen 6: Web GUI — Smart Folders

### Purpose
AI-generated file organization suggestions based on folder analysis.

### Components
- Folder analysis table: path | file count | total size | dominant extensions
- LLM-generated suggestion (markdown rendered as HTML)
- "Refresh Suggestions" button (re-runs analysis and Ollama)
- "Export as Text" button

### States
- Loading: "Analyzing folder structure and generating suggestions..."
- Ollama offline: "Smart suggestions require the local AI. Start with: `ollama serve`"

---

## Admin Flow (`doctor.py`)

```
python3 doctor.py [--repair]
      │
      ├── [Database Shards]
      │   ├── Check shard files exist → pass/fail
      │   ├── PRAGMA integrity_check per shard → pass/fail
      │   ├── FTS5 row count vs files row count → pass/warn
      │   └── Trigram unique file count → pass/warn
      │
      ├── [Content & Features]
      │   ├── file_content_fts row count → pass/warn
      │   ├── file_tags count → pass/warn
      │   └── file_hashes count → pass/warn
      │
      ├── [Behavior & Vectors]
      │   ├── behavior.db exists + opens/copies/searches counts → pass/warn
      │   └── LanceDB vectors directory exists → pass/warn
      │
      ├── [Services]
      │   └── Ollama reachable at localhost:11434 → pass/warn
      │
      └── [Dependencies]
          └── 12 Python packages importable → pass/warn per package
      │
      └── Summary: "X passed, Y failed, Z warnings"

If --repair:
  └── Rebuild FTS5 + trigrams across all shards
      ├── DELETE FROM files_fts (per shard)
      ├── INSERT INTO files_fts SELECT rowid, name, path FROM files
      ├── DELETE FROM name_trigrams
      ├── Regenerate trigrams for all files
      └── Report files rebuilt per shard
```

---

## Indexer Lifecycle Flow

```
systemd starts indexer.py
      │
      ▼
Load config.json + .filefinder_ignore patterns
      │
      ▼
full_scan(WATCH_PATH)
├── os.walk() skipping SKIP_DIRS + hidden dirs
├── upsert() per file (batch commit every 500 files)
│   ├── stat() file → check size, mtime unchanged? → skip
│   ├── explicit DELETE (fires files_ad trigger → cleans FTS5)
│   ├── INSERT (fires files_ai trigger → populates FTS5)
│   ├── INSERT trigrams for new rowid
│   ├── INSERT OR REPLACE file_hashes (MD5)
│   └── embedder.enqueue(path, mtime)
├── Write progress to /tmp/filefinder.booting (read by CLI progress bar)
└── cleanup /tmp/filefinder.booting when done
      │
      ▼
Observer.start() — watchdog listens on inotify
      │
      ▼
Event loop (per filesystem event):
├── on_created  → debouncer.schedule_upsert(path)
├── on_modified → debouncer.schedule_upsert(path)
├── on_deleted  → debouncer.schedule_delete(path)
└── on_moved    → schedule_delete(src) + schedule_upsert(dst)

Debouncer (500ms):
└── After 500ms quiet: call upsert() or delete()
    [Subsequent events reset the 500ms timer]

Shutdown (SIGTERM / KeyboardInterrupt):
├── debouncer.flush_all() — process all pending without holding self._lock during upsert
├── observer.stop() + observer.join()
└── Close all DB connections in pool
```

---

## Embedding Pipeline Flow

```
embedder.enqueue(path, mtime)
      │ (PriorityQueue: priority 0=PDF/DOCX, 1=other)
      ▼
_worker_loop() (background thread)
      │
      ▼
_embed_file(path, mtime)
      │
      ├── Is image (.jpg/.png/.webp)?
      │   ├── embed_image() → CLIP vector
      │   ├── upsert_image_embeddings() → LanceDB image_chunks
      │   └── pytesseract OCR → file_content_fts (if text found)
      │
      └── Is text file?
          ├── extract text (PDF: pymupdf, DOCX: mammoth, plain: read())
          ├── Compute MD5 hash of text
          ├── Compare with embedding_hashes — skip if unchanged
          ├── UPDATE file_content_fts (FTS5)
          ├── UPDATE embedding_hashes
          ├── _tag_queue.put((path, text[:500])) — async tagging
          ├── chunk_text() → 400-word chunks, 80-word overlap
          ├── embed_text_chunks() → 768-dim normalized vectors
          └── upsert_text_embeddings() → LanceDB chunks table

_tag_worker_loop() (separate background thread, lower priority)
      │
      ▼
For each (path, text_snippet):
├── Check file_tags — already tagged? → skip
├── POST to Ollama: "output 1-3 comma-separated categories"
└── INSERT OR REPLACE into file_tags
```
