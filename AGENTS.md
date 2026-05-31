# FileChat — Agent Guide

## Setup

```bash
bash filefinder/setup.sh          # full setup: apt deps, pip deps, systemd service
ollama pull phi3:mini             # required by setup, but must be pulled before
```

Deps: `python3-watchdog`, `rich`, `prompt-toolkit`, `requests` (via apt); `sentence-transformers`, `lancedb`, `pymupdf`, `mammoth`, `flask`, `pystray`, `pillow` (via pip). See `filefinder/setup.sh`.

## Run

| Command | Purpose |
|---|---|
| `python3 filefinder/chat.py` | Main CLI |
| `python3 filefinder/gui.py` | Flask web UI (port 5000) |
| `python3 filefinder/doctor.py` | Diagnose DB/index/perms/deps |
| `python3 filefinder/doctor.py --repair` | Fix issues |
| `python3 filefinder/indexer.py` | Manual indexer run (systemd auto-starts) |

## Architecture

- **Single-package** repo under `filefinder/`. No monorepo, no tests directory, no CI.
- **Entrypoints**: `chat.py` (CLI), `gui.py` (Flask), `tui.py` (Textual TUI), `tui_pt.py` (prompt_toolkit fallback).
- **Search engine** in `search.py` — 6-tier cascading: bare filename → FTS5 BM25 → fuzzy trigram → LLM intent + keywords + OR fallback.
- **Multi-shard SQLite** (`db_utils.py`): one `index_<topdir>.db` per top-level directory + `index_root.db`. All shards queried in parallel.
- **Config**: central `filefinder/config.json`, loaded by `config_loader.py` with defaults.
- **Systemd service**: `filefinder.service` runs `indexer.py` as `--user` daemon.
- **Semantic search** (Phase 2): `embedder.py` with SentenceTransformer + LanceDB. Background worker, priority queue for PDF/DOCX/TXT/MD.
- **Behavior tracking** (Phase 3): `behavior.py` logs opens/copies/searches to `behavior.db` for RFM scoring.

## Key files

| File | Role |
|---|---|
| `chat.py` | CLI entry, commands, pagination, file open/copy |
| `search.py` | All search logic: FTS5, trigram, LLM intent, cascading, RRF fusion |
| `indexer.py` | Watchdog daemon, multi-shard upsert, FTS5 triggers, trigram, vacuum |
| `db_utils.py` | Shard path resolution, init, `get_all_shard_paths()` |
| `embedder.py` | Semantic pipeline: chunk, embed, LanceDB upsert |
| `behavior.py` | Open/copy/search tracking, RFM scores |
| `aliases.py` | Alias shortcuts (`/alias set name path`) |
| `config_loader.py` | `get(key, default)`, singleton, `reload()` |
| `doctor.py` | `--repair` flag for auto-fix |

## Chat commands (in `chat.py`)

`/open N`, `/copy N`, `/alias set/rm/list`, `/re <regex>`, `/hidden`, `/service`, `stats`, `n`/`p`/`q` pagination.

## Search syntax

`type:image|video|audio|document|code|...`, `content:"text snippet"`, `tag:finance`, `/re .*pattern.*`.

## Dev notes

- **No test framework** — test via `python3 -c "from search import search; print(search(...))"` or `test_lens.py`.
- **No lint/typecheck/CI** — ensure clean imports, check `python3 -c` for import errors.
- **Task tracking** in `task.md` — 80 updates across 5 phases. Phase 1 ✅, Phase 2 ✅, Phase 3–5 pending.
- `chat.py` line count badge: background thread refreshes every 60s from `db_stats()`.
- FTS5 auto-rebuilds on startup if table is empty but `files` table has rows.
- Systemd logs: `journalctl --user -u filefinder -f`.
- Config hot-reload: call `config_loader.reload()` in code.
