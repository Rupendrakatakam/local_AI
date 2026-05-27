"""
indexer.py — Watches ~/home in real-time and keeps a SQLite index updated.
Batch 1: CPU throttle, debouncer, zero-byte filter, ignore file
Batch 3: #16 Automatic SQLite VACUUM every 5,000 writes
"""

import os
import re
import sys
import time
import fnmatch
import sqlite3
import logging
import resource
import threading
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ── Config ────────────────────────────────────────────────────────────────────
WATCH_PATH    = str(Path.home())
DB_PATH       = Path.home() / ".local" / "share" / "filefinder" / "index.db"
LOG_PATH      = Path.home() / ".local" / "share" / "filefinder" / "indexer.log"
IGNORE_FILE   = Path.home() / ".filefinder_ignore"
DEBOUNCE_SEC  = 0.5
THROTTLE_SEC  = 0.03
CPU_LOAD_CAP  = 2.0
VACUUM_EVERY  = 5_000    # #16: run VACUUM after this many write operations
MAX_FILE_SIZE = 500 * 1024 * 1024  # Update 75: skip files > 500MB
MEMORY_CAP_MB = 512               # Update 78: pause indexing if RSS exceeds this

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


def _maybe_vacuum(conn: sqlite3.Connection) -> None:
    """Increment write counter; VACUUM in background every VACUUM_EVERY writes."""
    global _write_count
    with _write_lock:
        _write_count += 1
        if _write_count % VACUUM_EVERY == 0:
            count = _write_count
            threading.Thread(target=_run_vacuum, args=(count,), daemon=True).start()


def _run_vacuum(count: int) -> None:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("VACUUM")
        conn.close()
        log.info("VACUUM complete after %d writes.", count)
    except Exception as e:
        log.warning("VACUUM failed: %s", e)


