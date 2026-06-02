"""
gui.py — Flask web backend for FileChat GUI.
Serves the single-page search UI and provides REST API endpoints.
"""
import os
import subprocess
import mimetypes
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_file
from search import search, db_stats, FileResult
from config_loader import get as cfg

app = Flask(__name__, template_folder="templates", static_folder="static")

@app.route("/")
def index():
    """Serves the single-page application."""
    return render_template("index.html")

@app.route("/api/search")
def api_search():
    """REST endpoint for file search."""
    q = request.args.get("q", "").strip()
    limit = int(request.args.get("limit", 50))
    if not q:
        return jsonify({"results": [], "is_fuzzy": False})
        
    results, is_fuzzy = search(q, limit)
    return jsonify({
        "results": [
            {
                "path": r.path, 
                "name": r.name, 
                "extension": r.extension,
                "size": r.size, 
                "size_human": r.size_human, 
                "mtime": r.mtime
            }
            for r in results
        ],
        "is_fuzzy": is_fuzzy,
        "query": q,
    })

@app.route("/api/open", methods=["POST"])
def api_open():
    """Opens a file using the system's default application and records the behavior."""
    data = request.get_json() or {}
    path = data.get("path", "")
    query = data.get("query", "")
    
    if not path or not os.path.exists(path):
        return jsonify({"ok": False, "error": "File not found"}), 404
        
    # Open file asynchronously
    subprocess.Popen(["xdg-open", path])
    
    # Record behavior
    try:
        from behavior import record_open
        record_open(query, path)
    except ImportError:
        pass
        
    try:
        from audit import log_action
        log_action("OPEN_GUI", f"Path: {path}, Source Query: {query}")
    except Exception:
        pass
        
    return jsonify({"ok": True})

@app.route("/api/preview")
def api_preview():
    """Generates a preview for the right-hand panel (text, image, or PDF)."""
    path = request.args.get("path", "")
    if not path or not os.path.exists(path):
        return jsonify({"type": "error", "content": "File not found"}), 404
        
    # Security: prevent path traversal
    try:
        watch_path = Path(cfg("watch_path", "~")).expanduser().resolve()
        resolved = Path(path).resolve()
        resolved.relative_to(watch_path)
    except (ValueError, RuntimeError):
        return jsonify({"type": "error", "content": "Access denied"}), 403
        
    ext = Path(path).suffix.lower()
    
    # Media preview (image, video, audio): Return the file directly
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp",
               ".mp4", ".webm", ".mov", ".avi", ".mkv",
               ".mp3", ".wav", ".ogg", ".flac", ".m4a"):
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        return send_file(path, mimetype=mime)
        
    # Spreadsheet preview: Return first 50 rows as JSON table
    if ext == ".csv":
        try:
            import csv
            with open(path, newline='', encoding='utf-8', errors='replace') as f:
                reader = csv.reader(f)
                data = [row for i, row in enumerate(reader) if i < 50]
            return jsonify({"type": "table", "data": data, "extension": "csv"})
        except Exception as e:
            return jsonify({"type": "error", "content": f"Failed to read CSV: {e}"})
            
    if ext == ".xlsx":
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
            sheet = wb.active
            data = []
            for i, row in enumerate(sheet.iter_rows(values_only=True)):
                if i >= 50:
                    break
                data.append([str(c) if c is not None else "" for c in row])
            return jsonify({"type": "table", "data": data, "extension": "xlsx"})
        except ImportError:
            return jsonify({"type": "error", "content": "openpyxl not installed for XLSX previews (pip install openpyxl)."})
        except Exception as e:
            return jsonify({"type": "error", "content": f"Failed to read XLSX: {e}"})
        
    # Text preview: Return the first 2000 characters
    text_exts = {
        ".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", 
        ".yaml", ".yml", ".sh", ".rs", ".go", ".c", ".cpp", ".h", ".csv",
        ".java", ".rb", ".xml", ".sql", ".toml", ".ini", ".cfg", ".r", 
        ".swift", ".kt", ".php", ".bash", ".zsh", ".log", ".diff", ".patch", ".env"
    }
    if ext in text_exts or not ext:
        try:
            text = Path(path).read_text(errors="replace")[:2000]
            return jsonify({"type": "text", "content": text, "extension": ext.lstrip(".")})
        except Exception as e:
            return jsonify({"type": "error", "content": f"Could not read text: {e}"})
            
    # PDF preview: Return first page text
    if ext == ".pdf":
        try:
            import fitz
            doc = fitz.open(path)
            content = doc[0].get_text()[:1000] if len(doc) > 0 else "No text found on first page."
            return jsonify({
                "type": "pdf", 
                "pages": len(doc), 
                "content": content
            })
        except ImportError:
            return jsonify({"type": "error", "content": "PyMuPDF not installed for PDF previews."})
        except Exception as e:
            return jsonify({"type": "error", "content": f"Failed to read PDF: {e}"})
            
    return jsonify({"type": "unknown", "content": f"No preview available for {ext} files."})

