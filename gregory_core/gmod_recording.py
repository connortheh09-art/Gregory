"""Bounded Recorder ingestion primitives; no game controls, memory imports or process management."""
from datetime import datetime
import hashlib
import json
import math
import os
import stat
from pathlib import Path
import uuid

from greg_recorder import open_reader, read_events
from greg_events import validate_event


class RecordingRefused(ValueError):
    def __init__(self, reason, **detail):
        self.receipt = dict(type='recording_refused', reason=reason, **detail)
        super().__init__(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def counter(value):
    if type(value) is not int or not 0 <= value <= 2**63-1:
        raise RecordingRefused('invalid_cursor')
    return value


def binding(value):
    keys = {'database_id', 'run_id', 'session_id', 'bridge_session', 'control_epoch'}
    if not isinstance(value, dict) or set(value) != keys:
        raise RecordingRefused('explicit_recording_binding_required')
    for key in ('database_id', 'run_id'):
        try:
            uuid.UUID(value[key])
        except (ValueError, TypeError, AttributeError):
            raise RecordingRefused('invalid_recording_identity') from None
    for key in ('session_id', 'bridge_session'):
        if not isinstance(value[key], str) or not 1 <= len(value[key]) <= 160:
            raise RecordingRefused('invalid_session_binding')
    counter(value['control_epoch'])
    return dict(value)


def read_page(path, *, database_id, after=0, limit=64, max_bytes=262144):
    """One consistent bounded read; the connection is closed before returning/delivery."""
    uuid.UUID(database_id)
    counter(after)
    if type(limit) is not int or not 1 <= limit <= 64 or type(max_bytes) is not int or not 1 <= max_bytes <= 262144:
        raise RecordingRefused('invalid_batch_budget')
    with open_reader(path) as db:  # ReadConnection BEGIN / finally-close, not sqlite's base context.
        page = read_events(db, after=after, limit=limit, max_bytes=max_bytes)
        if page['database_id'] != database_id:
            raise RecordingRefused('database_changed')
        tail = db.execute("""SELECT COALESCE(MAX(e.ingest_sequence),0) FROM events e JOIN runs r ON r.run_id=e.run_id
            WHERE COALESCE(r.end_reason,'')<>'retention_expiring'""").fetchone()[0]
        if after > tail:
            raise RecordingRefused('cursor_beyond_tail', cursor=after, last_available_cursor=tail)
        if page['retention_gap']:
            raise RecordingRefused('retention_gap', cursor=after)
        if after < tail and not page['events']:
            raise RecordingRefused('event_exceeds_batch_budget')
        page.update(after_cursor=after, last_available_cursor=tail)
    return page


def validate_page(page, expected):
    if not isinstance(page, dict) or set(page) != {'database_id', 'first_available_cursor', 'next_cursor',
            'events', 'retention_gap', 'coverage', 'after_cursor', 'last_available_cursor'}:
        raise RecordingRefused('invalid_page_contract')
    if page['database_id'] != expected['database_id']:
        raise RecordingRefused('database_changed')
    first, after, tail, nxt = page['first_available_cursor'], counter(page['after_cursor']), counter(page['last_available_cursor']), counter(page['next_cursor'])
    if first is not None and (counter(first) < 1 or first > tail):
        raise RecordingRefused('invalid_first_cursor')
    if after > tail:
        raise RecordingRefused('cursor_beyond_tail')
    if page['retention_gap'] is not False or (after and first and after < first-1):
        raise RecordingRefused('retention_gap')
    if page['coverage'] != 'committed_events_only' or not isinstance(page['events'], list) or len(page['events']) > 64:
        raise RecordingRefused('invalid_page_contract')
    if len(canonical(page).encode()) > 300000:
        raise RecordingRefused('invalid_batch_budget')
    previous = after
    for event in page['events']:
        if not isinstance(event, dict):
            raise RecordingRefused('invalid_envelope')
        seq = counter(event.get('ingest_sequence'))
        if not previous < seq <= tail:
            raise RecordingRefused('invalid_cursor_order')
        previous = seq
    if nxt != previous or not after <= nxt <= tail or (after < tail and not page['events']):
        raise RecordingRefused('invalid_next_cursor')


def prepare(event, expected, *, origin, seen_at, now, freshness_seconds):
    value = dict(event)
    value.pop('ingest_sequence')
    try:
        validate_event(value)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RecordingRefused('invalid_envelope') from None
    if value['run_id'] != expected['run_id'] or value['session_id'] != expected['session_id']:
        raise RecordingRefused('source_session_mismatch')
    control = value['control']
    # Recorder run lifecycle rows have no game control context. Any supplied context must agree.
    for key in ('bridge_session', 'control_epoch'):
        if control[key] is not None and control[key] != expected[key]:
            raise RecordingRefused('source_session_mismatch')
    if origin not in {'live', 'replay'}:
        raise RecordingRefused('explicit_origin_required')
    if (type(seen_at) not in (float, int) or not math.isfinite(seen_at) or seen_at > now or
            (origin == 'live' and now-seen_at > freshness_seconds)):
        raise RecordingRefused('stale_or_future_delivery')
    recorded_at = datetime.fromisoformat(value['source_timestamp_utc'].replace('Z', '+00:00')).timestamp()
    if origin == 'live':
        if not 0 <= now-recorded_at <= freshness_seconds:
            raise RecordingRefused('stale_or_future_source')
        if value['event_type'] == 'observation.accepted' and any(control[k] != expected[k] for k in ('bridge_session','control_epoch')):
            raise RecordingRefused('source_session_mismatch')
    kind = value['event_type']
    category = ('observation' if kind.startswith(('observation.', 'sensor.', 'model.')) else
                'decision' if kind.startswith(('decision.', 'action.')) else
                'outcome' if kind in {'outcome.evaluated', 'experience.closed', 'controller.feedback'} else
                'error' if kind.startswith(('telemetry.', 'recorder.')) else 'lifecycle')
    return dict(envelope=value, envelope_sha256=digest(value), category=category, recorded_at=recorded_at,
                source_age_seconds=now-recorded_at, seen_at=seen_at, origin=origin,
                source_event_id=canonical([value['source_instance_id'], value['source'], value['source_sequence']]))


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS recorder_ingest(
        source TEXT NOT NULL, source_event_id TEXT NOT NULL, event_id TEXT NOT NULL,
        envelope_sha256 TEXT NOT NULL, journal_id TEXT NOT NULL,
        PRIMARY KEY(source,source_event_id), UNIQUE(source,event_id))''')


def ingest(db, page, expected, *, origin, seen_at, now, freshness_seconds, core_run_id, adapter_session, fixture):
    validate_page(page, expected)
    prepared = [prepare(e, expected, origin=origin, seen_at=seen_at, now=now,
                        freshness_seconds=freshness_seconds) for e in page['events']]
    accepted = duplicates = 0
    source = 'recorder:' + expected['database_id']
    with db:  # All validation/conflict checks and journal/key inserts succeed together or roll back.
        namespace_preexisting = db.execute('SELECT 1 FROM recorder_ingest WHERE source=? LIMIT 1', (source,)).fetchone() is not None
        for row in prepared:
            e = row['envelope']
            old = db.execute('SELECT source_event_id,event_id,envelope_sha256 FROM recorder_ingest WHERE source=? AND (source_event_id=? OR event_id=?)',
                             (source, row['source_event_id'], e['event_id'])).fetchall()
            if old:
                if len(old) != 1 or tuple(old[0]) != (row['source_event_id'], e['event_id'], row['envelope_sha256']):
                    raise RecordingRefused('canonical_identity_conflict', event_id=e['event_id'])
                duplicates += 1
                continue
            jid = str(uuid.uuid4())
            payload = dict(row, adapter_session=adapter_session, database_id=expected['database_id'],
                           qualification='recorded evidence report; not current state, memory import or Core model call')
            if len(canonical(payload).encode()) > 16384:
                raise RecordingRefused('event_report_exceeds_journal_budget')
            db.execute('INSERT INTO events(id,occurred,run_id,kind,source,fixture,origin,correlation_id,payload) VALUES(?,?,?,?,?,?,?,?,?)',
                       (jid, now, core_run_id, row['category'], source, int(fixture),
                        'fixture' if fixture else origin, e['correlation_id'], canonical(payload)))
            db.execute('INSERT INTO recorder_ingest VALUES(?,?,?,?,?)',
                       (source, row['source_event_id'], e['event_id'], row['envelope_sha256'], jid))
            accepted += 1
    return dict(type='recorded_batch_committed', database_id=expected['database_id'],
                next_cursor=page['next_cursor'], accepted=accepted, duplicates=duplicates,
                batch_sha256=digest(page), observation_promoted_to_current=False,
                source_namespace=source, namespace_preexisting=namespace_preexisting,
                namespace_notice=('existing database namespace' if namespace_preexisting else
                    'new database namespace; not proof of continuity with another database_id'))


def load_cursor(path, database_id):
    uuid.UUID(database_id)
    path = Path(path)
    if not path.exists():
        return 0
    row = json.loads(path.read_text())
    if set(row) != {'database_id', 'cursor'} or row['database_id'] != database_id:
        raise RecordingRefused('cursor_database_changed')
    return counter(row['cursor'])


def save_after_receipt(path, page, receipt):
    """Call under the cursor lock, after delivery and outside any Recorder snapshot."""
    if (receipt.get('type') != 'recorded_batch_committed' or receipt.get('database_id') != page['database_id'] or
            receipt.get('batch_sha256') != digest(page) or receipt.get('next_cursor') != page['next_cursor'] or
            receipt.get('accepted', -1) + receipt.get('duplicates', -1) != len(page['events']) or
            receipt.get('_result', {}).get('status') != 'committed'):
        raise RecordingRefused('uncommitted_or_wrong_batch_receipt')
    path = Path(path)
    if load_cursor(path, page['database_id']) != page['after_cursor']:
        raise RecordingRefused('cursor_changed_during_delivery')
    temporary = path.with_name(path.name+'.tmp')
    # A previous crash can leave this reserved, untrusted temporary. Recompute
    # from the validated durable receipt; never trust its contents or recurse.
    try:
        info = temporary.lstat()
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(info.st_mode) or temporary.resolve() != temporary.absolute():
            raise RecordingRefused('unsafe_cursor_temporary')
        temporary.unlink()
    with temporary.open('x', encoding='utf8') as handle:
        handle.write(canonical(dict(database_id=page['database_id'], cursor=page['next_cursor'])))
        handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)
    if os.name != 'nt':
        fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
