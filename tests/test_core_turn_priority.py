"""Contention regressions from the 2026-11-10 live run (no GPU/game required)."""
import json,threading,time,unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"deployments/oldpc")]
from collections import deque
from types import SimpleNamespace
from greg_supervised import CoreGameAuthority,CoreTurnDeferred,SupervisedLane
from greg_agenda import Agenda

class PriorityTests(unittest.TestCase):
 def test_background_never_queues_behind_active_model(self):
  entered=threading.Event();release=threading.Event();calls=[]
  class Core:
   def call(self,op,payload,**kw):
    calls.append(payload['prompt']);entered.set();release.wait(2);return {}
  a=CoreGameAuthority(Core());worker=threading.Thread(target=lambda:a.think(dict(prompt='voice')))
  worker.start();self.assertTrue(entered.wait(1))
  try:
   with self.assertRaises(CoreTurnDeferred):a.think(dict(prompt='idle'),background=True)
   self.assertEqual(calls,['voice'])
  finally:release.set();worker.join(2)
  self.assertFalse(worker.is_alive())
 def test_waiting_owner_gets_next_slot_while_new_idle_work_is_discarded(self):
  entered=threading.Event();release=threading.Event();calls=[];errors=[]
  def call(op,payload,**kw):
   calls.append(payload['prompt'])
   if payload['prompt']=='running idle':entered.set();release.wait(2)
   return {}
  a=CoreGameAuthority(SimpleNamespace(call=call))
  def run(prompt,background=False):
   try:a.think(dict(prompt=prompt),background=background)
   except Exception as exc:errors.append(exc)
  first=threading.Thread(target=lambda:run('running idle',True));first.start()
  self.assertTrue(entered.wait(1))
  owner=threading.Thread(target=lambda:run('owner'));owner.start()
  try:
   deadline=time.monotonic()+1
   while a.foreground_waiters!=1 and time.monotonic()<deadline:time.sleep(.001)
   self.assertEqual(a.foreground_waiters,1)
   for i in range(5):
    with self.assertRaises(CoreTurnDeferred):a.think(dict(prompt='discarded idle'),background=True)
  finally:release.set();first.join(2);owner.join(2)
  self.assertEqual(errors,[]);self.assertEqual(calls,['running idle','owner'])
 def test_owner_queued_for_transcription_blocks_idle_without_model_call(self):
  a=CoreGameAuthority(SimpleNamespace(call=lambda *a,**k:self.fail('idle admitted')))
  a.foreground_pending=lambda:True
  with self.assertRaises(CoreTurnDeferred):a.think(dict(prompt='idle'),background=True)
 def test_failure_releases_admission_and_emits_separate_queue_service_timings(self):
  count=[];logs=[]
  def call(*a,**k):
   count.append(1)
   if len(count)==1:raise TimeoutError('fixture')
   return dict(say='Hello')
  a=CoreGameAuthority(SimpleNamespace(call=call));a.log=logs.append
  with self.assertRaises(TimeoutError):a.think(dict(prompt='first'))
  self.assertEqual(a.think(dict(prompt='second'),background=True)['say'],'Hello')
  rows=[json.loads(x.split(' ',1)[1]) for x in logs]
  self.assertEqual([r['outcome'] for r in rows],['failed','returned'])
  self.assertEqual(rows[1]['priority'],'background')
  self.assertGreaterEqual(rows[0]['queue_ms'],0);self.assertGreaterEqual(rows[0]['service_ms'],0)
 def test_owner_turn_precedes_import_and_internal_attention_without_evicting_them(self):
  lane=SupervisedLane.__new__(SupervisedLane)
  internal=dict(game_attention=True,kind='chat');owner=dict(voice_metadata={'request_id':'v'},kind='chat')
  lane.queue=deque([internal,owner],maxlen=4);lane.imports=deque(['memory-trace'])
  self.assertTrue(lane.foreground_pending());self.assertIs(lane._next_request(),owner)
  self.assertFalse(lane.foreground_pending())
  self.assertEqual(lane._next_request(),dict(kind='import',trace='memory-trace'))
  self.assertIs(lane._next_request(),internal)
 def test_pending_owner_finalizer_still_blocks_idle(self):
  lane=SupervisedLane.__new__(SupervisedLane);lane.queue=deque();lane.imports=deque()
  lane.ready=dict(request=dict(execution_receipt={'id':'receipt'}))
  self.assertTrue(lane.foreground_pending())

class IdleContractTests(unittest.TestCase):
 def test_quiet_idle_exposes_complete_non_spawn_choices_and_exact_tour_names(self):
  seen=[]
  def call(op,payload,**kw):
   seen.append(payload['prompt']);return dict(say='A walk.',used_memory_ids=[],intent=dict(action='game_activity',choice=dict(activity='explore')))
  a=CoreGameAuthority(SimpleNamespace(call=call));a.quiet_test_profile=True
  state=dict(map='map',bridgeSession='session',controlEpoch=1);a.observe(state,{})
  result=a.decide_activity('',dict(map='map',navigation_available=True,landmarks=[dict(name='North ground approach')],spawn_choices=[dict(id='bad:spawn')]),state)
  self.assertEqual(result,dict(activity='explore'))
  prompt=seen[0]
  self.assertIn('"action":"game_activity","choice":{"activity":"rest"}',prompt)
  self.assertIn('"action":"game_activity","choice":{"activity":"tour","landmark":"North ground approach"}',prompt)
  self.assertNotIn('bad:spawn',prompt)
  self.assertLessEqual(len(prompt),5800)
 def test_actual_live_browse_wrong_action_is_not_silently_normalized(self):
  a=CoreGameAuthority(SimpleNamespace(call=lambda *a,**k:dict(say='Browse.',used_memory_ids=[],intent=dict(action='browse',choice=dict(query='landmarks',kind='map')))))
  state=dict(map='m',bridgeSession='s',controlEpoch=1);a.observe(state,{})
  with self.assertRaisesRegex(ValueError,'decision schema branch mismatch'):a.decide_activity('',{},state)
 def test_repeated_invalid_idle_decisions_back_off_but_voice_deferral_does_not_count_as_failure(self):
  a=Agenda(None,None,None)
  self.assertEqual([a.defer_core(100) for _ in range(6)],[15,30,60,120,120,120])
  self.assertEqual(a.core_failures,4)
  b=Agenda(None,None,None)
  self.assertEqual(b.defer_core(10,decision_failure=False),2);self.assertEqual(b.core_failures,0)
  b.core_failures=4
  b.accept(dict(context=['m','s',1],choice=dict(activity='rest')),dict(map='m',bridgeSession='s',controlEpoch=1),20)
  self.assertEqual(b.core_failures,0)

if __name__=='__main__':unittest.main()
