"""
audit.py — Audit logging for FileChat.
Logs all file opens and searches for security and auditing purposes.
"""
import os
import datetime
from pathlib import Path

def get_audit_log_path() -> Path:
    return Path.home() / ".local" / "share" / "filefinder" / "audit.log"

def log_action(action: str, details: str):
    """
    Append an action to the audit log.
    action: e.g., 'SEARCH', 'OPEN', 'CONFIG'
    details: additional details about the action
    """
    log_file = get_audit_log_path()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.datetime.now().isoformat()
    log_entry = f"[{timestamp}] {action} - {details}\n"
    
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        # Fail silently to avoid breaking the main app
        print(f"Failed to write audit log: {e}")
