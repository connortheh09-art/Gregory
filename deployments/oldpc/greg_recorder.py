"""Opt-in local SQLite recorder. Only its writer thread touches the writable DB.

An admitted event is not committed. No network, model or game control lives here.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import threading
import time

from greg_events import EventFactory, Event, new_id, utc, validate_event, sanitize

DDL = '''
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE runs(run_id TEXT PRIMARY KEY,session_id TEXT NOT NULL,started_at_utc TEXT NOT NULL,
 ended_at_utc TEXT,end_reason TEXT,build_json TEXT NOT NULL,coverage_json TEXT NOT NULL);
CREATE TABLE events(ingest_sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL UNIQUE,
 schema_version INTEGER NOT NULL CHECK(schema_version=1),run_id TEXT NOT NULL REFERENCES runs(run_id),
 source TEXT NOT NULL,source_instance_id TEXT NOT NULL,source_sequence INTEGER NOT NULL,
 event_type TEXT NOT NULL,received_at_utc TEXT NOT NULL,correlation_id TEXT,action_id TEXT,
 envelope_json TEXT NOT NULL,UNIQUE(source_instance_id,source,source_sequence));
CREATE INDEX events_run ON events(run_id,ingest_sequence);
CREATE INDEX events_correlation ON events(correlation_id,ingest_sequence);
CREATE INDEX events_action ON events(action_id,ingest_sequence);
CREATE INDEX events_type_time ON events(event_type,received_at_utc);
CREATE TABLE links(from_event_id TEXT NOT NULL,relation TEXT NOT NULL,to_id TEXT NOT NULL,to_kind TEXT NOT NULL,
 PRIMARY KEY(from_event_id,relation,to_id,to_kind));
CREATE INDEX links_target ON links(to_id,to_kind);
CREATE TABLE experiences(correlation_id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(run_id),
 started_event_id TEXT NOT NULL,terminal_event_id TEXT,record_state TEXT NOT NULL,
 closure_reason TEXT,world_outcome TEXT NOT NULL,verdict TEXT NOT NULL,
 projection_version INTEGER NOT NULL,summary_json TEXT NOT NULL);
CREATE INDEX experiences_run ON experiences(run_id,correlation_id);
'''


class NullRecorder:
    enabled = False
    run_id = None
    def record(self, *args, **kwargs): return None
    def emit(self, *args, **kwargs): return 'disabled'
    def health(self): return {'status': 'disabled'}
    def close(self, **kwargs): return self.health()


@contextmanager
def writer_lock(path):
    """OS-owned lifetime lock. A stale lock *file* does not mean a stale lock."""
    with open(path, 'a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if handle.seek(0, 2) == 0: handle.write(b'0'); handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class Recorder:
    enabled = True
    def __init__(self, path, session_id, *, text='metadata', retention_days=7, max_mib=1024,
                 normal_limit=1024, critical_limit=256, connect=sqlite3.connect, build=None):
        self.path = Path(path).absolute()
        if str(path).startswith(('\\\\', '//')): raise ValueError('recorder requires local disk')
        if not 1 <= retention_days <= 365 or not 1 <= max_mib <= 102400:
            raise ValueError('invalid recorder retention/budget')
        if normal_limit < 1 or critical_limit < 1: raise ValueError('invalid queue limits')
        self.run_id, self.session_id = new_id(), session_id
        self.factory = EventFactory(self.run_id, session_id, text=text)
        self.retention_days, self.max_bytes = retention_days, max_mib * 1024 * 1024
        self._connect, self._build = connect, build or {}
        self._queues = {'normal': deque(), 'critical': deque()}
        self._limits = {'normal': normal_limit, 'critical': critical_limit}
        self._cv = threading.Condition()
        self._closing = False
        self._budget_halted = False
        self._stats = dict(status='starting', admitted=0, committed=0, dropped=0, invalid=0,
                           inflight=0, errors=0, last_error=None, last_ingest_sequence=0,
                           last_commit_utc=None, losses={}, started_at_utc=utc())
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name='greg-recorder', daemon=True)
        self._thread.start()

    def record(self, kind, payload=None, *, trace=None, priority='normal', **kwargs):
        try:
            event = self.factory.make(kind, payload, trace=trace, **kwargs)
            return event if self.emit(event, priority=priority) == 'queued' else None
        except Exception:
            with self._cv: self._stats['invalid'] += 1
            return None

    def emit(self, event, *, priority='normal'):
        try:
            if not isinstance(event, Event): raise ValueError('expected frozen event')
            value = event.as_dict()
            validate_event(value)
            if value['payload'] != sanitize(value['payload'], visible=self.factory.visible):
                raise ValueError('event payload bypassed privacy contract')
            if value['run_id'] != self.run_id or value['session_id'] != self.session_id:
                raise ValueError('foreign event run')
            if priority not in self._queues: raise ValueError('invalid priority')
            if priority == 'normal' and len(event.encoded) > 16384:
                raise ValueError('normal event exceeds 16 KiB')
        except Exception:
            with self._cv: self._stats['invalid'] += 1
            return 'invalid'
        with self._cv:
            if self._closing or self._budget_halted or len(self._queues[priority]) >= self._limits[priority]:
                self._stats['dropped'] += 1
                reason = 'closed' if self._closing else 'budget' if self._budget_halted else priority + '_full'
                losses = self._stats['losses']
                row = losses.setdefault(reason, {'count': 0, 'first_sequence': value['source_sequence'],
                                                 'last_sequence': value['source_sequence']})
                row['count'] += 1; row['last_sequence'] = value['source_sequence']
                return 'dropped'
            self._queues[priority].append(event)
            self._stats['admitted'] += 1
            self._cv.notify()
            return 'queued'

    def health(self):
        with self._cv:
            value = json.loads(json.dumps(self._stats))
            value.update(normal_depth=len(self._queues['normal']), critical_depth=len(self._queues['critical']),
                         run_id=self.run_id, thread_alive=self._thread.is_alive())
            return value

    def close(self, *, deadline_seconds=2.0):
        with self._cv:
            self._closing = True; self._cv.notify_all()
        self._thread.join(max(0, deadline_seconds))
        return self.health()

    def wait_ready(self, timeout=2):
        """Tests/administration only; collector never waits on DB readiness."""
        return self._ready.wait(timeout)

    def _initialize(self, db):
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=1000')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version not in {0, 1}: raise ValueError('unsupported recorder schema')
        if version == 0:
            if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                raise ValueError('unrecognized database')
            try:
                db.executescript('BEGIN IMMEDIATE;\n' + DDL + '\nPRAGMA user_version=1;\nCOMMIT;')
            except Exception:
                if db.in_transaction: db.rollback()
                raise
        if db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower() != 'wal':
            raise ValueError('WAL unavailable')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)', ('database_id', new_id()))
        started = self.factory.make('run.started', {'build': self._build, 'python_version': platform.python_version(),
                                    'sqlite_version': sqlite3.sqlite_version, 'coverage': 'playercore_navigation'})
        self._transaction(db, [started], startup=True)

    def _insert(self, db, event):
        v = event.as_dict()
        old = db.execute('SELECT envelope_json FROM events WHERE event_id=?', (v['event_id'],)).fetchone()
        if old:
            if old[0] != event.encoded: raise ValueError('conflicting duplicate event')
            return False
        db.execute('''INSERT INTO events(event_id,schema_version,run_id,source,source_instance_id,source_sequence,
                    event_type,received_at_utc,correlation_id,action_id,envelope_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                   (v['event_id'], 1, v['run_id'], v['source'], v['source_instance_id'], v['source_sequence'],
                    v['event_type'], v['received_at_utc'], v['correlation_id'], v['action_id'], event.encoded))
        for ref in v['observation_ids']:
            db.execute('INSERT OR IGNORE INTO links VALUES(?,?,?,?)', (v['event_id'], 'observation', ref, 'event'))
        if v['causation_id']:
            db.execute('INSERT OR IGNORE INTO links VALUES(?,?,?,?)', (v['event_id'], 'caused_by', v['causation_id'], 'event'))
        p, correlation = v['payload'], v['correlation_id']
        if correlation:
            db.execute('''INSERT OR IGNORE INTO experiences VALUES(?,?,?,?,?,?,?,?,?,?)''',
                       (correlation, v['run_id'], v['event_id'], None, 'open', None, 'unknown',
                        'inconclusive', 1, '{}'))
            if v['event_type'] == 'experience.closed':
                # Never let a delayed nonterminal event reopen a committed terminal record.
                db.execute('''UPDATE experiences SET terminal_event_id=?,record_state='closed',closure_reason=?,
                              world_outcome=?,verdict=?,summary_json=? WHERE correlation_id=? AND record_state='open' ''',
                           (v['event_id'], p.get('closure_reason'), p.get('world_outcome', 'unknown'),
                            p.get('verdict', 'inconclusive'), json.dumps(p), correlation))
        if v['event_type'] == 'run.ended':
            db.execute('UPDATE runs SET ended_at_utc=?,end_reason=? WHERE run_id=?',
                       (v['received_at_utc'], 'orderly', v['run_id']))
        return True

    def _transaction(self, db, batch, *, startup=False):
        db.execute('BEGIN IMMEDIATE')
        count = 0
        try:
            if startup:
                db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',
                           (self.run_id, self.session_id, utc(), None, None,
                            json.dumps(self._build), json.dumps({'navigation': True, 'voice': False, 'media': False})))
                # Recovery events belong to the new process; old outcomes remain unknown.
                old_runs = [r[0] for r in db.execute('SELECT run_id FROM runs WHERE ended_at_utc IS NULL AND run_id<>?', (self.run_id,))]
                for old in old_runs:
                    recovery = self.factory.make('run.recovered', {'reason': 'unclean_restart'})
                    count += self._insert(db, recovery)
                    db.execute("UPDATE experiences SET record_state='closed',closure_reason='unclean_restart',world_outcome='unknown',verdict='inconclusive',terminal_event_id=? WHERE run_id=? AND record_state='open'", (recovery.as_dict()['event_id'], old))
                    db.execute("UPDATE runs SET ended_at_utc=?,end_reason='unclean_restart' WHERE run_id=?", (utc(), old))
            for event in batch: count += self._insert(db, event)
            cursor = db.execute('SELECT COALESCE(MAX(ingest_sequence),0) FROM events').fetchone()[0]
            db.commit()
        except Exception:
            db.rollback()
            raise
        with self._cv:
            self._stats['committed'] += count
            self._stats['last_ingest_sequence'] = cursor
            self._stats['last_commit_utc'] = utc()

    def _maintenance(self, db):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat().replace('+00:00','Z')
        old = [r[0] for r in db.execute('SELECT run_id FROM runs WHERE ended_at_utc<? AND run_id<>? LIMIT 4', (cutoff, self.run_id))]
        for run in old:
            # Bounded per-transaction deletion; preserve projections until all rows expire.
            ids = [r[0] for r in db.execute('SELECT event_id FROM events WHERE run_id=? LIMIT 64', (run,))]
            db.execute('BEGIN IMMEDIATE')
            try:
                for eid in ids:
                    db.execute('DELETE FROM links WHERE from_event_id=? OR (to_id=? AND to_kind=?)', (eid,eid,'event'))
                    db.execute('DELETE FROM events WHERE event_id=?', (eid,))
                if not db.execute('SELECT 1 FROM events WHERE run_id=? LIMIT 1',(run,)).fetchone():
                    db.execute('DELETE FROM experiences WHERE run_id=?',(run,)); db.execute('DELETE FROM runs WHERE run_id=?',(run,))
                db.commit()
            except Exception: db.rollback(); raise
        total = sum(p.stat().st_size for p in (self.path, Path(str(self.path)+'-wal')) if p.exists())
        free = shutil.disk_usage(self.path.parent).free
        with self._cv:
            self._budget_halted = total >= self.max_bytes * .95 or free < 16 * 1024 * 1024
            self._stats['storage_bytes'] = total

    def _health_file(self):
        value = self.health()
        value['updated_at_utc'] = utc()
        path = self.path.with_name('recorder_health.json')
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(value), encoding='utf8')
        os.replace(tmp, path)

    def _run(self):
        pending = []
        db = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with writer_lock(self.path.with_name('recorder.lock')):
                db = self._connect(str(self.path), isolation_level=None, timeout=1)
                self._initialize(db)
                with self._cv: self._stats['status'] = 'ready'
                self._ready.set()
                maintained = health_at = 0.0
                served = 0
                reported_loss = 0
                while True:
                    with self._cv:
                        if not pending:
                            for _ in range(64):
                                priority = 'critical' if self._queues['critical'] and (served < 8 or not self._queues['normal']) else 'normal'
                                if not self._queues[priority]: break
                                pending.append(self._queues[priority].popleft())
                            served = served+1 if priority == 'critical' else 0
                        self._stats['inflight'] = len(pending)
                        if self._closing and not pending and not any(self._queues.values()): break
                        if not pending: self._cv.wait(.1)
                    try:
                        if pending:
                            self._transaction(db, pending)
                            pending = []
                        now = time.monotonic()
                        if now-maintained >= 5:
                            self._maintenance(db); maintained = now
                        loss = self.health()['dropped']
                        if loss != reported_loss:
                            event = self.factory.make('recorder.loss', {'count': loss, 'losses': self.health()['losses']})
                            self._transaction(db,[event]); reported_loss = loss
                        with self._cv:
                            self._stats['status'] = 'budget_halted' if self._budget_halted else 'ready'
                            self._stats['inflight'] = 0
                        if now-health_at >= 2:
                            self._health_file(); health_at = now
                    except Exception as exc:
                        with self._cv:
                            self._stats['errors'] += 1; self._stats['status'] = 'degraded'
                            self._stats['last_error'] = type(exc).__name__
                            closing = self._closing
                        if closing: break
                        # Writer-only backoff; admissions remain bounded and nonblocking.
                        with self._cv: self._cv.wait(.5)
                if not pending:
                    self._transaction(db,[self.factory.make('run.ended', {'reason': 'orderly'})])
                with self._cv:
                    self._stats['status'] = 'closed' if not pending else 'degraded'
                    self._stats['inflight'] = len(pending)
                self._health_file()
        except Exception as exc:
            with self._cv:
                self._stats['status'] = 'degraded'; self._stats['errors'] += 1
                self._stats['last_error'] = type(exc).__name__
        finally:
            self._ready.set()
            if db is not None: db.close()


def open_reader(path):
    path = Path(path).resolve()
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.25)
    db.execute('PRAGMA query_only=ON')
    if db.execute('PRAGMA user_version').fetchone()[0] != 1:
        db.close(); raise ValueError('unsupported recorder schema')
    db.row_factory = sqlite3.Row
    return db


def read_events(db, *, after=0, limit=100, max_bytes=1048576):
    if isinstance(after,bool) or after < 0 or not 1 <= limit <= 1000: raise ValueError('invalid cursor/limit')
    rows = db.execute('SELECT ingest_sequence,envelope_json FROM events WHERE ingest_sequence>? ORDER BY ingest_sequence LIMIT ?', (after,limit)).fetchall()
    events, size, cursor = [], 0, after
    for row in rows:
        if size + len(row['envelope_json']) > max_bytes: break
        value = json.loads(row['envelope_json']); value['ingest_sequence'] = row['ingest_sequence']
        events.append(value); cursor = row['ingest_sequence']; size += len(row['envelope_json'])
    first = db.execute('SELECT MIN(ingest_sequence) FROM events').fetchone()[0]
    return dict(database_id=db.execute("SELECT value FROM meta WHERE key='database_id'").fetchone()[0],
                first_available_cursor=first, next_cursor=cursor, events=events,
                retention_gap=bool(after and first and after < first-1))


def get_experience(db, correlation_id):
    row = db.execute('SELECT * FROM experiences WHERE correlation_id=?', (correlation_id,)).fetchone()
    if row is None: return None
    events = [json.loads(r[0]) for r in db.execute('SELECT envelope_json FROM events WHERE correlation_id=? ORDER BY ingest_sequence', (correlation_id,))]
    refs = {ref for event in events for ref in event['observation_ids']}
    evidence, missing = [], []
    for ref in refs:
        record = db.execute('SELECT envelope_json FROM events WHERE event_id=?', (ref,)).fetchone()
        if record: evidence.append(json.loads(record[0]))
        else: missing.append(ref)
    result = dict(row); result.update(events=events, observations=evidence, unresolved_refs=sorted(missing))
    kinds = {e['event_type'] for e in events}
    result['trace_complete'] = not missing and {'decision.requested','decision.applied','action.dispatch','controller.feedback','outcome.evaluated','experience.closed'} <= kinds
    return result


def backup(db, output, *, deadline_seconds=5):
    path = Path(output)
    # Reserve destination exclusively; never overwrite a user file.
    with path.open('xb'): pass
    target = sqlite3.connect(path)
    started = time.monotonic()
    def progress(*_):
        if time.monotonic()-started > deadline_seconds: raise TimeoutError('backup deadline')
    try: db.backup(target, pages=64, progress=progress, sleep=.01)
    finally: target.close()
