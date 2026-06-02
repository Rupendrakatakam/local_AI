# FileChat — Master Implementation Plan (Micro-Tasks)

> Every task is a single, small, independently testable code change.
> Total micro-tasks: **350+** across 9 phases.
> Legend: `[ ]` = todo, `[/]` = in progress, `[x]` = done

---

## Phase A: Stabilization & Wiring Fixes (25 updates)

> Goal: Fix every known disconnect and bug before building new features.

### A1 — Backup Auto-Scheduling

- [ ] A1.01 — In `indexer.py`, import `backup.py`'s `perform_backup` function at the top (lazy import)
- [ ] A1.02 — Create a `_backup_thread()` function in `indexer.py` that calls `perform_backup()` once per week (604800 seconds)
- [ ] A1.03 — In `indexer.py` `main()`, spawn `_backup_thread` as a daemon thread after full scan completes
- [ ] A1.04 — Add a `backup_interval_hours` key to `config.json` (default: 168 = 1 week)
- [ ] A1.05 — Update `_backup_thread()` to read interval from `config_loader.get("backup_interval_hours")`
- [ ] A1.06 — Create `filefinder-backup.timer` systemd timer file (weekly schedule alternative)
- [ ] A1.07 — Create `filefinder-backup.service` systemd service file (runs `python3 backup.py`)
- [ ] A1.08 — Update `setup.sh` to install and enable the backup timer

### A2 — Audit Wiring Fixes

- [ ] A2.01 — In `chat.py`, find the `/copy N` handler block
- [ ] A2.02 — Add `audit.log_action("COPY_CLI", f"Path: {path}")` after `record_copy()` in the copy handler
- [ ] A2.03 — Verify audit log entries appear for both `/open` and `/copy` by running `chat.py` and testing

### A3 — Missing Dependencies

- [ ] A3.01 — Add `markdown` to the `pip install` line in `setup.sh`
- [ ] A3.02 — Add `"markdown"` to `doctor.py`'s `check_dependencies()` dict
- [ ] A3.03 — Wrap `import markdown` in `gui.py` `/api/smart_folders` with try/except and return a friendly error message
- [ ] A3.04 — Wrap `import markdown` in `gui.py` `/api/chat` with try/except and return a friendly error message

### A4 — Dead Code Cleanup

- [ ] A4.01 — Remove the unused `DB_PATH` constant from `search.py` line 23
- [ ] A4.02 — Remove any other references to `DB_PATH` in search.py (grep to verify)
- [ ] A4.03 — Update `embedder.py` line 40 default from `"all-MiniLM-L6-v2"` to `"all-mpnet-base-v2"` to match config.json

### A5 — Hotkey Service Integration

- [ ] A5.01 — Create `filefinder-hotkey.service` systemd user service file (runs `python3 hotkey.py`)
- [ ] A5.02 — Set `After=graphical-session.target` in the service file
- [ ] A5.03 — Update `setup.sh` to copy and enable `filefinder-hotkey.service`
- [ ] A5.04 — Add `--display` environment passthrough to the service file for X11/Wayland

### A6 — Doctor Repair Enhancement

- [ ] A6.01 — In `doctor.py` `repair_fts()`, add a section to rebuild `code_symbols` from existing `.py` files
- [ ] A6.02 — In `doctor.py` `repair_fts()`, add a section to rebuild `file_content_fts` from embedder data
- [ ] A6.03 — In `doctor.py` `repair_fts()`, add a section to recalculate `embedding_hashes`

### A7 — Race Condition Fix

- [ ] A7.01 — In `behavior.py`, move `if _behavior_conn is None` check inside `_behavior_lock` context manager

---

## Phase B: Search & AI Enhancements (62 updates)

> Goal: Multi-language code parsing, smarter synonyms, learned reranking, streaming search.

### B1 — Tree-Sitter Code Symbol Parsing

- [ ] B1.01 — Add `tree-sitter` to `setup.sh` pip dependencies
- [ ] B1.02 — Add `tree-sitter-python` to pip dependencies
- [ ] B1.03 — Add `tree-sitter-javascript` to pip dependencies
- [ ] B1.04 — Add `tree-sitter-typescript` to pip dependencies
- [ ] B1.05 — Add `tree-sitter-c` to pip dependencies (covers C and C++)
- [ ] B1.06 — Add `tree-sitter-rust` to pip dependencies
- [ ] B1.07 — Add `tree-sitter-go` to pip dependencies
- [ ] B1.08 — Add `tree-sitter-java` to pip dependencies
- [ ] B1.09 — In `indexer.py`, create a new `_extract_symbols_treesitter(path)` function (shell/stub)
- [ ] B1.10 — Implement Python tree-sitter parser inside `_extract_symbols_treesitter()` for `.py` files
- [ ] B1.11 — Implement JavaScript parser for `.js` and `.mjs` files
- [ ] B1.12 — Implement TypeScript parser for `.ts` and `.tsx` files
- [ ] B1.13 — Implement C parser for `.c` and `.h` files
- [ ] B1.14 — Implement C++ parser for `.cpp`, `.cc`, `.hpp` files
- [ ] B1.15 — Implement Rust parser for `.rs` files
- [ ] B1.16 — Implement Go parser for `.go` files
- [ ] B1.17 — Implement Java parser for `.java` files
- [ ] B1.18 — Add a dispatch map: `{".py": py_parser, ".js": js_parser, ...}`
- [ ] B1.19 — Replace the `ast`-only `_extract_code_symbols()` call in `upsert()` with `_extract_symbols_treesitter()`
- [ ] B1.20 — Keep the `ast` fallback if tree-sitter is not installed (graceful degradation)
- [ ] B1.21 — Add `tree-sitter` and `tree-sitter-python` to `doctor.py` dependency check
- [ ] B1.22 — Test `code:` queries against JS and Python symbols
- [ ] B1.23 — Benchmark: verify P95 latency still under 200ms after tree-sitter integration

