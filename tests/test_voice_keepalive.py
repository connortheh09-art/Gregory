"""Transport reuse must not replay accepted non-idempotent operations."""
from pathlib import Path
import sys,time,unittest
from unittest.mock import patch
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deployments/oldpc'))
from greg_voice_session import VoiceSession,VoiceServer
from greg_voice_client import VoiceHTTP
CONFIG=dict(owner_id='1001',guild_id='2001',channel_id='3001',game_name='Connor')

class KeepaliveTests(unittest.TestCase):
 def setUp(self):
  self.host=VoiceSession(CONFIG,'STEAM_0:1:1000')
  self.server=VoiceServer(self.host).start();self.addCleanup(self.server.close)
  self.transport=VoiceHTTP(self.server.receipt());self.addCleanup(self.transport.close)
  self.count=0;original=self.server.server.get_request
  def accepted():
   value=original();self.count+=1;return value
  self.server.server.get_request=accepted
  r=self.transport('connect',{k:CONFIG[k] for k in ('guild_id','channel_id')})
  self.scope={k:r[k] for k in ('connection','generation')}
 def test_hundred_polls_reuse_exactly_one_connection(self):
  for _ in range(100):self.transport('poll',self.scope)
  self.assertEqual(self.count,1)
 def test_refusal_closes_socket_without_automatic_connect_replay(self):
  with self.assertRaises(HTTPError):self.transport('poll',dict(self.scope,connection='invalid'))
  self.assertIsNone(self.transport.connection)
  self.assertEqual(self.count,1)
  r=self.transport('poll',self.scope)
  self.assertEqual(r['connection'],self.scope['connection']);self.assertEqual(self.count,2)
 def test_lost_response_never_replays_an_accepted_operation(self):
  generation=self.host.generation
  with patch.object(self.transport.connection,'getresponse',side_effect=ConnectionError('lost reply')):
   with self.assertRaises(ConnectionError):self.transport('interrupt',self.scope)
  deadline=time.monotonic()+1
  while self.host.generation==generation and time.monotonic()<deadline:time.sleep(.01)
  self.assertEqual(self.host.generation,generation+1)
  self.assertEqual(self.count,1);self.assertIsNone(self.transport.connection)
 def test_reconnect_with_new_socket_preserves_generation_and_scope(self):
  self.transport.close()
  r=self.transport('poll',self.scope)
  self.assertEqual(r['generation'],self.scope['generation']);self.assertEqual(self.count,2)

if __name__=='__main__':unittest.main()
