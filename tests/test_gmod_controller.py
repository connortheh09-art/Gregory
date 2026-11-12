"""Slice 1 fixtures: intent/lease/stop core, single writer, receipts, receiver rule.

The game here is a model: a single latest-envelope mailbox polled by an
executable copy of the documented Lua receiver rule. It pins semantics for the
Lua work; it is not evidence of Lua or live game behaviour.
"""
from pathlib import Path
import json
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'deployments/oldpc')]
from greg_controller_core import (AMBIGUOUS, DEFERRED, FAILED, PUBLISHED, REFUSED,
                                  DirectController, LeasePolicy)
from gmod_controller import GModAdapter, bridge_publisher, reserve_run, validate

WALL = 1_000_000.
CASES = json.loads((Path(__file__).with_name('gmod_drive_receiver_cases.json')).read_text())['cases']


def is_gen(value):
    return type(value) in (int, float) and value == value and value >= 1 and value == int(value)


class DriveReceiver:
    """Executable model of the Lua receiver rule (docs/GMOD_CONTROLLER.md). The
    envelope session plays no part: the fence belongs to the controller run `ctl`."""
    def __init__(self):
        self.ctl, self.floor, self.stop_gen, self.gen = 0, 0, 0, 0
        self.active, self.expires = False, 0.

    def _run(self, ctl):
        if ctl > self.ctl:  # a newer run: release the old hold, fresh fence
            self.ctl, self.floor, self.stop_gen, self.gen, self.active = int(ctl), 0, 0, 0, False

    def deliver(self, env, now):
        a = env.get('action') or {}
        name, ctl = a.get('action'), a.get('ctl')
        if name == 'wait' and ctl is None:  # legacy wait: release, no fence
            self.active = False
            return 'released'
        if name not in ('wait', 'drive'):
            return 'ignored'
        if not is_gen(ctl):
            return 'invalid_controller'
        if ctl < self.ctl:
            return 'retired_controller'
        if name == 'wait':
            self._run(ctl)
            self.active = False
            if is_gen(a.get('driveGen')):
                self.stop_gen = max(self.stop_gen, int(a['driveGen']))
            return 'released'
        g, lease = a.get('gen'), a.get('lease')
        if not is_gen(g):
            return 'invalid_generation'
        if type(lease) not in (int, float) or not lease > 0:
            return 'invalid_lease'
        self._run(ctl)
        if g <= self.stop_gen:
            return 'released_generation'
        if g < self.floor:
            return 'stale_generation'
        self.floor = self.gen = int(g)
        self.active, self.expires = True, now + min(max(lease, .1), 2.)
        return 'applied'

    def expire(self, now):
        if self.active and now >= self.expires:
            self.active = False


class Clock:
    def __init__(self):
        self.t = 100.

    def __call__(self):
        return self.t


class Mailbox:
    """Single latest-envelope mailbox. outcomes: queued (reported, written) pairs."""
    def __init__(self, clock):
        self.clock, self.history, self.latest, self.seq = clock, [], None, 0
        self.outcomes, self.hook = [], None
        self.inflight, self.peak, self.lock = 0, 0, threading.Lock()

    def __call__(self, action, mode):
        with self.lock:
            self.inflight += 1
            self.peak = max(self.peak, self.inflight)
        try:
            if self.hook:
                self.hook(action, mode)
            reported, written = self.outcomes.pop(0) if self.outcomes else (PUBLISHED, True)
            with self.lock:
                self.seq += 1
                env = {'seq': self.seq, 'session': 'py', 'action': action, 'mode': mode, 'at': self.clock()}
                self.history.append(env)
                if written:
                    self.latest = env
            return reported
        finally:
            with self.lock:
                self.inflight -= 1

    def actions(self, name=None):
        return [e['action'] for e in self.history if name is None or e['action']['action'] == name]


class Game:
    """Polls the mailbox like Lua (latest envelope, session:seq dedup) and reports telemetry."""
    def __init__(self, box, clock, drive=True):
        self.box, self.clock, self.drive = box, clock, drive
        self.rx, self.last, self.seq = DriveReceiver(), None, 0
        self.identity = {'steamid': 'STEAM_0:1:1000', 'bridgeSession': 'b1', 'controlEpoch': 1, 'map': 'gm_construct'}
        self.dead = False

    def poll(self):
        env = self.box.latest
        if env is not None and env['seq'] != self.last:
            self.last = env['seq']
            return self.rx.deliver(env, self.clock())

    def state(self):
        self.rx.expire(self.clock())
        self.seq += 1
        s = dict(self.identity, seq=self.seq, enabled=True, dead=self.dead, menu=False,
                 inVehicle=False, serverTime=WALL)
        if self.drive:
            s['capabilities'] = {'drive': 1}
            s['drive'] = {'v': 1, 'ctl': self.rx.ctl, 'active': self.rx.active, 'gen': self.rx.gen,
                          'stopGen': self.rx.stop_gen,
                          'held': ['forward', 'speed'] if self.rx.active else {}, 'speed': 0, 'mode': 'walk'}
        return s


