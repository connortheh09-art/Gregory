"""Non-destructive preflight and pure monitoring rules; never rotate live files."""
import hashlib
import math
import json
import time
from pathlib import Path


def inventory(root):
    root = Path(root).absolute()
    if root.resolve() != root or not root.is_dir(): raise ValueError('real directory required, no symlink root')
    result = {}
    for p in sorted(root.rglob('*')):
        if p.is_symlink(): raise ValueError('symlink in input tree')
        if p.is_file():
            stat = p.stat()
            if stat.st_size > 64 * 1024 * 1024: raise ValueError('oversized input file')
            result[p.relative_to(root).as_posix()] = dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
    return result


def clean_b(*, source_root, core_root, transport_root, bootstrap_sha256, source_sha256, core_sha256,
            context_paths, map_name):
    """Run while A processes are down, after supervisor archive-and-empty.

    No deletion/rotation or start occurs here. Any unlisted file fails closed.
    Bootstrap hashes come from a trusted pretrial manifest, not A's transport.
    """
    source, core, transport = inventory(source_root), inventory(core_root), inventory(transport_root)
    if set(bootstrap_sha256) != {'playercore_agent.txt', 'navdump.json'}:
        raise ValueError('exact static marker/nav bootstrap required')
    if set(transport) != set(bootstrap_sha256): raise ValueError('transport not empty except approved bootstrap')
    for path, expected in bootstrap_sha256.items():
        if transport[path]['sha256'] != expected: raise ValueError('bootstrap hash mismatch')
    if (Path(transport_root) / 'playercore_agent.txt').read_text() != 'installed-agent-20261015':
        raise ValueError('bootstrap agent marker mismatch')
    if json.loads((Path(transport_root) / 'navdump.json').read_text()).get('map') != map_name:
        raise ValueError('bootstrap nav map mismatch')
    # Do not resolve defaults from CWD; protect the actual loaded bridge tree.
    if not {'gmod_bridge.py', 'greg_dialogue.py', 'greg_chat_memory.py', 'greg_playercore.py'} <= set(source_sha256):
        raise ValueError('loaded module source pins missing')
    actual = {k: v['sha256'] for k, v in source.items() if '__pycache__/' not in k}
    if actual != source_sha256: raise ValueError('fresh source copy differs from approved manifest')
    core_actual = {k: v['sha256'] for k, v in core.items() if '__pycache__/' not in k}
    if core_actual != core_sha256 or 'memory.py' not in core_actual or 'canary.py' not in core_actual:
        raise ValueError('core source differs from approved manifest')
    if any((k.endswith(('.jsonl', '.sqlite3', '.db')) or
            (k.endswith('.json') and k != 'SOURCE-MANIFEST.json') or 'greg_player_memory/' in k) for k in actual):
        raise ValueError('legacy context in source tree')
    absence = {}
    for name, value in context_paths.items():
        p = Path(value).absolute()
        if p.resolve() != p or p.exists(): raise ValueError('legacy context path not absent: ' + name)
        absence[name] = str(p)
    required = {'chat_memory', 'player_memory', 'audit', 'trace', 'lessons', 'landmarks'}
    if set(absence) != required: raise ValueError('explicit source-relative context paths required')
    return dict(kind='gregory.canary.clean-b.v1', created_ns=time.time_ns(),
                mtime_slack_ns=1_000_000_000, map_name=map_name,
                source_root=str(Path(source_root).resolve()), core_root=str(Path(core_root).resolve()),
                transport_root=str(Path(transport_root).resolve()),
                source_inventory=source, core_inventory=core, bootstrap_inventory=transport, absent=absence)


