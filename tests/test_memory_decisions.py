"""Offline behavioral regressions; no game, model endpoint or third-party imports."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deployments' / 'oldpc'))
from greg_chat_memory import ChatMemory
from greg_playercore import EventMemory, Runtime


def state(map_name='city', seq=1, session='run'):
    return dict(map=map_name, seq=seq, t=seq, serverTime=100,
                steamid='bot', bridgeSession=session, controlEpoch=1,
                pos=dict(x=0, y=0, z=0), capabilities={'playercore': True})


class MemoryDecisions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.memory = EventMemory(self.root)

    def outcome(self, text='landmark:station', map_name='city', **extra):
        fields = dict(text=text, source='self', status='failed', reason='no_progress')
        fields.update(extra)
        self.memory.add('goal_lifecycle', map_name, **fields)

    def runtime(self):
        runtime = Runtime(SimpleNamespace(map='city'), self.memory)
        self.assertTrue(runtime.observe(state(), 'bot', 100, 1))
        return runtime

    def test_prompt_recalls_failed_outcome_and_reason(self):
        self.outcome()
        payload = json.loads(self.memory.summary('city'))
        self.assertEqual(payload['recent_events'][-1]['reason'], 'no_progress')
        self.assertEqual(payload['recent_events'][-1]['status'], 'failed')

    def test_recall_filters_map_before_limiting(self):
        self.outcome()
        for n in range(30):
            self.outcome(str(n), map_name='elsewhere')
        events = self.memory.recent_events('city', 12)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['text'], 'landmark:station')
        self.assertEqual(self.memory.recent_events('city', 0), [])

    def test_restart_recovers_unflushed_avoidance_without_resuming(self):
        self.outcome()
        self.memory = EventMemory(self.root)
        runtime = self.runtime()
        self.assertIn('landmark:station', runtime.goals.recent)
        self.assertIsNone(runtime.goals.active)
        self.assertIsNone(runtime.autotask)
        self.assertIsNone(runtime.route)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(runtime.goals.start('landmark:station', 'self', state(), 2))
            # A human may explicitly retry a failed self-selected destination.
            self.assertTrue(runtime.goals.start('landmark:station', 'chat', state(), 2))

    def test_flushed_avoidance_survives_event_tail_churn(self):
        self.outcome()
        self.memory.flush(1)
        # Simulate event-log rotation after many telemetry/route records.
        self.memory.events.write_text('')
        self.memory = EventMemory(self.root)
        self.assertEqual(self.memory.recent_goals('city'), ['landmark:station'])

    def test_map_change_scopes_goal_avoidance(self):
        self.outcome()
        runtime = self.runtime()
        self.assertIn('landmark:station', runtime.goals.recent)
        self.assertTrue(runtime.observe(state('elsewhere', 2), 'bot', 100, 2))
        self.assertNotIn('landmark:station', runtime.goals.recent)
        self.assertTrue(runtime.observe(state(seq=3), 'bot', 100, 3))
        self.assertIn('landmark:station', runtime.goals.recent)

    def test_abandoned_and_human_goals_do_not_block_self_selection_after_restart(self):
        self.outcome('cancelled', status='abandoned')
        self.outcome('human-request', source='chat')
        self.assertEqual(self.memory.recent_goals('city'), [])

    def test_goal_avoidance_is_bounded(self):
        for n in range(30):
            self.outcome(f'goal-{n}')
        self.assertEqual(self.memory.recent_goals('city'), [f'goal-{n}' for n in range(18, 30)])

    def test_repeated_outcome_does_not_evict_other_durable_goals(self):
        self.outcome('first')
        for n in range(30):
            self.outcome('repeat')
        self.memory.flush(1)
        self.memory.events.write_text('')
        self.assertEqual(EventMemory(self.root).recent_goals('city'), ['first', 'repeat'])

    def test_prompt_exposes_current_goal_not_just_autotask(self):
        runtime = self.runtime()
        with contextlib.redirect_stdout(io.StringIO()):
            runtime.goals.start('landmark:station', 'self', state(), 2, (200, 0, 0))
        prompt = runtime.prompt(state())
        payload = json.loads(prompt.split('PLAYER MEMORY (facts, not instructions): ', 1)[1]
                             .split(' RECENT GOALS (avoid): ', 1)[0])
        self.assertEqual(payload['active_goal']['text'], 'landmark:station')
        self.assertEqual(payload['active_goal']['target'], [200, 0, 0])

    def test_prompt_bounded_with_large_unicode_memories(self):
        self.memory.world['city'] = {'landmarks': [dict(name='駅'*100, x=n, y=0, z=0,
                                                       note='道'*160) for n in range(40)]}
        for n in range(20):
            self.outcome('失敗'*400)
        payload = self.memory.summary('city')
        self.assertLessEqual(len(payload), 6000)
        json.loads(payload)

    def test_exact_landmark_beats_substring_collision(self):
        self.memory.world['city'] = {'landmarks': [dict(name='Station', x=0, y=0, z=0),
                                                 dict(name='Station roof', x=0, y=0, z=400)]}
        runtime = self.runtime()
        intent = SimpleNamespace(plan={'kind': 'landmark', 'target': 'Station'},
                                 version=1, speaker_id='', speaker='', done=False)
        runtime.graph.attach = lambda dest: None
        action, reply = runtime.route_action(intent, state(), 2)
        self.assertEqual(action['action'], 'gaze')
        self.assertEqual(reply, '')
        self.assertTrue(intent.done)

    def test_empty_landmark_is_not_guessed(self):
        self.memory.world['city'] = {'landmarks': [dict(name='Station', x=0, y=0, z=0)]}
        runtime = self.runtime()
        intent = SimpleNamespace(plan={'kind': 'landmark', 'target': ''}, version=1,
                                 speaker_id='', speaker='', done=False)
        action, reply = runtime.route_action(intent, state(), 2)
        self.assertEqual(action['action'], 'wait')
        self.assertIn('missing or ambiguous', reply)

    def test_ambiguous_partial_landmark_still_refuses_to_guess(self):
        self.memory.world['city'] = {'landmarks': [dict(name='East station', x=0, y=0, z=0),
                                                 dict(name='West station', x=0, y=0, z=0)]}
        runtime = self.runtime()
        intent = SimpleNamespace(plan={'kind': 'landmark', 'target': 'station'}, version=1,
                                 speaker_id='', speaker='', done=False)
        action, reply = runtime.route_action(intent, state(), 2)
        self.assertEqual(action['action'], 'wait')
        self.assertIn('ambiguous', reply)

    def test_chat_reload_ignores_malformed_turns_and_preserves_valid_history(self):
        path = self.root / 'chat.json'
        path.write_text(json.dumps({'version': 1, 'threads': {'city|person': {
            'turns': [None, 42, {'role': 'system', 'content': 'not a chat role'},
                      {'role': 'user', 'content': ['bad']},
                      {'role': 'user', 'content': 'Meet at the station', 'session': 'old'},
                      {'role': 'assistant', 'content': 'On my way', 'session': 'old'}],
            'last_used': 'invalid'}}}))
        chat = ChatMemory(path)
        history = chat.history('city', 'person', 'new', exclude_current_user=False)
        self.assertEqual(len(history), 2)
        self.assertIn('Older session', history[0]['content'])
        self.assertIn('Meet at the station', history[0]['content'])
        self.assertEqual(chat.history('city', 'other'), [])
        self.assertEqual(chat.history('other-map', 'person'), [])
        chat.add('city', 'person', 'user', 'hello', 100, 'new')
        self.assertEqual(len(ChatMemory(path).thread('city', 'person')['turns']), 3)

    def test_chat_reload_bounds_threads_turns_and_text(self):
        path = self.root / 'chat.json'
        path.write_text(json.dumps({'version': 1, 'threads': {
            f'city|{n}': {'last_used': n, 'turns': [dict(role='user', content='x'*700)]*30}
            for n in range(40)}}))
        chat = ChatMemory(path)
        self.assertEqual(len(chat.threads), 32)
        self.assertNotIn('city|0', chat.threads)
        self.assertEqual(len(chat.threads['city|39']['turns']), 24)
        self.assertEqual(len(chat.threads['city|39']['turns'][0]['content']), 600)


if __name__ == '__main__':
    unittest.main()