def make(policy=None, drive=True, clock=None, before=None, run_id=1, **kw):
    clock = clock or Clock()
    box = Mailbox(clock)
    game = Game(box, clock, drive)
    if before is not None:
        before(game)
    ctl = DirectController(GModAdapter(wall=lambda: WALL), box, run_id=run_id, policy=policy,
                           clock=clock, **kw)
    ctl.observe(game.state())
    return ctl, box, game, clock


def run(ctl, game, clock, until, step=.25, trace=None):
    """The owner loop: tick, game poll, telemetry back."""
    while clock.t < until - 1e-9:
        clock.t = round(clock.t + step, 6)
        ctl.tick()
        game.poll()
        ctl.observe(game.state())
        if trace is not None:
            trace.append(game.rx.active)


class Fence(unittest.TestCase):
    def assertFenced(self, box):
        """Within a controller run, no hold of generation <= S follows a release of S."""
        fence = {}
        for a in box.actions():
            if a['action'] == 'wait':
                fence[a['ctl']] = max(fence.get(a['ctl'], 0), a['driveGen'])
            elif a['action'] == 'drive':
                self.assertGreater(a['gen'], fence.get(a['ctl'], 0), box.actions())


class Renewal(Fence):
    def test_renewals_keep_the_fixed_deadline_and_generation(self):
        ctl, box, game, clock = make()
        hold = ctl.set_intent({'forward': 1, 'speed': 1}, duration=4)
        deadline, trace = ctl.intent.deadline, []
        run(ctl, game, clock, 103.75, trace=trace)
        self.assertEqual(ctl.intent.deadline, deadline)  # heartbeats and telemetry never extend it
        self.assertTrue(hold.applied and all(trace))
        holds = [e for e in box.history if e['action']['action'] == 'drive']
        self.assertGreaterEqual(len(holds), 8)
        self.assertEqual({e['action']['gen'] for e in holds}, {hold.generation})
        self.assertTrue(all(e['at'] + e['action']['lease'] <= deadline + 1e-9 for e in holds))
        run(ctl, game, clock, 105)
        release = ctl.release
        self.assertIsNone(ctl.intent)
        self.assertEqual((release.reason, release.generation), ('expired', hold.generation + 1))
        self.assertTrue(release.acknowledged and release.released)
        self.assertFalse(game.rx.active)
        self.assertFenced(box)

    def test_model_latency_is_bridged_without_stop_start(self):
        ctl, box, game, clock = make()
        ctl.set_intent({'forward': 1, 'speed': .5}, duration=10)
        trace = []
        run(ctl, game, clock, 106, trace=trace)  # six seconds without a model decision
        self.assertTrue(all(trace))
        self.assertEqual(box.actions('wait'), [])

    def test_missed_renewals_inside_the_lease_do_not_stop_motion(self):
        ctl, box, game, clock = make()
        ctl.set_intent({'forward': 1}, duration=10)
        run(ctl, game, clock, 101)
        box.outcomes = [(DEFERRED, False)] * 4  # about a second of writer back-pressure
        trace = []
        run(ctl, game, clock, 103, trace=trace)
        self.assertTrue(all(trace))

    def test_new_decision_retargets_without_a_release(self):
        ctl, box, game, clock = make()
        first = ctl.set_intent({'forward': 1, 'speed': 1}, duration=10)
        run(ctl, game, clock, 101)
        second = ctl.set_intent({'right': 1, 'speed': .3, 'yaw': 90}, duration=10)
        ctl.observe(game.state())  # the game still applies the first generation
        self.assertFalse(second.applied)
        trace = []
        run(ctl, game, clock, 102, trace=trace)
        self.assertEqual(second.generation, first.generation + 1)
        self.assertEqual(box.actions('wait'), [])
        self.assertTrue(all(trace) and second.applied)
        self.assertEqual(game.rx.gen, second.generation)

    def test_policy_rejects_leases_that_cannot_bridge_a_missed_renewal(self):
        for bad in (dict(lease=1.0), dict(lease=2.5, renew_interval=.5), dict(stop_retry=float('nan')),
                    dict(default_intent=40.)):
            with self.assertRaises(ValueError):
                LeasePolicy(**bad)


