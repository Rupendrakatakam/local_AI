"""
indexer.py — Watches ~/home in real-time and keeps multiple SQLite indexes updated.
Batch 1: CPU throttle, debouncer, zero-byte filter, ignore file
Batch 3: #16 Automatic SQLite VACUUM every 5,000 writes
Phase 4: Multi-Index Architecture support
"""

import os
import re
import sys
import time
import fnmatch
import sqlite3
import logging
import ast
import hashlib
import resource
import threading
import mimetypes
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from config_loader import get as cfg
from db_utils import get_shard_path, init_shard

# ── Config ────────────────────────────────────────────────────────────────────
watch_cfg = cfg("watch_path", "~")
WATCH_PATH    = str(Path(watch_cfg).expanduser())
LOG_PATH      = Path.home() / ".local" / "share" / "filefinder" / "indexer.log"
IGNORE_FILE   = Path.home() / ".filefinder_ignore"
DEBOUNCE_SEC  = float(cfg("debounce_sec", 0.5))
THROTTLE_SEC  = 0.03
CPU_LOAD_CAP  = float(cfg("cpu_load_cap", 2.0))
VACUUM_EVERY  = int(cfg("vacuum_every", 5000))
MAX_FILE_SIZE = int(cfg("max_file_size_mb", 500)) * 1024 * 1024
MEMORY_CAP_MB = int(cfg("memory_cap_mb", 512))

SKIP_DIRS = {
    ".git", ".cache", ".npm", ".cargo", "node_modules",
    "__pycache__", ".venv", "venv", ".local/share/Trash", "snap",
}

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("indexer")


# ── Ignore patterns ───────────────────────────────────────────────────────────
def load_ignore_patterns() -> list[str]:
    if not IGNORE_FILE.exists():
        IGNORE_FILE.write_text(
            "# FileChat ignore file — one glob pattern per line\n"
            "# Examples:\n"
            "#   */datasets/*\n"
            "#   */model_weights/*\n"
            "#   *.tmp\n"
        )
        return []
    patterns = []
    for line in IGNORE_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    if patterns:
        log.info("Loaded %d ignore pattern(s) from %s", len(patterns), IGNORE_FILE)
    return patterns


def is_ignored(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in patterns)


# ── Write counter + VACUUM (#16) ─────────────────────────────────────────────
_write_count = 0
_write_lock  = threading.Lock()
from collections import defaultdict
_shard_locks = defaultdict(threading.Lock)

_db_pool: dict[str, sqlite3.Connection] = {}
_db_pool_lock = threading.Lock()

def get_all_active_dbs() -> list[sqlite3.Connection]:
    with _db_pool_lock:
        return list(_db_pool.values())

def get_all_active_dbs_with_paths() -> list[tuple[str, sqlite3.Connection]]:
    with _db_pool_lock:
        return list(_db_pool.items())

def _maybe_vacuum() -> None:
    """Increment write counter; VACUUM in background every VACUUM_EVERY writes."""
    global _write_count
    with _write_lock:
        _write_count += 1
        if _write_count % VACUUM_EVERY == 0:
            count = _write_count
            threading.Thread(target=_run_vacuum, args=(count,), daemon=True).start()


def _run_vacuum(count: int) -> None:
    # Use dedicated connections for VACUUM to avoid locking the shared ones
    for shard_path, _ in get_all_active_dbs_with_paths():
        try:
            with _shard_locks[shard_path]:
                # Temporary connection
                v_conn = sqlite3.connect(shard_path)
                try:
                    v_conn.execute("VACUUM")
                    v_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    v_conn.close()
        except Exception as e:
            log.warning("VACUUM failed on a shard: %s", e)
    log.info("VACUUM complete after %d writes.", count)


# ── Database ──────────────────────────────────────────────────────────────────
def _generate_trigrams(name: str) -> list[str]:
    s = name.lower()
    if len(s) < 3:
        return []
    return list({s[i:i+3] for i in range(len(s)-2)})


