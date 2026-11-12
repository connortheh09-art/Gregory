"""Fake audio/STT/TTS plus actual host, Core and bridge caller boundaries."""
import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import time
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
import test_recorder_integration  # existing offline Requests stub
from greg_voice_session import VoiceSession,VoiceServer,VoiceRefused,VoiceTail
from greg_voice_client import CoreVoiceAdapter,VoiceHTTP
from greg_voice_protocol import stop_text
from test_supervised_bridge import exercise_chat

CONFIG=dict(owner_id='1001',guild_id='2001',channel_id='3001',game_name='Connor')
STEAM='STEAM_0:1:1000'


class StopSpellingTests(unittest.TestCase):
    def test_client_and_host_share_one_parser_for_whisper_punctuation(self):
        import greg_voice_client,greg_voice_session
        self.assertIs(greg_voice_client.stop_text,greg_voice_session.stop_text)
        for text in ('stop','Stop.','Stop!','Gregory, stop!',' Wait.','Gregory: STOP MOVING!!!','HALT!','Stop now.','Do not move!'):
            with self.subTest(text=text):self.assertTrue(stop_text(text))
        for text in ('unstoppable',"don't stop",'stopped','Gregory stop the music',None):
            with self.subTest(text=text):self.assertFalse(stop_text(text))


def connected(host):
    result=host.call('connect',{k:CONFIG[k] for k in ('guild_id','channel_id')})
    return {k:result[k] for k in ('connection','generation')}


def turn(host,scope,text,**extra):
    scope={k:scope[k] for k in ('connection','generation')}
    return host.call('turn',dict(scope,request_id=str(uuid.uuid4()),author_id=CONFIG['owner_id'],
        is_bot=False,text=text,captured_at=time.time(),**extra))


