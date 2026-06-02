"""
backup.py — Automatic database backups for FileChat.
Runs weekly (or daily) to zip and copy SQLite shard DBs and behavior.db.
"""
import os
import time
import zipfile
from pathlib import Path
import datetime
import shutil

def get_base_dir() -> Path:
    return Path.home() / ".local" / "share" / "filefinder"

def perform_backup():
    base_dir = get_base_dir()
    backup_dir = base_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"filefinder_backup_{timestamp}.zip"
    
    files_to_backup = []
    
    # Collect all shards
    for p in base_dir.glob("*.db"):
        files_to_backup.append(p)
        
    if not files_to_backup:
        print("No databases found to backup.")
        return
        
    print(f"Creating backup: {backup_path}")
    try:
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in files_to_backup:
                # Store relative to base_dir
                arcname = file.name
                zipf.write(file, arcname)
        print("Backup completed successfully.")
        
        # Cleanup old backups (keep last 5)
        all_backups = sorted(backup_dir.glob("*.zip"))
        if len(all_backups) > 5:
            for old_backup in all_backups[:-5]:
                print(f"Removing old backup: {old_backup}")
                old_backup.unlink()
                
    except Exception as e:
        print(f"Backup failed: {e}")

if __name__ == "__main__":
    # If run directly, perform backup immediately
    perform_backup()