def get_db(path: str) -> sqlite3.Connection:
    shard_path = get_shard_path(path)
    key = str(shard_path)
    
    with _db_pool_lock:
        if key in _db_pool:
            return _db_pool[key]
            
        try:
            shard_path.parent.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            pass
        try:
            os.chmod(str(shard_path.parent), 0o700)
        except OSError:
            pass
        conn = sqlite3.connect(shard_path, check_same_thread=False)
        try:
            os.chmod(str(shard_path), 0o600)
        except OSError:
            pass
            
        init_shard(conn)

        # Update 71: DB integrity check on startup
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if result[0] != "ok":
                log.error("DATABASE CORRUPTION DETECTED in %s: %s", shard_path.name, result[0])
            else:
                log.info("DB integrity check passed for %s.", shard_path.name)
        except Exception as e:
            log.warning("Integrity check failed for %s: %s", shard_path.name, e)
        
        # Check if FTS5 is populated when there are files
        try:
            cursor = conn.execute("SELECT count(*) FROM files_fts")
            fts_count = cursor.fetchone()[0]
            if fts_count == 0:
                cursor = conn.execute("SELECT count(*) FROM files")
                files_count = cursor.fetchone()[0]
                if files_count > 0:
                    log.info("Rebuilding FTS5 virtual table for %d files in %s...", files_count, shard_path.name)
                    conn.execute("INSERT INTO files_fts(rowid, name, path) SELECT rowid, name, path FROM files")
                    
                    # Also populate trigrams if empty
                    cursor = conn.execute("SELECT count(*) FROM name_trigrams")
                    trig_count = cursor.fetchone()[0]
                    if trig_count == 0:
                        log.info("Populating name trigrams table for %s...", shard_path.name)
                        rows = conn.execute("SELECT rowid, name FROM files").fetchall()
                        trigram_inserts = []
                        for r_id, name in rows:
                            for tg in _generate_trigrams(name):
                                trigram_inserts.append((tg, r_id))
                        if trigram_inserts:
                            conn.executemany("INSERT INTO name_trigrams (trigram, file_id) VALUES (?, ?)", trigram_inserts)
        except sqlite3.OperationalError as e:
            log.warning("FTS5/Trigram population check failed for %s: %s", shard_path.name, e)
            
        conn.commit()
        _db_pool[key] = conn
        return conn


def _compute_file_hash(path: Path, size: int) -> str:
    """Feature 5.3: Fast hashing for duplicates. Full MD5 if <50MB, else partial hash."""
    hasher = hashlib.md5()
    try:
        with open(path, "rb") as f:
            if size <= 50 * 1024 * 1024:
                # Full hash for small files
                for chunk in iter(lambda: f.read(4096 * 1024), b""):
                    hasher.update(chunk)
            else:
                # Fast partial hash for large files
                hasher.update(f.read(1024 * 1024))
                f.seek(-1024 * 1024, 2)
                hasher.update(f.read(1024 * 1024))
                hasher.update(str(size).encode('utf-8'))
    except OSError:
        pass
    return hasher.hexdigest()

def _extract_symbols_treesitter(path: Path) -> list[tuple[str, str]]:
    """Feature B1: Extract symbols using tree-sitter, fallback to AST for Python."""
    try:
        import tree_sitter
        from tree_sitter import Parser
    except ImportError:
        # Fallback to AST for Python
        if path.suffix != ".py": return []
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            return [(n.name, "class") if isinstance(n, ast.ClassDef) else (n.name, "function") 
                    for n in ast.walk(tree) if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]
        except Exception:
            return []

    ext_map = {
        ".py": ("tree_sitter_python", "language", ["function_definition", "class_definition"]),
        ".js": ("tree_sitter_javascript", "language", ["function_declaration", "class_declaration"]),
        ".ts": ("tree_sitter_typescript", "language_typescript", ["function_declaration", "class_declaration"]),
        ".c": ("tree_sitter_c", "language", ["function_definition"]),
        ".cpp": ("tree_sitter_c", "language", ["function_definition", "class_specifier"]),
        ".rs": ("tree_sitter_rust", "language", ["function_item", "struct_item", "impl_item"]),
        ".go": ("tree_sitter_go", "language", ["function_declaration", "method_declaration"]),
        ".java": ("tree_sitter_java", "language", ["method_declaration", "class_declaration"]),
    }
    
    if path.suffix not in ext_map:
        return []
        
    pkg, lang_func, query_types = ext_map[path.suffix]
    try:
        lang_module = __import__(pkg)
        lang = tree_sitter.Language(getattr(lang_module, lang_func)())
        parser = Parser()
        parser.set_language(lang)
        source = path.read_bytes()
        tree = parser.parse(source)
        
        symbols = []
        def traverse(node):
            if node.type in query_types:
                for child in node.children:
                    if child.type == "identifier" or child.type == "name":
                        sym_type = "function" if "function" in node.type or "method" in node.type else "class"
                        symbols.append((child.text.decode('utf8'), sym_type))
                        break
            for child in node.children:
                traverse(child)
                
        traverse(tree.root_node)
        return symbols
    except Exception as e:
        # Fallback to AST for Python if tree-sitter fails
        if path.suffix == ".py":
            try:
                source_txt = path.read_text(encoding="utf-8")
                tree_ast = ast.parse(source_txt)
                return [(n.name, "class") if isinstance(n, ast.ClassDef) else (n.name, "function") 
                        for n in ast.walk(tree_ast) if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]
            except Exception:
                pass
        return []

