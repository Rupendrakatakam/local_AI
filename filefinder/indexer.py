"""
indexer.py — Watches ~/home in real-time and keeps a SQLite index updated.
Run this as a background service (see filefinder.service).
"""

import os
import sys
import time
import sqlite3
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ── Config ────────────────────────────────────────────────────────────────────
WATCH_PATH = str(Path.home())
DB_PATH    = Path.home() / ".local" / "share" / "filefinder" / "index.db"
LOG_PATH   = Path.home() / ".local" / "share" / "filefinder" / "indexer.log"

# Folders to skip entirely (speeds up scan, avoids noise)
SKIP_DIRS = {
    ".git", ".cache", ".npm", ".cargo", "node_modules",
    "__pycache__", ".venv", "venv", ".local/share/Trash",
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


# ── Database ──────────────────────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")   # safe for concurrent reads
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


def upsert(conn: sqlite3.Connection, path: str) -> None:
    try:
        p = Path(path)
        if not p.is_file():
            return
        st = p.stat()
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


# ── Initial full scan ─────────────────────────────────────────────────────────
def full_scan(conn: sqlite3.Connection) -> None:
    log.info("Starting full scan of %s …", WATCH_PATH)
    count = 0
    for root, dirs, files in os.walk(WATCH_PATH, followlinks=False):
        # Prune skipped directories in-place
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS and not d.startswith(".")
        ]
        for fname in files:
            if fname.startswith("."):
                continue
            upsert(conn, os.path.join(root, fname))
            count += 1
    log.info("Full scan complete — %d files indexed.", count)


# ── Watchdog event handler ────────────────────────────────────────────────────
class Handler(FileSystemEventHandler):
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def on_created(self, event):
        if not event.is_directory:
            upsert(self.conn, event.src_path)
            log.debug("+ %s", event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            delete(self.conn, event.src_path)
            log.debug("- %s", event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            delete(self.conn, event.src_path)
            upsert(self.conn, event.dest_path)
            log.debug("mv %s → %s", event.src_path, event.dest_path)

    def on_modified(self, event):
        if not event.is_directory:
            upsert(self.conn, event.src_path)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    conn = get_db()
    full_scan(conn)

    observer = Observer()
    observer.schedule(Handler(conn), WATCH_PATH, recursive=True)
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
