"""Offline synthetic memory milestone. Creates only a TemporaryDirectory.

Run: python3 -B tools/greg_memory_demo.py
No network, ML runtime/model loading, production database or game connection.
"""
from pathlib import Path
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from _core_fixtures import experience, FixtureEmbedder
from gregory_core.memory import MemoryStore
from gregory_core.evaluation import evaluate_retrieval


def main():
    with tempfile.TemporaryDirectory(prefix='gregory-synthetic-memory-') as temp:
        with MemoryStore(Path(temp)/'memory.sqlite3', owner_id='synthetic-owner',
                         retention_seconds=86400, clock=lambda:1700000020) as store:
            events, run, cid = experience(movements=200, session='synthetic-last-played')
            store.ingest(events, actor='synthetic-owner', source_label='synthetic:200-movement-fixture')
            key = store.consolidate(run, cid, actor='synthetic-owner', domain='gmod')
            answer = store.last_session(actor='synthetic-owner')
            # Separate owner-reported episode for a lexical-miss ranking fixture.
            other, run, cid = experience(start=1699999900, session='synthetic-older-session')
            store.ingest(other, actor='synthetic-owner', source_label='synthetic:orchard-fixture')
            orchard = store.consolidate(run, cid, actor='synthetic-owner', domain='generic-simulation')
            store.correct(orchard, 'A synthetic orchard exercise.', actor='synthetic-owner', reason='labelled fixture')
            backend = FixtureEmbedder()
            for memory_id in (key, orchard):
                store.index(memory_id, backend, actor='synthetic-owner')
            cases = [dict(query='follow', expected_ids=[key]), dict(query='fruit', expected_ids=[orchard])]
            result = dict(status='PASS', evidence_kind='SYNTHETIC_ONLY',
                          question='What happened last time we played?',
                          answer=answer['episodes'][0]['summary'],
                          memory_count_for_200_movements=len(answer['episodes']),
                          raw_event_count=len(events), cited_event_count=len(answer['episodes'][0]['evidence']),
                          claims=answer['episodes'][0]['claims'], historical_only=answer['historical_only'],
                          evidence=answer['episodes'][0]['evidence'], source_events=events + other,
                          current_world_state=answer['current_world_state'],
                          keyword_benchmark=evaluate_retrieval(store, cases, actor='synthetic-owner'),
                          fixture_hybrid_benchmark=evaluate_retrieval(store, cases, actor='synthetic-owner', embedder=backend),
                          actual_nomic_v15='NOT RUN; local artifact/runtime qualification pending',
                          actual_nomic_v2_moe='NOT RUN; benchmark only after v1.5 qualification')
            print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
