# FileChat Features — Complete Guide

Every feature is listed here, along with a plain-English explanation of *how* it works under the hood.

---

## 1. Lightning-Fast Full-Text Search (FTS5)

**What it does:** When you type a query like "resume", FileChat finds matching files in under 1 millisecond — across 670,000+ files.

**How it works (simple):** Imagine a book's index at the back. Instead of reading every page to find the word "resume", you flip to the index, find "resume → page 42, 87, 203" and go directly there. FTS5 is that index, but for every filename and path on your computer. SQLite builds this index automatically whenever a file is created, renamed, or deleted.

**How it works (technical):** We create a `files_fts` virtual table using SQLite's FTS5 module. Three database triggers (`INSERT`, `UPDATE`, `DELETE`) keep this index perfectly in sync with the main `files` table. The tokenizer splits filenames on underscores, dashes, dots, and spaces so "my_resume_2024.pdf" is searchable by "resume", "2024", or "my".

---

## 2. Typo-Tolerant Fuzzy Search (Trigrams)

**What it does:** Mistype "reusme" instead of "resume"? FileChat still finds it.

**How it works (simple):** Every filename is broken into 3-letter pieces called "trigrams". The word "resume" becomes `["res", "esu", "sum", "ume"]`. When you search "reusme", it becomes `["reu", "eus", "usm", "sme"]`. FileChat compares these two sets of trigrams using a formula called the Dice coefficient. If enough trigrams overlap, it's considered a fuzzy match.

**Why this approach:** Trigrams are extremely fast (sub-millisecond) because they're pre-computed and stored in an indexed table. Other fuzzy methods like Levenshtein distance would require scanning every single filename, which is too slow for 670K files.

---

## 3. Natural Language Understanding (LLM Intent Parsing)

**What it does:** You can ask "where is my tax report PDF in Downloads?" and FileChat understands you want:
- Keywords: `tax`, `report`
- File type: `.pdf`
- Location: `~/Downloads`

**How it works (simple):** Your query is sent to a small AI model (Phi-3 Mini) running locally via Ollama. The AI reads your sentence and extracts structured information (keywords, extension, directory) as a JSON object. FileChat then uses these extracted fields to search precisely.

**Why local LLM:** We use Ollama so the AI runs on YOUR machine. Your queries are never sent to the cloud. Phi-3 Mini is small (2.3GB) and responds in under 1 second.

**Fallback:** If Ollama is offline, FileChat automatically falls back to a simple regex-based keyword extractor. You'll never be stuck.

---

## 4. Semantic Search (Vector Embeddings)

**What it does:** Search by *meaning*. Ask "notes about machine learning" and find a file called `deep_learning_lecture_3.md` — even though the words "machine learning" don't appear in the filename.

**How it works (simple):** Every document's text content is read, split into 400-word chunks, and converted into a list of 384 numbers (a "vector") using a model called MiniLM. These vectors capture the *meaning* of the text. When you search, your query is also converted into a vector, and we find the documents whose vectors are most similar (closest in this 384-dimensional space).

**How it works (technical):** Text is extracted from files using PyMuPDF (PDFs), mammoth (DOCX), or direct reading (plain text). Chunks are created with 80-word overlap to preserve context across boundaries. The `all-MiniLM-L6-v2` model from Sentence-Transformers generates 384-dimensional normalized vectors. These are stored in LanceDB, a columnar vector database. Search uses Approximate Nearest Neighbor (ANN) via LanceDB's built-in index.

**Result Fusion:** Semantic results are blended with keyword results using **Reciprocal Rank Fusion (RRF)** — a technique that combines two ranked lists into one optimal ordering. This means you always get the best of both worlds: exact matches AND meaning-based matches.

---

## 5. Behavioral Learning (RFM Scoring)

**What it does:** Files you access frequently rise to the top of search results automatically.

**How it works (simple):** Every time you `/open` or `/copy` a file, FileChat records the event in a separate database (`behavior.db`). It then calculates three scores:
- **Recency**: How recently did you last access this file? (Recent = higher boost)
- **Frequency**: How many times total? (More = higher boost)
- **Monetary**: Did you open it (high value) or just copy its path (medium value)?

These three scores are combined into a single boost (0–25 points) that is added to the file's relevance score during search.

**Workspace Affinity:** If you frequently access files in `~/Rupendra/projects/`, then ANY file in that directory tree gets a small boost (0–15 points). The system recognizes your "hot" workspaces.

**Time-of-Day Patterns:** If you tend to open PDFs in the morning, PDFs get a tiny boost during morning searches (0–5 points).

---

## 6. File Aliases

**What it does:** Create shortcuts for files you access constantly.

**How to use:**
```
/alias set resume ~/Documents/Resume_Final.pdf
/alias set thesis ~/Research/thesis_v3.docx
/alias list
/alias rm resume
```

After setting an alias, just search "resume" and the aliased file appears instantly as the #1 result — no searching needed.

**How it works:** Aliases are stored in `~/.config/filefinder/aliases.json`. At the very start of every search, before any FTS5 or semantic processing, FileChat checks if the query matches an alias name. If it does, it returns that file immediately.

---

## 7. Premium Web GUI

**What it does:** A beautiful, browser-based interface at `http://127.0.0.1:5000` with:
- Live search (results appear as you type)
- File type emoji icons (🐍 for Python, 📕 for PDF, etc.)
- Click-to-preview panel (text, images, PDF content)
- Keyboard shortcuts (`/` to search, `↑↓` to navigate, `Enter` to open)
- Dark/Light mode toggle
- Stats dashboard

**How it works:** Flask serves a single HTML page with inline CSS and JavaScript. The frontend makes fetch() calls to REST API endpoints (`/api/search`, `/api/preview`, etc.). No React, no Node.js, no build step — just one HTML file and one Python file.

---

## 8. Privacy Controls

**What it does:** Complete control over your behavioral data.

- `/privacy clear` — Instantly deletes `behavior.db`, wiping all tracking history.
- All data stays in `~/.local/share/filefinder/` — no cloud, no telemetry, no analytics.
- The `.filefinder_ignore` file lets you exclude sensitive directories from indexing entirely.

---

## 9. Self-Diagnostics (Doctor)

**What it does:** Run `python3 doctor.py` to get a full health report:
- Database exists and is not corrupt
- FTS5 is in sync with the file index
- Trigram table is populated
- Behavior database is healthy
- LanceDB vectors directory exists
- Ollama is reachable
- All 11 Python dependencies are installed

**Auto-repair:** Run `python3 doctor.py --repair` to automatically rebuild FTS5 and trigrams if they get out of sync.

---

## 10. Background Indexing

**What it does:** The indexer runs as a systemd service in the background. It watches your entire home directory for file changes (creates, renames, deletes) and updates the database in real-time.

**How it works:** Uses the `watchdog` library to receive filesystem events from the Linux kernel (via inotify). Events are debounced (0.5s) to avoid redundant updates. CPU usage is throttled if system load exceeds 2.0. A full scan runs once on startup, then real-time watching takes over.

---

## 11. Centralized Configuration

All settings live in one file: `config.json`. You can change the Ollama model, embedding model, chunk sizes, cache durations, memory limits, and more without editing any code.
