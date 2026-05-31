# FileChat — Backend System Design

---

## Database Architecture

### Shard Strategy

FileChat uses a **multi-index sharded architecture**. Each top-level directory under `WATCH_PATH` gets its own SQLite database file:

```
~/.local/share/filefinder/
├── index_Documents.db
├── index_Downloads.db
├── index_Rupendra.db
├── index_root.db          ← files directly in WATCH_PATH
└── behavior.db            ← separate, for clean privacy clearing
```

Files outside WATCH_PATH fall back to `index_root.db`. Dot-directory shards (`index_.git.db`) are excluded from search queries.

**Why sharding?**
- Parallel writes to different directories without cross-shard lock contention
- Smaller B-tree depth per shard = faster queries
- Clean isolation: deleting `index_Downloads.db` removes just that shard

---

### ER Diagram

```
files (PK: path)
  │
  ├──[rowid FK]── files_fts (FTS5 virtual, content='files')
  │
  ├──[rowid FK]── file_content_fts (FTS5 virtual, content='files')
  │                   stores extracted document text
  │
  ├──[rowid FK]── name_trigrams (1:N — one file → many trigrams)
  │
  ├──[path FK]──  file_hashes (1:1 — duplicate detection)
  │
  ├──[path FK]──  file_tags (1:1 — auto-generated categories)
  │
  └──[path FK]──  embedding_hashes (1:1 — skip re-embedding if unchanged)

behavior.db (separate file):
  opens    (path INDEX)
  copies   (path INDEX)
  searches

LanceDB vectors/ (separate directory):
  chunks        (text embeddings: path, chunk_id, text, vector, mtime, extension)
  image_chunks  (image embeddings: path, vector, mtime, extension)
```

---

### Table Definitions

#### `files` (one per shard)

| Column    | Type    | Constraints                  |
|-----------|---------|------------------------------|
| path      | TEXT    | PRIMARY KEY                  |
| name      | TEXT    | NOT NULL, INDEX NOCASE       |
| extension | TEXT    | INDEX                        |
| size      | INTEGER |                              |
| mtime     | REAL    |                              |

Notes:
- `path` is the absolute filesystem path
- `extension` stored without dot, lowercase (e.g., `pdf` not `.pdf`)
- Zero-byte files excluded (`size > 0` in all queries)
- `mtime` is Unix epoch float from `stat().st_mtime`

#### `files_fts` (FTS5 virtual, per shard)

```sql
CREATE VIRTUAL TABLE files_fts USING fts5(
    name,
    path,
    content='files',
    content_rowid='rowid',
    tokenize='unicode61 separators "_-."'
);
```

**Critical:** `separators "_-."` is required. Without it, `unicode61` treats underscores and hyphens as part of tokens — meaning `My_Resume_2024.pdf` is indexed as one unsplittable token. Searching `resume` via FTS5 returns zero results.

Sync triggers:
```sql
CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, name, path) VALUES (new.rowid, new.name, new.path);
END;

CREATE TRIGGER files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, name, path)
    VALUES('delete', old.rowid, old.name, old.path);
END;

CREATE TRIGGER files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, name, path)
    VALUES('delete', old.rowid, old.name, old.path);
    INSERT INTO files_fts(rowid, name, path) VALUES (new.rowid, new.name, new.path);
END;
```

**Critical:** `upsert()` must use explicit `DELETE + INSERT`, never `INSERT OR REPLACE`. `REPLACE` performs an internal delete that does NOT fire `files_ad`, leaving ghost FTS5 entries for updated files.

#### `file_content_fts` (FTS5 virtual, per shard)

```sql
CREATE VIRTUAL TABLE file_content_fts USING fts5(
    content,
    content='files',
    content_rowid='rowid',
    tokenize='unicode61'
);
```

Notes:
- Keyed by `files.rowid` (integer B-tree join — fast)
- NOT keyed by `files.path` (string equality join — slow, O(N))
- Populated by embedder pipeline, not the indexer
- Join pattern: `JOIN files ON files.rowid = file_content_fts.rowid`

#### `name_trigrams`

| Column  | Type    | Constraints                        |
|---------|---------|------------------------------------|
| trigram | TEXT    | NOT NULL, INDEX (`idx_trigram`)    |
| file_id | INTEGER | NOT NULL, FK → files.rowid         |

Generation: `{name[i:i+3] for i in range(len(name.lower())-2)}`

Query pattern (Dice coefficient):
```sql
SELECT files.path, files.name, files.extension, files.size, files.mtime,
       (2.0 * count(*) / (? + max(1, length(files.name) - 2))) as similarity
FROM name_trigrams
JOIN files ON files.rowid = name_trigrams.file_id
WHERE name_trigrams.trigram IN (/* query trigrams */)
  AND files.size > 0
GROUP BY name_trigrams.file_id
HAVING similarity >= 0.45
ORDER BY similarity DESC, files.mtime DESC
LIMIT 15
```

