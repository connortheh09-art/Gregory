"""GMod adapter for the direct controller (greg_controller_core).

Holds are the typed Lua `drive` verb. Releases are `wait` carrying `driveGen`:
old Lua still releases everything, new Lua also fences that generation. Both
carry `ctl`, the controller run id that scopes the game's fence (reserve_run).
Game evidence comes only from the Lua `drive` telemetry block, advertised by
`capabilities.drive`. Wire contract: docs/GMOD_CONTROLLER.md.
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

from greg_controller_core import AMBIGUOUS, DEFERRED, FAILED, PUBLISHED, REFUSED, Feedback

DRIVE_VERSION = 1
JUMPS = ('none', 'tap', 'hold')
MODES = ('walk', 'noclip')
FIELDS = frozenset(('forward', 'right', 'up', 'speed', 'yaw', 'pitch', 'turn_rate', 'jump', 'crouch', 'mode'))
# Legacy verbs that move, steer or release. Only the controller may send them.
MOVEMENT = frozenset(('drive', 'move', 'navigate', 'key', 'look', 'gaze', 'wait'))
IDENTITY = ('steamid', 'bridgeSession', 'controlEpoch', 'map')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _bounded(params, key, low, high, default):
    value = params.get(key, default)
    if not _finite(value) or not low <= value <= high:
        raise ValueError(f'{key} must be a finite number in [{low:g}, {high:g}]')
    return float(value)


def _count(value):
    return _finite(value) and value >= 0 and value == int(value)


def validate(params):
    """Normalize one drive decision; unknown, non-finite or out-of-range fields are refused.

    forward/right/up: -1..1 relative to the current view (up only acts in noclip);
    speed: 0..1 of run speed; yaw/pitch: absolute look target; turn_rate: deg/s.
    """
    if not isinstance(params, dict):
        raise ValueError('drive params must be an object')
    unknown = set(params) - FIELDS
    if unknown:
        raise ValueError('unknown drive field: ' + ','.join(sorted(map(str, unknown))))
    forward, right, up = (_bounded(params, k, -1, 1, 0.) for k in ('forward', 'right', 'up'))
    norm = math.hypot(forward, right)
    if norm > 1:
        forward, right = forward / norm, right / norm
    jump, crouch, mode = params.get('jump', 'none'), params.get('crouch', False), params.get('mode')
    if jump not in JUMPS:
        raise ValueError('jump must be none, tap or hold')
    if type(crouch) is not bool:
        raise ValueError('crouch must be true or false')
    if mode is not None and mode not in MODES:
        raise ValueError('mode must be walk or noclip')
    yaw, pitch = params.get('yaw'), params.get('pitch')
    if (yaw is not None and not _finite(yaw)) or (pitch is not None and not _finite(pitch)):
        raise ValueError('yaw and pitch must be finite numbers')
    return dict(forward=forward, right=right, up=up, speed=_bounded(params, 'speed', 0, 1, .5),
                yaw=None if yaw is None else float(yaw) % 360,
                pitch=None if pitch is None else max(-89., min(89., float(pitch))),
                turn_rate=_bounded(params, 'turn_rate', 30, 720, 180.),
                jump=jump, crouch=crouch, mode=mode)


def reserve_run(path, *, initialize=False):
    """Reserve the next controller run id from a durable counter beside cmd.writer.lock.

    Call only while holding that lock (one writer per data directory). Ids never repeat
    and only grow, independent of any clock, so a successor outranks every envelope a
    dead run created, including ones still in transit. Any doubt raises: a missing
    counter (unless initialize, for a fresh install or after the game's bridge Lua
    reloaded), a corrupt one, or a failed durable write. The caller then constructs the
    controller without a run id, which fails closed. A failure before the replace leaves
    the counter untouched; one after it (directory fsync) leaves it advanced, which only
    skips an id. Never roll the counter back.
    """
    path = Path(path)
    try:
        last = json.loads(path.read_text(encoding='utf-8'))['run']
    except FileNotFoundError:
        if not initialize:
            raise
        last = 0
    if type(last) is not int or not 0 <= last < 2 ** 53 - 1:
        raise ValueError('corrupt controller run counter')
    run, tmp = last + 1, path.with_name(path.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'run': run}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    if hasattr(os, 'O_DIRECTORY'):  # make the rename durable too (POSIX). Windows crash durability
        # of this replace is not qualified here: verify on the target before relying on it.
        fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return run


def bridge_actionable(state, now):
    """Copy of gmod_bridge.actionable; integration should pass the bridge's own."""
    server_time = state.get('serverTime')
    return bool(state.get('enabled') is True and not state.get('dead') and not state.get('menu')
                and not state.get('inVehicle') and _finite(server_time) and 0 <= now - server_time <= 3
                and state.get('steamid') and state.get('bridgeSession')
                and isinstance(state.get('controlEpoch'), (int, float)))


