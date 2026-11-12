"""Game-agnostic direct control: one intent, short game leases, one writer.

A model decision sets an intent with a fixed deadline. Between decisions the
controller renews a short game-side lease; renewals never extend the intent.
Stop, expiry, identity change and disconnect bump the generation before the
release is published, and holds are only ever built from the current intent
under the writer lock, so a delayed renewal cannot follow a stop. Publication
is not application: only adapter telemetry marks a hold applied or a release
acknowledged/released, and only telemetry bound to the receipt's exact actor/
world identity and to this controller run.

Each controller run has an ordered id (`run_id`) reserved by the caller from a
durable counter under the single-writer lock, so a successor always ranks above
every envelope a dead run created, whatever the clocks do. The game fences
generations per run and ignores retired runs. Without a run id, or if the game
reports a run at or above ours that we never used, the controller fails closed:
no holds; stops still go out as plain (unfenced) releases.

Adapters (e.g. gmod_controller.GModAdapter) supply validate(params),
hold_action(intent, lease, controller), release_action(generation, reason,
controller) -> (action, mode), is_movement(action) and read(state) -> Feedback | None.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import asdict, dataclass

# Publication outcomes. Only PUBLISHED means the mailbox holds the envelope.
PUBLISHED = 'published'   # local file replace, or a relay ACK attesting its file replace
ACCEPTED = 'accepted'     # a transport accepted it without attesting mailbox publication
AMBIGUOUS = 'ambiguous'   # sent without a usable ACK: may or may not be in the mailbox
DEFERRED = 'deferred'     # not sent (writer cadence/budget/busy); rebuilt later
REFUSED = 'refused'       # not sent: arbitration or transport refused it
FAILED = 'failed'         # not in the mailbox
OUTCOMES = frozenset((PUBLISHED, ACCEPTED, AMBIGUOUS, DEFERRED, REFUSED, FAILED))
NOT_SENT = frozenset((DEFERRED, REFUSED, FAILED))


@dataclass(frozen=True)
class LeasePolicy:
    """Proposed values to validate live, not locked settings."""
    renew_interval: float = .5   # controller heartbeat cadence while an intent holds
    lease: float = 1.5           # game-side hold per renewal: survives a missed renewal
    min_lease: float = .2        # shorter remainders are left to the previous lease
    default_intent: float = 10.  # intent lifetime when the decision gives none
    max_intent: float = 30.
    stop_retry: float = .5       # republish an unacknowledged release this often
    release_timeout: float = 3.  # then mark it unconfirmed (holds stay dead regardless)
    telemetry_timeout: float = 3.
    stop_wait: float = 1.        # longest a caller waits behind an in-flight publication

    def __post_init__(self):
        if not all(type(v) in (int, float) and math.isfinite(v) and v > 0
                   for v in (getattr(self, k) for k in self.__dataclass_fields__)):
            raise ValueError('lease policy values must be positive finite numbers')
        if self.lease < 2 * self.renew_interval + .25:
            raise ValueError('lease must survive one missed renewal plus a game poll')
        if not self.min_lease <= self.lease <= 2:
            raise ValueError('lease must be within [min_lease, 2s] (the Lua clamp)')
        if self.default_intent > self.max_intent:
            raise ValueError('default intent exceeds max intent')


@dataclass(frozen=True)
class Feedback:
    """One telemetry sample. drive=False means no usable control report, which is
    never evidence of application or release."""
    identity: tuple
    seq: int
    actionable: bool
    drive: bool = False
    active: bool = False
    gen: int = 0
    stop_gen: int = 0
    held: frozenset = frozenset()
    speed: float | None = None
    mode: str | None = None
    ctl: int = 0                # controller run the game's fence currently belongs to


@dataclass(frozen=True)
class Intent:
    generation: int
    params: dict
    accepted_at: float
    deadline: float
    identity: tuple


@dataclass
class Receipt:
    """What is known about one generation. Telemetry alone sets applied/acknowledged/released."""
    kind: str                   # 'hold' or 'release'
    generation: int
    reason: str = ''
    refused: str = ''           # request refused before any publication
    requested_at: float = 0.
    attempts: int = 0
    transport: str = ''         # outcome of the latest publication attempt
    published: bool = False     # some attempt was attested in the mailbox
    applied: bool = False       # hold: the game reported applying this generation
    acknowledged: bool = False  # release: the game reported processing this release generation
    released: bool = False      # release: newer telemetry shows no control inputs held
    superseded: bool = False    # release: a newer intent replaced it first
    unconfirmed: bool = False   # release: retries ended (or the world changed) without game evidence
    binding: tuple = ()         # actor/world identity the evidence must come from
    after_seq: int | None = None  # release: telemetry seq at request; released needs a newer sample


class DirectController:
    """The single mailbox writer for one controlled player.

    publish(action, mode) -> one of OUTCOMES. Nothing else may write the same
    mailbox: task helpers use publish_task, everything else publish_other.
    """

    def __init__(self, adapter, publish, *, run_id=None, policy=None, clock=time.monotonic,
                 on_task_preempted=None):
        self.adapter, self._write = adapter, publish
        self.policy = policy or LeasePolicy()
        self.clock = clock
        self.on_task_preempted = on_task_preempted
        self._state = threading.Lock()  # short; never held across publication
        self._io = threading.Lock()     # held across publication: one writer, in order
        self._io_thread = None
        self.generation = 0
        self.intent = None
        self.hold = self.release = None
        self.owner = None               # None, 'direct' or 'task'
        self.tasks_blocked = False      # after a stop, until Core resumes tasks explicitly
        self.feedback = self.feedback_at = None
        self._renew_at = self._release_at = None
        valid = type(run_id) is int and 1 <= run_id < 2 ** 53
        self.controller = run_id if valid else None  # reserved run id; None = fail closed
        self.retired = ''               # why this run may no longer write, if it may not
        self._sent = False              # some envelope carrying our run id left the writer
        self._pending = 0               # attempts carrying our run id handed to the publisher, unresolved
        self._seen_unsent = False       # the game showed our id while nothing was known sent
        self._staged = []               # telemetry with our id awaiting that judgment (bounded)

    # -- decisions -------------------------------------------------------------
    def set_intent(self, params, duration=None):
        """Accept a model decision as a new generation with a fixed deadline. A
        change while moving publishes the new hold directly; nothing is released first."""
        now = self.clock()
        with self._state:
            receipt = Receipt('hold', self.generation, requested_at=now)
            refusal = self._refusal(now)
            if not refusal:
                try:
                    params, duration = self.adapter.validate(params), self._duration(duration)
                except ValueError as exc:
                    refusal = 'invalid: ' + str(exc)
            if refusal:
                receipt.refused = refusal
                return receipt
            self.generation += 1
            preempted = self.owner == 'task'
            self.owner = 'direct'
            self.intent = Intent(self.generation, params, now, now + duration, self.feedback.identity)
            if self.release is not None and not self.release.acknowledged:
                self.release.superseded = True
            self._release_at = None
            receipt.generation, receipt.binding = self.generation, self.intent.identity
            self.hold, self._renew_at = receipt, now
        if preempted and self.on_task_preempted is not None:
            self.on_task_preempted('direct_control')
        self._service(self.policy.stop_wait)
        return receipt

    def stop(self, reason='stop'):
        """Stop always wins: invalidate the hold first, then publish the release."""
        with self._state:
            if self.retired:  # the game ignores this run now; the owning run handles stops
                return Receipt('release', self.generation, reason, refused=self.retired)
            receipt = self._begin_release(reason, self.clock())
        self._service(self.policy.stop_wait)
        return receipt

    def disconnect(self, reason='disconnect'):
        """As stop, and forget telemetry: nothing resumes without fresh state and a new decision."""
        with self._state:
            if self.retired:
                return Receipt('release', self.generation, reason, refused=self.retired)
            receipt = self._begin_release(reason, self.clock())
            self.feedback = self.feedback_at = None
        self._service(self.policy.stop_wait)
        return receipt

    def allow_tasks(self):
        """Core's explicit decision to let route helpers write again after a stop."""
        with self._state:
            self.tasks_blocked = False

    def end_task(self):
        with self._state:
            if self.owner == 'task':
                self.owner = None

    # -- owner loop ------------------------------------------------------------
    def tick(self):
        """Heartbeat: expire, renew or retry a release. Never waits behind an
        in-flight publication; due work stays due."""
        now = self.clock()
        with self._state:
            i = self.intent
            if i is not None:
                if now >= i.deadline:
                    self._begin_release('expired', now)
                elif now - self.feedback_at > self.policy.telemetry_timeout:
                    self._begin_release('telemetry_stale', now)
        self._service(0)

    def observe(self, state):
        """Fold one telemetry sample in. This is the only source of game evidence."""
        fb = self.adapter.read(state)
        if fb is None:
            return None
        now = self.clock()
        with self._state:
            prev = self.feedback
            if prev is not None and prev.identity == fb.identity and fb.seq <= prev.seq:
                return prev
            self.feedback, self.feedback_at = fb, now
            i = self.intent
            if fb.drive and self.controller is not None and fb.ctl > self.controller:
                self._retire('controller_superseded')  # a newer run owns the fence: go quiet
                return fb
            if fb.drive and self.controller is not None and fb.ctl == self.controller and not self._sent:
                if not self._pending:
                    # Our reservation is not above what the game has seen: the id cannot be trusted.
                    self._retire('controller_run_reused')
                    return fb
                # Our own first publication may have landed before its ACK returned; decide
                # once that attempt resolves (see _record).
                self._seen_unsent = True
            r = self.release
            if i is not None and fb.identity != i.identity:
                self._begin_release('identity_changed', now)
            elif i is not None and not fb.actionable:
                self._begin_release('not_actionable', now)
            elif (r is not None and fb.identity != r.binding and self._release_at is not None
                  and not r.superseded):
                # Evidence from another world cannot confirm this release; fence that world afresh.
                r.unconfirmed = True
                self._begin_release('identity_changed', now)
            self._evidence(fb, now)
        self._service(0)
        return fb

    # -- other writers -----------------------------------------------------------
    def publish_task(self, action, mode):
        """Route-helper writes: refused while a direct intent holds control, and after
        a stop until allow_tasks(). Returns (outcome, reason)."""
        return self._service(self.policy.stop_wait, ('task', action, mode))

    def publish_other(self, action, mode):
        """Non-movement writes (speech, use, ...) through the same writer, in order."""
        return self._service(self.policy.stop_wait, ('other', action, mode))

    def status(self):
        with self._state:
            i = self.intent
            return dict(generation=self.generation, owner=self.owner, tasks_blocked=self.tasks_blocked,
                        intent=None if i is None else dict(generation=i.generation,
                                                           remaining=max(0., i.deadline - self.clock())),
                        hold=asdict(self.hold) if self.hold else None,
                        release=asdict(self.release) if self.release else None)

    # -- internals (state lock held unless noted) -------------------------------
    def _retire(self, reason):
        self.retired, self._staged = reason, []
        self.intent = self._renew_at = self._release_at = None
        self.owner = None

    def _refusal(self, now):
        if self.retired:
            return self.retired
        if self.controller is None:
            return 'no_controller_run'
        fb = self.feedback
        if fb is None or now - self.feedback_at > self.policy.telemetry_timeout:
            return 'no_fresh_state'
        if not fb.actionable:
            return 'not_actionable'
        return '' if fb.drive else 'drive_unsupported'

    def _duration(self, duration):
        if duration is None:
            return self.policy.default_intent
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('duration must be a positive finite number')
        return min(float(duration), self.policy.max_intent)

    def _begin_release(self, reason, now):
        self.generation += 1
        self.intent = self._renew_at = None
        self.owner, self.tasks_blocked = None, True
        fb = self.feedback
        self.release = Receipt('release', self.generation, reason, requested_at=now,
                               binding=fb.identity if fb else (), after_seq=fb.seq if fb else None)
        self._release_at = now
        return self.release

    def _evidence(self, fb, now):
        # Generations are only comparable within this run and this actor/world binding.
        if not fb.drive:
            return
        r = self.release
        if (r is not None and not r.superseded and fb.identity == r.binding
                and (r.after_seq is None or fb.seq > r.after_seq)):
            r.released = not fb.active and not fb.held  # observed input clearance, not attribution
        if self.controller is None or fb.ctl != self.controller:
            return
        if not self._sent:
            # Our id in the game before any attempt carrying it is known to have left: whether
            # it is ours is decided when that attempt resolves (_record). Stage, don't commit.
            self._staged = (self._staged + [fb])[-16:]
            return
        self._attribute(fb, now)

    def _attribute(self, fb, now):
        # fb carries this run's id and its sender is established: application/acknowledgment.
        h = self.hold
        if h is not None and fb.identity == h.binding and fb.active and fb.gen == h.generation:
            h.applied = True
        r = self.release
        if r is None or r.superseded or fb.identity != r.binding:
            return
        if fb.stop_gen >= r.generation:
            r.acknowledged = True
        wanted = self.intent.generation if self.intent is not None else None
        if fb.active and fb.gen != wanted and fb.gen < r.generation and self._release_at is None:
            # The game still holds a generation we released: reopen the release retries.
            r.unconfirmed, r.requested_at, self._release_at = False, now, now

    def _next_job(self, now, done):
        # done holds the receipts already sent in this pass (objects, so ids cannot recycle).
        r = self.release
        if (r is not None and not any(x is r for x in done) and not r.superseded
                and self._release_at is not None and now >= self._release_at):
            unsupported = r.published and (self.feedback is None or not self.feedback.drive)
            if (r.acknowledged and r.released) or unsupported:
                self._release_at = None
            elif r.attempts and now - r.requested_at >= self.policy.release_timeout:
                r.unconfirmed, self._release_at = True, None
            else:
                self._release_at = now + self.policy.stop_retry
                return self._outstanding(r, self.adapter.release_action(r.generation, r.reason, self.controller))
        i = self.intent
        if (i is not None and not any(x is self.hold for x in done)
                and self._renew_at is not None and now >= self._renew_at):
            lease = min(self.policy.lease, i.deadline - now)
            if lease < self.policy.min_lease:
                self._renew_at = None  # the last lease covers the remainder; tick() releases at the deadline
                return None
            self._renew_at = now + self.policy.renew_interval
            return self._outstanding(self.hold, self.adapter.hold_action(i, lease, self.controller))
        return None

    def _outstanding(self, receipt, job):
        if self.controller is not None:
            self._pending += 1  # resolved by _record, whatever the publisher does
        return receipt, job

    def _record(self, receipt, outcome, now):
        receipt.attempts += 1
        receipt.transport = outcome
        if self.controller is not None:
            self._pending -= 1
            if outcome not in NOT_SENT and not self._sent:
                self._sent = True
                staged, self._staged = self._staged, []
                for fb in staged:  # our envelope may have landed first: commit, in order
                    self._attribute(fb, now)
            elif outcome in NOT_SENT and self._seen_unsent and not self._sent and not self._pending:
                # The game showed our id, yet every attempt carrying it definitely never left:
                # the staged evidence was never ours (_retire discards it).
                self._retire('controller_run_reused')
                return
        if outcome == PUBLISHED:
            receipt.published = True
        if outcome in NOT_SENT:  # nothing reached the game: rebuild on the next pass
            if receipt is self.hold and self.intent is not None and self._renew_at is not None:
                self._renew_at = now
            elif receipt is self.release and self._release_at is not None:
                self._release_at = now

    def _send(self, action, mode):
        # Called without the state lock, with the writer lock held.
        try:
            outcome = self._write(action, mode)
        except Exception:
            return AMBIGUOUS  # the write may have happened before the error
        return outcome if outcome in OUTCOMES else FAILED

    def _extra(self, kind, action, mode):
        # Writer lock held. Guard and ownership change are atomic with the decision to send.
        with self._state:
            if self.retired:
                refusal = self.retired
            elif kind == 'task' and self.intent is not None:
                refusal = 'direct_active'
            elif kind == 'task' and self.tasks_blocked:
                refusal = 'stopped'
            elif kind == 'other' and self.adapter.is_movement(action):
                refusal = 'movement_requires_arbiter'
            else:
                refusal = ''
                if kind == 'task':
                    self.owner = 'task'
        return (REFUSED, refusal) if refusal else (self._send(action, mode), '')

    def _drain(self, done):
        for _ in range(3):
            with self._state:
                job = self._next_job(self.clock(), done)
            if job is None:
                return
            receipt, (action, mode) = job
            done.append(receipt)
            outcome = self._send(action, mode)  # _next_job counted it outstanding already
            with self._state:
                self._record(receipt, outcome, self.clock())

    def _service(self, wait, extra=None):
        """Publish due work in order under the writer lock: releases first, then the
        extra write, then renewals. A call made from inside a publication returns at
        once; the outer pass publishes whatever became due before it lets go."""
        if self._io_thread == threading.get_ident():
            return (DEFERRED, 'reentrant') if extra else None
        if not (self._io.acquire(timeout=wait) if wait > 0 else self._io.acquire(blocking=False)):
            return (DEFERRED, 'writer_busy') if extra else None
        self._io_thread, done, result = threading.get_ident(), [], None
        try:
            self._drain(done)
            if extra is not None:
                result = self._extra(*extra)
                self._drain(done)
        finally:
            self._io_thread = None
            self._io.release()
        return result