#### `file_hashes`

| Column | Type    | Constraints                      |
|--------|---------|----------------------------------|
| path   | TEXT    | PRIMARY KEY                      |
| hash   | TEXT    | NOT NULL, INDEX (`idx_file_hashes`) |
| size   | INTEGER |                                  |

Hash strategy: MD5. Full hash for files ≤50MB. Partial hash (first 1MB + last 1MB + size) for larger files. Duplicate detection query groups by hash.

#### `file_tags`

| Column | Type | Constraints  |
|--------|------|--------------|
| path   | TEXT | PRIMARY KEY  |
| tags   | TEXT | NOT NULL (comma-separated: "work,finance,q3") |

#### `embedding_hashes`

| Column | Type | Constraints |
|--------|------|-------------|
| path   | TEXT | PRIMARY KEY |
| hash   | TEXT | NOT NULL (MD5 of extracted text content) |

Purpose: Skip re-embedding when file content hasn't changed, even if mtime updates.

#### `behavior.db: opens`

| Column    | Type    | Constraints              |
|-----------|---------|--------------------------|
| id        | INTEGER | PRIMARY KEY AUTOINCREMENT |
| query     | TEXT    |                          |
| path      | TEXT    | INDEX (`idx_opens_path`) |
| timestamp | REAL    | Unix epoch               |

#### `behavior.db: copies`

| Column    | Type    | Constraints               |
|-----------|---------|---------------------------|
| id        | INTEGER | PRIMARY KEY AUTOINCREMENT |
| path      | TEXT    | INDEX (`idx_copies_path`) |
| timestamp | REAL    |                           |

#### `behavior.db: searches`

| Column       | Type    | Constraints               |
|--------------|---------|---------------------------|
| id           | INTEGER | PRIMARY KEY AUTOINCREMENT |
| query        | TEXT    |                           |
| result_count | INTEGER |                           |
| timestamp    | REAL    |                           |

---

### Data Lifecycle

| Dataset | Lifecycle | Retention |
|---------|-----------|-----------|
| `files` table | Upserted on every FS event; mirror of actual filesystem | Permanent; stale entries cleaned by `_filter_and_clean()` |
| `file_content_fts` | Updated when text hash changes | Permanent; invalidated by `embedding_hashes` check |
| `file_hashes` | Updated on every `upsert()` | Permanent; deleted in `delete()` |
| `file_tags` | Generated once; regenerated if file changes | Permanent |
| `embedding_hashes` | Updated when content hash changes | Permanent |
| `name_trigrams` | Regenerated on every file upsert | Permanent; deleted with file in `delete()` |
| `behavior.db` | Append-only; never modified | 12-month rolling retention (V1 background task) |
| LanceDB vectors | Updated when content hash changes; old vectors deleted before insertion | Permanent |

### Backup Strategy

| Tier | Strategy |
|------|----------|
| Single user | Weekly `cp index_*.db *.db.bak` via systemd timer (V1) |
| Team Edition | Daily automated backup + WAL archival for point-in-time recovery |
| Enterprise | Continuous WAL shipping + daily full backup + 30-day retention |

---

## RFM Scoring Model

The behavioral boost for a file is computed from three components:

### 1. RFM Score (0–25 points)
```
freq = opens_count + copies_count
days_old = (now - max(all_timestamps)) / 86400
recency = 1.0 / (1.0 + days_old)
monetary = (opens × 2.0) + (copies × 1.0)
rfm_boost = min(25.0, freq × recency × (monetary / freq))
```

Opens are weighted 2× copies because an open delivers more value signal.

### 2. Workspace Affinity (0–15 points)
```
parent_dir = Path(path).parent
dir_accesses = opens_in_dir + copies_in_dir (WHERE path >= dir AND path < dir + '\xff')
workspace_boost = min(15.0, float(dir_accesses) × 0.5)
```

Note: Use range scan (`path >= dir AND path < dir||'\xff'`) instead of `LIKE '%dir%'` — leading wildcard disables B-tree index traversal.

### 3. Time-of-Day Pattern (0–5 points)
```
current_block = datetime.now().hour // 4    # 6 blocks of 4 hours each
count = opens WHERE extension = ext AND hour_block = current_block
time_boost = min(5.0, count × 0.5)
```

### Batch Implementation (Required)
All three queries must be batched into a single DB call per search pass, not per result:

