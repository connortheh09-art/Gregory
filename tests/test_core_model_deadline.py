"""Regressions for the evidenced synchronous-writer hang, not a Core re-review."""
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gregory_core.runtime import Core,FixtureProvider,AdmissionRefused


class ModelDeadlineTests(unittest.TestCase):
    def test_completion_status_failure_resolves_uncommitted_model_future(self):
        release,started=threading.Event(),threading.Event()
        class Slow(FixtureProvider):
            def generate(self,profile,prompt):started.set();release.wait(2);return {'say':'fixture'}
        with tempfile.TemporaryDirectory() as root:
            core=Core(Path(root)/'character',provider=Slow()).start()
            original=core._status
            def failed_status():
                task=core.model_task
                if task and not task.thread.is_alive() and task.output.empty():
                    raise RuntimeError('fixture completion status failure')
                return original()
            try:
                future=core.submit('think',{'prompt':'fixture'})
                self.assertTrue(started.wait(1))
                with patch.object(core,'_status',failed_status):
                    release.set()
                    self.assertTrue(core.finished.wait(2))
                    with self.assertRaisesRegex(RuntimeError,'fixture completion status failure'):
                        future.result(.2)
            finally:
                release.set()
                if core.accepting:core.call('stop')
                core.thread.join(3)

    def test_caller_timeout_is_also_a_turn_deadline_not_just_future_timeout(self):
        release=threading.Event()
        class Slow(FixtureProvider):
            def generate(self,profile,prompt):release.wait(2);return {'say':'late'}
        with tempfile.TemporaryDirectory() as root:
            core=Core(Path(root)/'character',provider=Slow()).start()
            correlation=str(uuid.uuid4())
            try:
                with self.assertRaises(TimeoutError):
                    core.call('think',dict(prompt='fixture',correlation_id=correlation),timeout=.03)
                release.set();time.sleep(.1)
                events=core.call('correlation',dict(correlation_id=correlation))['events']
                self.assertFalse(any(e['kind']=='inference' for e in events))
            finally:
                release.set()
                if core.accepting:core.call('stop')
                core.thread.join(3)

    def test_hung_model_does_not_wedge_writer_or_write_late_inference(self):
        started,release=threading.Event(),threading.Event()
        class Slow(FixtureProvider):
            def generate(self,profile,prompt):
                started.set();release.wait(3)
                return {'say':'LATE answer must not enter the journal'}
        with tempfile.TemporaryDirectory() as root:
            core=Core(Path(root)/'character',provider=Slow()).start()
            correlation=str(uuid.uuid4())
            try:
                future=core.submit('think',{'prompt':'fixture','deadline_seconds':.08,
                    'correlation_id':correlation})
                self.assertTrue(started.wait(1))
                began=time.monotonic()
                core.call('lookup',{'query':'empty'},timeout=.3)
                self.assertLess(time.monotonic()-began,.3)
                with self.assertRaises(TimeoutError): future.result(.5)
                status=core.call('status')
                self.assertTrue(status['core']['model_busy'])
                self.assertEqual(status['core']['model_state'],'timed_out')
                self.assertGreater(status['core']['inflight_age'],0)
                with self.assertRaises(AdmissionRefused): core.submit('think',{'prompt':'busy'})
                release.set()
                until=time.monotonic()+1
                while core.call('status')['core']['model_busy'] and time.monotonic()<until: time.sleep(.01)
                events=core.call('correlation',{'correlation_id':correlation})['events']
                self.assertFalse(any(e['kind'] in ('inference','decision') for e in events))
                self.assertFalse(any(e['payload'].get('type')=='model.response' for e in events))
                self.assertTrue(any(e['payload'].get('type')=='model.late_discarded' for e in events))
            finally:
                release.set()
                if core.accepting: core.call('stop',timeout=5)
                core.thread.join(5)

    def test_stop_terminates_writer_without_waiting_for_never_returning_model(self):
        release=threading.Event()
        class Never(FixtureProvider):
            def generate(self,profile,prompt): release.wait(5);return {'say':'late'}
        with tempfile.TemporaryDirectory() as root:
            core=Core(Path(root)/'character',provider=Never()).start()
            future=core.submit('think',{'prompt':'fixture'})
            try:
                began=time.monotonic()
                stopped=core.call('stop',timeout=.4)
                self.assertLess(time.monotonic()-began,.4)
                self.assertTrue(stopped['databases_closed'])
                self.assertTrue(stopped['model_transport_pending'])
                self.assertFalse(stopped['fully_drained'])
                with self.assertRaises(Exception):future.result(.1)
            finally:
                release.set()
                if core.accepting: core.call('stop',timeout=6)
                core.thread.join(6)

if __name__=='__main__': unittest.main()
