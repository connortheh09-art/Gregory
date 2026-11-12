from pathlib import Path
import json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gregory_core.runtime import Core,FixtureProvider
CFG=dict(bot_id='1563299893014036550',users=['1200889100379639899'],after_id='100')
SCOPE=dict(bot_id=CFG['bot_id'],channel_id='200',peer_id=CFG['users'][0])
TURN=dict(bot_id=CFG['bot_id'],channel_id='200',author_id=CFG['users'][0],surface='dm')
class Provider(FixtureProvider):
 def __init__(self):self.prompts=[]
 def generate(self,profile,prompt):
  self.prompts.append(prompt)
  return dict(say='private-keyword-zebra',intent={'action':'must_not_dispatch'},used_memory_ids=[])
class ContextTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.provider=Provider();self.core=Core(Path(self.temp.name)/'core',provider=self.provider,inbox_config=CFG).start();self.addCleanup(self.stop)
  self.core.call('inbox',dict(SCOPE,operation='bind'))
  self.core.call('inbox',dict(SCOPE,operation='batch',messages=[dict(message_id='101',author_id=SCOPE['peer_id'],content='private-keyword-zebra')]))
 def stop(self):
  if self.core.accepting:self.core.call('stop')
  self.core.thread.join(5)
 def test_real_core_think_injects_private_data_and_discards_intent(self):
  result=self.core.call('think',dict(prompt='What did I DM?',inbox_scope=TURN))
  self.assertIn('private-keyword-zebra',self.provider.prompts[0]);self.assertIn('untrusted',self.provider.prompts[0]);self.assertNotIn('intent',result)
  self.assertFalse(result['dispatched'])
 def test_public_turn_has_no_inbox(self):
  self.core.call('think',dict(prompt='Hello in public',metadata_only=True))
  self.assertNotIn('private-keyword-zebra',self.provider.prompts[0])
 def test_wrong_author_channel_bot_and_vc_never_call_provider(self):
  for bad in [dict(TURN,author_id='999'),dict(TURN,channel_id='999'),dict(TURN,bot_id='999'),dict(TURN,surface='vc')]:
   with self.assertRaises(PermissionError):self.core.call('think',dict(prompt='What did I DM?',inbox_scope=bad))
  self.assertEqual(self.provider.prompts,[])
 def test_private_say_not_in_journal(self):
  self.core.call('think',dict(prompt='What did I DM?',inbox_scope=TURN))
  import sqlite3
  from contextlib import closing
  with closing(sqlite3.connect(self.core.root/'core.sqlite3')) as db:
   events=' '.join(x[0] for x in db.execute('SELECT payload FROM events'))
  self.assertNotIn('private-keyword-zebra',events)
  self.assertIn('inbox_message_ids',events)
 def test_context_budget(self):
  for i in range(102,110):self.core.call('inbox',dict(SCOPE,operation='batch',messages=[dict(message_id=str(i),author_id=SCOPE['peer_id'],content='x'*2000)]))
  self.core.call('think',dict(prompt='q'*1600,inbox_scope=TURN))
  self.assertLessEqual(len(self.provider.prompts[0]),14000)
if __name__=='__main__':unittest.main()
