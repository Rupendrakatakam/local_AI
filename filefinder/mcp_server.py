#!/usr/bin/env python3
import sys
import json
import logging
import sqlite3
import datetime
import os
from search import search as do_search

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mcp_server")

MANIFEST = {
    "name": "FileFinder",
    "description": "Local search and file intelligence server for FileChat",
    "version": "1.0.0",
    "tools": [
        {
            "name": "search_files",
            "description": "Search for files locally using BM25 and fuzzy search",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "limit": {"type": "integer", "description": "Max results to return", "default": 20},
                    "type": {"type": "string", "description": "Optional file type filter (e.g. document, image, code)"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "get_file_content",
            "description": "Read the content of a local file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file"}
                },
                "required": ["path"]
            }
        },
        {
            "name": "get_file_metadata",
            "description": "Get metadata (size, mtime, extension) for a local file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file"}
                },
                "required": ["path"]
            }
        },
        {
            "name": "list_recent_files",
            "description": "List files recently opened or modified",
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "description": "Number of hours to look back", "default": 24}
                },
                "required": []
            }
        }
    ]
}

def tool_search_files(query, limit=20, file_type=None):
    if file_type:
        query = f"type:{file_type} {query}"
    res, fuzzy = do_search(query, limit=limit)
    return [{"path": r.path, "name": r.name, "score": r.score} for r in res]

def tool_get_file_content(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return {"content": f.read(10000)} # limit to 10k chars
    except Exception as e:
        return {"error": str(e)}

def tool_get_file_metadata(path):
    try:
        stat = os.stat(path)
        return {
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "is_dir": os.path.isdir(path),
            "path": path
        }
    except Exception as e:
        return {"error": str(e)}

def tool_list_recent_files(hours=24):
    try:
        from behavior import get_behavior_db
        conn = get_behavior_db()
        cutoff = (datetime.datetime.now() - datetime.timedelta(hours=hours)).timestamp()
        cur = conn.execute("SELECT path, timestamp FROM opens WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 50", (cutoff,))
        recent = [{"path": row[0], "timestamp": row[1]} for row in cur.fetchall()]
        conn.close()
        return recent
    except Exception as e:
        return {"error": str(e)}

def handle_request(req):
    if "method" not in req:
        return {"error": "Missing method"}
        
    method = req["method"]
    
    if method == "manifest":
        return MANIFEST
        
    if method == "call_tool":
        tool = req.get("tool")
        args = req.get("args", {})
        
        if tool == "search_files":
            return tool_search_files(args.get("query"), args.get("limit", 20), args.get("type"))
        elif tool == "get_file_content":
            return tool_get_file_content(args.get("path"))
        elif tool == "get_file_metadata":
            return tool_get_file_metadata(args.get("path"))
        elif tool == "list_recent_files":
            return tool_list_recent_files(args.get("hours", 24))
        else:
            return {"error": f"Unknown tool: {tool}"}
            
    return {"error": f"Unknown method: {method}"}

def run_stdio():
    logger.info("Starting MCP stdio server")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
            
        try:
            req = json.loads(line)
            res = handle_request(req)
            if "id" in req:
                print(json.dumps({"id": req["id"], "result": res}), flush=True)
            else:
                print(json.dumps(res), flush=True)
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON"}), flush=True)
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            print(json.dumps({"error": str(e)}), flush=True)

if __name__ == "__main__":
    run_stdio()
