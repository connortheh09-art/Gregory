"""Actual bridge publication + real task controller + receipt-only speech gate."""
from pathlib import Path
from collections import deque
from concurrent.futures import Future
from types import SimpleNamespace
import ast,json,sys,threading,time,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
import test_vc_game_tasks as base
from greg_supervised import SupervisedLane,reply_surface
from gregory_core.supervised_game import RecordingRefused
import gmod_bridge as bridge

class HarnessTests(unittest.TestCase):
 def setUp(self):
  base.TaskTests.setUp(self)
  self.state['steamid']='fixture-bot'
  self.stamp=('voice',1);self.logs=[];self.closed=[];self.spoken=[];self.asked=[]
  self.lane=SupervisedLane.__new__(SupervisedLane)
  self.lane.harness=True;self.lane.turn_ledger={};self.lane.game_tasks=self.link
  self.lane.generation=0;self.lane.state=self.state;self.lane.lock=threading.Lock()
  self.lane.queue=deque(maxlen=4);self.lane.dialogue=deque(maxlen=8)
  self.lane.log=self.logs.append;self.lane.game_authority=None
  self.lane.delivery=SimpleNamespace(stamp=lambda:self.stamp)
  def think(op,payload):
   self.assertEqual(op,'think');self.asked.append(payload)
   return dict(say='I have not changed what I am doing.',intent=None,used_memory_ids=[])
  self.lane.core=SimpleNamespace(call=think)
  self.lane.tracker=SimpleNamespace(close=lambda *a:self.closed.append(a))
  self.row=dict(request=dict(kind='chat',generation=0,text='Could you follow me?',
      voice_metadata=dict(request_id='owner-turn'),delivery_stamp=self.stamp,trace=None),
      say='I am moving now.',game_intent=None,game_task_view=self.link.snapshot())
  source=(ROOT/'deployments/oldpc/gmod_bridge.py').read_text();tree=ast.parse(source)
  self.block=compile(ast.fix_missing_locations(ast.Module(body=[next(n for n in ast.walk(tree)
     if isinstance(n,ast.If) and ast.unparse(n.test).startswith('supervised_say is not None and now >= command_due'))],type_ignores=[])),'actual-publication','exec')
 def publish(self,row=None):
  env=dict(bridge.__dict__);env.update(supervised_say=row or self.row,now=2,command_due=0,
   supervised=self.lane,game_tasks=self.link,game_authority=None,agenda=None,voice_activity=None,
   voice_session=SimpleNamespace(stamp=lambda:self.stamp,offer=lambda row:self.spoken.append(row) or True),
   latest=self.state,PLAYERCORE=self.runtime,tracker=SimpleNamespace(pending_speech_trace=None,decision_result=lambda *a,**k:None),
   ready=None,run_voice_log=None,game_screen=None,reply_surface=reply_surface,log=self.logs.append)
  exec(self.block,env);return env
 def finalize(self):
  request=self.lane.queue.popleft();answer=self.lane._work(request)
  return dict(answer,request=request)
 def test_false_promise_with_no_intent_is_never_published(self):
  self.publish();self.assertEqual(self.spoken,[]);self.assertEqual(len(self.lane.queue),1)
  receipt=self.lane.queue[0]['execution_receipt'];self.assertEqual(receipt['status'],'no_change')
  final=self.finalize();self.publish(final)
  self.assertEqual([x['say'] for x in self.spoken],['I have not changed what I am doing.'])
  self.assertIn('EXECUTION_RECEIPT',self.asked[0]['prompt'])
 def test_accepted_task_applies_before_finalization_and_only_once(self):
  self.row['game_intent']=dict(action='game_task',kind='visit',target=self.target)
  self.publish();version=self.link.revision;task_id=self.link.active['id']
  self.assertEqual(self.spoken,[]);self.assertEqual(self.link.tick(self.runtime,self.state,2)['action'],'navigate')
  self.assertEqual(self.lane.queue[0]['execution_receipt']['status'],'accepted')
  final=self.finalize();self.publish(final)
  self.assertEqual(self.link.revision,version);self.assertEqual(self.link.active['id'],task_id)
  self.publish(final);self.assertEqual(len(self.spoken),1)
 def test_duplicate_initial_turn_cannot_replace_task(self):
  self.row['game_intent']=dict(action='game_task',kind='hold',stay_seconds=20)
  self.publish();task=self.link.active['id'];self.publish()
  self.assertEqual(self.link.active['id'],task);self.assertEqual(len(self.lane.queue),1)
 def test_refusal_reaches_core_not_the_original_promise(self):
  self.row['game_intent']=dict(action='game_task',kind='visit',target='fabricated')
  self.publish();self.assertFalse(self.link.engaged);self.assertEqual(self.spoken,[])
  self.assertEqual(self.lane.queue[0]['execution_receipt']['status'],'refused')
  final=self.finalize();self.publish(final)
  self.assertIn("that spot wasn't one of my current options",self.asked[0]['prompt'])
  self.assertNotIn('unoffered destination',self.asked[0]['prompt'])
 def test_finalization_cannot_sneak_in_a_second_tool(self):
  self.publish();self.lane.core.call=lambda *a:dict(say='Moving.',intent=dict(action='game_task',kind='hold'),used_memory_ids=[])
  with self.assertRaisesRegex(RecordingRefused,'speech_only'):self.finalize()
  self.assertEqual(self.spoken,[]);self.assertFalse(self.link.engaged)
 def test_finalization_keeps_source_bounded_memory_evidence(self):
  self.row['memory_evidence']=[dict(id='source-1',summary='Owner likes jeeps.')]
  self.publish()
  def think(op,payload):
   self.assertEqual(payload['memory_evidence_ids'],['source-1'])
   self.assertIn('HISTORICAL_EVIDENCE',payload['prompt'])
   return dict(say='You said you liked jeeps.',intent=None,used_memory_ids=['source-1'])
  self.lane.core.call=think;final=self.finalize();self.publish(final)
  self.assertEqual(len(self.spoken),1)
 def test_finalization_cannot_invent_memory_citations(self):
  self.publish();self.lane.core.call=lambda *a:dict(say='I remember.',intent=None,used_memory_ids=['invented'])
  with self.assertRaisesRegex(RecordingRefused,'ungrounded_memory'):self.finalize()
  self.assertEqual(self.spoken,[])
 def test_model_failure_does_not_release_draft(self):
  self.publish()
  def fail(*a):raise TimeoutError('offline')
  self.lane.core.call=fail
  with self.assertRaises(TimeoutError):self.finalize()
  self.assertEqual(self.spoken,[])
 def test_queue_budget_never_evicts_a_turn_or_releases_draft(self):
  self.lane.queue.extend([dict(n=i) for i in range(4)]);self.publish()
  self.assertEqual([x['n'] for x in self.lane.queue],list(range(4)));self.assertEqual(self.spoken,[])
 def test_voice_barge_in_cancels_final_speech_not_task(self):
  self.row['game_intent']=dict(action='game_task',kind='visit',target=self.target)
  self.publish();self.stamp=('voice',2)
  with self.assertRaisesRegex(RecordingRefused,'stale'):self.finalize()
  self.assertTrue(self.link.engaged);self.assertEqual(self.link.tick(self.runtime,self.state,3)['action'],'navigate')
 def test_task_change_after_model_return_cancels_old_speech(self):
  self.publish();final=self.finalize();self.link.invalidate();self.link.update(self.runtime,self.state,3)
  self.publish(final);self.assertEqual(self.spoken,[])
 def test_world_change_cancels_receipt(self):
  self.publish();self.state['controlEpoch']=2;self.link.update(self.runtime,self.state,3)
  with self.assertRaisesRegex(RecordingRefused,'stale'):self.finalize()
 def test_stale_voice_never_applies_first_proposal(self):
  self.stamp=('voice',2);self.row['game_intent']=dict(action='game_task',kind='hold',stay_seconds=20)
  self.publish();self.assertFalse(self.link.engaged);self.assertEqual(self.spoken,[])
 def test_ledger_budget_rejects_new_turn_without_eviction(self):
  self.lane.turn_ledger={str(i):{} for i in range(128)};self.publish()
  self.assertEqual(len(self.lane.turn_ledger),128);self.assertEqual(self.spoken,[])
 def test_private_dm_claim_bypasses_game_receipt_pipeline(self):
  self.row['request']['inbox_voice_claim']='private'
  self.assertFalse(self.lane._harness_eligible(self.row))
 def test_plain_game_chat_does_not_gain_voice_harness(self):
  self.row['request'].pop('voice_metadata')
  self.assertFalse(self.lane._harness_eligible(self.row))
 def test_final_worker_poll_carries_receipt_not_action(self):
  self.publish();request=self.lane.queue.popleft();answer=self.lane._work(request)
  future=Future();future.set_result(answer)
  self.lane.future=future;self.lane.request=request
  self.lane.poll();row=self.lane.take()
  self.assertTrue(row['harness_finalized']);self.assertIsNone(row['game_intent'])
  self.assertEqual(row['harness_receipt']['status'],'no_change')
 def test_actual_core_receives_receipt_and_cannot_dispatch_game_actions(self):
  from gregory_core.runtime import Core,FixtureProvider
  import tempfile
  observed=[]
  class Provider(FixtureProvider):
   def generate(provider,profile,prompt):
    observed.append(prompt)
    return dict(say='Nothing changed yet.',intent=None,used_memory_ids=[])
  with tempfile.TemporaryDirectory() as directory:
   core=Core(Path(directory),provider=Provider()).start()
   try:
    self.lane.core=core;self.publish();final=self.finalize();self.publish(final)
   finally:core.call('stop');core.thread.join(3)
  self.assertEqual(len(observed),1);self.assertIn('"status":"no_change"',observed[0])
  self.assertFalse(self.link.engaged);self.assertEqual(self.spoken[0]['say'],'Nothing changed yet.')

if __name__=='__main__':unittest.main()
