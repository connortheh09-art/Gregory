"""Failed controller tasks must not become successful native goal receipts."""
import sys,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc'),str(ROOT/'tests')]
import test_task_retry_exhaustion as retry
from test_voice_prompt_budget import voice_prefix,view
from greg_supervised import bounded_turn_prompt

class TerminalTruth(unittest.TestCase):
 setUp=retry.Exhaustion.setUp
 snap=retry.Exhaustion.snap;cover=retry.Exhaustion.cover;replan=retry.Exhaustion.replan
 arrive=retry.Exhaustion.arrive;leave=retry.Exhaustion.leave;exhaust=retry.Exhaustion.exhaust
 def goal(self,now):
  self.assertTrue(self.runtime.goals.start('fixture execution','core',self.state,now))
 def terminal(self,status):
  rows=[e for e in self.runtime.memory.recent_events('test_map',30)
        if e.get('kind')=='goal_lifecycle' and e.get('status') in {'failed','completed'}]
  self.assertTrue(rows);self.assertEqual(rows[-1]['status'],status)
 def test_final_window_expiry_is_failed_in_both_controller_and_runtime(self):
  self.exhaust();self.goal(8);self.link.tick(self.runtime,self.state,52)
  self.assertEqual(self.link.last_outcome['phase'],'failed');self.terminal('failed')
 def test_processing_deadline_is_failed_in_both_controller_and_runtime(self):
  self.cover();self.goal(3);self.link.tick(self.runtime,self.state,self.link.active['deadline'])
  self.assertEqual(self.link.last_outcome['phase'],'failed');self.terminal('failed')
 def test_chosen_stay_expiry_remains_a_completed_native_goal(self):
  self.link.apply(dict(action='game_task',kind='hold',stay_seconds=20),self.snap(2),self.state,self.runtime,2)
  self.goal(3);self.link.tick(self.runtime,self.state,22)
  self.assertEqual(self.link.last_outcome['phase'],'expired');self.terminal('completed')

class FinalReviewBudget(unittest.TestCase):
 def test_full_voice_eight_players_and_final_inspection_rule_keep_headroom(self):
  v=view(8);v['current_task'].update(id='x'*32,kind='visit',phase='needs_review',completion='observe_cover',attempts=3,final_review=True)
  v['last_refusal'].update(reason='r'*120,target='t'*80)
  prompt,_=bounded_turn_prompt(voice_prefix(),'q'*1000,{},[],[],task_view=v)
  self.assertGreaterEqual(6000-len(prompt),200)
  self.assertIn('final_review: no more replans; settle or cancel',prompt)
  for p in v['players']:self.assertIn(p['id'],prompt)

if __name__=='__main__':unittest.main()
