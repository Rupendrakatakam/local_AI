"""
doctor.py — FileChat diagnostic tool.
Usage: python3 doctor.py [--repair]

Checks:
  1. Database shards exist and are readable
  2. DB integrity (PRAGMA integrity_check) per shard
  3. FTS5 table in sync with files table per shard
  4. Trigram table populated per shard
  5. behavior.db exists and is readable
  6. LanceDB vectors directory exists
  7. Ollama is reachable
  8. All Python dependencies are importable
"""
import os
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db_utils import get_all_shard_paths

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


def check_shards():
    shards = get_all_shard_paths()
    if not shards:
        fail("No database shards found")
        return False
    ok(f"Found {len(shards)} database shard(s)")
    total_size_mb = sum(p.stat().st_size for p in shards if p.exists()) / (1024 * 1024)
    ok(f"Total database size: {total_size_mb:.1f} MB")
    return True

def check_shard_integrity():
    shards = get_all_shard_paths()
    for shard in shards:
        try:
            conn = sqlite3.connect(shard)
            result = conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()
            if result[0] == "ok":
                ok(f"{shard.name}: integrity OK")
            else:
                fail(f"{shard.name}: CORRUPT — {result[0]}")
        except Exception as e:
            fail(f"{shard.name}: integrity check error — {e}")

def check_fts_sync():
    shards = get_all_shard_paths()
    total_files = 0
    total_fts = 0
    for shard in shards:
        try:
            conn = sqlite3.connect(shard)
            files_count = conn.execute("SELECT count(*) FROM files").fetchone()[0]
            fts_count = conn.execute("SELECT count(*) FROM files_fts").fetchone()[0]
            conn.close()
            total_files += files_count
            total_fts += fts_count
            if fts_count == 0 and files_count > 0:
                warn(f"{shard.name}: FTS5 empty ({files_count:,} files). Run: /rebuild")
            elif abs(fts_count - files_count) > 10:
                warn(f"{shard.name}: FTS5 mismatch ({fts_count:,} FTS vs {files_count:,} files)")
        except Exception as e:
            warn(f"{shard.name}: FTS check error — {e}")
    
    if total_fts == total_files:
        ok(f"FTS5 in sync across all shards ({total_fts:,} rows)")
    elif total_fts > 0:
        warn(f"FTS5 partial sync: {total_fts:,} FTS vs {total_files:,} files total")
    else:
        fail(f"FTS5 is empty! {total_files:,} files total. Run: /rebuild")

def check_trigram_sync():
    shards = get_all_shard_paths()
    total_trig = 0
    for shard in shards:
        try:
            conn = sqlite3.connect(shard)
            trig_count = conn.execute("SELECT count(DISTINCT file_id) FROM name_trigrams").fetchone()[0]
            conn.close()
            total_trig += trig_count
        except Exception:
            pass
    
    if total_trig > 0:
        ok(f"Trigram table populated ({total_trig:,} unique files)")
    else:
        warn("Trigram table is empty across all shards. Run: /rebuild")

def check_content_fts():
    shards = get_all_shard_paths()
    total_content = 0
    for shard in shards:
        try:
            conn = sqlite3.connect(shard)
            count = conn.execute("SELECT count(*) FROM file_content_fts").fetchone()[0]
            conn.close()
            total_content += count
        except Exception:
            pass
    
    if total_content > 0:
        ok(f"Content FTS populated ({total_content:,} documents)")
    else:
        warn("Content FTS is empty (embedder may not have processed documents yet)")

def check_tags():
    shards = get_all_shard_paths()
    total_tags = 0
    for shard in shards:
        try:
            conn = sqlite3.connect(shard)
            count = conn.execute("SELECT count(*) FROM file_tags").fetchone()[0]
            conn.close()
            total_tags += count
        except Exception:
            pass
    
    if total_tags > 0:
        ok(f"Auto-tags: {total_tags:,} files tagged")
    else:
        warn("No files auto-tagged yet (embedder needs to process documents)")

def check_hashes():
    shards = get_all_shard_paths()
    total_hashes = 0
    for shard in shards:
        try:
            conn = sqlite3.connect(shard)
            count = conn.execute("SELECT count(*) FROM file_hashes").fetchone()[0]
            conn.close()
            total_hashes += count
        except Exception:
            pass
    
    if total_hashes > 0:
        ok(f"Duplicate hashes: {total_hashes:,} files hashed")
    else:
        warn("No file hashes computed yet")

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
        "rapidfuzz": "Fuzzy search",
        "pynput": "Keyboard shortcuts (Global Hotkey)",
    }
    for mod, label in deps.items():
        try:
            __import__(mod)
            ok(f"{label} ({mod})")
        except ImportError:
            warn(f"{label} ({mod}) — not installed")


def repair_fts():
    """Rebuild FTS5 and trigram tables across all shards."""
    print("\n\033[93mRepairing FTS5 + trigrams across all shards...\033[0m")
    shards = get_all_shard_paths()
    total_files = 0
    
    from indexer import _generate_trigrams
    
    for shard in shards:
        try:
            conn = sqlite3.connect(shard)
            conn.execute("DELETE FROM files_fts")
            conn.execute("INSERT INTO files_fts(rowid, name, path) SELECT rowid, name, path FROM files")
            conn.execute("DELETE FROM name_trigrams")
            
            rows = conn.execute("SELECT rowid, name FROM files").fetchall()
            batch = []
            for rid, name in rows:
                for tg in _generate_trigrams(name):
                    batch.append((tg, rid))
            conn.executemany("INSERT INTO name_trigrams (trigram, file_id) VALUES (?, ?)", batch)
            conn.commit()
            conn.close()
            total_files += len(rows)
            ok(f"Rebuilt {shard.name}: {len(rows):,} files")
        except Exception as e:
            fail(f"Repair failed for {shard.name}: {e}")
    
    ok(f"Total: {total_files:,} files across {len(shards)} shards")


if __name__ == "__main__":
    print("\n\033[1m══════════════════════════════════════════\033[0m")
    print("\033[1m  FileChat Doctor\033[0m")
    print("\033[1m══════════════════════════════════════════\033[0m\n")
    
    print("\033[1m[Database Shards]\033[0m")
    if check_shards():
        check_shard_integrity()
        check_fts_sync()
        check_trigram_sync()
    
    print("\n\033[1m[Content & Features]\033[0m")
    check_content_fts()
    check_tags()
    check_hashes()
    
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
