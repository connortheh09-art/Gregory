"""Isolated Gregory process: persistent character, serialized writes, adapter seams.

No game/voice process launch, live command dispatch, model loading or embeddings.
Operational events are NOT Recorder evidence. Only canonical exports enter memory.
"""
from concurrent.futures import Future
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import queue
import sqlite3
import sys
import threading
import time
import uuid

OLDPC = Path(__file__).resolve().parents[1] / 'deployments/oldpc'
sys.path.insert(0, str(OLDPC))
from greg_recorder import writer_lock
from gregory_core.memory import MemoryStore
from gregory_core.dialogue import DialogueWindow
from gregory_core.model_task import ModelTask

KINDS = {'observation', 'memory', 'inference', 'decision', 'outcome', 'error', 'lifecycle', 'model', 'conversation'}


class AdmissionRefused(RuntimeError):
    def __init__(self, receipt):
        self.receipt=receipt
        super().__init__(receipt['reason'])


class CoreDegraded(RuntimeError):
    """Failure receipt, never a successful stopped/drained acknowledgement."""
    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__(receipt['failure'])


class MemoryCitationError(ValueError):
    """A declared citation was not in the supplied historical evidence."""


def bounded(value, limit=16384):
    encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
    if len(encoded.encode('utf8')) > limit:
        raise ValueError('bounded JSON required')
    return json.loads(encoded)


def capture_model_call(body, attempt, started, *, response=None, error=None):
    """Diagnostic D1 at the provider boundary (opt-in, local only, never raises).

    GREG_MODEL_CAPTURE=<path.jsonl> records every model request this provider sends (decision and
    finalization): the full body with system prompt and schema (images replaced by sha256/length),
    HTTP status, raw reply text or error body (bounded), and the user-prompt sha256 that joins it to
    the bridge-side GREG_DECISION_CAPTURE row (screen turns append text to the prompt: join those by
    prefix on the stored user text). Capped at 200 MB.
    """
    path = os.environ.get('GREG_MODEL_CAPTURE')
    if not path:
        return
    try:
        if os.path.exists(path) and os.path.getsize(path) > 200 * 2**20:
            return
        messages = []
        for m in body.get('messages', []):
            content = m.get('content')
            if isinstance(content, list):
                content = [dict(type='image', sha256=hashlib.sha256(str(c.get('image_url', {}).get('url', '')).encode()).hexdigest(),
                                chars=len(str(c.get('image_url', {}).get('url', ''))))
                           if c.get('type') == 'image_url' else c for c in content]
            messages.append(dict(role=m.get('role'), content=content))
        user = next((m['content'] for m in body.get('messages', []) if m.get('role') == 'user'), '')
        text = user if isinstance(user, str) else next((c.get('text', '') for c in user if c.get('type') == 'text'), '')
        row = dict(t=time.time(), seconds=round(time.perf_counter() - started, 3), attempt=attempt,
                   kind='decision' if 'response_format' in body else 'speech',
                   prompt_sha256=hashlib.sha256(text.encode()).hexdigest(),
                   body=dict({k: v for k, v in body.items() if k != 'messages'}, messages=messages))
        if response is not None:
            row.update(status=getattr(response, 'status_code', None), reply=str(getattr(response, 'text', ''))[:16384])
        if error is not None:
            row['error'] = error
        with open(path, 'a', encoding='utf8') as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
    except Exception:
        pass


