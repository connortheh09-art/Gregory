from pathlib import Path
import sys,unittest,json
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
from greg_game_tasks import GameTasks
import test_vc_game_tasks as base

OWNER='STEAM_0:1:1000'
class PlayerTasks(unittest.TestCase):
 setUpBase=base.TaskTests.setUp
 def setUp(self):
  self.setUpBase();self.link=GameTasks(OWNER)
  self.state['players']=[dict(steamid=OWNER,name='Connor',fresh=True,pos=dict(x=500,y=0,z=0))]
  self.link.update(self.runtime,self.state,1);self.offered=self.link.snapshot();self.player=self.offered['players'][0]['id']
 def apply(self,kind='follow',target=None):
  return self.link.apply(dict(action='game_task',kind=kind,target=target or self.player),self.offered,self.state,self.runtime,2)
 def test_actual_follow_controller_tracks_person_and_stays_active_when_close(self):
  self.apply();first=self.link.tick(self.runtime,self.state,2)
  self.assertEqual(first['action'],'navigate');self.assertEqual(first['gazeSteamID'],OWNER)
  self.state['pos']=dict(x=450,y=0,z=0)
  self.assertEqual(self.link.tick(self.runtime,self.state,3)['action'],'gaze');self.assertTrue(self.link.engaged)
  self.state['players'][0]['pos']['x']=0
  self.assertEqual(self.link.tick(self.runtime,self.state,5)['action'],'navigate')
 def test_approach_finishes_once_in_range(self):
  self.apply('approach');self.link.tick(self.runtime,self.state,2)
  self.state['pos']=dict(x=500,y=0,z=0);self.link.tick(self.runtime,self.state,3)
  self.assertFalse(self.link.engaged);self.assertEqual(self.link.last_outcome['phase'],'arrived')
 def test_dormant_target_stops_route_not_stale_following(self):
  self.apply();self.link.tick(self.runtime,self.state,2);self.state['players'][0]['fresh']=False
  self.assertEqual(self.link.tick(self.runtime,self.state,3),dict(action='wait'))
  self.assertFalse(self.link.engaged);self.assertIsNone(self.runtime.route)
 def test_fabricated_player_id_is_refused(self):
  with self.assertRaisesRegex(ValueError,'player target'):self.apply(target='invented')
 def test_disappearing_target_is_rechecked_at_apply(self):
  self.state['players']=[]
  with self.assertRaisesRegex(ValueError,'player target'):self.apply()
 def test_duplicate_steam_identity_cannot_select_an_ambiguous_person(self):
  self.state['players']*=2;self.link.update(self.runtime,self.state,2)
  self.assertEqual(self.link.snapshot()['players'],[])
 def test_display_name_is_not_owner_authority_and_native_ids_do_not_leak(self):
  self.state['players'].append(dict(steamid='STEAM_0:1:2000',name='Connor',fresh=True,pos=dict(x=100,y=0,z=0)))
  self.link.update(self.runtime,self.state,2);view=self.link.snapshot()
  self.assertEqual([p['is_owner'] for p in view['players']],[True,False])
  self.assertNotIn(OWNER,json.dumps(view));self.assertNotIn('STEAM_',json.dumps(view))
 def test_world_change_rejects_old_alias_and_clears_follow_task(self):
  self.apply();self.state['controlEpoch']=2;self.link.update(self.runtime,self.state,3)
  self.assertFalse(self.link.engaged);self.assertNotEqual(self.link.snapshot()['players'][0]['id'],self.player)
  with self.assertRaisesRegex(ValueError,'stale task'):self.apply()
 def test_follow_is_bounded_by_processing_deadline(self):
  self.apply();self.link.tick(self.runtime,self.state,603)
  self.assertFalse(self.link.engaged);self.assertEqual(self.link.last_outcome['phase'],'failed')
 def test_natural_task_prompt_exposes_tools_not_trigger_phrases(self):
  text=GameTasks.instruction(self.offered)
  self.assertIn('follow',text);self.assertIn('approach',text);self.assertIn(self.player,text)
  self.assertIn('no movement starts',text);self.assertNotIn(OWNER,text)
 def test_relative_nav_bearing_uses_current_heading(self):
  self.state['ang']=dict(y=0);self.link.last_candidates=-float('inf');self.link.update(self.runtime,self.state,3)
  dest=self.link.snapshot()['destinations'][0]
  self.assertEqual(dest['bearing_relative'],0);self.assertEqual(dest['distance'],500)

