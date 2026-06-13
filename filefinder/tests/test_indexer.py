import pytest
import sqlite3
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
import stat

sys.path.insert(0, str(Path(__file__).parent.parent))

import indexer


class MockStat:
    def __init__(self, size=100, mtime=12345.0):
        self.st_size = size
        self.st_mtime = mtime
        self.st_mode = stat.S_IFREG | 0o644


def test_upsert(populated_db):
    """Test upsert function with mocked stat."""
    test_path = '/tmp/test_file.txt'
    
    with patch('os.stat', return_value=MockStat()), \
         patch('pathlib.Path.is_file', return_value=True), \
         patch('indexer.is_ignored', return_value=False), \
         patch('indexer.get_shard_path', return_value=Path(populated_db)):
        
        indexer.upsert(test_path, [])
        
        conn = sqlite3.connect(populated_db)
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT name, size, extension FROM files WHERE path = ?", (test_path,))
        row = cur.fetchone()
        conn.close()
        
        assert row is not None
        assert row['name'] == 'test_file.txt'
        assert row['size'] == 100
        assert row['extension'] == 'txt'


def test_upsert_skips_zero_byte(populated_db):
    """Test that zero-byte files are skipped."""
    test_path = '/tmp/empty.txt'
    
    with patch('os.stat', return_value=MockStat(size=0)), \
         patch('os.path.isfile', return_value=True), \
         patch('indexer.get_shard_path', return_value=Path(populated_db)):
        
        indexer.upsert(test_path, [])
        
        conn = sqlite3.connect(populated_db)
        cur = conn.execute("SELECT COUNT(*) FROM files WHERE path = ?", (test_path,))
        count = cur.fetchone()[0]
        conn.close()
        
        assert count == 0


def test_upsert_skips_large_file(populated_db):
    """Test that files exceeding MAX_FILE_SIZE are skipped."""
    test_path = '/tmp/huge_file.dat'
    
    with patch('os.stat', return_value=MockStat(size=600 * 1024 * 1024)), \
         patch('os.path.isfile', return_value=True), \
         patch('indexer.get_shard_path', return_value=Path(populated_db)):
        
        indexer.upsert(test_path, [])
        
        conn = sqlite3.connect(populated_db)
        cur = conn.execute("SELECT COUNT(*) FROM files WHERE path = ?", (test_path,))
        count = cur.fetchone()[0]
        conn.close()
        
        assert count == 0


def test_upsert_respects_ignore_patterns(populated_db):
    """Test that ignore patterns are respected."""
    test_path = '/tmp/ignored.tmp'
    
    with patch('os.stat', return_value=MockStat()), \
         patch('os.path.isfile', return_value=True), \
         patch('indexer.get_shard_path', return_value=Path(populated_db)), \
         patch('indexer.is_ignored', return_value=True):
        
        indexer.upsert(test_path, ['*.tmp'])
        
        conn = sqlite3.connect(populated_db)
        cur = conn.execute("SELECT COUNT(*) FROM files WHERE path = ?", (test_path,))
        count = cur.fetchone()[0]
        conn.close()
        
        assert count == 0


def test_delete(populated_db):
    """Test delete function."""
    test_path = '/home/user/docs/report.pdf'
    
    with patch('indexer.get_shard_path', return_value=Path(populated_db)):
        indexer.delete(test_path)
        
        conn = sqlite3.connect(populated_db)
        cur = conn.execute("SELECT COUNT(*) FROM files WHERE path = ?", (test_path,))
        count = cur.fetchone()[0]
        conn.close()
        
        assert count == 0