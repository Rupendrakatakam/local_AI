import pytest
import sqlite3
import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db_utils import (
    get_shard_path, 
    get_all_shard_paths, 
    init_shard, 
    BASE_DIR,
    get_watch_path,
    get_data_dir
)


class TestDBUtils:
    """Test db_utils module."""
    
    def test_get_data_dir(self):
        """Test get_data_dir returns BASE_DIR."""
        assert get_data_dir() == BASE_DIR
    
    def test_get_watch_path(self):
        """Test get_watch_path expands home."""
        path = get_watch_path()
        assert isinstance(path, Path)
        assert path.is_absolute()
    
    def test_get_shard_path_root(self):
        """Test files in watch_path root go to index_root.db."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)
            # Need to mock config
            from config_loader import get as cfg_get
            import config_loader
            config_loader._config = {"watch_path": str(tmpdir)}
            
            # Get shard path for a file in the watch root
            test_file = watch_path / "file.txt"
            shard = get_shard_path(str(test_file))
            assert shard.name == "index_root.db"
            assert shard.parent == BASE_DIR
    
    def test_get_shard_path_subdirectory(self):
        """Test files in subdirectories get sharded by top-level dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)
            from config_loader import get as cfg_get
            import config_loader
            config_loader._config = {"watch_path": str(tmpdir)}
            
            # Get shard path for a file in a subdirectory
            test_file = watch_path / "Documents" / "file.txt"
            shard = get_shard_path(str(test_file))
            assert shard.name == "index_Documents.db"
            assert shard.parent == BASE_DIR
    
    def test_get_shard_path_outside_watch(self):
        """Test files outside watch_path fall back to index_root.db."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)
            import config_loader
            config_loader._config = {"watch_path": str(tmpdir)}
            
            # File outside watch_path
            outside_path = Path("/tmp/outside.txt")
            shard = get_shard_path(str(outside_path))
            assert shard.name == "index_root.db"
    
    def test_init_shard_creates_all_tables(self):
        """Test init_shard creates all required tables."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            conn = sqlite3.connect(db_path)
            init_shard(conn)
            
            # Check all tables exist
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {t[0] for t in tables}
            
            expected_tables = {
                'files', 'files_fts', 'file_content_fts', 
                'name_trigrams', 'embedding_hashes', 
                'file_hashes', 'file_tags', 'code_symbols'
            }
            
            for expected in expected_tables:
                assert expected in table_names, f"Missing table: {expected}"
            
            # Check indexes exist
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
            index_names = {i[0] for i in indexes}
            
            assert 'idx_name' in index_names
            assert 'idx_ext' in index_names
            assert 'idx_trigram' in index_names
            assert 'idx_file_hashes' in index_names
            
            conn.close()
        finally:
            os.unlink(db_path)
    
    def test_init_shard_creates_triggers(self):
        """Test FTS5 triggers are created."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            conn = sqlite3.connect(db_path)
            init_shard(conn)
            
            triggers = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
            trigger_names = {t[0] for t in triggers}
            
            assert 'files_ai' in trigger_names
            assert 'files_ad' in trigger_names
            assert 'files_au' in trigger_names
            
            conn.close()
        finally:
            os.unlink(db_path)
    
    def test_get_all_shard_paths(self):
        """Test get_all_shard_paths returns existing shards."""
        # This depends on actual database state, just verify it runs
        shards = get_all_shard_paths()
        assert isinstance(shards, list)
        for shard in shards:
            assert isinstance(shard, Path)
            assert shard.suffix == '.db'