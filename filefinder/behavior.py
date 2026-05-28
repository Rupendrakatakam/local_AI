"""
behavior.py — User behavior tracking for FileChat.
Stores open/copy history and computes RFM and workspace boosts.
"""
import time
import sqlite3
import datetime
from pathlib import Path
from collections import defaultdict

BEHAVIOR_DB = Path.home() / ".local" / "share" / "filefinder" / "behavior.db"

def get_behavior_db() -> sqlite3.Connection:
    """Returns a connection to the behavior database, initializing if needed."""
    BEHAVIOR_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(BEHAVIOR_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS opens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT,
            path TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS copies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            result_count INTEGER,
            timestamp REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_opens_path ON opens(path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_copies_path ON copies(path)")
    conn.commit()
    return conn


def record_open(query: str, path: str) -> None:
    """Record that the user opened a file."""
    try:
        conn = get_behavior_db()
        conn.execute("INSERT INTO opens (query, path, timestamp) VALUES (?, ?, ?)", 
                     (query, path, time.time()))
        conn.commit()
        conn.close()
    except Exception:
        pass


def record_copy(path: str) -> None:
    """Record that the user copied a file path."""
    try:
        conn = get_behavior_db()
        conn.execute("INSERT INTO copies (path, timestamp) VALUES (?, ?)", 
                     (path, time.time()))
        conn.commit()
        conn.close()
    except Exception:
        pass


def record_search(query: str, count: int) -> None:
    """Record a search query execution."""
    try:
        conn = get_behavior_db()
        conn.execute("INSERT INTO searches (query, result_count, timestamp) VALUES (?, ?, ?)", 
                     (query, count, time.time()))
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_rfm_boost(path: str) -> float:
    """
    Calculate RFM boost for a file path. Returns 0.0–25.0.
    """
    try:
        conn = get_behavior_db()
        # Get opens
        cur = conn.execute("SELECT timestamp FROM opens WHERE path=?", (path,))
        opens = [row[0] for row in cur.fetchall()]
        
        # Get copies
        cur = conn.execute("SELECT timestamp FROM copies WHERE path=?", (path,))
        copies = [row[0] for row in cur.fetchall()]
        conn.close()
        
        freq = len(opens) + len(copies)
        if freq == 0:
            return 0.0
            
        latest = max((opens if opens else [0]) + (copies if copies else [0]))
        days_old = max(0.0, (time.time() - latest) / 86400.0)
        
        recency = 1.0 / (1.0 + days_old)
        monetary = (len(opens) * 2.0) + (len(copies) * 1.0)
        
        boost = min(25.0, freq * recency * (monetary / max(freq, 1.0)))
        return boost
    except Exception:
        return 0.0


def get_workspace_affinity(path: str) -> float:
    """
    Returns 0.0–15.0 boost based on how often files in this 
    directory tree have been accessed.
    """
    try:
        parent_dir = str(Path(path).parent)
        if parent_dir == "/":
            return 0.0
            
        conn = get_behavior_db()
        cur = conn.execute("SELECT count(*) FROM opens WHERE path LIKE ?", (f"{parent_dir}%",))
        opens = cur.fetchone()[0]
        
        cur = conn.execute("SELECT count(*) FROM copies WHERE path LIKE ?", (f"{parent_dir}%",))
        copies = cur.fetchone()[0]
        conn.close()
        
        total_accesses = opens + copies
        return min(15.0, float(total_accesses) * 0.5)
    except Exception:
        return 0.0


def get_time_boost(path: str) -> float:
    """
    Returns 0.0–5.0 boost if the file's extension matches what the 
    user typically accesses at this hour of day.
    """
    try:
        ext = Path(path).suffix.lower()
        if not ext:
            return 0.0
            
        current_hour = datetime.datetime.now().hour
        # Group into 4-hour blocks
        block = current_hour // 4
        
        conn = get_behavior_db()
        # Find all paths opened in this block that match the extension
        query = """
            SELECT count(*) FROM opens 
            WHERE path LIKE ? 
            AND CAST(strftime('%H', datetime(timestamp, 'unixepoch', 'localtime')) AS INTEGER) / 4 = ?
        """
        count = conn.execute(query, (f"%{ext}", block)).fetchone()[0]
        conn.close()
        
        return min(5.0, count * 0.5)
    except Exception:
        return 0.0


def privacy_clear() -> None:
    """Wipe all behavioral data."""
    if BEHAVIOR_DB.exists():
        BEHAVIOR_DB.unlink()
