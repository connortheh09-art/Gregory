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
        with sqlite3.connect(self.path) as db: db.execute('PRAGMA user_version=99')
        r=self.recorder();self.assertEqual(r.health()['status'],'degraded')
        with sqlite3.connect(self.path) as db: self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],99)

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
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE runs SET ended_at_utc=NULL,end_reason=NULL')
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
        # One batch writes original then conflicts: entire batch is rolled back.
        v=e.as_dict();v['payload']['count']=2;r.emit(Event(json.dumps(v,separators=(',',':'))))
        r.close()
        with open_reader(self.path) as db:
            rows=[v for v in read_events(db)['events'] if v['event_id']==e.as_dict()['event_id']]
            self.assertTrue(not rows or rows[0]['payload']['count']==1)


if __name__=='__main__': unittest.main()