class Stop(Fence):
    def test_stop_before_a_due_renewal_publishes_no_renewal(self):
        ctl, box, game, clock = make()
        hold = ctl.set_intent({'forward': 1}, duration=10)
        clock.t += .5  # renewal is now due
        release = ctl.stop()
        self.assertEqual(release.generation, hold.generation + 1)
        n = len(box.history)
        ctl.tick()
        self.assertEqual(len(box.history), n)
        run(ctl, game, clock, 104)
        self.assertEqual(box.actions('drive'), box.actions('drive')[:1])
        self.assertTrue(release.acknowledged and release.released)
        self.assertFenced(box)

    def test_stop_during_an_inflight_renewal_publishes_after_it(self):
        ctl, box, game, clock = make()
        hold = ctl.set_intent({'forward': 1}, duration=10)
        gate, entered, out = threading.Event(), threading.Event(), []

        def hook(action, mode):
            if action['action'] == 'drive':
                box.hook = None
                entered.set()
                gate.wait(2)
        box.hook = hook
        clock.t += .5
        ticker = threading.Thread(target=ctl.tick)
        ticker.start()
        self.assertTrue(entered.wait(2))
        stopper = threading.Thread(target=lambda: out.append(ctl.stop()))
        stopper.start()
        for _ in range(200):  # the generation is invalidated before the in-flight write returns
            if ctl.generation == hold.generation + 1:
                break
            time.sleep(.005)
        self.assertEqual(ctl.generation, hold.generation + 1)
        self.assertIsNone(ctl.intent)
        gate.set()
        ticker.join(2)
        stopper.join(2)
        actions = box.actions()
        self.assertEqual(actions[-2]['action'], 'drive')
        self.assertEqual(actions[-1], {'action': 'wait', 'ctl': ctl.controller, 'driveGen': hold.generation + 1,
                                       'reason': 'stop'})
        self.assertTrue(out[0].published)
        self.assertFenced(box)

    def test_reentrant_stop_from_inside_a_publication(self):
        ctl, box, game, clock = make()
        hold = ctl.set_intent({'forward': 1}, duration=10)

        def hook(action, mode):
            if action['action'] == 'drive':
                box.hook = None
                ctl.stop('reentrant')
        box.hook = hook
        clock.t += .5
        started = time.monotonic()
        ctl.tick()
        self.assertLess(time.monotonic() - started, .5)  # no self-wait on the writer lock
        self.assertEqual(box.latest['action']['action'], 'wait')
        self.assertEqual(box.latest['action']['driveGen'], hold.generation + 1)
        self.assertTrue(ctl.release.published)
        self.assertFenced(box)

    def test_inflight_renewal_delivered_after_the_stop_is_rejected(self):
        ctl, box, game, clock = make()
        ctl.set_intent({'forward': 1}, duration=10)
        game.poll()
        stale = dict(box.latest)
        ctl.stop()
        self.assertEqual(game.poll(), 'released')
        self.assertEqual(game.rx.deliver(stale, clock()), 'released_generation')
        self.assertFalse(game.rx.active)

    def test_stop_overwritten_before_the_game_polls_is_reasserted(self):
        ctl, box, game, clock = make()
        ctl.set_intent({'forward': 1}, duration=10)
        game.poll()
        ctl.observe(game.state())
        release = ctl.stop()
        self.assertEqual(ctl.publish_other({'action': 'say', 'text': 'hi'}, 'chat'), (PUBLISHED, ''))
        self.assertEqual(game.poll(), 'ignored')  # the game never saw the stop
        ctl.observe(game.state())
        self.assertFalse(release.acknowledged or release.released)
        clock.t += .5
        ctl.tick()
        self.assertEqual(game.poll(), 'released')
        ctl.observe(game.state())
        self.assertEqual(release.attempts, 2)
        self.assertTrue(release.acknowledged and release.released)
        n = len(box.history)
        run(ctl, game, clock, 104)
        self.assertEqual(len(box.history), n)

    def test_unpublished_release_retries_then_is_reported_unconfirmed(self):
        ctl, box, game, clock = make()
        ctl.set_intent({'forward': 1}, duration=10)
        game.poll()
        box.outcomes = [(FAILED, False)] * 40
        release = ctl.stop()
        run(ctl, game, clock, 104)
        self.assertTrue(release.unconfirmed)
        self.assertFalse(release.published)
        self.assertGreater(release.attempts, 5)
        self.assertFalse(game.rx.active)  # only the last lease bounded the motion
        self.assertEqual(len(box.actions('drive')), 1)

    def test_new_decision_supersedes_an_unacknowledged_release(self):
        ctl, box, game, clock = make()
        ctl.set_intent({'forward': 1}, duration=10)
        box.outcomes = [(FAILED, False)]
        release = ctl.stop()
        hold = ctl.set_intent({'forward': -1}, duration=10)
        run(ctl, game, clock, 103)
        self.assertTrue(release.superseded)
        self.assertEqual(release.attempts, 1)
        self.assertFalse(release.acknowledged or release.released or release.unconfirmed)
        self.assertTrue(hold.applied and game.rx.active)
        self.assertEqual(box.actions('wait'), [box.history[1]['action']])
        self.assertFenced(box)

    def test_game_still_holding_a_released_generation_reopens_retries(self):
        ctl, box, game, clock = make()
        ctl.set_intent({'forward': 1}, duration=10)
        game.poll()
        release = ctl.stop()
        game.poll()
        run(ctl, game, clock, 101)
        self.assertTrue(release.acknowledged and release.released)
        game.rx.active = True  # a broken game reports the old hold again
        n = len(box.history)
        clock.t += .25
        ctl.observe(game.state())
        self.assertFalse(release.released)
        self.assertEqual(box.actions()[n]['action'], 'wait')


