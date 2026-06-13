import os
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

try:
    import duckdb
except ImportError:
    duckdb = None

try:
    import networkx as nx
except ImportError:
    nx = None

from db_utils import get_data_dir

@dataclass
class FileNode:
    path: str
    name: str
    extension: str
    size: int
    mtime: float

@dataclass
class PersonNode:
    name: str
    source_file: str

@dataclass
class ProjectNode:
    name: str
    directory_path: str

@dataclass
class TopicNode:
    name: str
    from_tags: bool

@dataclass
class DateNode:
    date: str
    extracted_from: str

class KnowledgeGraph:
    def __init__(self):
        self.data_dir = get_data_dir()
        self.db_path = str(self.data_dir / "knowledge.duckdb")
        if duckdb:
            self.conn = duckdb.connect(self.db_path)
            self._init_schema()
        else:
            self.conn = None

    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                source VARCHAR,
                target VARCHAR,
                edge_type VARCHAR,
                weight DOUBLE,
                created_at DOUBLE
            )
        """)

    def add_co_accessed_edge(self, file1: str, file2: str):
        if not self.conn: return
        self.conn.execute("INSERT INTO edges VALUES (?, ?, 'co_accessed', 1.0, ?)", 
                         (file1, file2, time.time()))

    def add_semantic_similar_edge(self, file1: str, file2: str, score: float):
        if not self.conn: return
        if score > 0.8:
            self.conn.execute("INSERT INTO edges VALUES (?, ?, 'semantic_similar', ?, ?)", 
                             (file1, file2, score, time.time()))

    def add_version_of_edge(self, file1: str, file2: str):
        if not self.conn: return
        self.conn.execute("INSERT INTO edges VALUES (?, ?, 'version_of', 1.0, ?)", 
                         (file1, file2, time.time()))

    def add_references_edge(self, file1: str, file2: str):
        if not self.conn: return
        self.conn.execute("INSERT INTO edges VALUES (?, ?, 'references', 1.0, ?)", 
                         (file1, file2, time.time()))

    def add_contains_entity_edge(self, file_path: str, entity: str):
        if not self.conn: return
        self.conn.execute("INSERT INTO edges VALUES (?, ?, 'contains_entity', 1.0, ?)", 
                         (file_path, f"entity:{entity}", time.time()))

    def build_graph(self):
        # Stub: normally reads behavior.db and lancedb to populate duckdb edges.
        pass

    def find_related(self, path: str, depth: int = 2) -> List[Dict[str, Any]]:
        if not self.conn: return []
        res = self.conn.execute("""
            WITH RECURSIVE bfs AS (
                SELECT target, edge_type, 1 AS depth, ARRAY[source] AS visited FROM edges WHERE source = ?
                UNION
                SELECT source, edge_type, 1 AS depth, ARRAY[target] AS visited FROM edges WHERE target = ?
                UNION
                SELECT e.target, e.edge_type, b.depth + 1, list_append(b.visited, e.source)
                FROM edges e JOIN bfs b ON e.source = b.target
                WHERE b.depth < ? AND NOT list_contains(b.visited, e.source)
                UNION
                SELECT e.source, e.edge_type, b.depth + 1, list_append(b.visited, e.target)
                FROM edges e JOIN bfs b ON e.target = b.source
                WHERE b.depth < ? AND NOT list_contains(b.visited, e.target)
            )
            SELECT DISTINCT target, edge_type, depth FROM bfs WHERE target != ? LIMIT 100
        """, (path, path, depth, depth, path)).fetchall()
        
        return [{"node": r[0], "edge_type": r[1], "depth": r[2]} for r in res]

    def find_by_topic(self, topic: str) -> List[str]:
        if not self.conn: return []
        res = self.conn.execute("SELECT DISTINCT source FROM edges WHERE target = ? AND edge_type = 'contains_entity'", (f"entity:{topic}",)).fetchall()
        return [r[0] for r in res]

    def find_co_accessed(self, path: str) -> List[str]:
        if not self.conn: return []
        res = self.conn.execute("SELECT DISTINCT target FROM edges WHERE source = ? AND edge_type = 'co_accessed'", (path,)).fetchall()
        return [r[0] for r in res]
        
    def get_project_files(self, project_name: str) -> List[str]:
        if not self.conn: return []
        # Dummy implementation
        return []