# ── Text Content Extraction ────────────────────────────────────────────────────
def _extract_text_content(path: Path) -> str:
    """Extract text content from a file for FTS indexing."""
    try:
        # Check file size - skip very large files
        if path.stat().st_size > 10 * 1024 * 1024:  # 10MB limit
            return ""
        
        ext = path.suffix.lower()
        
        # PDF
        if ext == ".pdf":
            try:
                import fitz
                doc = fitz.open(str(path))
                pages = []
                for page in doc:
                    pages.append(page.get_text())
                    if len(pages) >= 50:
                        break
                doc.close()
                return "\n".join(pages)[:50000]
            except ImportError:
                return ""
            except Exception:
                return ""
        
        # DOCX/DOC
        if ext in (".docx", ".doc"):
            try:
                import mammoth
                with open(path, "rb") as f:
                    result = mammoth.extract_raw_text(f)
                    return result.value[:50000]
            except ImportError:
                return ""
            except Exception:
                return ""
        
        # Plain text files (code, markdown, etc.)
        if ext in {
            '.txt', '.md', '.rst', '.log', '.csv', '.json', '.yaml', '.yml', '.toml',
            '.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.scss', '.less',
            '.cpp', '.c', '.h', '.hpp', '.cs', '.java', '.rs', '.go', '.rb', '.php',
            '.swift', '.kt', '.scala', '.sh', '.bash', '.zsh', '.fish', '.ps1',
            '.sql', '.xml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.properties',
            '.dockerfile', '.gitignore', '.env', '.lock'
        }:
            try:
                return path.read_text(encoding="utf-8", errors="replace")[:50000]
            except Exception:
                return ""
        
        return ""
    except Exception:
        return ""

def upsert(path: str, ignore_patterns: list[str], commit: bool = True) -> None:
    try:
        p = Path(path)
        if not p.is_file():
            return
        st = p.stat()
        if st.st_size == 0:
            return
        # Update 75: skip very large files
        if st.st_size > MAX_FILE_SIZE:
            return
        if is_ignored(str(p), ignore_patterns):
            return
        
        # Ensure we skip hidden directories (like .git) and SKIP_DIRS 
        if any(part.startswith('.') and part != '.' for part in p.parts[:-1]):
            return
        if any(part in SKIP_DIRS for part in p.parts):
            return
            
        conn = get_db(path)
        
        # Feature 5.3: Compute hash outside the db lock
        file_hash = _compute_file_hash(p, st.st_size)
        
        shard_key = str(get_shard_path(path))
        with _shard_locks[shard_key]:
            # Check if row exists to check if modified
            cursor = conn.execute("SELECT rowid, size, mtime FROM files WHERE path = ?", (str(p),))
            row = cursor.fetchone()
            if row:
                if row[1] == st.st_size and abs(row[2] - st.st_mtime) < 0.001:
                    return
                conn.execute("DELETE FROM name_trigrams WHERE file_id = ?", (row[0],))
                conn.execute("DELETE FROM files WHERE path = ?", (str(p),))
                
            cursor = conn.execute(
                "INSERT INTO files VALUES (?,?,?,?,?)",
                (str(p), p.name, p.suffix.lower().lstrip("."), st.st_size, st.st_mtime),
            )
            rowid = cursor.lastrowid
            
            # Populate trigrams
            trigrams = _generate_trigrams(p.name)
            if trigrams:
                conn.executemany(
                    "INSERT INTO name_trigrams (trigram, file_id) VALUES (?, ?)",
                    [(tg, rowid) for tg in trigrams]
                )
                
            # Store duplicate hash
            conn.execute("INSERT OR REPLACE INTO file_hashes (path, hash, size) VALUES (?, ?, ?)", 
                         (str(p), file_hash, st.st_size))
                         
            # Feature 1.1: Code symbols
            conn.execute("DELETE FROM code_symbols WHERE path = ?", (str(p),))
            if p.suffix in {'.py', '.js', '.ts', '.c', '.cpp', '.rs', '.go', '.java'}:
                symbols = _extract_symbols_treesitter(p)
                if symbols:
                    conn.executemany("INSERT INTO code_symbols (symbol, path, type) VALUES (?, ?, ?)",
                                     [(sym[0], str(p), sym[1]) for sym in symbols])
            
            # Extract and index text content for content search
            conn.execute("DELETE FROM file_content_fts WHERE rowid = ?", (rowid,))
            content = _extract_text_content(p)
            if content:
                conn.execute("INSERT INTO file_content_fts(rowid, content) VALUES (?, ?)", (rowid, content))
            
            if commit:
                conn.commit()
            
        # Semantic embedding integration (Phase 2)
        try:
            from embedder import get_pipeline
            pipeline = get_pipeline()
            # Start worker safely (it checks if already running)
            pipeline.start_worker()
            pipeline.enqueue(str(p), st.st_mtime)
        except ImportError:
            pass
            
        if commit:
            _maybe_vacuum()   # #16
    except (PermissionError, OSError):
        pass