### B2 — Embedding-Based Synonym Expansion

- [ ] B2.01 — In `search.py`, create a `_build_vocabulary_index()` function (loads common filename tokens from DB)
- [ ] B2.02 — Collect top 5000 unique filename words from all shards for the vocabulary
- [ ] B2.03 — Embed the vocabulary words using the loaded SentenceTransformer model
- [ ] B2.04 — Store vocabulary embeddings as a numpy array (in-memory, built on first use)
- [ ] B2.05 — Create `_embedding_synonyms(word, top_k=3)` function with cosine similarity lookup
- [ ] B2.06 — Add `@lru_cache(maxsize=1024)` to `_embedding_synonyms()`
- [ ] B2.07 — Replace `FALLBACK_SYNONYMS.get()` call with `_embedding_synonyms()` in the synonym expansion section
- [ ] B2.08 — Keep `FALLBACK_SYNONYMS` as a fallback if SentenceTransformer is not loaded
- [ ] B2.09 — Add a config key `synonym_expansion_enabled` (default: true)
- [ ] B2.10 — Test: search for "quarterly" should also surface "q3", "q4" related files
- [ ] B2.11 — Benchmark: confirm synonym expansion adds < 5ms to search latency

### B3 — Learned Reranker

- [ ] B3.01 — Create `reranker.py` module (new file)
- [ ] B3.02 — Define `RerankerModel` class with `train()` and `predict()` methods
- [ ] B3.03 — Implement feature extraction: `_extract_features(query_atoms, result)` → 20-element float vector
- [ ] B3.04 — Feature 1: keyword coverage ratio (matched / total)
- [ ] B3.05 — Feature 2: exact name match (binary)
- [ ] B3.06 — Feature 3: prefix match (binary)
- [ ] B3.07 — Feature 4: extension matches requested (binary)
- [ ] B3.08 — Feature 5: recency score (days_old decay)
- [ ] B3.09 — Feature 6: path depth (integer)
- [ ] B3.10 — Feature 7: RFM score (float)
- [ ] B3.11 — Feature 8: workspace affinity score (float)
- [ ] B3.12 — Feature 9: time-of-day boost (float)
- [ ] B3.13 — Feature 10: file size log-scaled
- [ ] B3.14 — Feature 11: name length
- [ ] B3.15 — Feature 12: query length
- [ ] B3.16 — Feature 13: is in home root (binary)
- [ ] B3.17 — Feature 14-15: BM25 rank and semantic cosine similarity (if available)
- [ ] B3.18 — Implement `_collect_training_data()` from `behavior.db` (opens = positive, top-3 skips = negative)
- [ ] B3.19 — Implement `train()` using `sklearn.linear_model.LogisticRegression`
- [ ] B3.20 — Save trained model to `~/.local/share/filefinder/reranker.pkl` (joblib)
- [ ] B3.21 — Implement `predict(features)` returning relevance probability
- [ ] B3.22 — Create `_train_reranker_background()` function for weekly retraining
- [ ] B3.23 — In `search.py`, add conditional: if `reranker.pkl` exists, use learned reranker; else fall back to heuristic `_score_result()`
- [ ] B3.24 — Wire reranker training into `indexer.py` background thread (weekly)
- [ ] B3.25 — Add config key `use_learned_reranker` (default: false until first training completes)

### B4 — WebSocket Streaming Search

- [ ] B4.01 — Add `flask-socketio` to `setup.sh` pip dependencies
- [ ] B4.02 — Import `SocketIO` in `gui.py`
- [ ] B4.03 — Initialize `socketio = SocketIO(app)` in `gui.py`
- [ ] B4.04 — Create `@socketio.on('search')` event handler
- [ ] B4.05 — Inside the handler, run FTS5 search synchronously and emit `search_fts5` event with results
- [ ] B4.06 — Launch semantic search in background thread, emit `search_semantic` event when done
- [ ] B4.07 — Emit `search_fused` event with RRF-merged final results
- [ ] B4.08 — In `index.html`, add Socket.IO client library (CDN)
- [ ] B4.09 — Create `connectWebSocket()` function in frontend JS
- [ ] B4.10 — On `search_fts5` event, render first batch of results immediately
- [ ] B4.11 — On `search_semantic` event, merge and re-render with updated results
- [ ] B4.12 — On `search_fused` event, replace with final ranked results
- [ ] B4.13 — Add visual indicator "Loading semantic results…" while waiting for fusion
- [ ] B4.14 — Fallback: keep existing `/api/search` REST endpoint working (non-WS clients)

---

## Phase C: GUI & UX Polish (65 updates)

> Goal: Make every GUI screen production-quality.

### C1 — Alias Management in GUI

