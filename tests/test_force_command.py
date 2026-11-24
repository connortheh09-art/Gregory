"""Force phrases bypass Gregory; ordinary stop does not.

Connor's rule: plain 'stop' is a request he may argue about. 'Gregory force stop' is
owner-only, matches loosely for Whisper, and never reaches the model.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "deployments" / "oldpc")]

from greg_voice_protocol import force_action, force_command  # noqa: E402
from greg_supervised import SessionWindow  # noqa: E402
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
