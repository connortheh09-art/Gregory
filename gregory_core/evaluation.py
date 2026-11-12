"""Small labelled retrieval benchmark; not an automatic truth/behavior judge."""
import statistics
import time


def evaluate_retrieval(store, cases, *, actor, embedder=None, limit=5):
    if not cases:
        raise ValueError('labelled cases required')
    rows = []
    for case in cases:
        started = time.perf_counter()
        result = store.search(case['query'], actor=actor, embedder=embedder, limit=limit,
                              domain=case.get('domain'), session_id=case.get('session_id'))
        elapsed = (time.perf_counter() - started) * 1000
        ids = [hit['memory_id'] for hit in result['hits']]
        expected = set(case['expected_ids'])
        ranks = [n for n, key in enumerate(ids, 1) if key in expected]
        rows.append(dict(query=case['query'], expected_ids=sorted(expected), retrieved_ids=ids,
                         recall=len(expected.intersection(ids)) / len(expected) if expected else float(not ids),
                         reciprocal_rank=1 / min(ranks) if ranks else 0,
                         latency_ms=elapsed, warnings=result['warnings']))
    latencies = sorted(row['latency_ms'] for row in rows)
    return dict(cases=len(rows), recall_at_k=statistics.mean(row['recall'] for row in rows),
                mrr=statistics.mean(row['reciprocal_rank'] for row in rows), k=limit,
                median_ms=statistics.median(latencies), max_ms=max(latencies),
                embedding_space=embedder.space.__dict__ if embedder else None,
                semantic_model_quality_claim=False, rows=rows)
