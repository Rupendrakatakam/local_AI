import pytest
import sys
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestEmbedder:
    """Test embedder module."""
    
    def test_embeddable_exts(self):
        """Test EMBEDDABLE_EXTS contains expected extensions."""
        from embedder import EMBEDDABLE_EXTS, PRIORITY_EXTS
        
        assert '.pdf' in EMBEDDABLE_EXTS
        assert '.docx' in EMBEDDABLE_EXTS
        assert '.txt' in EMBEDDABLE_EXTS
        assert '.md' in EMBEDDABLE_EXTS
        assert '.py' in EMBEDDABLE_EXTS  # Code files now included for content search
        
        assert '.pdf' in PRIORITY_EXTS
        assert '.txt' in PRIORITY_EXTS
        assert '.py' in PRIORITY_EXTS
    
    def test_chunk_text(self):
        """Test text chunking."""
        from embedder import EmbeddingPipeline
        
        pipeline = EmbeddingPipeline()
        
        # Short text - single chunk
        short = "Hello world"
        chunks = pipeline.chunk_text(short)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world"
        
        # Long text - multiple chunks
        long_text = " ".join(["word"] * 500)
        chunks = pipeline.chunk_text(long_text)
        assert len(chunks) > 1
        
        # Empty text
        chunks = pipeline.chunk_text("")
        assert chunks == []
        
        # Whitespace only
        chunks = pipeline.chunk_text("   ")
        assert chunks == []
    
    def test_extract_text_plain(self):
        """Test plain text extraction."""
        from embedder import EmbeddingPipeline
        
        pipeline = EmbeddingPipeline()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Hello world\nThis is a test file.\n" * 100)
            test_file = f.name
        
        try:
            text = pipeline._extract_text_plain(test_file)
            assert "Hello world" in text
            assert "test file" in text
        finally:
            os.unlink(test_file)
    
    def test_embedding_pipeline_init(self):
        """Test EmbeddingPipeline initializes without error."""
        from embedder import EmbeddingPipeline
        
        pipeline = EmbeddingPipeline()
        assert pipeline._text_model is None
        assert pipeline._clip_model is None
        assert pipeline._db is None
    
    def test_enqueue_and_progress(self):
        """Test enqueue and progress tracking."""
        from embedder import EmbeddingPipeline
        
        pipeline = EmbeddingPipeline()
        
        # Initially empty
        progress = pipeline.get_progress()
        assert progress["total"] == 0
        assert progress["done"] == 0
        assert progress["errors"] == 0
        
        # Enqueue a file
        pipeline.enqueue("/tmp/test.txt", time.time())
        
        progress = pipeline.get_progress()
        assert progress["total"] == 1
        assert progress["queued"] == 1


import time