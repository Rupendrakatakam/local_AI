import re
from enum import Enum

class QueryType(Enum):
    EXACT_FILENAME = "exact"      # "config.json"
    KEYWORD = "keyword"           # "tax report"
    DESCRIPTIVE = "descriptive"   # "document about ML" 
    TEMPORAL = "temporal"         # "file from yesterday"

def classify_query(query: str) -> QueryType:
    """Classifies a query to determine the best search strategy."""
    q = query.strip()
    
    # 1. Exact Filename
    # No spaces and has an extension
    if ' ' not in q and '.' in q:
        parts = q.rsplit('.', 1)
        if len(parts) == 2 and 1 <= len(parts[1]) <= 10:
            return QueryType.EXACT_FILENAME
            
    # 2. Temporal
    temporal_signals = ["yesterday", "last week", "today", "this morning", "recently"]
    if any(signal in q.lower() for signal in temporal_signals):
        return QueryType.TEMPORAL
        
    # 3. Descriptive
    words = q.split()
    filler = {"find", "search", "locate", "show", "me", "my", "the", "a", "an",
              "where", "is", "get", "can", "you", "file", "document", "script", "folder"}
    meaningful_words = [w for w in words if w.lower() not in filler]
    
    abstract_signals = {"about", "related", "similar", "like", "with",
                        "containing", "regarding", "notes", "report", "what", "how", "I"}
    
    if len(meaningful_words) >= 3 or any(w.lower() in abstract_signals for w in words):
        return QueryType.DESCRIPTIVE
        
    # 4. Keyword (Default)
    return QueryType.KEYWORD
