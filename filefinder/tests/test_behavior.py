import pytest
import sqlite3
import time
import tempfile
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import behavior


@pytest.fixture
def behavior_db():
    """Create a temporary behavior database."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    # Mock the BEHAVIOR_DB path
    with patch('behavior.BEHAVIOR_DB', Path(db_path)):
        # Reset the singleton
        behavior._behavior_conn = None
        behavior._behavior_init_done = False
        
        yield db_path
        
        # Cleanup
        if behavior._behavior_conn:
            behavior._behavior_conn.close()
        behavior._behavior_conn = None
        behavior._behavior_init_done = False
        if os.path.exists(db_path):
            os.unlink(db_path)


class TestBehavior:
    """Test behavior module."""
    
    def test_record_open(self, behavior_db):
        """Test recording an open event."""
        with patch('behavior.BEHAVIOR_DB', Path(behavior_db)):
            behavior._behavior_conn = None
            behavior._behavior_init_done = False
            
            behavior.record_open("test query", "/home/user/file.txt")
            
            conn = sqlite3.connect(behavior_db)
            cur = conn.execute("SELECT * FROM opens WHERE path = ?", ("/home/user/file.txt",))
            row = cur.fetchone()
            conn.close()
            
            assert row is not None
            assert row[1] == "test query"  # query
            assert row[2] == "/home/user/file.txt"  # path
    
    def test_record_copy(self, behavior_db):
        """Test recording a copy event."""
        with patch('behavior.BEHAVIOR_DB', Path(behavior_db)):
            behavior._behavior_conn = None
            behavior._behavior_init_done = False
            
            behavior.record_copy("/home/user/file.txt")
            
            conn = sqlite3.connect(behavior_db)
            cur = conn.execute("SELECT * FROM copies WHERE path = ?", ("/home/user/file.txt",))
            row = cur.fetchone()
            conn.close()
            
            assert row is not None
            assert row[1] == "/home/user/file.txt"
    
    def test_record_search(self, behavior_db):
        """Test recording a search event."""
        with patch('behavior.BEHAVIOR_DB', Path(behavior_db)):
            behavior._behavior_conn = None
            behavior._behavior_init_done = False
            
            behavior.record_search("test query", 5)
            
            conn = sqlite3.connect(behavior_db)
            cur = conn.execute("SELECT * FROM searches WHERE query = ?", ("test query",))
            row = cur.fetchone()
            conn.close()
            
            assert row is not None
            assert row[1] == "test query"
            assert row[2] == 5
    
    def test_get_all_behavior_boosts_no_data(self, behavior_db):
        """Test boost calculation with no data returns 0."""
        with patch('behavior.BEHAVIOR_DB', Path(behavior_db)):
            behavior._behavior_conn = None
            behavior._behavior_init_done = False
            
            boost = behavior.get_all_behavior_boosts("/home/user/file.txt")
            assert boost == 0.0
    
    def test_get_all_behavior_boosts_with_opens(self, behavior_db):
        """Test boost calculation with open history."""
        with patch('behavior.BEHAVIOR_DB', Path(behavior_db)):
            behavior._behavior_conn = None
            behavior._behavior_init_done = False
            
            # Record some opens
            behavior.record_open("query1", "/home/user/file.txt")
            behavior.record_open("query2", "/home/user/file.txt")
            
            boost = behavior.get_all_behavior_boosts("/home/user/file.txt")
            assert boost > 0.0
    
    def test_get_all_behavior_boosts_with_copies(self, behavior_db):
        """Test boost calculation with copy history."""
        with patch('behavior.BEHAVIOR_DB', Path(behavior_db)):
            behavior._behavior_conn = None
            behavior._behavior_init_done = False
            
            # Record copies
            behavior.record_copy("/home/user/file.txt")
            behavior.record_copy("/home/user/file.txt")
            behavior.record_copy("/home/user/file.txt")
            
            boost = behavior.get_all_behavior_boosts("/home/user/file.txt")
            assert boost > 0.0
    
    def test_get_all_boosts_batch(self, behavior_db):
        """Test batch boost calculation."""
        with patch('behavior.BEHAVIOR_DB', Path(behavior_db)):
            behavior._behavior_conn = None
            behavior._behavior_init_done = False
            
            paths = ["/home/user/file1.txt", "/home/user/file2.txt"]
            behavior.record_open("query", paths[0])
            
            boosts = behavior.get_all_boosts_batch(paths)
            
            assert isinstance(boosts, dict)
            assert paths[0] in boosts
            assert paths[1] in boosts
            # Both paths get some boost due to workspace affinity
            assert boosts[paths[0]] >= 0.0
            assert boosts[paths[1]] >= 0.0
    
    def test_privacy_clear(self, behavior_db):
        """Test privacy_clear removes the database."""
        with patch('behavior.BEHAVIOR_DB', Path(behavior_db)):
            behavior._behavior_conn = None
            behavior._behavior_init_done = False
            
            behavior.record_open("query", "/home/user/file.txt")
            assert Path(behavior_db).exists()
            
            behavior.privacy_clear()
            assert not Path(behavior_db).exists()