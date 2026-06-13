import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import search


class TestSearch:
    """Test search module functions."""
    
    def test_normalize_keywords(self):
        """Test keyword normalization."""
        keywords = ["my_file.py", "hello-world", "test.case"]
        result = search._normalize_keywords(keywords)
        
        # Should split on separators but preserve filenames with dots
        assert "my_file.py" in result  # preserved as filename
        assert "hello" in result
        assert "world" in result
        assert "test.case" in result  # preserved as filename (has dot, no space)
    
    def test_normalize_keywords_preserves_filenames(self):
        """Test that filenames with dots are preserved."""
        keywords = ["my_script.py", "config.json"]
        result = search._normalize_keywords(keywords)
        
        assert "my_script.py" in result
        assert "config.json" in result
    
    def test_normalize_for_fuzzy(self):
        """Test fuzzy normalization."""
        assert search._normalize_for_fuzzy("my_file.txt") == "my file txt"
        assert search._normalize_for_fuzzy("hello-world") == "hello world"
        # SimpleName is not split by default (no separators)
        assert search._normalize_for_fuzzy("SimpleName") == "simplename"
    
    def test_extract_type_filter(self):
        """Test type: filter extraction."""
        extensions, cleaned = search._extract_type_filter("type:image rupendra")
        assert extensions == search.CATEGORY_MAP["image"]
        assert "rupendra" in cleaned
        
        extensions, cleaned = search._extract_type_filter("find type:video")
        assert extensions == search.CATEGORY_MAP["video"]
    
    def test_extract_content_filter(self):
        """Test content: filter extraction."""
        content, cleaned = search._extract_content_filter('content:"hello world" test')
        assert content == "hello world"
        assert cleaned == "test"
    
    def test_extract_tag_filter(self):
        """Test tag: filter extraction."""
        tag, cleaned = search._extract_tag_filter('tag:finance report')
        assert tag == "finance"
        assert cleaned == "report"
    
    def test_extract_code_filter(self):
        """Test code: filter extraction."""
        code, cleaned = search._extract_code_filter('code:my_function test')
        assert code == "my_function"
        assert cleaned == "test"
    
    def test_detect_category(self):
        """Test natural language category detection."""
        extensions, remaining = search._detect_category(["find", "image", "named", "photo"])
        assert extensions == search.CATEGORY_MAP["image"]
        assert "image" not in remaining
    
    def test_get_synonyms(self):
        """Test synonym expansion."""
        syns = search._get_synonyms("photo")
        assert "image" in syns
        assert "picture" in syns
        assert "img" in syns
    
    def test_looks_like_filename(self):
        """Test filename detection."""
        assert search._looks_like_filename("file.txt") is True
        assert search._looks_like_filename("document.pdf") is True
        assert search._looks_like_filename("my script.py") is False
        assert search._looks_like_filename("noextension") is False
    
    def test_strip_command_prefix(self):
        """Test command prefix stripping."""
        assert search._strip_command_prefix("find my file") == "my file"
        assert search._strip_command_prefix("search for document.pdf") == "document.pdf"
        assert search._strip_command_prefix("where is my resume") == "resume"
        assert search._strip_command_prefix("just a query") == "just a query"
    
    def test_score_result(self):
        """Test relevance scoring."""
        result = search.FileResult(
            path="/home/user/report.pdf",
            name="report.pdf",
            extension="pdf",
            size=1024,
            mtime=time.time()
        )
        
        score = search._score_result(["report"], result, None, 0.0)
        assert score > 0
        
        # Exact name match should get high score
        result2 = search.FileResult(
            path="/home/user/report.pdf",
            name="report.pdf",
            extension="pdf",
            size=1024,
            mtime=time.time()
        )
        score2 = search._score_result(["report.pdf"], result2, None, 0.0)
        assert score2 > 80  # Should get exact match bonus
    
    def test_rerank(self):
        """Test result reranking."""
        import time
        results = [
            search.FileResult("/a.txt", "a.txt", "txt", 100, time.time()),
            search.FileResult("/b.txt", "b.txt", "txt", 100, time.time()),
        ]
        
        ranked = search._rerank(["a"], results)
        assert ranked[0].name == "a.txt"
        assert ranked[0].score > ranked[1].score


class TestSearchIntegration:
    """Integration tests for search cascading."""
    
    def test_quick_search(self, populated_db):
        """Test quick_search function."""
        with patch('search.get_all_shard_paths', return_value=[Path(populated_db)]):
            results = search.quick_search("report", limit=10)
            assert isinstance(results, list)
    
    def test_search_returns_tuple(self, populated_db):
        """Test search returns (results, is_fuzzy) tuple."""
        with patch('search.get_all_shard_paths', return_value=[Path(populated_db)]):
            result = search.search("test", limit=10)
            assert isinstance(result, tuple)
            assert len(result) == 2
            assert isinstance(result[0], list)
            assert isinstance(result[1], bool)
    
    def test_search_empty_query(self, populated_db):
        """Test search with empty query."""
        with patch('search.get_all_shard_paths', return_value=[Path(populated_db)]):
            results, fuzzy = search.search("", limit=10)
            assert results == []
            assert fuzzy is False


import time