- [ ] C1.01 — Create `/api/alias` GET endpoint in `gui.py` → returns all aliases as JSON
- [ ] C1.02 — Create `/api/alias` POST endpoint → `{name, path}` → calls `aliases.set_alias()`
- [ ] C1.03 — Create `/api/alias/<name>` DELETE endpoint → calls `aliases.remove_alias()`
- [ ] C1.04 — In `index.html`, add an "Aliases" tab/button in the navigation
- [ ] C1.05 — Create aliases panel HTML (table with name, path, delete button)
- [ ] C1.06 — Add "New Alias" form (name input, path input, save button)
- [ ] C1.07 — JS: `fetchAliases()` → `GET /api/alias` → render table
- [ ] C1.08 — JS: `createAlias()` → `POST /api/alias` → refresh table
- [ ] C1.09 — JS: `deleteAlias(name)` → `DELETE /api/alias/<name>` → refresh table
- [ ] C1.10 — Add success/error toast notifications for alias operations
- [ ] C1.11 — Style the aliases panel to match existing dark/light theme

### C2 — Chat Assistant Polish

- [ ] C2.01 — In `index.html`, create a dedicated chat tab/panel with message list
- [ ] C2.02 — Create user message bubble component (right-aligned, blue)
- [ ] C2.03 — Create assistant message bubble component (left-aligned, gray)
- [ ] C2.04 — Add chat input field with send button at the bottom
- [ ] C2.05 — JS: `sendChatMessage()` → `POST /api/chat` → render response
- [ ] C2.06 — Add 3-dot typing indicator animation while waiting for Ollama
- [ ] C2.07 — Implement file path pill detection: regex scan response for backtick paths
- [ ] C2.08 — Convert detected file paths into clickable pill elements
- [ ] C2.09 — On pill click, call `/api/open` with the file path
- [ ] C2.10 — Add "Clear Conversation" button that resets the message list
- [ ] C2.11 — Persist conversation history in `localStorage` (survives page reload)
- [ ] C2.12 — Load conversation history from `localStorage` on page load
- [ ] C2.13 — Add 3 example prompt buttons on empty chat: "What was I working on?", "Find recent PDFs", "Clean up Downloads"
- [ ] C2.14 — Handle Ollama-offline error: show "AI is not running. Start with: `ollama serve`"

### C3 — Duplicate Detector UI

- [ ] C3.01 — In `index.html`, add "Duplicates" tab/button in navigation
- [ ] C3.02 — Create duplicates panel HTML (summary bar + group list)
- [ ] C3.03 — JS: `fetchDuplicates()` → `GET /api/duplicates` → render groups
- [ ] C3.04 — Render summary bar: "X duplicate groups found, Y MB wasted"
- [ ] C3.05 — Render each group as a collapsible card (hash, file count, wasted size)
- [ ] C3.06 — Inside each group, list all file paths with sizes and modified dates
- [ ] C3.07 — Add "Reveal in Files" button per file (calls `/api/open` on the directory)
- [ ] C3.08 — Sort groups by wasted size descending (biggest savings first)
- [ ] C3.09 — Handle empty state: "No duplicate files found. ✨"
- [ ] C3.10 — Handle loading state: spinner + "Computing duplicate groups…"
- [ ] C3.11 — Style to match existing dark/light theme

### C4 — Smart Folders UI

- [ ] C4.01 — In `index.html`, add "Smart Folders" tab/button
- [ ] C4.02 — Create smart folders panel HTML
- [ ] C4.03 — JS: `fetchSmartFolders()` → `GET /api/smart_folders` → render suggestion
- [ ] C4.04 — Render the LLM-generated suggestion as formatted HTML/Markdown
- [ ] C4.05 — Add "Refresh Suggestions" button that re-calls the API
- [ ] C4.06 — Add "Export as Text" button that downloads suggestion as `.txt`
- [ ] C4.07 — Add folder analysis table: path | file count | total size | dominant extensions
- [ ] C4.08 — Handle Ollama offline state with friendly error message
- [ ] C4.09 — Handle loading state with "Analyzing folder structure…" message

### C5 — Stats Dashboard Complete

- [ ] C5.01 — In `index.html`, redesign the stats modal as a full dashboard page/tab
- [ ] C5.02 — Render "Total Files Indexed" as a large number card
- [ ] C5.03 — Render "Database Size" card (MB across all shards)
- [ ] C5.04 — Render "Shard Count" card
- [ ] C5.05 — Render embedding progress bar (done / total / percentage)
- [ ] C5.06 — Render Ollama status indicator (online/offline with model name)
- [ ] C5.07 — JS: `fetchAnalytics()` → `GET /api/analytics` → render charts
- [ ] C5.08 — Render "Top 5 Queries" as a horizontal bar chart (CSS-only or Chart.js)
- [ ] C5.09 — Render "Top 5 Opened Files" as a list with open counts
- [ ] C5.10 — Render "Hourly Activity" as a 24-bar heatmap (searches + opens combined)
- [ ] C5.11 — Add auto-refresh (poll every 60 seconds while dashboard is visible)
- [ ] C5.12 — Style all cards with consistent border radius, shadows, theme colors

### C6 — Skeleton Loaders

- [ ] C6.01 — Create a CSS `skeleton` class with shimmer animation (linear-gradient pulse)
- [ ] C6.02 — Create `renderSkeletonCards(count)` JS function that inserts 5 placeholder cards
- [ ] C6.03 — Show skeleton cards during search API fetch
- [ ] C6.04 — Replace skeletons with real results on API response
- [ ] C6.05 — Add skeleton for preview panel (right side)
- [ ] C6.06 — Respect `prefers-reduced-motion` — disable shimmer animation

### C7 — Theming System

