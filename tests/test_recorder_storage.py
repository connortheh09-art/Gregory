from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deployments'/'oldpc'))
from greg_events import TraceContext,new_id,Event
from greg_recorder import Recorder,NullRecorder,open_reader,read_events,get_experience,backup


class Storage(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'data'/'experience.sqlite3'

    def recorder(self,**kwargs):
        r=Recorder(self.path,'session',**kwargs);self.addCleanup(r.close)
        self.assertTrue(r.wait_ready());return r

    def test_disabled_has_no_files_or_threads(self):
        before={t.ident for t in threading.enumerate()}
        sink=NullRecorder();sink.record('run.started',{});sink.close()
        self.assertFalse(self.path.parent.exists());self.assertEqual(before,{t.ident for t in threading.enumerate()})

    def test_idempotence_reader_cursor_and_immutable_event(self):
        r=self.recorder();e=r.factory.make('run.heartbeat',{'count':1})
        r.emit(e);r.emit(e);r.close()
        with open_reader(self.path) as db:
            page=read_events(db)
            self.assertEqual(sum(v['event_id']==e.as_dict()['event_id'] for v in page['events']),1)
            self.assertEqual(read_events(db,after=page['next_cursor'])['events'],[])
            with self.assertRaises(sqlite3.OperationalError): db.execute("DELETE FROM events")

    def test_missing_reader_does_not_create_database(self):
        with self.assertRaises(sqlite3.OperationalError): open_reader(self.path)
        self.assertFalse(self.path.exists())

    def test_newer_schema_left_untouched(self):
        self.path.parent.mkdir()
        with closing(sqlite3.connect(self.path)) as db, db: db.execute('PRAGMA user_version=99')
        r=self.recorder();self.assertEqual(r.health()['status'],'degraded')
        with closing(sqlite3.connect(self.path)) as db, db: self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],99)

    def test_unrelated_schema_one_is_not_reconfigured(self):
        self.path.parent.mkdir()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('PRAGMA user_version=1');db.execute('CREATE TABLE unrelated(data)')
        r=self.recorder();self.assertEqual(r.health()['status'],'degraded')
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'delete')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM unrelated').fetchone()[0],0)

    def test_second_writer_lock_refused_and_first_remains_live(self):
        r=self.recorder();other=self.recorder()
        self.assertEqual(other.health()['status'],'degraded')
        self.assertEqual(r.health()['status'],'ready')

    def test_bounded_admission_and_loss_under_failed_startup(self):
        def fail(*a,**k): raise sqlite3.OperationalError('fixture disk full')
        r=self.recorder(connect=fail,normal_limit=2,critical_limit=1)
        for _ in range(20): r.record('run.heartbeat',{})
        self.assertEqual(r.health()['normal_depth'],2);self.assertEqual(r.health()['dropped'],18)
        self.assertEqual(r.health()['errors'],1)

    def test_recovery_closes_only_unfinished_experience(self):
        r=self.recorder();trace=TraceContext(r.run_id,new_id(),decision_id=new_id())
        r.record('decision.requested',{},trace=trace,priority='critical');r.close()
        # Emulate absence of a committed orderly termination after a crash.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE runs SET ended_at_utc=NULL,end_reason=NULL')
            db.execute("UPDATE experiences SET record_state='open',closure_reason=NULL,terminal_event_id=NULL")
        second=self.recorder();second.close()
        with open_reader(self.path) as db:
            e=get_experience(db,trace.correlation_id)
            self.assertEqual(e['world_outcome'],'unknown');self.assertEqual(e['closure_reason'],'unclean_restart')
            n=db.execute("SELECT COUNT(*) FROM events WHERE event_type='run.recovered'").fetchone()[0]
        third=self.recorder();third.close()
        with open_reader(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE event_type='run.recovered'").fetchone()[0],n)

    def test_backup_is_readable_refuses_overwrite(self):
        r=self.recorder();r.close();out=Path(self.tmp.name)/'backup.sqlite3'
        with open_reader(self.path) as db:
            backup(db,out)
            with self.assertRaises(FileExistsError): backup(db,out)
        with open_reader(out) as db: self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_conflicting_duplicate_is_not_overwritten(self):
        r=self.recorder();e=r.factory.make('run.heartbeat',{'count':1});r.emit(e)
        # Conflicting payload is quarantined, never allowed to replace the original.
        v=e.as_dict();v['payload']['count']=2;r.emit(Event(json.dumps(v,separators=(',',':'))))
        r.close()
        with open_reader(self.path) as db:
            rows=[v for v in read_events(db)['events'] if v['event_id']==e.as_dict()['event_id']]
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['payload']['count'],1)

    def test_actual_process_exit_after_commit_is_recovered_unknown(self):
        module_path=str(Path(__file__).resolve().parents[1]/'deployments'/'oldpc')
        script='''import sys,os,time,json
sys.path.insert(0,sys.argv[1])
from greg_recorder import Recorder,open_reader,get_experience
from greg_events import TraceContext,new_id
r=Recorder(sys.argv[2],'crash');r.wait_ready()
t=TraceContext(r.run_id,new_id(),decision_id=new_id())
r.record('decision.requested',{},trace=t,priority='critical')
for _ in range(200):
    with open_reader(sys.argv[2]) as db: found=get_experience(db,t.correlation_id)
    if found: break
    time.sleep(.01)
else: raise RuntimeError('commit not observed')
print(t.correlation_id,flush=True)
os._exit(0)
'''
        child=subprocess.run([sys.executable,'-c',script,module_path,str(self.path)],capture_output=True,text=True,timeout=5)
        self.assertEqual(child.returncode,0,child.stderr)
        cid=child.stdout.strip()
        r=self.recorder();r.close()
        with open_reader(self.path) as db:
            result=get_experience(db,cid)
            self.assertEqual(result['world_outcome'],'unknown')
            self.assertEqual(result['closure_reason'],'unclean_restart')
            self.assertTrue(result['terminal_resolved'])
            terminal=next(e for e in result['events'] if e['event_id']==result['terminal_event_id'])
            self.assertEqual(terminal['event_type'],'experience.closed')
            self.assertEqual(terminal['correlation_id'],cid)
            self.assertEqual(result['unresolved_refs'],[])
            self.assertEqual(terminal['run_id'],result['run_id'])
            self.assertNotEqual(terminal['source_instance_id'],result['run_id'])
            old_run_events=[e for e in read_events(db,limit=1000)['events'] if e['run_id']==result['run_id']]
            self.assertTrue(any(e['event_id']==result['terminal_event_id'] for e in old_run_events))

    def test_untrusted_envelope_cannot_bypass_payload_privacy(self):
        r=self.recorder();e=r.factory.make('run.heartbeat',{})
        value=e.as_dict();value['payload']['headers']={'Authorization':'secret'}
        self.assertEqual(r.emit(Event(json.dumps(value))),'invalid')
        r.close()
        self.assertNotIn(b'secret',self.path.read_bytes())

    def test_runtime_database_error_does_not_block_admission(self):
        r=self.recorder(normal_limit=3)
        from unittest.mock import patch
        with patch.object(r,'_transaction',side_effect=sqlite3.OperationalError('fixture full')):
            r.record('run.heartbeat',{})
            until=time.monotonic()+1
            while r.health()['errors']==0 and time.monotonic()<until: time.sleep(.01)
            started=time.monotonic()
            for _ in range(30): r.record('run.heartbeat',{})
            self.assertLess(time.monotonic()-started,.25)
            self.assertGreater(r.health()['errors'],0)
            self.assertLessEqual(r.health()['normal_depth'],3)
            self.assertGreater(r.health()['dropped'],0)
            r.close(deadline_seconds=.05)

    def test_retention_expires_closed_run_and_emits_marker(self):
        r=self.recorder();trace=TraceContext(r.run_id,new_id(),decision_id=new_id())
        r.record('decision.requested',{},trace=trace,priority='critical');r.close()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE runs SET ended_at_utc='2000-01-01T00:00:00Z'")
        second=self.recorder();second.record('run.heartbeat',{})
        until=time.monotonic()+2
        while time.monotonic()<until:
            with open_reader(self.path) as db: expired=get_experience(db,trace.correlation_id) is None
            if expired: break
            time.sleep(.01)
        second.close()
        self.assertTrue(expired)
        with open_reader(self.path) as db:
            kinds={e['event_type'] for e in read_events(db)['events']}
            self.assertIn('retention.expired',kinds)

    def test_reader_connection_closes_after_context(self):
        r=self.recorder();r.close()
        with open_reader(self.path) as db: self.assertEqual(db.execute('SELECT 1').fetchone()[0],1)
        with self.assertRaises(sqlite3.ProgrammingError): db.execute('SELECT 1')

    def test_transient_writer_fault_recovers_with_durable_markers(self):
        r=self.recorder();original=r._transaction;failed=[False]
        def transient(*args,**kwargs):
            if not failed[0]:
                failed[0]=True;raise sqlite3.OperationalError('fixture busy')
            return original(*args,**kwargs)
        from unittest.mock import patch
        with patch.object(r,'_transaction',side_effect=transient):
            r.record('run.heartbeat',{})
            until=time.monotonic()+2
            while time.monotonic()<until:
                with open_reader(self.path) as db:
                    recovered=db.execute("SELECT 1 FROM events WHERE event_type='recorder.recovered'").fetchone()
                if recovered: break
                time.sleep(.01)
        r.close();self.assertTrue(recovered)


if __name__=='__main__': unittest.main()
