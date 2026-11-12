"""Limit autonomous rest decisions, not controller waits or owner stays."""
from pathlib import Path
import sys,unittest
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
from greg_agenda import Agenda
from greg_supervised import CoreGameAuthority,CoreTurnDeferred
from gregory_core.decision_contract import activity_intents,envelope,validate,SchemaViolation
class RestBudget(unittest.TestCase):
 def setUp(self):
  self.state=dict(map='map',bridgeSession='session',controlEpoch=1)
  self.catalog=SimpleNamespace(describe=lambda s:[],choices=lambda s,**kw:[],observations=lambda s:[],entries=lambda s:([],{}))
  self.agenda=Agenda(self.catalog,'unused','unused')
 def result(self,kind='rest',autonomous=True):return dict(choice=dict(activity=kind),context=tuple(self.state.values()),autonomous=autonomous,navigation_available=True)
 def rest(self):return self.agenda.accept(self.result(),self.state,10)
 def exhaust(self):
  for _ in range(3):self.rest()
 def test_three_rests_then_native_fourth_refused(self):
  self.exhaust();before=list(self.agenda.recent)
  with self.assertRaisesRegex(ValueError,'rest budget exhausted'):self.rest()
  self.assertEqual(list(self.agenda.recent),before)
 def test_explicit_owner_rest_allowed(self):
  self.exhaust();self.assertEqual(self.agenda.accept(self.result(autonomous=False),self.state,20)[0],{'action':'wait'})
  self.assertFalse(self.agenda.recent[-1]['autonomous'])
 def test_stale_world_result_does_not_consume_budget(self):
  for _ in range(2):self.rest()
  stale=self.result();stale['context']=('old','old',0);self.agenda.accept(stale,self.state,20)
  self.rest();self.assertFalse(self.agenda.autonomous_rest_available(self.state))
 def test_world_change_resets_budget(self):
  self.exhaust();self.state['controlEpoch']=2;self.assertTrue(self.agenda.autonomous_rest_available(self.state));self.rest();self.assertEqual(len(self.agenda.recent),1)
 def test_controller_polling_does_not_consume_budget(self):
  for _ in range(1000):self.assertTrue(self.agenda.autonomous_rest_available(self.state))
  self.exhaust();self.assertFalse(self.agenda.autonomous_rest_available(self.state))
 def test_nonrest_choice_resets_streak(self):
  self.exhaust();self.agenda.accept(self.result('browse'),self.state,20);self.assertTrue(self.agenda.autonomous_rest_available(self.state));self.rest()
 def test_invalid_tour_does_not_reset_streak(self):
  self.exhaust();bad=self.result('tour');bad['choice']['landmark']='not offered';self.agenda.accept(bad,self.state,20);self.assertFalse(self.agenda.autonomous_rest_available(self.state))
 def test_background_schema_removes_rest_keeps_nontravel(self):
  schema=envelope(activity_intents(dict(autonomous_rest_available=False,navigation_available=False)))
  validate(dict(say='Browse.',intent=dict(action='game_activity',choice=dict(activity='browse',query='props',kind='')),used_memory_ids=[]),schema)
  with self.assertRaises(SchemaViolation):validate(dict(say='Rest.',intent=dict(action='game_activity',choice=dict(activity='rest')),used_memory_ids=[]),schema)
 def test_owner_schema_and_validation_unchanged(self):
  schema=envelope(activity_intents({}));proposal=dict(action='game_activity',choice=dict(activity='rest'));validate(dict(say='Rest.',intent=proposal,used_memory_ids=[]),schema)
  a=CoreGameAuthority(None);self.assertEqual(a.validate_activity(proposal,dict(binding=list(self.state.values())),self.state)['choice'],dict(activity='rest'))
 def test_actual_agenda_core_path_filters_schema(self):
  calls=[]
  def call(op,payload,**kw):calls.append(payload);return dict(say='Browse.',intent=dict(action='game_activity',choice=dict(activity='browse',query='props',kind='')),used_memory_ids=[])
  a=CoreGameAuthority(SimpleNamespace(call=call));a.reset_world(self.state);self.agenda.core_decider=a.decide_activity;self.exhaust()
  out=self.agenda.decide(self.state,[]);self.assertTrue(out['autonomous']);self.assertEqual(out['choice']['activity'],'browse')
  with self.assertRaises(SchemaViolation):validate(dict(say='Rest.',intent=dict(action='game_activity',choice=dict(activity='rest')),used_memory_ids=[]),calls[0]['response_schema'])
  self.agenda.accept(out,self.state,20);self.assertTrue(self.agenda.autonomous_rest_available(self.state))
 def test_busy_foreground_does_not_spend_budget(self):
  a=CoreGameAuthority(SimpleNamespace(call=lambda *args,**kw:self.fail('background model call')));a.reset_world(self.state);a.foreground_pending=lambda:True;self.agenda.core_decider=a.decide_activity
  for _ in range(2):self.rest()
  with self.assertRaises(CoreTurnDeferred):self.agenda.decide(self.state,[])
  self.rest();self.assertFalse(self.agenda.autonomous_rest_available(self.state))
if __name__=='__main__':unittest.main()
