import asyncio,time,unittest
from pathlib import Path
from types import SimpleNamespace
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
from greg_voice_client import CoreVoiceAdapter,TurnAssembly
from greg_supervised import reply_surface
import test_voice_handoff as base

class AssemblyTests(unittest.TestCase):
 def setUp(self):self.now=100.;self.buf=TurnAssembly(quiet=.3,clock=lambda:self.now)
 def add(self,text,scope=None):self.buf.add(text,scope or dict(connection='c',generation=1),self.now,self.now)
 def test_fragments_are_one_turn_after_real_quiet(self):
  self.add('We are playing');self.now+=.2;self.add('hide and seek.')
  self.assertIsNone(self.buf.take(self.now))
  self.now+=.31;row=self.buf.take(self.now);self.assertEqual(row['text'],'We are playing hide and seek.');self.assertEqual(row['fragment_count'],2)
 def test_continued_speech_keeps_floor_even_without_a_new_transcript(self):
  self.add('Let me explain');self.now+=.31
  self.assertIsNone(self.buf.take(self.now,activity=self.now-.1))
  self.now+=.31;self.assertEqual(self.buf.take(self.now,activity=self.now-.4)['text'],'Let me explain')
 def test_connection_or_generation_change_cannot_merge_old_text(self):
  self.add('old private turn');self.add('new turn',dict(connection='new',generation=2));self.now+=.31
  self.assertEqual(self.buf.take(self.now)['text'],'new turn')
 def test_completed_turn_keeps_actual_last_capture_stamp(self):
  self.add('first');self.now+=.1;self.add('last');self.now+=.4
  self.assertEqual(self.buf.take(self.now)['captured_at'],100.1)
 def test_text_budget_flushes_previous_turn_without_losing_new_fragment(self):
  self.add('x'*900)
  flushed=self.buf.add('y'*200,dict(connection='c',generation=1),self.now,self.now)
  self.assertEqual([x['text'] for x in flushed],['x'*900])
  self.assertEqual(self.buf.pending['text'],'y'*200)
  self.assertEqual(flushed[0]['boundary'],'text_budget')
 def test_single_oversized_fragment_is_split_without_loss(self):
  text='x'*2101;flushed=self.buf.add(text,dict(connection='c',generation=1),self.now,self.now)
  self.now+=.31;flushed.append(self.buf.take(self.now))
  self.assertEqual(''.join(x['text'] for x in flushed),text)
  self.assertTrue(all(len(x['text'])<=1000 for x in flushed))
 def test_time_cap_flushes_even_when_owner_is_still_speaking(self):
  self.add('A continuing explanation');self.now+=10
  row=self.buf.take(self.now,activity=self.now)
  self.assertEqual(row['text'],'A continuing explanation');self.assertEqual(row['boundary'],'time_budget')
  self.assertEqual(row['quiet_seconds'],0)

class AdapterTurnTests(unittest.IsolatedAsyncioTestCase):
 asyncTearDown=base.AdapterTests.asyncTearDown
 wait=base.AdapterTests.wait
 offer=base.AdapterTests.offer
 async def asyncSetUp(self):
  await base.AdapterTests.asyncSetUp(self);self.adapter.turn_taking=True;self.adapter.turn_buffer.quiet=.3
  self.adapter.tasks.append(asyncio.create_task(self.adapter._assemble()))
 async def test_two_short_fragments_submit_one_core_turn(self):
  await self.adapter.audio(b'We are playing',self.user,1,time.time())
  await asyncio.sleep(.15);await self.adapter.audio(b'hide and seek',self.user,1,time.time())
  await self.wait(lambda:bool(self.host.turns))
  self.assertEqual([x['text'] for x in self.host.turns],['We are playing hide and seek'])
 async def test_meaningful_barge_in_yields_audio_but_not_a_game_stop(self):
  self.offer('A long reply to interrupt.');await self.wait(lambda:bool(self.plays))
  await self.adapter.audio(b'Wait, I need to explain the rules.',self.user,1,time.time())
  await self.wait(lambda:self.adapter.current is None)
  self.assertNotIn('"state": "completed"',''.join(self.logs))
  await self.wait(lambda:bool(self.host.turns))
  self.assertFalse(any(x['msg']=='stop' for x in self.host.drain()))
 async def test_backchannel_does_not_interrupt_active_audio(self):
  self.offer('A reply that can continue.');await self.wait(lambda:bool(self.plays))
  after=self.after;await self.adapter.audio(b'yeah',self.user,1,time.time());await asyncio.sleep(.1)
  self.assertIs(self.after,after)
 async def test_stop_bypasses_assembly_quiet_window(self):
  await self.adapter.audio(b'I am still explaining',self.user,1,time.time());await asyncio.sleep(.05)
  await self.adapter.audio(b'Stop!',self.user,1,time.time())
  await self.wait(lambda:bool(self.host.turns))
  self.assertEqual([x['text'] for x in self.host.turns],['Stop!'])
 async def test_unauthorized_speech_activity_cannot_hold_the_floor(self):
  before=self.adapter.last_activity
  self.assertFalse(self.adapter.speech_activity(SimpleNamespace(id=999,bot=False)))
  self.assertEqual(self.adapter.last_activity,before)

