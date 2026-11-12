from pathlib import Path
import sys,tempfile,unittest,json
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'deployments/oldpc')]
from gregory_core.runtime import Core,FixtureProvider
from gregory_core.inbox import turn_context
CFG=dict(bot_id='1563299893014036550',users=['1200889100379639899'],after_id='100')
S=dict(bot_id=CFG['bot_id'],channel_id='200',peer_id=CFG['users'][0])
TURN=dict(bot_id=S['bot_id'],channel_id=S['channel_id'],author_id=S['peer_id'],surface='dm')
class Provider(FixtureProvider):
 def __init__(self):self.prompts=[]
 def generate(self,profile,prompt):self.prompts.append(prompt);return dict(say='fixture',used_memory_ids=[])
class Window(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.provider=Provider()
  self.core=Core(Path(self.tmp.name)/'core',provider=self.provider,inbox_config=CFG,
    inbox_voice_authorizer=lambda claim:dict(author_id=S['peer_id'])).start();self.addCleanup(self.stop)
  self.core.call('inbox',dict(S,operation='bind'))
 def stop(self):
  if self.core.accepting:self.core.call('stop')
  self.core.thread.join(5)
 def add(self,mid,text):self.core.call('inbox',dict(S,operation='batch',messages=[dict(message_id=str(mid),author_id=S['peer_id'],content=text)]))
 def test_discussion_outside_old_eight_is_available_now(self):
  self.add(101,'We discussed the GMod jeep and airboat.')
  for mid in range(102,121):self.add(mid,'Later topic '+str(mid))
  self.core.call('think',dict(prompt='What did we discuss about GMod?',inbox_scope=TURN))
  self.assertIn('GMod jeep and airboat',self.provider.prompts[-1])
 def test_window_is_bounded_to_latest_twenty_four(self):
  for mid in range(101,131):self.add(mid,'topic-'+str(mid))
  context=self.core.call('inbox',dict(S,operation='context',surface='dm'))
  self.assertEqual([m['message_id'] for m in context['messages']],[str(n) for n in range(107,131)])
 def test_large_private_history_fits_but_public_cap_unchanged(self):
  for mid in range(101,126):self.add(mid,'x'*1900)
  self.core.call('think',dict(prompt='q'*1600,inbox_scope=TURN))
  self.assertGreater(len(self.provider.prompts[-1]),6000)
  self.assertLessEqual(len(self.provider.prompts[-1]),14000)
  count=len(self.provider.prompts)
  with self.assertRaises(ValueError):self.core.call('think',dict(prompt='x'*6001,metadata_only=True))
  self.assertEqual(len(self.provider.prompts),count)
 def test_old_pin_kept_even_outside_twenty_four_and_history_budget(self):
  self.add(101,'My name is Connor, your creator.')
  self.core.call('pin_inbox',dict(S,label='creator_identity',message_id='101',expected_revision=0,authorization_message_id='900'))
  for mid in range(102,135):self.add(mid,'y'*1600)
  self.core.call('think',dict(prompt='Who am I?',inbox_scope=TURN))
  self.assertIn('My name is Connor',self.provider.prompts[-1])
  self.assertLessEqual(len(self.provider.prompts[-1]),14000)
 def test_explicit_voice_builder_retains_smaller_existing_budget(self):
  for mid in range(101,120):self.add(mid,'v'*600)
  self.core.call('think',dict(prompt='What did I DM?',inbox_voice_claim='fixture-voice-grant-1234567890'))
  prompt=self.provider.prompts[-1]
  selected,_=json.JSONDecoder().raw_decode(prompt.split('PRIVATE_INBOX_DATA_JSON: ',1)[1])
  self.assertLessEqual(len(prompt),6000);self.assertLessEqual(len(selected),8)
 def test_private_history_does_not_enter_unscoped_turn(self):
  self.add(101,'private-needle-jellyfish')
  self.core.call('think',dict(prompt='Public hello',metadata_only=True))
  self.assertNotIn('private-needle-jellyfish',self.provider.prompts[-1])
if __name__=='__main__':unittest.main()
