"""
audit.py — Audit logging for FileChat.
Logs all file opens and searches for security and auditing purposes.
"""
import os
import logging
import logging.handlers
import datetime
from pathlib import Path

_audit_logger = None
_audit_logger_lock = __import__('threading').Lock()

def _get_audit_logger() -> logging.Logger:
    global _audit_logger
    if _audit_logger is not None:
        return _audit_logger
    with _audit_logger_lock:
        if _audit_logger is not None:
            return _audit_logger
        log_file = Path.home() / ".local" / "share" / "filefinder" / "audit.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s"))
        _audit_logger = logging.getLogger("filefinder.audit")
        _audit_logger.setLevel(logging.INFO)
        _audit_logger.addHandler(handler)
        _audit_logger.propagate = False
        return _audit_logger

def log_action(action: str, details: str):
    _get_audit_logger().info(f"{action} - {details}")
