"""Real persistence and lifecycle tests; no live Discord/game/GPU/model service."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from gregory_core.runtime import Core, FixtureProvider, LMStudioProvider, CoreDegraded, AdmissionRefused
from gregory_core.control_http import ControlServer
from gregory_core.memory import MemoryStore
from core_fixture_experience import capture_fixture


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def start(self, **kwargs):
        core=Core(self.root/'character',**kwargs).start()
        def cleanup():
            if core.accepting: core.call('stop')
            core.thread.join(5)
        self.addCleanup(cleanup)
        return core

    def test_empty_lookup_abstains_and_current_state_is_unknown(self):
        core=self.start()
        result=core.call('lookup',{'query':'crate'})
        self.assertEqual(result['hits'],[])
        self.assertTrue(result['historical_only'])
        self.assertEqual(result['current_world_state'],'unknown; requires fresh adapter observations')
        self.assertEqual(result['mode'],'keyword')

    def test_memory_contract_fault_is_visible_for_search_and_exact_id(self):
        core=self.start()
        mid=core.call('import',capture_fixture(self.root/'capture'))['memory_id']
        original=core.call('lookup',{'memory_id':mid})['hits'][0]
        bad_row=dict(original,historical_only=False,current_world_state='FAULT: backend claimed current state')
        cases=[('search',{'query':'wood_crate001a'},dict(hits=[bad_row],mode='keyword',
                 historical_only=False,current_world_state=bad_row['current_world_state'])),
               ('inspect',{'memory_id':mid},bad_row)]
        for method,query,backend in cases:
            with self.subTest(method=method),patch.object(MemoryStore,method,return_value=backend):
                result=core.call('lookup',query)
                # Fault injection must be observable: normal A4 assertions would
                # fail on this result rather than a wrapper hiding the defect.
                self.assertIs(result['historical_only'],False)
                self.assertEqual(result['current_world_state'],bad_row['current_world_state'])
                self.assertIs(result['hits'][0]['historical_only'],False)
        actual=core.call('lookup',{'memory_id':mid})
        self.assertTrue(actual['historical_only'])
        self.assertEqual(actual['hits'][0]['evidence'],original['evidence'])

    def test_model_counter_requires_request_type_not_requested_text(self):
        class MisleadingName(FixtureProvider):name='requested appears in every phase'
        core=self.start(provider=MisleadingName())
        core.call('think',{'prompt':'fixture counter check'})
        status=core.call('status')
        self.assertEqual(status['model_counts'],{'live':0,'fixture':1})
        core.call('stop');core.thread.join(5)
        # A prior prototype's request has only an exact phase, no new type.
        # Keeping its count must not require editing historical journal rows.
        with closing(sqlite3.connect(core.root/'core.sqlite3')) as db:
            db.execute("UPDATE events SET payload=json_remove(payload,'$.type') WHERE kind='model'")
            db.commit()
        restarted=self.start()
        self.assertEqual(restarted.call('status')['model_counts'],{'live':0,'fixture':1})

    def test_recorder_memory_survives_core_restart_with_citations(self):
        experience=capture_fixture(self.root/'capture')
        core=self.start()
        core.call('goals',{'goals':['Remember experiences across worlds']})
        identity=core.call('status')['profile']
        imported=core.call('import',experience)
        before=core.call('lookup',{'query':'wood_crate001a'})
        exact_before=core.call('lookup',{'memory_id':imported['memory_id']})['hits'][0]
        self.assertEqual(before['hits'][0]['memory_id'],imported['memory_id'])
        self.assertTrue(before['hits'][0]['evidence'])
        self.assertTrue(all(e['source_label']=='fixture-NOT-live-GMod' for e in before['hits'][0]['evidence']))
        source_ids={e['event_id'] for e in experience['events']}
        self.assertTrue({e['event_id'] for e in before['hits'][0]['evidence']} <= source_ids)
        core.call('stop');core.thread.join(5)
        reopened=self.start()
        after=reopened.call('lookup',{'query':'wood_crate001a'})
        exact_after=reopened.call('lookup',{'memory_id':imported['memory_id']})['hits'][0]
        self.assertEqual(exact_before['evidence'],exact_after['evidence'])
        self.assertEqual(exact_before['claims'],exact_after['claims'])
        self.assertTrue(exact_after['historical_only'])
        self.assertEqual(after['hits'][0]['memory_id'],imported['memory_id'])
        self.assertEqual(reopened.call('status')['profile'],identity)
        self.assertEqual(after['current_world_state'],'unknown; requires fresh adapter observations')
        self.assertEqual(reopened.call('status')['adapters']['game']['state'],'not-connected')

    def test_adapter_restart_and_game_disconnect_do_not_reset_character(self):
        core=self.start()
        identity=core.call('status')['profile']['character_id']
        core.call('adapter',dict(kind='game',session='A',event='connect',fixture=True))
        core.call('adapter',dict(kind='voice',session='voice-A',event='connect',fixture=True))
        core.call('adapter',dict(kind='game',session='A',event='disconnect'))
        core.call('adapter',dict(kind='game',session='B',event='connect',fixture=True))
        core.call('adapter',dict(kind='voice',session='voice-A',event='disconnect'))
        core.call('adapter',dict(kind='voice',session='voice-B',event='connect',fixture=True))
        self.assertTrue(core.thread.is_alive())
        self.assertEqual(core.call('status')['profile']['character_id'],identity)
        with self.assertRaisesRegex(ValueError,'old/disconnected'):
            core.call('adapter',dict(kind='game',session='A',event='heartbeat'))

    def test_stale_heartbeat_is_not_a_live_connection(self):
        core=self.start(heartbeat_seconds=.02)
        core.call('adapter',dict(kind='game',session='A',event='connect',fixture=True))
        time.sleep(.04)
        self.assertEqual(core.call('status')['adapters']['game']['state'],'stale')

    def test_removed_object_report_cannot_rewrite_or_promote_historical_memory(self):
        core=self.start()
        imported=core.call('import',capture_fixture(self.root/'capture'))
        original=core.call('lookup',{'memory_id':imported['memory_id']})['hits'][0]
        core.call('adapter',dict(kind='game',session='B',event='connect',fixture=True))
        for observation in (None,{'changed_object':'decoy'}, {'object_at_old_spot':False}):
            if observation is not None:
                core.call('adapter',dict(kind='game',session='B',event='event',category='observation',
                          observed_at=time.time(),data=observation))
            result=core.call('lookup',{'memory_id':imported['memory_id']})
            self.assertEqual(result['hits'][0]['memory_id'],imported['memory_id'])
            self.assertTrue(result['hits'][0]['historical_only'])
            self.assertEqual(result['hits'][0]['origin'],'fixture')
            self.assertEqual(result['hits'][0]['evidence'],original['evidence'])
            self.assertEqual(result['hits'][0]['claims'],original['claims'])
            self.assertEqual(result['current_world_state'],'unknown; requires fresh adapter observations')
            ranked=core.call('lookup',{'query':'wood_crate001a'})
            self.assertEqual(ranked['hits'][0]['memory_id'],imported['memory_id'])
            self.assertTrue(ranked['hits'][0]['historical_only'])
            self.assertEqual(ranked['current_world_state'],'unknown; requires fresh adapter observations')
        event=next(e for e in core.call('status')['events'] if e['kind']=='memory')
        self.assertTrue(event['fixture'])
        self.assertEqual(event['payload']['fixture_memory_ids'],[imported['memory_id']])

    def test_categories_preserve_memory_inference_and_outcome_boundaries(self):
        core=self.start(provider=FixtureProvider())
        core.call('adapter',dict(kind='game',session='A',event='connect',fixture=True))
        for kind in ('observation','inference','decision','outcome'):
            core.call('adapter',dict(kind='game',session='A',event='event',category=kind,
                      observed_at=time.time(),executor='fixture-executor',data={'text':'fixture report'}))
        core.call('think',{'prompt':'A fixture-only model transport check'})
        status=core.call('status')
        self.assertTrue({'observation','inference','decision','outcome','model'} <= {e['kind'] for e in status['events']})
        self.assertFalse(status['live_state_available'])
        self.assertTrue(all(e['fixture'] for e in status['events'] if e['kind']=='model'))
        self.assertFalse(next(e for e in status['events'] if e['kind']=='decision')['payload']['dispatched'])
        self.assertEqual(status['model_counts'],{'live':0,'fixture':1})
        self.assertTrue(all(e['origin']=='fixture' for e in status['events'] if e['fixture']))
        with self.assertRaises(ValueError):
            core.call('adapter',dict(kind='game',session='A',event='event',category='memory',data={}))

    def test_stale_future_observation_rejected_not_promoted(self):
        core=self.start()
        core.call('adapter',dict(kind='game',session='A',event='connect',fixture=True))
        for when in (time.time()-30,time.time()+30):
            with self.assertRaisesRegex(ValueError,'stale/future'):
                core.call('adapter',dict(kind='game',session='A',event='event',category='observation',observed_at=when,data={}))
        self.assertFalse(any(e['kind']=='observation' for e in core.call('status')['events']))

    def test_owner_stop_drains_accepted_writes_and_rejects_new_work(self):
        core=self.start()
        began=time.monotonic()
        futures=[core.submit('goals',{'goals':[str(n)]}) for n in range(40)]
        stopped=core.submit('stop')
        with self.assertRaisesRegex(RuntimeError,'admission closed'):
            core.submit('goals',{'goals':['must not commit']})
        results=[f.result(10) for f in futures]
        self.assertEqual([r['_result']['sequence'] for r in results],list(range(1,41)))
        self.assertTrue(stopped.result(10)['databases_closed'])
        core.thread.join(5)
        self.assertLess(time.monotonic()-began,10)
        refusal=json.loads((core.root/'control-refusals.jsonl').read_text().splitlines()[-1])
        self.assertEqual(refusal['type'],'admission_refused')
        self.assertEqual(core.commands.unfinished_tasks,0)
        with closing(sqlite3.connect(core.root/'core.sqlite3')) as db:
            profile=json.loads(db.execute('SELECT value FROM profile').fetchone()[0])
            self.assertEqual(profile['goals'],['39'])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='decision'").fetchone()[0],40)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertIn('owner_stop_drained',db.execute('SELECT payload FROM events ORDER BY seq DESC LIMIT 1').fetchone()[0])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM command_results').fetchone()[0],41)
        with closing(sqlite3.connect(core.root/'episodes.sqlite3')) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        restarted=self.start()
        self.assertEqual(restarted.call('status')['profile']['goals'],['39'])

    def test_empty_and_wrong_episode_controls_use_same_exact_id_query(self):
        core=self.start()
        expected=core.call('import',capture_fixture(self.root/'expected-episode'))['memory_id']
        self.assertEqual(core.call('lookup',{'memory_id':expected})['hits'][0]['memory_id'],expected)
        control=Core(self.root/'control-character').start()
        self.addCleanup(lambda: control.call('stop') if control.accepting else None)
        self.assertEqual(control.call('lookup',{'memory_id':expected})['hits'],[])
        wrong=control.call('import',capture_fixture(self.root/'different-episode'))
        self.assertNotEqual(wrong['memory_id'],expected)
        result=control.call('lookup',{'memory_id':expected})
        self.assertEqual(result['hits'],[])
        self.assertNotIn('say',result)

    def test_database_write_failure_is_reported_and_does_not_commit_goal(self):
        core=self.start()
        with closing(sqlite3.connect(core.root/'core.sqlite3')) as db:
            db.execute("CREATE TRIGGER fail_profile BEFORE UPDATE ON profile BEGIN SELECT RAISE(ABORT,'fixture-write-failure'); END;")
            db.commit()
        with self.assertRaisesRegex(sqlite3.IntegrityError,'fixture-write-failure'):
            core.call('goals',{'goals':['not committed']})
        status=core.call('status')
        self.assertEqual(status['profile']['goals'],[])
        self.assertTrue(any(e['kind']=='error' and e['payload']['command']=='goals' for e in status['events']))

    def test_journal_failure_during_stop_reports_uncommitted_work_without_hanging(self):
        entered,release=threading.Event(),threading.Event()
        class BlockedFixture(FixtureProvider):
            def generate(self,profile,prompt):
                entered.set()
                if not release.wait(5):raise RuntimeError('fixture release deadline')
                return super().generate(profile,prompt)
        core=self.start(provider=BlockedFixture());self.addCleanup(release.set)
        pending=core.submit('think',{'prompt':'blocked fixture call'})
        self.assertTrue(entered.wait(2))
        with self.assertRaisesRegex(RuntimeError,'model already busy'):
            core.submit('think',{'prompt':'must not build an unbounded model queue'})
        with closing(sqlite3.connect(core.root/'core.sqlite3')) as db:
            db.execute("CREATE TRIGGER fail_journal BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'fixture-journal-failure'); END;")
            db.commit()
        write=core.submit('goals',{'goals':['not committed']})
        stop=core.submit('stop');release.set()
        for future in (pending,write,stop):
            with self.assertRaises(Exception):future.result(5)
        self.assertTrue(core.finished.wait(2))
        report=json.loads(core.failure_path.read_text())
        self.assertEqual({v['action'] for v in report['uncommitted_commands']},{'think','goals','stop'})
        self.assertEqual(core.state,'failed')

    def test_busy_store_at_stop_degrades_loudly_and_releases_writer(self):
        core=self.start()
        lock=sqlite3.connect(core.root/'core.sqlite3')
        lock.execute('BEGIN IMMEDIATE')
        began=time.monotonic()
        stop=core.submit('stop')
        with self.assertRaises(CoreDegraded) as raised:stop.result(8)
        self.assertLess(time.monotonic()-began,10)
        receipt=raised.exception.receipt
        self.assertFalse(receipt['fully_drained'])
        self.assertEqual(receipt['exit_code'],1)
        self.assertEqual(receipt['uncommitted_commands'][0]['action'],'stop')
        self.assertNotIn('stopped',receipt)
        lock.rollback();lock.close();core.thread.join(2)
        self.assertEqual(json.loads(core.failure_path.read_text()),receipt)
        restarted=self.start()
        self.assertNotEqual(restarted.run_id,core.run_id)

    def test_writer_lock_refuses_second_core_without_taking_over(self):
        first=self.start()
        second=Core(first.root)
        with self.assertRaises(RuntimeError):second.start()
        second.thread.join(5)
        self.assertTrue(first.thread.is_alive())

    def test_model_seam_reuses_existing_budget_and_excludes_reasoning(self):
        core=self.start(provider=LMStudioProvider('http://127.0.0.1:1234/v1/chat/completions','configured-gemma'))
        class Response:
            def raise_for_status(self):pass
            def json(self):return {'choices':[{'message':{'content':'{"say":"A proposed reply","intent":{"kind":"wait"}}','reasoning_content':'PRIVATE NOT READ'}}]}
        import types
        import greg_model
        budget_before=(greg_model._min_tokens,greg_model._timeout,greg_model._reasoning)
        from unittest.mock import Mock
        fake_requests=types.ModuleType('requests');fake_requests.post=Mock(return_value=Response())
        with patch.dict(sys.modules,{'requests':fake_requests}):
            result=core.call('think',{'prompt':'fixture transport'})
        post=fake_requests.post
        self.assertFalse(result['dispatched'])
        self.assertFalse(result['fixture'])
        self.assertEqual(post.call_args.kwargs['json']['reasoning_effort'],'none')
        self.assertEqual(post.call_args.kwargs['json']['max_tokens'],1024)
        self.assertEqual((greg_model._min_tokens,greg_model._timeout,greg_model._reasoning),budget_before)
        self.assertNotIn('PRIVATE NOT READ',json.dumps(core.call('status')))


class ProcessAndHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def request(self, server, path, data=None, token=None):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        with urlopen(Request(server.url+path,data=None if data is None else json.dumps(data).encode(),headers=headers),timeout=10) as response:
            body=response.read()
            return json.loads(body) if response.headers['Content-Type'].startswith('application/json') else body.decode()

    def test_http_read_only_ui_capabilities_and_injection_are_bounded(self):
        core=Core(self.root/'core').start();server=ControlServer(core).start()
        try:
            page=self.request(server,'/')
            self.assertIn('One Gregory. Multiple worlds.',page)
            self.assertIn('textContent',page)
            self.assertNotIn(server.owner_token,page)
            before=core.call('status')['profile']
            for path in ('/api/stop','/api/goals','/api/import','/api/profile'):
                with self.assertRaises(HTTPError) as denied:
                    self.request(server,path,{},server.adapter_token)
                self.assertEqual(denied.exception.code,403)
                refusal=json.loads(denied.exception.read())
                self.assertEqual(refusal,{'type':'capability_refused','actor':'adapter','scope':path})
            errors=[e for e in core.call('status')['events'] if e['kind']=='error']
            self.assertEqual(len(errors),4)
            self.assertEqual({e['payload']['scope'] for e in errors},{'/api/stop','/api/goals','/api/import','/api/profile'})
            self.assertTrue(all(e['payload']['actor']=='adapter' for e in errors))
            self.assertEqual(core.call('status')['profile'],before)
            self.request(server,'/api/goals',{'goals':['owner still works']},server.owner_token)
            with self.assertRaises(HTTPError):
                self.request(server,'/api/goals',{'goals':['not authorized']})
            self.assertEqual(self.request(server,'/api/status')['profile']['goals'],['owner still works'])
            # A closed observer request is unrelated to Core lifecycle.
            self.assertTrue(core.thread.is_alive())
            self.request(server,'/api/stop',{},server.owner_token)
        finally:
            if core.accepting:core.call('stop')
            server.close();core.thread.join(5)

    def test_five_stages_join_and_outcome_is_read_by_separate_fixture_executor(self):
        core=Core(self.root/'core',provider=FixtureProvider()).start();server=ControlServer(core).start()
        control=self.root/'control.json';control.write_text(json.dumps(server.control_receipt()))
        try:
            experience=capture_fixture(self.root/'capture')
            correlation=experience['correlation_id']
            imported=core.call('import',experience)
            core.call('think',{'prompt':'Exercise the fixture marker only','correlation_id':correlation})
            proc=subprocess.run([sys.executable,'-B',str(ROOT/'tools/gregory_control.py'),'fixture-executor',
                '--control',str(control),'--root',str(self.root/'executor'),'--correlation',correlation],
                capture_output=True,text=True,timeout=10)
            self.assertEqual(proc.returncode,0,proc.stderr)
            result=json.loads(proc.stdout)
            events=core.call('correlation',{'correlation_id':correlation})['events']
            stages=[e for e in events if e['kind'] in ('observation','memory','inference','decision','outcome')]
            self.assertEqual([e['kind'] for e in stages],['observation','memory','inference','decision','outcome'])
            self.assertTrue(all(e['origin']=='fixture' for e in stages))
            outcome=stages[-1]['payload']
            self.assertEqual(outcome['executor'],'fixture-marker-executor')
            self.assertNotEqual(outcome['report']['executor_pid'],os.getpid())
            self.assertTrue(outcome['report']['marker_exists'])
            import hashlib
            self.assertEqual(outcome['report']['marker_sha256'],hashlib.sha256((self.root/'executor/fixture-marker.txt').read_bytes()).hexdigest())
            self.assertEqual(stages[1]['payload']['memory_id'],imported['memory_id'])
            self.assertEqual(core.call('status')['model_counts'],{'live':0,'fixture':1})
        finally:
            if core.accepting:core.call('stop')
            server.close();core.thread.join(5)

    def test_process_busy_store_stop_exits_nonzero_with_degraded_receipt(self):
        # Windows venv python.exe redirects to a worker with a different PID.
        # Use the actual interpreter so the fixture owns the reported process.
        command=[getattr(sys, '_base_executable', sys.executable) if os.name=='nt' else sys.executable,'-B',str(ROOT/'tools/gregory_control.py')]
        log=(self.root/'failed-core-process.log').open('w');self.addCleanup(log.close)
        proc=subprocess.Popen(command+['serve','--root',str(self.root/'character')],stdout=log,stderr=log)
        control=self.root/'character/control.json';lock=None
        try:
            deadline=time.monotonic()+10
            while not control.exists() and proc.poll() is None and time.monotonic()<deadline:time.sleep(.03)
            self.assertIsNone(proc.poll())
            config=json.loads(control.read_text())
            class Server:url=config['url']
            lock=sqlite3.connect(self.root/'character/core.sqlite3');lock.execute('BEGIN IMMEDIATE')
            began=time.monotonic()
            with self.assertRaises(HTTPError) as failed:self.request(Server,'/api/stop',{},config['owner_token'])
            receipt=json.loads(failed.exception.read())['receipt']
            self.assertEqual(receipt['type'],'core_degraded')
            self.assertFalse(receipt['fully_drained'])
            self.assertEqual(receipt['uncommitted_commands'][0]['action'],'stop')
            failed_exit=proc.wait(8)
            self.assertEqual(failed_exit,1)
            self.assertLess(time.monotonic()-began,10)
            lock.rollback();lock.close();lock=None
            failure=json.loads(next((self.root/'character').glob('failure-*.json')).read_text())
            self.assertEqual(receipt,failure)
            second=subprocess.Popen(command+['serve','--root',str(self.root/'character')],stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    current=json.loads(control.read_text())
                    if current['run_id']!=config['run_id']:break
                    time.sleep(.03)
                else:self.fail('replacement Core did not acquire writer and publish readiness')
                class Replacement:url=current['url']
                status=self.request(Replacement,'/api/status')
                self.assertEqual(status['core']['pid'],second.pid)
                self.assertNotEqual(status['core']['core_instance_id'],config['run_id'])
                self.request(Replacement,'/api/stop',{},current['owner_token'])
                restarted_exit=second.wait(8)
                self.assertEqual(restarted_exit,0)
                print(json.dumps({'acceptance':'A7b','failed_pid':proc.pid,'failed_process_returncode':failed_exit,
                    'degraded_receipt':receipt,'replacement_pid':second.pid,
                    'replacement_instance':status['core']['core_instance_id'],
                    'replacement_acquired_writer_and_answered_health':True,'replacement_process_returncode':restarted_exit}))
            finally:
                if second.poll() is None:second.terminate();second.wait(5)
        finally:
            if lock is not None:lock.rollback();lock.close()
            if proc.poll() is None:proc.terminate();proc.wait(5)  # test-owned process only

    def test_separate_core_and_adapter_processes_restart_independently(self):
        # Windows venv python.exe redirects to a worker with a different PID.
        # Use the actual interpreter so the fixture owns the reported process.
        command=[getattr(sys, '_base_executable', sys.executable) if os.name=='nt' else sys.executable,'-B',str(ROOT/'tools/gregory_control.py')]
        log=(self.root/'core-process.log').open('w');self.addCleanup(log.close)
        proc=subprocess.Popen(command+['serve','--root',str(self.root/'character')],stdout=log,stderr=log)
        control=self.root/'character/control.json'
        try:
            deadline=time.monotonic()+10
            while not control.exists() and proc.poll() is None and time.monotonic()<deadline:time.sleep(.03)
            self.assertIsNone(proc.poll())
            config=json.loads(control.read_text())
            from gregory_core import control_http
            class Server: url=config['url']
            first=self.request(Server,'/api/status')
            identity=first['profile']['character_id']
            previous=first['core']['uptime_seconds']
            for kind in ('game','voice','game','voice'):
                adapter=subprocess.run(command+['fixture-adapter','--control',str(control),'--kind',kind,'--seconds','.1'],capture_output=True,text=True,timeout=10)
                self.assertEqual(adapter.returncode,0,adapter.stderr)
                self.assertIsNone(proc.poll())
                status=self.request(Server,'/api/status')
                self.assertEqual(status['profile']['character_id'],identity)
                self.assertEqual(status['core']['core_instance_id'],first['core']['core_instance_id'])
                self.assertGreater(status['core']['uptime_seconds'],previous)
                previous=status['core']['uptime_seconds']
                boots=[e for e in status['events'] if e['payload'].get('event')=='core_started']
                self.assertEqual(len(boots),1)
                began=time.monotonic();self.request(Server,'/api/status')
                self.assertLess(time.monotonic()-began,2)
                self.assertEqual(status['adapters'][kind]['state'],'disconnected')
            # Force only this test-owned fixture child to disappear without a
            # disconnect packet; no live game or voice process is involved.
            child=subprocess.Popen(command+['fixture-adapter','--control',str(control),'--kind','game','--seconds','30'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    if self.request(Server,'/api/status')['adapters']['game'].get('pid_reported')==child.pid:break
                    time.sleep(.03)
                else:self.fail('fixture child failed to connect')
                child.terminate();child.wait(5)
                time.sleep(3.1)
                status=self.request(Server,'/api/status')
                self.assertEqual(status['adapters']['game']['state'],'stale')
                self.assertEqual(status['core']['core_instance_id'],first['core']['core_instance_id'])
                self.assertGreater(status['core']['uptime_seconds'],previous)
                self.assertEqual(sum(e['payload'].get('event')=='core_started' for e in status['events']),1)
            finally:
                if child.poll() is None:child.terminate();child.wait(5)
            self.request(Server,'/api/stop',{},config['owner_token'])
            self.assertEqual(proc.wait(10),0)
        finally:
            if proc.poll() is None:
                try:
                    config=json.loads(control.read_text())
                    req=Request(config['url']+'/api/stop',data=b'{}',headers={'Authorization':'Bearer '+config['owner_token']})
                    with urlopen(req,timeout=5) as response:response.read()
                    proc.wait(10)
                finally:
                    if proc.poll() is None:proc.terminate();proc.wait(5)  # this test-owned child only


if __name__=='__main__':unittest.main()
