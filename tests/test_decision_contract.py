"""Short labels are scoped to one exact offer; grammar is not controller authority."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import sys,json,time,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc'),str(ROOT/'tests')]
from gregory_core.decision_contract import TurnChoices,SchemaViolation,validate,envelope,obj,enum,without_inspection,generate
from gregory_core.runtime import LMStudioProvider,FixtureProvider
from greg_supervised import bounded_turn_prompt
import test_player_game_tasks as fixture
from test_voice_prompt_budget import view,voice_prefix

class Choices(unittest.TestCase):
 setUp=fixture.PlayerTasks.setUp
 setUpBase=fixture.PlayerTasks.setUpBase
 def contract(self,internal=False):
  native=self.link.snapshot();c=TurnChoices(native);s=c.schema(c.view,{},internal=internal)
  return c,s,native
 def test_labels_round_trip_into_unchanged_real_controller(self):
  c,s,native=self.contract();p=c.decode(dict(action='game_task',kind='follow',target='P1'),s)
  self.assertEqual(p['target'],self.player)
  self.assertEqual(self.link.apply(p,native,self.state,self.runtime,2),'accepted')
  self.assertEqual(self.link.tick(self.runtime,self.state,3)['action'],'navigate')
 def test_destinations_round_trip_without_mutating_snapshot(self):
  c,s,native=self.contract();before=deepcopy(native)
  p=c.decode(dict(action='game_task',kind='visit',target='D1'),s)
  self.assertEqual(p['target'],native['destinations'][0]['id']);self.assertEqual(native,before)
 def test_unknown_alias_native_id_and_extra_target_are_refused(self):
  c,s,native=self.contract()
  for p in [dict(action='game_task',kind='visit',target='D99'),dict(action='game_task',kind='visit',target=native['destinations'][0]['id']),dict(action='game_task',kind='continue',target='D1')]:
   with self.subTest(proposal=p),self.assertRaises(SchemaViolation):c.decode(p,s)
 def test_each_request_owns_its_mapping_no_global_remap(self):
  c,s,native=self.contract();other=deepcopy(native);other['destinations'][0]['id']='different-native-id'
  d=TurnChoices(other);ds=d.schema(d.view,{})
  p=dict(action='game_task',kind='visit',target='D1')
  self.assertNotEqual(c.decode(p,s)['target'],d.decode(p,ds)['target'])
  self.assertEqual(c.decode(p,s)['target'],native['destinations'][0]['id'])
 def test_stale_revision_rejects_decoded_alias(self):
  c,s,native=self.contract();p=c.decode(dict(action='game_task',kind='visit',target='D1'),s)
  self.link.apply(dict(action='game_task',kind='hold'),native,self.state,self.runtime,2)
  with self.assertRaisesRegex(ValueError,'stale task decision'):self.link.apply(p,native,self.state,self.runtime,3)
 def test_active_task_label_is_exact_and_internal_replan_requires_it(self):
  self.link.apply(dict(action='game_task',kind='follow',target=self.player),self.link.snapshot(),self.state,self.runtime,2)
  self.link.update(self.runtime,self.state,3);c,s,native=self.contract(internal=True)
  self.assertEqual(c.view['current_task']['id'],'T1')
  with self.assertRaises(SchemaViolation):c.decode(dict(action='game_task',kind='visit',target='D1'),s)
  p=c.decode(dict(action='game_task',kind='visit',target='D1',task_id='T1'),s)
  self.assertEqual(p['task_id'],self.link.active['id'])
 def test_exhausted_internal_travel_is_not_offered_but_new_owner_task_is(self):
  self.link.apply(dict(action='game_task',kind='hide',target=self.link.snapshot()['destinations'][0]['id']),self.link.snapshot(),self.state,self.runtime,2)
  self.link.active.update(attempts=3,phase='needs_review',final_review=True)
  self.link.update(self.runtime,self.state,3);c,s,native=self.contract(internal=True)
  with self.assertRaises(SchemaViolation):c.decode(dict(action='game_task',kind='hide',target='D1',task_id='T1'),s)
  c,s,_=self.contract();self.assertEqual(c.decode(dict(action='game_task',kind='hide',target='D1'),s)['kind'],'hide')
 def test_exhaustion_cannot_be_bypassed_by_internal_kind_switch(self):
  self.link.apply(dict(action='game_task',kind='hide',target=self.link.snapshot()['destinations'][0]['id']),self.link.snapshot(),self.state,self.runtime,2)
  self.link.active.update(attempts=3,phase='needs_review',final_review=True)
  self.link.update(self.runtime,self.state,3);c,s,native=self.contract(internal=True)
  attempts=[dict(kind='visit',target='D1'),dict(kind='hide',target='D1'),dict(kind='follow',target='P1'),dict(kind='approach',target='P1'),dict(kind='move',direction='forward'),dict(kind='hold')]
  for fields in attempts:
   with self.subTest(kind=fields['kind']):
    model=dict(action='game_task',task_id='T1',**fields)
    with self.assertRaises(SchemaViolation):c.decode(model,s)
    native_proposal=dict(model,task_id=self.link.active['id'])
    if 'target' in model:native_proposal['target']=(c.players if fields['kind'] in {'follow','approach'} else c.destinations)[model['target']]
    with self.assertRaisesRegex(ValueError,'retry budget exhausted|settle or cancel'):self.link.apply(native_proposal,native,self.state,self.runtime,4)
  self.assertEqual(self.link.active['attempts'],3);self.assertEqual(self.link.active['phase'],'needs_review')
  # Choosing a new task without T1 remains an owner capability, not a retry bypass.
  c,s,native=self.contract();new=c.decode(dict(action='game_task',kind='hold'),s)
  old=self.link.active['id'];self.assertEqual(self.link.apply(new,native,self.state,self.runtime,4),'accepted')
  self.assertNotEqual(old,self.link.active['id'])
 def test_owner_schema_omits_invalid_exhausted_continuations_not_new_tasks(self):
  self.state['ang']=dict(y=0)
  self.link.apply(dict(action='game_task',kind='hide',target=self.link.snapshot()['destinations'][0]['id']),self.link.snapshot(),self.state,self.runtime,2)
  self.link.active.update(attempts=3,phase='needs_review',final_review=True)
  self.link.update(self.runtime,self.state,3);c,s,native=self.contract()
  for fields in [dict(kind='move',direction='forward'),dict(kind='follow',target='P1'),dict(kind='approach',target='P1'),dict(kind='hold')]:
   p=dict(action='game_task',**fields)
   c.decode(p,s)
   with self.subTest(kind=fields['kind']),self.assertRaises(SchemaViolation):c.decode(dict(p,task_id='T1'),s)
 def test_settle_shape_has_no_target_and_still_requires_fresh_screen(self):
  self.link.apply(dict(action='game_task',kind='hide',target=self.link.snapshot()['destinations'][0]['id']),self.link.snapshot(),self.state,self.runtime,2)
  self.link.active['phase']='needs_review';self.link.update(self.runtime,self.state,3)
  c,s,native=self.contract(internal=True)
  p=dict(action='game_task',kind='settle',task_id='T1',stay_seconds=120)
  with self.assertRaises(SchemaViolation):c.decode(dict(p,target='D1'),s)
  decoded=c.decode(p,s)
  with self.assertRaisesRegex(ValueError,'fresh screen'):self.link.apply(decoded,native,self.state,self.runtime,4)
 def test_budgeted_out_targets_are_not_in_schema(self):
  v=view(8);v['current_task']['id']='f'*32;c=TurnChoices(v);ctx={}
  prompt,ids=bounded_turn_prompt(voice_prefix()+c.hint+'x'*250,'q'*1000,{},[],[],task_view=c.view,decision_context=ctx)
  s=c.schema(ctx['task_view'],{})
  shown={r['id'] for r in ctx['task_view']['destinations']}
  for label in c.destinations:
   p=dict(action='game_task',kind='visit',target=label)
   if label in shown:c.decode(p,s)
   else:
    with self.assertRaises(SchemaViolation):c.decode(p,s)
  self.assertGreaterEqual(6000-len(prompt),200)
 def test_no_navigation_or_players_means_no_travel_schema(self):
  v=dict(navigation_available=False,destinations=[],players=[],current_task=None);c=TurnChoices(v);s=c.schema(c.view,{})
  for k in ['visit','follow','move']:
   with self.assertRaises(SchemaViolation):c.decode(dict(action='game_task',kind=k,target='D1'),s)
 def test_listen_and_inspection_are_only_offered_in_enabled_scope(self):
  c,s,_=self.contract()
  for p in [dict(action='inspect_screen'),dict(action='voice_turn',kind='listen')]:
   with self.assertRaises(SchemaViolation):c.decode(p,s)
  s=c.schema(c.view,{},screen=True,listen=True)
  c.decode(dict(action='inspect_screen'),s);c.decode(dict(action='voice_turn',kind='listen'),s)
  with self.assertRaises(SchemaViolation):c.decode(dict(action='inspect_screen'),without_inspection(s))
 def test_citations_and_numeric_bounds_are_checked_locally(self):
  c,_,_=self.contract();s=c.schema(c.view,{},memory_ids=['real'])
  for reply in [dict(say='hi',intent=None,used_memory_ids=['invented']),dict(say='hi',intent=dict(action='game_task',kind='hold',stay_seconds=999),used_memory_ids=[])]:
   with self.assertRaises(SchemaViolation):validate(reply,s)

class ProviderContract(unittest.TestCase):
 def schema(self):return envelope([dict(type='null')])
 def test_local_schema_is_sent_as_request_setting_not_system_authority(self):
  seen=[]
  def post(url,**kw):
   seen.append(kw['json']);return SimpleNamespace(raise_for_status=lambda:None,json=lambda:dict(choices=[dict(finish_reason='stop',message=dict(content=json.dumps(dict(say='hi',intent=None,used_memory_ids=[]))))]))
  p=LMStudioProvider('http://127.0.0.1:1234/v1/chat/completions','fixture')
  schema=self.schema()
  with patch('greg_model.post_chat',side_effect=post):p.generate_constrained(dict(persona='Gregory',goals=[]),'hi',response_schema=schema)
  self.assertEqual(seen[0]['response_format']['json_schema']['schema'],schema)
  self.assertIs(seen[0]['response_format']['json_schema']['strict'],True)
 def test_bad_schema_reply_fails_without_unconstrained_retry(self):
  calls=[]
  def post(url,**kw):
   calls.append(kw['json']);return SimpleNamespace(raise_for_status=lambda:None,json=lambda:dict(choices=[dict(finish_reason='stop',message=dict(content=json.dumps(dict(say='hi',intent=dict(action='bad'),used_memory_ids=[]))))]))
  p=LMStudioProvider('http://127.0.0.1:1234/v1/chat/completions','fixture')
  with patch('greg_model.post_chat',side_effect=post),self.assertRaises(ValueError):p.generate_constrained(dict(persona='Gregory',goals=[]),'hi',response_schema=self.schema())
  self.assertEqual(len(calls),1);self.assertIn('response_format',calls[0])
 def test_constrained_screen_followup_still_requires_explicit_game_scope(self):
  from gregory_core.screen import generate_with_screen
  replies=[dict(say='Looking.',intent=dict(action='inspect_screen'),used_memory_ids=[]),dict(say='Waiting.',intent=dict(action='game_task',kind='hold'),used_memory_ids=[])]
  class P(FixtureProvider):
   def generate(self,profile,prompt,**kw):return replies.pop(0)
  schema=envelope([dict(type='null'),obj(dict(action=enum(['inspect_screen']))),obj(dict(action=enum(['game_task']),kind=enum(['hold'])))])
  source=SimpleNamespace(inspect=lambda session:(None,dict(status='unavailable')));receipts=[]
  reply=generate_with_screen(P(),{},'hi',source,'s',time.monotonic()+2,receipts,allow_game_task=False,response_schema=schema)
  self.assertIsNone(reply.get('intent'));self.assertTrue(receipts[0]['followup_intent_discarded'])
 def test_unsupported_provider_does_not_silently_generate_plain_text(self):
  p=SimpleNamespace(generate=lambda *a:self.fail('unconstrained fallback'))
  with self.assertRaises(SchemaViolation):generate(p,{},'hi',response_schema=self.schema())

if __name__=='__main__':unittest.main()
