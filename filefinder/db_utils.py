"""
db_utils.py — Shard path resolution for Multi-Index Architecture.
"""
from pathlib import Path
from config_loader import get as cfg

BASE_DIR = Path.home() / ".local" / "share" / "filefinder"

def get_watch_path() -> Path:
    return Path(cfg("watch_path", "~")).expanduser().resolve()

def get_shard_path(filepath: str) -> Path:
    """
    Determine which SQLite shard a file belongs to based on its top-level directory.
    E.g. ~/Documents/file.txt -> index_Documents.db
    """
    watch_path = get_watch_path()
    try:
        rel = Path(filepath).resolve().relative_to(watch_path)
        parts = rel.parts
        if len(parts) > 1:
            # It's inside a top-level directory
            shard_name = f"index_{parts[0]}.db"
        else:
            # It's in the watch_path directly
            shard_name = "index_root.db"
    except ValueError:
        # If filepath is outside watch_path, fallback to root
        shard_name = "index_root.db"
        
    return BASE_DIR / shard_name

def get_all_shard_paths() -> list[Path]:
    """Return a list of all existing SQLite shard database paths."""
    if not BASE_DIR.exists():
        return []
    # Filter out dot-directory shards (e.g. index_.git.db) — these should never be searched
    shards = [
        p for p in BASE_DIR.glob("index_*.db")
        if not p.stem.startswith("index_.")  # excludes index_.git, index_.cache, etc.
    ]
    legacy = BASE_DIR / "index.db"
    if legacy.exists() and legacy not in shards:
        shards.append(legacy)
    return shards

def init_shard(conn) -> None:
    """Initialize a new SQLite shard connection with required PRAGMAs and tables."""
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
    
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
            name, path,
            content='files', content_rowid='rowid',
            tokenize='unicode61 separators "_-."'
        )
    """)
    
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS file_content_fts USING fts5(
            content,
            content='files', content_rowid='rowid',
            tokenize='unicode61'
        )
    """)
    
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
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS name_trigrams (
            trigram TEXT NOT NULL,
            file_id INTEGER NOT NULL,
            FOREIGN KEY(file_id) REFERENCES files(rowid)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trigram ON name_trigrams(trigram)")
    
    # Feature 4.2 table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embedding_hashes (
            path TEXT PRIMARY KEY,
            hash TEXT NOT NULL
        )
    """)
    
    # Feature 5.3 table: Duplicate detection
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_hashes (
            path TEXT PRIMARY KEY,
            hash TEXT NOT NULL,
            size INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_hashes ON file_hashes(hash)")
    
    # Feature 5.2 table: Auto-tagging
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_tags (
            path TEXT PRIMARY KEY,
            tags TEXT NOT NULL
        )
    """)
    
    # Feature 1.1 table: Code symbols
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS code_symbols USING fts5(
            symbol, path, type,
            tokenize='unicode61 separators "_-."'
        )
    """)
    
    conn.commit()
