import pytest
import sqlite3
import os
from unittest.mock import patch
import indexer

def test_upsert(temp_db):
    conn = sqlite3.connect(temp_db)
    
    # Mocking os.stat
    class MockStat:
        st_size = 100
        st_mtime = 12345.0
        
    with patch('os.stat', return_value=MockStat()), \
         patch('os.path.isdir', return_value=False), \
         patch('db_utils.get_shard_path', return_value=temp_db):
         
         indexer.upsert('/tmp/test_file.txt')
         
         cur = conn.execute("SELECT name, size FROM files WHERE path = '/tmp/test_file.txt'")
         row = cur.fetchone()
         assert row is not None
         assert row[0] == 'test_file.txt'
         assert row[1] == 100
         
    conn.close()
