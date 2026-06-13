import pytest
import sqlite3
import os
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from db_utils import init_shard, BASE_DIR


@pytest.fixture
def temp_db():
    """Create a temporary database with the correct schema using init_shard."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    
    conn = sqlite3.connect(path)
    init_shard(conn)
    conn.close()
    
    yield path
    
    os.remove(path)


@pytest.fixture
def populated_db(temp_db):
    """Create a temp DB with some test data."""
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    
    # Insert test files
    test_files = [
        ("/home/user/docs/report.pdf", "report.pdf", "pdf", 1024, 1700000000.0),
        ("/home/user/code/main.py", "main.py", "py", 2048, 1700000100.0),
        ("/home/user/images/photo.jpg", "photo.jpg", "jpg", 512000, 1700000200.0),
        ("/home/user/.hidden_file", ".hidden_file", "", 100, 1700000300.0),
        ("/home/user/data.csv", "data.csv", "csv", 4096, 1700000400.0),
    ]
    
    for path, name, ext, size, mtime in test_files:
        conn.execute(
            "INSERT INTO files (path, name, extension, size, mtime) VALUES (?, ?, ?, ?, ?)",
            (path, name, ext, size, mtime)
        )
    
    conn.commit()
    conn.close()
    
    yield temp_db


@pytest.fixture(autouse=True)
def reset_search_state():
    """Reset search module global state before each test."""
    import search
    # Ensure hidden files toggle is OFF by default
    if search._show_hidden:
        search.toggle_hidden()
    yield
    # Clean up after test
    if search._show_hidden:
        search.toggle_hidden()