def delete(path: str) -> None:
    conn = get_db(path)
    shard_key = str(get_shard_path(path))
    with _shard_locks[shard_key]:
        conn.execute("DELETE FROM name_trigrams WHERE file_id IN (SELECT rowid FROM files WHERE path = ?)", (path,))
        conn.execute("DELETE FROM file_content_fts WHERE rowid IN (SELECT rowid FROM files WHERE path = ?)", (path,))
        conn.execute("DELETE FROM code_symbols WHERE path = ?", (path,))
        conn.execute("DELETE FROM files WHERE path = ?", (path,))
        conn.commit()
    _maybe_vacuum()   # #16


# ── CPU throttle ──────────────────────────────────────────────────────────────
def throttle_if_busy() -> None:
    try:
        if os.getloadavg()[0] > CPU_LOAD_CAP:
            time.sleep(THROTTLE_SEC)
    except OSError:
        pass


# ── Full scan ─────────────────────────────────────────────────────────────────
def full_scan(ignore_patterns: list[str]) -> None:
    log.info("Starting full scan of %s …", WATCH_PATH)
    progress_file = Path("/tmp/filefinder.booting")
    count = 0
    for root, dirs, files in os.walk(WATCH_PATH, followlinks=False):
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS
            and not d.startswith(".")
            and not is_ignored(os.path.join(root, d), ignore_patterns)
        ]
        for fname in files:
            if fname.startswith("."):
                continue
            full_path = os.path.join(root, fname)
            upsert(full_path, ignore_patterns, commit=False)
            count += 1
            if count % 500 == 0:
                for shard_key, conn in get_all_active_dbs_with_paths():
                    with _shard_locks[shard_key]:
                        try:
                            conn.execute("DELETE FROM files WHERE size = 0")
                            conn.commit()
                        except sqlite3.OperationalError:
                            pass
                throttle_if_busy()
                progress_file.write_text(str(count))
            # Update 78: memory cap check every 1000 files
            if count % 1000 == 0:
                _check_memory()
    with _db_pool_lock:
        for conn in _db_pool.values():
            conn.commit()  # Final commit
    progress_file.unlink(missing_ok=True)
    log.info("Full scan complete — %d files indexed.", count)