- [ ] C7.01 — Create a `themes.js` file with theme definitions (Monokai, Solarized, Nord, Gruvbox, Default Dark, Default Light)
- [ ] C7.02 — Each theme = a JS object mapping CSS variable names to values
- [ ] C7.03 — Create `applyTheme(themeName)` function that sets CSS variables on `<html>`
- [ ] C7.04 — Add a theme selector dropdown in the GUI header/nav
- [ ] C7.05 — Save selected theme to `localStorage`
- [ ] C7.06 — Load saved theme from `localStorage` on page load
- [ ] C7.07 — Style the theme dropdown to match the active theme

---

## Phase D: Cross-Platform Foundation (42 updates)

> Goal: macOS and Windows support without breaking Linux.

### D1 — Platform Detection Layer

- [ ] D1.01 — Create `platform_utils.py` module (new file)
- [ ] D1.02 — Import `platform` and `shutil`
- [ ] D1.03 — Create `get_os()` function returning `"linux"`, `"darwin"`, or `"windows"`
- [ ] D1.04 — Create `open_file(path)` dispatcher: linux=`xdg-open`, mac=`open`, win=`os.startfile`
- [ ] D1.05 — Create `copy_to_clipboard(text)` dispatcher: linux=`xclip/xsel`, mac=`pbcopy`, win=`pyperclip`
- [ ] D1.06 — Create `get_data_dir()` dispatcher: linux=`~/.local/share/filefinder`, mac=`~/Library/Application Support/FileChat`, win=`%APPDATA%/FileChat`
- [ ] D1.07 — Create `get_config_dir()` dispatcher
- [ ] D1.08 — Create `get_service_manager()` returning `"systemd"`, `"launchd"`, or `"windows_service"`
- [ ] D1.09 — Update `chat.py` to use `platform_utils.open_file()` instead of hardcoded `xdg-open`
- [ ] D1.10 — Update `chat.py` to use `platform_utils.copy_to_clipboard()` instead of hardcoded `xclip`
- [ ] D1.11 — Update `gui.py` to use `platform_utils.open_file()`
- [ ] D1.12 — Update `db_utils.py` `BASE_DIR` to use `platform_utils.get_data_dir()`
- [ ] D1.13 — Update `behavior.py` `BEHAVIOR_DB` to use `platform_utils.get_data_dir()`
- [ ] D1.14 — Update `backup.py` `get_base_dir()` to use `platform_utils.get_data_dir()`
- [ ] D1.15 — Update `audit.py` `get_audit_log_path()` to use `platform_utils.get_data_dir()`

### D2 — pathlib Audit

- [ ] D2.01 — Grep all files for hardcoded `/home/` or `~/.local/share/filefinder` paths
- [ ] D2.02 — Replace each with `platform_utils.get_data_dir()` call
- [ ] D2.03 — Grep for `os.path.sep` assumptions and replace with `Path()` operations
- [ ] D2.04 — Verify all `Path.home()` calls work on macOS and Windows
- [ ] D2.05 — Test that `config.json` `watch_path` with `~` expands correctly on all platforms

### D3 — macOS Support

- [ ] D3.01 — Create `com.filechat.indexer.plist` launchd plist file
- [ ] D3.02 — Set `RunAtLoad = true` and `KeepAlive = true` in the plist
- [ ] D3.03 — Point `ProgramArguments` to `python3 indexer.py`
- [ ] D3.04 — Create `setup_macos.sh` script (installs via Homebrew + launchd)
- [ ] D3.05 — Test watchdog FSEvents backend on macOS
- [ ] D3.06 — Verify `open` command works for file opening
- [ ] D3.07 — Verify `pbcopy` works for clipboard operations
- [ ] D3.08 — Test LanceDB on macOS (ARM64 and Intel)
- [ ] D3.09 — Test Ollama on macOS
- [ ] D3.10 — Update `doctor.py` to detect macOS and adjust checks accordingly

### D4 — Windows Foundation

- [ ] D4.01 — Add `pyperclip` to `setup.sh` / setup script pip dependencies
- [ ] D4.02 — Implement `open_file()` for Windows using `os.startfile()`
- [ ] D4.03 — Implement `copy_to_clipboard()` for Windows using `pyperclip`
- [ ] D4.04 — Create `setup_windows.bat` or `setup_windows.ps1` script
- [ ] D4.05 — Replace `resource.setrlimit()` in indexer.py with a cross-platform memory check
- [ ] D4.06 — Replace `os.getloadavg()` in indexer.py with cross-platform CPU check (psutil)
- [ ] D4.07 — Test watchdog `ReadDirectoryChangesW` backend on Windows
- [ ] D4.08 — Test SQLite WAL mode on Windows (file locking differences)
- [ ] D4.09 — Test `os.chmod` calls (no-op on Windows, needs try/except)
- [ ] D4.10 — Create Windows Task Scheduler XML for indexer auto-start
- [ ] D4.11 — Update `doctor.py` to detect Windows and adjust checks
- [ ] D4.12 — Test the full search pipeline on Windows end-to-end

---

## Phase E: Tauri Desktop App (50 updates)

> Goal: Native desktop app with global hotkey and system tray.

### E1 — Project Scaffold

- [ ] E1.01 — Install Rust toolchain (`curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`)
- [ ] E1.02 — Install Tauri CLI (`cargo install create-tauri-app`)
- [ ] E1.03 — Scaffold Tauri project: `cargo create-tauri-app filechat-app`
- [ ] E1.04 — Choose vanilla frontend (HTML/JS/CSS — matching our existing stack)
- [ ] E1.05 — Verify Tauri dev server starts: `cargo tauri dev`
- [ ] E1.06 — Configure `tauri.conf.json`: set window title to "FileChat"
- [ ] E1.07 — Set default window size to 900×650
- [ ] E1.08 — Set `resizable: true`, `decorations: true`

