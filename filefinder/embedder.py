"""
embedder.py — Semantic embedding and OCR pipeline for FileChat.
Designed modularly to allow upgrading models/methods easily.
Lazy imports: only loads heavy deps if installed.
"""
import os
import time
import logging
import sqlite3
import hashlib
import threading
from pathlib import Path
from queue import PriorityQueue
from typing import Optional, List, Dict
from config_loader import get as cfg

# Suppress noisy model loading output (progress bars, LOAD REPORT, HF warnings)
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(Path.home() / ".cache" / "torch" / "sentence_transformers"))

LANCEDB_PATH = Path.home() / ".local" / "share" / "filefinder" / "vectors"

# EXTS: We focus only on documents and texts for now, per user request.
# Code files are excluded from PRIORITY_EXTS to save initial embedding time.
EMBEDDABLE_EXTS = {
    '.txt', '.md', '.rst', '.log', '.csv', '.json', '.yaml', '.yml', '.toml',
    '.pdf', '.docx', '.doc', '.rtf'
}
PRIORITY_EXTS = {'.pdf', '.docx', '.doc', '.txt', '.md'}

CHUNK_SIZE = int(cfg("chunk_size", 400))
CHUNK_OVERLAP = int(cfg("chunk_overlap", 80))
BATCH_SIZE = int(cfg("batch_size", 32))

# ==============================================================================
# Model Configuration (Modular for easy future upgrades)
# ==============================================================================
TEXT_EMBEDDING_MODEL = cfg("embedding_model", "all-MiniLM-L6-v2")
IMAGE_EMBEDDING_MODEL = cfg("image_model", "openai/clip-vit-base-patch32")
# ==============================================================================

log = logging.getLogger("embedder")

