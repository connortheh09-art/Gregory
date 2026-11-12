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
import re
import time
from pathlib import Path

from greg_controller_core import AMBIGUOUS, DEFERRED, FAILED, PUBLISHED, REFUSED, Feedback

DRIVE_VERSION = 1
JUMPS = ('none', 'tap', 'hold')
MODES = ('walk', 'noclip')
FIELDS = frozenset(('forward', 'right', 'up', 'speed', 'yaw', 'pitch', 'turn_rate', 'jump', 'crouch', 'mode',
                    'look_steamid', 'look_point', 'look_near', 'use'))
STEAMID = re.compile(r'STEAM_[0-5]:[01]:[0-9]+')
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


def _point(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3 or not all(_finite(v) and abs(v) <= 65536 for v in value):
        return None
    return [float(v) for v in value]


def validate(params):
    """Normalize one drive decision; unknown, non-finite or out-of-range fields are refused.

    forward/right/up: -1..1 relative to the current view (up only acts in noclip);
    speed: 0..1 of run speed; yaw/pitch: absolute look target; turn_rate: deg/s;
    look_steamid/look_point: a tracked look target instead (Lua re-aims every command), with
    look_near: stand-off in units inside which forward motion toward it stops; use: one press.
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
    steamid, point, near, use = (params.get('look_steamid'), params.get('look_point'), params.get('look_near'),
                                 params.get('use', False))
    if steamid is not None and not (isinstance(steamid, str) and STEAMID.fullmatch(steamid)):
        raise ValueError('look_steamid must be a SteamID')
    if point is not None:
        point = _point(point)
        if point is None:
            raise ValueError('look_point must be three finite world coordinates')
    if (yaw is not None or pitch is not None) + (steamid is not None) + (point is not None) > 1:
        raise ValueError('one look target at a time')
    if near is not None and steamid is None and point is None:
        raise ValueError('look_near needs a tracked look target')
    if type(use) is not bool:
        raise ValueError('use must be true or false')
    return dict(forward=forward, right=right, up=up, speed=_bounded(params, 'speed', 0, 1, .5),
                yaw=None if yaw is None else float(yaw) % 360,
                pitch=None if pitch is None else max(-89., min(89., float(pitch))),
                turn_rate=_bounded(params, 'turn_rate', 30, 720, 180.),
                jump=jump, crouch=crouch, mode=mode, look_steamid=steamid, look_point=point,
                look_near=None if near is None else _bounded(params, 'look_near', 0, 512, 0.), use=use)


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
        tracked = ({'steamid': p['look_steamid']} if p.get('look_steamid') is not None else
                   {'point': p['look_point']} if p.get('look_point') is not None else None)
        if tracked is not None:
            action['look'] = {**tracked, 'rate': p['turn_rate']}
            if p.get('look_near') is not None:
                action['look']['near'] = p['look_near']
        elif p['yaw'] is not None or p['pitch'] is not None:
            action['look'] = {**{k: p[k] for k in ('yaw', 'pitch') if p[k] is not None}, 'rate': p['turn_rate']}
        if p['mode'] is not None:
            action['mode'] = p['mode']
        if p.get('use'):
            action['use'] = True  # Lua presses once per new generation, never on renewal
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


# -- Slice 2: Core's typed control decision -> controller -------------------------------
# The vocabulary is gregory_core.decision_contract's (CONTROL_MOVES/PACES/TURNS); this maps it
# to GMod inputs. Paces are fractions of run speed: at stock speeds walk is the normal walk.
PACES = {'sneak': .25, 'walk': .5, 'jog': .75, 'run': 1.}
MOVES = {'none': (0., 0.), 'forward': (1., 0.), 'back': (-1., 0.), 'left': (0., -1.), 'right': (0., 1.),
         'forward_left': (1., -1.), 'forward_right': (1., 1.), 'back_left': (-1., -1.), 'back_right': (-1., 1.)}
TURNS = {'turn_left': 90., 'turn_right': -90., 'turn_around': 180., 'slight_left': 30., 'slight_right': -30.}
TILTS = {'up': -45., 'down': 45., 'level': 0.}  # Source pitch: negative looks up
NEAR = {'player': 80., 'destination': 40.}     # stand-off: walk up to a target, not into it
CONTROL_FIELDS = frozenset(('action', 'command', 'move', 'pace', 'look', 'jump', 'crouch', 'use', 'fly',
                            'vertical', 'seconds'))


def _world(state):
    return tuple(state.get(k) for k in ('map', 'bridgeSession', 'controlEpoch'))


def translate(intent, view, state, player=lambda alias, state: None):
    """One decoded Core control drive -> (set_intent params, seconds, ignored fields).

    Relative turns use the heading at publication. Look targets must be in this decision's
    offer (view) and, for players, present now (player(alias, state) -> SteamID or None).
    ValueError refuses the decision; nothing is changed.
    """
    if (not isinstance(intent, dict) or intent.get('action') != 'control' or intent.get('command') != 'drive'
            or set(intent) - CONTROL_FIELDS):
        raise ValueError('bounded control drive required')
    move, speed = MOVES.get(intent.get('move')), PACES.get(intent.get('pace', 'walk'))
    if move is None or speed is None:
        raise ValueError('unknown move or pace')
    seconds = intent.get('seconds')
    if type(seconds) is not int or not 1 <= seconds <= 30:
        raise ValueError('seconds must be a whole number from 1 to 30')
    params = dict(forward=move[0], right=move[1], speed=speed, jump=intent.get('jump', 'none'),
                  crouch=intent.get('crouch', False), use=intent.get('use', False))
    look = intent.get('look')
    if isinstance(look, dict) and set(look) == {'player'}:
        steamid = player(look['player'], state)
        if steamid is None:
            raise ValueError('look target player is not present')
        params.update(look_steamid=steamid, look_near=NEAR['player'])
    elif isinstance(look, dict) and set(look) == {'destination'}:
        row = next((d for d in (view or {}).get('destinations', []) if d.get('id') == look['destination']), None)
        point = _point((row or {}).get('position'))
        if point is None:
            raise ValueError('unoffered look destination')
        params.update(look_point=point, look_near=NEAR['destination'])
    elif isinstance(look, str) and look in TURNS:
        ang = state.get('ang')
        yaw = ang.get('y') if isinstance(ang, dict) else None
        if not _finite(yaw):
            raise ValueError('turn needs the current heading')
        params['yaw'] = yaw + TURNS[look]
    elif isinstance(look, str) and look in TILTS:
        params['pitch'] = TILTS[look]
    elif look is not None:
        raise ValueError('unknown look')
    fly, vertical, ignored = intent.get('fly'), intent.get('vertical'), []
    if fly is not None:
        if fly not in ('on', 'off'):
            raise ValueError('fly must be on or off')
        params['mode'] = 'noclip' if fly == 'on' else 'walk'
    if vertical is not None:
        if vertical not in ('up', 'down'):
            raise ValueError('vertical must be up or down')
        drive = state.get('drive')
        if params.get('mode', drive.get('mode') if isinstance(drive, dict) else None) == 'noclip':
            params['up'] = 1. if vertical == 'up' else -1.
        else:
            ignored.append('vertical')  # only acts in flight; reported, not silently dropped
    return params, seconds, ignored


class GModControl:
    """Core's direct-control surface over one DirectController, which stays the only writer.

    offer(state) feeds the decision contract; apply() runs once per decision at publication;
    yield_to_task() hands the body back when Core picks a task or activity. The model's
    latest decision wins either way. people(state) -> [(view row with 'id', SteamID)], as
    GameTasks.people, resolves player look targets against the live state.
    """

    def __init__(self, controller, people=lambda state: ()):
        self.controller, self.people = controller, people

    def offer(self, state):
        """What the model may choose now; None when a decision would be refused anyway."""
        if not isinstance(state, dict) or self.controller.refusal():
            return None
        drive = state.get('drive') if isinstance(state.get('drive'), dict) else {}
        mode = drive.get('mode') if drive.get('mode') in ('walk', 'noclip') else 'other'
        noclip = drive.get('noclip') if isinstance(drive.get('noclip'), dict) else {}
        intent = self.controller.status()['intent']
        offer = dict(mode=mode, active=intent is not None,
                     seconds_left=0 if intent is None else math.ceil(intent['remaining']),
                     max_seconds=int(self.controller.policy.max_intent))
        # Flight is offered unless the game refused it in this world; Lua treats a mode it is
        # already in as a no-op, so a slightly stale offer is harmless.
        if mode == 'noclip' or (mode == 'walk' and noclip.get('state') != 'refused'):
            offer['fly'] = ['on', 'off']
        return offer

    def apply(self, intent, view, state):
        """One model decision at publication -> summary dict. ValueError means refused."""
        if not isinstance(intent, dict) or intent.get('action') != 'control':
            raise ValueError('control intent required')
        ignored = []
        if intent.get('command') == 'stop' and set(intent) == {'action', 'command'}:
            receipt = self.controller.stop('model_stop')  # stop always wins: no staleness check
        else:
            if tuple((view or {}).get('binding', ())) != _world(state):
                raise ValueError('stale control decision')
            params, seconds, ignored = translate(intent, view, state, self._player)
            receipt = self.controller.set_intent(params, seconds)
        if receipt.refused:
            raise ValueError(receipt.refused)
        return dict(generation=receipt.generation, transport=receipt.transport, ignored=ignored)

    def yield_to_task(self):
        """Core chose a task or activity: end any direct hold and let route helpers write."""
        if self.controller.status()['intent'] is not None:
            self.controller.stop('task_selected')
        self.controller.allow_tasks()

    def _player(self, alias, state):
        return next((steamid for row, steamid in self.people(state) if row.get('id') == alias), None)