class HostTests(unittest.TestCase):
    def setUp(self):
        self.logs=[];self.host=VoiceSession(CONFIG,STEAM,log=self.logs.append);self.scope=connected(self.host)

    def test_owner_id_not_nickname_and_bot_echo_are_refused(self):
        for author,bot in [('9999',False),(CONFIG['owner_id'],True)]:
            data=dict(self.scope,request_id=str(uuid.uuid4()),author_id=author,is_bot=bot,
                      text='stop',captured_at=time.time())
            with self.assertRaises(VoiceRefused):self.host.call('turn',data)
        self.assertEqual(self.host.drain(),[])

    def test_queue_drops_oldest_chat_but_recognized_stop_bypasses_queue(self):
        for text in ('first','second','third'):turn(self.host,self.scope,text)
        self.assertEqual([r['msg'] for r in self.host.drain()],['second','third'])
        for text in ('fourth','fifth'):turn(self.host,self.scope,text)
        self.scope=turn(self.host,self.scope,'stop')
        rows=VoiceTail(SimpleNamespace(read_new=lambda:[]),self.host).read_new()
        rec=json.loads(rows[0]);self.assertEqual(rec['steamid'],STEAM)
        self.assertEqual([json.loads(r)['msg'] for r in rows],['stop'])
        bridge=ROOT/'deployments/oldpc/gmod_bridge.py'
        _,runtime,_,writes=exercise_chat(bridge.read_text(),rec['msg'],supervised=True)
        self.assertEqual(writes,[{'action':'wait'}]);self.assertFalse(runtime.goal_active)

    def test_all_recognized_stop_forms_reach_the_real_controller_stop(self):
        bridge=ROOT/'deployments/oldpc/gmod_bridge.py'
        for text in ('Stop.','Gregory, stop!','Wait.','Halt!','Freeze.','Do not move!'):
            with self.subTest(text=text):
                self.scope=turn(self.host,self.scope,text)
                rec=self.host.drain()[0]
                self.assertEqual(rec['msg'],'stop')
                _,runtime,_,writes=exercise_chat(bridge.read_text(),rec['msg'],supervised=True)
                self.assertEqual(writes,[{'action':'wait'}]);self.assertFalse(runtime.goal_active)

    def test_generation_lease_and_rejoin_drop_late_replies(self):
        row=dict(request=dict(delivery_stamp=self.host.stamp()),say='old reply')
        self.host.invalidate();self.assertFalse(self.host.offer(row))
        self.scope=connected(self.host)
        row['request']['delivery_stamp']=self.host.stamp()
        self.host.call('disconnect',self.scope);self.assertFalse(self.host.offer(row))
        self.scope=connected(self.host);self.host.seen_at-=11
        self.assertIsNone(self.host.stamp())

    def test_recognized_owner_stop_survives_generation_race_but_not_connection_change(self):
        old=dict(self.scope);self.host.invalidate()
        self.scope=turn(self.host,old,'stop')
        self.assertEqual(self.host.drain()[0]['msg'],'stop')
        self.scope=connected(self.host)
        with self.assertRaises(VoiceRefused):turn(self.host,old,'stop')

    def test_playback_error_is_not_completion_and_metadata_has_no_transcript(self):
        turn(self.host,self.scope,'A private spoken sentence.')
        row=dict(request=dict(delivery_stamp=self.host.stamp()),say='answer')
        self.assertTrue(self.host.offer(row))
        reply=self.host.call('poll',self.scope)['replies'][0]
        for state in ('started','failed'):
            self.host.call('playback',dict(self.scope,reply_id=reply['reply_id'],state=state))
        with self.assertRaises(VoiceRefused):
            self.host.call('playback',dict(self.scope,reply_id=reply['reply_id'],state='completed'))
        self.assertNotIn('private spoken',''.join(self.logs))
        self.assertIn('"state": "failed"',''.join(self.logs))

    def test_scoped_loopback_transport_cannot_call_core_owner_operations(self):
        server=VoiceServer(self.host).start();self.addCleanup(server.close)
        client=VoiceHTTP(server.receipt())
        scope=client('connect',{k:CONFIG[k] for k in ('guild_id','channel_id')})
        self.assertTrue(scope['connection'])
        for operation in ('api/think','api/import','api/stop','profile'):
            with self.assertRaises(Exception):client(operation,scope)
        server.close_intake()
        with self.assertRaises(Exception):client('connect',{k:CONFIG[k] for k in ('guild_id','channel_id')})


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.logs=[];self.host=VoiceSession(CONFIG,STEAM,log=self.logs.append)
        self.channel={k:CONFIG[k] for k in ('guild_id','channel_id')}
        self.plays=[];self.after=None;self.tts_gate=None
        def synth(text):
            if self.tts_gate and not self.tts_gate.wait(3):raise RuntimeError('fixture TTS expired')
            return text.encode()
        def play(pcm,after):self.plays.append(pcm);self.after=after
        def stop():
            if self.after:
                after,self.after=self.after,None;after(None)
        self.adapter=CoreVoiceAdapter(self.host.call,owner_id=CONFIG['owner_id'],
            channel=lambda:self.channel,transcribe=lambda pcm:pcm.decode(),synthesize=synth,
            play=play,stop=stop,log=self.logs.append)
        self.user=SimpleNamespace(id=int(CONFIG['owner_id']),bot=False,display_name='any nickname')
        await self.adapter.start()
        await self.wait(lambda:self.adapter.scope is not None)

    async def asyncTearDown(self):
        if self.tts_gate:self.tts_gate.set()
        await self.adapter.close()

    async def wait(self,predicate):
        end=time.monotonic()+3
        while time.monotonic()<end:
            if predicate():return
            await asyncio.sleep(.01)
        self.fail('bounded async fixture timeout')

    def offer(self,text):
        self.assertTrue(self.host.offer(dict(request=dict(delivery_stamp=self.host.stamp()),say=text)))

    async def test_stop_during_playback_is_intaken_and_never_logged_completed(self):
        self.offer('Still talking about the crate.')
        await self.wait(lambda:bool(self.plays))
        await self.adapter.audio(b'stop',self.user,1,time.time())
        await self.wait(lambda:bool(self.host.turns))
        self.assertEqual(self.host.drain()[0]['msg'],'stop')
        await asyncio.sleep(.1)
        self.assertNotIn('"state": "completed"',''.join(self.logs))

    async def test_stop_during_tts_prevents_late_voice_play(self):
        self.tts_gate=threading.Event();self.offer('A slow synthesized reply.')
        await self.wait(lambda:self.adapter.cancelled is False and self.adapter.reply_queue.empty())
        await self.adapter.audio(b'stop',self.user,1,time.time())
        await self.wait(lambda:bool(self.host.turns))
        self.tts_gate.set();await asyncio.sleep(.15)
        self.assertEqual(self.plays,[])

    async def test_echo_is_filtered_before_interrupt_or_turn_submission(self):
        self.adapter.recent_speech=('The wooden crate is beside the wall.',time.time())
        stamp=self.host.stamp()
        await self.adapter.audio(b'The wooden crate is beside the wall',self.user,1,time.time())
        await self.wait(lambda:'VOICE_ECHO_DROPPED' in self.logs)
        self.assertEqual(self.host.stamp(),stamp);self.assertEqual(self.host.drain(),[])

    async def test_playback_callback_error_is_reported_failed_not_completed(self):
        self.offer('A playback failure fixture.')
        await self.wait(lambda:self.after is not None)
        self.after(RuntimeError('fixture playback error'))
        await self.wait(lambda:'"state": "failed"' in ''.join(self.logs))
        self.assertNotIn('"state": "completed"',''.join(self.logs))

    async def test_player_stop_failure_does_not_kill_intake_or_claim_completion(self):
        def unavailable():raise RuntimeError('fixture player stop unavailable')
        self.adapter.stop=unavailable
        await self.adapter.audio(b'stop',self.user,1,time.time())
        await self.wait(lambda:bool(self.host.turns))
        self.assertEqual(self.host.drain()[0]['msg'],'stop')
        self.assertTrue(any(x.startswith('VOICE_STOP_UNAVAILABLE ') for x in self.logs))
        self.assertNotIn('"state": "completed"',''.join(self.logs))

    async def test_capture_end_time_is_preserved_not_replaced_by_handler_clock(self):
        ended=time.time()-.5
        await self.adapter.audio(b'hello',self.user,1,ended)
        await self.wait(lambda:bool(self.host.turns))
        # Host-domain conversion is conservative; preserve the capture endpoint
        # age, not exact equality between independent wall-clock domains.
        self.assertLessEqual(self.host.turns[0]['captured_at'],ended+.002)
        self.assertAlmostEqual(self.host.turns[0]['captured_at'],ended,delta=.1)

    async def test_new_owner_stop_is_retained_while_stt_is_busy(self):
        entered,release=threading.Event(),threading.Event()
        def transcribe(pcm):
            if pcm==b'first':
                entered.set()
                if not release.wait(3):raise RuntimeError('fixture STT expired')
            return pcm.decode()
        self.adapter.transcribe=transcribe
        await self.adapter.audio(b'first',self.user,1,time.time())
        await self.wait(entered.is_set)
        try:
            for text in (b'older chat',b'newer chat',b'stop'):
                self.assertTrue(await self.adapter.audio(text,self.user,1,time.time()))
            self.assertLessEqual(self.adapter.audio_queue.qsize(),2)
        finally:release.set()
        await self.wait(lambda:bool(self.host.turns) and self.host.turns[-1]['text']=='stop')
        self.assertEqual([r['msg'] for r in self.host.drain()],['stop'])

    async def test_whisper_stop_punctuation_survives_stt_generation_race_and_echo(self):
        for text in ('Stop.','Gregory, stop!','Wait.'):
            with self.subTest(text=text):
                entered,release=threading.Event(),threading.Event()
                def transcribe(pcm):
                    entered.set()
                    if not release.wait(3):raise RuntimeError('fixture STT expired')
                    return pcm.decode()
                self.adapter.transcribe=transcribe
                self.adapter.recent_speech=(text,time.time())
                await self.adapter.audio(text.encode(),self.user,1,time.time())
                await self.wait(entered.is_set)
                try:
                    self.host.invalidate()
                    await self.wait(lambda:self.adapter.scope['generation']==self.host.generation)
                finally:release.set()
                await self.wait(lambda:bool(self.host.turns))
                self.assertEqual([r['msg'] for r in self.host.drain()],['stop'])
                self.assertNotIn('VOICE_ECHO_DROPPED',self.logs)

    async def test_incidental_chat_does_not_interrupt_active_playback(self):
        self.offer('I am still describing the crate.')
        await self.wait(lambda:bool(self.plays))
        scope=dict(self.adapter.scope);after=self.after
        await self.adapter.audio(b'Nice.',self.user,1,time.time())
        await self.wait(lambda:bool(self.host.turns))
        self.assertEqual(self.adapter.scope,scope)
        self.assertIs(self.after,after)
        self.assertIsNotNone(self.adapter.current)
        self.assertNotIn('"state": "cancelled"',''.join(self.logs))
        after(None)
        await self.wait(lambda:'"state": "completed"' in ''.join(self.logs))

    async def test_playback_deadline_is_typed_timeout_not_generic_failure(self):
        self.adapter.playback_timeout=.05
        self.offer('A reply with no completion callback.')
        await self.wait(lambda:'VOICE_PLAYBACK_TIMEOUT' in self.logs)
        await self.wait(lambda:'"state": "timeout"' in ''.join(self.logs))
        self.assertNotIn('"state": "failed"',''.join(self.logs))
        self.assertNotIn('"state": "completed"',''.join(self.logs))

    async def test_disconnect_during_tts_cannot_play_after_rejoin(self):
        self.tts_gate=threading.Event();self.offer('Old channel reply.')
        await asyncio.sleep(.15);self.channel=None
        await self.wait(lambda:self.adapter.scope is None)
        self.channel={k:CONFIG[k] for k in ('guild_id','channel_id')}
        await self.wait(lambda:self.adapter.scope is not None)
        self.tts_gate.set();await asyncio.sleep(.15)
        self.assertEqual(self.plays,[])


