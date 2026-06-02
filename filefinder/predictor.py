import sqlite3
import datetime
import os
from collections import defaultdict

class AccessPredictor:
    def __init__(self):
        from db_utils import get_data_dir
        self.db_path = get_data_dir() / "behavior.db"

    def build_access_matrix(self):
        # Dummy implementation to avoid heavy pandas/scikit-learn dependency overhead
        # In a full ML system, this would build a feature matrix.
        pass

    def predict_likely_files(self, horizon_hours=2):
        """Returns likely files to be opened based on time of day."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            now = datetime.datetime.now()
            current_hour = now.hour
            
            # Predict based on files opened around this time of day historically
            # hour_start and hour_end
            start_hour = (current_hour - 1) % 24
            end_hour = (current_hour + horizon_hours) % 24
            
            # Query files opened during this hour window across all days
            if start_hour < end_hour:
                query = "SELECT path, count(*) as c FROM opens WHERE cast(strftime('%H', datetime(timestamp, 'unixepoch', 'localtime')) as integer) BETWEEN ? AND ? GROUP BY path ORDER BY c DESC LIMIT 10"
                params = (start_hour, end_hour)
            else:
                query = "SELECT path, count(*) as c FROM opens WHERE cast(strftime('%H', datetime(timestamp, 'unixepoch', 'localtime')) as integer) >= ? OR cast(strftime('%H', datetime(timestamp, 'unixepoch', 'localtime')) as integer) <= ? GROUP BY path ORDER BY c DESC LIMIT 10"
                params = (start_hour, end_hour)
                
            cur = conn.execute(query, params)
            
            predictions = []
            for row in cur.fetchall():
                path = row[0]
                if os.path.exists(path):
                    # Confidence is just an arbitrary metric based on count
                    confidence = min(0.99, 0.5 + (row[1] * 0.05))
                    predictions.append({"path": path, "confidence": confidence})
                    
            conn.close()
            return predictions
        except Exception:
            return []
