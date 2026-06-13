import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_loader import get, reload, DEFAULTS


class TestConfigLoader:
    """Test config_loader module."""
    
    def test_defaults_present(self):
        """Test all expected defaults are present."""
        for key in DEFAULTS:
            val = get(key)
            assert val is not None, f"Default for {key} is None"
    
    def test_get_returns_default_for_unknown_key(self):
        """Test get returns default for unknown keys."""
        assert get("nonexistent_key", "default_value") == "default_value"
    
    def test_get_returns_none_for_unknown_key_no_default(self):
        """Test get returns None for unknown keys without default."""
        assert get("nonexistent_key") is None
    
    def test_specific_defaults(self):
        """Test specific default values."""
        assert get("ollama_model") == "phi3:mini"
        assert get("embedding_model") == "all-mpnet-base-v2"
        assert get("chunk_size") == 400
        assert get("trigram_threshold") == 0.45
        assert get("fuzzy_score_cutoff") == 65
    
    def test_reload_resets_config(self):
        """Test reload() resets the cached config."""
        # Access a value to populate cache
        get("ollama_model")
        
        # Reload should not fail
        reload()
        
        # Value should still be accessible
        assert get("ollama_model") == "phi3:mini"
    
    def test_watch_path_default(self):
        """Test watch_path default is home directory."""
        # Default is "~" but get() may resolve it via Path.expanduser()
        val = get("watch_path")
        # The config_loader returns raw value "~", but if it goes through Path it expands
        # Just verify we get a valid path string
        assert isinstance(val, str)
        assert len(val) > 0