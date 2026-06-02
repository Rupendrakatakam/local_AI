import pytest
import sqlite3
import os
import tempfile
from pathlib import Path

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    
    conn = sqlite3.connect(path)
    conn.execute('''
        CREATE TABLE files (
            path TEXT PRIMARY KEY,
            name TEXT,
            size INTEGER,
            mtime REAL,
            is_dir INTEGER,
            extension TEXT
        )
    ''')
    conn.execute('''
        CREATE VIRTUAL TABLE fts_files USING fts5(
            path,
            name,
            content='',
            tokenize='trigram'
        )
    ''')
    conn.close()
    
    yield path
    os.remove(path)
