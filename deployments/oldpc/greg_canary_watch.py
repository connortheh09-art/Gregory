"""Read a supervisor sampler heartbeat. Never start, kill or restart a process."""
import json
import os
from pathlib import Path
import time
import math


def supervision(path, *, now=None, bridge_pid=None):
    status = json.loads(Path(path).read_text())
    now = time.time() if now is None else now
    if (status.get('kind') != 'gregory.canary.monitor.v1' or status.get('ok') is not True or
        status.get('bridge_pid') != (os.getpid() if bridge_pid is None else bridge_pid) or
        type(status.get('utc_seconds')) not in (int, float) or
        not 0 <= now - status['utc_seconds'] <= 15 or type(status.get('baseline_ready')) is not bool):
        raise ValueError('supervision stale, failed or bound to another process')
    return status['baseline_ready']


def await_baseline(path, *, timeout=135):
    started = time.monotonic()
    while time.monotonic() - started <= timeout:
        try:
            if supervision(path): return
        except FileNotFoundError:
            if time.monotonic() - started > 15: raise
        time.sleep(.1)
    raise ValueError('monitor baseline unavailable')


def wait_still(tail, previous, stop_sequence, *, timeout=3, clock=time.monotonic, sleep=time.sleep):
    """Corroborate >=1s of stationary state in BOTH local and game time.

    stop_sequence addresses the published command, NOT a state acknowledgement:
    Lua increments state.seq independently. No command ACK exists in this wire
    format. The parameter is retained/type-checked for API compatibility only;
    it intentionally does not enter the state comparison. A true result is
    physical corroboration, never delivery proof.
    """
    started = clock(); prior = None
    identity = tuple(previous.get(k) for k in ('steamid', 'bridgeSession', 'controlEpoch', 'map'))
    if (type(stop_sequence) is not int or stop_sequence < 0 or
            type(previous.get('seq')) is not int or
            type(previous.get('t')) not in (int, float) or not math.isfinite(previous['t'])):
        return False
    last_sequence, last_stamp = previous['seq'], previous['t']
    while clock() - started <= timeout:
        for line in tail.read_new():
            try:
                s = json.loads(line)
                if not isinstance(s, dict):
                    prior = None
                    continue
                if tuple(s.get(k) for k in ('steamid', 'bridgeSession', 'controlEpoch', 'map')) != identity: continue
                if type(s.get('seq')) is not int or s['seq'] <= last_sequence:
                    prior = None
                    continue
                stamp = float(s['t'])
                if not math.isfinite(stamp) or stamp <= last_stamp:
                    prior = None
                    continue
                last_sequence, last_stamp = s['seq'], stamp
                if not 0 <= time.time() - s['serverTime'] <= 3:
                    prior = None
                    continue
                if (s.get('locomotion') or {}).get('status') != 'stopped':
                    prior = None
                    continue
                pos = tuple(float(s['pos'][k]) for k in ('x','y','z'))
                if not all(math.isfinite(v) for v in pos):
                    prior = None
                    continue
                observed = clock()
                if prior:
                    before, game_before, position, sequence = prior
                    if s['seq'] <= sequence or stamp <= game_before: continue
                    if math.dist(pos, position) <= 1:
                        if observed - before >= 1 and stamp - game_before >= 1:
                            return True
                        continue  # Keep the beginning of the stillness interval.
                prior = (observed, stamp, pos, s['seq'])
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                prior = None
                continue
        sleep(.05)
    return False
