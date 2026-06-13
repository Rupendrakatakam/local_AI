"""
behavior.py — User behavior tracking for FileChat.
Stores open/copy history and computes RFM and workspace boosts.
"""
import time
import sqlite3
import datetime
import threading
import logging
from pathlib import Path

log = logging.getLogger("behavior")

BEHAVIOR_DB = Path.home() / ".local" / "share" / "filefinder" / "behavior.db"

_behavior_conn = None
_behavior_init_done = False
_behavior_lock = threading.Lock()

def _get_behavior_conn() -> sqlite3.Connection:
    global _behavior_conn, _behavior_init_done
    if _behavior_conn is not None:
        return _behavior_conn
    with _behavior_lock:
        if _behavior_conn is not None:
            return _behavior_conn
        BEHAVIOR_DB.parent.mkdir(parents=True, exist_ok=True)
        _behavior_conn = sqlite3.connect(BEHAVIOR_DB, check_same_thread=False)
        if not _behavior_init_done:
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
    except Exception as e:
        log.debug("record_open failed for %s: %s", path, e)


def record_copy(path: str) -> None:
    try:
        conn = _get_behavior_conn()
        with _behavior_lock:
            conn.execute("INSERT INTO copies (path, timestamp) VALUES (?, ?)", 
                         (path, time.time()))
            conn.commit()
    except Exception as e:
        log.debug("record_copy failed for %s: %s", path, e)


def record_search(query: str, count: int) -> None:
    try:
        conn = _get_behavior_conn()
        with _behavior_lock:
            conn.execute("INSERT INTO searches (query, result_count, timestamp) VALUES (?, ?, ?)", 
                         (query, count, time.time()))
            conn.commit()
    except Exception as e:
        log.debug("record_search failed for %s: %s", query, e)


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
            cur = conn.execute("SELECT count(*) FROM opens WHERE path >= ? AND path < ?", 
                               (parent_dir + "/", parent_dir + "/\xff"))
            dir_opens = cur.fetchone()[0]
            cur = conn.execute("SELECT count(*) FROM copies WHERE path >= ? AND path < ?", 
                               (parent_dir + "/", parent_dir + "/\xff"))
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

    except Exception as e:
        log.debug("get_all_behavior_boosts failed for %s: %s", path, e)

    return total_boost


def get_all_boosts_batch(paths: list[str]) -> dict[str, float]:
    """Compute behavioral boosts for ALL paths in ONE DB pass."""
    if not paths:
        return {}
    
    result = {}
    try:
        conn = _get_behavior_conn()
        now = time.time()
        
        # 1. RFM Component
        placeholders = ",".join("?" * len(paths))
        opens = conn.execute(
            f"SELECT path, timestamp FROM opens WHERE path IN ({placeholders})", paths
        ).fetchall()
        copies = conn.execute(
            f"SELECT path, timestamp FROM copies WHERE path IN ({placeholders})", paths
        ).fetchall()
        
        from collections import defaultdict
        open_map = defaultdict(list)
        copy_map = defaultdict(list)
        for p, ts in opens:
            open_map[p].append(ts)
        for p, ts in copies:
            copy_map[p].append(ts)
            
        # 2. Workspace Affinity Component
        parents = {}
        for p in paths:
            parent_dir = str(Path(p).parent)
            if parent_dir != "/":
                parents[p] = parent_dir
                
        unique_parents = list(set(parents.values()))
        parent_counts = {}
        if unique_parents:
            queries = []
            params = []
            for parent_dir in unique_parents:
                queries.append("""
                    SELECT ?, 
                    (SELECT count(*) FROM opens WHERE path >= ? AND path < ?) + 
                    (SELECT count(*) FROM copies WHERE path >= ? AND path < ?)
                """)
                params.extend([parent_dir, parent_dir + "/", parent_dir + "/\xff", parent_dir + "/", parent_dir + "/\xff"])
            union_query = " UNION ALL ".join(queries)
            rows = conn.execute(union_query, params).fetchall()
            for parent_dir, count in rows:
                parent_counts[parent_dir] = count
                
        # 3. Time Boost Component
        current_hour = datetime.datetime.now().hour
        block = current_hour // 4
        
        time_query = """
            SELECT path FROM opens 
            WHERE CAST(strftime('%H', datetime(timestamp, 'unixepoch', 'localtime')) AS INTEGER) / 4 = ?
        """
        time_rows = conn.execute(time_query, (block,)).fetchall()
        
        ext_counts = defaultdict(int)
        for (p,) in time_rows:
            ext_p = Path(p).suffix.lower()
            if ext_p:
                ext_counts[ext_p] += 1
                
        # Compute total boost for each path
        for path in paths:
            total_boost = 0.0
            
            # RFM Boost
            o = open_map.get(path, [])
            c = copy_map.get(path, [])
            freq = len(o) + len(c)
            if freq > 0:
                latest = max((o or [0]) + (c or [0]))
                days_old = max(0.0, (now - latest) / 86400.0)
                recency = 1.0 / (1.0 + days_old)
                monetary = (len(o) * 2.0) + (len(c) * 1.0)
                total_boost += min(25.0, freq * recency * (monetary / max(freq, 1.0)))
                
            # Workspace Affinity Boost
            parent_dir = parents.get(path)
            if parent_dir and parent_dir in parent_counts:
                total_accesses = parent_counts[parent_dir]
                total_boost += min(15.0, float(total_accesses) * 0.5)
                
            # Time Boost
            ext = Path(path).suffix.lower()
            if ext:
                count = ext_counts.get(ext, 0)
                total_boost += min(5.0, count * 0.5)
                
            result[path] = total_boost
            
    except Exception as e:
        log.debug("get_all_boosts_batch failed: %s", e)
        for path in paths:
            result[path] = 0.0
            
    return result


def privacy_clear() -> None:
    global _behavior_conn
    try:
        if _behavior_conn:
            _behavior_conn.close()
            _behavior_conn = None
    except Exception as e:
        log.debug("privacy_clear failed: %s", e)
    if BEHAVIOR_DB.exists():
        BEHAVIOR_DB.unlink()

