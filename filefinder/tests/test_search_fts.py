import pytest
import sqlite3
from unittest.mock import patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import search
import os


def test_fts_search(populated_db):
    """Test FTS5 search - requires FTS to be populated."""
    # First populate FTS for the test
    conn = sqlite3.connect(populated_db)
    conn.execute("INSERT INTO files_fts(rowid, name, path) SELECT rowid, name, path FROM files")
    conn.commit()
    conn.close()
    
    with patch('search.get_all_shard_paths', return_value=[Path(populated_db)]), \
         patch('search.os.path.exists', return_value=True):
        res, fuzzy = search.search('report', limit=10)
        assert len(res) >= 1
        assert any(r.name == 'report.pdf' for r in res)


def test_fts_search_partial_match(populated_db):
    """Test FTS5 partial match with prefix."""
    conn = sqlite3.connect(populated_db)
    conn.execute("INSERT INTO files_fts(rowid, name, path) SELECT rowid, name, path FROM files")
    conn.commit()
    conn.close()
    
    with patch('search.get_all_shard_paths', return_value=[Path(populated_db)]), \
         patch('search.os.path.exists', return_value=True):
        res, fuzzy = search.search('repor', limit=10)
        # FTS5 prefix matching
        assert len(res) >= 1


def test_fts_search_with_extension_filter(populated_db):
    """Test FTS5 search combined with type filter."""
    conn = sqlite3.connect(populated_db)
    conn.execute("INSERT INTO files_fts(rowid, name, path) SELECT rowid, name, path FROM files")
    conn.commit()
    conn.close()
    
    with patch('search.get_all_shard_paths', return_value=[Path(populated_db)]), \
         patch('search.os.path.exists', return_value=True):
        res, fuzzy = search.search('type:document', limit=10)
        assert len(res) == 1
        assert res[0].extension == 'pdf'


def test_fts_empty_query(populated_db):
    """Test FTS with empty query."""
    with patch('search.get_all_shard_paths', return_value=[Path(populated_db)]):
        res, fuzzy = search.search('', limit=10)
        assert res == []