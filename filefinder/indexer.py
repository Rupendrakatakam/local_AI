"""
indexer.py — Watches ~/home in real-time and keeps a SQLite index updated.
Batch 1 additions:
  - CPU idle-throttling during initial scan (#19)
  - Watchdog event debouncer (#6)
  - Zero-byte file filter (#10)
  - .filefinder_ignore support (#1)
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
WATCH_PATH   = str(Path.home())
DB_PATH      = Path.home() / ".local" / "share" / "filefinder" / "index.db"
LOG_PATH     = Path.home() / ".local" / "share" / "filefinder" / "indexer.log"
IGNORE_FILE  = Path.home() / ".filefinder_ignore"
DEBOUNCE_SEC = 0.5          # merge rapid events on the same file
THROTTLE_SEC = 0.03         # sleep between files during scan when CPU load is high
CPU_LOAD_CAP = 2.0          # 1-min load average threshold to start throttling

# Folders to always skip
SKIP_DIRS = {
    ".git", ".cache", ".npm", ".cargo", "node_modules",
    "__pycache__", ".venv", "venv", ".local/share/Trash",
    "snap",                 # Ubuntu snap — tens of thousands of tiny files
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


# ── .filefinder_ignore loader (#1) ───────────────────────────────────────────
def load_ignore_patterns() -> list[str]:
    """
    Read ~/.filefinder_ignore, one glob pattern per line.
    Lines starting with # are comments.
    Example:
        # ignore large dataset folders
        */datasets/*
        */model_weights/*
        *.tmp
    """
    if not IGNORE_FILE.exists():
        # Create a helpful default file on first run
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
    for pat in patterns:
        if fnmatch.fnmatch(path, pat):
            return True
    return False


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
        # (#10) Skip zero-byte files — temp locks, empty placeholders, etc.
        if st.st_size == 0:
            return
        # (#1) Skip ignored patterns
        if is_ignored(str(p), ignore_patterns):
            return
        conn.execute(
            "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?)",
            (str(p), p.name, p.suffix.lower().lstrip("."), st.st_size, st.st_mtime),
        )
        conn.commit()
    except (PermissionError, OSError):
        pass


def delete(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM files WHERE path = ?", (path,))
    conn.commit()


# ── CPU throttle helper (#19) ─────────────────────────────────────────────────
def throttle_if_busy() -> None:
    """Sleep briefly if 1-min CPU load average is above cap."""
    try:
        load = os.getloadavg()[0]
        if load > CPU_LOAD_CAP:
            time.sleep(THROTTLE_SEC)
    except OSError:
        pass


# ── Initial full scan ─────────────────────────────────────────────────────────
def full_scan(conn: sqlite3.Connection, ignore_patterns: list[str]) -> None:
    log.info("Starting full scan of %s …", WATCH_PATH)
    # Write progress to /tmp so chat.py can show it during boot
    progress_file = Path("/tmp/filefinder.booting")
    count = 0

    for root, dirs, files in os.walk(WATCH_PATH, followlinks=False):
        # Prune skipped and hidden directories in-place
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
            # (#19) Throttle if system is busy
            if count % 100 == 0:
                throttle_if_busy()
                progress_file.write_text(str(count))

    progress_file.unlink(missing_ok=True)
    log.info("Full scan complete — %d files indexed.", count)


# ── Debouncer (#6) ────────────────────────────────────────────────────────────
class Debouncer:
    """
    Coalesces rapid filesystem events on the same path.
    A pending upsert for path X is reset if X fires again within DEBOUNCE_SEC.
    """
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


# ── Watchdog event handler ────────────────────────────────────────────────────
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
    observer = Observer()
    observer.schedule(Handler(debouncer), WATCH_PATH, recursive=True)
    observer.start()
    log.info("Watching %s for changes. Press Ctrl+C to stop.", WATCH_PATH)

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