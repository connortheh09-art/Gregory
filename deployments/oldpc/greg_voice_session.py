"""Narrow trusted-bot transport, not a model/action endpoint. No audio imports."""
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import re
import secrets
import socket
import threading
import time
import uuid


class VoiceRefused(ValueError):
    pass


from greg_voice_protocol import stop_text, inbox_text


class VoiceSession:
    """HTTP threads only enqueue; the bridge remains the only controller writer.

    Capability holders are trusted voice adapters. Discord speaker attribution
    must come from authenticated receive events, never from transcript wording.
    """
    def __init__(self, config, steamid, *, clock=time.time, log=lambda s: None, recorder=None):
        required = {'owner_id', 'guild_id', 'channel_id', 'game_name'}
        if set(config) != required or any(not re.fullmatch(r'[0-9]{1,20}', config[k])
                                         for k in ('owner_id','guild_id','channel_id')):
            raise VoiceRefused('explicit voice scope required')
        if not isinstance(config['game_name'], str) or not 1 <= len(config['game_name']) <= 80:
            raise VoiceRefused('explicit game nickname required')
        if not re.fullmatch(r'STEAM_[0-5]:[01]:[0-9]+', steamid):
            raise VoiceRefused('explicit Steam mapping required')
        self.config, self.steamid, self.clock, self.log = dict(config), steamid, clock, log
        self.recorder, self.receipts = recorder, deque(maxlen=32)
        self.lock = threading.RLock()
        self.closed = False
        self.connection, self.generation, self.seen_at = None, 0, 0
        self.turns, self.replies = deque(), deque()
        self.seen, self.playbacks, self.issued = {}, {}, {}
        self.inbox_grants = {}
        self.draining = False

    def begin_drain(self):
        with self.lock:
            self.draining = True

    @property
    def pending_playback(self):
        with self.lock:
            return len(self.playbacks) if self._live() else 0

    def _advance(self):
        self.generation += 1
        self.turns.clear(); self.replies.clear(); self.playbacks.clear(); self.issued.clear()
        self.inbox_grants.clear()

    def authorize_inbox(self, metadata, text):
        with self.lock:
            if (not inbox_text(text) or metadata.get('author_id') != self.config['owner_id'] or
                    any(metadata.get(k) != self.config[k] for k in ('guild_id', 'channel_id')) or
                    (metadata.get('connection'), metadata.get('generation')) != self.stamp() or
                    not 0 <= self.clock()-metadata.get('captured_at', 0) <= 20):
                return None
            claim = secrets.token_urlsafe(32)
            self.inbox_grants[claim] = dict(metadata)
            if len(self.inbox_grants) > 4:
                self.inbox_grants.pop(next(iter(self.inbox_grants)))
            return claim

    def consume_inbox(self, claim):
        with self.lock:
            metadata = self.inbox_grants.pop(claim, None)
            if (metadata is None or self.closed or
                    (metadata['connection'], metadata['generation']) != self.stamp() or
                    not 0 <= self.clock()-metadata['captured_at'] <= 20):
                raise PermissionError('voice inbox grant expired or invalid')
            return metadata

    def invalidate(self):
        with self.lock:
            self._advance()

    def _live(self):
        if self.connection and not 0 <= self.clock()-self.seen_at <= 10:
            self.connection = None; self._advance()
        return self.connection is not None

    def stamp(self):
        with self.lock:
            return (self.connection, self.generation) if self._live() else None

    def _scope(self, data):
        if (not self._live() or data.get('connection') != self.connection or
                data.get('generation') != self.generation):
            raise VoiceRefused('voice connection changed or expired')

    def call(self, operation, data):
        with self.lock:
            if self.closed: raise VoiceRefused('voice host closed')
            if operation == 'connect':
                if set(data) != {'guild_id','channel_id'} or any(
                    data.get(k) != self.config[k] for k in ('guild_id','channel_id')):
                    raise VoiceRefused('voice channel refused')
                self._advance(); self.seen.clear()
                self.connection = str(uuid.uuid4()); self.seen_at = self.clock()
            else:
                if operation == 'poll' or (operation == 'turn' and
                        isinstance(data.get('text'),str) and stop_text(data['text'])):
                    if not self._live() or data.get('connection') != self.connection:
                        raise VoiceRefused('voice connection changed or expired')
                else:
                    self._scope(data)
                # Valid polling/requests renew the lease, not arbitrary traffic.
                self.seen_at = self.clock()
                if operation == 'interrupt':
                    self._advance()  # audio/reply cancellation only; never a movement directive
                elif operation == 'disconnect':
                    self.connection = None; self._advance()
                elif operation == 'turn':
                    if set(data) != {'connection','generation','request_id','author_id','is_bot','text','captured_at'}:
                        raise VoiceRefused('voice turn schema refused')
                    if data['author_id'] != self.config['owner_id'] or data['is_bot'] is not False:
                        raise VoiceRefused('voice author refused')
                    if self.draining and not stop_text(data.get('text')):
                        raise VoiceRefused('voice admission closed; draining playback')
                    text, captured = data['text'], data['captured_at']
                    if (not isinstance(text,str) or not 1 <= len(text.strip()) <= 1000 or
                            type(captured) not in (int,float) or not 0 <= self.clock()-captured <= 20):
                        raise VoiceRefused('voice text/capture age refused')
                    try: uuid.UUID(data['request_id'])
                    except (ValueError,TypeError,AttributeError): raise VoiceRefused('request ID refused')
                    fingerprint = hashlib.sha256(json.dumps([data['author_id'],text,captured]).encode()).hexdigest()
                    if data['request_id'] in self.seen:
                        if self.seen[data['request_id']] != fingerprint:
                            raise VoiceRefused('request ID conflict')
                        return dict(connection=self.connection,generation=self.generation,duplicate=True,server_time=self.clock())
                    if stop_text(text):
                        self._advance()  # drop old audio immediately; controller stop is queued next tick
                    elif len(self.turns) >= 2:
                        self.turns.popleft()
                    self.seen[data['request_id']] = fingerprint
                    if len(self.seen) > 128: self.seen.pop(next(iter(self.seen)))
                    self.turns.append(dict(request_id=data['request_id'],text=text.strip(),captured_at=captured))
                    self.log('VOICE_TURN_ADMITTED '+json.dumps(dict(request_id=data['request_id'],
                        author_id=data['author_id'],guild_id=self.config['guild_id'],
                        channel_id=self.config['channel_id'],connection=self.connection,
                        generation=self.generation,captured_at=captured)))
                elif operation == 'poll':
                    replies = list(self.replies); self.replies.clear()
                    return dict(connection=self.connection,generation=self.generation,replies=replies,server_time=self.clock())
                elif operation == 'playback':
                    key = data.get('reply_id'); state = data.get('state')
                    if key not in self.playbacks or state not in {'started','completed','cancelled','failed','timeout'}:
                        raise VoiceRefused('playback receipt refused')
                    previous = self.playbacks[key]['state']
                    if state not in ({'started','cancelled','failed'} if previous == 'queued' else
                                     {'completed','cancelled','failed','timeout'} if previous == 'started' else set()):
                        raise VoiceRefused('playback transition refused')
                    if len(self.receipts)==self.receipts.maxlen:
                        raise VoiceRefused('playback receipt intake full')
                    self.playbacks[key]['state'] = state
                    self.receipts.append((self.playbacks[key]['trace'],dict(kind='discord_voice',
                        status=state,id=key,bridgeSession=self.connection,version=str(self.generation),
                        reason='adapter_report_not_listener_ack')))
                    self.log('VOICE_PLAYBACK ' + json.dumps(dict(reply_id=key,state=state,
                        connection=self.connection,generation=self.generation,
                        correlation_id=self.playbacks[key]['correlation_id'],
                        qualification='adapter report, not proof another participant heard audio')))
                    if state in {'completed','cancelled','failed','timeout'}: del self.playbacks[key]
                else:
                    raise VoiceRefused('unknown voice operation')
            return dict(connection=self.connection,generation=self.generation,server_time=self.clock())

    def drain(self):
        with self.lock:
            self.flush_receipts()
            if not self._live(): return []
            rows = [r for r in self.turns if 0 <= self.clock()-r['captured_at'] <= 20]
            self.turns.clear()
            result=[]
            for row in rows:
                claim=secrets.token_urlsafe(16)
                rec=dict(user=self.config['game_name'],steamid=self.steamid,msg=('stop' if stop_text(row['text']) else row['text']),
                         t=row['captured_at'],voice_claim=claim)
                metadata=dict(author_id=self.config['owner_id'],guild_id=self.config['guild_id'],
                    channel_id=self.config['channel_id'],connection=self.connection,
                    generation=self.generation,request_id=row['request_id'],captured_at=row['captured_at'])
                self.issued[claim]=(dict(rec),metadata)
                if len(self.issued)>8:self.issued.pop(next(iter(self.issued)))
                result.append(rec)
            return result

    def claim(self,rec):
        with self.lock:
            item=self.issued.pop(rec.get('voice_claim'),None)
            return item[1] if item and rec==item[0] else None

    def flush_receipts(self):
        with self.lock:
            while self.receipts:
                trace,payload=self.receipts.popleft()
                if self.recorder is not None:
                    event=self.recorder.record('voice.playback',payload,trace=trace,priority='critical')
                    if event is None:self.log('VOICE_RECEIPT_UNRECORDED recorder_unavailable')

    def offer(self, row):
        with self.lock:
            stamp = self.stamp()
            reason = ('delivery_stamp_changed' if row['request'].get('delivery_stamp') != stamp
                else 'voice_not_live' if not self._live()
                else 'reply_queue_full' if len(self.replies) >= 4
                else 'playback_budget_full' if len(self.playbacks) >= 8 else None)
            if reason:
                self.log('VOICE_REPLY_REFUSED '+json.dumps(dict(reason=reason,
                    request_id=(row['request'].get('voice_metadata') or {}).get('request_id'))))
                return False
            key = str(uuid.uuid4())
            self.replies.append(dict(reply_id=key,text=row['say']))
            trace=row['request'].get('trace')
            self.playbacks[key] = dict(state='queued',trace=trace,correlation_id=(trace.correlation_id if trace else None))
            self.log('VOICE_REPLY_QUEUED ' + json.dumps(dict(reply_id=key,
                correlation_id=self.playbacks[key]['correlation_id'],
                qualification='not spoken until playback receipt')))
            return True


