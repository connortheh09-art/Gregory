"""Deadline regressions. Child kills apply only to our disposable fixtures."""
import inspect
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import site
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import test_recorder_integration as fixture

bridge = fixture.bridge
PROCESS_PYTHON=getattr(sys,'_base_executable',sys.executable) if os.name=='nt' else sys.executable


def group():
    from concurrent.futures import ThreadPoolExecutor
    backend = ThreadPoolExecutor(max_workers=1)
    return bridge.ProducerGroup(backend) if hasattr(bridge, 'ProducerGroup') else backend


class DeadlineTests(unittest.TestCase):
    def test_never_returning_policy_is_degraded_and_sinks_deferred(self):
        self.child('worker')

    def test_never_returning_social_still_cancels_policy_first(self):
        self.child('social')

    def child(self, kind):
        program = r'''
import json,sys,threading,time,inspect
sys.path.insert(0,sys.argv[1])
import test_bridge_deadline as t
b=t.bridge
worker=t.group()
social=b.SocialLane('offline','fixture',enabled=False)
started=threading.Event()
def never():
    started.set()
    threading.Event().wait()
(worker if sys.argv[3]=='worker' else social.worker).submit(never)
assert started.wait(1)
rec=t.fixture.Recorder(t.Path(sys.argv[2]),'fixture')
rec.record('decision.error',{'error_category':'before_hang'})
time.sleep(.1)
b.log=lambda s: print(s,flush=True)
kw=dict(worker=worker,social=social,tracker=None,recorder=rec,cmd_path=t.Path('unused'),latest=None,
        target=None,stop_sequence=7,session='fixture-session',capture=False,state_tail=None)
if 'deadline_seconds' in inspect.signature(b.shutdown_bridge).parameters: kw['deadline_seconds']=.15
try:
    b.shutdown_bridge(**kw)
except b.ShutdownIncomplete as exc:
    print('DEGRADED '+json.dumps(exc.receipt),flush=True)
    print('CANCEL_ALL '+json.dumps({'worker':worker.stopping,'social':social.worker.stopping}),flush=True)
print('RETURNED',flush=True)
'''
        with tempfile.TemporaryDirectory() as root:
            db = Path(root)/'fixture.sqlite3'
            env=dict(os.environ,PYTHONPATH=os.pathsep.join(site.getsitepackages()))
            child = subprocess.Popen([PROCESS_PYTHON, '-B', '-u', '-c', program,
                str(Path(__file__).resolve().parent), str(db), kind], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,env=env)
            killed = False
            try:
                out, err = child.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                killed = True
                child.kill()
                out, err = child.communicate(timeout=2)
            evidence = dict(case=kind, pid=child.pid, parent_kill=killed,
                            returncode=child.returncode, stdout=out, stderr=err)
            # Forced termination is NEVER a clean run. Recover only fixture WAL.
            with closing(sqlite3.connect(db)) as sql, sql:
                evidence['integrity'] = sql.execute('PRAGMA integrity_check').fetchone()[0]
                evidence['recovered_events'] = sql.execute('SELECT count(*) FROM events').fetchone()[0]
                sql.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()
            evidence['run_outcome']='inconclusive_forced_termination' if killed else 'degraded'
            print('DEADLINE_CHILD '+json.dumps(evidence), flush=True)
            self.assertIn('BRIDGE_SHUTDOWN_START ', out)
            row = json.loads(next(s.split(' ',1)[1] for s in out.splitlines() if s.startswith('DEGRADED ')))
            self.assertFalse(row['ok'])
            self.assertFalse(row['fully_drained'])
            self.assertEqual(row['deferred_stages'], ['tracker','recorder'])
            self.assertIn(kind, row['pending_producers'])
            self.assertIn('"worker": true, "social": true', out)
            self.assertNotIn('"ok": true', out)
            self.assertEqual(evidence['integrity'], 'ok')
            self.assertGreater(evidence['recovered_events'], 0)

    def test_interrupt_is_not_swallowed_and_does_not_close_sink(self):
        class InterruptWorker:
            def request_stop(self): pass
            def join_until(self, deadline): raise KeyboardInterrupt()
            def shutdown(self, **kw): raise KeyboardInterrupt()
            @property
            def pending(self): return 1
        social = bridge.SocialLane('offline','fixture',enabled=False)
        recorder = unittest.mock.Mock()
        try:
            with patch.object(bridge,'log'), self.assertRaises(KeyboardInterrupt):
                bridge.shutdown_bridge(worker=InterruptWorker(),social=social,tracker=None,
                    recorder=recorder,cmd_path=Path('unused'),latest=None,target=None,
                    stop_sequence=1,session='fixture',capture=False,state_tail=None)
            recorder.close.assert_not_called()
        finally:
            social.close()

    def test_start_precedes_join_and_shared_deadline_waits_for_both(self):
        worker=group()
        social=bridge.SocialLane('offline','fixture',enabled=False)
        release=threading.Event()
        worker.submit(lambda:release.wait(2))
        social.worker.submit(lambda:release.wait(2))
        logs=[]
        try:
            kw=dict(worker=worker,social=social,tracker=None,recorder=None,cmd_path=Path('unused'),
                latest=None,target=None,stop_sequence=1,session='fixture',capture=False,state_tail=None)
            if 'deadline_seconds' in inspect.signature(bridge.shutdown_bridge).parameters: kw['deadline_seconds']=.08
            started=time.monotonic()
            with patch.object(bridge,'log',logs.append), self.assertRaises(bridge.ShutdownIncomplete):
                bridge.shutdown_bridge(**kw)
            self.assertLess(time.monotonic()-started,.35)
            self.assertTrue(logs[0].startswith('BRIDGE_SHUTDOWN_START '))
        finally:
            release.set()
            worker.shutdown(wait=True,cancel_futures=True)
            social.close()


if __name__=='__main__': unittest.main()
