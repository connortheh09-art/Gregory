from pathlib import Path
import sys,tempfile,unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'deployments/oldpc')]
from gregory_core.runtime import Core,FixtureProvider
CFG=dict(bot_id='1563299893014036550',users=['1200889100379639899'],after_id='100')
S=dict(bot_id=CFG['bot_id'],channel_id='200',peer_id=CFG['users'][0])
TURN=dict(bot_id=S['bot_id'],channel_id=S['channel_id'],author_id=S['peer_id'],surface='dm')
class Provider(FixtureProvider):
 def __init__(self):self.prompts=[]
 def generate(self,profile,prompt):self.prompts.append(prompt);return dict(say='fixture',used_memory_ids=[])
class Pins(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'core';self.provider=Provider();self.start();self.addCleanup(self.stop)
  self.core.call('inbox',dict(S,operation='bind'))
  self.batch('101','My name is Connor. I am your creator.')
 def start(self):self.core=Core(self.root,provider=self.provider,inbox_config=CFG).start()
 def stop(self):
  if self.core.accepting:self.core.call('stop')
  self.core.thread.join(5)
 def batch(self,mid,text):return self.core.call('inbox',dict(S,operation='batch',messages=[dict(message_id=mid,author_id=S['peer_id'],content=text)]))
 def pin(self,**kw):return self.core.call('pin_inbox',dict(S,label='creator_identity',message_id='101',expected_revision=0,authorization_message_id='900',**kw))
 def test_old_source_survives_tail_expiry_restart_and_reaches_private_provider(self):
  result=self.pin();self.assertEqual(result['revision'],1)
  for n in range(102,113):self.batch(str(n),'Later conversation')
  self.stop();self.start();self.core.call('think',dict(prompt='Who created you?',inbox_scope=TURN))
  self.assertIn('My name is Connor. I am your creator.',self.provider.prompts[-1])
  self.assertIn('PRIVATE_PINNED_RECORDS_JSON',self.provider.prompts[-1])
 def test_no_pin_in_public_prompt(self):
  self.pin();self.core.call('think',dict(prompt='Public hello',metadata_only=True))
  self.assertNotIn('My name is Connor',self.provider.prompts[-1])
 def test_duplicate_pin_is_idempotent(self):
  self.pin();self.assertTrue(self.pin()['duplicate'])
 def test_stale_revision_cannot_replace(self):
  self.pin();self.batch('102','Corrected source')
  p=dict(S,label='creator_identity',message_id='102',expected_revision=0,authorization_message_id='901')
  with self.assertRaises(ValueError):self.core.call('pin_inbox',p)
  p['expected_revision']=1;self.assertEqual(self.core.call('pin_inbox',p)['revision'],2)
 def test_wrong_peer_and_missing_source_refused(self):
  p=dict(S,label='creator_identity',message_id='101',expected_revision=0,authorization_message_id='900')
  with self.assertRaises(PermissionError):self.core.call('pin_inbox',dict(p,peer_id='999'))
  with self.assertRaises(ValueError):self.core.call('pin_inbox',dict(p,message_id='999'))
 def test_pin_does_not_create_episodic_memory(self):
  before=self.core.call('lookup',dict(query='Connor',metadata_only=True))
  self.pin();after=self.core.call('lookup',dict(query='Connor',metadata_only=True))
  self.assertEqual(before['hits'],after['hits'])
if __name__=='__main__':unittest.main()
