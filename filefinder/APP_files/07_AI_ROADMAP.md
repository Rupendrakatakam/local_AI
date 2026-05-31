# FileChat — AI & Automation Roadmap

---

## Current AI Stack (MVP)

### Intent Extraction — Ollama / phi3:mini

**Input:** Raw natural language query string
**Output:** `{keywords: [], extension: null|str, directory: null|str}`
**Latency:** ~150ms (local Ollama round-trip)
**Fallback:** Regex keyword extractor if Ollama offline

System prompt (current):
```
You are a file-search intent extractor.
Return ONLY a JSON object — no explanation, no markdown.
Fields:
  "keywords"  : filename keywords (lowercase). Split compound terms.
                Exclude: find, where, my, the, can, you, show, me, file, named, called.
  "extension" : single extension without dot, e.g. "py", "pdf", or null.
  "directory" : folder name hint or null.
```

Known issues:
- Merges compound keywords ("on-line estimation" → "online estimation")
- Includes filler words as keywords on some queries
- Solution: `_normalize_keywords()` post-processing splits on `_`, `-`, `.`, camelCase

### Text Embeddings — all-mpnet-base-v2 (768-dim)

- Chunks: 400 words, 80-word overlap
- Normalization: L2 normalized vectors for cosine similarity
- Storage: LanceDB columnar database
- Throughput: ~2 files/sec CPU, ~50 files/sec GPU (RTX 3050)
- Cold start: loads from `~/.cache/torch` in offline mode (no HF Hub requests)

### Image Embeddings — clip-ViT-B-32 (512-dim)

- Handles JPG, PNG, WEBP
- Text query → image retrieval ("find screenshots with error messages")
- OCR fallback via pytesseract for text-in-image extraction
- Co-stored in LanceDB `image_chunks` table

### Auto-Tagging — phi3:mini (background worker)

- Input: filename + first 500 chars of extracted content
- Output: 1–3 comma-separated category tags
- Prompt: "output 1-3 comma-separated categories (e.g. work, personal, finance, code, media). Only output tags, nothing else."
- Runs in separate queue — does not block embedding pipeline
- Tags stored in `file_tags` table; exposed via `tag:` search prefix

### RFM Behavioral Model

- No ML inference — pure formula: `recency × frequency × monetary_value`
- Recency: `1 / (1 + days_since_last_access)`
- Monetary: opens weighted 2×, copies weighted 1×
- Workspace affinity: open count in parent directory tree
- Time-of-day: extension-based hour block pattern
- Score range: 0–45 points added to relevance score

---

## V1 AI Improvements

### Embedding-Based Synonym Expansion

Replace static `FALLBACK_SYNONYMS` dict with dynamic nearest-neighbor expansion:

```python
@lru_cache(maxsize=1024)
def _embedding_synonyms(word: str, top_k: int = 3) -> list[str]:
    """Find semantically similar terms using the loaded embedding model."""
    model = get_pipeline()._get_text_model()
    if model is None:
        return FALLBACK_SYNONYMS.get(word, [])
    word_vec = model.encode([word], normalize_embeddings=True)[0]
    # Compare against a vocabulary index (built once at startup from common filename tokens)
    # Returns top_k nearest terms
    ...
```

Benefit: `"quarterly"` also matches `"q3"`, `"q4"`. `"budget"` matches `"finance"`, `"cost"`. Domain-specific without manual curation.

### Streaming Search (WebSocket)

```
Client sends:  {q: "machine learning notes", requestId: "abc123"}

Server streams:
  t=5ms:   {tier: "fts5",     results: [top 10 keyword matches], done: false}
  t=50ms:  {tier: "semantic", results: [top 10 semantic matches], done: false}
  t=60ms:  {tier: "fused",    results: [RRF merged + ranked],    done: true}
```

Eliminates the "waiting for semantic search" perception problem.

### Learned Reranker (Light)

Replace heuristic `_score_result()` with a trained logistic regression:

