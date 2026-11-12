from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys,time,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
from greg_supervised import SupervisedLane,reply_surface
from greg_game_tasks import GameTasks
import test_vc_game_tasks as fixture

class AttentionTests(unittest.TestCase):
 def setUp(self):
  self.view=dict(binding=['map','session',1],current_task=dict(id='goal',phase='needs_review',version=1,completion='observe_cover'),last_refusal=None)
  self.lane=SupervisedLane.__new__(SupervisedLane)
  self.lane.screen_source=object();self.lane.game_tasks=SimpleNamespace(snapshot=lambda:self.view)
  self.lane.delivery=object();self.lane.future=None;self.lane.ready=None;self.lane.queue=[]
  self.lane.last_attention=None;self.lane.attention_due=0;self.lane.attention_binding=None
  self.lane.hear=lambda text:self.lane.queue.append(dict(text=text)) or True
 def attention(self,now):
  with patch('greg_supervised.time.monotonic',return_value=now):
   result=self.lane.consider_game_feedback()
  self.lane.queue.clear();return result
 def test_successful_settle_is_not_reopened_even_with_pending_refusal(self):
  self.view['current_task']['phase']='arrived'
  self.view['last_refusal']=dict(id='new',automatic_recovery=True)
  self.assertFalse(self.attention(100))
 def test_refusal_uuid_changes_cannot_bypass_recovery_interval(self):
  self.assertTrue(self.attention(100))
  self.view['last_refusal']=dict(id='first',automatic_recovery=True)
  self.assertFalse(self.attention(101))
  self.view['last_refusal']=dict(id='second',automatic_recovery=True)
  self.assertFalse(self.attention(102));self.assertTrue(self.attention(115))
 def test_review_phase_cannot_bypass_exhausted_recovery_budget(self):
  self.view['last_refusal']=dict(id='fourth',automatic_recovery=False)
  self.assertFalse(self.attention(100))
 def test_terminal_outcome_has_one_attention_opportunity(self):
  self.view['current_task']=None
  self.view['last_outcome']=dict(id='goal',phase='failed',ended_at=20)
  self.assertTrue(self.attention(100));self.assertFalse(self.attention(200))
 def test_new_world_does_not_inherit_old_attention_cooldown(self):
  self.assertTrue(self.attention(100))
  self.view['binding']=['newmap','newsession',2]
  self.assertTrue(self.attention(101))

class TaskContracts(unittest.TestCase):
 setUp=fixture.TaskTests.setUp
 apply=fixture.TaskTests.apply
 def review(self):
  self.apply(target=self.target,completion='observe_cover')
  self.state['pos']=dict(x=500,y=0,z=0)
  self.link.tick(self.runtime,self.state,3);self.link.update(self.runtime,self.state,3)
 def test_task_context_only_offers_settle_in_review_phase(self):
  self.apply(target=self.target,completion='observe_cover')
  self.link.update(self.runtime,self.state,3)
  self.assertNotIn('settle',self.link.snapshot()['allowed_task_kinds'])
  self.state['pos']=dict(x=500,y=0,z=0);self.link.tick(self.runtime,self.state,4);self.link.update(self.runtime,self.state,4)
  self.assertIn('settle',self.link.snapshot()['allowed_task_kinds'])
  p=dict(action='game_task',kind='settle',task_id=self.link.active['id'])
  self.link.apply(p,self.link.snapshot(),self.state,self.runtime,5,screen_observations=[dict(status='ready',session='test',captured_at=time.time())],screen_session='test')
  self.link.update(self.runtime,self.state,5)
  self.assertNotIn('settle',self.link.snapshot()['allowed_task_kinds'])
 def test_internal_replan_instruction_embeds_exact_current_task_id(self):
  self.apply(target=self.target,completion='observe_cover');self.link.update(self.runtime,self.state,3)
  text=GameTasks.instruction(self.link.snapshot(),internal=True)
  self.assertIn('"task_id":"'+self.link.active['id']+'"',text)
  self.assertIn('Never create a replacement task',text)
 def test_settle_rejections_distinguish_phase_from_frame(self):
  self.review();p=dict(action='game_task',kind='settle',task_id=self.link.active['id'])
  with self.assertRaisesRegex(ValueError,'fresh screen result'):self.link.apply(p,self.link.snapshot(),self.state,self.runtime,4)
  self.link.apply(p,self.link.snapshot(),self.state,self.runtime,4,screen_observations=[dict(status='ready',session='test',captured_at=time.time())],screen_session='test')
  self.link.update(self.runtime,self.state,5)
  with self.assertRaisesRegex(ValueError,'needs_review phase'):self.link.apply(p,self.link.snapshot(),self.state,self.runtime,5)

class SpeechRouting(unittest.TestCase):
 def test_internal_refusal_is_operator_feedback_not_spoken_loop(self):
  row=dict(request=dict(game_attention=True,output_surface='voice'),task_outcome=dict(verdict='refused'))
  self.assertEqual(reply_surface(row,True),'internal')
 def test_owner_request_refusal_still_receives_voice_answer(self):
  row=dict(request=dict(voice_metadata=dict(author_id='owner')),task_outcome=dict(verdict='refused'))
  self.assertEqual(reply_surface(row,True),'voice')

class ActualInternalFailure(unittest.TestCase):
 setUp=fixture.TaskTests.setUp
 def test_bridge_records_internal_refusal_without_offering_tts(self):
  from test_core_game_authority import ActualPublicationTests
  env,delivered=ActualPublicationTests.publish(self,dict(action='game_task',kind='visit',target='bad'),internal=True)
  self.assertEqual(env['surface'],'internal');self.assertFalse(env['published'])
  self.assertEqual(delivered[0]['task_outcome']['reason'],'unoffered destination')
  self.assertEqual(self.link.last_refusal['target'],'bad')

class InternalHoldIdentity(unittest.TestCase):
 setUp=fixture.TaskTests.setUp
 def test_automatic_hold_cannot_replace_active_goal_without_its_id(self):
  self.link.apply(dict(action='game_task',kind='hide',target=self.target),self.link.snapshot(),self.state,self.runtime,2)
  goal=self.link.active['id'];self.link.update(self.runtime,self.state,3)
  from test_core_game_authority import ActualPublicationTests
  env,delivered=ActualPublicationTests.publish(self,dict(action='game_task',kind='hold',stay_seconds=120),internal=True)
  self.assertEqual(self.link.active['id'],goal)
  self.assertEqual(delivered[0]['task_outcome']['reason'],'internal retry must retain task id')
  self.assertFalse(env['published'])

if __name__=='__main__':unittest.main()