### E2 — Port Flask GUI into Tauri

- [ ] E2.01 — Copy `templates/index.html` into Tauri's `src/` directory
- [ ] E2.02 — Copy all CSS files into Tauri's `src/styles/`
- [ ] E2.03 — Copy all JS files into Tauri's `src/scripts/`
- [ ] E2.04 — Update all fetch URLs from relative to `http://127.0.0.1:5000` absolute
- [ ] E2.05 — Test search functionality through Tauri WebView
- [ ] E2.06 — Test preview panel through Tauri WebView
- [ ] E2.07 — Test file open functionality (Tauri → Flask → xdg-open)
- [ ] E2.08 — Test dark/light theme toggle in Tauri WebView
- [ ] E2.09 — Add Tauri `invoke` commands for native file operations (bypass Flask)
- [ ] E2.10 — Create Rust `open_file` command using `open::that(path)`
- [ ] E2.11 — Wire Tauri invoke for file open (optional upgrade from Flask API)

### E3 — Global Hotkey

- [ ] E3.01 — Add `tauri-plugin-global-shortcut` to `Cargo.toml` dependencies
- [ ] E3.02 — Register `Super+Space` shortcut in `main.rs`
- [ ] E3.03 — On hotkey activation, show the main window
- [ ] E3.04 — On hotkey activation, focus the search input field
- [ ] E3.05 — If window is already visible and focused, hide it (toggle behavior)
- [ ] E3.06 — Make hotkey configurable via config.json (`global_hotkey` key)
- [ ] E3.07 — Test on Linux (X11 and Wayland)
- [ ] E3.08 — Test on macOS

### E4 — Floating Search Window

- [ ] E4.01 — Create a secondary "search overlay" window configuration in `tauri.conf.json`
- [ ] E4.02 — Set overlay window: frameless, always-on-top, centered, transparent background
- [ ] E4.03 — Set overlay size: 600×60 (just the search bar), expandable to 600×400 on results
- [ ] E4.04 — Create minimal overlay HTML: search input + compact results list
- [ ] E4.05 — Style overlay with glassmorphism: blur backdrop, rounded corners, subtle border
- [ ] E4.06 — On Escape key, hide the overlay window
- [ ] E4.07 — On Enter key, open selected result and hide overlay
- [ ] E4.08 — Animate overlay appearance: fade-in + scale from 95% to 100%
- [ ] E4.09 — Animate overlay dismissal: fade-out + scale from 100% to 95%
- [ ] E4.10 — Auto-dismiss overlay when clicking outside of it (focus loss)

### E5 — System Tray

- [ ] E5.01 — Add `tauri-plugin-tray` to `Cargo.toml` dependencies
- [ ] E5.02 — Create tray icon (use FileChat logo or generate one)
- [ ] E5.03 — Create tray menu: "Show FileChat", "Search…", "Stats", "Quit"
- [ ] E5.04 — Wire "Show FileChat" to show the main window
- [ ] E5.05 — Wire "Search…" to show the floating overlay
- [ ] E5.06 — Wire "Quit" to gracefully exit the app
- [ ] E5.07 — Show tray tooltip: "FileChat — X files indexed"
- [ ] E5.08 — Update tooltip periodically (poll `/api/stats`)

### E6 — App Icons & Installer

- [ ] E6.01 — Design or generate FileChat app icon (512×512 PNG)
- [ ] E6.02 — Generate icon sizes: 32, 64, 128, 256, 512 PNG
- [ ] E6.03 — Generate .icns for macOS
- [ ] E6.04 — Generate .ico for Windows
- [ ] E6.05 — Configure `tauri.conf.json` with icon paths
- [ ] E6.06 — Build `.AppImage` for Linux: `cargo tauri build`
- [ ] E6.07 — Build `.dmg` for macOS: `cargo tauri build`
- [ ] E6.08 — Build `.msi` for Windows: `cargo tauri build`
- [ ] E6.09 — Test each installer on a clean machine (or VM)
- [ ] E6.10 — Add installer download links to README.md

---

## Phase F: Testing & Reliability (45 updates)

> Goal: Full test coverage, type safety, linting, CI.

### F1 — Regression Test Suite