@app.route("/api/analytics")
def api_analytics():
    """Returns search history analytics from behavior.db."""
    try:
        from behavior import get_behavior_db
        conn = get_behavior_db()
        
        # Top 5 queries
        cur = conn.execute("SELECT query, count(*) as c FROM searches GROUP BY query ORDER BY c DESC LIMIT 5")
        top_queries = [{"query": row[0], "count": row[1]} for row in cur.fetchall() if row[0]]
        
        # Top 5 opened files
        cur = conn.execute("SELECT path, count(*) as c FROM opens GROUP BY path ORDER BY c DESC LIMIT 5")
        top_files = [{"path": row[0], "count": row[1]} for row in cur.fetchall() if row[0]]
        
        # Hourly access distribution (local time)
        cur = conn.execute("SELECT strftime('%H', datetime(timestamp, 'unixepoch', 'localtime')), count(*) FROM opens GROUP BY 1")
        hourly = {f"{i:02d}": 0 for i in range(24)}
        for row in cur.fetchall():
            if row[0]:
                hourly[row[0]] = row[1]
                
        cur = conn.execute("SELECT strftime('%H', datetime(timestamp, 'unixepoch', 'localtime')), count(*) FROM searches GROUP BY 1")
        for row in cur.fetchall():
            if row[0]:
                hourly[row[0]] += row[1]
                
        conn.close()
        
        return jsonify({
            "top_queries": top_queries,
            "top_files": top_files,
            "hourly": [hourly[f"{i:02d}"] for i in range(24)]
        })
    except ImportError:
        return jsonify({"error": "behavior module not found"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stats")
def api_stats():
    """Returns overall health, database, and behavior stats for the dashboard."""
    s = db_stats()
    result = {"total": s.get("total", 0), "ready": s.get("ready", False)}
    
    # Add embedding progress if available
    try:
        from embedder import get_pipeline
        result["embeddings"] = get_pipeline().get_progress()
    except ImportError:
        result["embeddings"] = None
        
    # Add health report if available
    try:
        from health import generate_health_report
        result["health"] = generate_health_report()
    except ImportError:
        result["health"] = None
        
    return jsonify(result)

@app.route("/api/smart_folders")
def api_smart_folders():
    try:
        from config_loader import get as cfg
        import sqlite3
        import requests
        import json
        from collections import defaultdict
        from pathlib import Path
        from db_utils import get_all_shard_paths
        
        shards = get_all_shard_paths()
        if not shards:
            return jsonify({"error": "No database found"}), 404
            
        folders = defaultdict(lambda: {"count": 0, "size": 0, "exts": defaultdict(int)})
        
        for db_path in shards:
            try:
                conn = sqlite3.connect(db_path)
                cur = conn.execute("SELECT path, size, extension FROM files WHERE size > 0")
                for row in cur:
                    path, size, ext = row
                    parent = str(Path(path).parent)
                    folders[parent]["count"] += 1
                    folders[parent]["size"] += size
                    if ext:
                        folders[parent]["exts"][ext] += 1
                conn.close()
            except Exception:
                pass
        
        # Filter and sort folders by count
        valid_folders = {k: v for k, v in folders.items() if v["count"] > 5}
        top_folders = sorted(valid_folders.items(), key=lambda x: x[1]["count"], reverse=True)[:10]
        
        if not top_folders:
            return jsonify({"suggestion": "Your folders seem quite organized or don't have enough files to cluster yet!"})
            
        prompt = "I have the following folders with files scattered in them. Suggest a better organization strategy or folder structure to clean this up. Keep it concise, actionable, and format with markdown.\n\n"
        for folder, stats in top_folders:
            ext_summary = ", ".join(f"{count} {ext}" for ext, count in sorted(stats["exts"].items(), key=lambda x: x[1], reverse=True)[:3])
            prompt += f"Folder '{folder}': {stats['count']} files ({stats['size'] // (1024*1024)} MB). Main types: {ext_summary}\n"
            
        OLLAMA_URL = cfg("ollama_url", "http://localhost:11434/api/generate")
        MODEL = cfg("ollama_model", "phi3:mini")
        
        resp = requests.post(OLLAMA_URL, json={"model": MODEL, "prompt": prompt, "stream": False}, timeout=90)
        resp.raise_for_status()
        
        suggestion = resp.json().get("response", "").strip()
        import markdown
        html_suggestion = markdown.markdown(suggestion)
        return jsonify({"suggestion": html_suggestion})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/duplicates")
def api_duplicates():
    try:
        from db_utils import get_all_shard_paths
        import sqlite3
        from collections import defaultdict
        
        shards = get_all_shard_paths()
        hash_groups = defaultdict(list)
        
        for db_path in shards:
            try:
                conn = sqlite3.connect(db_path)
                cur = conn.execute("SELECT path, hash, size FROM file_hashes")
                for row in cur:
                    path, fhash, size = row
                    hash_groups[fhash].append({"path": path, "size": size})
                conn.close()
            except Exception:
                pass
                
        duplicates = []
        for fhash, files in hash_groups.items():
            if len(files) > 1:
                duplicates.append({
                    "hash": fhash,
                    "count": len(files),
                    "wasted_size": files[0]["size"] * (len(files) - 1),
                    "files": files
                })
                
        duplicates.sort(key=lambda x: x["wasted_size"], reverse=True)
        return jsonify({"duplicates": duplicates[:50]}) # Top 50 dupes
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/chat", methods=["POST"])
def api_chat():
    try:
        from behavior import get_behavior_db
        import requests
        import datetime
        
        user_message = request.json.get("message", "").strip()
        if not user_message:
            return jsonify({"error": "Empty message"}), 400
            
        # Get recent context
        conn = get_behavior_db()
        
        # Recent opens
        cur = conn.execute("SELECT path, timestamp FROM opens ORDER BY timestamp DESC LIMIT 10")
        recent_opens = []
        for p, ts in cur.fetchall():
            dt = datetime.datetime.fromtimestamp(ts).strftime("%A %I:%M %p")
            recent_opens.append(f"- Opened '{p}' at {dt}")
            
        # Recent searches
        cur = conn.execute("SELECT query, timestamp FROM searches ORDER BY timestamp DESC LIMIT 5")
        recent_searches = []
        for q, ts in cur.fetchall():
            dt = datetime.datetime.fromtimestamp(ts).strftime("%A %I:%M %p")
            recent_searches.append(f"- Searched '{q}' at {dt}")
            
        conn.close()
        
        context_lines = []
        if recent_opens:
            context_lines.append("Recent Files Opened:\n" + "\n".join(recent_opens))
        if recent_searches:
            context_lines.append("Recent Searches:\n" + "\n".join(recent_searches))
            
        context_str = "\n\n".join(context_lines) if context_lines else "No recent activity."
        
        prompt = f"""You are FileChat, a helpful personal file assistant running locally.
You have access to the user's recent file activity context below.
If the user asks about what they were doing, or what file they were working on, use the context to answer them.
If you suggest a specific file path to the user, ALWAYS wrap the exact path in backticks (e.g. `/home/user/doc.txt` or `C:\\Users\\file.pdf`) so the frontend can turn it into a clickable link.
Do not make up file paths that are not in the context. Keep your response conversational and concise.

Context:
{context_str}

User Message: {user_message}"""

        OLLAMA_URL = cfg("ollama_url", "http://localhost:11434/api/generate")
        MODEL = cfg("ollama_model", "phi3:mini")
        
        resp = requests.post(OLLAMA_URL, json={"model": MODEL, "prompt": prompt, "stream": False}, timeout=90)
        resp.raise_for_status()
        
        reply = resp.json().get("response", "").strip()
        
        import markdown
        # Custom markdown extension or simple regex to convert backticks to actionable links is handled in JS
        html_reply = markdown.markdown(reply)
        
        return jsonify({"reply": html_reply})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(cfg("gui_port", 5000)), debug=True)
