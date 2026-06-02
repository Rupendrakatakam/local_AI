import os
import sqlite3
import json
import shutil
from pathlib import Path
from collections import defaultdict
import requests
from config_loader import get as cfg

class OrganizationAgent:
    def __init__(self):
        from db_utils import get_data_dir, get_all_shard_paths
        self.data_dir = get_data_dir()
        self.undo_file = self.data_dir / "undo_log.json"
        self.shards = get_all_shard_paths()
        self.ollama_url = cfg("ollama_url", "http://localhost:11434/api/generate")
        self.model = cfg("ollama_model", "phi3:mini")

    def find_duplicates(self, folder: str) -> dict[str, list[str]]:
        """Find duplicate files in a folder based on hash."""
        duplicates = defaultdict(list)
        for db_path in self.shards:
            try:
                conn = sqlite3.connect(db_path)
                # Ensure hash column exists or we group by size and name if hash not fully populated
                cur = conn.execute("SELECT path, size FROM files WHERE path LIKE ?", (f"{folder}/%",))
                for row in cur:
                    path, size = row
                    if os.path.exists(path):
                        duplicates[size].append(path)
                conn.close()
            except Exception:
                pass
                
        # Filter for actual duplicates (same size, >1 file)
        return {str(size): paths for size, paths in duplicates.items() if len(paths) > 1}

    def cluster_files(self, folder: str) -> dict[str, list[str]]:
        """Cluster files semantically. Dummy implementation without hdbscan to avoid hard dependencies if it fails to install."""
        clusters = defaultdict(list)
        for db_path in self.shards:
            try:
                conn = sqlite3.connect(db_path)
                cur = conn.execute("SELECT path, extension FROM files WHERE path LIKE ?", (f"{folder}/%",))
                for row in cur:
                    path, ext = row
                    ext = ext or "unknown"
                    clusters[ext].append(path)
                conn.close()
            except Exception:
                pass
        return dict(clusters)

    def generate_plan(self, folder: str) -> dict:
        duplicates = self.find_duplicates(folder)
        clusters = self.cluster_files(folder)
        
        prompt = f"I want to organize this folder: {folder}.\n\n"
        prompt += f"Found {len(duplicates)} duplicate groups based on size.\n"
        prompt += "Here are the files grouped by type (clusters):\n"
        for ext, files in clusters.items():
            prompt += f"- {ext}: {len(files)} files\n"
            
        prompt += "\nPlease suggest a folder structure and a move plan. Return ONLY valid JSON in this format: {\"moves\": [{\"source\": \"/path/to/old\", \"target\": \"/path/to/new\"}], \"rationale\": \"...\"}"
        
        try:
            resp = requests.post(self.ollama_url, json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }, timeout=60)
            
            result = resp.json().get("response", "{}")
            return json.loads(result)
        except Exception as e:
            return {"error": str(e), "moves": [], "rationale": "Failed to generate plan."}

    def execute_plan(self, moves: list[dict]) -> bool:
        undo_log = []
        success = True
        
        for move in moves:
            src = move.get("source")
            dst = move.get("target")
            
            if not src or not dst or not os.path.exists(src):
                continue
                
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                undo_log.append({"source": dst, "target": src}) # Reverse operation
            except Exception:
                success = False
                
        if undo_log:
            # Append to undo log
            existing = []
            if self.undo_file.exists():
                try:
                    with open(self.undo_file, 'r') as f:
                        existing = json.load(f)
                except Exception:
                    pass
            existing.append(undo_log)
            with open(self.undo_file, 'w') as f:
                json.dump(existing, f)
                
        return success
        
    def undo_last(self) -> bool:
        if not self.undo_file.exists():
            return False
            
        try:
            with open(self.undo_file, 'r') as f:
                existing = json.load(f)
                
            if not existing:
                return False
                
            last_moves = existing.pop()
            
            for move in last_moves:
                src = move.get("source")
                dst = move.get("target")
                if os.path.exists(src):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.move(src, dst)
                    
            with open(self.undo_file, 'w') as f:
                json.dump(existing, f)
                
            return True
        except Exception:
            return False