- [ ] F1.01 — Create `tests/` directory in `filefinder/`
- [ ] F1.02 — Create `tests/__init__.py`
- [ ] F1.03 — Create `tests/conftest.py` with shared fixtures (temp DB, mock config)
- [ ] F1.04 — Create `tests/test_search_exact.py` — 10 exact filename queries
- [ ] F1.05 — Create `tests/test_search_fts.py` — 10 FTS5 keyword queries
- [ ] F1.06 — Create `tests/test_search_typo.py` — 10 typo/fuzzy queries
- [ ] F1.07 — Create `tests/test_search_nl.py` — 10 natural language queries
- [ ] F1.08 — Create `tests/test_search_type.py` — 10 `type:` filter queries
- [ ] F1.09 — Create `tests/test_search_content.py` — 5 `content:` filter queries
- [ ] F1.10 — Create `tests/test_search_tag.py` — 5 `tag:` filter queries
- [ ] F1.11 — Create `tests/test_search_code.py` — 5 `code:` filter queries
- [ ] F1.12 — Create `tests/test_search_regex.py` — 5 regex queries
- [ ] F1.13 — Create `tests/test_search_alias.py` — 3 alias lookup queries
- [ ] F1.14 — Create `tests/test_search_hidden.py` — hidden files toggle tests
- [ ] F1.15 — Create `tests/test_search_cache.py` — verify cache hit/miss behavior
- [ ] F1.16 — Create `tests/test_indexer.py` — test `upsert()`, `delete()`, trigram generation
- [ ] F1.17 — Create `tests/test_behavior.py` — test `record_open()`, `record_copy()`, `get_all_boosts_batch()`
- [ ] F1.18 — Create `tests/test_db_utils.py` — test `get_shard_path()`, `init_shard()`
- [ ] F1.19 — Create `tests/test_config_loader.py` — test `get()` with defaults and overrides
- [ ] F1.20 — Create `tests/test_aliases.py` — test set/get/remove/list
- [ ] F1.21 — Create `tests/test_audit.py` — test `log_action()` writes to file
- [ ] F1.22 — Create `tests/test_backup.py` — test `perform_backup()` creates zip and retains 5
- [ ] F1.23 — Create `tests/test_benchmark.py` — assert P95 < 200ms across 100 queries
- [ ] F1.24 — Add `pytest` to `setup.sh` pip dependencies
- [ ] F1.25 — Create `pytest.ini` or `pyproject.toml` [tool.pytest] section

### F2 — Type Checking

- [ ] F2.01 — Install `mypy` and add to pip dependencies
- [ ] F2.02 — Create `mypy.ini` or add `[mypy]` section to `pyproject.toml`
- [ ] F2.03 — Add type annotations to all public functions in `search.py`
- [ ] F2.04 — Add type annotations to all public functions in `indexer.py`
- [ ] F2.05 — Add type annotations to all public functions in `behavior.py`
- [ ] F2.06 — Add type annotations to all public functions in `embedder.py`
- [ ] F2.07 — Add type annotations to `db_utils.py`
- [ ] F2.08 — Add type annotations to `config_loader.py`
- [ ] F2.09 — Add type annotations to `audit.py`, `backup.py`, `health.py`
- [ ] F2.10 — Run `mypy filefinder/` and fix all errors

### F3 — Linting

- [ ] F3.01 — Install `ruff` and add to pip dependencies
- [ ] F3.02 — Create `ruff.toml` config file
- [ ] F3.03 — Run `ruff check .` and fix all auto-fixable issues
- [ ] F3.04 — Fix remaining manual lint issues
- [ ] F3.05 — Add pre-commit hook: `.pre-commit-config.yaml` with ruff

### F4 — Setup Script Hardening

- [ ] F4.01 — Add Python version check to `setup.sh` (require 3.10+)
- [ ] F4.02 — Make `setup.sh` idempotent (check if deps already installed before re-running)
- [ ] F4.03 — Add `pip install` error handling with retry
- [ ] F4.04 — Add colorized output to `setup.sh` (green=success, red=fail)
- [ ] F4.05 — Test `setup.sh` from a completely clean Ubuntu 22.04 install

---

## Phase G: Advanced AI (52 updates)

> Goal: Conversational file agents, MCP server, predictive intelligence.

### G1 — File Intelligence Agent

- [ ] G1.01 — Create `agents/file_agent.py` module (new file)
- [ ] G1.02 — Create `FileIntelligenceAgent` class
- [ ] G1.03 — Implement `query_recent_activity(time_range)` → queries `behavior.db`
- [ ] G1.04 — Implement `group_by_project(opens)` → clusters by parent directory
- [ ] G1.05 — Implement `find_related_files(paths)` → semantic search for files in same directories
- [ ] G1.06 — Implement `generate_summary(grouped_files)` → Ollama prompt for natural language summary
- [ ] G1.07 — Create `parse_time_reference(text)` → "last Tuesday", "yesterday", "this week" → datetime range
- [ ] G1.08 — Wire the agent into `/api/chat` as a special handler for activity queries
- [ ] G1.09 — Return file cards with one-click open buttons
- [ ] G1.10 — Test: "What was I working on last Tuesday?" returns correct files
- [ ] G1.11 — Test: "Show me files from this morning" returns correct time-filtered results

### G2 — Organization Agent

- [ ] G2.01 — Create `agents/org_agent.py` module (new file)
- [ ] G2.02 — Create `OrganizationAgent` class
- [ ] G2.03 — Implement `scan_folder(path)` → collects file_hashes, file_tags, embeddings
- [ ] G2.04 — Implement `find_duplicates(folder)` → hash-based grouping
- [ ] G2.05 — Install `hdbscan` and add to pip dependencies
- [ ] G2.06 — Implement `cluster_files(folder)` → HDBSCAN on file embeddings → topic groups
- [ ] G2.07 — Implement `generate_plan(clusters, duplicates)` → Ollama prompt for folder structure suggestion
- [ ] G2.08 — Create `/api/organize` endpoint in `gui.py`
- [ ] G2.09 — Return plan as markdown with preview (do NOT auto-execute)
- [ ] G2.10 — Add "Approve" button that executes the move plan
- [ ] G2.11 — Implement `execute_plan(moves)` with undo history (store original locations)
- [ ] G2.12 — Create undo file: `~/.local/share/filefinder/undo_log.json`
- [ ] G2.13 — Create `/api/organize/undo` endpoint to reverse last organization

### G3 — MCP Server Interface

