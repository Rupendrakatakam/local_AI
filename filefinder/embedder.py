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
        
        self._worker_thread = None
        self._queue = PriorityQueue()
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
            from sentence_transformers import SentenceTransformer
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._text_model = SentenceTransformer(TEXT_EMBEDDING_MODEL, device=device)
            log.info("Loaded text model %s on %s", TEXT_EMBEDDING_MODEL, device)
            return self._text_model
        except ImportError:
            return None

    def _get_clip_model(self):
        """Lazy-load the image embedding model (CLIP)."""
        if self._clip_model is not None:
            return self._clip_model, self._clip_processor
        try:
            from transformers import CLIPModel, CLIPProcessor
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._clip_model = CLIPModel.from_pretrained(IMAGE_EMBEDDING_MODEL).to(device)
            self._clip_processor = CLIPProcessor.from_pretrained(IMAGE_EMBEDDING_MODEL)
            log.info("Loaded image model %s on %s", IMAGE_EMBEDDING_MODEL, device)
            return self._clip_model, self._clip_processor
        except ImportError:
            return None, None

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
        model, processor = self._get_clip_model()
        if model is None or processor is None:
            return []
        try:
            from PIL import Image
            import torch
            image = Image.open(path).convert("RGB")
            inputs = processor(images=image, return_tensors="pt").to(model.device)
            with torch.no_grad():
                image_features = model.get_image_features(**inputs)
            # Normalize
            image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)
            # Pad to 384 to match text vectors in the same DB (MiniLM is 384, CLIP ViT-B/32 is 512)
            # IMPORTANT: For real multimodal fusion in a single table, dimensions MUST match.
            # LanceDB requires fixed dimension. To store both, we either need 2 tables, 
            # or pad/project. Since user wants modularity, let's just create a separate table for images!
            return image_features[0].cpu().tolist()
        except Exception as e:
            log.debug("Image embed failed for %s: %s", path, e)
            return []

    def upsert_text_embeddings(self, path: str, chunks: list[str], vectors: list[list[float]], mtime: float, ext: str):
        table = self._get_db()
        if table is None:
            return
        
        try:
            table.delete(f'path = "{path}"')
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
            self._queue.put((priority, path, mtime))
            self._progress["total"] += 1
            
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
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        log.info("Embedding worker started")

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
        
        # Image embedding path (future extension with 2nd table)
        if ext in {'.jpg', '.jpeg', '.png', '.webp'}:
            # To be implemented when image table is created
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
            db_path.parent.mkdir(parents=True, exist_ok=True)
            
            conn = sqlite3.connect(db_path)
            # Create hash table if missing
            conn.execute("CREATE TABLE IF NOT EXISTS embedding_hashes (path TEXT PRIMARY KEY, hash TEXT)")
            
            # Check existing hash
            cursor = conn.execute("SELECT hash FROM embedding_hashes WHERE path = ?", (path,))
            row = cursor.fetchone()
            if row and row[0] == content_hash:
                # Content has not changed, skip embedding!
                conn.close()
                return
                
            # Content changed (or new file), save to FTS and update hash
            conn.execute("DELETE FROM file_content_fts WHERE path = ?", (path,))
            conn.execute("INSERT INTO file_content_fts(path, content) VALUES (?, ?)", (path, text))
            conn.execute("INSERT OR REPLACE INTO embedding_hashes(path, hash) VALUES (?, ?)", (path, content_hash))
            conn.commit()
            
            # Feature 5.2: Auto-Tagging
            conn.execute("CREATE TABLE IF NOT EXISTS file_tags (path TEXT PRIMARY KEY, tags TEXT)")
            cursor = conn.execute("SELECT tags FROM file_tags WHERE path = ?", (path,))
            if not cursor.fetchone():
                try:
                    import requests
                    from config_loader import get as cfg
                    OLLAMA_URL = cfg("ollama_url", "http://localhost:11434/api/generate")
                    MODEL = cfg("ollama_model", "phi3:mini")
                    
                    snippet = text[:500]
                    prompt = f"Given the filename {path} and snippet: '{snippet}', output 1-3 comma-separated categories for this file (e.g. work, personal, finance, code, media, document, homework, tax). Only output the tags, nothing else."
                    
                    resp = requests.post(OLLAMA_URL, json={"model": MODEL, "prompt": prompt, "stream": False}, timeout=10)
                    if resp.status_code == 200:
                        tags = resp.json().get("response", "").strip().lower()
                        # Clean up
                        tags = tags.replace('"', '').replace('.', '').replace('tags:', '').replace('categories:', '').strip()
                        if tags:
                            conn.execute("INSERT OR REPLACE INTO file_tags (path, tags) VALUES (?, ?)", (path, tags))
                            conn.commit()
                except Exception as tag_e:
                    log.debug("Auto-tagging failed for %s: %s", path, tag_e)

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
