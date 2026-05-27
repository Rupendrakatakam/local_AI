"""
aliases.py — Auto-alias system for FileChat.
Allows users to set shortcuts like '/alias set resume ~/Resume.pdf'.
"""
import json
from pathlib import Path

ALIAS_FILE = Path.home() / ".config" / "filefinder" / "aliases.json"

def _load_aliases() -> dict[str, str]:
    if not ALIAS_FILE.exists():
        return {}
    try:
        with open(ALIAS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_aliases(aliases: dict[str, str]) -> None:
    ALIAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ALIAS_FILE, "w") as f:
        json.dump(aliases, f, indent=2)

def set_alias(name: str, path: str) -> None:
    """Create or update an alias."""
    aliases = _load_aliases()
    aliases[name.lower()] = str(Path(path).expanduser().resolve())
    _save_aliases(aliases)

def get_alias(name: str) -> str | None:
    """Get the path for an alias."""
    aliases = _load_aliases()
    return aliases.get(name.lower())

def remove_alias(name: str) -> bool:
    """Remove an alias. Returns True if removed, False if not found."""
    aliases = _load_aliases()
    name_low = name.lower()
    if name_low in aliases:
        del aliases[name_low]
        _save_aliases(aliases)
        return True
    return False

def list_aliases() -> dict[str, str]:
    """Return all aliases."""
    return _load_aliases()
