import pytest
import sqlite3
from unittest.mock import patch
import search

def test_fts_search(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.execute("INSERT INTO files (path, name, size, is_dir, extension) VALUES ('/tmp/hello_world.py', 'hello_world.py', 10, 0, 'py')")
    conn.execute("INSERT INTO fts_files (rowid, path, name) VALUES (last_insert_rowid(), '/tmp/hello_world.py', 'hello_world.py')")
    conn.commit()
    conn.close()

    with patch('search.get_all_shard_paths', return_value=[temp_db]):
        res, fuzzy = search.search('hello')
        assert len(res) == 1
        assert res[0].name == 'hello_world.py'
