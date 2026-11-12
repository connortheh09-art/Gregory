"""Opt-in B recall. Small speech-only path using existing model/mailbox helpers.

Not qualified for live use. Gates B/C and external supervision remain required.
"""
import json
import os
from pathlib import Path
import sys
import time
import uuid


def run_recall(args, *, bridge_module):
    root = Path(__file__).resolve().parents[2]
    if not (root / 'gregory_core').is_dir(): raise ValueError('reviewed core package missing')
    sys.path.insert(0, str(root))
    from gregory_core.memory import MemoryStore, digest
    from gregory_core.canary import (RETENTION_SECONDS, prepare_request, speech_only, logical_snapshot,
                                    write_receipt, QuestionLeakError, current_presence_check)
    from gregory_core.canary_preflight import started_b
    from greg_recorder import open_reader
    from greg_model import configure
    from greg_canary_watch import await_baseline, supervision

    config = json.loads(Path(args.first_memory_recall).read_text())
    required = {'memory_db', 'source_db', 'owner', 'seal', 'question', 'preflight_receipt',
                'preflight_sha256', 'allowed_b_files', 'receipt_prefix', 'empty_control'}
    if set(config) != required: raise ValueError('exact recall manifest required')
    if args.model == 'auto': raise ValueError('pin existing configured model; no discovery in B')
    pre = json.loads(Path(config['preflight_receipt']).read_text())
    if digest(pre) != config['preflight_sha256']: raise ValueError('preflight receipt digest mismatch')
    if type(config['empty_control']) is not bool: raise ValueError('explicit empty-control flag required')
    if Path(pre['source_root']).resolve() != Path(__file__).resolve().parent:
        raise ValueError('loaded bridge is not fresh B source copy')
    if Path(pre['transport_root']).resolve() != (Path(args.data) / 'greg').resolve():
        raise ValueError('Lua fixed transport path mismatch')
    if Path(pre['core_root']).resolve() != root / 'gregory_core': raise ValueError('core package path mismatch')
    paths = pre['absent']
    expected = dict(chat_memory='greg_chat_memory.json', player_memory='greg_player_memory',
                    audit='greg_model_audit.jsonl', trace='trace.jsonl',
                    lessons='greg_lessons.jsonl', landmarks='greg_landmarks.json')
    if os.environ.get('GREG_TRACE_PATH') or os.environ.get('PYTHONPATH'):
        raise ValueError('B forbids trace/module path environment overrides')
    for key, name in expected.items():
        if paths.get(key) != str(Path(__file__).resolve().with_name(name)):
            raise ValueError('source-relative path override is not isolated')
    # Fail before touching model or writable memory store. Never create/rotate data.
    loaded = {}
    for name in ('gmod_bridge', 'greg_dialogue', 'greg_chat_memory', 'greg_playercore'):
        module = bridge_module if name == 'gmod_bridge' else sys.modules.get(name)
        path = Path(module.__file__).resolve() if module and getattr(module, '__file__', None) else None
        if path != Path(pre['source_root']) / (name + '.py'): raise ValueError('loaded module outside pinned B source')
        loaded[name] = str(path)
    if Path(sys.modules['gregory_core.memory'].__file__).resolve() != root / 'gregory_core' / 'memory.py':
        raise ValueError('loaded memory package outside pinned B source')
    preflight = started_b(pre, allowed_files=config['allowed_b_files'])
    preflight['loaded_modules'] = loaded
    prefix = Path(config['receipt_prefix'])
    for protected in (pre['source_root'], pre['core_root'], pre['transport_root']):
        if prefix.resolve().is_relative_to(Path(protected).resolve()): raise ValueError('receipt output overlaps B inputs')
    write_receipt(str(prefix) + '.preflight.json', preflight)
    await_baseline(args.first_memory_monitor)
    configure(args.model_min_tokens, min(args.model_timeout, 8), args.model_reasoning)
    frozen = None if config['empty_control'] else json.loads(Path(config['seal']).read_text())
    if not Path(config['memory_db']).is_file(): raise ValueError('B memory database must already exist')
    b = bridge_module
    session = uuid.uuid4().hex
    tail = b.Tail(Path(args.data) / 'greg' / 'state.json')
    source_session = None
    start = time.monotonic()

    def current():
        nonlocal source_session
        latest = None
        for line in tail.read_new():
            state = json.loads(line)
            if args.steamid and state.get('steamid') != args.steamid: continue
            if not b.actionable(state, time.time()): raise ValueError('B dead/stale/disabled state')
            identity = (state['steamid'], state['bridgeSession'], state['controlEpoch'], state.get('map'))
            if source_session is not None and source_session != identity: raise ValueError('B context changed')
            source_session = identity
            latest = state
        return latest

    # No state facts, target coordinates or chat enter generation. State is used
    # only for mailbox addressing and fresh/alive/context safety gates.
    state = None
    while state is None and time.monotonic() - start <= 3:
        state = current()
        if state is None: time.sleep(.05)
    if state is None: raise ValueError('no fresh B observation')
    if state.get('map') != pre['map_name']: raise ValueError('B map does not match bootstrap')
    with MemoryStore(config['memory_db'], owner_id=config['owner'], retention_seconds=RETENTION_SECONDS) as store, open_reader(config['source_db']) as reader:
        before = logical_snapshot(store)
        store.db.execute('PRAGMA query_only=ON')
        try:
            body, receipt = prepare_request(store, reader, frozen, actor=config['owner'],
                question=config['question'], model=args.model, empty_control=config['empty_control'],
                min_tokens=args.model_min_tokens, reasoning=args.model_reasoning)
        except QuestionLeakError as exc:
            write_receipt(str(prefix) + '.request-rejected.json', exc.receipt)
            raise
        if receipt.get('a_bridge_session') == state.get('bridgeSession'):
            raise ValueError('A adapter session reused in B')
        if receipt['block']['memories'] and receipt['block']['memories'][0]['facts']['map_name'] != pre['map_name']:
            raise ValueError('retrieved map mismatch')
        receipt.update(b_session=session, b_context=list(source_session))
        write_receipt(str(prefix) + '.request.json', receipt)  # Verified and durable BEFORE model call.
        response = b.post_chat(args.lm, json=body, timeout=8)
        response.raise_for_status()
        raw = response.json()['choices'][0]['message']['content']
        action = speech_only(json.loads(raw))  # No legacy model_json audit or action routing.
        if not supervision(args.first_memory_monitor): raise ValueError('monitor baseline lost')
        fresh = current()
        if fresh is None: raise ValueError('fresh B observation required after generation')
        if time.monotonic() - start > 30: raise ValueError('bounded recall window elapsed')
        if logical_snapshot(store) != before or digest(body) != receipt['request_sha256']:
            raise ValueError('sealed rows or request changed during generation')
        # Validate sources again after generation; an external writer cannot turn
        # a once-valid receipt into permission to publish an unbound claim.
        from gregory_core.canary import retrieve
        check = retrieve(store, reader, frozen, actor=config['owner'], question=config['question'],
                         empty_control=config['empty_control'])
        if check['block_sha256'] != receipt['block_sha256']: raise ValueError('binding changed during generation')
        status = []
        presence = current_presence_check(action['text'])
        write_receipt(str(prefix) + '.speech-assessment.json', presence)
        # Existing writer accepts only this newly constructed say action.
        old_trace = b.TRACE_PATH
        try:
            b.TRACE_PATH = str(prefix) + '.trace.jsonl'  # Output only, outside B's context roots.
            b.write_cmd(Path(args.data) / 'greg' / 'cmd.json', 1, action, fresh, session, 'chat',
                        observer=lambda payload, **result: status.append(dict(payload=payload, **result)))
        finally:
            b.TRACE_PATH = old_trace
        if len(status) != 1 or status[0]['write_result'] != 'written': raise ValueError('speech submission failed')
        write_receipt(str(prefix) + '.submission.json', dict(request_sha256=digest(body),
            response=action, command=status[0], delivered=False,
            current_state_claim=presence['current_state_claim'], current_state_check=presence,
            acceptance='submission only; supervisor must corroborate actual game speech'))
        if logical_snapshot(store) != before: raise ValueError('B mutated sealed rows')
    return 0
