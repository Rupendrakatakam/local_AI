"""
suggestions.py — Query suggestion engine for FileChat.
Uses search history from behavior.db to suggest common queries.
"""
from behavior import get_behavior_db

def get_suggestions(prefix: str, limit: int = 5) -> list[str]:
    """
    Return recent queries matching prefix, ordered by frequency and recency.
    Reads from behavior.db searches table.
    """
    if not prefix or len(prefix.strip()) < 2:
        return []
        
    try:
        conn = get_behavior_db()
        # Group by query, order by count (frequency) and max timestamp (recency)
        cur = conn.execute(
            """
            SELECT query, COUNT(*) as freq, MAX(timestamp) as last_seen
            FROM searches
            WHERE query LIKE ?
            GROUP BY query
            ORDER BY freq DESC, last_seen DESC
            LIMIT ?
            """,
            (f"{prefix}%", limit)
        )
        suggestions = [row[0] for row in cur.fetchall()]
        conn.close()
        return suggestions
    except Exception:
        return []