class LMStudioProvider:
    """Opt-in seam using the existing local-model budget; never starts a service."""
    name = 'lm-studio'
    fixture = False

    def __init__(self, endpoint, model, *, temperature=.4):
        from urllib.parse import urlsplit
        url = urlsplit(endpoint)
        if url.scheme != 'http' or url.username or url.password or url.query or not model:
            raise ValueError('explicit credential-free local LM Studio endpoint/model required')
        # Do not accept OpenAI Platform endpoints or credentials in this local seam.
        import ipaddress
        address = ipaddress.ip_address(url.hostname)
        if not (address.is_loopback or address.is_private or address in ipaddress.ip_network('100.64.0.0/10')):
            raise ValueError('local/private model endpoint required')
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            raise ValueError('speech temperature must be finite from 0 to 2')
        self.endpoint, self.model, self.temperature = endpoint, model, float(temperature)

    def generate_constrained(self,profile,prompt,*,images=None,response_schema=None):
        return self.generate(profile,prompt,images=images,response_schema=response_schema)

    def generate(self, profile, prompt, *, images=None, response_schema=None):
        from greg_model import post_chat
        from gregory_core.provider_reply import ProviderReplyError
        import re
        # Keep this request explicit. configure() owns process-wide globals and
        # must not leak a Core provider's budget into other existing callers.
        body = dict(model=self.model, max_tokens=1024, temperature=self.temperature, reasoning_effort='none', messages=[
            dict(role='system', content=(profile['persona'] + ' You are Gregory, an AI character. '
                'Respond to the present conversation in first person. You may be curious, express a tentative '
                'preference, or suggest a next step without a recorded precedent. Recent dialogue is conversational '
                'context. Match tone and length to the exchange; casual chat can be brief, playful or straightforward. '
                'Avoid repeating stock phrases or turning every topic into an architectural metaphor. Recent dialogue is '
                'not proof of a past event. Retrieved episodic memories support historical claims, not '
                'current observation or your whole identity. Do not invent experiences, capabilities or completed '
                'actions. Never infer an empty life history from a retrieval miss. '
                'Conversational memory writes are unavailable: do not imply a lasting save or trait update succeeded. '
                'Return JSON with optional intent, say, and used_memory_ids: only IDs from supplied historical '
                'evidence that your answer actually uses, or an empty list. '
                'A proposed intent is not execution. Goals: ' + json.dumps(profile['goals']))),
            dict(role='user', content=([dict(type='text',text=prompt)]+[
                dict(type='image_url',image_url=dict(url=value)) for value in images]) if images else prompt)])
        if response_schema is not None:
            body['response_format']=dict(type='json_schema',json_schema=dict(name='gregory_decision',strict=True,schema=response_schema))
        deadline = time.monotonic() + 30
        for attempt in range(2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderReplyError('provider_reply_deadline')
            started = time.perf_counter()  # not monotonic(): the deadline tests script that clock
            try:
                response = post_chat(self.endpoint, json=body, timeout=remaining)
            except Exception as exc:
                capture_model_call(body, attempt, started, error=type(exc).__name__ + ': ' + str(exc)[:500])
                raise
            capture_model_call(body, attempt, started, response=response)
            response.raise_for_status()
            # Read final content only. Reasoning is not a speech fallback.
            try:
                choice = response.json()['choices'][0]
                content = choice['message'].get('content')
            except (KeyError, IndexError, TypeError, ValueError, AttributeError):
                raise ProviderReplyError('provider_reply_shape') from None
            if content is None or isinstance(content, str) and not content.strip():
                if attempt == 0:
                    body = dict(body, chat_template_kwargs={'enable_thinking': False})
                    continue
                raise ProviderReplyError('provider_reply_empty')
            if not isinstance(content, str):
                raise ProviderReplyError('provider_reply_content_type')
            if len(content.encode('utf8')) > 16384:
                raise ProviderReplyError('provider_reply_too_large')
            if choice.get('finish_reason') not in (None, 'stop'):
                raise ProviderReplyError('provider_reply_incomplete')
            content = content.strip()
            if content.startswith('```'):
                lines = content.splitlines()
                if (len(lines) < 3 or not re.fullmatch(r'```(?:json)?[ \t]*', lines[0], re.IGNORECASE)
                        or lines[-1] != '```'):
                    raise ProviderReplyError('provider_reply_fence')
                content = '\n'.join(lines[1:-1])
            try:
                value = json.loads(content)
            except ValueError:
                raise ProviderReplyError('provider_reply_json') from None
            if (not isinstance(value, dict) or set(value) - {'say', 'intent', 'used_memory_ids'}
                    or not isinstance(value.get('say'), str) or not value['say'].strip()):
                raise ProviderReplyError('provider_reply_dialogue')
            try:
                value=bounded(value,2400)
                if response_schema is not None:
                    from gregory_core.decision_contract import validate
                    validate(value,response_schema)
                return value
            except ValueError:
                raise ProviderReplyError('provider_reply_bounds') from None


class FixtureProvider:
    name = 'fixture-NOT-live-model'
    fixture = True

    def generate_constrained(self,profile,prompt,*,images=None,response_schema=None):
        result=self.generate(profile,prompt,images=images) if images else self.generate(profile,prompt)
        from gregory_core.decision_contract import validate
        validate(result,response_schema)
        return result

    def generate(self, profile, prompt):
        return {'say': 'This is a fixture-provider response, not live Gregory speech.',
                'intent': {'kind': 'fixture-marker', 'dispatched': False}}


class Core:
    def __init__(self, root, *, owner='connor', provider=None, heartbeat_seconds=3, freshness_seconds=3, embedder=None,
                 overview_scope=None, inbox_config=None, inbox_voice_authorizer=None, screen_source=None):
        # Set by trusted startup configuration, never by a chat/model assertion.
        if overview_scope is not None:
            import re
            if (not isinstance(overview_scope,dict) or set(overview_scope)!={'guild_id','channel_id','owner_id'} or
                any(not isinstance(v,str) or not re.fullmatch(r'[0-9]{1,20}',v) for v in overview_scope.values())):
                raise ValueError('explicit guild/channel/owner overview scope required')
            overview_scope=tuple(overview_scope[k] for k in ('guild_id','channel_id','owner_id'))
        from gregory_core.inbox import validate_config
        self.inbox_config = validate_config(inbox_config)
        if screen_source is not None:
            from gregory_core.screen import ScreenBuffer
            if not isinstance(screen_source,ScreenBuffer):raise ValueError('trusted screen buffer required')
        self.screen_source=screen_source
        if inbox_voice_authorizer is not None and not callable(inbox_voice_authorizer):
            raise ValueError('trusted voice authorizer required')
        self.inbox_voice_authorizer = inbox_voice_authorizer
        self.overview_scope=overview_scope
        self.root = Path(root).absolute()
        if self.root.resolve() != self.root:
            raise ValueError('real private Core directory required')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.owner, self.provider = owner, provider
        self.embedder = embedder
        self.dialogue = DialogueWindow()
        self.heartbeat_seconds = heartbeat_seconds
        if type(freshness_seconds) not in (float, int) or not 0 < freshness_seconds <= 60:
            raise ValueError('bounded freshness_seconds required')
        self.freshness_seconds = freshness_seconds
        self.commands = queue.Queue()
        self.admission = threading.Lock()
        self.accepting = False
        self.ready, self.finished = threading.Event(), threading.Event()
        self.state, self.failure = 'starting', None
        self.run_id = str(uuid.uuid4())
        self.started = time.monotonic()
        self.adapters = {}
        self.completed = 0
        self.model_pending = False
        self.model_task = None
        self.command_context = None
        self.cached_status = None
        self.failure_path=self.root/('failure-'+self.run_id+'.json')
        self.thread = threading.Thread(target=self._run, name='gregory-core-writer')

    def start(self):
        self.thread.start()
        if not self.ready.wait(10):
            raise RuntimeError('Core startup deadline')
        if self.failure:
            raise RuntimeError(self.failure)
        return self

    def submit(self, action, payload=None):
        future = Future()
        data = bounded(payload or {}, 1024 * 1024)
        with self.admission:
            if not self.accepting:
                raise AdmissionRefused(self._refusal('Core admission closed',action))
            if self.commands.qsize() >= 256 and action != 'stop':
                raise AdmissionRefused(self._refusal('Core queue full',action))
            if action == 'think':
                if self.model_pending:
                    raise AdmissionRefused(self._refusal('model already busy',action))
                seconds=data.get('deadline_seconds',30)
                if type(seconds) not in (float,int) or not 0 < seconds <= 60:
                    raise ValueError('bounded model deadline required')
                data['_model_deadline']=time.monotonic()+seconds
                self.model_pending = True
            if action == 'stop':
                self.accepting = False  # reserve stop after all accepted commands
            self.commands.put((str(uuid.uuid4()), action, data, future))
        return future

    def call(self, action, payload=None, timeout=40):
        if action=='status':
            return self.status_snapshot()
        if action=='think':
            payload=dict(payload or {})
            payload['deadline_seconds']=min(payload.get('deadline_seconds',30),timeout)
        return self.submit(action, payload).result(timeout)

    def _refusal(self, reason, action, actor='owner-client'):
        # Stop may already have closed SQLite. A separate fsynced control
        # journal records refusals without reopening/taking over the DB writer.
        row=dict(kind='error',origin='core',actor=actor,scope=action,
                 reason=reason,run_id=self.run_id,occurred=time.time(),type='admission_refused')
        with (self.root/'control-refusals.jsonl').open('a',encoding='utf8') as handle:
            handle.write(json.dumps(row)+'\n');handle.flush();os.fsync(handle.fileno())
        return row

    def status_snapshot(self):
        if self.cached_status is None: raise RuntimeError('Core not ready')
        value=bounded(self.cached_status,4*1024*1024)
        delta=time.monotonic()-value.pop('_snapshot_mono')
        task=self.model_task
        value['core'].update(model_state=('timed_out' if task and task.terminal else 'running' if task else 'idle'),
            inflight_action='think' if task else None, inflight_since=task.started if task else None,
            inflight_age=round(time.monotonic()-task.started,3) if task else 0,
            degraded=bool(task and task.terminal))
        value['core'].update(state=self.state,uptime_seconds=round(time.monotonic()-self.started,3),
                             pending=self.commands.qsize(),model_busy=self.model_pending)
        for row in value['adapters'].values():
            if 'age_seconds' in row:
                row['age_seconds']=round(row['age_seconds']+delta,3)
                if row['state']=='connected' and row['age_seconds']>self.heartbeat_seconds:row['state']='stale'
        path=self.root/'control-refusals.jsonl'
        refusals=[]
        if path.exists():
            with path.open('rb') as handle:
                handle.seek(0,2);handle.seek(max(0,handle.tell()-65536))
                for line in handle.read(65536).splitlines():
                    try:refusals.append(json.loads(line))
                    except ValueError:continue
        value['control_refusals']=refusals[-50:]
        return value

    def _open_journal(self):
        path = self.root / 'core.sqlite3'
        if path.exists():
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                if dict(db.execute('SELECT key,value FROM metadata')) != {'kind': 'gregory.core.prototype.v2', 'owner': self.owner}:
                    raise ValueError('wrong Core database/owner')
        db = sqlite3.connect(path, timeout=2)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        db.executescript('''CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS profile(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE,
              occurred REAL,run_id TEXT,kind TEXT,source TEXT,fixture INTEGER,origin TEXT,
              correlation_id TEXT,payload TEXT);
            CREATE INDEX IF NOT EXISTS events_correlation ON events(correlation_id,seq);
            CREATE TABLE IF NOT EXISTS command_results(seq INTEGER PRIMARY KEY AUTOINCREMENT,
              command_id TEXT UNIQUE,action TEXT,status TEXT,result_sha256 TEXT,occurred REAL);''')
        with db:
            db.executemany('INSERT OR IGNORE INTO metadata VALUES(?,?)',
                           [('kind', 'gregory.core.prototype.v2'), ('owner', self.owner)])
            profile = dict(character_id=str(uuid.uuid4()), name='Gregory',
                           persona='A curious, persistent AI character. One Gregory. Multiple worlds.', goals=[])
            db.execute('INSERT OR IGNORE INTO profile VALUES(1,?)', (json.dumps(profile),))
            from gregory_core.gmod_recording import initialize
            initialize(db)
            from gregory_core.conversation import initialize as initialize_conversation
            initialize_conversation(db)
            from gregory_core.inbox import initialize as initialize_inbox
            initialize_inbox(db)
        return db

    def _event(self, kind, payload, *, source='core', fixture=False):
        if kind not in KINDS:
            raise ValueError('explicit event category required')
        payload = bounded(payload)
        with self.db:
            self.db.execute('INSERT INTO events(id,occurred,run_id,kind,source,fixture,origin,correlation_id,payload) VALUES(?,?,?,?,?,?,?,?,?)',
                (str(uuid.uuid4()), time.time(), self.run_id, kind, source, int(fixture),
                 'fixture' if fixture else source,self.command_context,json.dumps(payload)))

    def _result(self, cid, action, status, result):
        with self.db:
            cursor=self.db.execute('INSERT INTO command_results(command_id,action,status,result_sha256,occurred) VALUES(?,?,?,?,?)',
                (cid,action,status,hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest(),time.time()))
        return dict(sequence=cursor.lastrowid,command_id=cid,status=status)

    def memory_context(self, scope, *, limit=3):
        """Called on the Core writer; scope is a trusted Discord source tuple."""
        if self.overview_scope is None:
            return dict(state='unavailable',reason='overview_scope_unbound')
        if not isinstance(scope,(tuple,list)) or tuple(scope)!=self.overview_scope:
            return dict(state='forbidden',reason='participant_scope_refused')
        result=self.memory.overview(actor=self.owner,limit=limit)
        self._event('memory',dict(operation='overview',mode='overview',
            memory_count=result['memory_count'],memory_ids=[h['memory_id'] for h in result['hits']],
            truncated=result['truncated'],historical_only=True))
        return result

    def _profile(self):
        return json.loads(self.db.execute('SELECT value FROM profile WHERE id=1').fetchone()[0])

    def _model_count(self, fixture):
        # New rows carry an explicit request type. Preserve older prototype
        # rows via their exact phase field, without rewriting journal history.
        return self.db.execute("""SELECT COUNT(*) FROM events WHERE kind='model' AND fixture=? AND
            (json_extract(payload,'$.type')='model.request' OR
             (json_type(payload,'$.type') IS NULL AND json_extract(payload,'$.phase')='requested'))""",
            (int(fixture),)).fetchone()[0]

    def _status(self):
        now = time.monotonic()
        adapters = {}
        for kind in ('game', 'voice'):
            row = self.adapters.get(kind)
            adapters[kind] = ({**row, 'age_seconds': round(now-row['heartbeat'], 3),
                'state': ('connected' if now-row['heartbeat'] <= self.heartbeat_seconds else 'stale')
                if row['connected'] else 'disconnected'} if row else {'state': 'not-connected'})
            adapters[kind].pop('heartbeat', None)
        events = [dict(row, payload=json.loads(row['payload']), fixture=bool(row['fixture']))
                  for row in self.db.execute('SELECT * FROM events ORDER BY seq DESC LIMIT 100')]
        return dict(profile=self._profile(), core=dict(pid=os.getpid(), run_id=self.run_id,
            core_instance_id=self.run_id,
            state=self.state, uptime_seconds=round(now-self.started, 3), pending=self.commands.qsize(),
            completed=self.completed, journal='committed', mode='isolated-prototype',
            last_ingest_sequence=self.db.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]), adapters=adapters,
            provider=self.provider.name if self.provider else 'not-connected', events=events,
            embedding=dict(connected=self.embedder is not None,
                space_key=(self.embedder.space.key if self.embedder is not None else None),
                vector_count=self.memory.db.execute('SELECT COUNT(*) FROM vectors').fetchone()[0]),
            model_counts={'live':self._model_count(False),'fixture':self._model_count(True)},
            live_state_available=False, memory_count=self.memory.db.execute('SELECT COUNT(*) FROM memories').fetchone()[0],
            _snapshot_mono=now,
            limits=['No live voice/game wiring or action dispatcher', 'Dashboard is read-only',
                    'Fixture origin is not live evidence', 'Loopback is not an OS user isolation boundary'])

    def _adapter(self, p):
        if set(p) - {'kind', 'session', 'event', 'pid', 'fixture', 'category', 'data', 'observed_at','correlation_id','executor',
                     'recording', 'page', 'origin', 'seen_at'}:
            raise ValueError('unknown adapter fields')
        kind, session, event = p['kind'], p['session'], p['event']
        if kind not in ('game', 'voice') or not isinstance(session, str) or not 1 <= len(session) <= 100:
            raise ValueError('bounded adapter kind/session required')
        row = self.adapters.get(kind)
        if event == 'connect':
            if row and row['session'] == session:
                raise ValueError('restart requires a new session')
            recording = None
            if 'recording' in p:
                from gregory_core.gmod_recording import binding
                if kind != 'game': raise ValueError('Recorder binding requires game adapter')
                recording = binding(p['recording'])
            self.adapters[kind] = dict(session=session, pid_reported=p.get('pid'), fixture=p.get('fixture') is True,
                                       recording=recording,
                                       connected=True, heartbeat=time.monotonic())
            self._event('lifecycle', {'adapter': kind, 'session': session, 'event': 'connect'},
                        source=kind, fixture=p.get('fixture') is True)
        else:
            if not row or row['session'] != session or not row['connected']:
                raise ValueError('old/disconnected adapter session')
            if event == 'disconnect':
                row['connected'] = False
                self._event('lifecycle', {'adapter': kind, 'session': session, 'event': 'disconnect'},
                            source=kind, fixture=row['fixture'])
            elif event == 'heartbeat':
                row['heartbeat'] = time.monotonic()
            elif event == 'recorded_batch':
                from gregory_core.gmod_recording import ingest, RecordingRefused
                if not row.get('recording'):
                    raise RecordingRefused('explicit_recording_binding_required')
                result = ingest(self.db, p['page'], row['recording'], origin=p['origin'], seen_at=p['seen_at'],
                    now=time.time(), freshness_seconds=self.freshness_seconds, core_run_id=self.run_id,
                    adapter_session=session, fixture=row['fixture'])
                row['recording_status'] = dict(availability='readable at last batch',
                    seen_at=p['seen_at'], origin=p['origin'], game_liveness='not established by adapter heartbeat')
                return result
            elif event == 'event':
                category = p['category']
                if category not in {'observation', 'inference', 'decision', 'outcome', 'error'}:
                    raise ValueError('adapter cannot publish memory/identity/lifecycle as fact')
                if category=='outcome' and not p.get('executor'):
                    raise ValueError('outcome requires an explicit executor identity')
                if category == 'observation' and (not isinstance(p.get('observed_at'), (float, int)) or
                    not 0 <= time.time()-p['observed_at'] <= self.freshness_seconds):
                    raise ValueError('stale/future observation')
                self._event(category, dict(adapter_session=session, report=p.get('data'),
                    executor=p.get('executor'),
                    qualification='adapter report; not automatically Recorder evidence'),
                    source=kind, fixture=row['fixture'])
            else:
                raise ValueError('unknown adapter event')
        return {'accepted': True, 'observation_promoted_to_current': False}

    def _execute(self, action, p):
        if action == 'pin_inbox':
            from gregory_core.inbox_pins import execute
            return execute(self, p)
        if action == 'inbox':
            from gregory_core.inbox import execute
            return execute(self, p)
        if action == 'conversation':
            from gregory_core.conversation import execute
            return execute(self,p)
        if action == 'status':
            return self._status()
        if action == 'audit_refusal':
            self._event('error',dict(type='capability_refused',actor=p['actor'],scope=p['scope']))
            return {'refused':True,'type':'capability_refused'}
        if action == 'correlation':
            uuid.UUID(p['correlation_id'])
            return {'events':[dict(r,payload=json.loads(r['payload'])) for r in self.db.execute(
                'SELECT * FROM events WHERE correlation_id=? ORDER BY seq',(p['correlation_id'],))]}
        if action == 'adapter':
            return self._adapter(p)
        if action == 'persona':
            if set(p) != {'persona'} or not isinstance(p['persona'], str) or not 1 <= len(p['persona']) <= 8192:
                raise ValueError('bounded explicit owner persona required')
            profile = self._profile(); previous = profile['persona']; profile['persona'] = p['persona']
            with self.db:
                self.db.execute('UPDATE profile SET value=? WHERE id=1', (json.dumps(profile),))
                self._event('decision', dict(type='owner_persona_configuration',
                    previous_sha256=hashlib.sha256(previous.encode()).hexdigest(),
                    persona_sha256=hashlib.sha256(p['persona'].encode()).hexdigest()), source='owner')
            return profile
        if action == 'goals':
            goals = p['goals']
            if not isinstance(goals, list) or len(goals)>10 or any(not isinstance(g,str) or not 1<=len(g)<=200 for g in goals):
                raise ValueError('bounded owner goals required')
            profile = self._profile(); profile['goals'] = goals
            with self.db:
                self.db.execute('UPDATE profile SET value=? WHERE id=1', (json.dumps(profile),))
                self._event('decision', {'owner_goals': goals, 'dispatched': False}, source='owner')
            return profile
        if action == 'import':
            if len(p['events']) > 512:
                raise ValueError('bounded canonical experience batch required')
            self.memory.ingest(p['events'], actor=self.owner, source_label=p['source_label'])
            mid = self.memory.consolidate(p['run_id'], p['correlation_id'], actor=self.owner, domain=p['domain'])
            if self.embedder is not None:
                # Optional lane: a failed embedding must never remove the episode.
                try:
                    self.memory.index(mid, self.embedder, actor=self.owner)
                except Exception as exc:
                    self._event('error', {'type': 'embedding.failed', 'stage': 'consolidate',
                        'memory_id': mid, 'error_category': type(exc).__name__}, source='core')
            row = self.memory.inspect(mid, actor=self.owner)
            self._event('observation',{'phase':'historical Recorder evidence import; not current observation',
                'actor':self.owner,'correlation_id':p['correlation_id'],'source_label':p['source_label'],
                'evidence_ids':[e['event_id'] for e in p['events'] if e['event_type']=='observation.accepted']},
                source='recorder',fixture=p['source_label'].startswith('fixture'))
            self._event('memory', {'operation': 'consolidate', 'memory_id': mid,
                'evidence_ids': [e['event_id'] for e in row['evidence']],
                'historical_only': row['historical_only'], 'current_world_state': row['current_world_state']},
                fixture=p['source_label'].startswith('fixture'))
            return {'memory_id': mid, 'historical_only': row['historical_only'],
                    'current_world_state': row['current_world_state']}
        if action == 'reembed':
            if self.embedder is None:
                raise ValueError('no local embedder connected')
            result = self.memory.backfill(self.embedder, actor=self.owner, limit=p.get('limit', 200))
            self._event('memory', {'operation': 'reembed', 'space_key': result['space_key'],
                'candidates': result['candidates'], 'indexed': result['indexed'],
                'failed': [f['memory_id'] for f in result['failed']]}, source='core')
            return result
        if action == 'lookup':
            scope=p.get('conversation_scope')
            if self.overview_scope is not None and scope is not None and tuple(scope)!=self.overview_scope:
                raise PermissionError('conversation memory scope refused')
            if p.get('operation')=='overview':
                return self.memory_context(scope,limit=p.get('limit',3))
            if 'memory_id' in p:
                row=self.memory.inspect(p['memory_id'],actor=self.owner)
                if row is not None:
                    result=dict(hits=[row] if not row['expired'] else [],mode='exact-id',
                        historical_only=row['historical_only'],current_world_state=row['current_world_state'])
                else:
                    # Obtain even the empty-result envelope from MemoryStore,
                    # rather than inventing/masking its history/state contract.
                    result=self.memory.search('',actor=self.owner,embedder=None,limit=1)
                    if result['hits']:raise ValueError('empty memory query returned content')
                    result['mode']='exact-id'
            else:
                result = self.memory.search(p['query'], actor=self.owner, embedder=self.embedder, limit=5,
                                            min_similarity=p.get('min_similarity'))
            fixture_ids = [h['memory_id'] for h in result['hits'] if any(
                e['source_label'].startswith('fixture') for e in h['evidence'])]
            for hit in result['hits']:
                hit['origin'] = 'fixture' if hit['memory_id'] in fixture_ids else 'recorder'
            # Retrieval context only: lets a caller decide whether a rewrite is
            # worth a model call, without inventing a hit on an empty store.
            result['memory_count'] = self.memory.db.execute('SELECT COUNT(*) FROM memories').fetchone()[0]
            self._event('memory', {'operation': 'lookup', **({'query_sha256':hashlib.sha256(p.get('query','').encode()).hexdigest()} if p.get('metadata_only') else {'query':p.get('query')}),
                'memory_ids': [h['memory_id'] for h in result['hits']],
                'mode':result['mode'],'warnings':result.get('warnings',[]),
                'retrieval_channels':{h['memory_id']:h.get('retrieval_channels',[]) for h in result['hits']},
                'retrieval_scores':{h['memory_id']:h.get('retrieval_score') for h in result['hits']},
                'historical_only': result['historical_only'], 'current_world_state': result['current_world_state'],
                'fixture_memory_ids': fixture_ids}, fixture=bool(fixture_ids))
            return result
        if action == 'think':
            if self.provider is None:
                raise ValueError('no model provider connected')
            prompt = p['prompt']
            inbox_ids = None
            inbox_images, inbox_media = [], []
            inbox_surface = 'dm'
            if 'inbox_voice_claim' in p:
                if 'inbox_scope' in p:
                    raise PermissionError('ambiguous inbox surface')
                from gregory_core.inbox import voice_scope
                scope = voice_scope(self, p['inbox_voice_claim'])
                p = dict(p, inbox_scope=scope)
                inbox_surface = 'vc'
            if 'inbox_scope' in p:
                from gregory_core.inbox import turn_context
                prompt, inbox_ids = turn_context(self, p['inbox_scope'], prompt,
                    max_messages=24 if inbox_surface=='dm' else 8,
                    record_budget=10000 if inbox_surface=='dm' else 3400)
                if inbox_surface == 'vc':
                    prompt = ('AUTHORIZED ONE-TURN VC DISCLOSURE: The authenticated sender explicitly asked '
                              'to discuss their own DMs in this shared call. Reply in one or two short '
                              'sentences, normally at most 35 words. This permission expires after this turn; '
                              'do not announce or reuse private content on later turns.\n' + prompt)
                from gregory_core.inbox_media import images_for_turn
                inbox_images, inbox_media = images_for_turn(self, p['inbox_scope'])
                if inbox_media:
                    prompt += '\nPrivate DM image attachment previews (GIF frames are samples, not the whole animation): '+json.dumps(inbox_media)
                else:
                    prompt += '\nIMAGE STATUS: No validated image previews are supplied on this turn. Do not describe an image from its filename, URL, hash or prior model guesses.'
                p = dict(p, metadata_only=True, memory_evidence_ids=[])
            prompt_limit = 14000 if inbox_ids is not None and inbox_surface=='dm' else 6000
            if not isinstance(prompt,str) or not 1<=len(prompt)<=prompt_limit:
                raise ValueError('bounded prompt required')
            seconds=p.get('deadline_seconds',30)
            if type(seconds) not in (float,int) or not 0 < seconds <= 60:
                raise ValueError('bounded model deadline required')
            seconds=p['_model_deadline']-time.monotonic()
            if seconds<=0:raise TimeoutError('model deadline expired before start')
            evidence_ids=p.get('memory_evidence_ids',[])
            if (not isinstance(evidence_ids,list) or len(evidence_ids)>3 or
                any(not isinstance(v,str) or len(v)>80 for v in evidence_ids)):
                raise ValueError('bounded supplied memory IDs required')
            self._event('model', {'type':'model.request','phase':'requested','provider':self.provider.name,
                'memory_evidence_ids':evidence_ids,
                **({'inbox_message_ids':inbox_ids,'inbox_media':inbox_media,'surface':inbox_surface} if inbox_ids is not None else {}),
                'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}, fixture=self.provider.fixture)
            screen_session=p.get('screen_session')
            if screen_session is not None:
                if (self.screen_source is None or screen_session!=self.screen_source.session
                        or inbox_ids is not None):
                    raise ValueError('screen tool requires explicit game session without private inbox context')
            if p.get('screen_game_tasks',False) is not False and (p.get('screen_game_tasks') is not True or screen_session is None):
                raise ValueError('screen game proposals require explicit screen session')
            response_schema=p.get('response_schema')
            if response_schema is not None and (not isinstance(response_schema,dict) or len(json.dumps(response_schema))>32768 or inbox_ids is not None):
                raise ValueError('bounded game decision schema without private inbox required')
            task=ModelTask(self.provider,self._profile(),prompt,seconds,images=inbox_images,
                screen_source=self.screen_source if screen_session is not None else None,
                screen_session=screen_session,absolute_deadline=p['_model_deadline'],
                screen_game_tasks=p.get('screen_game_tasks',False),response_schema=response_schema)
            task.metadata_only=p.get('metadata_only',False)
            task.private_inbox = inbox_ids is not None
            task.memory_evidence_ids=evidence_ids
            task.citation_contract='memory_evidence_ids' in p
            self.model_task=task
            return task
        raise ValueError('unknown command')

    def _poll_model(self, *, stopping=False):
        task=self.model_task
        if task is None:return
        delivery=None
        saved=self.command_context
        self.command_context=task.correlation
        try:
            if not task.terminal and (stopping or time.monotonic()>=task.deadline):
                error=TimeoutError('Core model deadline expired' if not stopping else 'Core stopped model turn')
                self._event('error',{'type':'model.cancelled' if stopping else 'model.timed_out',
                    'command':'think','provider':self.provider.name},fixture=self.provider.fixture)
                self._result(task.cid,'think','cancelled' if stopping else 'timed_out',{'error':type(error).__name__})
                task.terminal=True
                if not task.future.done():task.future.set_exception(error)
            try: success,result=task.output.get_nowait()
            except queue.Empty:return
            if task.terminal:
                self._event('model',{'type':'model.late_discarded','provider':self.provider.name},fixture=self.provider.fixture)
            else:
                try:
                    for receipt in getattr(task,'screen_receipts',[]):
                        self._event('observation',dict(type='screen.tool_result',**receipt),fixture=self.provider.fixture)
                    if not success:raise result
                    result=bounded(result,2400)
                    if not isinstance(result,dict) or set(result)-{'say','intent','used_memory_ids'}:
                        raise ValueError('dialogue/intent result required')
                    if getattr(task,'private_inbox',False):
                        result = dict(result)
                        result.pop('intent',None)
                    used=result.get('used_memory_ids',[])
                    valid=(isinstance(used,list) and len(used)<=3 and
                        all(isinstance(v,str) and v in task.memory_evidence_ids for v in used) and
                        len(used)==len(set(used)))
                    verdict=('valid' if 'used_memory_ids' in result else 'undeclared') if valid else 'invalid'
                    if task.citation_contract or 'used_memory_ids' in result:
                        self._event('memory',dict(operation='citation_verdict',verdict=verdict,
                            supplied_memory_ids=task.memory_evidence_ids,
                            declared_memory_ids=used if isinstance(used,list) and len(used)<=3 and
                                all(isinstance(v,str) and len(v)<=80 for v in used) else [],
                            used_memory_ids=used if valid else [],
                            error_category=None if valid else 'MemoryCitationError'),fixture=self.provider.fixture)
                    if not valid:raise MemoryCitationError('citation outside supplied historical evidence')
                    self._event('model',{'type':'model.response','phase':'returned','provider':self.provider.name,
                        'latency_ms':round((time.monotonic()-task.started)*1000,2)},fixture=self.provider.fixture)
                    say=result.get('say')
                    inference=({'say_sha256':hashlib.sha256(str(say).encode()).hexdigest()} if task.metadata_only else {'say':say})
                    inference.update(used_memory_ids=used,citation_verdict=verdict)
                    self._event('inference',dict(inference,qualification='model output; not a world observation'),fixture=self.provider.fixture)
                    decision=({'intent_discarded':True} if task.metadata_only else {'intent':result.get('intent')})
                    self._event('decision',dict(decision,dispatched=False),fixture=self.provider.fixture)
                    answer=dict(result,citation_verdict=verdict,dispatched=False,fixture=self.provider.fixture)
                    if task.screen_receipts:answer['screen_observations']=list(task.screen_receipts)
                    answer['_result']=self._result(task.cid,'think','committed',answer)
                    self.completed+=1
                    delivery=(True,answer)
                except Exception as exc:
                    self._event('error',{'command':'think','error_category':type(exc).__name__},fixture=self.provider.fixture)
                    self._result(task.cid,'think','failed',{'error':type(exc).__name__})
                    delivery=(False,exc)
        finally:
            self.command_context=saved
            self.cached_status=self._status()
        self.model_task=None
        with self.admission:self.model_pending=False
        if delivery is not None and not task.future.done():
            if delivery[0]:task.future.set_result(delivery[1])
            else:task.future.set_exception(delivery[1])

    def _run(self):
        stop_future = None
        current = None
        failures = []
        degraded = None
        inflight = None
        task_active = False
        self.db = self.memory = None
        try:
            with writer_lock(self.root/'core.writer.lock'):
                self.db = self._open_journal()
                self.memory = MemoryStore(self.root/'episodes.sqlite3', owner_id=self.owner, retention_seconds=604800)
                self._event('lifecycle', {'event':'core_started','pid':os.getpid()})
                self.state, self.accepting = 'running', True
                self.cached_status=self._status()
                self.ready.set()
                while True:
                    self._poll_model()
                    try:cid, action, payload, current = self.commands.get(timeout=.02)
                    except queue.Empty:continue
                    inflight = (cid,action,current)
                    task_active = True
                    self.command_context=payload.get('correlation_id')
                    if action == 'stop':
                        self.state='stopping'
                        self._poll_model(stopping=True)
                        transport_pending=bool(self.model_task and self.model_task.thread.is_alive())
                        self._event('lifecycle', {'event':'owner_stop_drained','completed':self.completed,
                            'model_transport_pending':transport_pending,'fully_drained':not transport_pending})
                        stop_result=self._result(cid,action,'committed',{'stopped':True})
                        stop_future=current
                        self.commands.task_done()
                        task_active = False
                        inflight = None
                        break
                    try:
                        if self.command_context is not None:
                            uuid.UUID(self.command_context)
                        result=self._execute(action,payload)
                        if isinstance(result,ModelTask):
                            result.cid,result.future,result.correlation=cid,current,self.command_context
                            current=None
                            inflight=None
                            continue
                        self.completed+=1
                        result['_result']=self._result(cid,action,'committed',result)
                        self.cached_status=self._status()
                        current.set_result(result)
                    except Exception as exc:
                        self._event('error', {'command':action,'error_category':type(exc).__name__,
                            'detail':str(exc)[:300],'correlation_id':cid})
                        self._result(cid,action,'failed',{'error':type(exc).__name__})
                        self.cached_status=self._status()
                        current.set_exception(exc)
                    finally:
                        if action == 'think' and self.model_task is None:
                            with self.admission:
                                self.model_pending=False
                        self.commands.task_done()
                        task_active = False
                    inflight = None
                self.memory.close(); self.memory=None
                self.db.close(); self.db=None
            self.state='stopped'
            stop_future.set_result({'stopped':True,'databases_closed':True,'completed':self.completed,
                'model_transport_pending':transport_pending,'fully_drained':not transport_pending,'_result':stop_result})
        except Exception as exc:
            self.failure=type(exc).__name__+': '+str(exc)
            self.state='failed'
            if self.model_task is not None and not self.model_task.future.done():
                failures.append((self.model_task.cid,'think',self.model_task.future))
            if inflight is not None and inflight[2] is not None:
                failures.append(inflight)
            elif stop_future is not None and not stop_future.done():
                failures.append((cid,'stop',stop_future))
            if task_active:
                self.commands.task_done()
            with self.admission:
                self.accepting=False
                while not self.commands.empty():
                    cid, action, _, future=self.commands.get_nowait()
                    failures.append((cid,action,future))
                    self.commands.task_done()
            degraded = dict(type='core_degraded',state='failed',failure=self.failure,
                run_id=self.run_id,exit_code=1,fully_drained=False,
                uncommitted_commands=[dict(id=c,action=a) for c,a,_ in failures],
                note='No durable command result; partial effects may exist. Inspect stores before retry.')
            # Closed/locked SQLite cannot be the only destination for this report.
            with self.failure_path.open('w',encoding='utf8') as handle:
                json.dump(degraded,handle);handle.flush();os.fsync(handle.fileno())
        finally:
            self.dialogue.clear()
            if self.memory is not None: self.memory.close()
            if self.db is not None: self.db.close()
            self.accepting=False
            # Completion follows writer-lock release and database close, including
            # the degraded path; clients must not race a still-owned writer lock.
            for _,_,future in failures:
                if not future.done():future.set_exception(CoreDegraded(degraded))
            self.ready.set(); self.finished.set()