class GModAdapter:
    def __init__(self, *, actionable=bridge_actionable, wall=time.time):
        self.actionable, self.wall = actionable, wall

    validate = staticmethod(validate)

    def hold_action(self, intent, lease, ctl):
        p = intent.params
        action = {'action': 'drive', 'v': DRIVE_VERSION, 'ctl': ctl, 'gen': intent.generation,
                  'lease': math.floor(lease * 1000) / 1000,  # never past the intent deadline
                  'move': {k: p[k] for k in ('forward', 'right', 'up', 'speed')},
                  'jump': p['jump'], 'crouch': p['crouch']}
        if p['yaw'] is not None or p['pitch'] is not None:
            action['look'] = {**{k: p[k] for k in ('yaw', 'pitch') if p[k] is not None}, 'rate': p['turn_rate']}
        if p['mode'] is not None:
            action['mode'] = p['mode']
        return action, 'direct'

    def release_action(self, generation, reason, ctl):
        # mode 'stop' + action 'wait' is what TickWriter lets preempt its cadence. Without a
        # run id this is a plain legacy release: it stops inputs but fences nothing.
        if ctl is None:
            return {'action': 'wait', 'reason': str(reason)[:32]}, 'stop'
        return {'action': 'wait', 'ctl': ctl, 'driveGen': generation, 'reason': str(reason)[:32]}, 'stop'

    def is_movement(self, action):
        if not isinstance(action, dict):
            return True
        name = action.get('action')
        return name in MOVEMENT or (name == 'console' and str(action.get('cmd', '')).lower().split()[:1] == ['noclip'])

    def read(self, state):
        """Telemetry -> Feedback. A missing or malformed drive block is never evidence."""
        if not isinstance(state, dict) or type(state.get('seq')) is not int:
            return None
        identity = tuple(state.get(k) for k in IDENTITY)
        if not identity[0] or not identity[1]:
            return None
        actionable = bool(self.actionable(state, self.wall()))
        caps, drive = state.get('capabilities'), state.get('drive')
        held = drive.get('held') if isinstance(drive, dict) else None
        if held == {}:
            held = []  # util.TableToJSON may encode an empty Lua table as an object
        if not (isinstance(caps, dict) and caps.get('drive') == DRIVE_VERSION and isinstance(drive, dict)
                and drive.get('v') == DRIVE_VERSION and type(drive.get('active')) is bool
                and _count(drive.get('ctl')) and _count(drive.get('gen')) and _count(drive.get('stopGen'))
                and isinstance(held, list) and len(held) <= 16 and all(isinstance(h, str) for h in held)):
            return Feedback(identity, state['seq'], actionable)
        speed, mode = drive.get('speed'), drive.get('mode')
        return Feedback(identity, state['seq'], actionable, True, drive['active'], int(drive['gen']),
                        int(drive['stopGen']), frozenset(held), float(speed) if _finite(speed) else None,
                        mode if mode in ('walk', 'noclip', 'other') else None, int(drive['ctl']))


def bridge_publisher(write, cmd_path, next_seq, latest, session, chain=lambda: None):
    """Adapt gmod_bridge.write_cmd (or its TickWriter wrapper) to a publication outcome.

    write_cmd's observer argument replaces the recorder observer, so `chain` must
    return the bridge's current _COMMAND_OBSERVER to keep recording intact.
    """
    def publish(action, mode):
        state = latest()
        if not state:
            return REFUSED
        seen = {}

        def observe(payload, **status):
            seen.update(status)
            previous = chain()
            if previous is not None:
                previous(payload, **status)
        written = write(cmd_path, next_seq(), action, state, session, mode, observer=observe)
        result = seen.get('write_result')
        if written is True or result == 'written':
            return PUBLISHED
        if result == 'failed':
            return AMBIGUOUS if seen.get('reason') == 'remote_publication_unconfirmed' else FAILED
        if result == 'suppressed':
            return REFUSED
        # No report: TickWriter held it back. It queues a held-back stop and replays it on the
        # next tick (greg_supervised.py:110), so a stop may still reach the game.
        return AMBIGUOUS if mode == 'stop' and action.get('action') == 'wait' else DEFERRED
    return publish
