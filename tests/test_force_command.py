"""Force phrases bypass Gregory; ordinary stop does not.

Connor's rule: plain 'stop' is a request he may argue about. 'Gregory force stop' is
owner-only, matches loosely for Whisper, and never reaches the model — or the queue.
"""

import sys
import threading
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "deployments" / "oldpc")]

from greg_voice_protocol import force_action, force_command  # noqa: E402
from gmod_bridge import apply_control  # noqa: E402
from greg_supervised import SupervisedLane, force_intent, force_outcome  # noqa: E402
from gregory_core import persona as p  # noqa: E402


class ForcePhraseTests(unittest.TestCase):
    def test_force_stop_variants(self):
        for text in ("Gregory, force stop", "force stop", "forced stop", "force, stop",
                     "force stop now", "Gregory force stop please"):
            with self.subTest(text=text):
                self.assertEqual(force_command(text), "stop")

    def test_force_back_variants(self):
        for text in ("Gregory, force backwards", "force back", "force back up",
                     "force backup", "force, back", "gregory force backwards"):
            with self.subTest(text=text):
                self.assertEqual(force_command(text), "back")

    def test_fused_and_loose_stop_variants(self):
        # Whisper's two live misses: a fused token, and the command followed by commentary.
        for text in ("forstop", "Forstop!", "forcestop", "force-stop", "Force stop because I said so",
                     "force stop moving now", "force halt, we're done"):
            with self.subTest(text=text):
                self.assertEqual(force_command(text), "stop")

    def test_lead_in_words_still_land(self):
        # Live speech rarely starts with the command itself.
        for text in ("Okay Gregory, force stop", "uh force stop", "Greg, force stop",
                     "Gregory's force stop", "hey gregory force stop now"):
            with self.subTest(text=text):
                self.assertEqual(force_command(text), "stop")

    def test_fused_back_must_be_the_whole_command(self):
        # Grady's catch: the fused form was ignoring everything after it.
        for text in ("forcebackup the files", "forceback and then walk forward"):
            with self.subTest(text=text):
                self.assertIsNone(force_command(text))
        self.assertEqual(force_command("forceback"), "back")
        self.assertEqual(force_command("forceback now"), "back")

    def test_force_back_stays_strict(self):
        for text in ("force back", "force backwards please", "force back up now"):
            with self.subTest(text=text):
                self.assertEqual(force_command(text), "back")
        for text in ("force it back", "force back, then walk forward", "force backup the files"):
            with self.subTest(text=text):
                self.assertIsNone(force_command(text))

    def test_plain_requests_are_not_force(self):
        for text in ("stop", "stop now", "wait", "stay close", "don't force it",
                     "force field", "for stop", "force stopping", "walk forward 3s", "back up", ""):
            with self.subTest(text=text):
                self.assertIsNone(force_command(text))

    def test_force_actions(self):
        self.assertEqual(force_action("stop"), {"action": "wait", "mode": "stop"})
        back = force_action("back")
        self.assertEqual((back["action"], back["dir"], back["mode"]), ("move", "back", "stop"))

    def test_persona_states_the_exception(self):
        identity = p.identity()
        self.assertIn("suggestion from a friend, not an order from a boss", identity)
        self.assertIn("force command", identity)
        self.assertNotIn("If someone tells you to stop, stop", p.guide())


class FakeAgenda:
    def __init__(self):
        self.holds = []

    def hold(self, now, seconds=60):
        self.holds.append((now, seconds))


class FakeAuthority:
    def __init__(self):
        self.events = []
        self.agenda = FakeAgenda()


class FakeController:
    def __init__(self):
        self.stops = []

    def stop(self, reason="stop"):
        self.stops.append(reason)


class FakeDelivery:
    config = {'owner_id': 'owner', 'guild_id': 'g', 'channel_id': 'c'}

    def stamp(self):
        return ('conn', 1)


class BlockedFuture:
    """A decision still in progress; its result is stale by the time it lands."""

    def __init__(self, generation):
        self.generation = generation
        self.finished = False
        self.release = threading.Event()

    def done(self):
        return self.finished

    def result(self):
        return dict(say="Walking forward.", game_intent={"action": "drive", "forward": 1.0})


def fake_trace():
    return SimpleNamespace(correlation_id='c1', run_id='r1',
                           control=SimpleNamespace(map_name='gm_construct', bridge_session='s1',
                                                   control_epoch=0))


def fake_lane():
    lane = SupervisedLane.__new__(SupervisedLane)
    lane.delivery = FakeDelivery()
    lane.queue = deque(maxlen=4)
    lane.imports = deque()
    lane.pending_imports = {}
    lane.dialogue = deque(maxlen=8)
    lane.unanswered_voice = deque(maxlen=4)
    lane.voice_input_sequence = 0
    lane.log = lambda message: None
    lane.last_owner_voice = -float('inf')
    lane.generation = 0
    lane.future, lane.request, lane.ready = None, None, None
    lane.force_pending = None
    lane.force_hold_seconds = 15.0
    lane.lock = threading.Lock()
    lane.game_authority = FakeAuthority()
    lane.game_tasks = None
    lane.control = FakeController()
    return lane


def voice_meta(**overrides):
    meta = dict(author_id='owner', guild_id='g', channel_id='c', connection='conn',
                generation=1, request_id='r1', captured_at=0)
    meta.update(overrides)
    return meta