class EmbeddingPipeline:
    """Manages the lifecycle of embeddings, database, and background workers."""
    
    def __init__(self):
        self._text_model = None
        self._clip_model = None
        self._clip_processor = None
        self._db = None
        self._table = None
        self._image_table = None
        
        self._worker_thread = None
        self._queue = PriorityQueue(maxsize=500)
        self._tag_worker_thread = None
        import queue
        self._tag_queue = queue.Queue(maxsize=500)
        self._stop_event = threading.Event()
        self._progress = {"total": 0, "done": 0, "errors": 0}

    # ── Database ─────────────────────────────────────────────────────────────
    def _get_db(self):
        """Lazy-init LanceDB connection and table."""
        if self._db is not None:
            return self._table
        
        try:
            import lancedb
            import pyarrow as pa
            LANCEDB_PATH.mkdir(parents=True, exist_ok=True)
            self._db = lancedb.connect(str(LANCEDB_PATH))
            
            # Get dimension dynamically
            model = self._get_text_model()
            dim = model.get_sentence_embedding_dimension() if model else 768

            try:
                self._table = self._db.open_table("chunks")
                # Check if dimension matches existing schema
                existing_dim = self._table.schema.field("vector").type.list_size
                if existing_dim != dim:
                    log.warning(f"Vector dimension mismatch (model {dim} != db {existing_dim}). Dropping old vectors.")
                    self._db.drop_table("chunks")
                    raise ValueError("Dimension mismatch")
            except Exception:
                schema = pa.schema([
                    pa.field("path", pa.utf8()),
                    pa.field("chunk_id", pa.int32()),
                    pa.field("text", pa.utf8()),
                    pa.field("vector", pa.list_(pa.float32(), dim)),
                    pa.field("mtime", pa.float64()),
                    pa.field("extension", pa.utf8()),
                    pa.field("type", pa.utf8()), # 'text' or 'image'
                ])
                self._table = self._db.create_table("chunks", schema=schema)
                
            # Initialize image table
            try:
                self._image_table = self._db.open_table("image_chunks")
            except Exception:
                import pyarrow as pa
                img_schema = pa.schema([
                    pa.field("path", pa.utf8()),
                    pa.field("vector", pa.list_(pa.float32(), 512)),
                    pa.field("mtime", pa.float64()),
                    pa.field("extension", pa.utf8()),
                ])
                self._image_table = self._db.create_table("image_chunks", schema=img_schema)
                
            return self._table
        except ImportError:
            log.warning("lancedb not installed — semantic search disabled")
            return None

    # ── Models (Pluggable) ───────────────────────────────────────────────────
    def _get_text_model(self):
        """Lazy-load the text embedding model."""
        if self._text_model is not None:
            return self._text_model
        try:
            import logging as _logging
            # Silence transformers/sentence_transformers during model load
            for _logger_name in ("transformers", "sentence_transformers", "huggingface_hub"):
                _logging.getLogger(_logger_name).setLevel(_logging.ERROR)
            from sentence_transformers import SentenceTransformer
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            # Try offline mode first to prevent 30+ HTTP requests to HF Hub
            try:
                self._text_model = SentenceTransformer(TEXT_EMBEDDING_MODEL, device=device, local_files_only=True)
                log.info("Loaded text model %s (offline) on %s", TEXT_EMBEDDING_MODEL, device)
            except Exception:
                self._text_model = SentenceTransformer(TEXT_EMBEDDING_MODEL, device=device)
                log.info("Loaded text model %s (downloaded) on %s", TEXT_EMBEDDING_MODEL, device)
            return self._text_model
        except ImportError:
            return None

    def _get_clip_model(self):
        """Lazy-load the image embedding model (CLIP)."""
        if self._clip_model is not None:
            return self._clip_model
        try:
            import logging as _logging
            for _logger_name in ("transformers", "sentence_transformers", "huggingface_hub"):
                _logging.getLogger(_logger_name).setLevel(_logging.ERROR)
            from sentence_transformers import SentenceTransformer
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            try:
                self._clip_model = SentenceTransformer("clip-ViT-B-32", device=device, local_files_only=True)
            except Exception:
                self._clip_model = SentenceTransformer("clip-ViT-B-32", device=device)
            log.info("Loaded image model clip-ViT-B-32 on %s", device)
            return self._clip_model
        except ImportError:
            return None

    # ── Text Extractors ──────────────────────────────────────────────────────
    def _extract_text_plain(self, path: str) -> str:
        """Extract plain text."""
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                text = Path(path).read_text(encoding=enc, errors="replace")
                return text[:50_000]
            except (OSError, UnicodeDecodeError):
                continue
        return ""

    def _extract_text_pdf(self, path: str) -> str:
        """Extract text from PDF using PyMuPDF (fitz). Falls back to OCR if empty."""
        try:
            import fitz
            doc = fitz.open(path)
            pages = []
            for page in doc:
                pages.append(page.get_text())
                if len(pages) >= 50:  # Cap at 50 pages to save time/memory
                    break
            doc.close()
            text = "\n".join(pages).strip()
            
            if not text:
                # PDF is likely scanned images, fallback to OCR
                return self._ocr_pdf(path)
            return text[:50_000]
        except ImportError:
            return ""
        except Exception as e:
            log.debug("PDF extraction failed for %s: %s", path, e)
            return ""

    def _extract_text_docx(self, path: str) -> str:
        """Extract text from DOCX using mammoth."""
        try:
            import mammoth
            with open(path, "rb") as f:
                result = mammoth.extract_raw_text(f)
                return result.value[:50_000]
        except ImportError:
            return ""
        except Exception:
            return ""

    # ── Pluggable OCR ────────────────────────────────────────────────────────
    def _ocr_pdf(self, path: str) -> str:
        """Modular OCR function. Currently uses EasyOCR."""
        try:
            import fitz
            import easyocr
            import numpy as np
            
            # Initialize reader (could be cached)
            reader = easyocr.Reader(['en'], gpu=True)
            
            doc = fitz.open(path)
            text_blocks = []
            
            # OCR only first 3 pages to save time
            for i in range(min(3, len(doc))):
                page = doc[i]
                pix = page.get_pixmap()
                img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
                
                # easyocr works with BGR or RGB (pix.n=3 means RGB)
                results = reader.readtext(img_array)
                for (bbox, text, prob) in results:
                    text_blocks.append(text)
                    
            doc.close()
            return " ".join(text_blocks)[:10_000]
        except ImportError:
            return ""
        except Exception as e:
            log.debug("OCR failed for %s: %s", path, e)
            return ""

    # ── Pipeline Methods ─────────────────────────────────────────────────────
    def chunk_text(self, text: str) -> list[str]:
        words = text.split()
        if len(words) <= CHUNK_SIZE:
            return [text] if text.strip() else []
        chunks = []
        for i in range(0, len(words), CHUNK_SIZE - CHUNK_OVERLAP):
            chunk = " ".join(words[i:i + CHUNK_SIZE])
            if chunk.strip():
                chunks.append(chunk)
        return chunks

    def embed_text_chunks(self, chunks: list[str]) -> list[list[float]]:
        model = self._get_text_model()
        if model is None:
            return []
        vectors = model.encode(chunks, batch_size=BATCH_SIZE, normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()

    def embed_image(self, path: str) -> list[float]:
        """Generate CLIP vector for an image."""
        model = self._get_clip_model()
        if model is None:
            return []
        try:
            from PIL import Image
            image = Image.open(path).convert("RGB")
            # SentenceTransformer handles preprocessing and returns a numpy array
            vector = model.encode([image], convert_to_numpy=True, show_progress_bar=False)[0]
            # Normalize to ensure vector distances (cosine) work properly
            import numpy as np
            vector = vector / np.linalg.norm(vector)
            return vector.tolist()
        except Exception as e:
            log.debug("Image embed failed for %s: %s", path, e)
            return []

    def upsert_image_embeddings(self, path: str, vector: list[float], mtime: float, ext: str):
        if self._image_table is None:
            return
            
        try:
            import json
            self._image_table.delete(f"path = {json.dumps(path)}")
        except Exception:
            pass
            
        if not vector:
            return
            
        rows = [{"path": path, "vector": vector, "mtime": mtime, "extension": ext}]
        self._image_table.add(rows)

    def upsert_text_embeddings(self, path: str, chunks: list[str], vectors: list[list[float]], mtime: float, ext: str):
        table = self._get_db()
        if table is None:
            return
        
        try:
            import json
            table.delete(f"path = {json.dumps(path)}")
        except Exception:
            pass
            
        if not chunks:
            return
            
        rows = [
            {"path": path, "chunk_id": i, "text": c, "vector": v, "mtime": mtime, "extension": ext, "type": "text"}
            for i, (c, v) in enumerate(zip(chunks, vectors))
        ]
        table.add(rows)

    # ── Background Worker ────────────────────────────────────────────────────
    def enqueue(self, path: str, mtime: float):
        """Queue a file for background embedding."""
        ext = Path(path).suffix.lower()
        if ext in EMBEDDABLE_EXTS:
            priority = 0 if ext in PRIORITY_EXTS else 1
            try:
                # Use timeout to prevent complete deadlock if queue is full
                self._queue.put((priority, path, mtime), timeout=5)
                self._progress["total"] += 1
            except Exception:
                log.warning("Embedding queue full, dropping %s", path)
            
    def get_progress(self) -> dict:
        total = max(1, self._progress["total"])
        return {
            "queued": self._queue.qsize(),
            "done": self._progress["done"],
            "total": self._progress["total"],
            "errors": self._progress["errors"],
            "pct": round(100 * self._progress["done"] / total, 1),
        }

    def start_worker(self):
        """Starts background worker if not running."""
        self._stop_event.clear()
        if not (self._worker_thread and self._worker_thread.is_alive()):
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker_thread.start()
            log.info("Embedding worker started")
        if not (self._tag_worker_thread and self._tag_worker_thread.is_alive()):
            self._tag_worker_thread = threading.Thread(target=self._tag_worker_loop, daemon=True)
            self._tag_worker_thread.start()
            log.info("Tagging worker started")

    def _tag_worker_loop(self):
        while not self._stop_event.is_set():
            try:
                import queue
                path, text = self._tag_queue.get(timeout=2)
            except queue.Empty:
                continue
            except Exception:
                continue
                
            try:
                import sqlite3, requests
                from config_loader import get as cfg
                from db_utils import get_shard_path
                db_path = get_shard_path(path)
                conn = sqlite3.connect(db_path)
                cursor = conn.execute("SELECT tags FROM file_tags WHERE path = ?", (path,))
                if not cursor.fetchone():
                    OLLAMA_URL = cfg("ollama_url", "http://localhost:11434/api/generate")
                    MODEL = cfg("ollama_model", "phi3:mini")
                    
                    snippet = text[:500]
                    prompt = f"Given the filename {path} and snippet: '{snippet}', output 1-3 comma-separated categories for this file (e.g. work, personal, finance, code, media, document, homework, tax). Only output the tags, nothing else."
                    
                    resp = requests.post(OLLAMA_URL, json={"model": MODEL, "prompt": prompt, "stream": False}, timeout=10)
                    if resp.status_code == 200:
                        tags = resp.json().get("response", "").strip().lower()
                        tags = tags.replace('"', '').replace('.', '').replace('tags:', '').replace('categories:', '').strip()
                        if tags:
                            conn.execute("INSERT OR REPLACE INTO file_tags (path, tags) VALUES (?, ?)", (path, tags))
                            conn.commit()
                conn.close()
            except Exception as e:
                log.debug("Auto-tagging failed for %s: %s", path, e)
                
            try:
                import os, time
                if os.getloadavg()[0] > 2.0:
                    log.debug("High CPU load detected in tag worker. Sleeping for 2s.")
                    time.sleep(2.0)
            except OSError:
                pass

    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                priority, path, mtime = self._queue.get(timeout=2)
            except Exception:
                continue
                
            try:
                self._embed_file(path, mtime)
                self._progress["done"] += 1
            except Exception as e:
                log.debug("Embed failed for %s: %s", path, e)
                self._progress["errors"] += 1
                
            try:
                # Throttle if system load is high
                if os.getloadavg()[0] > 2.0:
                    log.debug("High CPU load detected. Sleeping for 2s.")
                    time.sleep(2.0)
            except OSError:
                pass

    def _embed_file(self, path: str, mtime: float):
        ext = Path(path).suffix.lower()
        
        # Image embedding path
        if ext in {'.jpg', '.jpeg', '.png', '.webp'}:
            img_vector = self.embed_image(path)
            if img_vector:
                self.upsert_image_embeddings(path, img_vector, mtime, ext.lstrip('.'))
                
            # Optional lightweight OCR fallback via pytesseract
            text = ""
            try:
                import pytesseract
                from PIL import Image
                text = pytesseract.image_to_string(Image.open(path))[:5000].strip()
            except Exception:
                pass # pytesseract not installed or failed
                
            # If we found text in the image, index it in FTS!
            if text:
                try:
                    from db_utils import get_shard_path
                    db_path = get_shard_path(path)
                    db_path.parent.mkdir(parents=True, exist_ok=True)
                    conn = sqlite3.connect(db_path)
                    cursor = conn.execute("SELECT rowid FROM files WHERE path = ?", (path,))
                    row = cursor.fetchone()
                    if row:
                        rowid = row[0]
                        conn.execute("DELETE FROM file_content_fts WHERE rowid = ?", (rowid,))
                        conn.execute("INSERT INTO file_content_fts(rowid, content) VALUES (?, ?)", (rowid, text))
                        conn.commit()
                    conn.close()
                except Exception as e:
                    log.debug(f"Failed to save image OCR to sqlite: {e}")
            return
            
        # Text embedding path
        if ext == ".pdf":
            text = self._extract_text_pdf(path)
        elif ext in (".docx", ".doc"):
            text = self._extract_text_docx(path)
        else:
            text = self._extract_text_plain(path)
            
        if not text or len(text.strip()) < 20:
            return
            
        # Feature 4.2: Incremental Embedding Hash Check
        content_hash = hashlib.md5(text.encode('utf-8', errors='replace')).hexdigest()
        
        try:
            from db_utils import get_shard_path
            db_path = get_shard_path(path)
            
            conn = sqlite3.connect(db_path)
            
            # Check existing hash
            cursor = conn.execute("SELECT hash FROM embedding_hashes WHERE path = ?", (path,))
            row = cursor.fetchone()
            if row and row[0] == content_hash:
                # Content has not changed, skip embedding!
                conn.close()
                return
                
            # Content changed (or new file), save to FTS and update hash
            cursor = conn.execute("SELECT rowid FROM files WHERE path = ?", (path,))
            row = cursor.fetchone()
            if row:
                rowid = row[0]
                conn.execute("DELETE FROM file_content_fts WHERE rowid = ?", (rowid,))
                conn.execute("INSERT INTO file_content_fts(rowid, content) VALUES (?, ?)", (rowid, text))
                conn.execute("INSERT OR REPLACE INTO embedding_hashes(path, hash) VALUES (?, ?)", (path, content_hash))
                conn.commit()
            
                # Feature 5.2: Auto-Tagging (Moved to background worker)
                try:
                    self._tag_queue.put_nowait((path, text))
                except Exception:
                    pass

            conn.close()
        except Exception as e:
            log.warning("Failed to save content/hash to sqlite: %s", e)
            
        chunks = self.chunk_text(text)
        if not chunks:
            return
            
        vectors = self.embed_text_chunks(chunks)
        if not vectors:
            return
            
        self.upsert_text_embeddings(path, chunks, vectors, mtime, ext.lstrip("."))

# Global singleton
pipeline = None

def get_pipeline() -> EmbeddingPipeline:
    global pipeline
    if pipeline is None:
        pipeline = EmbeddingPipeline()
    return pipeline
