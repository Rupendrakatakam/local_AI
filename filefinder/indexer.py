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
def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
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
    conn.commit()
    return conn


def upsert(conn: sqlite3.Connection, path: str, ignore_patterns: list[str]) -> None:
    try:
        p = Path(path)
        if not p.is_file():
            return
        st = p.stat()
        if st.st_size == 0:
            return
        if is_ignored(str(p), ignore_patterns):
            return
        conn.execute(
            "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?)",
            (str(p), p.name, p.suffix.lower().lstrip("."), st.st_size, st.st_mtime),
        )
        conn.commit()
        _maybe_vacuum(conn)   # #16
    except (PermissionError, OSError):
        pass


def delete(conn: sqlite3.Connection, path: str) -> None:
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
            upsert(conn, full_path, ignore_patterns)
            count += 1
            if count % 100 == 0:
                throttle_if_busy()
                progress_file.write_text(str(count))
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

    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        conn.close()
        log.info("Indexer stopped.")
