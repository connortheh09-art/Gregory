from pathlib import Path
from types import SimpleNamespace
import sys,tempfile,time,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
from greg_game_tasks import GameTasks
from greg_playercore import Runtime,NavGraph,EventMemory
import test_supervised_sensor as fixture
import test_supervised_bridge as bridge_fixture

class TaskTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  rows=[]
  for i,x in [(1,0),(2,500)]:
   rows.append(dict(i=i,c=dict(x=x,y=0,z=0),a=[3-i],k=[dict(x=xx,y=yy,z=0) for xx,yy in [(x-250,-100),(x+250,-100),(x+250,100),(x-250,100)]]))
  self.runtime=Runtime(NavGraph(dict(map='test_map',areas=rows)),EventMemory(Path(self.tmp.name)))
  self.state=dict(map='test_map',bridgeSession='s',controlEpoch=1,pos=dict(x=0,y=0,z=0),capabilities=dict(playercore=True),serverTime=time.time(),enabled=True)
  self.link=GameTasks();self.link.update(self.runtime,self.state,1)
  self.offered=self.link.snapshot();self.target=self.offered['destinations'][0]['id']
 def apply(self,kind='visit',**kwargs):return self.link.apply(dict(action='game_task',kind=kind,**kwargs),self.offered,self.state,self.runtime,2)
 def test_actual_runtime_routes_then_holds_without_claiming_concealment(self):
  self.apply(target=self.target,objective='Find somewhere out of the open',stay_seconds=120)
  action=self.link.tick(self.runtime,self.state,2)
  self.assertEqual(action['action'],'navigate');self.assertFalse(action['walk'])
  self.state['pos']=dict(x=500,y=0,z=0);self.link.tick(self.runtime,self.state,3);self.link.update(self.runtime,self.state,3)
  self.assertEqual(self.link.snapshot()['current_task']['phase'],'arrived')
  self.assertIn('concealment unverified',self.link.snapshot()['current_task']['qualification'])
  self.assertEqual(self.link.tick(self.runtime,self.state,4),dict(action='wait'))
 def test_visit_without_chosen_stay_releases_on_arrival(self):
  self.apply(target=self.target);self.state['pos']=dict(x=500,y=0,z=0)
  self.link.tick(self.runtime,self.state,3);self.link.update(self.runtime,self.state,3)
  self.assertFalse(self.link.engaged);self.assertEqual(self.link.snapshot()['last_outcome']['phase'],'arrived')
 def test_chosen_hold_expires_and_releases(self):
  self.apply('hold',stay_seconds=120);self.link.tick(self.runtime,self.state,123)
  self.assertFalse(self.link.engaged)
 def test_blocked_task_releases_and_keeps_feedback(self):
  self.apply(target=self.target)
  self.runtime.route_action=lambda *a:({'action':'wait'},'No connected walking route')
  self.link.tick(self.runtime,self.state,3);self.link.update(self.runtime,self.state,3)
  self.assertFalse(self.link.engaged);self.assertEqual(self.link.snapshot()['last_outcome']['phase'],'blocked')
 def test_actual_spoken_stop_clears_task_in_same_tick(self):
  self.apply(target=self.target);self.link.tick(self.runtime,self.state,2)
  source=(ROOT/'deployments/oldpc/gmod_bridge.py').read_text()
  intent,runtime,lane,writes=bridge_fixture.exercise_chat(source,'Stop.',supervised=True,game_tasks=self.link)
  self.assertFalse(self.link.engaged);self.assertIsNone(self.link.tick(self.runtime,self.state,3))
  self.assertTrue(any(w.get('action')=='wait' for w in writes))
 def test_actual_continue_directive_preserves_conversational_task(self):
  self.apply(target=self.target)
  source=(ROOT/'deployments/oldpc/gmod_bridge.py').read_text()
  bridge_fixture.exercise_chat(source,'continue',supervised=True,game_tasks=self.link)
  self.assertTrue(self.link.engaged)
 def test_continue_keeps_existing_route(self):
  self.apply(target=self.target);self.link.tick(self.runtime,self.state,2);route=self.runtime.route_id
  self.link.update(self.runtime,self.state,3);self.offered=self.link.snapshot();self.apply('continue')
  self.assertEqual(self.runtime.route_id,route)
 def test_invented_destination_refused(self):
  with self.assertRaises(ValueError):self.apply(target='invented')
  self.assertFalse(self.link.engaged)
 def test_old_epoch_refused(self):
  self.state['controlEpoch']=2
  with self.assertRaises(ValueError):self.apply(target=self.target)
 def test_old_revision_refused(self):
  self.apply('hold')
  with self.assertRaises(ValueError):self.apply('cancel')
 def test_cancel_releases_task(self):
  self.apply('hold');self.link.update(self.runtime,self.state,3);self.offered=self.link.snapshot();self.apply('cancel')
  self.assertFalse(self.link.engaged)
 def test_disconnected_route_refused_before_mutation(self):
  self.runtime.graph.links={1:{},2:{}}
  with self.assertRaises(ValueError):self.apply(target=self.target)
  self.assertFalse(self.link.engaged)
 def test_map_change_stops_task(self):
  self.apply('hold');self.state['map']='other'
  self.assertEqual(self.link.tick(self.runtime,self.state,3),dict(action='wait'));self.assertFalse(self.link.engaged)
 def test_arbitrary_coordinate_or_permission_field_refused(self):
  with self.assertRaises(ValueError):self.apply('hold',position=[0,0,0])
 def test_prompt_requires_correct_outer_reply_envelope(self):
  prompt=self.link.instruction(self.offered)
  self.assertIn('keys intent, say, used_memory_ids',prompt)  # lean L1: action first
  self.assertNotIn('Return optional intent',prompt)
 def test_disconnected_nearby_area_is_not_offered(self):
  self.runtime.graph.links={1:{},2:{}}
  self.link.update(self.runtime,self.state,5)
  self.assertEqual(self.link.snapshot()['destinations'],[])
 def test_blocked_edge_is_not_offered_and_recovers_after_expiry(self):
  self.runtime.memory.edge_failure('test_map',(1,2),time.time())
  self.link.update(self.runtime,self.state,5)
  self.assertEqual(self.link.snapshot()['destinations'],[])
  self.runtime.memory.world['test_map']['blocked_edges']={}
  self.link.update(self.runtime,self.state,9)
  targets=self.link.snapshot()['destinations'];self.assertTrue(targets)
  for target in targets:
   self.runtime.graph.route((0,0,0),target['position'])
 def test_wrong_nav_map_offers_nothing(self):
  self.state['map']='other';self.link.update(self.runtime,self.state,5)
  self.assertFalse(self.link.snapshot()['navigation_available']);self.assertEqual(self.link.snapshot()['destinations'],[])