class ForceOutcomeTests(unittest.TestCase):
    def test_holds_agenda_records_event_and_returns_control_intent(self):
        authority = FakeAuthority()
        row = force_outcome("stop", authority=authority, now=100.0)
        self.assertEqual(row["game_intent"], {"action": "control", "command": "stop"})
        self.assertFalse(row["dispatched"])
        self.assertEqual(authority.agenda.holds, [(100.0, 15.0)])
        self.assertEqual(authority.events[-1]["kind"], "force_stop")

    def test_stop_calls_the_controller_which_owns_the_hold(self):
        lane = fake_lane()
        lane.hear_voice("Gregory force stop", voice_meta())
        self.assertEqual(lane.control.stops, ["owner_force"])

    def test_back_is_a_drive_not_a_command(self):
        intent = force_intent("back")
        self.assertEqual(intent["command"], "drive")
        self.assertEqual(intent["move"], "back")
        self.assertEqual((intent["seconds"], intent["task"]), (2, "pause"))

    def test_model_cannot_be_involved(self):
        import inspect
        params = inspect.signature(force_outcome).parameters
        self.assertNotIn("core", params)
        self.assertNotIn("provider", params)


class ForceAdmissionTests(unittest.TestCase):
    def test_force_is_answered_immediately_and_ahead_of_a_blocked_decision(self):
        # Gordon's live bug: the force row must not wait for the 4s decision, and the
        # decision must not move him afterwards.
        lane = fake_lane()
        blocked = BlockedFuture(lane.generation)
        lane.future = blocked
        lane.request = dict(kind="chat", text="walk forward", generation=lane.generation, trace=None)

        self.assertTrue(lane.hear_voice("Gregory force stop", voice_meta()))
        lane.poll()

        row = lane.take()
        self.assertIsNotNone(row, "force intent must be available while the decision is blocked")
        self.assertEqual(row["game_intent"], {"action": "control", "command": "stop"})
        self.assertFalse(blocked.finished, "the decision was still running")

        # The late decision lands now; the generation bump must drop it.
        blocked.finished = True
        lane.poll()
        self.assertIsNone(lane.take())

    def test_force_never_enters_the_queue(self):
        lane = fake_lane()
        self.assertTrue(lane.hear_voice("Gregory force stop", voice_meta()))
        self.assertEqual(len(lane.queue), 0)
        self.assertIsNotNone(lane.force_pending)

    def test_plain_stop_still_queues_for_the_brain(self):
        lane = fake_lane()
        def hear(text):
            lane.queue.append(dict(kind="chat", text=text, trace=fake_trace(), generation=lane.generation,
                                   delivery_stamp=lane.delivery.stamp()))
            return True

        lane.tracker = SimpleNamespace(close=lambda *a, **k: None, begin_decision=lambda **k: fake_trace(),
                                       _emit=lambda *a, **k: None)
        lane.hear = hear
        self.assertTrue(lane.hear_voice("stop", voice_meta()))
        self.assertEqual(len(lane.queue), 1)
        self.assertIsNone(lane.force_pending)
        self.assertNotEqual(lane.last_owner_voice, -float('inf'))

    def test_force_does_not_start_the_voice_quiet_clock(self):
        lane = fake_lane()
        self.assertTrue(lane.hear_voice("Gregory force stop", voice_meta()))
        self.assertEqual(lane.last_owner_voice, -float('inf'))

    def test_force_is_owner_only(self):
        lane = fake_lane()
        self.assertFalse(lane.hear_voice("Gregory force stop", voice_meta(author_id='someone-else')))
        self.assertIsNone(lane.force_pending)


class FakeControl:
    def __init__(self):
        self.applied = []

    def apply(self, intent, view, latest):
        self.applied.append(intent)
        return dict(generation=1, noop=False)


class FakeNotes:
    def __init__(self):
        self.notes = []

    def note(self, *args, **kwargs):
        self.notes.append((args, kwargs))


class ForceControlPublicationTests(unittest.TestCase):
    def force_row(self, **overrides):
        row = dict(request=dict(voice_metadata={'request_id': 'r1', 'author_id': 'owner'},
                               delivery_stamp=None),
                   say='', game_intent=force_intent('back'), force=True)
        row.update(overrides)
        return row

    def test_force_back_is_applied_without_an_offer(self):
        # apply_control refuses non-stop commands unless control was offered; a force
        # row is the owner's override, so it must not need the offer.
        control, logs = FakeControl(), []
        out = apply_control(self.force_row(), {}, control, None, None, FakeNotes(), logs.append, 10.0)
        self.assertEqual(out['task_outcome']['verdict'], 'accepted')
        self.assertEqual(out['say'], '')
        self.assertEqual(control.applied[0]['move'], 'back')

    def test_back_without_force_still_needs_the_offer(self):
        control, logs = FakeControl(), []
        out = apply_control(self.force_row(force=False), {}, control, None, None, FakeNotes(), logs.append, 10.0)
        self.assertEqual(out['task_outcome']['verdict'], 'refused')
        self.assertIn("can't move like that", out['say'])


    def test_force_stop_does_not_get_the_60s_0025_hold(self):
        # force_outcome already held 15s; apply_control's default hold would override it.
        agenda = FakeAgenda()
        control, logs = FakeControl(), []
        row = dict(request=dict(voice_metadata={'request_id': 'r1', 'author_id': 'owner'},
                                delivery_stamp=None),
                   say='', game_intent={'action': 'control', 'command': 'stop'}, force=True)
        out = apply_control(row, {}, control, None, None, FakeNotes(), logs.append, 10.0, agenda)
        self.assertEqual(out['task_outcome']['verdict'], 'accepted')
        self.assertEqual(agenda.holds, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