class CaptureChunkTests(unittest.TestCase):
 def test_actual_sink_chunks_long_speech_and_keeps_activity_without_disk_or_model_calls(self):
  # Fixed loud PCM/RMS fixture; execute real sink chunking without numpy dependency.
  class Loud:
   def __len__(self):return 2
   def astype(self,*args):return self
   def __truediv__(self,value):return self
   def __pow__(self,value):return self
  np=SimpleNamespace(frombuffer=lambda *a,**k:Loud(),mean=lambda a:1,sqrt=lambda a:1)
  fn,env=base.VoiceCallerTests.method(self,'write')
  state=dict(buf=bytearray(b'x'*1535996),silent=0,active=True)
  activities=[];chunks=[];scheduled=[]
  adapter=SimpleNamespace(turn_taking=True,speech_activity=lambda user:activities.append(user.id))
  env.update(np=np,time=SimpleNamespace(time=lambda:123),bot=SimpleNamespace(core_voice=adapter),
   asyncio=SimpleNamespace(run_coroutine_threadsafe=lambda value,loop:scheduled.append(value)))
  stub=SimpleNamespace(nframes=0,peak=0,lastlog=123,thresh=.001,silence_ms=400,busy=False,
   loop=None,_state=lambda uid:state,handle=lambda *args:chunks.append(args))
  user=SimpleNamespace(id=1001,bot=False)
  fn(stub,user,SimpleNamespace(pcm=b'\xff\x7f'*2))
  self.assertEqual(activities,[1001]);self.assertEqual(len(chunks),1)
  self.assertEqual(chunks[0][2],8);self.assertEqual(chunks[0][3],123)
  self.assertEqual(state['buf'],bytearray());self.assertTrue(state['active'])

class ListenRouting(unittest.TestCase):
 def test_listen_choice_is_not_a_tts_reply(self):
  self.assertEqual(reply_surface(dict(voice_wait=True,request=dict(voice_metadata={})),True),'internal')

class CoreListenTests(unittest.TestCase):
 def rig(self):
  import test_supervised_sensor as sensor
  import test_vc_game_tasks as tasks
  class Case(unittest.TestCase):
   setUp=sensor.SensorTests.setUp
   cleanup=sensor.SensorTests.cleanup
   wait_for=sensor.SensorTests.wait_for
  host=Case();host.setUp();tasks.VoiceCoreTests.enable(host)
  host.lane.turn_taking=True
  def generate(profile,prompt):
   host.provider.prompt=prompt
   return dict(say='[listen]',intent=dict(action='voice_turn',kind='listen'),used_memory_ids=[])
  host.provider.generate=generate
  return host
 def test_actual_core_listen_never_speaks_or_changes_game_task_and_keeps_input(self):
  host=self.rig()
  try:
   self.assertTrue(host.lane.hear_voice('First let me explain the rules',host.meta))
   host.wait_for(lambda:host.lane.ready is not None)
   row=host.lane.take()
   self.assertEqual(row['say'],'');self.assertIsNone(row['game_intent'])
   self.assertTrue(row['voice_wait']);self.assertEqual(reply_surface(row,True),'internal')
   self.assertFalse(host.tasks.engaged)
   host.lane.published(row,False,listened=True)
   self.assertEqual(host.lane.recent_dialogue()[0]['user'],'First let me explain the rules')
   self.assertEqual(host.lane.recent_dialogue()[0]['reply'],'')
  finally:host.doCleanups()
 def test_stale_unpublished_listen_does_not_enter_dialogue(self):
  host=self.rig()
  try:
   host.lane.hear_voice('unfinished',host.meta);host.wait_for(lambda:host.lane.ready is not None)
   row=host.lane.take();host.lane.published(row,False)
   self.assertEqual(host.lane.recent_dialogue(),[])
  finally:host.doCleanups()
 def test_listen_action_is_not_available_to_plain_game_chat(self):
  host=self.rig()
  try:
   host.lane.hear('Hello from game');host.wait_for(lambda:host.lane.future is None and not host.lane.queue)
   self.assertIsNone(host.lane.ready);self.assertEqual(host.lane.recent_dialogue(),[])
  finally:host.doCleanups()

class QuietProfileTests(unittest.TestCase):
 def rig(self,quiet):
  from greg_supervised import CoreGameAuthority
  authority=CoreGameAuthority(None);state=dict(map='m',bridgeSession='s',controlEpoch=1)
  authority.observe(state,{});authority.quiet_test_profile=quiet
  def think(args,*,background=False):
   self.assertTrue(background)
   self.prompt=args['prompt']
   return dict(say='Try a crate.',used_memory_ids=[],intent=dict(action='game_activity',choice=dict(activity='spawn',id='prop:crate')))
  authority.think=think
  return authority,state,dict(spawn_choices=[dict(id='prop:crate')],navigation_available=True)
 def test_quiet_idle_decider_cannot_select_even_a_real_catalog_spawn(self):
  authority,state,payload=self.rig(True)
  with self.assertRaisesRegex(ValueError,'decision schema branch mismatch'):authority.decide_activity('',payload,state)
  self.assertIn('QUIET TEST',self.prompt)
 def test_default_idle_decider_still_allows_offered_spawn(self):
  authority,state,payload=self.rig(False)
  self.assertEqual(authority.decide_activity('',payload,state)['id'],'prop:crate')
 def test_quiet_profile_does_not_remove_explicit_voice_spawn_tool(self):
  authority,state,payload=self.rig(True)
  proposal=dict(action='game_activity',choice=dict(activity='spawn',id='prop:crate'))
  offered=dict(binding=['m','s',1],spawn_choices=payload['spawn_choices'])
  self.assertEqual(authority.validate_activity(proposal,offered,state)['choice']['id'],'prop:crate')

if __name__=='__main__':unittest.main()
