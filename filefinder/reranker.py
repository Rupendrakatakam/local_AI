import os
import sqlite3
import numpy as np
from pathlib import Path
from config_loader import get as cfg

RERANKER_MODEL_PATH = Path.home() / ".local" / "share" / "filefinder" / "reranker.pkl"

class RerankerModel:
    def __init__(self):
        self.model = None
        self._load()
        
    def _load(self):
        if RERANKER_MODEL_PATH.exists():
            try:
                import joblib
                with open(RERANKER_MODEL_PATH, "rb") as f:
                    self.model = joblib.load(f)
            except ImportError:
                try:
                    import json
                    with open(RERANKER_MODEL_PATH.with_suffix('.json'), "r") as f:
                        self.model = json.load(f)
                except Exception:
                    pass
            except Exception:
                pass
                
    def extract_features(self, query: str, file_result) -> np.ndarray:
        """Extract 15 features for learning to rank"""
        features = [
            file_result.score,
            len(file_result.name),
            file_result.size,
            file_result.mtime,
            1 if file_result.extension in (".py", ".js", ".ts") else 0,
            1 if file_result.extension in (".md", ".txt") else 0,
            1 if query.lower() in file_result.name.lower() else 0,
            # Add more feature extractions here...
            0, 0, 0, 0, 0, 0, 0, 0
        ]
        return np.array(features)
        
    def train(self):
        try:
            from sklearn.linear_model import LogisticRegression
        except ImportError:
            return
            
        behavior_db_path = Path.home() / ".local" / "share" / "filefinder" / "behavior.db"
        if not behavior_db_path.exists():
            return
            
        try:
            conn = sqlite3.connect(behavior_db_path)
            # Basic training logic placeholder
            # Extract queries and opened paths, run _db_search, get positive/negative examples
            pass
        except Exception:
            pass
            
    def predict(self, query: str, file_results: list) -> list:
        if not self.model or not cfg("use_learned_reranker", False):
            return file_results
            
        try:
            X = np.array([self.extract_features(query, r) for r in file_results])
            scores = self.model.predict_proba(X)[:, 1]
            scored = list(zip(file_results, scores))
            scored.sort(key=lambda x: x[1], reverse=True)
            return [x[0] for x in scored]
        except Exception:
            return file_results

_model = RerankerModel()

def rerank(query: str, results: list) -> list:
    return _model.predict(query, results)
    
def train_reranker_background():
    if cfg("use_learned_reranker", False):
        import threading
        threading.Thread(target=_model.train, daemon=True).start()
