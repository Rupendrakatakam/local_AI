from search import search, _fts_search, _db_search, _semantic_search, _filter_and_clean, _rrf_fusion, _parse_intent, _normalize_keywords
q = "can you find the files name improved in them"
intent = _parse_intent(q)
kw = intent.get("keywords") or [w for w in q.split() if len(w) >= 2]
res = _fts_search(kw, None, None, 15)
if not res: res = _db_search(kw, None, None, 15)
kw_res = _filter_and_clean(res)
sem_res = _semantic_search(q, 15)
fused = _rrf_fusion(kw_res, sem_res)
print(f"Keyword len: {len(kw_res)}")
print(f"Semantic len: {len(sem_res)}")
print(f"Fused len: {len(fused)}")
