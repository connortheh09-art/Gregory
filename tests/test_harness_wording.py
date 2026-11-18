"""Receipt explanations and finalization speech guidance (Grady's half of Harness R2)."""
import ast,re,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc'),str(ROOT/'tests')]
import test_core_harness as harness
from greg_supervised import explain_refusal,_REFUSAL_EXPLANATIONS,_FALLBACK_REFUSAL

FORBIDDEN=re.compile(r'\b(map|id|uuid|validat\w*|error|exception|offered|unoffered|stale|budget)\b',re.I)

class ExplanationTable(unittest.TestCase):
 def test_unoffered_destination_is_an_option_not_a_map_claim(self):
  self.assertEqual(explain_refusal('unoffered destination'),"that spot wasn't one of my current options")
 def test_unknown_or_empty_codes_get_generic_line_not_a_guess(self):
  for code in (None,'','something new',' brand-new controller code '):
   self.assertEqual(explain_refusal(code),_FALLBACK_REFUSAL)
 def test_lookup_is_exact_code_not_substring(self):
  self.assertEqual(explain_refusal('unoffered destination because reasons'),_FALLBACK_REFUSAL)
 def test_every_explanation_is_plain_bounded_speech(self):
  for code,text in list(_REFUSAL_EXPLANATIONS.items())+[('fallback',_FALLBACK_REFUSAL)]:
   with self.subTest(code=code):
    self.assertLessEqual(len(text),80);self.assertNotRegex(text,FORBIDDEN)
 def test_controller_refusal_codes_are_all_covered(self):
  # Every ValueError a voice-reachable apply/validate path can raise must map
  # to a plain explanation, except pure schema errors (model shape mistakes).
  schema={'bounded game task required','bounded objective required','bounded stay required',
   'bounded task completion/budget required','bounded relative direction/distance required',
   'relative travel fields only apply to move','stay only applies to visit/hold',
   'target only applies to visit','Core activity proposal required','bounded Core activity required',
   'bounded activity text required','known reply surface required','essential game context exceeds turn budget'}
  codes=set()
  for name in ('greg_game_tasks.py','greg_supervised.py'):
   tree=ast.parse((ROOT/'deployments/oldpc'/name).read_text())
   for node in ast.walk(tree):
    if (isinstance(node,ast.Call) and getattr(node.func,'id',None)=='ValueError' and node.args
      and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str)):
     codes.add(node.args[0].value)
  self.assertEqual(sorted(codes-schema-set(_REFUSAL_EXPLANATIONS)),[])

class ReceiptWording(unittest.TestCase):
 setUp=harness.HarnessTests.setUp
 publish=harness.HarnessTests.publish
 finalize=harness.HarnessTests.finalize
 def test_refused_receipt_carries_plain_explanation_into_finalization(self):
  self.row['game_intent']=dict(action='game_task',kind='visit',target='fabricated')
  self.publish();receipt=self.lane.queue[0]['execution_receipt']
  self.assertEqual(receipt['status'],'refused')
  self.assertEqual(receipt['explanation'],"that spot wasn't one of my current options")
  self.finalize();prompt=self.asked[0]['prompt']
  self.assertIn("that spot wasn't one of my current options",prompt)
  self.assertNotIn('unoffered destination',prompt)
  self.assertEqual(receipt['reason'],'unoffered destination')
  self.assertIn('giving only receipt.explanation as the reason',prompt)
  self.assertNotIn('go along with it',prompt)  # L9
 def test_accepted_and_no_change_receipts_have_no_refusal_explanation(self):
  self.publish();self.assertIsNone(self.lane.queue[0]['execution_receipt']['explanation'])
  self.lane.queue.clear();self.lane.turn_ledger.clear()
  self.row['game_intent']=dict(action='game_task',kind='visit',target=self.target)
  self.row['request']=dict(self.row['request'],voice_metadata=dict(request_id='owner-turn-2'))
  self.publish();receipt=self.lane.queue[0]['execution_receipt']
  self.assertEqual(receipt['status'],'accepted');self.assertIsNone(receipt['explanation'])
 def test_accept_guidance_is_conversational_and_keeps_existing_guards(self):
  self.row['game_intent']=dict(action='game_task',kind='visit',target=self.target)
  self.publish();self.finalize();prompt=self.asked[0]['prompt']
  self.assertIn('lead the way',prompt);self.assertIn('Talk like a person, not a system',prompt)
  # Pre-existing honesty contracts survive the lean wording (L5), stated positively.
  self.assertNotIn('you have not done it yet',prompt);self.assertNotIn('It did not work',prompt)  # L9: no other status's rule
  for clause in ('You have not seen the result yet','You still have your game controls next turn',
                 'invent no places, objects or obstacles','This reply is speech only'):
   self.assertIn(clause,prompt)

if __name__=='__main__':unittest.main()
