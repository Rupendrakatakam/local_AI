import pytest
import sqlite3
from unittest.mock import patch
import search

def test_exact_search(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.execute("INSERT INTO files (path, name, size, is_dir, extension) VALUES ('/tmp/test.txt', 'test.txt', 10, 0, 'txt')")
    conn.commit()
    conn.close()

    with patch('search.get_all_shard_paths', return_value=[temp_db]):
        res, fuzzy = search.search('test.txt')
        assert len(res) == 1
        assert res[0].name == 'test.txt'
        assert not fuzzy
