from contextlib import closing
"""Independent-review reproductions: poison events, recovery and auxiliary lanes."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deployments' / 'oldpc'))
from greg_events import Event, TraceContext, new_id
from greg_recorder import Recorder, open_reader, get_experience, read_events
from greg_experience import ExperienceTracker


class ReviewFixes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'history.sqlite3'

    def recorder(self):
        r = Recorder(self.path, 'session'); self.addCleanup(r.close)
        self.assertTrue(r.wait_ready()); self.assertEqual(r.health()['status'], 'ready')
        return r

    def wait_for(self, predicate):
        until = time.monotonic() + 2
        while time.monotonic() < until:
            if predicate(): return
            time.sleep(.01)
        self.fail('condition did not become true before deadline')

    def committed(self, event_id):
        with open_reader(self.path) as db:
            return db.execute('SELECT 1 FROM events WHERE event_id=?', (event_id,)).fetchone() is not None

    def test_greg_conflicting_duplicate_does_not_stall_later_valid_event(self):
        r = self.recorder()
        original = r.factory.make('run.heartbeat', {'count': 1})
        r.emit(original); self.wait_for(lambda: self.committed(original.as_dict()['event_id']))
        value = original.as_dict(); value['payload']['count'] = 2
        r.emit(Event(json.dumps(value)))
        later = r.record('run.heartbeat', {'count': 3})
        self.wait_for(lambda: self.committed(later.as_dict()['event_id']))
        self.wait_for(lambda: r.health()['status'] == 'ready' and r.health()['inflight'] == 0)
        r.close()
        with open_reader(self.path) as db:
            events = read_events(db, limit=1000)['events']
            self.assertEqual(next(e for e in events if e['event_id'] == original.as_dict()['event_id'])['payload']['count'], 1)
            rejected = [e for e in events if e['event_type'] == 'recorder.loss' and e['payload'].get('reason') == 'event_id_conflict']
            self.assertEqual(len(rejected), 1)
            self.assertEqual(rejected[0]['payload']['rejected_event_id'], original.as_dict()['event_id'])
            self.assertNotIn('count":2', json.dumps(rejected, separators=(',', ':')))
        self.assertEqual(r.health()['quarantined'], 1)
        self.assertEqual(r.health()['dropped'], 1)
        self.assertEqual(r.health()['losses']['event_id_conflict']['count'], 1)

    def test_conflict_in_same_batch_rolls_neither_original_nor_later_back(self):
        r = self.recorder()
        first = r.factory.make('run.heartbeat', {'count': 1})
        mutated = first.as_dict(); mutated['payload']['count'] = 2
        later = r.factory.make('run.heartbeat', {'count': 3})
        # Hold admission mutex so all three enter the same writer batch.
        with r._cv:
            r.emit(first); r.emit(Event(json.dumps(mutated))); r.emit(later)
        self.wait_for(lambda: self.committed(later.as_dict()['event_id']))
        self.assertTrue(self.committed(first.as_dict()['event_id']))
        self.assertEqual(r.health()['quarantined'], 1)

    def test_conflicting_source_sequence_is_quarantined_too(self):
        r = self.recorder(); original = r.factory.make('run.heartbeat', {'count': 1})
        r.emit(original); self.wait_for(lambda: self.committed(original.as_dict()['event_id']))
        bad = original.as_dict(); bad['event_id'] = new_id()
        r.emit(Event(json.dumps(bad)))
        later = r.record('run.heartbeat', {'count': 3})
        self.wait_for(lambda: self.committed(later.as_dict()['event_id']))
        r.close()
        self.assertFalse(self.committed(bad['event_id']))
        self.assertEqual(r.health()['losses']['source_sequence_conflict']['count'], 1)

    def test_quarantine_and_loss_accounting_are_atomic_across_db_retry(self):
        r = self.recorder()
        original = r.factory.make('run.heartbeat', {'count': 1})
        changed = original.as_dict(); changed['payload']['count'] = 2
        later = r.factory.make('run.heartbeat', {'count': 3})
        insert = r._insert; failed = [False]
        def fail_later_once(db, event):
            if event.as_dict()['event_id'] == later.as_dict()['event_id'] and not failed[0]:
                failed[0] = True
                raise sqlite3.OperationalError('fixture busy after quarantine')
            return insert(db, event)
        with patch.object(r, '_insert', side_effect=fail_later_once):
            with r._cv:
                r.emit(original); r.emit(Event(json.dumps(changed))); r.emit(later)
            self.wait_for(lambda: failed[0])
            self.assertEqual(r.health()['quarantined'], 0)
            self.wait_for(lambda: self.committed(later.as_dict()['event_id']))
            self.wait_for(lambda: r.health()['status'] == 'ready')
        r.close()
        self.assertEqual(r.health()['quarantined'], 1)
        self.assertEqual(r.health()['losses']['event_id_conflict']['count'], 1)
        with open_reader(self.path) as db:
            events = read_events(db, limit=1000)['events']
        quarantines = [e for e in events if e['event_type']=='recorder.loss' and e['payload'].get('mode')=='quarantine']
        self.assertEqual(len(quarantines), 1)
        self.assertEqual(quarantines[0]['payload']['count'], 1)
        self.assertIn('recorder.recovered', {e['event_type'] for e in events})

    def test_oversized_sqlite_sequence_is_rejected_before_admission(self):
        r = self.recorder(); bad = r.factory.make('run.heartbeat', {}).as_dict()
        bad['source_sequence'] = 2**63
        self.assertEqual(r.emit(Event(json.dumps(bad))), 'invalid')
        later = r.record('run.heartbeat', {})
        self.wait_for(lambda: self.committed(later.as_dict()['event_id']))
        self.assertEqual(r.health()['invalid'], 1)

    def test_orderly_closure_has_correlated_terminal_event(self):
        r = self.recorder(); trace = TraceContext(r.run_id, new_id(), decision_id=new_id())
        r.record('decision.requested', {}, trace=trace, priority='critical'); r.close()
        with open_reader(self.path) as db:
            result = get_experience(db, trace.correlation_id)
        terminal = next(e for e in result['events'] if e['event_id'] == result['terminal_event_id'])
        self.assertEqual(terminal['event_type'], 'experience.closed')
        self.assertEqual(terminal['correlation_id'], trace.correlation_id)
        self.assertTrue(result['terminal_resolved'])
        self.assertEqual(result['world_outcome'], 'unknown')
        self.assertFalse(result['trace_complete'])  # No action/feedback was observed.
        self.assertIn('action.dispatch', result['missing_stages'])

    def test_restart_terminal_belongs_to_old_run_and_is_idempotent(self):
        r = self.recorder(); trace = TraceContext(r.run_id, new_id(), decision_id=new_id())
        r.record('decision.requested', {}, trace=trace, priority='critical'); r.close()
        with closing(sqlite3.connect(self.path)) as db, db:
            # Simulated pre-closure crash snapshot; no fabricated terminal history.
            db.execute("DELETE FROM events WHERE event_type IN ('run.ended','outcome.evaluated','experience.closed')")
            db.execute('DELETE FROM links WHERE from_event_id NOT IN (SELECT event_id FROM events)')
            db.execute('UPDATE runs SET ended_at_utc=NULL,end_reason=NULL')
            db.execute("UPDATE experiences SET record_state='open',closure_reason=NULL,terminal_event_id=NULL")
        second = self.recorder(); second.close()
        with open_reader(self.path) as db:
            result = get_experience(db, trace.correlation_id)
            terminal = next(e for e in result['events'] if e['event_id'] == result['terminal_event_id'])
            self.assertEqual(terminal['event_type'], 'experience.closed')
            self.assertEqual(terminal['run_id'], r.run_id)
            self.assertEqual(terminal['source_instance_id'], second.run_id)
            self.assertEqual(terminal['correlation_id'], trace.correlation_id)
            self.assertEqual(result['closure_reason'], 'unclean_restart')
            self.assertEqual(result['world_outcome'], 'unknown')
            self.assertEqual(result['unresolved_refs'], [])
            self.assertTrue(result['terminal_resolved'])
            n = db.execute("SELECT COUNT(*) FROM events WHERE event_type='experience.closed'").fetchone()[0]
        third = self.recorder(); third.close()
        with open_reader(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE event_type='experience.closed'").fetchone()[0], n)

    def test_failed_recovery_transaction_leaves_old_run_open_for_next_start(self):
        r = self.recorder(); trace = TraceContext(r.run_id, new_id(), decision_id=new_id())
        event = r.record('decision.requested', {}, trace=trace)
        self.wait_for(lambda: self.committed(event.as_dict()['event_id']))
        r.close()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM events WHERE event_type IN ('run.ended','outcome.evaluated','experience.closed')")
            db.execute('DELETE FROM links WHERE from_event_id NOT IN (SELECT event_id FROM events)')
            db.execute('UPDATE runs SET ended_at_utc=NULL,end_reason=NULL')
            db.execute("UPDATE experiences SET record_state='open',closure_reason=NULL,terminal_event_id=NULL")
        class FailCommit(sqlite3.Connection):
            def commit(self): raise sqlite3.OperationalError('fixture recovery commit failure')
        def connect(*args, **kwargs): return sqlite3.connect(*args, factory=FailCommit, **kwargs)
        failed = Recorder(self.path, 'failed restart', connect=connect); self.addCleanup(failed.close)
        self.assertTrue(failed.wait_ready()); failed.close()
        self.assertEqual(failed.health()['status'], 'degraded')
        with open_reader(self.path) as db:
            self.assertEqual(get_experience(db, trace.correlation_id)['record_state'], 'open')
            self.assertFalse(db.execute("SELECT 1 FROM events WHERE event_type='run.recovered'").fetchone())
        recovered = self.recorder(); recovered.close()
        with open_reader(self.path) as db:
            result = get_experience(db, trace.correlation_id)
            closures = [e for e in result['events'] if e['event_type']=='experience.closed']
            self.assertEqual(len(closures), 1)
            self.assertTrue(result['terminal_resolved'])
            self.assertEqual(result['world_outcome'], 'unknown')

    def test_sensor_evidence_stays_with_inspect_not_active_navigation(self):
        r = self.recorder(); tracker = ExperienceTracker(r)
        active = tracker.begin_decision(lane='agenda')
        tracker.decision_result(active, accepted=True, reason='navigation')
        parent = tracker.begin_decision(lane='model')
        tracker.decision_result(parent, accepted=True, reason='collector_inspect', activate=False)
        sensor = tracker.begin_sensor(parent)
        self.assertEqual(sensor.correlation_id, parent.correlation_id)
        tracker.sensor_result(sensor, accepted=True, reason='sensor_ready', result={'caption':'private scene', 't':123})
        self.assertEqual(tracker.active_trace, active)
        tracker.dispatch({'seq':1, 'session':'session', 'action':{'action':'navigate',
                          'id':'route', 'points':[{'x':500,'y':0,'z':0}], 'lease':2.5}})
        r.close()
        with open_reader(self.path) as db:
            result = get_experience(db, parent.correlation_id)
            navigation = get_experience(db, active.correlation_id)
        self.assertNotIn('action.dispatch', {e['event_type'] for e in result['events']})
        self.assertIn('action.dispatch', {e['event_type'] for e in navigation['events']})
        self.assertIn('sensor.result', {e['event_type'] for e in result['events']})
        self.assertEqual(result['closure_reason'], 'inspection_observed')
        self.assertNotIn('private scene', json.dumps(result))
        self.assertEqual(len(tracker.episodes), 2)

    def test_rejected_sensor_is_terminal_and_never_activates_action_trace(self):
        r = self.recorder(); tracker = ExperienceTracker(r)
        active = tracker.begin_decision(lane='agenda')
        tracker.decision_result(active, accepted=True, reason='navigation')
        parent = tracker.begin_decision(lane='model')
        tracker.decision_result(parent, accepted=True, reason='collector_inspect', activate=False)
        sensor = tracker.begin_sensor(parent)
        tracker.sensor_result(sensor, accepted=False, reason='stale_or_context')
        self.assertEqual(tracker.active_trace, active)
        r.close()
        with open_reader(self.path) as db:
            result = get_experience(db, parent.correlation_id)
        self.assertEqual(result['closure_reason'], 'stale_or_context')
        self.assertEqual(result['world_outcome'], 'unknown')
        self.assertIn('sensor.error', {e['event_type'] for e in result['events']})
        self.assertTrue(result['terminal_resolved'])

    def test_legacy_goal_selection_finalizes_without_claiming_gameplay(self):
        r = self.recorder(); tracker = ExperienceTracker(r)
        active = tracker.begin_decision(lane='agenda')
        tracker.decision_result(active, accepted=True, reason='navigation')
        selected = tracker.begin_decision(lane='goal')
        tracker.goal_selection(selected, accepted=True, goal='private goal words', native_goal={'id':'native-goal'})
        rejected = tracker.begin_decision(lane='goal')
        tracker.goal_selection(rejected, accepted=False, goal='')
        self.assertEqual(tracker.active_trace, active)
        r.close()
        with open_reader(self.path) as db:
            good = get_experience(db, selected.correlation_id); bad = get_experience(db, rejected.correlation_id)
        self.assertEqual(good['closure_reason'], 'goal_selected')
        self.assertEqual(good['world_outcome'], 'not_applicable')
        self.assertIn('decision.applied', {e['event_type'] for e in good['events']})
        self.assertTrue(next(e for e in good['events'] if e['event_type']=='goal.observed')['goal_id'])
        self.assertEqual(bad['closure_reason'], 'goal_empty_or_rejected')
        self.assertNotIn('decision.applied', {e['event_type'] for e in bad['events']})
        self.assertNotIn('private goal words', json.dumps(good))
    def test_backup_connect_failure_removes_reserved_empty_destination(self):
        from greg_recorder import backup
        r = self.recorder(); r.close(); target = Path(self.tmp.name)/'snapshot.sqlite3'
        with open_reader(self.path) as db, patch('greg_recorder.sqlite3.connect', side_effect=sqlite3.OperationalError('fixture')):
            with self.assertRaises(sqlite3.OperationalError): backup(db, target)
        self.assertFalse(target.exists())

    def test_export_failure_removes_partial_but_preserves_preexisting_file(self):
        from greg_recorder import export_run
        r = self.recorder(); r.close(); target = Path(self.tmp.name)/'export.jsonl'
        with open_reader(self.path) as db:
            with self.assertRaises(ValueError): export_run(db, r.run_id, target, max_bytes=1)
            self.assertFalse(target.exists())
            target.write_text('unrelated existing file')
            with self.assertRaises(FileExistsError): export_run(db, r.run_id, target)
        self.assertEqual(target.read_text(), 'unrelated existing file')

    def test_legacy_v1_terminal_is_resolved_without_inventing_a_closure(self):
        r = self.recorder(); trace = TraceContext(r.run_id, new_id(), decision_id=new_id())
        r.record('decision.requested', {}, trace=trace); r.close()
        with closing(sqlite3.connect(self.path)) as db, db:
            ended = db.execute("SELECT event_id FROM events WHERE event_type='run.ended'").fetchone()[0]
            db.execute('UPDATE experiences SET terminal_event_id=?', (ended,))
            db.execute("DELETE FROM events WHERE event_type='experience.closed'")
        with open_reader(self.path) as db:
            result = get_experience(db, trace.correlation_id)
        self.assertTrue(result['terminal_resolved'])
        self.assertTrue(any(e['event_id']==ended for e in result['events']))
        self.assertFalse(result['trace_complete'])
        self.assertIn('experience.closed', result['missing_stages'])



if __name__ == '__main__': unittest.main()
