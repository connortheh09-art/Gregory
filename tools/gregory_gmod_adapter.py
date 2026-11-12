"""One-page Recorder adapter primitive. No daemon, live deployment or game controls.

Requires an explicitly prepared adapter-only receipt and recording binding; never
reads the combined owner control.json. A full supervised runner is not implemented.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'deployments/oldpc'))
from gregory_core.gmod_recording import binding, load_cursor, read_page, save_after_receipt, RecordingRefused
from greg_recorder import writer_lock


def connection(path):
    row = json.loads(Path(path).read_text())
    if set(row) != {'url', 'adapter_token', 'recording', 'fixture'} or type(row['fixture']) is not bool:
        raise RecordingRefused('adapter_only_connection_required')
    url = urlsplit(row['url'])
    if (url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.username or
            url.password or url.query or url.fragment or url.path not in ('', '/')):
        raise RecordingRefused('loopback_connection_required')
    if not isinstance(row['adapter_token'], str) or not 20 <= len(row['adapter_token']) <= 128:
        raise RecordingRefused('invalid_adapter_capability')
    row['recording'] = binding(row['recording'])
    return row


def once(db_path, cursor_path, config, deliver, *, origin='replay', limit=64, max_bytes=262144):
    expected = binding(config['recording'])
    source, cursor = Path(db_path).resolve(), Path(cursor_path).absolute()
    if cursor.resolve() == source.parent or source.parent in cursor.resolve().parents:
        raise RecordingRefused('cursor_root_must_be_separate_from_recorder')
    for candidate in (cursor, cursor.with_name(cursor.name+'.lock'), cursor.with_name(cursor.name+'.tmp')):
        if candidate.resolve() != candidate:
            raise RecordingRefused('real_private_cursor_path_required')
    # One local cursor owner; this lock has no game-command or Recorder-writer authority.
    with writer_lock(Path(cursor_path).with_name(Path(cursor_path).name+'.lock')):
        after = load_cursor(cursor_path, expected['database_id'])
        page = read_page(db_path, database_id=expected['database_id'], after=after, limit=limit, max_bytes=max_bytes)
        seen_at = time.time()  # Snapshot is already closed, before calling HTTP/Core.
        receipt = deliver(page, origin, seen_at)
        save_after_receipt(cursor_path, page, receipt)
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('connection', 'recorder-db', 'cursor'):
        p.add_argument('--'+key, required=True)
    p.add_argument('--origin', choices=('replay', 'live'), default='replay')
    args = p.parse_args()
    config = connection(args.connection)
    session = 'recorder-page-' + str(uuid.uuid4())
    base = dict(kind='game', session=session)
    def rpc(data):
        req = Request(config['url'].rstrip('/')+'/api/adapter', data=json.dumps(data).encode(),
                      headers={'Authorization':'Bearer '+config['adapter_token'], 'Content-Type':'application/json'})
        with urlopen(req, timeout=10) as response:
            return json.load(response)
    rpc(dict(base, event='connect', pid=os.getpid(), fixture=config['fixture'], recording=config['recording']))
    failure = None
    try:
        result = once(args.recorder_db, args.cursor, config,
            lambda page, origin, seen_at: rpc(dict(base, event='recorded_batch', page=page, origin=origin, seen_at=seen_at)),
            origin=args.origin)
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try: rpc(dict(base, event='disconnect'))
        except Exception:
            if failure is None: raise
    print(json.dumps(result))


if __name__ == '__main__':
    main()