class VoiceCallerTests(unittest.IsolatedAsyncioTestCase):
    def method(self,name):
        source=(ROOT/'recovery/2026-11-12/voice-reference/gdiscord.py').read_text();tree=ast.parse(source)
        node=next(n for n in ast.walk(tree) if isinstance(n,(ast.AsyncFunctionDef,ast.FunctionDef)) and n.name==name)
        env={};exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(ROOT/'voice-caller'), 'exec'),env)
        return env[name],env

    async def test_real_voice_callback_bypasses_speaking_flags_history_and_direct_model(self):
        fn,env=self.method('on_utterance');calls=[]
        async def audio(*args):calls.append(args)
        stub=SimpleNamespace(core_voice=SimpleNamespace(audio=audio),speaking=True)
        user=SimpleNamespace(id=1001,bot=False)
        await fn(stub,b'voice',user,1,123)
        self.assertEqual(calls,[(b'voice',user,1,123)])

    async def test_real_voice_callback_has_no_direct_model_fallback(self):
        fn,_=self.method('on_utterance')
        with self.assertRaisesRegex(RuntimeError,'no direct-model fallback'):
            await fn(SimpleNamespace(core_voice=None),b'voice',None,1,123)

    async def test_real_sink_handle_bypasses_legacy_pause_in_core_mode(self):
        fn,env=self.method('handle');calls=[]
        async def heard(*args):calls.append(args)
        env['bot']=SimpleNamespace(core_voice=object(),on_utterance=heard)
        stub=SimpleNamespace(busy=True)
        await fn(stub,b'voice','user',1,123)
        self.assertEqual(calls,[(b'voice','user',1,123)]);self.assertFalse(stub.busy)

    async def test_real_sink_busy_does_not_drop_new_capture_and_stamps_at_endpoint(self):
        fn,env=self.method('write');calls=[]
        state=dict(buf=bytearray(b'x'*192000),silent=400,active=True)
        env.update(np=SimpleNamespace(frombuffer=lambda *a,**k:[]),
            time=SimpleNamespace(time=lambda:123),bot=SimpleNamespace(core_voice=object()),
            asyncio=SimpleNamespace(run_coroutine_threadsafe=lambda *a:None))
        stub=SimpleNamespace(nframes=0,peak=0,lastlog=123,thresh=.01,silence_ms=400,
            busy=True,loop=None,_state=lambda uid:state,handle=lambda *a:calls.append(a))
        user=SimpleNamespace(id=1001,bot=False)
        fn(stub,user,SimpleNamespace(pcm=b'x'))
        self.assertEqual(calls,[(b'x'*192000,user,1,123)])


