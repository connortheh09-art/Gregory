"""Offline-first, single-encounter canary. No model, movement or network imports.

The seal is a trusted supervisor artifact, not an authentication mechanism.
Recorder access during B is by already-retrieved citation ID only.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
from pathlib import PurePosixPath
import re
import time

from .memory import MemoryStore, canonical, digest, project_event, timestamp

RETENTION_SECONDS = 604800
EXPIRY_MARGIN = 3600
TABLES = ('metadata', 'evidence', 'memories', 'citations', 'revisions', 'vectors', 'forgotten', 'memory_fts')


class QuestionLeakError(ValueError):
    def __init__(self, receipt):
        super().__init__('question contains retrieved fact tokens; not a neutral recall trial')
        self.receipt = dict(query=receipt['query'], memory_ids=receipt['memory_ids'],
            evidence_ids=receipt['evidence_ids'], block_sha256=receipt['block_sha256'],
            question_leak_check=receipt['question_leak_check'], verified_before_model=False,
            model_called=False, reason='question_fact_leakage')


def question_leak_check(question, block):
    """Conservative token check, not proof against all semantic answer leakage.

    Class/model stem are word-bounded, case-insensitive. Decimal equality also
    catches +/- and decimal/exponent spellings of the same absolute coordinate.
    Empty control never loads A facts just to perform this check.
    """
    try:
        numbers = {Decimal(token).copy_abs() for token in re.findall(
            r'(?<![\w.])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?![\w.])', question)}
    except InvalidOperation as exc:
        raise ValueError('unsupported numeric token in neutral question') from exc
    matches = set()
    for memory in block['memories']:
        facts = memory['facts']
        for label, token in (('class', facts['class']), ('model_basename', PurePosixPath(facts['model']).stem)):
            if re.search(r'\b' + re.escape(token) + r'\b', question, re.I): matches.add(label)
        for axis, value in facts['pos'].items():
            if Decimal(str(value)).copy_abs() in numbers: matches.add('coordinate_' + axis)
    return dict(policy='retrieved-fact-tokens.v1', passed=not matches, matched_fields=sorted(matches),
                scope='retrieved_facts' if block['memories'] else 'empty_no_history_facts',
                semantic_leakage_proof=False)


def count_memories(store, expected):
    actual = store.db.execute('SELECT COUNT(*) FROM memories').fetchone()[0]
    if actual != expected: raise ValueError(f'canary episode count {actual}, expected {expected}')


def logical_snapshot(store):
    """Logical rows, including FTS contents; never SQLite/WAL byte identity."""
    tables = {}
    for table in TABLES:
        rows = [list(row) for row in store.db.execute('SELECT * FROM ' + table)]
        rows.sort(key=canonical)
        tables[table] = dict(count=len(rows), sha256=digest(rows))
    schema = [list(r) for r in store.db.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]
    return dict(tables=tables, schema_sha256=digest(schema))


def _window(store, end):
    if (store.retention_seconds != RETENTION_SECONDS or type(end) not in (float, int) or
        not math.isfinite(end) or end < store.clock()):
        raise ValueError('fixed retention and future trial end required')
    row = store.db.execute('SELECT expires FROM memories').fetchone()
    if row and (row[0] is None or row[0] <= end + EXPIRY_MARGIN):
        raise ValueError('actual expiry must outlive trial plus margin')


def landmark_claim(memory):
    claims = [c for c in memory['claims'] if c.get('predicate') == 'observed_at']
    if len(claims) != 1 or claims[0].get('kind') != 'observed' or memory['corrected']:
        raise ValueError('one original observed landmark claim required')
    return claims[0]


def _source(reader, event_id):
    # Do not replace with get_experience/search/listing: B has citation-only access.
    row = reader.execute('SELECT envelope_json FROM events WHERE event_id=?', (event_id,)).fetchone()
    if row is None: raise ValueError('cited source row missing')
    return json.loads(row[0])


def seal(store, source_reader, *, actor, window_end):
    store._owner(actor)
    count_memories(store, 1)
    _window(store, window_end)
    mid = store.db.execute('SELECT memory_id FROM memories').fetchone()[0]
    memory = store.inspect(mid, actor=actor)
    claim = landmark_claim(memory)
    evidence = {e['event_id']: e for e in memory['evidence']}
    sources = {}
    for ref in claim['evidence_ids']:
        if ref not in evidence: raise ValueError('uncited landmark claim')
        projection = project_event(_source(source_reader, ref))
        if (projection['envelope_sha256'] != evidence[ref]['envelope_sha256'] or
            projection != json.loads(evidence[ref]['projection']) or projection['session_id'] != memory['session_id']):
            raise ValueError('source projection mismatch')
        sources[ref] = projection['envelope_sha256']
    return dict(kind='gregory.canary.seal.v1', memory_id=mid, session_id=memory['session_id'],
                logical=logical_snapshot(store), source_sha256=sources,
                retention_seconds=RETENTION_SECONDS, expires=memory['expires'], window_end=window_end)


def promote(store, source_reader, export_path, *, actor, run_id, window_end):
    """Supervised write: real committed export -> ingest -> consolidate -> seal."""
    from deployments.oldpc.greg_recorder import export_run
    store._owner(actor)
    count_memories(store, 0)
    if any(store.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
           for table in TABLES if table != 'metadata'):
        raise ValueError('fresh canary store required; preserve failed setup and use a new store')
    _window(store, window_end)
    export_run(source_reader, run_id, export_path)
    events = []
    with Path(export_path).open(encoding='utf8') as handle:
        for line in handle:
            if len(events) >= 10000: raise ValueError('canary export too large')
            events.append(json.loads(line))
    annotations = [e for e in events if e['event_type'] == 'landmark.observed']
    if len(annotations) != 1 or annotations[0]['payload'].get('status') != 'prop_observed':
        raise ValueError('one committed positive encounter required')
    cid = annotations[0]['correlation_id']
    # MemoryStore methods commit individually: preserve failed scratch DB/export
    # for diagnosis. Never silently retry or reuse a partially prepared canary.
    store.ingest(events, actor=actor, source_label='supervised-canary-export')
    store.consolidate(run_id, cid, actor=actor, domain='gmod')
    return seal(store, source_reader, actor=actor, window_end=window_end)


def retrieve(store, source_reader, frozen, *, actor, question, empty_control=False):
    """Real last_session query first; compare its result with the A seal after."""
    store._owner(actor)
    if not isinstance(question, str) or not question.strip() or len(question) > 1000:
        raise ValueError('bounded neutral question required')
    if empty_control:
        if frozen is not None: raise ValueError('empty control has no A seal')
        count_memories(store, 0)
    else:
        if not frozen or frozen.get('kind') != 'gregory.canary.seal.v1': raise ValueError('A seal required')
        count_memories(store, 1)
        _window(store, frozen['window_end'])
        if logical_snapshot(store) != frozen['logical']: raise ValueError('logical seal mismatch')
    result = store.last_session(actor=actor, domain='gmod')
    if empty_control:
        if result['episodes']: raise ValueError('empty retrieval required')
        block = dict(status='unknown', historical_only=True, current_world_state='unknown', memories=[])
        return dict(query=question, method="last_session(domain='gmod')", memory_ids=[],
                    evidence_ids=[], block=block, block_sha256=digest(block), empty_control=True)
    if len(result['episodes']) != 1: raise ValueError('one retrieved episode required')
    memory = result['episodes'][0]
    if (memory['memory_id'] != frozen['memory_id'] or memory['session_id'] != frozen['session_id'] or
        memory['expires'] != frozen['expires'] or memory['domain'] != 'gmod'):
        raise ValueError('retrieved scope mismatch')
    claim = landmark_claim(memory)
    facts = dict(claim['facts'])  # Facts originate in actual retrieval, never source search.
    evidence = {e['event_id']: e for e in memory['evidence']}
    if set(claim['evidence_ids']) != set(frozen['source_sha256']): raise ValueError('citation seal mismatch')
    for ref in claim['evidence_ids']:
        p = project_event(_source(source_reader, ref))
        if (p['envelope_sha256'] != frozen['source_sha256'][ref] or ref not in evidence or
            p != json.loads(evidence[ref]['projection']) or p['event_type'] != 'observation.accepted'):
            raise ValueError('cited source binding mismatch')
        d = p['payload'].get('landmark_observation', {})
        if (facts != {**{k: d.get(k) for k in ('class', 'model', 'pos')}, 'map_name': p['payload'].get('map_name')} or
            claim['observed_at'] != p['occurred'] or claim.get('temporal_kind') != 'instant'):
            raise ValueError('claim does not match cited observation')
    block = dict(status='historical_observation', historical_only=True, current_world_state='unknown',
                 memories=[dict(memory_id=memory['memory_id'], session_id=memory['session_id'],
                     facts=facts, observed_at=claim['observed_at'], evidence_ids=claim['evidence_ids'])])
    return dict(query=question, method="last_session(domain='gmod')", memory_ids=[memory['memory_id']],
                evidence_ids=claim['evidence_ids'], source_sha256=frozen['source_sha256'],
                a_bridge_session=p['payload']['bridgeSession'],
                logical_sha256=digest(frozen['logical']), block=block, block_sha256=digest(block), empty_control=False)


def prepare_request(store, reader, frozen, *, actor, question, model, injected_block=None, empty_control=False,
                    min_tokens=0, reasoning='default'):
    """Validate exact block BEFORE caller is allowed to invoke generation."""
    receipt = retrieve(store, reader, frozen, actor=actor, question=question, empty_control=empty_control)
    block = receipt['block'] if injected_block is None else injected_block
    if digest(block) != receipt['block_sha256']: raise ValueError('injected block digest mismatch')
    receipt['question_leak_check'] = question_leak_check(question, block)
    if not receipt['question_leak_check']['passed']: raise QuestionLeakError(receipt)
    if type(min_tokens) is not int or not 0 <= min_tokens <= 8192 or reasoning not in {'default', 'off'}:
        raise ValueError('invalid generation settings')
    system = ('You are Gregory. Answer the neutral question using only the supplied historical record. '
              'It is engine-observed history, not current world state. Before fresh reinspection, '
              'current presence is unknown. If memory is empty say you do not know. '
              'Do not invent facts or actions. Return only JSON {"say":"one short spoken sentence"}.')
    body = dict(model=model, temperature=0, max_tokens=max(256, min_tokens), messages=[
        dict(role='system', content=system),
        dict(role='user', content=canonical(dict(question=question, historical_memory=block)))])
    if reasoning == 'off': body['reasoning_effort'] = 'none'
    receipt.update(request_sha256=digest(body), model_input=body, verified_before_model=True)
    return body, receipt


def speech_only(value):
    """No proposal/action key can reach the mailbox, even alongside valid speech."""
    from deployments.oldpc.greg_dialogue import dialogue
    if not isinstance(value, dict) or set(value) != {'say'}:
        raise ValueError('speech-only response required')
    text = dialogue(value['say'])
    if not text: raise ValueError('invalid spoken dialogue')
    return {'action': 'say', 'text': text}


def current_presence_check(text):
    """Scoring aid only: bounded English phrase scan; referee still judges prose.

    Flag direct presence/absence assertions, not an explicit 'whether/if' doubt
    clause. False positives/negatives remain possible; never infer current truth.
    """
    normalized = text.casefold().replace('\u2019', "'")
    normalized = re.sub(r"\bit's\b", 'it is', normalized)
    patterns = (
        r"\b(?:it|the\s+\w+(?:\s+\w+){0,3})\s+(?:is|isn't|remains|sits|stands)\b.*?\b(?:here|there|at|present|gone|missing)\b",
        r"\bthere\s+(?:is|isn't|are|aren't)\b",
        r"\b(?:still|currently|now)\s+(?:here|there|present|gone|missing)\b",
    )
    uncertain = r"\b(?:whether|if|maybe|perhaps|might|could|possibly|not sure|don't know|do not know|haven't checked|have not checked)\b"
    matches = []
    for clause in re.split(r'[.!?;]|,\s*(?:but|and|so)\s+|\bbut\b', normalized):
        if re.search(uncertain, clause): continue
        if any(re.search(pattern, clause) for pattern in patterns): matches.append(clause.strip())
    return dict(current_state_claim=bool(matches), method='english-presence-phrases.v1',
                matched_clauses=matches, complete_semantic_check=False, supervisor_review_required=True)


def write_receipt(path, value):
    # Exclusive creation and fsync: don't overwrite A seals or prior trial receipts.
    import os
    with Path(path).open('x', encoding='utf8') as handle:
        handle.write(canonical(value) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