**Features (20 total):**
- Keyword coverage ratio (matched_atoms / total_atoms)
- Exact name match (binary)
- Prefix match (binary)
- File extension matches requested (binary)
- Recency score (days_old decay)
- Path depth (penalty)
- RFM score
- Workspace affinity score
- Time-of-day boost
- BM25 rank from FTS5
- Semantic cosine similarity
- File size (log-scaled)
- Name length (shorter = higher priority)
- Is in home directory root (binary)
- Query length (affects expected specificity)

**Training:** Implicit feedback from `behavior.db`. Open = positive signal (score +1). Search with no open = negative signal for top-3 non-opened results (score -0.5). Retrain weekly on accumulated data.

**Model:** scikit-learn `LogisticRegression`, 20 features, ~1KB serialized. Inference <0.1ms.

---

## V2 AI — Advanced Intelligence

### Code Symbol Indexing (tree-sitter)

```python
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)

def extract_symbols(path: str) -> list[dict]:
    """Extract function/class names, docstrings, and type hints."""
    code = Path(path).read_bytes()
    tree = parser.parse(code)
    symbols = []
    for node in traverse(tree.root_node):
        if node.type in ('function_definition', 'class_definition'):
            name = node.child_by_field_name('name').text.decode()
            symbols.append({'type': node.type, 'name': name, 'line': node.start_point[0]})
    return symbols
```

Storage: `code_symbols` FTS5 table with columns `(symbol_name, symbol_type, path, line_number)`.
Query: `code:calculate_tax` → `SELECT path FROM code_symbols WHERE symbol_name MATCH 'calculate_tax'`.

Supported languages (via tree-sitter grammars): Python, JavaScript, TypeScript, C, C++, Rust, Go, Java, Kotlin.

### Multi-Language Semantic Search

Replace `all-mpnet-base-v2` with `multilingual-e5-large` for non-English content:
- Supports 100+ languages in one model
- 1024-dim vectors (larger but more accurate)
- Required for users with non-English filenames or document content
- Configurable in `config.json`: `"embedding_model": "intfloat/multilingual-e5-large"`

---

## V3 — Autonomous AI Agents

### File Intelligence Agent

```
User: "What was I working on last Tuesday?"

Agent pipeline:
1. Query behavior.db: SELECT path, query, timestamp FROM opens
   WHERE timestamp BETWEEN tuesday_start AND tuesday_end
   ORDER BY timestamp DESC

2. Group by directory/project (infer project from path patterns)

3. Semantic search for related files not directly opened
   (files in same directories as opened files)

4. Generate summary via Ollama:
   "Last Tuesday you were primarily working on your thesis
   (5 files in ~/Research/thesis/) and the LQR controller
   code (3 files in ~/Projects/robotics/). Here are the
   most relevant files..."

5. Present 5 file cards with one-click open
```

### Organization Agent

```
User: "Clean up my Downloads folder"

Agent pipeline:
1. Scan ~/Downloads: file_hashes + file_tags + embeddings
2. Identify duplicate groups (file_hashes JOIN)
3. HDBSCAN clustering on file embeddings → topic groups
4. LLM generates suggested folder structure:
   "Create: ~/Downloads/Papers/, ~/Downloads/Code/, 
    ~/Downloads/Media/. Move X files, delete Y duplicates."
5. Present plan with preview → user approves
6. Execute with undo history (V3)
```

### Context Agent (IDE Integration)

```
Developer opens new_controller.py in VS Code

FileChat VS Code Extension:
1. Extract imports + function names from current file
2. Query FileChat API:
   GET /api/search?q=code:PIDController+similar:new_controller.py
3. Surface 3-5 related files in sidebar:
   - existing_controller.py (semantic match)
   - controller_tests.py (code symbol match)
   - controller_design.pdf (content match)
4. Refresh on every file save
```

### MCP Server Interface (V3)

FileChat as a retrieval backend for AI agents:

