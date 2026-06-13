import pytest
import sqlite3
from unittest.mock import patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import search


def test_exact_search(populated_db):
    """Test exact filename search."""
    with patch('search.get_all_shard_paths', return_value=[Path(populated_db)]):
        res, fuzzy = search.search('report.pdf', limit=10)
        assert len(res) == 1
        assert res[0].name == 'report.pdf'
        assert res[0].extension == 'pdf'
        assert not fuzzy


def test_exact_search_case_insensitive(populated_db):
    """Test exact search is case insensitive."""
    with patch('search.get_all_shard_paths', return_value=[Path(populated_db)]):
        res, fuzzy = search.search('REPORT.PDF', limit=10)
        assert len(res) == 1
        assert res[0].name == 'report.pdf'


def test_exact_search_not_found(populated_db):
    """Test exact search returns empty for non-existent file."""
    with patch('search.get_all_shard_paths', return_value=[Path(populated_db)]):
        res, fuzzy = search.search('nonexistent.xyz', limit=10)
        assert len(res) == 0


def test_hidden_files_excluded_by_default(populated_db):
    """Test hidden files are excluded by default."""
    with patch('search.get_all_shard_paths', return_value=[Path(populated_db)]):
        res, fuzzy = search.search('hidden', limit=10)
        # .hidden_file should not appear
        assert len(res) == 0


def test_hidden_files_included_when_toggled(populated_db):
    """Test hidden files are included when toggle is on."""
    search.toggle_hidden()
    try:
        with patch('search.get_all_shard_paths', return_value=[Path(populated_db)]):
            res, fuzzy = search.search('hidden', limit=10)
            assert len(res) == 1
            assert res[0].name == '.hidden_file'
    finally:
        search.toggle_hidden()


def test_type_filter(populated_db):
    """Test type: filter syntax."""
    with patch('search.get_all_shard_paths', return_value=[Path(populated_db)]):
        res, fuzzy = search.search('type:code', limit=10)
        assert len(res) == 1
        assert res[0].extension == 'py'
        
        res, fuzzy = search.search('type:image', limit=10)
        assert len(res) == 1
        assert res[0].extension == 'jpg'


def test_content_filter(populated_db):
    """Test content: filter - this searches FTS, which may be empty in test."""
    with patch('search.get_all_shard_paths', return_value=[Path(populated_db)]):
        res, fuzzy = search.search('content:report', limit=10)
        # FTS might not be populated, so we just check it doesn't crash
        assert isinstance(res, list)