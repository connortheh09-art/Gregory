#!/usr/bin/env python3
"""Owner-side reembed: fill the vector lane for a Core root.

Run only against a stopped Core (this takes the writer lock). Use a copy of the
authoritative root first: the vector lane is optional and must never be the
reason a real memory is touched.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gregory_core.runtime import Core
from lms_embedder import build_embedder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--model-id', default='text-embedding-nomic-embed-text-v2-moe')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--limit', type=int, default=200)
    parser.add_argument('--probe', help='optional query to run after reembedding')
    args = parser.parse_args()
    embedder = build_embedder(args.endpoint, model_id=args.model_id, revision=args.revision)
    core = Core(args.root, embedder=embedder).start()
    report = {'root': str(Path(args.root).resolve())}
    try:
        report['reembed'] = core.call('reembed', {'limit': args.limit})
        report['embedding'] = core.call('status')['embedding']
        if args.probe:
            result = core.call('lookup', {'query': args.probe})
            report['probe'] = {
                'query': args.probe,
                'hits': [{'memory_id': hit['memory_id'],
                          'channels': hit.get('retrieval_channels'),
                          'summary': hit['summary'][:120]} for hit in result['hits']],
                'historical_only': result['historical_only'],
                'current_world_state': result['current_world_state'],
            }
    finally:
        try:
            report['stop'] = core.call('stop')
        except Exception as exc:
            report['stop'] = 'ERROR: ' + type(exc).__name__
    print(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