- [ ] G3.01 — Create `mcp_server.py` module (new file)
- [ ] G3.02 — Define MCP server manifest JSON (name, description, tools)
- [ ] G3.03 — Implement `search_files(query, limit, type)` MCP tool
- [ ] G3.04 — Implement `get_file_content(path)` MCP tool → read file content
- [ ] G3.05 — Implement `get_file_metadata(path)` MCP tool → return size, mtime, tags
- [ ] G3.06 — Implement `list_recent_files(hours)` MCP tool → from behavior.db
- [ ] G3.07 — Implement JSON-RPC transport (stdin/stdout for local MCP)
- [ ] G3.08 — Create `filefinder://` URI scheme handler
- [ ] G3.09 — Add HTTP transport option (for remote MCP clients)
- [ ] G3.10 — Test with Claude Desktop or Cursor as MCP client
- [ ] G3.11 — Write MCP server README with integration instructions

### G4 — Predictive File Surfacing

- [ ] G4.01 — Create `predictor.py` module (new file)
- [ ] G4.02 — Create `AccessPredictor` class
- [ ] G4.03 — Implement `build_access_matrix()` → query behavior.db for hour × day-of-week × extension patterns
- [ ] G4.04 — Implement `predict_likely_files(horizon_hours=2)` → return top-N files by access probability
- [ ] G4.05 — Create `/api/predictions` endpoint in `gui.py`
- [ ] G4.06 — Create "Predicted Files" section on the GUI dashboard
- [ ] G4.07 — Render predicted files with confidence indicators
- [ ] G4.08 — Auto-refresh predictions every 30 minutes

### G5 — Morning Briefing

