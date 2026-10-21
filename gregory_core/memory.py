"""Snapshot-based episodic memory above recorder exports, not a live-state store.

Only deterministic, cited templates consolidate observations. No LLM is called.
API actor IDs are supplied by a trusted host; this is not an authentication server.
"""
from contextlib import closing
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .embeddings import unit_vector


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def timestamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('timezone required')
    return dt.timestamp()


def project_event(event):
    """Validate PR1 identity fields; cache metadata only, hash original envelope.

    This is structural/provenance validation, NOT proof the world claim is true.
    Raw dialogue, prompts, media and arbitrary payload keys never enter memory.
    """
    event = dict(event)
    event.pop('ingest_sequence', None)
    keys = {'schema_version', 'event_id', 'run_id', 'session_id', 'source', 'source_instance_id',
            'source_sequence', 'event_type', 'source_timestamp_utc', 'received_at_utc', 'monotonic_ns',
            'correlation_id', 'causation_id', 'decision_id', 'goal_id', 'action_id', 'control',
            'observation_ids', 'payload'}
    if set(event) != keys:
        raise ValueError('not a complete PR1 envelope')
    encoded = canonical(event)
    if len(encoded.encode()) > 65536 or type(event.get('schema_version')) is not int or event.get('schema_version') != 1:
        raise ValueError('unsupported or oversized recorder envelope')
    for key in ('event_id', 'run_id', 'source_instance_id'):
        uuid.UUID(event[key])
    cid = event['correlation_id']
    if cid is not None:
        uuid.UUID(cid)
    for key in ('causation_id', 'decision_id', 'goal_id', 'action_id'):
        if event[key] is not None:
            uuid.UUID(event[key])
    refs = event['observation_ids']
    if not isinstance(refs, list) or len(refs) > 32:
        raise ValueError('invalid observation references')
    for ref in refs:
        uuid.UUID(ref)
    if type(event.get('source_sequence')) is not int or not 1 <= event['source_sequence'] <= 2**63-1:
        raise ValueError('positive source sequence required')
    if type(event['monotonic_ns']) is not int or event['monotonic_ns'] < 0:
        raise ValueError('monotonic clock required')
    timestamp(event['received_at_utc'])
    for key in ('session_id', 'event_type', 'source'):
        if not isinstance(event[key], str) or not 0 < len(event[key]) <= 160:
            raise ValueError('invalid recorder identity')
    when = timestamp(event['source_timestamp_utc'])
    payload = event['payload']
    if not isinstance(payload, dict):
        raise ValueError('invalid payload')
    # Enumerated metadata prevents raw language/model content being laundered
    # into episodic summaries. Full original evidence stays in its source export.
    allowed = {
        'world_outcome': {'succeeded', 'failed', 'unknown', 'not_applicable'},
        'status': {'moving', 'stuck', 'blocked', 'arrived', 'no_ground', 'idle', 'expired'},
        'native_status': {'moving', 'stuck', 'blocked', 'arrived', 'no_ground', 'idle', 'expired'},
        'verdict': {'pass', 'fail', 'inconclusive', 'not_applicable'},
        'closure_reason': {'verified_arrival', 'unclean_restart', 'recorder_shutdown',
                           'timeout', 'stop_submitted', 'no_gameplay_action', 'speech_submitted'},
        'origin': {'model', 'deterministic'},
    }
    safe = {k: payload[k] for k, choices in allowed.items() if payload.get(k) in choices}
    if isinstance(payload.get('parameters_complete'), bool):
        safe['parameters_complete'] = payload['parameters_complete']
    for flag in ('fresh', 'accepted'):
        if isinstance(payload.get(flag), bool):
            safe[flag] = payload[flag]
    action = payload.get('action')
    if isinstance(action, dict) and action.get('activity') in {'navigate', 'follow', 'explore', 'wait', 'say'}:
        safe['activity'] = action['activity']
    # Evaluator identity is kept as an identifier, never treated as observation.
    evaluator = payload.get('evaluator', '')
    if isinstance(evaluator, str) and re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', evaluator):
        safe['evaluator'] = evaluator
    return dict(event_id=event['event_id'], run_id=event['run_id'], session_id=event['session_id'],
                correlation_id=cid, event_type=event['event_type'], occurred=when,
                observation_ids=refs, payload=safe, source=event['source'],
                source_instance_id=event['source_instance_id'], source_sequence=event['source_sequence'],
                envelope_sha256=hashlib.sha256(encoded.encode()).hexdigest())


