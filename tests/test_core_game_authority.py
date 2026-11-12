from pathlib import Path
from types import SimpleNamespace
import sys,tempfile,time,unittest,json,threading
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
from greg_supervised import CoreGameAuthority,bounded_turn_prompt
from greg_game_tasks import GameTasks
from greg_agenda import Agenda
from gregory_core.runtime import Core,FixtureProvider
import test_vc_game_tasks as fixture

class PersistentTasks(unittest.TestCase):
 setUp=fixture.TaskTests.setUp
 apply=fixture.TaskTests.apply
 def test_actual_current_target_survives_offer_rotation_and_retry_keeps_goal(self):
  self.apply(target=self.target,objective='hide',completion='observe_cover')
  goal=self.link.active['id'];self.link.update(self.runtime,self.state,3);offer=self.link.snapshot();offer['destinations']=[]
  self.link.apply(dict(action='game_task',kind='visit',target=self.target,task_id=goal),offer,self.state,self.runtime,4)
  self.assertEqual(self.link.active['id'],goal);self.assertEqual(self.link.active['completion'],'observe_cover')
  self.assertEqual(self.link.tick(self.runtime,self.state,5)['action'],'navigate')
 def test_rejected_target_cannot_apply_but_feedback_survives_for_retry(self):
  self.apply(target=self.target);goal=self.link.active['id'];self.link.update(self.runtime,self.state,3)
  proposal=dict(action='game_task',kind='visit',target='invented',task_id=goal)
  with self.assertRaises(ValueError):self.link.apply(proposal,self.link.snapshot(),self.state,self.runtime,4)
  self.link.record_refusal(proposal,self.link.snapshot(),self.state,'unoffered destination');self.link.update(self.runtime,self.state,4)
  self.assertEqual(self.link.snapshot()['last_refusal']['target'],'invented');self.assertEqual(self.link.active['id'],goal)
  self.assertTrue(self.link.snapshot()['last_refusal']['automatic_recovery'])
 def test_blocked_hiding_task_does_not_release_to_random_agenda(self):
  self.apply(target=self.target,completion='observe_cover');goal=self.link.active['id']
  self.runtime.route_action=lambda *args:({'action':'wait'},'blocked by observed controller feedback')
  self.link.tick(self.runtime,self.state,3);self.link.update(self.runtime,self.state,3)
  self.assertTrue(self.link.engaged);self.assertEqual(self.link.active['id'],goal)
  self.assertEqual(self.link.active['phase'],'needs_review')
 def test_reached_hiding_destination_needs_fresh_inspection_before_settle(self):
  self.apply(target=self.target,completion='observe_cover',stay_seconds=120)
  self.state['pos']=dict(x=500,y=0,z=0);self.link.tick(self.runtime,self.state,3);self.link.update(self.runtime,self.state,3)
  self.assertEqual(self.link.active['phase'],'needs_review')
  proposal=dict(action='game_task',kind='settle',task_id=self.link.active['id'],stay_seconds=120)
  with self.assertRaises(ValueError):self.link.apply(proposal,self.link.snapshot(),self.state,self.runtime,4)
  self.link.apply(proposal,self.link.snapshot(),self.state,self.runtime,4,screen_observations=[dict(status='ready',captured_at=time.time(),session='test')],screen_session='test')
  self.assertEqual(self.link.active['phase'],'arrived')
  self.assertIn('not independently verified',self.link.active['qualification'])
 def test_persistent_task_has_deadline_and_releases_truthfully(self):
  self.apply(target=self.target,completion='observe_cover',budget_seconds=30)
  self.link.tick(self.runtime,self.state,33);self.link.update(self.runtime,self.state,33)
  self.assertFalse(self.link.engaged);self.assertEqual(self.link.snapshot()['last_outcome']['phase'],'failed')

 def test_invalid_task_kind_is_refused_without_mutation(self):
  with self.assertRaises(ValueError):self.apply(kind={},target=self.target)
  self.assertFalse(self.link.engaged)

