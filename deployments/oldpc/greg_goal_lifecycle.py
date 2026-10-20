"""Mechanical goal outcomes and mailbox-wide speech deduplication."""
import hashlib
import math
import uuid
from collections import deque


def position(state):
    try:
        p = tuple(float(state['pos'][k]) for k in ('x', 'y', 'z'))
        return p if all(map(math.isfinite, p)) else None
    except (KeyError, TypeError, ValueError):
        return None


def key(text):
    return ' '.join(str(text).casefold().split())


class Goals:
    def __init__(self, emit=lambda event: None):
        self.active = None
        self.recent = deque(maxlen=12)
        self.emit = emit
        self.sample = None

    def finish(self, status, reason):
        if not self.active:
            return
        g, self.active = self.active, None
        self.recent.append(key(g['text']))
        self.emit(dict(g, status=status, reason=reason))

    def start(self, text, source, state, now, target=None):
        if source == 'self' and key(text) in self.recent:
            self.emit({'text': text, 'map': state.get('map'), 'status': 'rejected', 'reason': 'recent_goal'})
            return False
        self.finish('abandoned', 'superseded_by_' + source)
        self.active = dict(id=uuid.uuid4().hex[:12], ttl=600, last_progress_at=now, arrival_at=None, last_position=None, text=text, source=source, map=state.get('map'), set_at=now,
                           start_pos=position(state), best_dist=None, ticks=0,
                           last_progress=0, target=target,
                           context=(state.get('steamid'), state.get('bridgeSession'), state.get('controlEpoch')))
        self.sample = None
        self.emit(dict(self.active, status='started'))
        return True

    def observe(self, state, now):
        g = self.active
        if not g:
            return
        context = (state.get('steamid'), state.get('bridgeSession'), state.get('controlEpoch'))
        if state.get('map') != g['map'] or context != g['context']:
            return self.finish('abandoned', 'map_or_session_changed')
        if now - g['set_at'] >= g.get('ttl',600):
            return self.finish('failed', 'eta_timeout')
        stamp = (state.get('seq'), state.get('t'))
        if stamp == self.sample:
            return
        if self.sample is not None and (stamp[0] is None or stamp[1] is None or stamp[0] <= self.sample[0] or stamp[1] <= self.sample[1]):
            return
        self.sample = stamp
        if state.get('dead') or state.get('menu') or not state.get('enabled', True):
            return
        p = position(state)
        if not p or not g['start_pos']:
            return
        g['ticks'] += 1
        target = g['target']
        if target:
            d = math.dist(p, target)
            old=g.get('last_position');g['last_position']=(state.get('t'),p)
            speed=math.inf
            if old and state['t']>old[0]:speed=math.dist(p[:2],old[1][:2])/(state['t']-old[0])
            near=math.hypot(p[0]-target[0],p[1]-target[1])<=100 and abs(p[2]-target[2])<48
            if near and speed<=10:
                if g['arrival_at'] is None:g['arrival_at']=now
                elif now-g['arrival_at']>=.5:return self.finish('completed','arrived')
            else:g['arrival_at']=None
            score = d  # Remaining distance is nonnegative; lower is progress.
        elif any(w in key(g['text']) for w in ('rooftop', 'roof top')):
            score = p[2] - g['start_pos'][2]
            if score > 300:
                return self.finish('completed', 'height_gain')
        else:
            # Net displacement is evidence of progress, NOT generic task completion.
            score = math.dist(p, g['start_pos'])
        improved = (score < g['best_dist'] - 24 if target else score > g['best_dist'] + 24) if g['best_dist'] is not None else True
        if improved:
            g['best_dist'] = score
            g['last_progress'] = g['ticks']
            g['last_progress_at'] = now
        if now-g.get('last_progress_at',g['set_at']) >= 60:
            self.finish('failed', 'no_progress')


class Speech:
    def __init__(self):
        self.sent = {}

    def signature(self, state):
        p = position(state) or (0, 0, 0)
        return (state.get('map'), state.get('bridgeSession'), state.get('dead'),
                state.get('weapon'), tuple(int(v // 256) for v in p),
                (state.get('locomotion') or {}).get('status'))

    def allowed(self, text, state, now):
        digest = hashlib.sha256(key(text).encode()).hexdigest()
        old = self.sent.get(digest)
        return not old or (now - old[0] >= 60 and self.signature(state) != old[1])

    def commit(self, text, state, now):
        if len(self.sent) >= 128:
            self.sent.pop(next(iter(self.sent)))
        self.sent[hashlib.sha256(key(text).encode()).hexdigest()] = (now, self.signature(state))