class VoiceTail:
    """Wrap existing file-chat intake; no action/command writer is introduced."""
    def __init__(self, tail, voice): self.tail, self.voice = tail, voice
    def read_new(self):
        return list(self.tail.read_new()) + [json.dumps(row) for row in self.voice.drain()]


class VoiceServer:
    """Loopback only. Never reuse the broader Core owner capability."""
    def __init__(self, session, *, port=0):
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('valid voice port required')
        self.session, self.capability = session, secrets.token_urlsafe(32)
        parent = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self,*args): pass
            def do_POST(self):
                result, status = {'error':'voice request refused'}, 403
                if (self.headers.get('Host') == '127.0.0.1:'+str(parent.port) and
                    secrets.compare_digest(self.headers.get('Authorization',''), 'Bearer '+parent.capability)):
                    try:
                        size=int(self.headers.get('Content-Length','0'))
                        if not 0 < size <= 8192: raise VoiceRefused('bounded body required')
                        self.connection.settimeout(2)
                        data=json.loads(self.rfile.read(size))
                        if not isinstance(data,dict): raise VoiceRefused('object required')
                        result=parent.session.call(self.path.removeprefix('/'),data);status=200
                    except (ValueError,TypeError,KeyError,TimeoutError) as exc:
                        operation=self.path.removeprefix('/')
                        if operation not in {'connect','turn','poll','playback','disconnect','interrupt'}:
                            operation='unknown'
                        parent.session.log('VOICE_HTTP_REFUSED '+json.dumps(dict(operation=operation,
                            reason=str(exc)[:120] if isinstance(exc,VoiceRefused) else type(exc).__name__)))
                self.close_connection = status != 200 or parent.session.closed
                body=json.dumps(result).encode();self.send_response(status)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
                if self.close_connection:self.send_header('Connection','close')
                self.end_headers();self.wfile.write(body)
        class ExclusiveVoiceServer(ThreadingHTTPServer):
            # Windows SO_REUSEADDR otherwise permits two live listeners on P.
            allow_reuse_address = not hasattr(socket, 'SO_EXCLUSIVEADDRUSE')
            def server_bind(self):
                if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                super().server_bind()
        self.server=ExclusiveVoiceServer(('127.0.0.1',port),Handler)
        self.server.daemon_threads=True
        self.port=self.server.server_address[1]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
    def start(self): self.thread.start();return self
    def receipt(self):
        return dict(url='http://127.0.0.1:'+str(self.port),capability=self.capability,
                    owner_id=self.session.config['owner_id'])
    def close_intake(self):
        with self.session.lock:
            self.session.closed=True
            self.session.connection=None;self.session._advance()
            self.session.flush_receipts()
    def close(self):
        self.close_intake()
        self.server.shutdown();self.server.server_close();self.thread.join(3)