```python
def get_all_boosts_batch(paths: list[str]) -> dict[str, tuple[float, float, float]]:
    """Returns {path: (rfm, workspace, time_boost)} in ONE DB pass."""
    conn = _get_behavior_conn()
    placeholders = ",".join("?" * len(paths))
    opens = conn.execute(
        f"SELECT path, timestamp FROM opens WHERE path IN ({placeholders})", paths
    ).fetchall()
    copies = conn.execute(
        f"SELECT path, timestamp FROM copies WHERE path IN ({placeholders})", paths
    ).fetchall()
    # ... compute all three components from fetched data in Python ...
    return {path: (rfm, workspace, time) for path in paths}
```

---

## Caching Architecture

### Query Result Cache (Current — Broken)

`_cache_set()` has 0 call sites. Cache never populated. Every search re-runs full cascade.

**Fix:** Wrap `search()` in `_search_uncached()` and call `_cache_set()` on every return.

### Correct Cache Implementation

```python
_query_cache: dict[str, tuple[float, list, bool]] = {}
_cache_lock = threading.Lock()
CACHE_TTL = 30.0  # seconds

def _cache_get(key: str):
    with _cache_lock:
        entry = _query_cache.get(key)
        if entry and (time.time() - entry[0]) < CACHE_TTL:
            return entry[1], entry[2]
        if entry:
            del _query_cache[key]
    return None

def _cache_set(key: str, results, fuzzy):
    with _cache_lock:
        if len(_query_cache) >= 200:
            oldest = min(_query_cache, key=lambda k: _query_cache[k][0])
            del _query_cache[oldest]
        _query_cache[key] = (time.time(), results, fuzzy)

def search(query: str, limit: int = 15) -> tuple[list[FileResult], bool]:
    stripped = query.strip()
    cached = _cache_get(stripped)
    if cached:
        return cached
    result = _search_uncached(stripped, limit)
    _cache_set(stripped, result[0], result[1])
    return result
```

### Team Edition Cache (Redis)
```
Key:   f"filechat:search:{sha256(query)[:16]}"
Value: JSON-serialized result list
TTL:   30 seconds
Invalidation: on file.indexed / file.deleted events
```

---

## Thread Safety Model

### Shard Write Locks
```python
from collections import defaultdict
_shard_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

# Usage in upsert():
shard_key = str(get_shard_path(path))
with _shard_locks[shard_key]:
    # DELETE + INSERT operations
```

One lock per shard path, not one global lock. Documents and Downloads shards can be written simultaneously.

### Behavior DB Lock
```python
_behavior_lock = threading.Lock()

def record_open(query: str, path: str) -> None:
    conn = _get_behavior_conn()
    with _behavior_lock:
        conn.execute("INSERT INTO opens (query, path, timestamp) VALUES (?, ?, ?)", ...)
        conn.commit()
```

### Thread Pool (Module-Level, Persistent)
```python
# search.py — module level
_shard_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=min(16, os.cpu_count() or 4),
    thread_name_prefix="shard_query"
)
```

Never create a ThreadPoolExecutor inside a search function — thread spawn overhead defeats the parallelism benefit.

---

## Observability Architecture

### Logging

All modules use named loggers:
```python
log = logging.getLogger("search")   # or "indexer", "embedder", etc.
```

Every caught exception logs at DEBUG (never silently swallowed):
```python
# Current (bad):
except Exception:
    pass

# Required:
except Exception as e:
    log.debug("Operation failed for %s: %s", context_var, e)
```

### Prometheus Metrics (V1)

```python
from prometheus_client import Counter, Histogram, Gauge

search_requests_total   = Counter('filechat_searches_total', 'Total searches', ['tier'])
search_latency_seconds  = Histogram('filechat_search_duration_seconds', 'Search latency',
                                     buckets=[.001, .005, .01, .05, .1, .2, .5, 1.0])
indexed_files_total     = Gauge('filechat_indexed_files_total', 'Files in index')
embedding_queue_size    = Gauge('filechat_embedding_queue_size', 'Embedding queue depth')
ollama_calls_total      = Counter('filechat_ollama_calls_total', 'Ollama calls', ['status'])
behavior_boosts_latency = Histogram('filechat_behavior_boost_ms', 'Behavior scoring latency')
```

### Key Dashboards (Grafana)

**Search Health:** P50/P95/P99 latency timeseries | tier hit distribution pie | fuzzy rate gauge | searches/hour

**Index Health:** File count growth | shard sizes | embedding progress | queue depth

**Behavioral:** Top queries bar chart | top files list | hourly heatmap | WAR per user

### Alerting Thresholds (Team Edition)

| Alert | Condition |
|-------|-----------|
| Index lag | inotify event backlog >5 minutes |
| Embedding stall | Queue depth >500 for >10 minutes |
| Search degraded | P95 latency >500ms for 5+ consecutive requests |
| Ollama down | Unavailable >60 seconds |
| DB corruption | `integrity_check` returns anything other than "ok" |