class Disconnect(Fence):
    def test_disconnect_stops_renewal_and_nothing_replays_on_reconnect(self):
        ctl, box, game, clock = make()
        hold = ctl.set_intent({'forward': 1}, duration=20)
        run(ctl, game, clock, 101)
        release = ctl.disconnect('bridge_shutdown')
        self.assertTrue(release.published)
        n = len(box.actions('drive'))
        run(ctl, game, clock, 106)
        self.assertEqual(len(box.actions('drive')), n)
        self.assertFalse(game.rx.active)
        again = ctl.set_intent({'forward': 1})  # only a new decision moves again
        self.assertGreater(again.generation, release.generation > hold.generation)
        self.assertFenced(box)

    def test_identity_change_drops_the_intent(self):
        ctl, box, game, clock = make()
        ctl.set_intent({'forward': 1}, duration=20)
        run(ctl, game, clock, 101)
        game.identity['controlEpoch'] += 1  # death, disable or menu toggled the epoch
        run(ctl, game, clock, 103)
        self.assertIsNone(ctl.intent)
        self.assertEqual(ctl.release.reason, 'identity_changed')
        self.assertEqual(box.latest['action']['action'], 'wait')
        self.assertFenced(box)

    def test_not_actionable_drops_the_intent(self):
        ctl, box, game, clock = make()
        ctl.set_intent({'forward': 1}, duration=20)
        game.dead = True
        run(ctl, game, clock, 101)
        self.assertEqual(ctl.release.reason, 'not_actionable')
        self.assertEqual(ctl.set_intent({'forward': 1}).refused, 'not_actionable')

    def test_stale_telemetry_stops_renewal(self):
        ctl, box, game, clock = make()
        ctl.set_intent({'forward': 1}, duration=20)
        while clock.t < 104:
            clock.t += .25
            ctl.tick()
        self.assertEqual(ctl.release.reason, 'telemetry_stale')
        last_wait = max(i for i, a in enumerate(box.actions()) if a['action'] == 'wait')
        self.assertEqual([a for a in box.actions()[last_wait:] if a['action'] == 'drive'], [])
        self.assertFenced(box)


OLD_RUN = 5_000  # a previous controller run's id


def successor(box, clock, counter):
    """A restarted writer: reserves its run under the (implied) writer lock, then reads state."""
    return DirectController(GModAdapter(wall=lambda: WALL), box, run_id=reserve_run(counter), clock=clock)


