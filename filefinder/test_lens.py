import time
import os
import sys
from pathlib import Path

# Add current directory to path to ensure local search imports work
sys.path.insert(0, str(Path(__file__).parent))

from search import search

# 50 benchmark queries covering direct, typo, partial, natural language, and type queries
BENCHMARK_QUERIES = [
    # 1. Exact Filename Matches (18 queries)
    "search.py",
    "behavior.py",
    "indexer.py",
    "embedder.py",
    "db_utils.py",
    "config_loader.py",
    "aliases.py",
    "suggestions.py",
    "doctor.py",
    "gui.py",
    "tui.py",
    "tui_pt.py",
    "tray.py",
    "setup.sh",
    "ROADMAP.md",
    "README.md",
    "secret_doc.txt",
    "config.json",
    
    # 2. Typo Queries (Trigram) (14 queries)
    "searh.py",
    "behavir.py",
    "idxner.py",
    "embdr.py",
    "db_utls.py",
    "confg_loader.py",
    "alaes.py",
    "sugestions.py",
    "doctr.py",
    "giu.py",
    "tiu.py",
    "ROADMP.md",
    "REDME.md",
    "secrt_doc.txt",
    
    # 3. Natural Language & Partial Matches (15 queries)
    "find search",
    "behavior tracking",
    "run indexer",
    "embedding model",
    "database utilities",
    "config loader",
    "shortcuts and aliases",
    "autocomplete suggestions",
    "system doctor",
    "flask server gui",
    "textual tui",
    "interactive tray",
    "installation script",
    "project roadmap",
    "secret text",
    
    # 4. Type filters (3 queries)
    "type:code search",
    "type:document roadmap",
    "type:code db_utils"
]

def run_benchmarks():
    print("==================================================")
    # 1. Warm-up queries (to load SentenceTransformer models, init caches, etc.)
    print("Warming up search engine...")
    for q in ["search.py", "type:code behavior", "warmup query"]:
        try:
            search(q, limit=15)
        except Exception as e:
            print(f"Warmup query '{q}' failed: {e}")
            
    print("Warm-up complete. Starting benchmark of 50 queries...")
    print("==================================================")
    
    latencies = []
    success_count = 0
    results_found_total = 0
    
    for i, q in enumerate(BENCHMARK_QUERIES, 1):
        start_time = time.perf_counter()
        try:
            results, is_fuzzy = search(q, limit=15)
            end_time = time.perf_counter()
            elapsed = (end_time - start_time) * 1000.0  # convert to ms
            latencies.append(elapsed)
            success_count += 1
            results_found_total += len(results)
            print(f"[{i:02d}/50] Query: '{q}' -> Found {len(results)} files (fuzzy={is_fuzzy}) in {elapsed:.2f}ms")
        except Exception as e:
            end_time = time.perf_counter()
            elapsed = (end_time - start_time) * 1000.0
            print(f"[{i:02d}/50] Query: '{q}' FAILED after {elapsed:.2f}ms: {e}")
            
    if not latencies:
        print("No successful queries run.")
        sys.exit(1)
        
    # Calculate statistics
    latencies.sort()
    n = len(latencies)
    
    min_lat = latencies[0]
    max_lat = latencies[-1]
    avg_lat = sum(latencies) / n
    
    # Percentiles
    p50 = latencies[int(n * 0.50)]
    p90 = latencies[int(n * 0.90)]
    p95 = latencies[int(n * 0.95)] if n > 19 else latencies[-1]
    
    print("\n================ BENCHMARK RESULTS ================")
    print(f"Queries Executed successfully: {success_count}/{len(BENCHMARK_QUERIES)}")
    print(f"Total Results Found:           {results_found_total}")
    print(f"Min Latency:                   {min_lat:.2f}ms")
    print(f"Average Latency:               {avg_lat:.2f}ms")
    print(f"P50 (Median) Latency:          {p50:.2f}ms")
    print(f"P90 Latency:                   {p90:.2f}ms")
    print(f"P95 Latency:                   {p95:.2f}ms")
    print(f"Max Latency:                   {max_lat:.2f}ms")
    print("===================================================")
    
    # Assertions
    print(f"Asserting P95 latency ({p95:.2f}ms) < 200ms ...")
    assert p95 < 200.0, f"Benchmark FAILED: P95 latency {p95:.2f}ms exceeds the 200ms budget!"
    print("Benchmark PASSED!")
    print("===================================================")

if __name__ == "__main__":
    run_benchmarks()
