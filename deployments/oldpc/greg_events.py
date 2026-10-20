"""Versioned, bounded recorder contracts. No game, provider, or filesystem imports."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from itertools import islice
import json
import math
import re
import threading
import time
import uuid

SCHEMA_VERSION = 1
EVENT_TYPES = frozenset('''run.started run.heartbeat run.ended run.recovered
observation.accepted telemetry.gap telemetry.resumed telemetry.sequence_gap
decision.requested decision.response decision.parsed decision.applied decision.discarded decision.error
sensor.requested sensor.result sensor.error goal.observed route.observed
action.requested action.dispatch action.write_failed action.suppressed controller.feedback
outcome.evaluated experience.closed recorder.loss recorder.degraded recorder.recovered retention.expired'''.split())
_SCOPE = ContextVar('greg_recorder_trace', default=None)
_UNSAFE = re.compile(r'(?i)(?:<\s*/?\s*(?:think|analysis|reasoning)\b|\b(?:authorization|bearer|password|api[_ -]?key|token)\s*[:= ]|\bsk-[a-z0-9]{12,}|\bgh[pousr]_[a-z0-9]{12,}|-----BEGIN .*PRIVATE KEY|https?://)')
_TEXT = frozenset(('text', 'content', 'caption', 'reply', 'announcement', 'native_text', 'cmd'))
_STRINGS = frozenset('''action id kind source status reason origin lane template_version model returned_model
provider finish_reason parse_status write_status write_method mode native_route_id native_goal_id
command_session dispatch_id controller_version traversal evaluator closure_reason world_outcome verdict
coverage continuation_of related_to interaction bridgeSession map_name actor_id build_commit python_version
sqlite_version error_category record_state relation to_id to_kind observation_id pre_observation_id
goal_id action_id decision_id correlation_id source_instance_id version native_status label'''.split())
_NUMBERS = frozenset('''x y z radius duration lease hold taps yaw pitch turn throttle steer zoom t seq
serverTime controlEpoch control_epoch intent_version command_sequence expires retries latency_ms queue_ms
max_tokens temperature timeout captured_at age_seconds event cursor ttl set_at distance speed dwell_seconds
prompt_tokens completion_tokens total_tokens reasoning_tokens count first_sequence last_sequence skipped
last_state_seq last_cmd_seq last_state_age_seconds uptime_seconds normal_depth critical_depth committed
admitted dropped inflight errors last_commit_ns schema_version started_mono_ns clock_uncertainty_ms
time limit bytes_received bytes_retained total expired_count oldest_age_seconds remaining_points
gap_seconds window_seconds received_age max_context_length'''.split())
_BOOLS = frozenset('''enabled menu dead grounded fresh playercore stop walk sprint jump rescueEligible
parameters_complete content_omitted truncated json_valid accepted context_match complete assisted
owned timed_out recording_enabled loaded is_final addressed consent_granted'''.split())
_CONTAINERS = frozenset('''action pos target points locomotion rescue capabilities clearance nearby players
velocity ang eye usage settings parsed proposal control fields losses build files hashes observation_ids
context_refs evidence_ids criteria summary links health payload statistics spawns undos'''.split())


def new_id():
    return str(uuid.uuid4())


def utc(ns=None):
    return datetime.fromtimestamp((time.time_ns() if ns is None else ns) / 1e9,
                                  timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def alias(run_id, value):
    return hashlib.sha256((run_id + ':' + str(value)).encode()).hexdigest()[:24] if value else None


def safe_text(value, limit=2048):
    if not isinstance(value, str) or _UNSAFE.search(value):
        return None
    return value[:limit]


def sanitize(value, *, visible=False, depth=0, key=''):
    """Fail closed on unknown fields. All collections are bounded before encoding."""
    if depth > 8:
        return None
    if value is None:
        return None
    if isinstance(value, dict):
        result = {}
        for k, v in islice(value.items(), 64):
            if not isinstance(k, str):
                continue
            if k in _TEXT:
                cleaned = safe_text(v) if visible else None
                if cleaned is None:
                    result['content_omitted'] = True
                else:
                    result[k] = cleaned
                    if len(v) > len(cleaned): result['truncated'] = True
            elif k in _CONTAINERS and isinstance(v, (dict,list,tuple)):
                result[k] = sanitize(v, visible=visible, depth=depth+1, key=k)
            elif k in _NUMBERS:
                if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                    result[k] = v
            elif k in _BOOLS:
                if isinstance(v, bool): result[k] = v
            elif k in _STRINGS:
                cleaned = safe_text(v, 160)
                if cleaned is not None: result[k] = cleaned
            elif k in _CONTAINERS:
                result[k] = sanitize(v, visible=visible, depth=depth+1, key=k)
        return result
    if isinstance(value, (list, tuple)):
        cap = 256 if key == 'points' else 32 if key in {'observation_ids', 'evidence_ids', 'links'} else 12
        return [sanitize(v, visible=visible, depth=depth+1) for v in value[:cap]]
    if isinstance(value, bool): return value
    if isinstance(value, (float, int)):
        return value if math.isfinite(value) else None
    return safe_text(value, 160) if isinstance(value, str) else None


@dataclass(frozen=True)
class ControlContext:
    actor_id: str | None = None
    map_name: str | None = None
    bridge_session: str | None = None
    control_epoch: int | None = None
    intent_version: int | None = None

    @classmethod
    def from_state(cls, state, run_id, version=None):
        return cls(alias(run_id, state.get('steamid')), safe_text(state.get('map'), 160),
                   safe_text(state.get('bridgeSession'), 160), state.get('controlEpoch'), version)

    def as_dict(self):
        return dict(actor_id=self.actor_id, map_name=self.map_name,
                    bridge_session=self.bridge_session, control_epoch=self.control_epoch,
                    intent_version=self.intent_version)


@dataclass(frozen=True)
class TraceContext:
    run_id: str
    correlation_id: str | None
    decision_id: str | None = None
    goal_id: str | None = None
    action_id: str | None = None
    control: ControlContext = field(default_factory=ControlContext)
    observation_ids: tuple[str, ...] = ()
    lane: str = 'deterministic'
    template_version: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True)
class Event:
    encoded: str

    def as_dict(self):
        return json.loads(self.encoded)


class EventFactory:
    def __init__(self, run_id, session_id, *, text='metadata', clock=time.time_ns, mono=time.monotonic_ns):
        if text not in {'metadata', 'visible'}: raise ValueError('invalid recorder text policy')
        self.run_id, self.session_id, self.visible = run_id, session_id, text == 'visible'
        self.clock, self.mono = clock, mono
        self._lock, self._sequence = threading.Lock(), 0

    def make(self, kind, payload=None, *, trace=None, observation_ids=(), event_id=None,
             wall_ns=None, mono_ns=None):
        if kind not in EVENT_TYPES: raise ValueError('unsupported event type')
        if trace is not None and trace.run_id != self.run_id: raise ValueError('wrong trace run')
        payload = sanitize(payload or {}, visible=self.visible)
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        refs = tuple(observation_ids or (trace.observation_ids if trace else ()))[:32]
        value = dict(schema_version=1, event_id=event_id or new_id(), run_id=self.run_id,
                     session_id=self.session_id, source='gregory.collector', source_instance_id=self.run_id,
                     source_sequence=sequence, event_type=kind,
                     source_timestamp_utc=utc(self.clock() if wall_ns is None else wall_ns),
                     received_at_utc=utc(self.clock()), monotonic_ns=self.mono() if mono_ns is None else mono_ns,
                     correlation_id=trace.correlation_id if trace else None,
                     causation_id=trace.causation_id if trace else None,
                     decision_id=trace.decision_id if trace else None,
                     goal_id=trace.goal_id if trace else None, action_id=trace.action_id if trace else None,
                     control=trace.control.as_dict() if trace else ControlContext().as_dict(),
                     observation_ids=list(refs), payload=payload)
        return validate_event(value)


def validate_event(value):
    if value.get('schema_version') != 1 or value.get('event_type') not in EVENT_TYPES:
        raise ValueError('unsupported event contract')
    for k in ('event_id', 'run_id', 'source_instance_id'):
        uuid.UUID(value[k])
    for k in ('correlation_id', 'decision_id', 'goal_id', 'action_id', 'causation_id'):
        if value.get(k) is not None: uuid.UUID(value[k])
    for ref in value['observation_ids']: uuid.UUID(ref)
    if isinstance(value['source_sequence'], bool) or not isinstance(value['source_sequence'], int) or value['source_sequence'] < 1:
        raise ValueError('invalid sequence')
    if not isinstance(value['monotonic_ns'], int) or value['monotonic_ns'] < 0:
        raise ValueError('invalid monotonic clock')
    encoded = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
    if len(encoded.encode()) > 65536: raise ValueError('event exceeds 64 KiB')
    return Event(encoded)


def current_trace():
    scope = _SCOPE.get()
    return scope[0] if scope else None


def observed(kind, payload, *, priority='normal'):
    """Optional worker-local hook; failures never alter the observed operation."""
    scope = _SCOPE.get()
    if scope:
        try: return scope[1].record(kind, payload, trace=scope[0], priority=priority)
        except Exception: pass


def run_traced(trace, sink, fn, /, *args, **kwargs):
    token = _SCOPE.set((trace, sink))
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        observed('decision.error', {'error_category': type(exc).__name__}, priority='critical')
        raise
    finally:
        _SCOPE.reset(token)