# ── Database ──────────────────────────────────────────────────────────────────
def _generate_trigrams(name: str) -> list[str]:
    s = name.lower()
    if len(s) < 3:
        return []
    return list({s[i:i+3] for i in range(len(s)-2)})


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(str(DB_PATH.parent), 0o700)
    except OSError:
        pass
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try:
        os.chmod(str(DB_PATH), 0o600)
    except OSError:
        pass
    conn.execute("PRAGMA journal_mode=WAL")

    # Update 71: DB integrity check on startup
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result[0] != "ok":
            log.error("DATABASE CORRUPTION DETECTED: %s", result[0])
            log.error("Run: python3 doctor.py --repair")
        else:
            log.info("DB integrity check passed.")
    except Exception as e:
        log.warning("Integrity check failed: %s", e)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            path      TEXT PRIMARY KEY,
            name      TEXT NOT NULL,
            extension TEXT,
            size      INTEGER,
            mtime     REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_name ON files(name COLLATE NOCASE)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ext  ON files(extension)")
    
    # FTS5 Virtual Table for content indexing
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
            name, path,
            content='files', content_rowid='rowid',
            tokenize='unicode61 separators "_-."'
        )
    """)
    
    # FTS5 Triggers
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
            INSERT INTO files_fts(rowid, name, path) VALUES (new.rowid, new.name, new.path);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
            INSERT INTO files_fts(files_fts, rowid, name, path) VALUES('delete', old.rowid, old.name, old.path);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
            INSERT INTO files_fts(files_fts, rowid, name, path) VALUES('delete', old.rowid, old.name, old.path);
            INSERT INTO files_fts(rowid, name, path) VALUES (new.rowid, new.name, new.path);
        END
    """)
    
    # Trigram table + index for typo-tolerant fallback
    conn.execute("""
        CREATE TABLE IF NOT EXISTS name_trigrams (
            trigram TEXT NOT NULL,
            file_id INTEGER NOT NULL,
            FOREIGN KEY(file_id) REFERENCES files(rowid)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trigram ON name_trigrams(trigram)")
    
    # Check if FTS5 is populated when there are files
    try:
        cursor = conn.execute("SELECT count(*) FROM files_fts")
        fts_count = cursor.fetchone()[0]
        if fts_count == 0:
            cursor = conn.execute("SELECT count(*) FROM files")
            files_count = cursor.fetchone()[0]
            if files_count > 0:
                log.info("Rebuilding FTS5 virtual table for %d files...", files_count)
                conn.execute("INSERT INTO files_fts(rowid, name, path) SELECT rowid, name, path FROM files")
                
                # Also populate trigrams if empty
                cursor = conn.execute("SELECT count(*) FROM name_trigrams")
                trig_count = cursor.fetchone()[0]
                if trig_count == 0:
                    log.info("Populating name trigrams table...")
                    rows = conn.execute("SELECT rowid, name FROM files").fetchall()
                    trigram_inserts = []
                    for r_id, name in rows:
                        for tg in _generate_trigrams(name):
                            trigram_inserts.append((tg, r_id))
                    if trigram_inserts:
                        conn.executemany("INSERT INTO name_trigrams (trigram, file_id) VALUES (?, ?)", trigram_inserts)
    except sqlite3.OperationalError as e:
        log.warning("FTS5/Trigram population check failed: %s", e)
        
    conn.commit()
    return conn


def upsert(conn: sqlite3.Connection, path: str, ignore_patterns: list[str], commit: bool = True) -> None:
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
        
        # Check if row exists to delete old trigrams
        cursor = conn.execute("SELECT rowid FROM files WHERE path = ?", (str(p),))
        row = cursor.fetchone()
        if row:
            conn.execute("DELETE FROM name_trigrams WHERE file_id = ?", (row[0],))
            
        cursor = conn.execute(
            "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?)",
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
            conn.commit()
            _maybe_vacuum(conn)   # #16
    except (PermissionError, OSError):
        pass


def delete(conn: sqlite3.Connection, path: str) -> None:
    cursor = conn.execute("SELECT rowid FROM files WHERE path = ?", (path,))
    row = cursor.fetchone()
    if row:
        conn.execute("DELETE FROM name_trigrams WHERE file_id = ?", (row[0],))
    conn.execute("DELETE FROM files WHERE path = ?", (path,))
    conn.commit()
    _maybe_vacuum(conn)   # #16


# ── CPU throttle ──────────────────────────────────────────────────────────────
def throttle_if_busy() -> None:
    try:
        if os.getloadavg()[0] > CPU_LOAD_CAP:
            time.sleep(THROTTLE_SEC)
    except OSError:
        pass


# ── Full scan ─────────────────────────────────────────────────────────────────
def full_scan(conn: sqlite3.Connection, ignore_patterns: list[str]) -> None:
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
            upsert(conn, full_path, ignore_patterns, commit=False)
            count += 1
            if count % 500 == 0:
                conn.commit()
                throttle_if_busy()
                progress_file.write_text(str(count))
            # Update 78: memory cap check every 1000 files
            if count % 1000 == 0:
                _check_memory()
    conn.commit()  # Final commit
    progress_file.unlink(missing_ok=True)
    log.info("Full scan complete — %d files indexed.", count)


# ── Debouncer ─────────────────────────────────────────────────────────────────
class Debouncer:
    def __init__(self, conn: sqlite3.Connection, ignore_patterns: list[str]):
        self.conn = conn
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
        delete(self.conn, path)

    def _do_upsert(self, path: str) -> None:
        with self._lock:
            self._pending.pop(path, None)
        upsert(self.conn, path, self.ignore_patterns)

    # Update 72: Flush all pending timers on shutdown
    def flush_all(self):
        """Cancel all timers and process pending files immediately."""
        with self._lock:
            for path, timer in self._pending.items():
                timer.cancel()
                try:
                    upsert(self.conn, path, self.ignore_patterns)
                except Exception:
                    pass
            self._pending.clear()
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
def _wal_checkpoint_loop(conn):
    """Periodic WAL checkpoint to prevent unbounded WAL growth."""
    while True:
        time.sleep(300)  # every 5 minutes
        try:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
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
    conn = get_db()
    full_scan(conn, ignore_patterns)

    debouncer = Debouncer(conn, ignore_patterns)
    observer  = Observer()
    observer.schedule(Handler(debouncer), WATCH_PATH, recursive=True)
    observer.start()
    log.info("Watching %s for changes.", WATCH_PATH)

    # Update 68: Start WAL checkpoint thread
    threading.Thread(target=_wal_checkpoint_loop, args=(conn,), daemon=True).start()

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
        conn.close()
        log.info("Indexer stopped.")
