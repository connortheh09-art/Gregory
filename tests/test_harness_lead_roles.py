"""Lead/role selection guidance and no_change speech honesty (Grady, Harness R3 slice)."""
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc'),str(ROOT/'tests')]
import test_core_harness as harness
from greg_game_tasks import GameTasks

class LeadRoles(unittest.TestCase):
 # Reuse the harness fixture without re-running its inherited tests.
 setUp=harness.HarnessTests.setUp;publish=harness.HarnessTests.publish;finalize=harness.HarnessTests.finalize
 def instruction(self):
  return GameTasks.instruction(self.link.snapshot())
 def test_contract_defines_follow_direction_and_lead_means_visit(self):
  text=self.instruction()
  self.assertIn('follow/approach mean YOU go to THEM',text)
  self.assertIn('lets you lead/choose or will follow you',text)
  self.assertIn('pick an offered destination ID yourself now (visit)',text)
  self.assertIn('replacing follow; do not ask them to pick',text)
 def test_contract_does_not_invent_labels_for_unlabelled_spots(self):
  text=self.instruction()
  self.assertIn('Unlabelled destinations are spots, not known buildings',text)
  for d in self.link.snapshot().get('destinations',[]):
   self.assertNotIn('name',d)
 def test_lead_request_resolves_through_existing_validated_visit(self):
  # The guidance points at an action the controller already validates and executes.
  self.row['game_intent']=dict(action='game_task',kind='visit',target=self.target,objective='lead to a spot')
  self.publish();receipt=self.lane.queue[0]['execution_receipt']
  self.assertEqual(receipt['status'],'accepted');self.assertEqual(receipt['kind'],'visit')
  self.assertEqual(self.link.tick(self.runtime,self.state,2)['action'],'navigate')
 def test_no_change_finalization_forbids_choosing_filler(self):
  self.publish();receipt=self.lane.queue[0]['execution_receipt']
  self.assertEqual(receipt['status'],'no_change')
  self.finalize();prompt=self.asked[0]['prompt']
  # Lean L5: positive wording; no example sentence to parrot.
  self.assertIn('say so in your own words and offer to try',prompt)
  self.assertNotIn('UNSPOKEN_DRAFT',prompt)  # L7: the pre-outcome draft is not offered on no_change
  self.assertNotIn('I have not started moving',prompt)
  self.assertIn('You still have your game controls next turn',prompt)
  self.assertIn('This reply is speech only',prompt)
 def test_no_image_draft_cannot_invent_visible_suggestions(self):
  self.publish();self.finalize()
  self.assertIn('You have no image this turn: describe nothing you would have to see',self.asked[0]['prompt'])
 def test_ready_image_preserves_grounded_vision_instead_of_denial(self):
  self.row['screen_observations']=[dict(status='ready')]
  self.publish();self.finalize()
  self.assertIn('Keep only what the draft said about the image',self.asked[0]['prompt'])
  self.assertNotIn('You have no image this turn',self.asked[0]['prompt'])
 def test_guidance_adds_no_new_task_kinds_or_parser(self):
  kinds=GameTasks.allowed_kinds(True,None,True,True)
  self.assertEqual(sorted(kinds),sorted(['continue','cancel','hold','visit','hide','follow','approach','move']))

if __name__=='__main__':unittest.main()