SCHEMA = '''
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE evidence(event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, session_id TEXT NOT NULL,
 correlation_id TEXT, occurred REAL NOT NULL, source_label TEXT NOT NULL, projection TEXT NOT NULL,
 envelope_sha256 TEXT NOT NULL, source_instance_id TEXT NOT NULL, source_sequence INTEGER NOT NULL,
 UNIQUE(source_instance_id,source_sequence));
CREATE TABLE memories(memory_id TEXT PRIMARY KEY, episode_key TEXT NOT NULL UNIQUE,
 session_id TEXT NOT NULL, domain TEXT NOT NULL, occurred REAL NOT NULL, expires REAL,
 summary TEXT NOT NULL, claims TEXT NOT NULL, uncertainty TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1, corrected INTEGER NOT NULL DEFAULT 0);
CREATE TABLE citations(memory_id TEXT REFERENCES memories ON DELETE CASCADE,
 event_id TEXT REFERENCES evidence ON DELETE RESTRICT, PRIMARY KEY(memory_id,event_id));
CREATE TABLE revisions(memory_id TEXT REFERENCES memories ON DELETE CASCADE,
 revision INTEGER NOT NULL, summary TEXT NOT NULL, claims TEXT NOT NULL, reason TEXT NOT NULL,
 PRIMARY KEY(memory_id,revision));
CREATE TABLE vectors(memory_id TEXT REFERENCES memories ON DELETE CASCADE,
 space_key TEXT NOT NULL, space TEXT NOT NULL, vector TEXT NOT NULL,
 PRIMARY KEY(memory_id,space_key));
CREATE TABLE forgotten(event_fingerprint TEXT PRIMARY KEY);
CREATE VIRTUAL TABLE memory_fts USING fts5(memory_id UNINDEXED, summary);
CREATE INDEX evidence_episode ON evidence(run_id,correlation_id);
'''


