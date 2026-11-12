"""Full voice/task budgeting: protect actionable identity and latest owner input."""
import ast,copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
from greg_supervised import bounded_turn_prompt
from greg_game_tasks import GameTasks

def voice_prefix():
 tree=ast.parse((ROOT/'deployments/oldpc/greg_supervised.py').read_text())
 parts={}
 for node in ast.walk(tree):
  if isinstance(node,ast.Assign) and isinstance(node.value,ast.IfExp):
   for target in node.targets:
    if isinstance(target,ast.Name) and target.id in ('spoken_style','capabilities','attention'):
     parts[target.id]=ast.literal_eval(node.value.body)
 assert len(parts)==3
 return ''.join(parts.values())

def view(players=1):
 return dict(binding=['gm_bigcity_improved_rp','s'*32,1],revision=30,navigation_available=True,heading=75,
  current_task=dict(id='task-exact',kind='follow',objective='h'*240,phase='travelling',target=dict(id='0'*16,position=[10000,-10000,0]),version=30,completion='arrival',attempts=2,feedback='b'*160),
  last_outcome=dict(status='refused',reason='old reason',proposal={'detail':'x'*1000}),
  last_refusal=dict(id='r'*32,reason='unoffered destination',target='old-target',automatic_recovery=False),
  current_position=[10000,-10000,0],destinations=[dict(id='destination-'+str(i),position=[10000,-10000,0],distance=500,bearing_relative=45*i,cover='unverified') for i in range(8)],
  players=[dict(id=str(i)*16,name='名'*64,position=[10000,-10000,0],is_owner=i==0) for i in range(players)])

class VoiceBudget(unittest.TestCase):
 def build(self,v,question='question '*110,internal=False):
  live=dict(recent=[{'event':'x'*500}]*4,server_observations={'events':'e'*1000},last_spawn_request={'status':'written_not_confirmed','command':'s'*300},activity_options={'binding':['map','session',1],'spawn_choices':[]})
  before=copy.deepcopy((v,live))
  prompt,ids=bounded_turn_prompt(voice_prefix(),question,live,[],[],task_view=v,internal=internal)
  self.assertEqual((v,live),before)
  self.assertLessEqual(len(prompt),6000);self.assertIn(question,prompt)
  task=json.loads(prompt.split('GAME TASK CONTEXT:',1)[1].split('\nReturn ONE JSON',1)[0])
  self.assertEqual(task['binding'],v['binding']);self.assertEqual(task['revision'],30)
  self.assertEqual(task['current_task']['id'],v['current_task']['id'])
  self.assertEqual(task['current_task']['kind'],'follow')
  self.assertIn('pick an offered destination ID yourself now (visit)',prompt)
  self.assertEqual({k:value for k,value in task['last_refusal'].items() if k!='id'}, {k:value for k,value in v['last_refusal'].items() if k!='id'})
  self.assertTrue(task['destinations']);self.assertTrue(set(x['id'] for x in task['destinations'])<=set(x['id'] for x in v['destinations']))
  self.assertEqual([x['id'] for x in task['players']],[x['id'] for x in v['players']])
  self.assertIn('VOICE FLOOR:',prompt)
  self.assertGreaterEqual(6000-len(prompt),200,'full voice/task prompt must retain 200-character headroom')
  self.assertEqual([x['id'] for x in task['players'] if x.get('is_owner') is True],[x['id'] for x in v['players'] if x.get('is_owner') is True])
  return prompt,task
 def test_full_voice_active_task_and_max_owner_turn_fit(self):self.build(view(),question='q'*1000)
 def test_eight_players_keep_identity_when_budgeting(self):self.build(view(8),question='q'*1000)
 def test_full_refusal_and_active_objective_remain_while_old_diagnostics_evict(self):
  v=view(8);v['last_refusal'].update(reason='r'*120,target='t'*80);v['current_task']['id']='x'*32
  # Use the same semantic contract with a realistic UUID.
  prompt,task=self.build(v,question='q'*1000)
  self.assertEqual(task['current_task']['objective'],v['current_task']['objective'])
 def test_internal_continuation_keeps_exact_task_id(self):
  prompt,task=self.build(view(),internal=True)
  self.assertIn('"task_id":"task-exact"',prompt)
 def test_oversized_critical_instructions_fail_closed(self):
  with self.assertRaisesRegex(ValueError,'essential game context'):
   bounded_turn_prompt('x'*6000,'q',{},[],[],task_view=view())
 def test_small_context_keeps_optional_receipts(self):
  p,_=bounded_turn_prompt('p','q',{'recent':[{'id':'recent'}],'last_spawn_request':{'id':'spawn'}},[],[])
  self.assertIn('recent',p);self.assertIn('spawn',p)

if __name__=='__main__':unittest.main()
