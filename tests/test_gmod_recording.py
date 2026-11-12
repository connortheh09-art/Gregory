"""Real private Recorder/Core databases; all generated gameplay is synthetic fixture data."""
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'tools'))
from gregory_core.runtime import Core
from gregory_core.control_http import ControlServer
from gregory_core.gmod_recording import (read_page, load_cursor, save_after_receipt, RecordingRefused, digest)
from gregory_gmod_adapter import once, connection
from core_fixture_experience import capture_fixture
from greg_recorder import open_reader, Recorder


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        capture_fixture(self.root/'capture')
        self.path = self.root/'capture/fixture-recorder.sqlite3'
        with open_reader(self.path) as db:
            self.database_id = db.execute("SELECT value FROM meta WHERE key='database_id'").fetchone()[0]
        self.page = read_page(self.path, database_id=self.database_id)
        event = next(e for e in self.page['events'] if e['event_type']=='observation.accepted')
        self.binding = dict(database_id=self.database_id, run_id=event['run_id'], session_id=event['session_id'],
                            bridge_session=event['control']['bridge_session'], control_epoch=event['control']['control_epoch'])

    def core(self, **kwargs):
        core = Core(self.root/'character', **kwargs).start()
        def stop():
            if core.accepting: core.call('stop')
            core.thread.join(5)
        self.addCleanup(stop)
        return core

    def connect(self, core, session='recorded-A'):
        core.call('adapter', dict(kind='game', session=session, event='connect', fixture=True, recording=self.binding))

    def deliver(self, core, page=None, *, session='recorded-A', origin='replay', seen_at=None):
        return core.call('adapter', dict(kind='game', session=session, event='recorded_batch',
            page=self.page if page is None else page, origin=origin, seen_at=time.time() if seen_at is None else seen_at))

    def test_retry_after_commit_before_cursor_across_core_restart(self):
        core=self.core(); self.connect(core)
        first=self.deliver(core)
        self.assertEqual(first['accepted'],len(self.page['events']))
        # Deliberately lose the acknowledgement/cursor write, then restart Core.
        core.call('stop'); core.thread.join(5)
        replacement=self.core(); self.connect(replacement, 'recorded-B')
        retry=self.deliver(replacement, session='recorded-B')
        self.assertEqual((retry['accepted'],retry['duplicates']), (0,len(self.page['events'])))
        save_after_receipt(self.root/'cursor.json',self.page,retry)
        self.assertEqual(load_cursor(self.root/'cursor.json',self.database_id),self.page['next_cursor'])
        self.assertEqual(replacement.call('status')['memory_count'],0)
        with closing(sqlite3.connect(replacement.root/'core.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM recorder_ingest').fetchone()[0],len(self.page['events']))

    def test_same_identity_changed_digest_refuses_and_batch_rolls_back(self):
        core=self.core(); self.connect(core); self.deliver(core)
        bad=copy.deepcopy(self.page)
        conflict=copy.deepcopy(bad['events'][0]); conflict['payload']['status']='changed fixture'
        fresh=copy.deepcopy(conflict); fresh['event_id']=str(uuid.uuid4())
        fresh['source_sequence']=max(e['source_sequence'] for e in self.page['events'])+1
        start=self.page['next_cursor']
        fresh['ingest_sequence']=start+1; conflict['ingest_sequence']=start+2
        bad.update(events=[fresh,conflict],after_cursor=start,next_cursor=start+2,last_available_cursor=start+2)
        with self.assertRaises(RecordingRefused) as caught: self.deliver(core,bad)
        self.assertEqual(caught.exception.receipt['reason'],'canonical_identity_conflict')
        with closing(sqlite3.connect(core.root/'core.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM recorder_ingest').fetchone()[0],len(self.page['events']))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE source LIKE 'recorder:%'").fetchone()[0],len(self.page['events']))

    def test_older_same_database_id_backup_is_beyond_tail(self):
        backup=self.root/'older.sqlite3'
        with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(backup)) as target:
            source.backup(target)
        recorder=Recorder(self.path,'later-fixture'); self.assertTrue(recorder.wait_ready()); recorder.close()
        newer=read_page(self.path,database_id=self.database_id)
        self.assertGreater(newer['next_cursor'],self.page['next_cursor'])
        with self.assertRaises(RecordingRefused) as caught:
            read_page(backup,database_id=self.database_id,after=newer['next_cursor'])
        self.assertEqual(caught.exception.receipt['reason'],'cursor_beyond_tail')

    def test_empty_rollback_is_not_a_healthy_empty_poll(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DELETE FROM events'); db.commit()
        with self.assertRaisesRegex(RecordingRefused,'cursor_beyond_tail'):
            read_page(self.path,database_id=self.database_id,after=self.page['next_cursor'])

    def test_changed_database_id_is_hard_refusal(self):
        capture_fixture(self.root/'other')
        handles=[]
        def track(path):
            db=open_reader(path); handles.append(db); return db
        with patch('gregory_core.gmod_recording.open_reader',track):
            with self.assertRaisesRegex(RecordingRefused,'database_changed'):
                read_page(self.root/'other/fixture-recorder.sqlite3',database_id=self.database_id)
        with self.assertRaises(sqlite3.ProgrammingError): handles[0].execute('SELECT 1')
        core=self.core(); self.connect(core)
        bad=copy.deepcopy(self.page); bad['database_id']=str(uuid.uuid4())
        with self.assertRaisesRegex(RecordingRefused,'database_changed'): self.deliver(core,bad)

    def test_retention_gap_refuses(self):
        first=self.page['events'][3]['ingest_sequence']
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DELETE FROM events WHERE ingest_sequence<?',(first,)); db.commit()
        with self.assertRaisesRegex(RecordingRefused,'retention_gap'):
            read_page(self.path,database_id=self.database_id,after=1)

    def test_stale_replay_is_explicit_on_http_surface_not_current_or_memory(self):
        page=copy.deepcopy(self.page)
        for event in page['events']: event['source_timestamp_utc']='2000-01-01T00:00:00.000000Z'
        core=self.core(); self.connect(core); self.deliver(core,page,seen_at=time.time()-30)
        server=ControlServer(core).start(); self.addCleanup(server.close)
        with urlopen(server.url+'/api/status') as response: status=json.load(response)
        rows=[e for e in status['events'] if e['source'].startswith('recorder:')]
        self.assertTrue(rows)
        self.assertTrue(all(e['fixture'] and e['origin']=='fixture' and e['payload']['origin']=='replay' for e in rows))
        self.assertTrue(all(e['payload']['source_age_seconds']>86400 for e in rows))
        self.assertEqual(rows[0]['payload']['envelope']['source_timestamp_utc'],'2000-01-01T00:00:00.000000Z')
        self.assertFalse(status['live_state_available']); self.assertEqual(status['memory_count'],0)
        self.assertEqual(status['model_counts'],{'live':0,'fixture':0})
        self.assertTrue(all(e['kind']!='model' for e in rows))
        empty=core.call('lookup',{'query':'crate'}); self.assertEqual(empty['hits'],[])
        self.assertTrue(empty['historical_only'])

    def test_new_receipt_cannot_freshen_old_source_or_wrong_session(self):
        core=self.core(); self.connect(core)
        page=copy.deepcopy(self.page)
        page['events'][0]['source_timestamp_utc']='2000-01-01T00:00:00.000000Z'
        with self.assertRaisesRegex(RecordingRefused,'stale_or_future_source'): self.deliver(core,page,origin='live')
        page=copy.deepcopy(self.page); page['events'][0]['session_id']='wrong-session'
        with self.assertRaisesRegex(RecordingRefused,'source_session_mismatch'): self.deliver(core,page)

    def test_fresh_source_live_label_is_possible_but_never_current_state(self):
        core=self.core(); self.connect(core)
        receipt=self.deliver(core,origin='live')
        self.assertGreater(receipt['accepted'],0)
        rows=[e for e in core.call('status')['events'] if e['source'].startswith('recorder:')]
        self.assertTrue(all(e['payload']['origin']=='live' and e['fixture'] for e in rows))
        self.assertFalse(core.call('status')['live_state_available'])

    def test_one_page_cli_uses_adapter_only_receipt_over_real_loopback(self):
        core=self.core(); server=ControlServer(core).start(); self.addCleanup(server.close)
        cfg=self.root/'adapter only.json'
        cfg.write_text(json.dumps(dict(url=server.url,adapter_token=server.adapter_token,recording=self.binding,fixture=True)))
        cursor=self.root/'cli cursor.json'
        result=subprocess.run([sys.executable,str(ROOT/'tools/gregory_gmod_adapter.py'),
            '--connection',str(cfg),'--cursor',str(cursor),'--recorder-db',str(self.path)],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['accepted'],len(self.page['events']))
        self.assertEqual(load_cursor(cursor,self.database_id),self.page['next_cursor'])
        self.assertEqual(core.call('status')['adapters']['game']['state'],'disconnected')
        req=Request(server.url+'/api/import',data=b'{}',headers={'Authorization':'Bearer '+server.adapter_token})
        with self.assertRaises(HTTPError) as caught: urlopen(req)
        self.assertEqual(caught.exception.code,403)
        self.assertEqual(core.call('status')['memory_count'],0)
        self.assertTrue(any(e['payload'].get('type')=='capability_refused' and e['payload']['actor']=='adapter'
                            for e in core.call('status')['events']))

    def test_source_control_session_mismatch_and_stale_delivery_refuse(self):
        core=self.core(); self.connect(core)
        page=copy.deepcopy(self.page)
        event=next(e for e in page['events'] if e['event_type']=='observation.accepted')
        event['control']['bridge_session']='not-the-bound-game'
        with self.assertRaisesRegex(RecordingRefused,'source_session_mismatch'): self.deliver(core,page)
        with self.assertRaisesRegex(RecordingRefused,'stale_or_future_delivery'):
            self.deliver(core,seen_at=time.time()-30,origin='live')

    def test_heartbeat_tuning_does_not_change_observation_freshness(self):
        core=self.core(heartbeat_seconds=.001, freshness_seconds=3)
        core.call('adapter',dict(kind='game',session='A',event='connect',fixture=True))
        core.call('adapter',dict(kind='game',session='A',event='event',category='observation',observed_at=time.time()-.1,data={}))
        other=Core(self.root/'second',heartbeat_seconds=100,freshness_seconds=.001).start()
        self.addCleanup(lambda:(other.call('stop'),other.thread.join(5)))
        other.call('adapter',dict(kind='game',session='A',event='connect',fixture=True))
        with self.assertRaisesRegex(ValueError,'stale/future'):
            other.call('adapter',dict(kind='game',session='A',event='event',category='observation',observed_at=time.time()-.1,data={}))

    def test_snapshot_is_closed_before_delivery_and_cursor_needs_durable_receipt(self):
        core=self.core(); self.connect(core)
        seen=[]
        original=open_reader
        def track(path):
            db=original(path); seen.append(db); return db
        def deliver(page,origin,seen_at):
            with self.assertRaises(sqlite3.ProgrammingError): seen[-1].execute('SELECT 1')
            return self.deliver(core,page,origin=origin,seen_at=seen_at)
        with patch('gregory_core.gmod_recording.open_reader',track):
            receipt=once(self.path,self.root/'cursor.json',{'recording':self.binding},deliver)
        self.assertEqual(receipt['accepted'],len(self.page['events']))
        self.assertEqual(load_cursor(self.root/'cursor.json',self.database_id),self.page['next_cursor'])
        with self.assertRaisesRegex(RecordingRefused,'uncommitted_or_wrong_batch_receipt'):
            save_after_receipt(self.root/'bad-cursor.json',self.page,dict(receipt,_result={}))
        self.assertFalse((self.root/'bad-cursor.json').exists())

    def test_healthy_empty_tail_and_oversize_budget_are_distinct(self):
        page=read_page(self.path,database_id=self.database_id,after=self.page['next_cursor'])
        self.assertEqual(page['events'],[])
        self.assertEqual(page['next_cursor'],page['last_available_cursor'])
        with self.assertRaisesRegex(RecordingRefused,'event_exceeds_batch_budget'):
            read_page(self.path,database_id=self.database_id,max_bytes=1)
        with self.assertRaisesRegex(RecordingRefused,'invalid_batch_budget'):
            read_page(self.path,database_id=self.database_id,limit=65)

    def test_owner_config_is_not_an_adapter_receipt_and_cursor_is_db_bound(self):
        cfg=self.root/'combined.json'; cfg.write_text(json.dumps(dict(url='http://127.0.0.1:1',owner_token='not-a-real-secret',adapter_token='fixture-token')))
        with self.assertRaisesRegex(RecordingRefused,'adapter_only_connection_required'): connection(cfg)
        cursor=self.root/'cursor.json'; cursor.write_text(json.dumps(dict(database_id=str(uuid.uuid4()),cursor=1)))
        with self.assertRaisesRegex(RecordingRefused,'cursor_database_changed'): load_cursor(cursor,self.database_id)

    def test_cursor_cannot_overwrite_recorder_or_wal_files(self):
        before=self.path.read_bytes()
        nested=self.path.parent/'adapter'; nested.mkdir()
        for cursor in (self.path,Path(str(self.path)+'-wal'),Path(str(self.path)+'-shm'),nested/'cursor.json'):
            with self.assertRaisesRegex(RecordingRefused,'cursor_root_must_be_separate_from_recorder'):
                once(self.path,cursor,{'recording':self.binding},lambda *args: self.fail('must not deliver'))
        self.assertEqual(self.path.read_bytes(),before)

    def test_stale_cursor_temporary_is_recomputed_after_lost_ack(self):
        core=self.core(); self.connect(core); self.deliver(core)
        cursor=self.root/'cursor.json'
        temporary=cursor.with_name(cursor.name+'.tmp'); temporary.write_text('incomplete cursor from interrupted write')
        receipt=once(self.path,cursor,{'recording':self.binding},
            lambda page,origin,seen_at:self.deliver(core,page,origin=origin,seen_at=seen_at))
        self.assertEqual((receipt['accepted'],receipt['duplicates']),(0,len(self.page['events'])))
        self.assertEqual(load_cursor(cursor,self.database_id),self.page['next_cursor'])
        self.assertFalse(temporary.exists())
        # A directory in a reserved temp-file slot is refused, never recursively removed.
        temporary.mkdir()
        tail=read_page(self.path,database_id=self.database_id,after=self.page['next_cursor'])
        committed=self.deliver(core,tail)
        with self.assertRaisesRegex(RecordingRefused,'unsafe_cursor_temporary'):
            save_after_receipt(cursor,tail,committed)
        self.assertTrue(temporary.is_dir())

    def test_explicit_new_database_rebind_reports_new_namespace_not_continuation(self):
        core=self.core(); self.connect(core); original=self.deliver(core)
        replacement=self.root/'replacement.sqlite3'
        with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(replacement)) as target:
            source.backup(target)
        new_id=str(uuid.uuid4())
        with closing(sqlite3.connect(replacement)) as db:
            db.execute("UPDATE meta SET value=? WHERE key='database_id'",(new_id,)); db.commit()
        page=read_page(replacement,database_id=new_id)
        new_binding=dict(self.binding,database_id=new_id)
        core.call('adapter',dict(kind='game',session='explicit-rebind',event='connect',fixture=True,recording=new_binding))
        receipt=self.deliver(core,page,session='explicit-rebind')
        self.assertEqual(receipt['source_namespace'],'recorder:'+new_id)
        self.assertFalse(receipt['namespace_preexisting'])
        self.assertIn('not proof of continuity',receipt['namespace_notice'])
        self.assertEqual(receipt['accepted'],original['accepted'])
        duplicate=self.deliver(core,page,session='explicit-rebind')
        self.assertTrue(duplicate['namespace_preexisting'])
        self.assertEqual(duplicate['accepted'],0)


if __name__ == '__main__': unittest.main()
