"""
behavior.py — User behavior tracking for FileChat.
Stores open/copy history and computes RFM and workspace boosts.
"""
import time
import sqlite3
import datetime
import threading
from pathlib import Path

BEHAVIOR_DB = Path.home() / ".local" / "share" / "filefinder" / "behavior.db"

_behavior_conn = None
_behavior_init_done = False
_behavior_lock = threading.Lock()

def _get_behavior_conn() -> sqlite3.Connection:
    global _behavior_conn, _behavior_init_done
    if _behavior_conn is None:
        BEHAVIOR_DB.parent.mkdir(parents=True, exist_ok=True)
        _behavior_conn = sqlite3.connect(BEHAVIOR_DB, check_same_thread=False)
        if not _behavior_init_done:
            with _behavior_lock:
                _behavior_conn.execute("""
                    CREATE TABLE IF NOT EXISTS opens (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        query TEXT,
                        path TEXT NOT NULL,
                        timestamp REAL NOT NULL
                    )
                """)
                _behavior_conn.execute("""
                    CREATE TABLE IF NOT EXISTS copies (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        path TEXT NOT NULL,
                        timestamp REAL NOT NULL
                    )
                """)
                _behavior_conn.execute("""
                    CREATE TABLE IF NOT EXISTS searches (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        query TEXT NOT NULL,
                        result_count INTEGER,
                        timestamp REAL NOT NULL
                    )
                """)
                _behavior_conn.execute("CREATE INDEX IF NOT EXISTS idx_opens_path ON opens(path)")
                _behavior_conn.execute("CREATE INDEX IF NOT EXISTS idx_copies_path ON copies(path)")
                _behavior_conn.commit()
                _behavior_init_done = True
    return _behavior_conn


def get_behavior_db() -> sqlite3.Connection:
    """Returns a temporary connection to the behavior database for external use."""
    _get_behavior_conn() # Ensure initialized
    return sqlite3.connect(BEHAVIOR_DB)

def record_open(query: str, path: str) -> None:
    try:
        conn = _get_behavior_conn()
        with _behavior_lock:
            conn.execute("INSERT INTO opens (query, path, timestamp) VALUES (?, ?, ?)", 
                         (query, path, time.time()))
            conn.commit()
    except Exception:
        pass


def record_copy(path: str) -> None:
    try:
        conn = _get_behavior_conn()
        with _behavior_lock:
            conn.execute("INSERT INTO copies (path, timestamp) VALUES (?, ?)", 
                         (path, time.time()))
            conn.commit()
    except Exception:
        pass


def record_search(query: str, count: int) -> None:
    try:
        conn = _get_behavior_conn()
        with _behavior_lock:
            conn.execute("INSERT INTO searches (query, result_count, timestamp) VALUES (?, ?, ?)", 
                         (query, count, time.time()))
            conn.commit()
    except Exception:
        pass


def get_all_behavior_boosts(path: str) -> float:
    """Computes RFM, workspace affinity, and time boosts using a single persistent connection."""
    total_boost = 0.0
    try:
        conn = _get_behavior_conn()
        
        # 1. RFM Boost
        cur = conn.execute("SELECT timestamp FROM opens WHERE path=?", (path,))
        opens = [row[0] for row in cur.fetchall()]
        cur = conn.execute("SELECT timestamp FROM copies WHERE path=?", (path,))
        copies = [row[0] for row in cur.fetchall()]
        
        freq = len(opens) + len(copies)
        if freq > 0:
            latest = max((opens if opens else [0]) + (copies if copies else [0]))
            days_old = max(0.0, (time.time() - latest) / 86400.0)
            recency = 1.0 / (1.0 + days_old)
            monetary = (len(opens) * 2.0) + (len(copies) * 1.0)
            total_boost += min(25.0, freq * recency * (monetary / max(freq, 1.0)))

        # 2. Workspace Affinity Boost
        parent_dir = str(Path(path).parent)
        if parent_dir != "/":
            cur = conn.execute("SELECT count(*) FROM opens WHERE path LIKE ?", (f"{parent_dir}%",))
            dir_opens = cur.fetchone()[0]
            cur = conn.execute("SELECT count(*) FROM copies WHERE path LIKE ?", (f"{parent_dir}%",))
            dir_copies = cur.fetchone()[0]
            total_accesses = dir_opens + dir_copies
            total_boost += min(15.0, float(total_accesses) * 0.5)

        # 3. Time Boost
        ext = Path(path).suffix.lower()
        if ext:
            current_hour = datetime.datetime.now().hour
            block = current_hour // 4
            query = """
                SELECT count(*) FROM opens 
                WHERE path LIKE ? 
                AND CAST(strftime('%H', datetime(timestamp, 'unixepoch', 'localtime')) AS INTEGER) / 4 = ?
            """
            count = conn.execute(query, (f"%{ext}", block)).fetchone()[0]
            total_boost += min(5.0, count * 0.5)

    except Exception:
        pass

    return total_boost


def privacy_clear() -> None:
    global _behavior_conn
    try:
        if _behavior_conn:
            _behavior_conn.close()
            _behavior_conn = None
    except Exception:
        pass
    if BEHAVIOR_DB.exists():
        BEHAVIOR_DB.unlink()