class VoiceCoreTests(unittest.TestCase):
 setUp=fixture.SensorTests.setUp
 cleanup=fixture.SensorTests.cleanup
 wait_for=fixture.SensorTests.wait_for
 def enable(self):
  self.tasks=GameTasks();self.tasks.view=dict(binding=(self.state['map'],self.state['bridgeSession'],1),revision=0,current_task=None,destinations=[dict(id='offered',position=[500,0,0],cover='unverified')],navigation_available=True)
  self.lane.game_tasks=self.tasks
  self.lane.delivery=SimpleNamespace(config=dict(owner_id='owner',guild_id='guild',channel_id='voice'),stamp=lambda:('connection',1),invalidate=lambda:None)
  self.meta=dict(author_id='owner',guild_id='guild',channel_id='voice',connection='connection',generation=1,request_id='r1',captured_at=time.time())
  def generate(profile,prompt):
   self.provider.prompt=prompt
   return dict(say="I'll try somewhere less exposed.",used_memory_ids=[],intent=dict(action='game_task',kind='visit',target='D1',objective='Hide and seek'))
  self.provider.generate=generate
 def test_authenticated_voice_core_returns_proposal_without_worker_dispatch(self):
  self.enable();self.assertTrue(self.lane.hear_voice('Lets play hide and seek, you go hide',self.meta));self.wait_for(lambda:self.lane.ready is not None)
  row=self.lane.take();self.assertEqual(row['game_intent']['target'],'offered');self.assertIn('GAME TASK CONTEXT',self.provider.prompt);self.assertFalse(self.tasks.engaged)
 def test_guest_cannot_enqueue(self):
  self.enable();self.meta['author_id']='guest';self.assertFalse(self.lane.hear_voice('Go hide',self.meta));self.assertFalse(self.lane.queue)
 def test_plain_chat_has_no_task_handoff(self):
  self.enable();self.lane.hear('Hello');self.wait_for(lambda:self.lane.ready is not None)
  self.assertIsNone(self.lane.take()['game_intent']);self.assertNotIn('GAME TASK CONTEXT',self.provider.prompt)
 def test_private_dm_disclosure_branch_never_returns_game_action(self):
  self.enable()
  original=self.core.call
  def call(action,payload=None,**kwargs):
   if action=='think':return dict(say='private answer',intent=dict(action='game_task',kind='hold'))
   return original(action,payload,**kwargs)
  self.core.call=call
  result=self.lane._work(dict(kind='chat',generation=self.lane.generation,text='discuss my DMs',inbox_voice_claim='fixture',delivery_stamp=('connection',1)))
  self.assertNotIn('game_intent',result);self.assertFalse(self.tasks.engaged)
 def test_stale_voice_connection_refused(self):
  self.enable();self.meta['generation']=0;self.assertFalse(self.lane.hear_voice('Go hide',self.meta))

if __name__=='__main__':unittest.main()