```json
// MCP server manifest
{
  "name": "filechat",
  "description": "Local file search and retrieval",
  "tools": [
    {
      "name": "search_files",
      "description": "Search local files by name, content, or meaning",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "limit": {"type": "integer", "default": 10},
          "type": {"type": "string", "description": "File extension filter"}
        }
      }
    },
    {
      "name": "get_file_content",
      "description": "Read the content of a local file",
      "inputSchema": {
        "type": "object",
        "properties": {
          "path": {"type": "string"}
        }
      }
    }
  ]
}
```

Usage: Claude Desktop calls `search_files(query="Q3 revenue report")` → FileChat returns ranked results → agent reads content and grounds response in local file data.

---

## V4 — Predictive Intelligence

### Morning Briefing

```python
# Triggered at 8:00 AM via systemd timer
def generate_morning_briefing():
    # 1. Analyze last 7 days of behavior.db
    recent_files = get_recent_opens(days=7)
    active_projects = cluster_by_directory(recent_files)

    # 2. Check today's calendar (local .ics file if present)
    events = parse_local_calendar()

    # 3. Match calendar topics to file clusters
    relevant_files = match_events_to_files(events, active_projects)

    # 4. Generate briefing
    prompt = f"Today's meetings: {events}. Recent files: {recent_files[:10]}. 
               Suggest the 5 most likely files needed today."
    briefing = ollama_query(prompt)

    # 5. Show as system notification with file pills
    show_notification(briefing, file_links=relevant_files[:5])
```

### Access Pattern Prediction

```python
# Time-series model on behavior.db
# Feature: hour-of-day × day-of-week × file extension
# Target: probability of access in next 2 hours

import numpy as np
from collections import defaultdict

def predict_likely_files(horizon_hours: int = 2) -> list[str]:
    """Predict which files are likely accessed in the next N hours."""
    conn = get_behavior_conn()
    current_hour = datetime.now().hour
    current_dow = datetime.now().weekday()

    # Build access probability matrix from history
    cur = conn.execute("""
        SELECT path, 
               CAST(strftime('%H', datetime(timestamp,'unixepoch','localtime')) AS INT) as hour,
               CAST(strftime('%w', datetime(timestamp,'unixepoch','localtime')) AS INT) as dow,
               count(*) as accesses
        FROM opens
        WHERE timestamp > ?
        GROUP BY path, hour, dow
    """, (time.time() - 90 * 86400,))  # Last 90 days

    # ... build probability model, return top-N files ...
```

---

## V5 — Knowledge Graph

### Node Types
- `File` (path, name, extension, size, mtime)
- `Person` (name — extracted from document content via NER)
- `Project` (inferred from directory structure + clustering)
- `Topic` (from auto-tags + embedding clusters)
- `Date` (extracted from document content)

### Edge Types

| Edge | Description |
|------|-------------|
| `co_accessed_with` | Files opened in same session (within 1 hour) |
| `contains_entity` | File → mentions Person/Date/Organization |
| `semantic_similar_to` | Cosine similarity >0.8 between embeddings |
| `version_of` | Similar name in same directory (thesis_v1 → thesis_v2) |
| `references` | Citation extracted from PDF references section |

### Queries

```python
# "All files related to the Kalman filter project"
graph.query("""
    MATCH (f:File)-[:SEMANTIC_SIMILAR_TO*1..2]-(seed:File)
    WHERE seed.name CONTAINS 'kalman'
    RETURN f ORDER BY f.mtime DESC LIMIT 20
""")

# "What files did I touch the week before the thesis deadline?"
graph.query("""
    MATCH (f:File)-[:CO_ACCESSED_WITH*1..3]-(anchor:File)
    WHERE anchor.name CONTAINS 'thesis'
      AND f.mtime BETWEEN deadline_minus_7d AND deadline
    RETURN f ORDER BY access_count DESC
""")
```

### Implementation: NetworkX + DuckDB

- NetworkX for in-memory graph traversal and clustering
- DuckDB for persistent edge storage and analytical queries
- Rebuild on demand (`/graph rebuild`) from existing `behavior.db` + LanceDB + `file_tags`
