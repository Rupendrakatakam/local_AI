import sqlite3
import datetime
import os
import requests
from config_loader import get as cfg

def parse_local_calendar():
    """Dummy implementation for parsing .ics files."""
    return []

def match_events_to_files(events, recent_files):
    """Dummy matching."""
    return recent_files

def generate_morning_briefing():
    try:
        from db_utils import get_data_dir
        from behavior import get_behavior_db
        db_path = get_data_dir() / "behavior.db"
        
        conn = get_behavior_db()
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=7)).timestamp()
        cur = conn.execute("SELECT path, count(*) as c FROM opens WHERE timestamp > ? GROUP BY path ORDER BY c DESC LIMIT 10", (cutoff,))
        recent_files = [row[0] for row in cur.fetchall()]
        conn.close()
        
        events = parse_local_calendar()
        relevant_files = match_events_to_files(events, recent_files)
        
        prompt = "Generate a short, encouraging morning briefing for me. Based on my recent files below, suggest 3 things I might want to pick up today.\n\nFiles:\n"
        for f in relevant_files[:5]:
            prompt += f"- {os.path.basename(f)} ({f})\n"
            
        ollama_url = cfg("ollama_url", "http://localhost:11434/api/generate")
        model = cfg("ollama_model", "phi3:mini")
        
        resp = requests.post(ollama_url, json={
            "model": model,
            "prompt": prompt,
            "stream": False
        }, timeout=30)
        
        return resp.json().get("response", "Have a great day!")
    except Exception as e:
        return f"Could not generate briefing: {e}"
