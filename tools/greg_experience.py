#!/usr/bin/env python3
"""Read-only experience inspection. Does not import the collector or OpenClaw."""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deployments' / 'oldpc'))
from greg_recorder import open_reader, read_events, get_experience, backup


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db',required=True)
    sub=ap.add_subparsers(dest='command',required=True)
    sub.add_parser('status')
    for name in ('sessions','experiences','events'):
        cmd=sub.add_parser(name);cmd.add_argument('--limit',type=int,default=100)
        if name=='experiences': cmd.add_argument('--last',default='10m')
        if name=='events': cmd.add_argument('--after',type=int,default=0);cmd.add_argument('--json',action='store_true')
    cmd=sub.add_parser('show');cmd.add_argument('--correlation',required=True)
    cmd=sub.add_parser('export');cmd.add_argument('--run',required=True);cmd.add_argument('--output',required=True)
    cmd=sub.add_parser('backup');cmd.add_argument('--output',required=True)
    args=ap.parse_args(argv)
    if hasattr(args,'limit') and not 1<=args.limit<=1000: ap.error('limit must be 1..1000')
    if hasattr(args,'after') and args.after<0: ap.error('cursor must be nonnegative')
    for name in ('correlation','run'):
        if hasattr(args,name):
            try: uuid.UUID(getattr(args,name))
            except ValueError: ap.error('expected UUID')
    try:
        with open_reader(args.db) as db:
            if args.command=='status':
                result=dict(database_id=db.execute("SELECT value FROM meta WHERE key='database_id'").fetchone()[0],
                            events=db.execute('SELECT COUNT(*) FROM events').fetchone()[0],
                            sessions=db.execute('SELECT COUNT(*) FROM runs').fetchone()[0],
                            last_commit=db.execute('SELECT MAX(received_at_utc) FROM events').fetchone()[0])
            elif args.command=='sessions':
                result=[dict(r) for r in db.execute("SELECT * FROM runs WHERE COALESCE(end_reason,'')<>'retention_expiring' ORDER BY started_at_utc DESC LIMIT ?", (args.limit,))]
            elif args.command=='experiences':
                text=args.last
                if len(text)<2 or text[-1] not in 'smhd' or not text[:-1].isdigit(): ap.error('last must be e.g. 10m')
                seconds=int(text[:-1])*dict(s=1,m=60,h=3600,d=86400)[text[-1]]
                if not 0<seconds<=366*86400: ap.error('invalid time window')
                cutoff=(datetime.now(timezone.utc)-timedelta(seconds=seconds)).isoformat().replace('+00:00','Z')
                result=[dict(r) for r in db.execute('''SELECT x.* FROM experiences x JOIN events e ON e.event_id=x.started_event_id
                           JOIN runs r ON r.run_id=x.run_id WHERE e.received_at_utc>=?
                           AND COALESCE(r.end_reason,'')<>'retention_expiring'
                           ORDER BY e.ingest_sequence DESC LIMIT ?''',(cutoff,args.limit))]
            elif args.command=='events': result=read_events(db,after=args.after,limit=args.limit)
            elif args.command=='show':
                result=get_experience(db,args.correlation)
                if result is None:
                    print('Experience not found (possibly expired by retention).',file=sys.stderr);return 5
            elif args.command=='backup':
                backup(db,args.output);result={'snapshot':'created','path':str(Path(args.output))}
            else:
                # Export a bounded snapshot, with stable IDs and cursor in every row.
                if not db.execute("SELECT 1 FROM runs WHERE run_id=? AND COALESCE(end_reason,'')<>'retention_expiring'",(args.run,)).fetchone(): return 5
                rows=db.execute('SELECT ingest_sequence,envelope_json FROM events WHERE run_id=? ORDER BY ingest_sequence',(args.run,))
                total=0
                with Path(args.output).open('x',encoding='utf8') as output:
                    for row in rows:
                        total+=len(row['envelope_json'])
                        if total>64*1024*1024: raise ValueError('export exceeds 64 MiB; select a smaller session')
                        value=json.loads(row['envelope_json']);value['ingest_sequence']=row['ingest_sequence']
                        output.write(json.dumps(value,ensure_ascii=True)+'\n')
                result={'exported_bytes':total,'retention':'Exports require separate deletion.'}
            print(json.dumps(result,ensure_ascii=True,indent=2))
        return 0
    except sqlite3.OperationalError:
        print('Recorder database unavailable or busy.',file=sys.stderr);return 3
    except (ValueError,sqlite3.DatabaseError):
        print('Recorder schema/data unsupported or corrupt.',file=sys.stderr);return 4
    except (OSError,TimeoutError):
        print('Output unavailable, already exists, or deadline exceeded.',file=sys.stderr);return 3


if __name__=='__main__': raise SystemExit(main())
