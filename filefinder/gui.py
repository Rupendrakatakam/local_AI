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
        
    return jsonify({"ok": True})

@app.route("/api/preview")
def api_preview():
    """Generates a preview for the right-hand panel (text, image, or PDF)."""
    path = request.args.get("path", "")
    if not path or not os.path.exists(path):
        return jsonify({"type": "error", "content": "File not found"}), 404
        
    ext = Path(path).suffix.lower()
    
    # Image preview: Return the file directly
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"):
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        return send_file(path, mimetype=mime)
        
    # Text preview: Return the first 2000 characters
    text_exts = {".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", 
                 ".yaml", ".yml", ".sh", ".rs", ".go", ".c", ".cpp", ".h", ".csv"}
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

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(cfg("gui_port", 5000)), debug=True)