class RunReservation(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.counter = Path(self.dir.name) / 'controller_run.json'

    def tearDown(self):
        self.dir.cleanup()

    def test_ids_only_grow_and_never_repeat_whatever_the_clock(self):
        self.assertEqual([reserve_run(self.counter, initialize=True), reserve_run(self.counter),
                          reserve_run(self.counter)], [1, 2, 3])
        self.assertEqual(json.loads(self.counter.read_text()), {'run': 3})
        self.assertEqual(sorted(p.name for p in self.counter.parent.iterdir()), ['controller_run.json'])

    def test_missing_or_corrupt_counter_fails_closed(self):
        with self.assertRaises(FileNotFoundError):
            reserve_run(self.counter)  # a lost counter is not silently restarted
        for bad in ('{', '{"run": -1}', '{"run": "7"}', '{"run": 1.5}', '{}', '[]'):
            self.counter.write_text(bad)
            with self.assertRaises((ValueError, KeyError, TypeError)):
                reserve_run(self.counter)
            self.assertEqual(self.counter.read_text(), bad)  # nothing overwritten on doubt

    def test_without_a_run_id_holds_are_refused_but_stops_still_release(self):
        ctl, box, game, clock = make(run_id=None)
        self.assertEqual(ctl.set_intent({'forward': 1}).refused, 'no_controller_run')
        game.rx.deliver({'action': {'action': 'drive', 'ctl': 3, 'gen': 1, 'lease': 1.5}}, clock())
        release = ctl.stop()
        self.assertEqual(box.latest['action'], {'action': 'wait', 'reason': 'stop'})
        self.assertEqual(game.poll(), 'released')  # plain release: inputs stop, nothing fenced
        self.assertTrue(release.published)
        self.assertEqual(box.actions('drive'), [])


class Handover(Fence):
    """Restart while the dead run's traffic is still in transit (review R4)."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.counter = Path(self.dir.name) / 'controller_run.json'

    def tearDown(self):
        self.dir.cleanup()

    def test_successor_outranks_unreported_in_transit_traffic(self):
        old, box, game, clock = make(run_id=reserve_run(self.counter, initialize=True))
        old.set_intent({'forward': 1})
        old.set_intent({'forward': 1})  # generation 2, never polled by the game
        delayed = dict(box.latest)
        new = successor(box, clock, self.counter)
        new.observe(game.state())  # fresh, actionable, and still reports no run at all
        self.assertTrue(new.feedback.actionable)
        self.assertEqual(game.rx.ctl, 0)
        stop = new.stop()  # stop-only restart
        self.assertEqual(game.poll(), 'released')
        self.assertEqual(game.rx.deliver(delayed, clock() + .1), 'retired_controller')
        self.assertFalse(game.rx.active)
        new.observe(game.state())
        self.assertTrue(stop.acknowledged and stop.released)
        hold = new.set_intent({'right': 1})  # a legitimate hold once the successor owns the fence
        game.poll()
        new.observe(game.state())
        self.assertTrue(hold.applied and game.rx.active)
        self.assertEqual(game.rx.deliver(delayed, clock() + .2), 'retired_controller')
        self.assertEqual(game.rx.gen, hold.generation)
        self.assertFenced(box)

    def test_game_already_at_or_above_our_run_fails_closed(self):
        for seen, reason in ((7, 'controller_run_reused'), (8, 'controller_superseded')):
            with self.subTest(seen=seen):
                ctl, box, game, clock = make(run_id=7, before=lambda g: setattr(g.rx, 'ctl', seen))
                self.assertEqual(ctl.retired, reason)
                self.assertEqual(ctl.set_intent({'forward': 1}).refused, reason)
                self.assertEqual(ctl.stop().refused, reason)
                self.assertEqual(box.history, [])

    def test_own_stop_seen_before_first_telemetry_is_not_reuse(self):
        ctl, box, game, clock = make(run_id=None)
        ctl = DirectController(GModAdapter(wall=lambda: WALL), box, run_id=9, clock=clock)
        first = ctl.stop('bridge_start')  # published before this run read any state
        game.poll()
        ctl.observe(game.state())
        self.assertEqual(ctl.retired, '')
        # It had no world to bind to, so the first sample re-issues a release bound to this world.
        self.assertTrue(first.unconfirmed and not first.acknowledged)
        game.poll()
        ctl.observe(game.state())
        self.assertTrue(ctl.release.acknowledged and ctl.release.released)
        self.assertEqual(ctl.release.binding, ctl.feedback.identity)


class InflightFirstPublication(Fence):
    """The game may apply our first envelope before the publisher returns (review R5)."""

    def run_first(self, stop, outcome=None, claim=False):
        ctl, box, game, clock = make(run_id=7)
        seen, during = [], []

        def pending_flags():  # what a concurrent caller could read while judgment is open
            r = ctl.release if stop else ctl.hold
            return r.applied or r.acknowledged

        def publisher(action, mode):
            if claim:  # something else already used id 7 and its counters match ours
                game.rx.ctl = 7
                if stop:
                    game.rx.stop_gen, game.rx.active = action['driveGen'], False
                else:
                    game.rx.gen, game.rx.active, game.rx.expires = action['gen'], True, clock() + 1.5
                ctl.observe(game.state())
                during.append(pending_flags())
                return outcome  # our attempt never left
            result = box(action, mode)  # the mailbox publication has completed
            seen.append(game.poll())
            ctl.observe(game.state())  # the owner loop observes while the ACK is pending
            during.append(pending_flags())
            return result
        ctl._write = publisher
        receipt = ctl.stop() if stop else ctl.set_intent({'forward': 1})
        self.assertEqual(during, [False])  # staged, not committed, until the attempt resolves
        return ctl, receipt, seen

    def test_first_hold_applied_before_its_ack_keeps_the_owner(self):
        ctl, hold, seen = self.run_first(stop=False)
        self.assertEqual((seen, ctl.retired), (['applied'], ''))
        self.assertTrue(hold.published and hold.applied)
        self.assertIsNotNone(ctl.intent)

    def test_first_stop_applied_before_its_ack_keeps_the_owner(self):
        ctl, release, seen = self.run_first(stop=True)
        self.assertEqual((seen, ctl.retired), (['released'], ''))
        self.assertTrue(release.published and release.acknowledged and release.released)

    def test_definitely_unsent_attempt_with_our_id_already_in_game_is_reuse(self):
        for stop in (False, True):
            for outcome in (DEFERRED, REFUSED, FAILED):
                with self.subTest(stop=stop, outcome=outcome):
                    ctl, receipt, _ = self.run_first(stop, outcome, claim=True)
                    self.assertEqual(ctl.retired, 'controller_run_reused')
                    self.assertIsNone(ctl.intent)
                    self.assertFalse(receipt.published)
                    self.assertFalse(receipt.applied or receipt.acknowledged)  # the reused run's, not ours

    def test_possibly_sent_attempt_is_not_reuse(self):
        for outcome in (AMBIGUOUS, PUBLISHED):  # e.g. a TickWriter-queued stop may still land
            with self.subTest(outcome=outcome):
                ctl, release, _ = self.run_first(True, outcome, claim=True)
                self.assertEqual(ctl.retired, '')
                self.assertTrue(release.acknowledged)  # staged evidence committed once ownership holds

    def test_staged_application_survives_a_later_inactive_sample(self):
        ctl, box, game, clock = make(run_id=7)

        def publisher(action, mode):
            result = box(action, mode)
            game.poll()
            ctl.observe(game.state())  # applied
            clock.t += 2
            ctl.observe(game.state())  # lease ran out before the ACK came back
            return result
        ctl._write = publisher
        hold = ctl.set_intent({'forward': 1})
        self.assertTrue(hold.applied)  # historical, genuinely matched application is kept


class Binding(Fence):
    """Evidence and fences belong to one controller run and one actor/world (review R1-R3)."""

    def test_restarted_controller_fences_the_previous_run(self):
        with tempfile.TemporaryDirectory() as d:
            counter = Path(d) / 'controller_run.json'
            first, box, game, clock = make(run_id=reserve_run(counter, initialize=True))
            first.set_intent({'forward': 1})
            game.poll()
            stale = dict(box.latest)
            second = successor(box, clock, counter)
            second.observe(game.state())
            self.assertGreater(second.controller, first.controller)
            release = second.stop()
            game.poll()
            second.observe(game.state())
            self.assertTrue(release.acknowledged and release.released)
            self.assertEqual(game.rx.deliver(stale, clock()), 'retired_controller')
            self.assertFalse(game.rx.active)

    def test_previous_run_counters_neither_apply_nor_acknowledge_this_run(self):
        def old_run(game):
            game.rx.ctl, game.rx.gen, game.rx.stop_gen = OLD_RUN, 1, 100
            game.rx.active, game.rx.expires = True, 1e9
        ctl, box, game, clock = make(before=old_run, run_id=OLD_RUN + 1)
        box.outcomes = [(DEFERRED, False)]
        hold = ctl.set_intent({'forward': 1})  # generation 1 collides with the old run's
        ctl.observe(game.state())
        self.assertFalse(hold.applied)
        box.outcomes = [(DEFERRED, False)] * 2  # the stop and observe()'s immediate retry
        release = ctl.stop()  # generation 2 <= the old run's stopGen 100
        ctl.observe(game.state())
        self.assertFalse(release.published or release.acknowledged or release.released)
        clock.t += .5
        ctl.tick()  # the retry actually reaches the game
        game.poll()
        ctl.observe(game.state())
        self.assertTrue(release.published and release.acknowledged and release.released)
        self.assertEqual(game.rx.ctl, ctl.controller)

    def test_another_actor_is_not_evidence_for_this_hold(self):
        ctl, box, game, clock = make()
        hold = ctl.set_intent({'forward': 1})  # published; this actor has not polled it
        state = game.state()
        state['steamid'] = 'STEAM_0:1:2000'
        state['drive'].update(ctl=ctl.controller, active=True, gen=hold.generation, held=['forward'])
        ctl.observe(state)
        self.assertFalse(hold.applied)
        self.assertEqual(ctl.release.reason, 'identity_changed')  # the new world only invalidates control

    def test_release_evidence_must_come_from_the_released_world(self):
        ctl, box, game, clock = make()
        ctl.set_intent({'forward': 1})
        game.poll()
        box.outcomes = [(DEFERRED, False)]
        first = ctl.stop()
        game.identity['controlEpoch'] += 1
        state = game.state()
        state['drive'].update(ctl=ctl.controller, stopGen=first.generation, active=False, held={})
        ctl.observe(state)
        self.assertFalse(first.acknowledged or first.released)
        self.assertTrue(first.unconfirmed)
        second = ctl.release  # a fresh release fences the new world
        self.assertEqual((second.reason, second.binding[2]), ('identity_changed', 2))
        run(ctl, game, clock, 102)
        self.assertTrue(second.acknowledged and second.released)
        self.assertFenced(box)

    def test_late_world_change_cannot_acknowledge_an_ended_release(self):
        ctl, box, game, clock = make()
        ctl.set_intent({'forward': 1})
        game.poll()
        box.outcomes = [(FAILED, False)] * 40
        release = ctl.stop()
        run(ctl, game, clock, 104)
        self.assertTrue(release.unconfirmed)  # retries ended; nothing will replace this receipt
        game.identity['controlEpoch'] += 1
        state = game.state()
        state['drive'].update(ctl=ctl.controller, stopGen=release.generation, active=False, held={})
        ctl.observe(state)
        self.assertFalse(release.acknowledged)

    def test_superseded_controller_goes_quiet(self):
        ctl, box, game, clock = make()
        ctl.set_intent({'forward': 1})
        run(ctl, game, clock, 101)
        game.rx.ctl = ctl.controller + 1  # a newer run now owns the game's fence
        n = len(box.history)
        clock.t += .25
        ctl.observe(game.state())
        self.assertTrue(ctl.retired)
        self.assertIsNone(ctl.intent)
        self.assertEqual(ctl.set_intent({'forward': 1}).refused, 'controller_superseded')
        self.assertEqual(ctl.stop().refused, 'controller_superseded')
        self.assertEqual(ctl.publish_other({'action': 'say', 'text': 'x'}, 'chat'), (REFUSED, 'controller_superseded'))
        run(ctl, game, clock, 104)
        self.assertEqual(len(box.history), n)


class Arbitration(Fence):
    NAV = {'action': 'navigate', 'id': 'r1', 'points': [{'x': 0, 'y': 0, 'z': 0}], 'lease': 1}

    def test_direct_intent_preempts_tasks_and_one_writer_routes_everything(self):
        calls = []
        ctl, box, game, clock = make(on_task_preempted=calls.append)
        self.assertEqual(ctl.publish_task(self.NAV, 'act'), (PUBLISHED, ''))
        self.assertEqual(ctl.owner, 'task')
        ctl.set_intent({'forward': 1})
        self.assertEqual((calls, ctl.owner), (['direct_control'], 'direct'))
        self.assertEqual(ctl.publish_task(self.NAV, 'act'), (REFUSED, 'direct_active'))
        for move in ({'action': 'move', 'dir': 'forward'}, {'action': 'console', 'cmd': 'NoClip'},
                     {'action': 'wait'}, 'garbage'):
            self.assertEqual(ctl.publish_other(move, 'act'), (REFUSED, 'movement_requires_arbiter'))
        self.assertEqual(ctl.publish_other({'action': 'say', 'text': 'hi'}, 'chat'), (PUBLISHED, ''))
        ctl.stop()
        self.assertEqual(ctl.publish_task(self.NAV, 'act'), (REFUSED, 'stopped'))
        ctl.allow_tasks()
        self.assertEqual(ctl.publish_task(self.NAV, 'act'), (PUBLISHED, ''))

    def test_concurrent_callers_never_overlap_publications(self):
        ctl, box, game, clock = make(clock=time.monotonic)
        errors = []

        def worker(k):
            try:
                for n in range(40):
                    op = (n + k) % 4
                    if op == 0:
                        ctl.set_intent({'forward': 1, 'speed': (n % 10) / 10})
                    elif op == 1:
                        ctl.tick()
                    elif op == 2:
                        ctl.publish_other({'action': 'say', 'text': f'{k}:{n}'}, 'chat')
                    else:
                        ctl.stop()
                    game.poll()
                    ctl.observe(game.state())
            except Exception as exc:  # surfaced below
                errors.append(exc)
        threads = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        final = ctl.stop()
        self.assertEqual(errors, [])
        self.assertEqual(box.peak, 1)
        self.assertEqual(box.latest['action'], {'action': 'wait', 'ctl': ctl.controller,
                                                'driveGen': final.generation, 'reason': 'stop'})
        self.assertFenced(box)


class Receipts(Fence):
    def test_publication_application_and_release_are_distinct(self):
        ctl, box, game, clock = make()
        hold = ctl.set_intent({'forward': 1})
        self.assertTrue(hold.published)
        ctl.observe(game.state())  # published, but the game has not polled yet
        self.assertFalse(hold.applied)
        game.poll()
        ctl.observe(game.state())
        self.assertTrue(hold.applied)
        release = ctl.stop()
        self.assertTrue(release.published)
        ctl.observe(game.state())  # still held until the game processes the stop
        self.assertFalse(release.acknowledged or release.released)
        game.poll()
        ctl.observe(game.state())
        self.assertTrue(release.acknowledged and release.released)

    def test_ambiguous_publication_is_not_counted_until_the_game_reports_it(self):
        ctl, box, game, clock = make()
        box.outcomes = [(AMBIGUOUS, True)]
        hold = ctl.set_intent({'forward': 1})
        self.assertEqual((hold.transport, hold.published, hold.applied), (AMBIGUOUS, False, False))
        game.poll()
        ctl.observe(game.state())
        self.assertTrue(hold.applied)

    def test_without_drive_telemetry_nothing_is_claimed(self):
        ctl, box, game, clock = make(drive=False)
        self.assertEqual(ctl.set_intent({'forward': 1}).refused, 'drive_unsupported')
        self.assertEqual(box.actions('drive'), [])
        release = ctl.stop()
        run(ctl, game, clock, 103)
        self.assertEqual((release.published, release.attempts), (True, 1))
        self.assertFalse(release.acknowledged or release.released)

    def test_malformed_drive_block_is_not_evidence(self):
        ctl, box, game, clock = make()
        ctl.set_intent({'forward': 1})
        game.poll()
        release = ctl.stop()
        game.poll()
        state = game.state()
        state['drive'] = {'v': 1, 'active': False, 'held': []}  # no generations reported
        ctl.observe(state)
        self.assertFalse(release.acknowledged or release.released)

    def test_refusals_publish_nothing_and_keep_the_generation(self):
        ctl, box, game, clock = make()
        for params in ({'forward': 2}, {'speed': float('inf')}, {'jump': 'big'}, {'crouch': 1},
                       {'fly': True}, {'forward': True}, None):
            r = ctl.set_intent(params)
            self.assertTrue(r.refused.startswith('invalid: '), (params, r.refused))
        self.assertTrue(ctl.set_intent({'forward': 1}, duration=0).refused.startswith('invalid: '))
        self.assertEqual((ctl.generation, box.history), (0, []))
        clock.t += 4  # telemetry now stale
        self.assertEqual(ctl.set_intent({'forward': 1}).refused, 'no_fresh_state')


class Adapter(unittest.TestCase):
    def test_validate_normalizes_and_bounds(self):
        p = validate({'forward': 1, 'right': 1, 'yaw': -90, 'pitch': 120})
        self.assertAlmostEqual(p['forward'], 2 ** -.5)
        self.assertAlmostEqual(p['right'], 2 ** -.5)
        self.assertEqual((p['yaw'], p['pitch'], p['speed'], p['jump'], p['mode']), (270., 89., .5, 'none', None))
        self.assertEqual(validate({'mode': 'noclip', 'up': -1, 'jump': 'tap'})['mode'], 'noclip')

    def test_hold_action_shape_and_lease_floor(self):
        from greg_controller_core import Intent
        adapter = GModAdapter()
        intent = Intent(7, validate({'forward': 1, 'yaw': 10, 'jump': 'hold', 'mode': 'walk'}), 0, 10, ())
        action, mode = adapter.hold_action(intent, .4999, 42)
        self.assertEqual(mode, 'direct')
        self.assertEqual(action, {'action': 'drive', 'v': 1, 'ctl': 42, 'gen': 7, 'lease': .499,
                                  'move': {'forward': 1., 'right': 0., 'up': 0., 'speed': .5},
                                  'jump': 'hold', 'crouch': False, 'look': {'yaw': 10., 'rate': 180.},
                                  'mode': 'walk'})
        self.assertEqual(adapter.release_action(8, 'stop', 42),
                         ({'action': 'wait', 'ctl': 42, 'driveGen': 8, 'reason': 'stop'}, 'stop'))

    def test_bridge_publisher_maps_write_cmd_outcomes_and_keeps_the_recorder(self):
        recorded, seqs = [], iter(range(1, 100))

        def recorder(payload, **status):
            recorded.append(status.get('write_result'))

        def make_write(ret, status=None):
            def write(path, seq, action, state, session, mode, *, observer=None):
                if status is not None:
                    observer({'seq': seq, 'action': action}, **status)
                return ret
            return write
        cases = [(make_write(True, dict(write_result='written')), PUBLISHED),
                 (make_write(None, dict(write_result='written')), PUBLISHED),
                 (make_write(False, dict(write_result='failed', reason='remote_publication_unconfirmed')), AMBIGUOUS),
                 (make_write(False, dict(write_result='failed', reason='write_retries_exhausted')), FAILED),
                 (make_write(False, dict(write_result='suppressed', reason='speech_dedup')), REFUSED),
                 (make_write(False), DEFERRED)]
        for write, expected in cases:
            publish = bridge_publisher(write, 'cmd.json', lambda: next(seqs), lambda: {'steamid': 'x'}, 's',
                                       chain=lambda: recorder)
            self.assertEqual(publish({'action': 'say'}, 'chat'), expected)
        self.assertEqual(recorded, ['written', 'written', 'failed', 'failed', 'suppressed'])
        # TickWriter queues a held-back stop and replays it: it may still reach the game.
        held_stop = bridge_publisher(make_write(False), 'cmd.json', lambda: 1, lambda: {'steamid': 'x'}, 's')
        self.assertEqual(held_stop({'action': 'wait', 'ctl': 1, 'driveGen': 2}, 'stop'), AMBIGUOUS)
        no_state = bridge_publisher(make_write(True), 'cmd.json', lambda: 1, lambda: None, 's')
        self.assertEqual(no_state({'action': 'say'}, 'chat'), REFUSED)


class ReceiverRule(unittest.TestCase):
    def test_shared_receiver_cases(self):
        for case in CASES:
            with self.subTest(case['name']):
                rx, now = DriveReceiver(), 0.
                for step in case['steps']:
                    if 'advance' in step:
                        now += step['advance']
                        rx.expire(now)
                    else:
                        self.assertEqual(rx.deliver({'action': step['action']}, now), step['expect'])
                self.assertEqual({'active': rx.active, 'ctl': rx.ctl, 'gen': rx.gen, 'stopGen': rx.stop_gen},
                                 case['final'])


if __name__ == '__main__':
    unittest.main()
