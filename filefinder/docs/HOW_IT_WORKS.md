# How FileChat Works — Architecture Explained Simply

This document explains the entire system architecture in simple terms, like explaining it to a friend who doesn't code.

---

## The Big Picture

FileChat has **three layers** that work together:

```
┌─────────────────────────────────────────────┐
│              YOU (the user)                  │
│     Type a query in terminal or browser      │
└──────────────────┬──────────────────────────┘
                   │
          ┌────────▼────────┐
          │   Search Layer  │  ← Finds your files
          │   (search.py)   │
          └────────┬────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
    ▼              ▼              ▼
┌────────┐  ┌───────────┐  ┌──────────┐
│ SQLite │  │  LanceDB  │  │ Behavior │
│ Index  │  │  Vectors  │  │ Tracking │
│(FTS5)  │  │(Semantic) │  │  (RFM)   │
└────────┘  └───────────┘  └──────────┘
    ▲              ▲
    │              │
┌───┴──────────────┴───┐
│    Indexer Layer      │  ← Watches your files
│    (indexer.py)       │
│    (embedder.py)      │
└──────────────────────┘
```

---

## Layer 1: The Indexer (Background Worker)

**Analogy:** Imagine a librarian who walks through every shelf in the library, writes down every book's title, location, and size into a master catalog, and then sits at the door watching for new books being added or old ones being removed.

That's exactly what `indexer.py` does:

1. **Full Scan (startup):** Walks through every directory under your home folder, records every file's name, path, extension, size, and modification time into a SQLite database.

2. **Real-Time Watching:** After the initial scan, it uses Linux's `inotify` system (via the `watchdog` library) to get instant notifications whenever a file is created, deleted, renamed, or modified. It updates the database in real-time.

3. **Embedding Pipeline:** For text-extractable files (PDFs, docs, text files), the indexer also sends them to `embedder.py`, which extracts the text, splits it into chunks, and generates vector embeddings for semantic search.

**Numbers:** On Rupendra's system, the initial scan indexes **670,055 files** in about 2 minutes. After that, real-time updates happen within 500ms of the file change.

---

## Layer 2: The Search Engine (The Brain)

**Analogy:** When you ask a librarian "Do you have any books about cooking Italian pasta?", the librarian doesn't read every book. They:
1. First check the catalog for "Italian" and "pasta" in book titles.
2. If that fails, check the subject index.
3. If that fails, think about which section pasta books are usually in.
4. Remember that you borrowed a pasta book last week and check that section first.

FileChat's `search.py` does the exact same thing with a **7-tier cascading search**:

```
Tier 0: Check if query matches an alias → instant result
Tier 1: Bare filename match → FTS5 lookup
Tier 2: LLM intent parsing → targeted FTS5 search
Tier 3: Relax extension filter → broader FTS5 search
Tier 4: Relax directory filter → even broader
Tier 5: Top-2 keywords only → handle wordy queries
Tier 6: OR mode + sub-keyword expansion → last keyword effort
Tier 6.5: Trigram fuzzy match → handles typos
Tier 7: Full fuzzy match → last resort
```

**Plus Semantic Search:** If the query is natural language (3+ words or abstract terms like "find", "about", "related"), the system also runs a semantic vector search in parallel and merges the results using Reciprocal Rank Fusion (RRF).

**Plus Behavioral Boost:** After all results are found, files you've accessed before get bonus ranking points (RFM score + workspace affinity + time-of-day pattern).

---

## Layer 3: The Interfaces (How You Talk To It)

### Terminal CLI (`chat.py`)
A rich, colorful terminal interface with:
- Live file count badge
- Pagination (next/prev/quit)
- Commands: `stats`, `/open N`, `/copy N`, `/hidden`, `/re <pattern>`, `/alias`, `/rebuild`, `/privacy clear`

### Web GUI (`gui.py` + `templates/index.html`)
A Flask-powered web interface at `http://127.0.0.1:5000` with:
- Live search with 300ms debounce
- File type icons, confidence bars
- Click-to-preview panel
- Keyboard shortcuts
- Dark/light mode

### System Tray (`tray.py`)
A small icon in your system tray with a right-click menu: Open, Stats, Quit.

---

## The Databases

FileChat uses **three separate databases**, each for a different purpose:

| Database | Location | Purpose |
|----------|----------|---------|
| `index.db` | `~/.local/share/filefinder/index.db` | Main file index (670K+ rows), FTS5 table, trigram table |
| `behavior.db` | `~/.local/share/filefinder/behavior.db` | User open/copy/search events for behavioral ranking |
| `vectors/` | `~/.local/share/filefinder/vectors/` | LanceDB vector embeddings for semantic search |

**Why three?** Separation of concerns. If you run `/privacy clear`, only `behavior.db` is deleted. The file index and embeddings remain untouched. If the embeddings get corrupted, you can delete the `vectors/` folder without affecting keyword search.

---

## Data Flow: What Happens When You Search

Here's the exact sequence when you type "find my tax report" and press Enter:

```
1. chat.py receives "find my tax report"
2. search.py checks: is this an alias? → No
3. search.py checks: does this need semantic search? → Yes (4 words, "find" is abstract)
4. search.py sends query to Ollama: "find my tax report"
5. Ollama returns: {"keywords": ["tax", "report"], "extension": null, "directory": null}
6. search.py runs FTS5 search for "tax" AND "report" → 12 results
7. search.py runs semantic search in LanceDB → 8 results
8. search.py merges both lists using RRF → 15 unique results
9. search.py adds behavioral boost to each result (RFM + workspace + time)
10. search.py re-ranks by total score
11. chat.py displays the top 10 results with pagination
```

Total time: ~200ms (including LLM call).