- [ ] G5.01 — Create `briefing.py` module (new file)
- [ ] G5.02 — Implement `generate_morning_briefing()` → analyze last 7 days of behavior.db
- [ ] G5.03 — Implement `parse_local_calendar()` → read `.ics` files if present in home directory
- [ ] G5.04 — Implement `match_events_to_files(events, recent_files)` → correlate calendar with file activity
- [ ] G5.05 — Generate briefing via Ollama prompt (today's meetings + recent files → suggest 5 files)
- [ ] G5.06 — Create `/api/briefing` endpoint in `gui.py`
- [ ] G5.07 — Display briefing as a dismissable card on the GUI home page
- [ ] G5.08 — Create systemd timer to generate briefing at configurable time (default: 8 AM)
- [ ] G5.09 — Optional: desktop notification via `notify-send` (Linux) or `osascript` (macOS)

---

## Phase H: IDE & Browser Extensions (40 updates)

> Goal: FileChat accessible from browser address bar and VS Code.

### H1 — Chrome Browser Extension

- [ ] H1.01 — Create `extensions/chrome/` directory
- [ ] H1.02 — Create `manifest.json` (Manifest V3)
- [ ] H1.03 — Set omnibox keyword to `fc` (type `fc <query>` in address bar)
- [ ] H1.04 — Create `background.js` service worker
- [ ] H1.05 — Implement omnibox `onInputChanged` → fetch `localhost:5000/api/search?q=...`
- [ ] H1.06 — Implement omnibox `onInputEntered` → open the selected file
- [ ] H1.07 — Show search suggestions as omnibox dropdown items
- [ ] H1.08 — Create popup HTML for extension icon click (mini search UI)
- [ ] H1.09 — Style popup with dark theme matching FileChat
- [ ] H1.10 — Add extension icon (16, 48, 128 PNG)
- [ ] H1.11 — Handle "FileChat not running" error gracefully
- [ ] H1.12 — Add options page: configure port number and max results
- [ ] H1.13 — Package as `.crx` for installation

### H2 — Firefox Extension Port

- [ ] H2.01 — Create `extensions/firefox/` directory
- [ ] H2.02 — Adapt `manifest.json` for Firefox (Manifest V2 compatibility where needed)
- [ ] H2.03 — Port `background.js` to Firefox's `browser.*` API namespace
- [ ] H2.04 — Port popup HTML and styles
- [ ] H2.05 — Test omnibox integration on Firefox
- [ ] H2.06 — Package as `.xpi` for installation

### H3 — VS Code Extension

- [ ] H3.01 — Create `extensions/vscode/` directory
- [ ] H3.02 — Run `npx -y yo code` to scaffold VS Code extension (TypeScript)
- [ ] H3.03 — Create `extension.ts` entry point
- [ ] H3.04 — Implement `activate()` function
- [ ] H3.05 — Extract imports and function names from the currently active editor file
- [ ] H3.06 — Query FileChat API: `GET /api/search?q=code:<symbols>`
- [ ] H3.07 — Create a TreeView sidebar panel ("FileChat: Related Files")
- [ ] H3.08 — Render related files as tree items with icons
- [ ] H3.09 — On tree item click, open the file in VS Code editor
- [ ] H3.10 — Refresh related files on every file save (`onDidSaveTextDocument`)
- [ ] H3.11 — Add a command palette command: "FileChat: Search Files"
- [ ] H3.12 — Show QuickPick dialog with search input → show results → open selected
- [ ] H3.13 — Add status bar item showing FileChat connection status
- [ ] H3.14 — Handle "FileChat not running" with a notification + retry button
- [ ] H3.15 — Add extension settings: `filechat.port`, `filechat.maxResults`
- [ ] H3.16 — Create extension icon
- [ ] H3.17 — Write extension README with screenshots

### H4 — API Rate Limiting

- [ ] H4.01 — Add `flask-limiter` to `setup.sh` pip dependencies
- [ ] H4.02 — Import `Limiter` in `gui.py`
- [ ] H4.03 — Initialize limiter with `default_limits=["60 per minute"]`
- [ ] H4.04 — Apply rate limit to `/api/search` endpoint
- [ ] H4.05 — Apply rate limit to `/api/chat` endpoint (lower: 10 per minute)
- [ ] H4.06 — Return `429 Too Many Requests` with friendly JSON error on limit exceeded

---

## Phase I: Knowledge Graph (38 updates)

> Goal: File-entity-concept relationships with visual explorer.

### I1 — Graph Data Model

- [ ] I1.01 — Create `knowledge_graph.py` module (new file)
- [ ] I1.02 — Install `networkx` and add to pip dependencies
- [ ] I1.03 — Install `duckdb` and add to pip dependencies
- [ ] I1.04 — Create `KnowledgeGraph` class
- [ ] I1.05 — Define `FileNode` dataclass (path, name, extension, size, mtime)
- [ ] I1.06 — Define `PersonNode` dataclass (name, source_file)
- [ ] I1.07 — Define `ProjectNode` dataclass (name, directory_path)
- [ ] I1.08 — Define `TopicNode` dataclass (name, from_tags)
- [ ] I1.09 — Define `DateNode` dataclass (date, extracted_from)
- [ ] I1.10 — Initialize DuckDB connection at `~/.local/share/filefinder/knowledge.duckdb`

### I2 — Edge Types

- [ ] I2.01 — Create `edges` table in DuckDB: `(source, target, edge_type, weight, created_at)`
- [ ] I2.02 — Implement `add_co_accessed_edge(file1, file2)` — files opened within 1-hour session
- [ ] I2.03 — Implement `add_semantic_similar_edge(file1, file2, score)` — cosine similarity > 0.8
- [ ] I2.04 — Implement `add_version_of_edge(file1, file2)` — similar names in same directory
- [ ] I2.05 — Implement `add_references_edge(file1, file2)` — citation extracted from PDF
- [ ] I2.06 — Implement `add_contains_entity_edge(file, entity)` — NER-detected entity in file
- [ ] I2.07 — Create `build_graph()` method that constructs all edges from existing data
- [ ] I2.08 — Build co-accessed edges from `behavior.db` session analysis
- [ ] I2.09 — Build semantic similarity edges from LanceDB vector comparisons
- [ ] I2.10 — Build version edges from filename similarity analysis

### I3 — Graph Queries

- [ ] I3.01 — Implement `find_related(path, depth=2)` → BFS from file node, return connected files
- [ ] I3.02 — Implement `find_by_topic(topic)` → all files connected to a topic node
- [ ] I3.03 — Implement `find_co_accessed(path)` → files commonly used together
- [ ] I3.04 — Implement `get_project_files(project_name)` → all files in a project cluster
- [ ] I3.05 — Create `/api/graph/related?path=...` endpoint in `gui.py`
- [ ] I3.06 — Create `/api/graph/rebuild` endpoint (triggers full graph rebuild)

### I4 — Visual Explorer

- [ ] I4.01 — Add `d3.js` (or `vis-network`) library to the frontend
- [ ] I4.02 — Create "Knowledge Graph" tab in the GUI
- [ ] I4.03 — JS: `fetchGraphData(path)` → `GET /api/graph/related?path=...`
- [ ] I4.04 — Render nodes as circles: color-coded by type (File=blue, Person=green, Topic=orange)
- [ ] I4.05 — Render edges as lines: thickness by weight, style by type
- [ ] I4.06 — Add node labels (file basename, person name, topic name)
- [ ] I4.07 — Implement click-to-expand: clicking a node loads its connections
- [ ] I4.08 — Implement node click → show file preview in side panel
- [ ] I4.09 — Add zoom and pan controls
- [ ] I4.10 — Add search box in graph view: type a filename → center graph on that node

### I5 — NER Entity Extraction

- [ ] I5.01 — Install `spacy` and add to pip dependencies
- [ ] I5.02 — Download `en_core_web_sm` model
- [ ] I5.03 — Create `_extract_entities(text)` function → return list of (entity_text, entity_type)
- [ ] I5.04 — Filter to PERSON, ORG, DATE entity types
- [ ] I5.05 — Integrate entity extraction into embedding pipeline (run after text extraction)
- [ ] I5.06 — Store extracted entities as graph nodes and edges
- [ ] I5.07 — Add fallback: if spaCy not installed, skip NER silently
- [ ] I5.08 — Test: extract entities from a sample PDF and verify graph nodes created

---

## Update Counter

| Phase | Updates | Cumulative |
|-------|---------|------------|
| A — Stabilization | 25 | 25 |
| B — Search & AI | 62 | 87 |
| C — GUI & UX | 65 | 152 |
| D — Cross-Platform | 42 | 194 |
| E — Tauri Desktop | 50 | 244 |
| F — Testing | 45 | 289 |
| G — Advanced AI | 52 | 341 |
| H — IDE & Browser | 40 | 381 |
| I — Knowledge Graph | 38 | **419** |

> **Total: 419 micro-tasks** across 9 phases.

---

## How to Use This Plan

1. **Start at Phase A** — these are pure bugfixes, no new features
2. **Work sequentially within each phase** — tasks are ordered by dependency
3. **Phases B, C, and F can run in parallel** — they touch different files
4. **Phases D and E are sequential** — Tauri needs cross-platform first
5. **Phase G unlocks Phase H** — extensions need the API features
6. **Phase I is independent** — can start anytime after Phase B

Mark tasks as `[/]` when starting and `[x]` when done. This file is your single source of truth.
