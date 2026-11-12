"""Real collector entry-point shutdown faults; synthetic I/O and no HTTP/game.

Reuses the established offline collector harness, not its test cases. Real
Recorder queues and a real in-flight executor task exercise producer ownership.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

import test_recorder_integration as fixture

bridge = fixture.bridge


class BridgeShutdownTests(unittest.TestCase):
    def setUp(self):
        self.harness = fixture.CollectorIntegration(methodName='runTest')
        self.harness.setUp()
        self.addCleanup(self.harness.doCleanups)
        self.logs = []
        self.closed = []
        self.addCleanup(patch.stopall)
        patch.object(bridge, 'log', self.logs.append).start()

    def observe_closers(self, stack, *, failing_social=False):
        def wrap(cls, name, label):
            original = getattr(cls, name)
            def close(obj, *args, **kw):
                self.closed.append(label)
                result = original(obj, *args, **kw)
                if label == 'social' and failing_social:
                    raise RuntimeError('synthetic social close failure')
                return result
            stack.enter_context(patch.object(cls, name, close))
        wrap(fixture.ImmediateExecutor, 'shutdown', 'worker')
        wrap(bridge.SocialLane, 'close', 'social')
        wrap(fixture.ExperienceTracker, 'shutdown', 'tracker')
        wrap(fixture.Recorder, 'close', 'recorder')

    def receipt(self):
        rows = [json.loads(x.split(' ', 1)[1]) for x in self.logs
                if x.startswith('BRIDGE_SHUTDOWN ')]
        self.assertEqual(len(rows), 1, self.logs)
        return rows[0]

    def fail_stop(self, mode):
        original = bridge.write_cmd
        write = Path.write_text
        def writer(*args, **kw):
            if args[5] != 'stop':
                return original(*args, **kw)
            if mode == 'malformed':
                args = list(args)
                args[3] = {k: v for k, v in args[3].items() if k != 'steamid'}
                return original(*args, **kw)
            def unavailable(path, *a, **k):
                if path.name in {'cmd.json', 'cmd.json.tmp'}:
                    raise OSError('synthetic full transport')
                return write(path, *a, **k)
            with patch.object(Path, 'write_text', unavailable), patch.object(
                    bridge.os, 'replace', side_effect=OSError('synthetic locked transport')):
                return original(*args, **kw)
        return patch.object(bridge, 'write_cmd', writer)

    def test_malformed_stop_state_cannot_skip_any_resource_closer(self):
        with ExitStack() as stack:
            self.observe_closers(stack)
            stack.enter_context(self.fail_stop('malformed'))
            with self.assertRaises(Exception):
                self.harness.run_collector(True)
        self.assertEqual(self.closed, ['worker', 'social', 'tracker', 'recorder'])
        row = self.receipt()
        self.assertFalse(row['ok'])
        self.assertEqual(row['stop_status'], 'write_failed')
        self.assertTrue(any(e['stage'] == 'stop' and e['error_type'] == 'KeyError'
                            for e in row['errors']))

    def test_failed_stop_publication_does_not_return_ordinary_success(self):
        with self.fail_stop('unwritable'):
            with self.assertRaisesRegex(RuntimeError, 'shutdown incomplete'):
                self.harness.run_collector(True)
        row = self.receipt()
        self.assertFalse(row['ok'])
        self.assertEqual(row['stop_status'], 'write_failed')

    def test_capture_failed_stop_still_closes_all_resources(self):
        with ExitStack() as stack:
            self.observe_closers(stack)
            stack.enter_context(self.fail_stop('unwritable'))
            with self.assertRaises(RuntimeError):
                self.harness.run_collector(True, capture=True)
        self.assertEqual(self.closed, ['worker', 'social', 'tracker', 'recorder'])
        self.assertEqual(self.receipt()['stop_status'], 'write_failed')

    def test_social_close_failure_does_not_skip_tracker_or_recorder(self):
        with ExitStack() as stack:
            self.observe_closers(stack, failing_social=True)
            with self.assertRaises(RuntimeError):
                self.harness.run_collector(True)
        self.assertEqual(self.closed, ['worker', 'social', 'tracker', 'recorder'])
        self.assertFalse(self.receipt()['fully_drained'])

    def test_policy_producer_finishes_before_tracker_and_recorder_close(self):
        import time
        recorder = fixture.Recorder(self.harness.root/'late.sqlite3', 'fixture')
        worker = bridge.ProducerGroup(ThreadPoolExecutor(max_workers=1))
        social = bridge.SocialLane('offline','fixture',enabled=False)
        release, started = threading.Event(), threading.Event()
        sink, sequence = {}, []
        def late():
            started.set()
            release.wait(3)
            sink['late_event'] = recorder.record('decision.error',
                {'error_category':'synthetic_late_result'})
            sequence.append('producer_finished')
        worker.submit(late)
        self.assertTrue(started.wait(1))
        timer=threading.Timer(.15, release.set)
        timer.start()
        original_close=recorder.close
        def close(**kw):
            sequence.append('recorder_close')
            return original_close(**kw)
        try:
            with patch.object(recorder,'close',close):
                row=bridge.shutdown_bridge(worker=worker,social=social,tracker=None,
                    recorder=recorder,cmd_path=self.harness.root/'unused',latest=None,
                    target=None,stop_sequence=1,session='fixture',capture=False,state_tail=None)
            self.assertEqual(sequence,['producer_finished','recorder_close'])
            self.assertTrue(row['fully_drained'])
            event_id=sink['late_event'].as_dict()['event_id']
            with fixture.open_reader(recorder.path) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM events WHERE event_id=?',
                    (event_id,)).fetchone()[0],1)
        finally:
            release.set();timer.join(2)
            worker.shutdown(wait=True,cancel_futures=True)
            social.close();recorder.close()

    def test_social_inflight_producer_is_joined_by_close(self):
        lane = bridge.SocialLane('offline-only', 'synthetic', enabled=False)
        release, started, completed = threading.Event(), threading.Event(), threading.Event()
        def producer():
            started.set()
            release.wait(3)
            completed.set()
        lane.future = lane.worker.submit(producer)
        self.assertTrue(started.wait(2))
        timer = threading.Timer(.15, release.set)
        timer.start()
        try:
            lane.close()
            self.assertTrue(completed.is_set(), 'social producer survived close')
        finally:
            release.set()
            lane.worker.shutdown(wait=True, cancel_futures=True)
            timer.join(2)

    def test_ordinary_success_receipt_does_not_claim_game_stop(self):
        self.harness.run_collector(True)
        row = self.receipt()
        self.assertTrue(row['ok'])
        self.assertTrue(row['fully_drained'])
        self.assertEqual(row['stop_status'], 'submitted_unverified')
        self.assertFalse(row['game_stop_confirmed'])

    def test_capture_receipt_distinguishes_stationary_observation_from_command_ack(self):
        self.harness.run_collector(True, capture=True)
        row = self.receipt()
        self.assertTrue(row['ok'])
        self.assertEqual(row['stop_status'], 'stationary_corroborated')
        self.assertTrue(row['game_stationary_corroborated'])
        self.assertFalse(row['game_stop_confirmed'])

    def test_ordinary_recorder_close_health_failure_is_not_success(self):
        original = fixture.Recorder.close
        def broken_health(rec, **kw):
            result = original(rec, **kw)
            return dict(result, errors=result['errors'] + 1)
        with patch.object(fixture.Recorder, 'close', broken_health):
            with self.assertRaisesRegex(RuntimeError, 'shutdown incomplete'):
                self.harness.run_collector(True)
        row = self.receipt()
        self.assertFalse(row['ok'])
        self.assertEqual(row['errors'][-1]['stage'], 'recorder')

    def test_primary_loop_error_survives_failed_receipt_publication(self):
        def broken_log(message):
            if message.startswith('BRIDGE_SHUTDOWN '):
                raise OSError('synthetic unavailable log')
            self.logs.append(message)
        with ExitStack() as stack:
            self.observe_closers(stack)
            stack.enter_context(patch.object(bridge, 'log', broken_log))
            stack.enter_context(patch.object(fixture.ExperienceTracker, 'tick',
                side_effect=RuntimeError('synthetic primary loop failure')))
            with self.assertRaisesRegex(RuntimeError, 'synthetic primary loop failure'):
                # Ordinary mode deliberately wraps tracker.tick in SafeTracker;
                # capture uses the strict tracker, so this actually reaches the
                # loop as a primary exception rather than being swallowed.
                self.harness.run_collector(True, capture=True)
        self.assertEqual(self.closed, ['worker', 'social', 'tracker', 'recorder'])

    def test_failed_ordinary_stop_has_captured_subprocess_exit_one(self):
        program = r'''
import json,os,sys
sys.path.insert(0,sys.argv[1])
import test_bridge_shutdown as t
case=t.BridgeShutdownTests(methodName='runTest')
case.setUp()
try:
    with case.fail_stop('unwritable'):
        case.harness.run_collector(True)
finally:
    receipts=[json.loads(s.split(' ',1)[1]) for s in case.logs if s.startswith('BRIDGE_SHUTDOWN ')]
    print('SHUTDOWN_FAULT_EVIDENCE '+json.dumps({'pid':os.getpid(),'receipts':receipts}))
    case.doCleanups()
'''
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        env.pop('PYTHONPATH', None)
        result = subprocess.run([sys.executable, '-B', '-c', program,
            str(Path(__file__).resolve().parent)], cwd=self.harness.root, env=env,
            capture_output=True, text=True, timeout=15)
        line = next(s for s in result.stdout.splitlines() if s.startswith('SHUTDOWN_FAULT_EVIDENCE '))
        evidence = json.loads(line.split(' ', 1)[1])
        print('SHUTDOWN_SUBPROCESS ' + json.dumps(dict(evidence, returncode=result.returncode)))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('ShutdownIncomplete', result.stderr)
        self.assertFalse(evidence['receipts'][0]['ok'])
        self.assertEqual(evidence['receipts'][0]['stop_status'], 'write_failed')

    def test_write_cmd_returns_publication_not_delivery(self):
        state = dict(steamid='synthetic', bridgeSession='session', controlEpoch=1)
        path = self.harness.root / 'cmd.json'
        with patch.object(bridge, 'p0_trace'):
            self.assertIs(bridge.write_cmd(path, 1, {'action': 'wait'}, state, 's', 'stop'), True)
            with patch.object(bridge.os, 'replace', side_effect=OSError('synthetic locked')):
                self.assertIs(bridge.write_cmd(path, 2, {'action': 'wait'}, state, 's', 'stop'), True)
            with patch.object(Path, 'write_text', side_effect=OSError('synthetic full')), patch.object(
                    bridge.time, 'sleep'):
                self.assertIs(bridge.write_cmd(path, 3, {'action': 'wait'}, state, 's', 'stop'), False)


if __name__ == '__main__':
    unittest.main()
