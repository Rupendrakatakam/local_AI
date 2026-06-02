import json
import sqlite3
import datetime
from pathlib import Path
from collections import defaultdict
import requests
from config_loader import get as cfg

class FileIntelligenceAgent:
    def __init__(self):
        from db_utils import get_data_dir
        self.db_path = get_data_dir() / "behavior.db"
        self.ollama_url = cfg("ollama_url", "http://localhost:11434/api/generate")
        self.model = cfg("ollama_model", "phi3:mini")

    def parse_time_reference(self, text: str) -> tuple[float, float]:
        """Parses simple time references into unix timestamp ranges."""
        now = datetime.datetime.now()
        text = text.lower()
        
        if "yesterday" in text:
            start = (now - datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0)
            end = start.replace(hour=23, minute=59, second=59)
            return start.timestamp(), end.timestamp()
            
        if "this morning" in text:
            start = now.replace(hour=0, minute=0, second=0)
            end = now.replace(hour=12, minute=0, second=0)
            return start.timestamp(), end.timestamp()
            
        if "this week" in text:
            start = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
            end = now
            return start.timestamp(), end.timestamp()
            
        # Default: last 24 hours
        start = now - datetime.timedelta(days=1)
        return start.timestamp(), now.timestamp()

    def query_recent_activity(self, start_ts: float, end_ts: float) -> list[str]:
        try:
            conn = sqlite3.connect(str(self.db_path))
            cur = conn.execute(
                "SELECT path FROM opens WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp DESC", 
                (start_ts, end_ts)
            )
            paths = [row[0] for row in cur.fetchall()]
            conn.close()
            return list(dict.fromkeys(paths)) # return unique, preserving order
        except Exception:
            return []

    def group_by_project(self, paths: list[str]) -> dict[str, list[str]]:
        projects = defaultdict(list)
        for p in paths:
            parent = str(Path(p).parent)
            projects[parent].append(p)
        return dict(projects)
        
    def find_related_files(self, paths: list[str]) -> list[str]:
        # Semantic search placeholder: for now, return files in same dir
        related = set()
        from db_utils import get_all_shard_paths
        shards = get_all_shard_paths()
        
        parents = {str(Path(p).parent) for p in paths}
        for parent in parents:
            for db_path in shards:
                try:
                    conn = sqlite3.connect(db_path)
                    cur = conn.execute("SELECT path FROM files WHERE path LIKE ?", (f"{parent}/%",))
                    for row in cur:
                        if row[0] not in paths:
                            related.add(row[0])
                    conn.close()
                except Exception:
                    pass
        return list(related)[:10]

    def generate_summary(self, grouped_files: dict[str, list[str]]) -> str:
        if not grouped_files:
            return "You haven't opened any files in this timeframe."
            
        prompt = "Summarize my recent file activity based on these grouped files. Be concise and helpful.\n"
        for folder, files in grouped_files.items():
            prompt += f"\nFolder: {folder}\n"
            for f in files[:5]:
                prompt += f"- {Path(f).name}\n"
            if len(files) > 5:
                prompt += f"- and {len(files) - 5} more...\n"
                
        try:
            resp = requests.post(self.ollama_url, json={
                "model": self.model,
                "prompt": prompt,
                "stream": False
            }, timeout=30)
            return resp.json().get("response", "Could not generate summary.")
        except Exception as e:
            return f"Error generating summary: {e}"
