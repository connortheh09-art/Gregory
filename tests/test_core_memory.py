from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from gregory_core.memory import MemoryStore, canonical, project_event
from _core_fixtures import experience, FixtureEmbedder, new_id


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'memory.sqlite3'
        self.now = 1700000010
        self.store = self.open()

    def open(self):
        store = MemoryStore(self.path, owner_id='owner', retention_seconds=86400,
                            clock=lambda: self.now)
        self.addCleanup(store.close)
        return store

    def episode(self, *, domain='gmod', **kwargs):
        events, run, cid = experience(**kwargs)
        self.store.ingest(events, actor='owner', source_label='synthetic:fixture')
        key = self.store.consolidate(run, cid, actor='owner', domain=domain)
        return key, events, run, cid

    def test_200_movements_become_one_grounded_episode_not_200_memories(self):
        key, events, _, _ = self.episode(movements=200)
        memory = self.store.inspect(key, actor='owner')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM memories').fetchone()[0], 1)
        self.assertEqual(len(memory['evidence']), len(events))
        self.assertLess(len(memory['summary']), 250)
        self.assertIn('difficulty', memory['summary'])
        self.assertIn('successful', memory['summary'])
        refs = {e['event_id'] for e in memory['evidence']}
        for claim in memory['claims']:
            self.assertTrue(claim['evidence_ids'])
            self.assertTrue(set(claim['evidence_ids']) <= refs)
        self.assertEqual(memory['claims'][-1]['kind'], 'inferred')

    def test_provenance_hash_points_to_original_not_projection(self):
        key, events, _, _ = self.episode()
        e = self.store.inspect(key, actor='owner')['evidence'][0]
        original = next(x for x in events if x['event_id'] == e['event_id'])
        self.assertEqual(e['envelope_sha256'], hashlib.sha256(canonical(original).encode()).hexdigest())
        self.assertEqual(e['source_label'], 'synthetic:fixture')

    def test_raw_dialogue_model_narratives_and_keys_are_not_cached(self):
        events, run, cid = experience(model=True)
        event = next(e for e in events if e['event_type'] == 'decision.response')
        event['payload']['text'] = 'SECRET_DIALOGUE Minecraft is running now'
        event['payload']['api_key'] = 'SECRET_CREDENTIAL'
        self.store.ingest(events, actor='owner', source_label='synthetic')
        key = self.store.consolidate(run, cid, actor='owner', domain='voice')
        data = json.dumps(self.store.inspect(key, actor='owner'))
        self.assertNotIn('SECRET_', data)
        self.assertNotIn('running now', data)

    def test_missing_terminal_is_unknown_not_invented_success(self):
        key, _, _, _ = self.episode(closed=False)
        m = self.store.inspect(key, actor='owner')
        self.assertIn('missing_terminal', m['uncertainty'])
        self.assertEqual(m['claims'][-1]['kind'], 'unknown')
        self.assertNotIn('successful', m['summary'])

    def test_dispatch_without_evaluation_does_not_prove_world_success(self):
        key, _, _, _ = self.episode(outcome='unknown')
        self.assertEqual(self.store.inspect(key, actor='owner')['claims'][-1]['kind'], 'unknown')

    def test_gap_or_stale_observation_blocks_success_claim(self):
        key, _, _, _ = self.episode(gap=True)
        self.assertIn('run_contains_evidence_gap', self.store.inspect(key, actor='owner')['uncertainty'])
        events, run, cid = experience()
        events[0]['payload']['fresh'] = False
        self.store.ingest(events, actor='owner', source_label='synthetic')
        key = self.store.consolidate(run, cid, actor='owner', domain='gmod')
        self.assertIn('stale_or_rejected_observation', self.store.inspect(key, actor='owner')['uncertainty'])

    def test_cross_run_observation_cannot_ground_outcome(self):
        events, run, cid = experience()
        events[0]['run_id'] = new_id()
        self.store.ingest(events, actor='owner', source_label='synthetic')
        key = self.store.consolidate(run, cid, actor='owner', domain='gmod')
        m = self.store.inspect(key, actor='owner')
        self.assertIn('missing_or_wrong_scope_observation', m['uncertainty'])
        self.assertEqual(m['claims'][-1]['kind'], 'unknown')

    def test_model_origin_requires_model_response_not_just_action(self):
        events, run, cid = experience(model=True)
        events = [e for e in events if e['event_type'] != 'decision.response']
        self.store.ingest(events, actor='owner', source_label='synthetic')
        key = self.store.consolidate(run, cid, actor='owner', domain='gmod')
        self.assertIn('incomplete_action_chain', self.store.inspect(key, actor='owner')['uncertainty'])

    def test_conflicting_terminal_conclusions_remain_unknown(self):
        events, run, cid = experience()
        other = copy.deepcopy(events[-1]);other['event_id'] = new_id()
        other['source_sequence'] += 1;other['payload']['world_outcome'] = 'failed'
        events.append(other)
        self.store.ingest(events, actor='owner', source_label='synthetic')
        key = self.store.consolidate(run, cid, actor='owner', domain='gmod')
        self.assertIn('conflicting_terminals', self.store.inspect(key, actor='owner')['uncertainty'])

    def test_source_clock_shift_does_not_reorder_terminal_chain(self):
        events, run, cid = experience()
        events[-1]['source_timestamp_utc'] = '2020-01-01T00:00:00+00:00'
        self.store.ingest(events, actor='owner', source_label='synthetic')
        key = self.store.consolidate(run, cid, actor='owner', domain='gmod')
        self.assertEqual(self.store.inspect(key, actor='owner')['claims'][-1]['kind'], 'inferred')

    def test_idempotent_import_and_consolidation_survive_reopen(self):
        key, events, run, cid = self.episode()
        reopened = self.open()
        reopened.ingest(events, actor='owner', source_label='synthetic:fixture')
        self.assertEqual(key, reopened.consolidate(run, cid, actor='owner', domain='gmod'))
        self.assertEqual(len(reopened.last_session(actor='owner')['episodes']), 1)

    def test_conflicting_duplicate_rolls_back_entire_batch(self):
        _, events, _, _ = self.episode()
        conflict = copy.deepcopy(events[-1]);conflict['payload']['world_outcome'] = 'failed'
        fresh = experience()[0][0]
        with self.assertRaises(ValueError):
            self.store.ingest([fresh, conflict], actor='owner', source_label='synthetic')
        self.assertIsNone(self.store.db.execute('SELECT 1 FROM evidence WHERE event_id=?', (fresh['event_id'],)).fetchone())

    def test_invalid_batch_validated_before_any_insert(self):
        events, _, _ = experience();events[-1]['schema_version'] = True
        with self.assertRaises(ValueError):self.store.ingest(events, actor='owner', source_label='synthetic')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM evidence').fetchone()[0], 0)

    def test_keyword_fts_is_literal_and_explains_evidence(self):
        key, _, _, _ = self.episode()
        result = self.store.search('follow " OR NOT :*', actor='owner')
        self.assertEqual(result['hits'][0]['memory_id'], key)
        self.assertEqual(result['hits'][0]['retrieval_channels'], ['keyword'])
        self.assertTrue(result['hits'][0]['evidence'])

    def test_last_played_uses_latest_occurrence_not_import_order(self):
        newer, _, _, _ = self.episode(session='newer', start=1700000005, domain='gmod')
        self.episode(session='yesterday-minecraft', start=1699990000, domain='minecraft')
        result = self.store.last_session(actor='owner')
        self.assertEqual(result['session_id'], 'newer')
        self.assertEqual(result['episodes'][0]['memory_id'], newer)
        past = self.store.last_session(actor='owner', domain='minecraft')
        self.assertEqual(past['session_id'], 'yesterday-minecraft')
        self.assertTrue(past['historical_only'])
        self.assertIn('requires fresh', past['current_world_state'])

    def test_domain_and_session_filters_apply_to_both_search_lanes(self):
        first, _, _, _ = self.episode(session='one', domain='gmod')
        second, _, _, _ = self.episode(session='two', domain='minecraft')
        for key in (first, second):self.store.index(key, FixtureEmbedder(), actor='owner')
        result = self.store.search('follow', actor='owner', embedder=FixtureEmbedder(), session_id='one', domain='gmod')
        self.assertEqual([m['memory_id'] for m in result['hits']], [first])

    def test_owner_correction_supersedes_fts_invalidates_vectors_and_is_reported(self):
        key, _, run, cid = self.episode()
        self.store.index(key, FixtureEmbedder(), actor='owner')
        self.store.correct(key, 'Owner correction: a synthetic orchard exercise.', actor='owner', reason='fixture correction')
        self.assertFalse(self.store.search('follow', actor='owner')['hits'])
        self.assertEqual(self.store.search('orchard', actor='owner')['hits'][0]['memory_id'], key)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM vectors').fetchone()[0], 0)
        self.assertEqual(self.store.consolidate(run, cid, actor='owner', domain='gmod'), key)
        m = self.store.inspect(key, actor='owner')
        self.assertEqual(m['claims'][0]['kind'], 'reported')
        self.assertEqual(m['revision'], 2)
        history = self.store.history(key, actor='owner')
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]['claims'][0]['kind'], 'reported')

    def test_forgetting_purges_fts_vectors_history_evidence_and_blocks_resurrection(self):
        key, events, _, _ = self.episode()
        self.store.correct(key, 'private orchard fixture', actor='owner', reason='test')
        self.store.index(key, FixtureEmbedder(), actor='owner')
        self.store.forget(key, actor='owner')
        for table in ('memories', 'citations', 'vectors', 'revisions', 'evidence', 'memory_fts'):
            self.assertEqual(self.store.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0, table)
        self.assertFalse(self.store.search('fruit', actor='owner', embedder=FixtureEmbedder())['hits'])
        with self.assertRaises(ValueError):self.store.ingest(events, actor='owner', source_label='synthetic')

    def test_source_evidence_removal_invalidates_derived_episode(self):
        key, events, _, _ = self.episode()
        self.store.forget_evidence(events[0]['event_id'], actor='owner')
        self.assertIsNone(self.store.inspect(key, actor='owner'))
        self.assertFalse(self.store.search('follow', actor='owner')['hits'])

    def test_expired_memory_hidden_before_maintenance_and_then_purged(self):
        key, _, _, _ = self.episode()
        self.now += 86401
        self.assertTrue(self.store.inspect(key, actor='owner')['expired'])
        self.assertFalse(self.store.search('follow', actor='owner')['hits'])
        self.assertEqual(self.store.last_session(actor='owner')['episodes'], [])
        self.assertEqual(self.store.expire(actor='owner'), 1)
        self.assertIsNone(self.store.inspect(key, actor='owner'))

    def test_unconsolidated_evidence_also_expires(self):
        events, _, _ = experience()
        self.store.ingest(events, actor='owner', source_label='synthetic')
        self.now += 86401
        self.store.expire(actor='owner')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM evidence').fetchone()[0], 0)

    def test_guest_cannot_read_correct_delete_import_or_embed(self):
        key, events, _, _ = self.episode()
        calls = [lambda:self.store.search('follow', actor='guest'),
                 lambda:self.store.inspect(key, actor='guest'),
                 lambda:self.store.correct(key, 'x', actor='guest', reason='x'),
                 lambda:self.store.forget(key, actor='guest'),
                 lambda:self.store.ingest(events, actor='guest', source_label='x'),
                 lambda:self.store.index(key, FixtureEmbedder(), actor='guest'),
                 lambda:self.store.history(key, actor='guest'),
                 lambda:self.store.expire(actor='guest')]
        for call in calls:
            with self.assertRaises(PermissionError):call()

    def test_unrelated_database_and_wrong_owner_left_untouched(self):
        unrelated = Path(self.tmp.name)/'recorder.sqlite3'
        with closing(sqlite3.connect(unrelated)) as db, db:db.execute('CREATE TABLE events(id)')
        before = unrelated.read_bytes()
        with self.assertRaises(ValueError):MemoryStore(unrelated, owner_id='owner', retention_seconds=10)
        self.assertEqual(before, unrelated.read_bytes())
        with self.assertRaises(ValueError):MemoryStore(self.path, owner_id='guest', retention_seconds=10)

    def test_same_source_sequence_cannot_be_reused_with_different_identity(self):
        _, events, _, _ = self.episode()
        duplicate = copy.deepcopy(events[0]);duplicate['event_id'] = new_id()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.ingest([duplicate], actor='owner', source_label='synthetic')

    def test_recovery_process_source_identity_is_not_confused_with_old_run(self):
        events, run, cid = experience(closed=False, outcome='unknown')
        # Like Recorder._owned_event: new process emits closure for old logical run.
        closure = copy.deepcopy(events[-1]);closure['event_id'] = new_id()
        closure['source_instance_id'] = new_id();closure['source_sequence'] = 1
        closure['event_type'] = 'experience.closed'
        closure['payload'] = {'closure_reason':'unclean_restart','world_outcome':'unknown'}
        events.append(closure)
        self.store.ingest(events, actor='owner', source_label='synthetic-recovery')
        key = self.store.consolidate(run, cid, actor='owner', domain='gmod')
        m = self.store.inspect(key, actor='owner')
        self.assertIn('unclean_restart', m['uncertainty'])
        self.assertIn('multiple_source_instances', m['uncertainty'])
        self.assertEqual(m['claims'][-1]['kind'], 'unknown')

    def test_later_observation_cannot_support_an_earlier_outcome_evaluation(self):
        events, run, cid = experience()
        events[0]['source_sequence'] = 1000
        self.store.ingest(events, actor='owner', source_label='synthetic')
        key = self.store.consolidate(run, cid, actor='owner', domain='gmod')
        self.assertIn('missing_or_wrong_scope_observation', self.store.inspect(key, actor='owner')['uncertainty'])

    def test_consolidation_cannot_relabel_an_existing_world(self):
        _, _, run, cid = self.episode(domain='gmod')
        with self.assertRaises(ValueError):
            self.store.consolidate(run, cid, actor='owner', domain='minecraft')

    def test_actual_pr1_recorder_export_import_leaves_source_database_unchanged(self):
        from greg_recorder import Recorder, open_reader, export_run
        recorder_path = Path(self.tmp.name)/'source-recorder.sqlite3'
        recorder = Recorder(recorder_path, 'synthetic-real-export')
        self.addCleanup(recorder.close)
        self.assertTrue(recorder.wait_ready())
        events, _, _ = experience(session='synthetic-real-export')
        # Produce the synthetic action through the real, unchanged Recorder API.
        from greg_events import TraceContext
        trace = TraceContext(recorder.run_id, new_id())
        recorder.record('decision.requested', {}, trace=trace)
        recorder.record('action.dispatch', {'parameters_complete':True}, trace=trace)
        recorder.close()
        export = Path(self.tmp.name)/'events.jsonl'
        with open_reader(recorder_path) as reader:export_run(reader, recorder.run_id, export)
        before = recorder_path.read_bytes()
        actual = [json.loads(line) for line in export.read_text().splitlines()]
        self.store.ingest(actual, actor='owner', source_label='synthetic:actual-PR1-export')
        key = self.store.consolidate(recorder.run_id, trace.correlation_id, actor='owner', domain='gmod')
        self.assertIn('outcome_not_established', self.store.inspect(key, actor='owner')['uncertainty'])
        self.assertEqual(before, recorder_path.read_bytes())


if __name__ == '__main__':
    unittest.main()