class SharedContext(unittest.TestCase):
 def setUp(self):
  self.state=dict(map='map',bridgeSession='session',controlEpoch=1)
  self.authority=CoreGameAuthority(None);self.authority.observe(self.state,{})
 def test_explosive_car_request_is_visible_in_voice_context_not_false_spawn_success(self):
  self.authority.action(self.state,dict(action='spawn_item',id='entity:explosive_car'),True,10)
  for i in range(12):self.authority.note(self.state,'controller_feedback',status='blocked',sequence=i)
  context=self.authority.context(self.state)
  self.assertEqual(context['last_spawn_request']['command']['id'],'entity:explosive_car')
  self.assertEqual(context['last_spawn_request']['status'],'written_not_confirmed')
  self.assertEqual(context['server_observations'],{'controller_events':[]})
 def test_world_change_cannot_leak_old_actions(self):
  self.authority.action(self.state,dict(action='spawn_item',id='entity:explosive_car'),True,10)
  new=dict(self.state,controlEpoch=2)
  self.assertEqual(self.authority.context(new),{})
  self.authority.observe(new,{})
  self.assertIsNone(self.authority.context(new)['last_spawn_request'])
 def test_voice_activity_ids_are_offered_and_bound(self):
  offered=dict(binding=['map','session',1],spawn_choices=[dict(id='entity:car')])
  p=dict(action='game_activity',choice=dict(activity='spawn',id='entity:car'))
  self.assertEqual(self.authority.validate_activity(p,offered,self.state)['choice']['id'],'entity:car')
  with self.assertRaises(ValueError):self.authority.validate_activity(dict(action='game_activity',choice=dict(activity='spawn',id='bad')),offered,self.state)
  with self.assertRaises(ValueError):self.authority.validate_activity(p,offered,dict(self.state,controlEpoch=2))
 def test_long_history_cannot_push_valid_turn_over_core_limit(self):
  view=dict(binding=['map','session',1],revision=3,current_task=dict(id='x'*32,objective='h'*240,phase='needs_review',target=dict(id='y'*16,position=[10000,-10000,0]),version=3,completion='observe_cover',attempts=2,feedback='b'*160),destinations=[dict(id=str(i)*16,position=[10000,-10000,0],cover='unverified') for i in range(8)])
  self.authority.action(self.state,dict(action='spawn_item',id='prop:'+'x'*240),True,10)
  prefix=GameTasks.instruction(view)
  prompt,ids=bounded_turn_prompt(prefix,'question '*110,self.authority.context(self.state),[dict(id='memory',summary='e'*1000)],[dict(user='u'*1000,reply='r'*1000)]*20)
  self.assertLessEqual(len(prompt),6000);self.assertIn('CURRENT_INPUT',prompt);self.assertIn('exact offered',prompt)

 def test_current_runtime_failure_reaches_context_but_old_world_history_does_not(self):
  now=time.time()
  rows=[dict(map='map',time=now-600,kind='route_failed',reason='old'),dict(map='map',time=now,kind='goal_lifecycle',status='failed',reason='no_reachable_exploration_goal')]
  self.authority.observe(self.state,{},rows)
  events=self.authority.context(self.state)['server_observations']['controller_events']
  self.assertEqual(len(events),1);self.assertEqual(events[0]['status'],'failed')
 def test_vc_travel_activity_cannot_accept_without_navigation(self):
  offered=dict(binding=['map','session',1],navigation_available=False)
  with self.assertRaises(ValueError):self.authority.validate_activity(dict(action='game_activity',choice=dict(activity='explore')),offered,self.state)

 def test_invalid_activity_shape_is_refused_not_a_type_crash(self):
  offered=dict(binding=['map','session',1],navigation_available=True)
  for proposal in [[],dict(action='game_activity',choice=dict(activity={}))]:
   with self.assertRaises(ValueError):self.authority.validate_activity(proposal,offered,self.state)

class CoreDecisionTests(unittest.TestCase):
 def test_agenda_uses_actual_core_persona_and_not_direct_post_chat(self):
  from unittest.mock import patch
  class Provider(FixtureProvider):
   def generate(self,profile,prompt,**kw):
    self.seen_profile=profile;self.seen_prompt=prompt
    return dict(say='I will try the car.',intent=dict(action='game_activity',choice=dict(activity='spawn',id='entity:car')),used_memory_ids=[])
  class Catalog:
   def describe(self,s):return {}
   def choices(self,s,**kw):return [dict(id='entity:car',name='Car',kind='entity')]
   def observations(self,s):return {}
  with tempfile.TemporaryDirectory() as tmp:
   provider=Provider();core=Core(Path(tmp)/'core',provider=provider).start()
   try:
    core.call('persona',dict(persona='The same Gregory persona.'))
    authority=CoreGameAuthority(core);state=dict(map='m',bridgeSession='s',controlEpoch=1)
    authority.observe(state,{})
    agenda=Agenda(Catalog(),'unused','unused',core_decider=authority.decide_activity)
    with patch('greg_agenda.post_chat',side_effect=AssertionError('legacy model bypass')):
     proposal=agenda.decide(state,[])
    self.assertEqual(proposal['authority'],'core');self.assertEqual(proposal['choice']['id'],'entity:car')
    self.assertIn('LIVE_ACTION_RECEIPTS',provider.seen_prompt)
    self.assertEqual(provider.seen_profile['persona'],'The same Gregory persona.')
   finally:core.call('stop');core.thread.join(3)

