"""
config_loader.py — Central configuration for FileChat.
Loads config.json once, provides defaults for every setting.
All modules import from here instead of hardcoding values.
"""
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

_config: dict | None = None

DEFAULTS = {
    "watch_path": "~",
    "db_path": "~/.local/share/filefinder/index.db",
    "ollama_url": "http://localhost:11434/api/generate",
    "ollama_model": "phi3:mini",
    "embedding_model": "all-mpnet-base-v2",
    "image_model": "openai/clip-vit-base-patch32",
    "chunk_size": 400,
    "chunk_overlap": 80,
    "batch_size": 32,
    "max_file_size_mb": 500,
    "memory_cap_mb": 512,
    "cache_ttl_seconds": 30,
    "gui_port": 5000,
    "vacuum_every": 5000,
    "wal_checkpoint_interval": 300,
    "debounce_sec": 0.5,
    "cpu_load_cap": 2.0,
    "ollama_rate_limit_ms": 100,
    "ollama_max_concurrent": 3,
    "lru_cache_maxsize": 256,
    "trigram_threshold": 0.45,
    "fuzzy_score_cutoff": 65,
}


def load_config() -> dict:
    """Load config.json, merged with defaults. Cached after first call."""
    global _config
    if _config is not None:
        return _config

    config = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH) as f:
            user_config = json.load(f)
        config.update(user_config)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    _config = config
    return _config


def get(key: str, default=None):
    """Get a single config value by key."""
    return load_config().get(key, default)


def reload():
    """Force re-read of config.json (useful after edits)."""
    global _config
    _config = None
    return load_config()
