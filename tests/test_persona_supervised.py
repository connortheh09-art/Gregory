"""The persona actually reaches the live path, and lean actions never need a model.

Stdlib unittest on purpose: this box has no pytest, and a test run nobody can see is
not a test run. Runnable as:
    python3 -m unittest tests.test_persona_supervised -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deployments" / "oldpc"))

import greg_model
from gregory_core import persona as p
from gregory_core.runtime import LMStudioProvider

PROFILE = {"persona": p.LEGACY_DEFAULT, "goals": []}


class Resp:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": '{"say": "hi", "used_memory_ids": []}'}}]}


class PersonaTests(unittest.TestCase):
    def tearDown(self):
        p._cache.update(key=None, sections={})
        os.environ.pop("GREG_PERSONA_PATH", None)

    def test_persona_file_loads(self):
        self.assertTrue(p.identity().startswith("You are Gregory."))
        self.assertIn("dry, quick, and genuinely funny", p.identity())
        self.assertIn("Garry's Mod", p.guide())

    def test_no_ai_framing_reaches_a_call(self):
        system = p.speech_system(PROFILE)
        self.assertNotIn("AI character", system)
        self.assertNotIn("AI character", p.identity())

    def test_legacy_stub_is_replaced_and_owner_text_wins(self):
        self.assertTrue(p.base_persona(None).startswith("You are Gregory."))
        self.assertTrue(p.base_persona(p.LEGACY_DEFAULT).startswith("You are Gregory."))
        self.assertEqual(p.base_persona("Mine."), "Mine.")

    def test_speech_system_keeps_replay_hardened_rules(self):
        system = p.speech_system(PROFILE)
        self.assertTrue(system.startswith("You are Gregory."))
        for rule in ("used_memory_ids", "A proposed intent is not execution",
                     "empty life history", "architectural metaphor"):
            self.assertIn(rule, system)

    def test_temperatures_split_by_job(self):
        calls = []

        def fake_post(endpoint, json=None, timeout=None):
            calls.append(json)
            return Resp()

        with mock.patch.object(greg_model, "post_chat", fake_post):
            provider = LMStudioProvider("http://127.0.0.1:1234/v1", "google/gemma-4-12b-qat")
            provider.generate(PROFILE, "hi")
            provider.generate(PROFILE, "hi", response_schema={"type": "object"})
        self.assertEqual(calls[0]["temperature"], 0.85)
        self.assertEqual(calls[1]["temperature"], 0.4)
        self.assertTrue(calls[0]["messages"][0]["content"].startswith("You are Gregory."))

    def test_lean_actions_need_no_model(self):
        self.assertEqual(p.lean_action("stop"), {"action": "wait"})
        self.assertEqual(p.lean_action("Stop now!"), {"action": "wait"})
        self.assertTrue(p.lean_action("jump")["jump"])

        walk = p.lean_action("walk forward 3s")
        self.assertEqual((walk["action"], walk["dir"], walk["duration"], walk["walk"]),
                         ("move", "forward", 3.0, True))

        run = p.lean_action("run back 2 seconds")
        self.assertEqual((run["dir"], run["sprint"], run["duration"]), ("back", True, 2.0))

    def test_lean_actions_reject_complex(self):
        for text in ("", "find a door that opens", "use the blue car", "spawn a barrel"):
            self.assertIsNone(p.lean_action(text), text)

    def test_parse_brain(self):
        self.assertEqual(p.parse_brain("SAY: **hi**\nDO: walk forward 3s"), ("hi", "walk forward 3s", ""))
        self.assertEqual(p.parse_brain("noise\nGOAL: climb the crane"), ("", "", "climb the crane"))
        self.assertEqual(p.parse_brain(""), ("", "", ""))

    def test_persona_changes_without_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "persona.md"
            override.write_text("# Gregory\n\nA different Gregory tonight.\n", encoding="utf-8")
            os.environ["GREG_PERSONA_PATH"] = str(override)
            p._cache.update(key=None, sections={})
            self.assertEqual(p.identity(), "A different Gregory tonight.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
