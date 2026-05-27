"""
doctor.py — FileChat diagnostic tool.
Usage: python3 doctor.py [--repair]

Checks:
  1. Database exists and is readable
  2. DB integrity (PRAGMA integrity_check)
  3. FTS5 table in sync with files table
  4. Trigram table populated
  5. behavior.db exists and is readable
  6. LanceDB vectors directory exists
  7. Ollama is reachable
  8. All Python dependencies are importable
"""
import os
import sys
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".local" / "share" / "filefinder" / "index.db"
BEHAVIOR_DB = Path.home() / ".local" / "share" / "filefinder" / "behavior.db"
LANCEDB_PATH = Path.home() / ".local" / "share" / "filefinder" / "vectors"

passed = 0
failed = 0
warnings = 0

def ok(msg):
    global passed
    passed += 1
    print(f"  \033[92m✓\033[0m {msg}")

def fail(msg):
    global failed
    failed += 1
    print(f"  \033[91m✗\033[0m {msg}")

def warn(msg):
    global warnings
    warnings += 1
    print(f"  \033[93m⚠\033[0m {msg}")


def check_db_exists():
    if DB_PATH.exists():
        size_mb = DB_PATH.stat().st_size / (1024 * 1024)
        ok(f"Index database exists ({size_mb:.1f} MB)")
        return True
    else:
        fail(f"Index database not found at {DB_PATH}")
        return False

def check_db_integrity():
    try:
        conn = sqlite3.connect(DB_PATH)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        if result[0] == "ok":
            ok("Database integrity check passed")
        else:
            fail(f"Database corrupt: {result[0]}")
    except Exception as e:
        fail(f"Integrity check error: {e}")

def check_fts_sync():
    try:
        conn = sqlite3.connect(DB_PATH)
        files_count = conn.execute("SELECT count(*) FROM files").fetchone()[0]
        fts_count = conn.execute("SELECT count(*) FROM files_fts").fetchone()[0]
        conn.close()
        if fts_count == files_count:
            ok(f"FTS5 in sync ({fts_count:,} rows)")
        elif fts_count == 0:
            fail(f"FTS5 is empty! files has {files_count:,} rows. Run: /rebuild")
        else:
            warn(f"FTS5 mismatch: {fts_count:,} FTS vs {files_count:,} files")
    except Exception as e:
        fail(f"FTS check error: {e}")

def check_trigram_sync():
    try:
        conn = sqlite3.connect(DB_PATH)
        trig_count = conn.execute("SELECT count(DISTINCT file_id) FROM name_trigrams").fetchone()[0]
        files_count = conn.execute("SELECT count(*) FROM files").fetchone()[0]
        conn.close()
        if trig_count > 0:
            ok(f"Trigram table populated ({trig_count:,} unique files)")
        else:
            warn("Trigram table is empty. Run: /rebuild")
    except Exception as e:
        warn(f"Trigram check error: {e}")

def check_behavior_db():
    if BEHAVIOR_DB.exists():
        try:
            conn = sqlite3.connect(BEHAVIOR_DB)
            opens = conn.execute("SELECT count(*) FROM opens").fetchone()[0]
            copies = conn.execute("SELECT count(*) FROM copies").fetchone()[0]
            searches = conn.execute("SELECT count(*) FROM searches").fetchone()[0]
            conn.close()
            ok(f"Behavior DB: {opens} opens, {copies} copies, {searches} searches")
        except Exception as e:
            warn(f"Behavior DB error: {e}")
    else:
        warn("Behavior DB not found (will be created on first use)")

def check_lancedb():
    if LANCEDB_PATH.exists():
        ok(f"LanceDB vectors directory exists at {LANCEDB_PATH}")
    else:
        warn("LanceDB vectors directory not found (embeddings not started)")

def check_ollama():
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            ok(f"Ollama online — models: {', '.join(models[:5])}")
        else:
            warn(f"Ollama responded with status {resp.status_code}")
    except Exception:
        warn("Ollama not reachable at localhost:11434")

def check_dependencies():
    deps = {
        "watchdog": "File watching",
        "rich": "Terminal UI",
        "prompt_toolkit": "CLI input",
        "requests": "HTTP client",
        "sentence_transformers": "Text embeddings",
        "lancedb": "Vector database",
        "fitz": "PDF extraction (PyMuPDF)",
        "mammoth": "DOCX extraction",
        "flask": "Web GUI",
        "pystray": "System tray",
        "PIL": "Image processing (Pillow)",
    }
    for mod, label in deps.items():
        try:
            __import__(mod)
            ok(f"{label} ({mod})")
        except ImportError:
            warn(f"{label} ({mod}) — not installed")


def repair_fts():
    """Rebuild FTS5 and trigram tables."""
    print("\n\033[93mRepairing FTS5 + trigrams...\033[0m")
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM files_fts")
        conn.execute("INSERT INTO files_fts(rowid, name, path) SELECT rowid, name, path FROM files")
        conn.execute("DELETE FROM name_trigrams")
        
        sys.path.insert(0, str(Path(__file__).parent))
        from indexer import _generate_trigrams
        
        rows = conn.execute("SELECT rowid, name FROM files").fetchall()
        batch = []
        for rid, name in rows:
            for tg in _generate_trigrams(name):
                batch.append((tg, rid))
        conn.executemany("INSERT INTO name_trigrams (trigram, file_id) VALUES (?, ?)", batch)
        conn.commit()
        conn.close()
        ok(f"Rebuilt FTS5 + trigrams for {len(rows):,} files")
    except Exception as e:
        fail(f"Repair failed: {e}")


if __name__ == "__main__":
    print("\n\033[1m══════════════════════════════════════════\033[0m")
    print("\033[1m  FileChat Doctor\033[0m")
    print("\033[1m══════════════════════════════════════════\033[0m\n")
    
    print("\033[1m[Database]\033[0m")
    if check_db_exists():
        check_db_integrity()
        check_fts_sync()
        check_trigram_sync()
    
    print("\n\033[1m[Behavior & Vectors]\033[0m")
    check_behavior_db()
    check_lancedb()
    
    print("\n\033[1m[Services]\033[0m")
    check_ollama()
    
    print("\n\033[1m[Dependencies]\033[0m")
    check_dependencies()
    
    # Repair mode
    if "--repair" in sys.argv:
        repair_fts()
    
    print(f"\n\033[1mSummary:\033[0m {passed} passed, {failed} failed, {warnings} warnings")
    if failed > 0:
        print("\033[91mSome checks failed. Run with --repair to attempt fixes.\033[0m")
    else:
        print("\033[92mAll critical checks passed!\033[0m")
    print()