# ── Debouncer ─────────────────────────────────────────────────────────────────
class Debouncer:
    def __init__(self, ignore_patterns: list[str]):
        self.ignore_patterns = ignore_patterns
        self._pending: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def schedule_upsert(self, path: str) -> None:
        with self._lock:
            if path in self._pending:
                self._pending[path].cancel()
            t = threading.Timer(DEBOUNCE_SEC, self._do_upsert, args=[path])
            self._pending[path] = t
            t.start()

    def schedule_delete(self, path: str) -> None:
        with self._lock:
            if path in self._pending:
                self._pending[path].cancel()
                del self._pending[path]
        delete(path)

    def _do_upsert(self, path: str) -> None:
        with self._lock:
            self._pending.pop(path, None)
        upsert(path, self.ignore_patterns)

    # Update 72: Flush all pending timers on shutdown
    def flush_all(self):
        """Cancel all timers and process pending files immediately."""
        with self._lock:
            pending_copy = list(self._pending.keys())
            for timer in self._pending.values():
                timer.cancel()
            self._pending.clear()
        
        for path in pending_copy:
            try:
                upsert(path, self.ignore_patterns)
            except Exception:
                pass
        log.info("Flushed all pending upserts.")


# ── Memory monitor (Update 78) ───────────────────────────────────────────────
def _check_memory():
    """Returns current RSS in MB. Pauses if over cap."""
    try:
        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KB -> MB on Linux
        if rss_mb > MEMORY_CAP_MB:
            log.warning("Memory usage %.0f MB exceeds cap %d MB — pausing 5s", rss_mb, MEMORY_CAP_MB)
            time.sleep(5)
        return rss_mb
    except Exception:
        return 0


# ── WAL Checkpoint (Update 68) ────────────────────────────────────────────────
def _wal_checkpoint_loop():
    """Periodic WAL checkpoint to prevent unbounded WAL growth."""
    while True:
        time.sleep(300)  # every 5 minutes
        try:
            # Snapshot connections to avoid blocking _db_pool_lock
            dbs = get_all_active_dbs()
            for conn in dbs:
                try:
                    # PASSIVE checkpoint doesn't require a write lock, so we don't need _shard_locks
                    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                except Exception:
                    pass
            log.debug("WAL checkpoint complete.")
        except Exception:
            pass


# ── Watchdog ──────────────────────────────────────────────────────────────────
class Handler(FileSystemEventHandler):
    def __init__(self, debouncer: Debouncer):
        self.db = debouncer

    def on_created(self, event):
        if not event.is_directory:
            self.db.schedule_upsert(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self.db.schedule_delete(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.db.schedule_delete(event.src_path)
            self.db.schedule_upsert(event.dest_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.db.schedule_upsert(event.src_path)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ignore_patterns = load_ignore_patterns()
    full_scan(ignore_patterns)

    debouncer = Debouncer(ignore_patterns)
    try:
        observer  = Observer()
        observer.schedule(Handler(debouncer), WATCH_PATH, recursive=True)
        observer.start()
        log.info("Watching %s for changes (using inotify).", WATCH_PATH)
    except OSError as e:
        if e.errno == 28:  # inotify watch limit reached
            current_watches = "unknown"
            try:
                with open("/proc/sys/fs/inotify/max_user_watches") as f:
                    current_watches = f.read().strip()
            except Exception:
                pass
            log.warning("WARNING: inotify watch limit reached (currently %s).", current_watches)
            log.warning("To fix this permanently, run: echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf && sudo sysctl -p")
            log.warning("Falling back to PollingObserver (will consume slightly more CPU/IO)...")
            from watchdog.observers.polling import PollingObserver
            observer = PollingObserver()
            observer.schedule(Handler(debouncer), WATCH_PATH, recursive=True)
            observer.start()
            log.info("Watching %s for changes (using polling fallback).", WATCH_PATH)
        else:
            raise

    # Update 68: Start WAL checkpoint thread
    threading.Thread(target=_wal_checkpoint_loop, daemon=True).start()
    
    # Feature B3: Background Reranker Training
    try:
        from reranker import train_reranker_background
        train_reranker_background()
    except Exception:
        pass

    def _backup_thread():
        import backup
        interval_hours = float(cfg("backup_interval_hours", 168))
        interval_seconds = interval_hours * 3600
        while True:
            time.sleep(interval_seconds)
            try:
                log.info("Starting automated backup...")
                backup.perform_backup()
            except Exception as e:
                log.error("Automated backup failed: %s", e)

    threading.Thread(target=_backup_thread, daemon=True).start()

    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        # Update 72: Flush pending before shutdown
        log.info("Flushing pending upserts before shutdown...")
        debouncer.flush_all()
        observer.stop()
        observer.join()
        for conn in get_all_active_dbs():
            conn.close()
        log.info("Indexer stopped.")
