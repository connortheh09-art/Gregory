"""Bounded Core-owned working dialogue. RAM only, never episodic evidence.

The Core writer is the sole caller. A scope is a guild/channel/author tuple;
only API-accepted exchanges enter it. No adapter keeps a second copy.
"""
from collections import OrderedDict
import json
import time


class DialogueWindow:
    max_scopes = 8
    max_turns = 4
    max_chars = 3000
    max_age = 20 * 60

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.scopes = OrderedDict()

    def clear(self):
        self.scopes.clear()

    @staticmethod
    def scope(metadata):
        return tuple(metadata[k] for k in ('guild_id', 'channel_id', 'author_id'))

    @staticmethod
    def _clip(text, budget):
        # Bound the serialized form too, including escaping of Unicode/quotes.
        if len(json.dumps(text)) <= budget:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if len(json.dumps(text[:mid] + '…')) <= budget:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + '…'

    @staticmethod
    def _messages(turns):
        return [dict(role=role, content=text) for _, _, user, reply in turns
                for role, text in (('user', user), ('assistant', reply))]

    def _prune(self, now):
        for scope in list(self.scopes):
            turns = self.scopes[scope]
            turns[:] = [t for t in turns if 0 <= now - t[1] < self.max_age]
            if not turns:
                del self.scopes[scope]

    def snapshot(self, metadata):
        self._prune(self.clock())
        scope = self.scope(metadata)
        turns = self.scopes.get(scope, [])
        if turns:
            self.scopes.move_to_end(scope)
        return self._messages(turns)

    def append(self, metadata, source_key, user, reply):
        now = self.clock()
        self._prune(now)
        scope = self.scope(metadata)
        turns = self.scopes.setdefault(scope, [])
        if any(t[0] == source_key for t in turns):
            return
        turns.append((source_key, now, self._clip(user, 900), self._clip(reply, 1400)))
        del turns[:-self.max_turns]
        while len(json.dumps(self._messages(turns))) > self.max_chars:
            del turns[0]
        self.scopes.move_to_end(scope)
        while len(self.scopes) > self.max_scopes:
            self.scopes.popitem(last=False)