class CoreHandoffTests(unittest.TestCase):
    def setUp(self):
        import test_supervised_sensor
        self.fixture=test_supervised_sensor.SensorTests()
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.host=VoiceSession(CONFIG,STEAM,recorder=self.fixture.recorder)
        self.scope=connected(self.host)
        self.fixture.lane.delivery=self.host

    def test_real_core_lane_consumes_attributed_voice_turn_and_queues_reply_not_game_command(self):
        turn(self.host,self.scope,'What do you remember about this crate?')
        rec=self.host.drain()[0];metadata=self.host.claim(rec)
        self.assertIsNone(self.host.claim(rec),'one-time trusted receive claim')
        lane=self.fixture.lane
        self.assertTrue(lane.hear_voice(rec['msg'],metadata))
        self.fixture.wait_for(lambda:lane.ready is not None)
        row=lane.take();self.assertTrue(self.host.offer(row))
        lane.published(row,True,qualification='voice queued, not audible delivery')
        reply=self.host.call('poll',self.scope)['replies'][0]
        self.assertEqual(reply['text'],row['say'])
        for state in ('started','completed'):
            self.host.call('playback',dict(self.scope,reply_id=reply['reply_id'],state=state))
        self.host.flush_receipts()
        self.assertIn('QUESTION: What do you remember',self.fixture.provider.prompt)
        from contextlib import closing
        from greg_recorder import open_reader
        deadline=time.monotonic()+2;events=[]
        while time.monotonic()<deadline:
            with closing(open_reader(self.fixture.recorder.path)) as db:
                events=[json.loads(r[0]) for r in db.execute('SELECT envelope_json FROM events')]
            if any(e['event_type']=='voice.playback' for e in events):break
            time.sleep(.01)
        admitted=next(e for e in events if e['payload'].get('reason')=='voice_admitted')
        self.assertEqual(admitted['payload']['actor_id'],CONFIG['owner_id'])
        self.assertEqual(admitted['payload']['related_to'],'2001:3001')
        self.assertEqual(admitted['payload']['id'],metadata['request_id'])
        playback=[e for e in events if e['event_type']=='voice.playback']
        self.assertEqual([e['payload']['status'] for e in playback],['started','completed'])
        self.assertTrue(all(e['correlation_id']==admitted['correlation_id'] for e in playback))
        self.assertTrue(all(e['payload']['reason']=='adapter_report_not_listener_ack' for e in playback))
        self.assertFalse(any(e['event_type']=='action.dispatch' for e in events))

    def test_stop_during_actual_core_inference_makes_late_voice_reply_undeliverable(self):
        entered,release=threading.Event(),threading.Event()
        provider=self.fixture.provider;original=provider.generate
        def blocked(*args):
            entered.set()
            if not release.wait(3):raise RuntimeError('fixture Core release expired')
            return original(*args)
        provider.generate=blocked
        turn(self.host,self.scope,'A slow question')
        rec=self.host.drain()[0];lane=self.fixture.lane
        self.assertTrue(lane.hear_voice(rec['msg'],self.host.claim(rec)));lane.poll()
        try:
            self.assertTrue(entered.wait(2))
            self.scope=turn(self.host,self.scope,'stop')
            self.assertEqual(self.host.drain()[0]['msg'],'stop')
        finally:release.set()
        self.fixture.wait_for(lambda:lane.ready is not None)
        row=lane.take();self.assertFalse(self.host.offer(row))
        lane.published(row,False)
        self.assertEqual(self.host.call('poll',self.scope)['replies'],[])


if __name__=='__main__':unittest.main()


class FixedVoicePortTests(unittest.TestCase):
    def test_same_fixed_port_preserves_http_capability_and_loopback_contract(self):
        import socket
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port=probe.getsockname()[1]
        host=VoiceSession(CONFIG,STEAM)
        server=VoiceServer(host,port=port).start()
        try:
            self.assertEqual(server.port,port)
            self.assertEqual(server.server.server_address,('127.0.0.1',port))
            client=VoiceHTTP(server.receipt())
            scope=client('connect',{k:CONFIG[k] for k in ('guild_id','channel_id')})
            self.assertIn('connection',scope)
            with self.assertRaises(OSError):VoiceServer(host,port=port)
        finally:server.close()

    def test_invalid_port_is_refused_before_any_listener_is_created(self):
        for port in (-1,65536,True,'18667',1.5):
            with self.subTest(port=port),self.assertRaises(ValueError):
                VoiceServer(VoiceSession(CONFIG,STEAM),port=port)