def started_b(preflight, *, allowed_files):
    """Second empirical listing after GMod starts. Exact allowlist is reviewed.

    A preflight is run BEFORE launching GMod; B may then legitimately create
    state/heartbeat streams. Old/missing-bootstrap/unlisted files still abort.
    """
    if preflight.get('kind') != 'gregory.canary.clean-b.v1': raise ValueError('clean B receipt required')
    source = inventory(preflight['source_root'])
    core = inventory(preflight['core_root'])
    for before, actual in ((preflight['source_inventory'], source), (preflight['core_inventory'], core)):
        stable = lambda data: {k:(v['sha256'],v['bytes']) for k,v in data.items() if '__pycache__/' not in k}
        if stable(before) != stable(actual): raise ValueError('source changed after preflight')
    transport = inventory(preflight['transport_root'])
    bootstrap = preflight['bootstrap_inventory']
    if not set(bootstrap) <= set(transport): raise ValueError('bootstrap missing after startup')
    for key, old in bootstrap.items():
        if transport[key] != old: raise ValueError('bootstrap changed after preflight')
    for key, value in transport.items():
        if key in bootstrap: continue
        # File timestamp precision need not match time.time_ns (even on this
        # Linux filesystem). Absence listing + new adapter identity are primary;
        # mtime is a supplementary coarse check, with explicit one-second slack.
        if key not in allowed_files or value['mtime_ns'] < preflight['created_ns'] - preflight['mtime_slack_ns']:
            raise ValueError('old or unlisted B transport file')
    for path in preflight['absent'].values():
        if Path(path).exists(): raise ValueError('legacy context appeared after preflight')
    return dict(transport_inventory=transport, new_files=sorted(set(transport) - set(bootstrap)))


class Monitor:
    """Evaluate external 5-second CSV samples. Does not inspect/stop processes."""
    def __init__(self):
        self.samples = []
        self.baseline = None
        self.identity = None
        self.baseline_started = None
        self.baseline_failed = False

    def accept(self, s):
        if self.baseline_failed:
            raise ValueError('invalid inactive baseline; start a new trial')
        try:
            return self._accept(s)
        except (ValueError, TypeError, KeyError, OverflowError):
            # A caught rejection cannot turn an unobserved/unsafe interval into
            # a valid inactive baseline. This also covers non-active failures.
            if self.baseline is None:
                self.baseline_failed = True
            raise

    def _accept(self, s):
        # Latch known activity BEFORE shape, numeric, identity or health guards
        # can reject the same sample for another reason.
        if (self.baseline is None and isinstance(s, dict) and
                type(s.get('active')) in (int, float) and s['active'] > 0):
            self.baseline_failed = True
            raise ValueError('activity contaminated the inactive baseline; start a new trial')
        required = {'elapsed', 'active', 'game_pid', 'game_start', 'bridge_pid', 'bridge_start',
                    'game_ws', 'game_private', 'bridge_ws', 'bridge_private', 'available',
                    'state_age', 'alive', 'supervised', 'recorder_ok'}
        if set(s) != required: raise ValueError('complete monitoring sample required')
        numeric = required - {'alive', 'supervised', 'recorder_ok'}
        if any(type(s[k]) not in (int, float) or not math.isfinite(s[k]) or s[k] < 0 for k in numeric):
            raise ValueError('finite monitoring measures required')
        identity = tuple(s[k] for k in ('game_pid', 'game_start', 'bridge_pid', 'bridge_start'))
        if self.identity and identity != self.identity: raise ValueError('process identity changed')
        self.identity = identity
        if self.samples and not 0 < s['elapsed'] - self.samples[-1]['elapsed'] <= 15:
            raise ValueError('sampler stale or clock reversed')
        if s['active'] > 300 or s['elapsed'] > 1800 or s['available'] < 2 * 1024**3 or s['state_age'] > 3:
            raise ValueError('time/RAM/freshness stop')
        if any(s[k] is not True for k in ('alive', 'supervised', 'recorder_ok')):
            raise ValueError('supervision/health stop')
        metrics = ('game_ws', 'game_private', 'bridge_ws', 'bridge_private')
        if self.baseline:
            if any(s[k] - self.baseline[k] >= 1024**3 for k in metrics): raise ValueError('per-process growth stop')
        # A rise is measured against every retained point in the last 60s,
        # not a sum of working set and private allocation.
        if any(any(s[k] - old[k] >= 500 * 1024**2 for k in metrics)
               for old in self.samples if s['elapsed'] - old['elapsed'] <= 60):
            raise ValueError('growth rate stop')
        if self.baseline_started is None:
            self.baseline_started = s['elapsed']
        self.samples.append(dict(s))
        self.samples = [old for old in self.samples if s['elapsed'] - old['elapsed'] <= 120]
        if self.baseline is None and s['elapsed'] - self.baseline_started >= 120:
            self.baseline = dict(s)
        return dict(baseline_ready=self.baseline is not None)

    def heartbeat(self, elapsed):
        if not self.samples or elapsed - self.samples[-1]['elapsed'] > 15:
            raise ValueError('sampler stale; stop trial')
