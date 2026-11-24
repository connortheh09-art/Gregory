"""Force phrases bypass Gregory; ordinary stop does not.

Connor's rule: plain 'stop' is a request he may argue about. 'Gregory force stop' is
owner-only, matches loosely for Whisper, and never reaches the model.
"""

import sys
import unittest
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "deployments" / "oldpc")]

from greg_voice_protocol import force_action, force_command  # noqa: E402
from greg_supervised import SessionWindow, SupervisedLane, force_intent, force_outcome  # noqa: E402
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

    def test_plain_requests_are_not_force(self):
        for text in ("stop", "stop now", "wait", "stay close", "don't force it",
                     "force field", "walk forward 3s", "back up", ""):
            with self.subTest(text=text):
                self.assertIsNone(force_command(text))

    def test_force_actions(self):
        self.assertEqual(force_action("stop"), {"action": "wait", "mode": "stop"})
        back = force_action("back")
        self.assertEqual((back["action"], back["dir"], back["mode"]), ("move", "back", "stop"))

    def test_force_preempts_a_draining_window(self):
        # A force phrase is admitted even while the session window is draining.
        self.assertTrue(SessionWindow.admits(True, "directive", "Gregory force stop"))
        self.assertFalse(SessionWindow.admits(True, "directive", "nice weather"))

    def test_plain_stop_still_reaches_the_brain(self):
        # Not force: it goes through the normal path, where he may argue about it.
        self.assertIsNone(force_command("stop"))
        self.assertTrue(p.base_persona(None).count("suggestion from a friend") == 1)

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


class FakeTasks:
    def __init__(self):
        self.holds = []

    def hold(self, now, seconds=60):
        self.holds.append((now, seconds))


class FakeController:
    def __init__(self):
        self.stops = []

    def stop(self, reason="stop"):
        self.stops.append(reason)


class ForceOutcomeTests(unittest.TestCase):
    def test_holds_agenda_records_event_and_returns_control_intent(self):
        authority, tasks = FakeAuthority(), FakeTasks()
        row = force_outcome("stop", authority=authority, tasks=tasks, now=100.0)
        self.assertEqual(row["game_intent"], {"action": "control", "command": "stop"})
        self.assertFalse(row["dispatched"])
        # Nothing restarts him: autonomous picks are held for the configured 15s.
        self.assertEqual(authority.agenda.holds, [(100.0, 15.0)])
        self.assertEqual(tasks.holds, [(100.0, 15.0)])
        # He finds out afterwards, as an event he can complain about next turn.
        self.assertEqual(authority.events[-1]["kind"], "force_stop")
        self.assertEqual(authority.events[-1]["command"], "stop")

    def test_stop_calls_the_controller_which_owns_the_hold(self):
        controller = FakeController()
        force_outcome("stop", controller=controller, now=1.0)
        self.assertEqual(controller.stops, ["owner_force"])

    def test_back_is_a_drive_not_a_command(self):
        # gmod_controller.validate() takes forward/right in -1..1; whole seconds 1..30.
        intent = force_intent("back")
        self.assertEqual(intent["command"], "drive")
        self.assertEqual(intent["move"], "back")
        self.assertEqual((intent["seconds"], intent["task"]), (2, "pause"))
        row = force_outcome("back", authority=object(), tasks=None, now=1.0)
        self.assertEqual(row["game_intent"]["move"], "back")

    def test_model_cannot_be_involved(self):
        import inspect
        params = inspect.signature(force_outcome).parameters
        self.assertNotIn("core", params)
        self.assertNotIn("provider", params)

    def test_missing_hooks_do_not_block_the_stop(self):
        row = force_outcome("back", authority=object(), tasks=None, now=1.0)
        self.assertEqual(row["game_intent"]["move"], "back")


class FakeDelivery:
    config = {'owner_id': 'owner', 'guild_id': 'g', 'channel_id': 'c'}

    def stamp(self):
        return ('conn', 1)


def fake_lane():
    lane = SupervisedLane.__new__(SupervisedLane)
    lane.delivery = FakeDelivery()
    lane.queue = deque(maxlen=4)
    lane.log = lambda message: None
    lane.last_owner_voice = -float('inf')
    lane.generation = 0
    lane.force_hold_seconds = 15.0

    def hear(text):
        lane.queue.append(dict(kind='chat', text=text, generation=lane.generation))
        return True

    lane.hear = hear
    return lane


def voice_meta(**overrides):
    meta = dict(author_id='owner', guild_id='g', channel_id='c', connection='conn',
                generation=1, request_id='r1', captured_at=0)
    meta.update(overrides)
    return meta


class ForceAdmissionTests(unittest.TestCase):
    def test_force_is_tagged_for_the_model_free_path(self):
        lane = fake_lane()
        self.assertTrue(lane.hear_voice('Gregory force stop', voice_meta()))
        self.assertEqual(lane.queue[-1]['force'], 'stop')

    def test_force_does_not_start_the_voice_quiet_clock(self):
        # 0027 quietens the agenda for --agenda-voice-quiet after an owner turn.
        # A force command has its own shorter hold, so it must not touch that timer.
        lane = fake_lane()
        self.assertTrue(lane.hear_voice('Gregory force stop', voice_meta()))
        self.assertEqual(lane.last_owner_voice, -float('inf'))

    def test_force_is_owner_only(self):
        lane = fake_lane()
        self.assertFalse(lane.hear_voice('Gregory force stop', voice_meta(author_id='someone-else')))
        self.assertEqual(len(lane.queue), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
