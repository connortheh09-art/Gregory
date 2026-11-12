from contextlib import closing
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
from gregory_core.runtime import Core, FixtureProvider
from gregory_core.supervised_game import react, RecordingRefused
from core_fixture_experience import capture_fixture
from greg_recorder import open_reader, read_events


class Provider(FixtureProvider):
    def generate(self, profile, prompt):
        self.prompt = prompt
        if getattr(self, 'after', None):
            self.after()
        return dict(say='That crate has potential.', used_memory_ids=[],
                    intent={'action': 'move', 'dir': 'forward'})


class SupervisedGameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.capture = capture_fixture(self.root / 'capture')
        self.db = self.root / 'capture' / 'fixture-recorder.sqlite3'
        with closing(open_reader(self.db)) as db:
            page = read_events(db, limit=64)
        self.event = next(e for e in page['events'] if e['event_type'] == 'observation.accepted')
        ctrl = self.event['control']
        self.expected = dict(database_id=page['database_id'], run_id=self.event['run_id'],
                             session_id=self.event['session_id'],
                             bridge_session=ctrl['bridge_session'], control_epoch=ctrl['control_epoch'])
        self.now = datetime.fromisoformat(self.event['source_timestamp_utc'].replace('Z', '+00:00')).timestamp() + .1
        self.state = dict(bridgeSession=ctrl['bridge_session'], controlEpoch=ctrl['control_epoch'],
                          map=ctrl['map_name'], serverTime=self.now, enabled=True,
                          dead=False, menu=False, stopped=False)
        self.provider = Provider()
        self.core = Core(self.root / 'core', provider=self.provider).start()
        self.addCleanup(self.stop)

    def stop(self):
        if self.core.accepting:
            self.core.call('stop')
        self.core.thread.join(5)

    def reaction(self, **kw):
        args = dict(event_id=self.event['event_id'], map_name=self.state['map'],
                    probe=lambda: deepcopy(self.state), clock=lambda: self.now)
        args.update(kw)
        return react(self.core, self.db, self.expected, **args)

    def test_committed_observation_reaches_actual_core_without_action_or_memory_write(self):
        result = self.reaction()
        self.assertEqual(result['say'], 'That crate has potential.')
        self.assertTrue(result['intent_discarded'])
        self.assertFalse(result['dispatched'])
        self.assertFalse(result['memory_saved'])
        self.assertEqual(self.core.call('lookup', {'query': 'crate'})['hits'], [])
        facts = json.loads(self.provider.prompt.split('GAME_OBSERVATION_REFERENCE: ')[1])
        self.assertEqual(facts['event_id'], self.event['event_id'])
        self.assertNotIn('NOT PERSISTED', self.provider.prompt)

    def test_old_observation_is_age_labelled_not_current(self):
        self.now += 4
        self.state['serverTime'] = self.now
        result = self.reaction()
        self.assertEqual(result['say'], 'That crate has potential.')
        facts = json.loads(self.provider.prompt.split('GAME_OBSERVATION_REFERENCE: ')[1])
        self.assertGreater(facts['observation_age_at_request_seconds'], 4)
        self.assertFalse(facts['current_state_established'])

    def test_missing_committed_event_refused(self):
        with self.assertRaisesRegex(RecordingRefused, 'observation_not_in_committed_window'):
            self.reaction(event_id='not-a-committed-event')

    def test_epoch_change_and_stop_during_generation_suppress_delivery(self):
        for key, value in [('controlEpoch', 2), ('stopped', True)]:
            original = deepcopy(self.state)
            self.provider.after = lambda k=key, v=value: self.state.update({k: v})
            with self.subTest(key=key), self.assertRaises(RecordingRefused):
                self.reaction()
            self.state = original

    def test_slow_reply_keeps_original_observation_age_and_can_be_delivered(self):
        def advance():
            self.now += 8
            self.state['serverTime'] = self.now
        self.provider.after = advance
        result = self.reaction()
        self.assertGreater(result['observation_age_at_reply_seconds'], 8)
        self.assertFalse(result['dispatched'])

    def test_wrong_map_and_inactive_controller_refused(self):
        for field, value in [('map', 'wrong-map'), ('menu', True), ('dead', True),
                             ('enabled', False), ('serverTime', self.now - 9)]:
            original = deepcopy(self.state)
            self.state[field] = value
            with self.subTest(field=field), self.assertRaises(RecordingRefused):
                self.reaction(map_name=self.event['control']['map_name'])
            self.state = original

    def test_existing_core_import_two_episodes_and_restart(self):
        other = capture_fixture(self.root / 'capture2')
        mids = [self.core.call('import', exp)['memory_id'] for exp in [self.capture, other]]
        self.assertNotEqual(*mids)
        self.stop()
        self.core = Core(self.root / 'core').start()
        for mid in mids:
            row = self.core.call('lookup', {'memory_id': mid})['hits'][0]
            self.assertEqual(row['memory_id'], mid)
            self.assertTrue(row['historical_only'])
            self.assertGreater(len(row['evidence']), 0)
        # Identical fixture prop in two episodes is not distinct-object/live acceptance.


if __name__ == '__main__':
    unittest.main()
