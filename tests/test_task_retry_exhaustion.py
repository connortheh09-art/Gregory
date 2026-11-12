"""Terminal retry exhaustion, final inspection window and bounded internal attention (Grady)."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys,time,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc'),str(ROOT/'tests')]
from greg_supervised import SupervisedLane
from greg_game_tasks import GameTasks
import test_vc_game_tasks as fixture

FRESH=lambda:[dict(status='ready',session='test',captured_at=time.time())]

class Exhaustion(unittest.TestCase):
 setUp=fixture.TaskTests.setUp
 def snap(self,now):self.link.update(self.runtime,self.state,now);return self.link.snapshot()
 def cover(self,now=2):
  return self.link.apply(dict(action='game_task',kind='hide',target=self.target,objective='hide'),self.snap(now),self.state,self.runtime,now)
 def replan(self,now):
  view=self.snap(now)
  return self.link.apply(dict(action='game_task',kind='hide',task_id=self.link.active['id'],target=view['destinations'][0]['id']),view,self.state,self.runtime,now)
 def arrive(self,now):
  self.state['pos']=dict(x=500,y=0,z=0);self.link.tick(self.runtime,self.state,now)
 def leave(self):self.state['pos']=dict(x=0,y=0,z=0)
 def exhaust(self):
  self.cover(2);self.arrive(3);self.leave();self.replan(4);self.arrive(5);self.leave();self.replan(6);self.arrive(7)
  self.assertEqual(self.link.active['attempts'],3)

 def test_arrival_on_last_attempt_keeps_one_final_inspection_window(self):
  self.exhaust();task=self.link.active
  self.assertEqual(task['phase'],'needs_review');self.assertTrue(task['final_review'])
  self.assertIn('settle',self.snap(8)['allowed_task_kinds'])
  self.assertIn('final_review: no more replans',GameTasks.instruction(self.snap(8),internal=True))
 def test_final_window_allows_settle_after_fresh_look(self):
  self.exhaust();p=dict(action='game_task',kind='settle',task_id=self.link.active['id'],stay_seconds=60)
  self.assertEqual(self.link.apply(p,self.snap(8),self.state,self.runtime,8,screen_observations=FRESH(),screen_session='test'),'accepted')
  self.assertEqual(self.link.active['phase'],'arrived')
 def test_final_window_refuses_further_travel_replans(self):
  self.exhaust()
  with self.assertRaisesRegex(ValueError,'retry budget exhausted'):self.replan(8)
 def test_unsettled_final_window_becomes_terminal_failure(self):
  self.exhaust();self.assertEqual(self.link.tick(self.runtime,self.state,7+44),dict(action='wait'))
  self.assertTrue(self.link.engaged)
  self.link.tick(self.runtime,self.state,7+45)
  self.assertFalse(self.link.engaged)
  self.assertEqual(self.snap(53)['last_outcome']['phase'],'failed')
  self.assertIn('ran out of tries',self.snap(53)['last_outcome']['feedback'])
 def test_ordinary_review_has_no_final_window(self):
  self.cover(2);self.arrive(3)
  self.assertFalse(self.link.active['final_review']);self.assertIsNone(self.link.active['review_until'])
 def test_owner_request_still_works_after_exhaustion(self):
  self.exhaust();old=self.link.active['id'];self.leave()
  self.assertEqual(self.cover(9),'accepted')
  self.assertNotEqual(self.link.active['id'],old);self.assertEqual(self.link.active['attempts'],1)
  self.link.tick(self.runtime,self.state,60);self.assertTrue(self.link.engaged)
 def test_owner_request_after_terminal_failure(self):
  self.exhaust();self.link.tick(self.runtime,self.state,60);self.assertFalse(self.link.engaged)
  self.leave();self.assertEqual(self.cover(61),'accepted')

class RefusalBudget(unittest.TestCase):
 setUp=fixture.TaskTests.setUp
 def test_accepted_step_does_not_reset_same_task_refusal_budget(self):
  self.link.apply(dict(action='game_task',kind='hide',target=self.target),self.link.snapshot(),self.state,self.runtime,2)
  tid=self.link.active['id']
  for _ in range(3):self.link.record_refusal({},None,self.state,'unoffered destination')
  self.state['pos']=dict(x=500,y=0,z=0);self.link.tick(self.runtime,self.state,3);self.state['pos']=dict(x=0,y=0,z=0)
  self.link.update(self.runtime,self.state,4);view=self.link.snapshot()
  self.link.apply(dict(action='game_task',kind='hide',task_id=tid,target=view['destinations'][0]['id']),view,self.state,self.runtime,4)
  self.link.record_refusal({},None,self.state,'unoffered destination')
  self.assertFalse(self.link.last_refusal['automatic_recovery'])
 def test_new_task_resets_refusal_budget(self):
  for _ in range(4):self.link.record_refusal({},None,self.state,'unoffered destination')
  self.link.apply(dict(action='game_task',kind='visit',target=self.target),self.link.snapshot(),self.state,self.runtime,2)
  self.link.record_refusal({},None,self.state,'unoffered destination')
  self.assertTrue(self.link.last_refusal['automatic_recovery'])
 def test_contract_says_non_travel_kinds_take_no_target(self):
  self.assertIn('continue/settle/hold/cancel take no target',GameTasks.instruction(self.link.snapshot()))
  for kind in ('continue','settle','hold','cancel'):
   with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'target only applies'):
    self.link.apply(dict(action='game_task',kind=kind,target=self.target),self.link.snapshot(),self.state,self.runtime,2)

class AttentionCap(unittest.TestCase):
 def setUp(self):
  self.view=dict(binding=['map','session',1],current_task=dict(id='goal',phase='needs_review',version=1,completion='observe_cover'),last_refusal=None)
  self.lane=SupervisedLane.__new__(SupervisedLane)
  self.lane.screen_source=object();self.lane.game_tasks=SimpleNamespace(snapshot=lambda:self.view)
  self.lane.delivery=object();self.lane.future=None;self.lane.ready=None;self.lane.queue=[]
  self.lane.last_attention=None;self.lane.attention_due=0;self.lane.attention_binding=None;self.lane.attention_counts={}
  self.lane.hear=lambda text:self.lane.queue.append(dict(text=text)) or True
 def attention(self,now):
  with patch('greg_supervised.time.monotonic',return_value=now):r=self.lane.consider_game_feedback()
  self.lane.queue.clear();return r
 def test_stuck_review_gets_at_most_four_internal_turns(self):
  fired=[self.attention(100+i*20) for i in range(10)]
  self.assertEqual(sum(fired),4);self.assertEqual(fired[:4],[True]*4)
 def test_new_task_id_gets_its_own_budget(self):
  for i in range(6):self.attention(100+i*20)
  self.view['current_task']=dict(self.view['current_task'],id='goal-2')
  self.assertTrue(self.attention(400))
 def test_refused_attention_admission_does_not_consume_budget_or_delay(self):
  admit=self.lane.hear;self.lane.hear=lambda text:False
  for i in range(6):self.assertFalse(self.attention(100+i*20))
  self.assertEqual(self.lane.attention_counts,{})
  self.assertIsNone(self.lane.last_attention);self.assertEqual(self.lane.attention_due,0)
  self.lane.hear=admit
  self.assertTrue(self.attention(221));self.assertEqual(self.lane.attention_counts['goal'],1)
 def test_world_change_resets_counts(self):
  for i in range(6):self.attention(100+i*20)
  self.view['binding']=['map','session',2]
  self.assertTrue(self.attention(400))
 def test_terminal_outcome_attention_is_not_counted_against_active_task(self):
  self.view['current_task']=None;self.view['last_outcome']=dict(id='goal',phase='failed',ended_at=20)
  self.assertTrue(self.attention(100));self.assertEqual(self.lane.attention_counts,{})

if __name__=='__main__':unittest.main()