class ActualPublicationTests(unittest.TestCase):
 setUp=fixture.TaskTests.setUp
 def publish(self,intent,*,offer=None,screen=None,internal=False):
  self.state['steamid']='fixture-bot'
  import ast,gmod_bridge as bridge
  from greg_supervised import reply_surface
  source=(ROOT/'deployments/oldpc/gmod_bridge.py').read_text();tree=ast.parse(source)
  node=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test).startswith('supervised_say is not None and now >= command_due'))
  delivered=[]
  authority=CoreGameAuthority(None);authority.observe(self.state,{})
  class Catalog:
   def entries(c,state):return [dict(id='entity:car',name='Car',key='car')],{}
  agenda=Agenda(Catalog(),'unused','unused')
  stamp=('voice',1)
  request=dict(generation=0,voice_metadata=dict(request_id='r'),delivery_stamp=stamp,trace=None)
  if internal:request.pop('voice_metadata');request['game_attention']=True;request['output_surface']='voice'
  row=dict(request=request,say='I will try it.',game_intent=intent,game_task_view=self.link.snapshot(),screen_observations=screen or [],activity_options=offer or {})
  lane=SimpleNamespace(generation=0,published=lambda row,ok,**kw:delivered.append(row))
  voice=SimpleNamespace(stamp=lambda:stamp,offer=lambda row:True)
  tracker=SimpleNamespace(pending_speech_trace=None,decision_result=lambda *a,**kw:None)
  env=dict(bridge.__dict__);env.update(supervised_say=row,now=2,command_due=0,supervised=lane,
   game_tasks=self.link,game_authority=authority,agenda=agenda,voice_activity=None,
   voice_session=voice,latest=self.state,PLAYERCORE=self.runtime,tracker=tracker,ready=None,
   run_voice_log=None,game_screen=None,reply_surface=reply_surface,log=lambda *a:None)
  exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'actual-publication','exec'),env)
  return env,delivered
 def test_vc_spawn_proposal_is_validated_by_actual_bridge_before_dispatch(self):
  offer=dict(binding=list((self.state[k] for k in ('map','bridgeSession','controlEpoch'))),spawn_choices=[dict(id='entity:car')])
  env,delivered=self.publish(dict(action='game_activity',choice=dict(activity='spawn',id='entity:car')),offer=offer)
  self.assertEqual(env['voice_activity'][2],dict(action='spawn_item',id='entity:car'))
  self.assertEqual(delivered[0]['task_outcome']['verdict'],'accepted')
 def test_actual_rejection_records_target_ids_for_next_core_retry(self):
  _,delivered=self.publish(dict(action='game_task',kind='visit',target='bad'))
  self.assertEqual(delivered[0]['task_outcome']['reason'],'unoffered destination')
  self.assertEqual(delivered[0]['task_outcome']['proposal']['target'],'bad')
  self.link.update(self.runtime,self.state,3)
  self.assertEqual(self.link.snapshot()['last_refusal']['target'],'bad')
 def test_actual_vc_hide_creates_persistent_core_task_not_hold(self):
  _,delivered=self.publish(dict(action='game_task',kind='hide',target=self.target,objective='hide from Connor'))
  self.assertEqual(delivered[0]['task_outcome']['verdict'],'accepted')
  self.assertEqual(self.link.active['completion'],'observe_cover')
  self.assertEqual(self.link.tick(self.runtime,self.state,3)['action'],'navigate')

class VoiceSharedContext(unittest.TestCase):
 def test_voice_actual_core_turn_receives_own_recent_spawn(self):
  import test_supervised_sensor as sensor
  obj=SimpleNamespace()
  # Reuse the complete Core/Recorder fixture through a small TestCase host.
  class Case(unittest.TestCase):
   setUp=sensor.SensorTests.setUp
   cleanup=sensor.SensorTests.cleanup
   wait_for=sensor.SensorTests.wait_for
  host=Case();host.setUp()
  try:
   fixture.VoiceCoreTests.enable(host)
   authority=CoreGameAuthority(host.core);authority.observe(host.state,{})
   authority.action(host.state,dict(action='spawn_item',id='entity:explosive_car'),True,17)
   host.lane.game_authority=authority
   host.lane.hear_voice('Why did you spawn an explosive car?',host.meta)
   host.wait_for(lambda:host.lane.ready is not None)
   self.assertIn('entity:explosive_car',host.provider.prompt)
   self.assertIn('written_not_confirmed',host.provider.prompt)
  finally:host.doCleanups()
 def test_concurrent_activity_and_voice_share_one_core_model_gate(self):
  class Provider(FixtureProvider):
   def __init__(self):self.active=0;self.maximum=0
   def generate(self,profile,prompt,**kw):
    self.active+=1;self.maximum=max(self.maximum,self.active);time.sleep(.02);self.active-=1
    return dict(say='Done.',used_memory_ids=[])
  with tempfile.TemporaryDirectory() as tmp:
   provider=Provider();core=Core(Path(tmp)/'core',provider=provider).start();errors=[]
   try:
    authority=CoreGameAuthority(core)
    def call():
     try:authority.think(dict(prompt='fixture'))
     except Exception as exc:errors.append(exc)
    threads=[threading.Thread(target=call) for _ in range(2)]
    for t in threads:t.start()
    for t in threads:t.join(2)
    self.assertEqual(errors,[]);self.assertEqual(provider.maximum,1)
   finally:core.call('stop');core.thread.join(3)

class OperatorStop(unittest.TestCase):
 def test_stop_uses_shared_drain_and_repeated_requests_never_extend_it(self):
  from greg_supervised import SessionWindow
  window=SessionWindow(0,1200);window.request_stop(10)
  self.assertEqual(window.phase(10,False),'drained');self.assertEqual(window.phase(10,True),'draining')
  window.request_stop(20);self.assertEqual(window.phase(45,True),'expired')

if __name__=='__main__':unittest.main()
