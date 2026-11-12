from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'deployments/oldpc'))
from greg_recorder import Recorder, open_reader, read_events
from greg_experience import ExperienceTracker
from gregory_core.runtime import Core, FixtureProvider
from gregory_core.supervised_game import react, RecordingRefused
from greg_supervised import SupervisedLane, ProducerMux
from greg_producers import ProducerGroup, ProducerDeadline
from concurrent.futures import ThreadPoolExecutor


class Provider(FixtureProvider):
    def generate(self, profile, prompt):
        self.prompt = prompt
        return dict(say='That looks like a dubious place for a crate.', intent=None, used_memory_ids=[])


class SensorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.recorder = Recorder(self.root/'recorder.sqlite3', 'fixture-sensor', max_mib=64)
        self.assertTrue(self.recorder.wait_ready())
        self.tracker = ExperienceTracker(self.recorder, landmark_capture=True)
        self.state = dict(steamid='fixture-agent', bridgeSession='fixture-bridge', controlEpoch=1,
            map='gm_construct', seq=1, t=1, serverTime=time.time(), enabled=True, dead=False,
            menu=False, stopped=False, pos=dict(x=0,y=0,z=0),
            eye=dict(hit=True,hitWorld=False,hitEntityValid=True,hitClass='prop_physics',
                hitPos=dict(x=20,y=10,z=5), entIndex=71,
                model='models/props_junk/wood_crate001a.mdl', entityPos=dict(x=20,y=10,z=5)))
        self.tracker.accepted_state(self.state)
        self.provider = Provider()
        self.core = Core(self.root/'core', provider=self.provider).start()
        self.lane = SupervisedLane(self.core, self.recorder, self.tracker)
        self.lane.update(self.state)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.lane.invalidate(); self.lane.jobs.request_stop()
        self.lane.jobs.join_until(time.monotonic()+3)
        if self.core.accepting:
            self.core.call('stop'); self.core.thread.join(5)
        self.tracker.shutdown(); self.recorder.close()

    def wait_for(self, predicate):
        deadline = time.monotonic()+3
        while time.monotonic()<deadline:
            self.lane.poll()
            if predicate(): return
            time.sleep(.01)
        self.fail('bounded fixture wait expired')

    def test_qwen_metadata_caption_reaches_actual_core_with_age_and_no_world_fact_promotion(self):
        trace = self.lane.begin_sensor()
        caption = 'A wooden crate near a wall.'
        self.assertTrue(self.lane.sensor(trace, dict(caption=caption, t=time.time()-6)))
        self.assertFalse(self.tracker.episodes[trace.correlation_id]['closed'])
        self.wait_for(lambda: self.lane.ready is not None)
        facts = json.loads(self.provider.prompt.split('GAME_OBSERVATION_REFERENCE: ')[1])
        self.assertEqual(facts['qwen_interpretation'], caption)
        self.assertGreaterEqual(facts['observation_age_at_request_seconds'], 6)
        self.assertFalse(facts['current_state_established'])
        self.assertEqual(facts['supporting_lua'][0]['landmark']['model'],
                         'models/props_junk/wood_crate001a.mdl')
        with closing(open_reader(self.recorder.path)) as db:
            rows = read_events(db, limit=64)['events']
        sensor = next(e for e in rows if e['event_type']=='sensor.result')
        self.assertNotIn('caption', sensor['payload'])
        self.assertEqual(sensor['payload']['caption_sha256'], hashlib.sha256(caption.encode()).hexdigest())

    def test_chat_distinguishes_configured_vision_from_missing_current_image(self):
        self.lane.vision_available = True
        self.assertTrue(self.lane.hear('Can you see me?'))
        self.wait_for(lambda:self.lane.ready is not None)
        self.assertIn('configured game snapshot adapter',self.provider.prompt)
        self.assertIn('No fresh image is supplied',self.provider.prompt)
        self.assertIn('never invent what is visible',self.provider.prompt)
        self.assertNotIn('GAME_OBSERVATION_REFERENCE:',self.provider.prompt)
        self.assertEqual(self.core.call('lookup', {'query':'crate'})['hits'], [])

    def test_publication_closes_then_imports_episode_and_recall_is_historical(self):
        trace = self.lane.begin_sensor()
        self.lane.sensor(trace, dict(caption='A wooden crate.',t=time.time()-.1))
        self.wait_for(lambda: self.lane.ready is not None)
        row = self.lane.take()
        # The real bridge reports only mailbox publication, never audible delivery.
        self.lane.published(row, True)
        self.assertTrue(self.tracker.episodes[trace.correlation_id]['closed'])
        self.wait_for(lambda: self.core.call('lookup', {'query':'wood_crate001a'})['hits'])
        hit = self.core.call('lookup', {'query':'wood_crate001a'})['hits'][0]
        self.assertTrue(hit['historical_only'])
        self.assertNotIn('wooden', hit['summary'].lower())
        self.assertTrue(hit['evidence'])

    def test_stop_during_generation_retains_observation_but_never_publishes_reply(self):
        entered, release = threading.Event(), threading.Event()
        original = self.provider.generate
        def blocked(*args):
            entered.set()
            if not release.wait(3): raise RuntimeError('fixture release expired')
            return original(*args)
        self.provider.generate = blocked
        trace = self.lane.begin_sensor()
        self.lane.sensor(trace,dict(caption='A crate.',t=time.time()))
        self.lane.poll()
        try:
            self.assertTrue(entered.wait(2), 'must actually enter Core inference before stop')
            self.lane.invalidate()
        finally:
            release.set()
        self.wait_for(lambda: self.lane.future is None)
        self.assertIsNone(self.lane.take())
        self.wait_for(lambda:bool(self.core.call('lookup', {'query':'wood_crate001a'})['hits']))
        self.assertIsNone(self.lane.take())

    def test_distinct_props_and_moved_prop_survive_core_restart_as_past_evidence(self):
        ids=[]
        for index,model,x in [(71,'models/props_junk/wood_crate001a.mdl',20),
                              (72,'models/props_c17/oildrum001.mdl',90),
                              (71,'models/props_junk/wood_crate001a.mdl',180)]:
            self.state['seq'] += 1
            self.state['serverTime'] = time.time()
            self.state['eye'].update(entIndex=index,model=model,
                entityPos=dict(x=x,y=10,z=5),hitPos=dict(x=x,y=10,z=5))
            self.tracker.accepted_state(self.state)
            self.lane.update(self.state)
            trace=self.lane.begin_sensor()
            self.lane.sensor(trace,dict(caption='Fixture interpretation only.',t=time.time()))
            self.wait_for(lambda:self.lane.ready is not None)
            row=self.lane.take();self.lane.published(row,True)
            self.wait_for(lambda:self.lane.future is None and not self.lane.imports)
            hits=self.core.call('lookup', {'query':model.split('/')[-1].removesuffix('.mdl')})['hits']
            ids.append({h['memory_id'] for h in hits})
        self.assertTrue(ids[0].isdisjoint(ids[1]))
        self.assertEqual(len(ids[2]),2)
        self.core.call('stop');self.core.thread.join(5)
        self.core=Core(self.root/'core',provider=self.provider).start()
        self.lane.core=self.core
        crates=self.core.call('lookup', {'query':'wood_crate001a'})['hits']
        drum=self.core.call('lookup', {'query':'oildrum001'})['hits']
        self.assertEqual({h['memory_id'] for h in crates},ids[2])
        self.assertEqual({h['memory_id'] for h in drum},ids[1])
        self.assertTrue(all(h['historical_only'] and h['evidence'] for h in crates+drum))

    def test_shutdown_drains_closed_episode_without_another_main_loop_poll(self):
        trace=self.lane.begin_sensor()
        self.lane.sensor(trace,dict(caption='A crate.',t=time.time()))
        self.wait_for(lambda:self.lane.ready is not None)
        self.lane.published(self.lane.take(),True)
        logs=[];self.lane.log=logs.append
        mux=ProducerMux(ProducerGroup(ThreadPoolExecutor(max_workers=1)),self.lane)
        self.assertGreater(mux.pending,0)
        mux.request_stop();mux.join_until(time.monotonic()+3)
        self.assertEqual(mux.pending,0)
        self.assertTrue(any(x.startswith('SUPERVISED_IMPORT_PENDING ') for x in logs))
        self.assertFalse(any(x.startswith('SUPERVISED_IMPORT_DEFERRED ') for x in logs))
        self.core.call('stop');self.core.thread.join(5)
        self.core=Core(self.root/'core',provider=self.provider).start();self.lane.core=self.core
        self.assertEqual(len(self.core.call('lookup',{'query':'wood_crate001a'})['hits']),1)

    def test_completed_unpolled_import_is_idempotent_during_shutdown(self):
        trace=self.lane.begin_sensor()
        self.lane.sensor(trace,dict(caption='A crate.',t=time.time()))
        self.wait_for(lambda:self.lane.ready is not None)
        self.lane.published(self.lane.take(),True)
        self.lane.poll()
        deadline=time.monotonic()+2
        while not self.lane.future.done() and time.monotonic()<deadline:time.sleep(.01)
        self.assertTrue(self.lane.future.done())
        mux=ProducerMux(ProducerGroup(ThreadPoolExecutor(max_workers=1)),self.lane)
        mux.request_stop();mux.join_until(time.monotonic()+3)
        self.assertEqual(mux.pending,0)
        self.assertEqual(len(self.core.call('lookup',{'query':'wood_crate001a'})['hits']),1)

    def test_blocked_import_respects_shared_shutdown_deadline(self):
        trace=self.lane.begin_sensor()
        self.lane.sensor(trace,dict(caption='A crate.',t=time.time()))
        self.wait_for(lambda:self.lane.ready is not None)
        self.lane.published(self.lane.take(),True)
        release=threading.Event();original=self.lane._import
        def blocked(trace):
            if not release.wait(3):raise RuntimeError('fixture release expired')
            return original(trace)
        self.lane._import=blocked
        logs=[];self.lane.log=logs.append
        mux=ProducerMux(ProducerGroup(ThreadPoolExecutor(max_workers=1)),self.lane)
        mux.request_stop();start=time.monotonic()
        try:
            with self.assertRaises(ProducerDeadline):mux.join_until(start+.03)
            self.assertLess(time.monotonic()-start,.5)
            self.assertGreater(mux.pending,0)
            self.assertTrue(any(x.startswith('SUPERVISED_IMPORT_DEFERRED ') and
                json.loads(x.split(' ',1)[1])['reason']=='shutdown_drain_incomplete' for x in logs))
        finally:
            release.set()
            if self.lane.drain_jobs:self.lane.drain_jobs.join_until(time.monotonic()+3)
        self.assertEqual(mux.pending,0)

    def test_failed_import_is_explicitly_deferred_not_cleanly_drained(self):
        trace=self.lane.begin_sensor()
        self.lane.sensor(trace,dict(caption='A crate.',t=time.time()))
        self.wait_for(lambda:self.lane.ready is not None)
        self.lane.published(self.lane.take(),True)
        logs=[];self.lane.log=logs.append
        def fail(trace): raise RuntimeError('fixture import failure')
        self.lane._import=fail
        mux=ProducerMux(ProducerGroup(ThreadPoolExecutor(max_workers=1)),self.lane)
        mux.request_stop()
        with self.assertRaises(ProducerDeadline):mux.join_until(time.monotonic()+2)
        self.assertGreater(mux.pending,0)
        receipt=json.loads(next(x.split(' ',1)[1] for x in logs
                               if x.startswith('SUPERVISED_IMPORT_DEFERRED ')))
        self.assertEqual(receipt['correlation_id'],trace.correlation_id)
        self.assertEqual(receipt['database_id'],self.lane.database_id)

    def test_indexed_evidence_survives_more_than_512_later_events(self):
        trace=self.lane.begin_sensor()
        self.lane.sensor(trace,dict(caption='A crate.',t=time.time()))
        for _ in range(600):
            self.assertIsNotNone(self.tracker._emit('sensor.error',
                                 {'accepted':False,'reason':'fixture_noise'},trace=trace,priority='normal'))
        deadline=time.monotonic()+3
        while any(self.recorder.health()[k] for k in ('inflight','normal_depth','critical_depth')) and time.monotonic()<deadline:time.sleep(.01)
        self.state['serverTime']=time.time();self.lane.update(self.state)
        self.wait_for(lambda:self.lane.ready is not None)
        self.assertIn('A crate.',self.provider.prompt)

    def test_chat_has_trace_and_published_only_recent_context(self):
        self.assertTrue(self.lane.hear('Call this plan the lighthouse.'))
        self.wait_for(lambda:self.lane.ready is not None)
        row=self.lane.take();trace=row['request']['trace']
        self.lane.published(row,True)
        self.assertTrue(self.tracker.episodes[trace.correlation_id]['closed'])
        self.assertTrue(self.lane.hear('What did I call the plan?'))
        self.wait_for(lambda:self.lane.ready is not None)
        self.assertIn('lighthouse',self.provider.prompt)
        self.lane.published(self.lane.take(),False)
        self.assertEqual(len(self.lane.dialogue),1)
        with closing(open_reader(self.recorder.path)) as db:
            raw=''.join(row[0] for row in db.execute('SELECT envelope_json FROM events'))
        self.assertNotIn('lighthouse',raw)
        self.lane.invalidate();self.assertEqual(list(self.lane.dialogue),[])

    def test_caption_substitution_fails_against_committed_digest(self):
        trace = self.lane.begin_sensor()
        event = self.tracker.sensor_result(trace, accepted=True, reason='sensor_ready',
            result=dict(caption='A crate.',t=time.time()),defer_close=True)
        request = dict(kind='sensor',trace=trace)
        deadline=time.monotonic()+2
        while self.recorder.health()['inflight'] and time.monotonic()<deadline:
            time.sleep(.01)
        with self.assertRaises(RecordingRefused):
            react(self.core,self.recorder.path,self.lane._binding(request),
                event_id=event.as_dict()['event_id'],map_name='gm_construct',
                probe=lambda:self.state,sensor_caption='A dragon.')


if __name__=='__main__': unittest.main()