class MemoryStore:
    def __init__(self, path, *, owner_id, retention_seconds, clock=time.time):
        if not owner_id or (retention_seconds is not None and
                            (not math.isfinite(retention_seconds) or retention_seconds <= 0)):
            raise ValueError('owner and explicit positive retention/None required')
        self.path = Path(path).resolve()
        self.owner_id, self.retention_seconds, self.clock = owner_id, retention_seconds, clock
        if self.path.exists():
            try:
                with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as probe:
                    meta = dict(probe.execute('SELECT key,value FROM metadata'))
                if meta != {'kind': 'gregory.memory.v0.1', 'owner_id': owner_id}:
                    raise ValueError('wrong memory schema or owner')
            except sqlite3.Error as exc:
                raise ValueError('not a Gregory memory database') from exc
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute('PRAGMA foreign_keys=ON')
            if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='metadata'").fetchone():
                self.db.executescript(SCHEMA)
                self.db.executemany('INSERT INTO metadata VALUES(?,?)',
                                    [('kind', 'gregory.memory.v0.1'), ('owner_id', owner_id)])
                self.db.commit()
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA secure_delete=ON')
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _owner(self, actor):
        if actor != self.owner_id:
            raise PermissionError('owner-only memory API')

    def ingest(self, events, *, actor, source_label):
        self._owner(actor)
        if not isinstance(source_label, str) or not 1 <= len(source_label) <= 160:
            raise ValueError('bounded source label required')
        # Validate the entire bounded batch before any writes.
        batch = []
        for event in events:
            if len(batch) >= 10000:
                raise ValueError('snapshot batch exceeds 10000 events')
            batch.append(project_event(event))
        with self.db:
            for e in batch:
                if self.db.execute('SELECT 1 FROM forgotten WHERE event_fingerprint=?',
                                   (digest(e['event_id']),)).fetchone():
                    raise ValueError('forgotten evidence cannot be reimported')
                old = self.db.execute('SELECT envelope_sha256 FROM evidence WHERE event_id=?',
                                      (e['event_id'],)).fetchone()
                if old:
                    if old[0] != e['envelope_sha256']:
                        raise ValueError('conflicting recorder event identity')
                    continue
                self.db.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?)',
                                (e['event_id'], e['run_id'], e['session_id'], e['correlation_id'],
                                 e['occurred'], source_label, canonical(e), e['envelope_sha256'],
                                 e['source_instance_id'], e['source_sequence']))
        return len(batch)

    def consolidate(self, run_id, correlation_id, *, actor, domain):
        self._owner(actor)
        uuid.UUID(run_id)
        uuid.UUID(correlation_id)
        if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}', domain):
            raise ValueError('explicit adapter/domain identifier required')
        key = digest([run_id, correlation_id])
        old = self.db.execute('SELECT memory_id,domain FROM memories WHERE episode_key=?', (key,)).fetchone()
        if old:
            if old['domain'] != domain:
                raise ValueError('episode domain is immutable')
            return old[0]  # Immutable snapshot; never overwrite an owner correction.
        rows = self.db.execute('SELECT projection FROM evidence WHERE run_id=? AND correlation_id=? '
                               'ORDER BY rowid', (run_id, correlation_id)).fetchall()
        if not rows:
            raise ValueError('no recorder experience')
        events = [json.loads(r[0]) for r in rows]
        source_instances = {e['source_instance_id'] for e in events}
        if len(source_instances) == 1:
            events.sort(key=lambda e: e['source_sequence'])
        sessions = {e['session_id'] for e in events}
        if len(sessions) != 1:
            raise ValueError('experience crosses sessions')
        evidence = {e['event_id']: e for e in events}
        missing = set()
        for e in events:
            for ref in e['observation_ids']:
                row = self.db.execute('SELECT projection FROM evidence WHERE event_id=?', (ref,)).fetchone()
                obs = json.loads(row[0]) if row else None
                if not obs or obs['run_id'] != run_id or obs['session_id'] != e['session_id'] or obs['event_type'] != 'observation.accepted' or (
                    obs['source_instance_id'] == e['source_instance_id'] and obs['source_sequence'] > e['source_sequence']):
                    missing.add(ref)
                else:
                    evidence[ref] = obs
        claims, uncertainty = [], []
        if len(source_instances) != 1:
            uncertainty.append('multiple_source_instances')
        def claim(kind, text, refs):
            claims.append(dict(kind=kind, text=text, evidence_ids=list(dict.fromkeys(refs))))
        dispatch = [e for e in events if e['event_type'] == 'action.dispatch']
        if dispatch:
            text = {'follow': 'I tried to follow a target.', 'navigate': 'I attempted navigation.',
                    'explore': 'I attempted exploration.', 'wait': 'I attempted waiting.',
                    'say': 'I submitted speech.'}.get(dispatch[0]['payload'].get('activity'), 'I attempted an action.')
            claim('observed', text, [dispatch[0]['event_id']])
        blocked = [e for e in events if e['event_type'] == 'controller.feedback' and
                   e['payload'].get('status', e['payload'].get('native_status')) in {'stuck', 'blocked', 'no_ground'}]
        if blocked:
            claim('observed', 'The controller reported difficulty progressing.', [e['event_id'] for e in blocked])
        terminal = [e for e in events if e['event_type'] == 'experience.closed']
        outcomes = [e for e in events if e['event_type'] == 'outcome.evaluated']
        kinds = {e['event_type'] for e in events}
        # Any run-wide loss/gap in this snapshot conservatively taints the episode.
        run_events = [json.loads(r[0]) for r in self.db.execute('SELECT projection FROM evidence WHERE run_id=?', (run_id,))]
        gaps = [e for e in run_events if e['event_type'] in {'telemetry.gap', 'recorder.loss'}]
        if missing:
            uncertainty.append('missing_or_wrong_scope_observation')
        if any(e['payload'].get('fresh') is False or e['payload'].get('accepted') is False
               for e in evidence.values() if e['event_type'] == 'observation.accepted'):
            uncertainty.append('stale_or_rejected_observation')
        if gaps:
            uncertainty.append('run_contains_evidence_gap')
            evidence.update((e['event_id'], e) for e in gaps)
        if not terminal:
            uncertainty.append('missing_terminal')
        required = {'decision.requested', 'decision.applied', 'action.dispatch', 'controller.feedback'}
        if any(e['payload'].get('origin') == 'model' for e in events if e['event_type'] == 'decision.requested'):
            required.add('decision.response')
        if not required <= kinds or not any(e['payload'].get('parameters_complete') for e in dispatch):
            uncertainty.append('incomplete_action_chain')
        outcome = terminal[-1]['payload'].get('world_outcome', 'unknown') if terminal else 'unknown'
        reason = terminal[-1]['payload'].get('closure_reason') if terminal else None
        supporting = [e for e in outcomes if e['payload'].get('world_outcome') == outcome and
                      e['payload'].get('evaluator') and e['observation_ids'] and
                      e['payload'].get('verdict') == {'succeeded': 'pass', 'failed': 'fail'}.get(outcome) and
                      terminal and e['source_instance_id'] == terminal[-1]['source_instance_id'] and
                      e['source_sequence'] < terminal[-1]['source_sequence']]
        if reason == 'unclean_restart':
            uncertainty.append('unclean_restart')
        if terminal and len({e['payload'].get('world_outcome') for e in terminal}) > 1:
            uncertainty.append('conflicting_terminals')
        if outcome in {'succeeded', 'failed'} and supporting and not uncertainty:
            refs = [terminal[-1]['event_id'], supporting[-1]['event_id'], *supporting[-1]['observation_ids']]
            # An evaluator conclusion is still an inference, never raw observation.
            word = 'successful' if outcome == 'succeeded' else 'failed'
            claim('inferred', f'The recorder evaluated the outcome as {word}.', refs)
        else:
            claim('unknown', 'The final world outcome is unknown from the available evidence.',
                  [e['event_id'] for e in terminal + outcomes] or [events[-1]['event_id']])
            uncertainty.append('outcome_not_established')
        summary = ' '.join(c['text'] for c in claims)
        memory_id = str(uuid.uuid4())
        occurred = max(e['occurred'] for e in events)
        expires = occurred + self.retention_seconds if self.retention_seconds is not None else None
        with self.db:
            self.db.execute('INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?,1,0)',
                            (memory_id, key, next(iter(sessions)), domain, occurred, expires,
                             summary, canonical(claims), canonical(sorted(set(uncertainty)))))
            self.db.executemany('INSERT INTO citations VALUES(?,?)', [(memory_id, ref) for ref in evidence])
            self.db.execute('INSERT INTO memory_fts VALUES(?,?)', (memory_id, summary))
            self.db.execute('INSERT INTO revisions VALUES(?,1,?,?,?)',
                            (memory_id, summary, canonical(claims), 'deterministic-consolidation-v1'))
        return memory_id

    def inspect(self, memory_id, *, actor):
        self._owner(actor)
        row = self.db.execute('SELECT * FROM memories WHERE memory_id=?', (memory_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result['claims'] = json.loads(result['claims'])
        result['uncertainty'] = json.loads(result['uncertainty'])
        result['evidence'] = [dict(r) for r in self.db.execute(
            'SELECT e.event_id,e.envelope_sha256,e.source_label,e.projection FROM evidence e '
            'JOIN citations c USING(event_id) WHERE c.memory_id=? ORDER BY e.event_id', (memory_id,))]
        result['historical_only'] = True
        result['current_world_state'] = 'unknown; requires fresh adapter observations'
        result['expired'] = result['expires'] is not None and result['expires'] <= self.clock()
        return result

    def correct(self, memory_id, text, *, actor, reason):
        self._owner(actor)
        if not isinstance(text, str) or not text.strip() or len(text) > 2000 or not reason or len(reason) > 200:
            raise ValueError('bounded correction and reason required')
        memory = self.inspect(memory_id, actor=actor)
        if memory is None:
            raise KeyError(memory_id)
        # Owner-reported text is never upgraded into an observed fact.
        claims = canonical([dict(kind='reported', text=text, reporter='owner',
                                 evidence_ids=[e['event_id'] for e in memory['evidence']])])
        version = memory['revision'] + 1
        with self.db:
            changed = self.db.execute('UPDATE memories SET summary=?,claims=?,revision=?,corrected=1 '
                                     'WHERE memory_id=? AND revision=?',
                                     (text, claims, version, memory_id, memory['revision']))
            if changed.rowcount != 1:
                raise ValueError('memory changed during correction')
            self.db.execute('INSERT INTO revisions VALUES(?,?,?,?,?)', (memory_id, version, text, claims, reason))
            self.db.execute('DELETE FROM memory_fts WHERE memory_id=?', (memory_id,))
            self.db.execute('INSERT INTO memory_fts VALUES(?,?)', (memory_id, text))
            self.db.execute('DELETE FROM vectors WHERE memory_id=?', (memory_id,))

    def history(self, memory_id, *, actor):
        self._owner(actor)
        rows = self.db.execute('SELECT revision,summary,claims,reason FROM revisions '
                               'WHERE memory_id=? ORDER BY revision', (memory_id,)).fetchall()
        return [dict(row, claims=json.loads(row['claims'])) for row in rows]

    def index(self, memory_id, embedder, *, actor):
        self._owner(actor)
        memory = self.inspect(memory_id, actor=actor)
        if memory is None or memory['expired']:
            raise ValueError('missing or expired memory')
        vector = unit_vector(embedder.document(memory['summary']), embedder.space.dimensions)
        with self.db:
            current = self.db.execute('SELECT revision FROM memories WHERE memory_id=?', (memory_id,)).fetchone()
            if current is None or current[0] != memory['revision']:
                raise ValueError('memory changed during embedding; stale vector rejected')
            self.db.execute('INSERT OR REPLACE INTO vectors VALUES(?,?,?,?)',
                            (memory_id, embedder.space.key, canonical(embedder.space.__dict__), canonical(vector)))

    def search(self, query, *, actor, embedder=None, session_id=None, domain=None, limit=5):
        self._owner(actor)
        if not isinstance(query, str) or len(query) > 2000 or not 1 <= limit <= 100:
            raise ValueError('bounded query/limit required')
        where, params = ' (m.expires IS NULL OR m.expires>?)', [self.clock()]
        for column, value in [('session_id', session_id), ('domain', domain)]:
            if value is not None:
                where += f' AND m.{column}=?'
                params.append(value)
        words = re.findall(r'[^\W_]+', query, re.UNICODE)[:32]
        fts = ' OR '.join('"' + word + '"' for word in words)
        lexical = []
        if fts:
            lexical = [r[0] for r in self.db.execute(
                'SELECT m.memory_id FROM memory_fts JOIN memories m USING(memory_id) '
                'WHERE memory_fts MATCH ? AND ' + where + ' ORDER BY bm25(memory_fts),m.memory_id LIMIT 100',
                [fts, *params])]
        lanes, warnings = {'keyword': lexical}, []
        if embedder is not None:
            try:
                q = unit_vector(embedder.query(query), embedder.space.dimensions)
                candidates = self.db.execute('SELECT v.memory_id,v.vector FROM vectors v '
                    'JOIN memories m USING(memory_id) WHERE v.space_key=? AND ' + where + ' LIMIT 5001',
                    [embedder.space.key, *params]).fetchall()
                if len(candidates) > 5000:
                    raise ValueError('prototype semantic scan limit exceeded')
                ranked = []
                for row in candidates:
                    v = unit_vector(json.loads(row[1]), embedder.space.dimensions)
                    similarity = sum(a * b for a, b in zip(q, v))
                    if similarity > 0:
                        ranked.append((row[0], similarity))
                lanes['semantic'] = [key for key, _ in sorted(ranked, key=lambda x: (-x[1], x[0]))[:100]]
                if not candidates:
                    warnings.append('no_vectors_for_selected_model_revision')
            except Exception as exc:
                warnings.append('semantic_unavailable:' + type(exc).__name__)
        # Reciprocal rank fusion avoids pretending BM25 and cosine share a scale.
        scores = {}
        for lane in lanes.values():
            for rank, key in enumerate(lane, 1):
                scores[key] = scores.get(key, 0) + 1 / (60 + rank)
        hits = []
        for key in sorted(scores, key=lambda k: (-scores[k], k))[:limit]:
            hit = self.inspect(key, actor=actor)
            hit['retrieval_score'] = scores[key]
            hit['retrieval_channels'] = [name for name, ids in lanes.items() if key in ids]
            hits.append(hit)
        return dict(hits=hits, warnings=warnings, mode='hybrid' if 'semantic' in lanes else 'keyword',
                    historical_only=True, current_world_state='unknown; requires fresh adapter observations')

    def last_session(self, *, actor, domain=None):
        self._owner(actor)
        where, params = '(expires IS NULL OR expires>?)', [self.clock()]
        if domain is not None:
            where += ' AND domain=?'
            params.append(domain)
        row = self.db.execute('SELECT session_id FROM memories WHERE ' + where +
                              ' ORDER BY occurred DESC,memory_id LIMIT 1', params).fetchone()
        ids = [] if row is None else [r[0] for r in self.db.execute(
            'SELECT memory_id FROM memories WHERE ' + where + ' AND session_id=? ORDER BY occurred,memory_id',
            [*params, row[0]])]
        return dict(session_id=row[0] if row else None,
                    episodes=[self.inspect(key, actor=actor) for key in ids], historical_only=True,
                    current_world_state='unknown; requires fresh adapter observations')

    def _forget(self, ids):
        for key in ids:
            refs = [r[0] for r in self.db.execute('SELECT event_id FROM citations WHERE memory_id=?', (key,))]
            self.db.execute('DELETE FROM memory_fts WHERE memory_id=?', (key,))
            self.db.execute('DELETE FROM memories WHERE memory_id=?', (key,))
            for ref in refs:
                self.db.execute('INSERT OR IGNORE INTO forgotten VALUES(?)', (digest(ref),))
                self.db.execute('DELETE FROM evidence WHERE event_id=? AND NOT EXISTS '
                                '(SELECT 1 FROM citations WHERE event_id=?)', (ref, ref))

    def forget(self, memory_id, *, actor):
        self._owner(actor)
        with self.db:
            self._forget([memory_id])

    def forget_evidence(self, event_id, *, actor):
        """Invalidate every episode depending on removed evidence, not just its text."""
        self._owner(actor)
        ids = [r[0] for r in self.db.execute('SELECT memory_id FROM citations WHERE event_id=?', (event_id,))]
        with self.db:
            self._forget(ids)
            self.db.execute('DELETE FROM evidence WHERE event_id=?', (event_id,))
            self.db.execute('INSERT OR IGNORE INTO forgotten VALUES(?)', (digest(event_id),))

    def expire(self, *, actor):
        self._owner(actor)
        ids = [r[0] for r in self.db.execute('SELECT memory_id FROM memories WHERE expires<=?', (self.clock(),))]
        with self.db:
            self._forget(ids)
            if self.retention_seconds is not None:
                orphans = [r[0] for r in self.db.execute('SELECT event_id FROM evidence WHERE occurred<=? '
                    'AND NOT EXISTS (SELECT 1 FROM citations c WHERE c.event_id=evidence.event_id)',
                    (self.clock() - self.retention_seconds,))]
                for ref in orphans:
                    self.db.execute('INSERT OR IGNORE INTO forgotten VALUES(?)', (digest(ref),))
                    self.db.execute('DELETE FROM evidence WHERE event_id=?', (ref,))
        return len(ids)