class IdleBackoffTests(unittest.TestCase):
 def test_actual_bridge_defers_failed_idle_decisions_without_legacy_fallback(self):
  import ast
  from types import SimpleNamespace
  source=(ROOT/'deployments/oldpc/gmod_bridge.py').read_text()
  tree=ast.parse(source)
  node=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=="a.supervised_session and pending_kind == 'agenda'")
  unit=compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-backoff>','exec')
  from greg_agenda import Agenda
  agenda=Agenda(None,None,None);logs=[]
  env=dict(a=SimpleNamespace(supervised_session=True),pending_kind='agenda',agenda=agenda,now=10,exc=ValueError('invalid'),log=logs.append)
  exec(unit,env)
  self.assertEqual(agenda.next_at,25);self.assertEqual(agenda.reconsider_at,25)
  self.assertIn('no legacy fallback',logs[0])
  env['a'].supervised_session=False;agenda.next_at=0;exec(unit,env)
  self.assertEqual(agenda.next_at,0)

class RelativeMovementTests(unittest.TestCase):
 def setUp(self):
  base.TaskTests.setUp(self);self.state['ang']=dict(y=0)
  self.link.update(self.runtime,self.state,2);self.offered=self.link.snapshot()
 def move(self,**fields):
  return self.link.apply(dict(action='game_task',kind='move',direction='forward',**fields),self.offered,self.state,self.runtime,3)
 def test_relative_move_uses_existing_route_and_finishes(self):
  self.move(distance=400)
  self.assertEqual(self.link.active['target']['position'],[400,0,0])
  action=self.link.tick(self.runtime,self.state,3)
  self.assertEqual(action['action'],'navigate');self.assertFalse(action['walk'])
  self.state['pos']=dict(x=400,y=0,z=0);self.link.tick(self.runtime,self.state,4)
  self.assertFalse(self.link.engaged)
 def test_direction_uses_fresh_heading_not_old_prompt_heading(self):
  self.state['ang']['y']=180;self.move(distance=200)
  self.assertAlmostEqual(self.link.active['target']['position'][0],-200)
 def test_missing_heading_refuses_motion(self):
  del self.state['ang']
  with self.assertRaisesRegex(ValueError,'pose'):self.move()
 def test_bad_distances_are_refused_without_changing_task(self):
  for value in (True,0,63,1025,float('nan'),float('inf'),'400'):
   with self.subTest(value=value),self.assertRaisesRegex(ValueError,'distance'):self.move(distance=value)
  self.assertFalse(self.link.engaged)
 def test_coordinate_and_target_bypass_are_refused(self):
  for fields in (dict(pos=[100,0,0]),dict(target='injected')):
   with self.subTest(fields=fields),self.assertRaises(ValueError):self.move(**fields)
 def test_outside_nav_is_refused(self):
  self.state['ang']['y']=90
  with self.assertRaisesRegex(ValueError,'navigation'):self.move(distance=500)
 def test_blocked_link_refuses_relative_destination(self):
  self.runtime.memory.blocked=lambda *a:{(1,2)}
  with self.assertRaisesRegex(ValueError,'connected walk route'):self.move(distance=500)
 def test_capability_not_offered_without_heading(self):
  self.assertIn('move',self.offered['allowed_task_kinds'])
  del self.state['ang'];self.link.update(self.runtime,self.state,3)
  self.assertNotIn('move',self.link.snapshot()['allowed_task_kinds'])
 def test_snap_that_reverses_requested_direction_is_refused(self):
  # A 64-unit request can be snapped all the way back to our feet.
  # The old <=64 snap-distance check alone accepted that no-op/opposite snap.
  self.runtime.graph.attach=lambda p:1
  self.runtime.graph.areas[1].closest=lambda p:(0,0,0)
  with self.assertRaisesRegex(ValueError,'direction'):self.move(distance=64)
  self.assertFalse(self.link.engaged)

if __name__=='__main__':unittest.main()
