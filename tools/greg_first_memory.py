#!/usr/bin/env python3
"""Offline administrative operations. Does not start a game, model or collector."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'deployments' / 'oldpc'))
from gregory_core.memory import MemoryStore
from gregory_core.canary import RETENTION_SECONDS, promote, prepare_request, logical_snapshot, write_receipt, QuestionLeakError
from greg_recorder import open_reader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('promote', 'recall-dry', 'preflight-b'))
    parser.add_argument('--memory-db')
    parser.add_argument('--source-db')
    parser.add_argument('--owner')
    parser.add_argument('--preflight-manifest')
    parser.add_argument('--receipt', required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--export')
    parser.add_argument('--window-end', type=float)
    parser.add_argument('--seal')
    parser.add_argument('--question', default='What did you encounter here last time, and where was it?')
    parser.add_argument('--empty-control', action='store_true')
    args = parser.parse_args()
    if args.operation == 'preflight-b':
        from gregory_core.canary_preflight import clean_b
        if not args.preflight_manifest: parser.error('--preflight-manifest required')
        value = clean_b(**json.loads(Path(args.preflight_manifest).read_text()))
        write_receipt(args.receipt, value)
        print(json.dumps({'operation': args.operation, 'receipt': args.receipt, 'runtime_started': False}))
        return
    if not (args.memory_db and args.source_db and args.owner):
        parser.error('--memory-db --source-db --owner required')
    if args.operation == 'promote' and not (args.run_id and args.export and args.window_end):
        parser.error('promote requires --run-id --export --window-end')
    if args.operation == 'recall-dry' and not args.empty_control and not args.seal:
        parser.error('recall requires --seal or --empty-control')
    if args.operation == 'recall-dry' and not Path(args.memory_db).is_file():
        parser.error('recall never creates a missing memory DB')
    if Path(args.receipt).exists(): parser.error('receipt destination exists')
    with MemoryStore(args.memory_db, owner_id=args.owner, retention_seconds=RETENTION_SECONDS) as store, open_reader(args.source_db) as reader:
        before = logical_snapshot(store)
        if args.operation == 'promote':
            value = promote(store, reader, args.export, actor=args.owner, run_id=args.run_id, window_end=args.window_end)
        else:
            frozen = json.loads(Path(args.seal).read_text()) if args.seal else None
            try:
                _, value = prepare_request(store, reader, frozen, actor=args.owner, question=args.question,
                                           model='OFFLINE-NO-MODEL-CALL', empty_control=args.empty_control)
            except QuestionLeakError as exc:
                write_receipt(args.receipt, exc.receipt)
                raise
            if before != logical_snapshot(store): raise ValueError('query mutated logical rows')
        write_receipt(args.receipt, value)
    print(json.dumps({'operation': args.operation, 'receipt': args.receipt, 'model_called': False}))


if __name__ == '__main__':
    main()
