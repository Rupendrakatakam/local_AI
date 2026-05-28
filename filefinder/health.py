"""
health.py — Index health reporter for FileChat.
Generates statistics on DB size, FTS rows, and behavioral tracking.
Now supports multi-index architecture (iterates all shards).
"""
import os
import sqlite3
from pathlib import Path
from db_utils import get_all_shard_paths
from behavior import BEHAVIOR_DB

def generate_health_report() -> dict:
    """Generate a health report dict with index statistics."""
    report = {
        "total_files": 0,
        "fts_count": 0,
        "behavior_opens": 0,
        "behavior_copies": 0,
        "behavior_searches": 0,
        "db_size_mb": 0.0,
        "shard_count": 0
    }
    
    # 1. Aggregate stats across all shards
    shards = get_all_shard_paths()
    report["shard_count"] = len(shards)
    
    for db_path in shards:
        try:
            conn = sqlite3.connect(db_path)
            report["total_files"] += conn.execute("SELECT count(*) FROM files").fetchone()[0]
            report["fts_count"] += conn.execute("SELECT count(*) FROM files_fts").fetchone()[0]
            conn.close()
            report["db_size_mb"] += os.path.getsize(db_path) / (1024 * 1024)
        except Exception:
            pass
    
    report["db_size_mb"] = round(report["db_size_mb"], 2)
        
    # 2. Behavior DB stats
    try:
        if BEHAVIOR_DB.exists():
            conn = sqlite3.connect(BEHAVIOR_DB)
            report["behavior_opens"] = conn.execute("SELECT count(*) FROM opens").fetchone()[0]
            report["behavior_copies"] = conn.execute("SELECT count(*) FROM copies").fetchone()[0]
            report["behavior_searches"] = conn.execute("SELECT count(*) FROM searches").fetchone()[0]
            conn.close()
    except Exception:
        pass
        
    return report

def print_health_report() -> None:
    """Pretty-print the health report to console."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        console = Console()
        report = generate_health_report()
        
        lines = [
            f"[cyan]Files in Index:[/cyan]   {report['total_files']:,}",
            f"[cyan]FTS5 Rows:[/cyan]        {report['fts_count']:,}",
            f"[cyan]Database Size:[/cyan]    {report['db_size_mb']} MB ({report['shard_count']} shards)",
            "",
            "[bold]Behavior Tracking[/bold]",
            f"[yellow]Files Opened:[/yellow]     {report['behavior_opens']:,}",
            f"[yellow]Paths Copied:[/yellow]     {report['behavior_copies']:,}",
            f"[yellow]Total Searches:[/yellow]   {report['behavior_searches']:,}"
        ]
        
        console.print(Panel("\n".join(lines), title="FileChat Health Report", border_style="green", width=55))
    except ImportError:
        print(generate_health_report())

if __name__ == "__main__":
    print_health_report()
