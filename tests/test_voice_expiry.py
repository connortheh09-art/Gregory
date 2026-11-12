"""Expiry closes new admissions but lets committed audio finish within grace."""
from pathlib import Path
import sys,time,unittest,uuid
from types import SimpleNamespace
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'deployments/oldpc')]
from greg_voice_session import VoiceSession,VoiceRefused
from greg_supervised import drain_pending,SessionWindow

class PlaybackExpiryTests(unittest.TestCase):
 def setUp(self):
  self.config=dict(owner_id='1001',guild_id='2001',channel_id='3001',game_name='fixture')
  self.voice=VoiceSession(self.config,'STEAM_0:1:1000')
  r=self.voice.call('connect',{k:self.config[k] for k in ('guild_id','channel_id')})
  self.scope={k:r[k] for k in ('connection','generation')}
  self.lane=SimpleNamespace(queue=[],ready=None,delivery=self.voice)
  self.window=SessionWindow(0,1200)
  self.assertTrue(self.voice.offer(dict(request=dict(delivery_stamp=self.voice.stamp()),say='fixture audio')))
  self.reply=self.voice.replies[0]['reply_id']
 def pending(self):return drain_pending(SimpleNamespace(pending=0),self.lane,None,None)
 def playback(self,state):return self.voice.call('playback',dict(self.scope,reply_id=self.reply,state=state))
 def turn(self,text):return self.voice.call('turn',dict(self.scope,request_id=str(uuid.uuid4()),author_id='1001',is_bot=False,text=text,captured_at=self.voice.clock()))
 def test_active_audio_prevents_early_expiry_then_completion_drains(self):
  self.playback('started');self.voice.begin_drain()
  self.assertEqual(self.pending(),1)
  self.assertEqual(self.window.phase(1200,self.pending()),'draining')
  self.playback('completed')
  self.assertEqual(self.window.phase(1203,self.pending()),'drained')
 def test_tts_queued_before_expiry_also_counts(self):
  self.voice.begin_drain();self.assertEqual(self.pending(),1)
  self.assertEqual(self.window.phase(1201,self.pending()),'draining')
 def test_new_chat_refused_but_stop_remains_immediate(self):
  self.playback('started');self.voice.begin_drain()
  with self.assertRaises(VoiceRefused):self.turn('keep talking')
  self.turn('Stop.');self.assertEqual(self.voice.pending_playback,0)
 def test_audio_never_makes_the_grace_period_unbounded(self):
  self.playback('started');self.voice.begin_drain()
  self.assertEqual(self.window.phase(1235,self.pending()),'expired')
 def test_expired_tunnel_lease_does_not_hold_drain_open(self):
  self.voice.begin_drain();clock=self.voice.clock;self.voice.clock=lambda:clock()+11
  self.assertEqual(self.pending(),0)

if __name__=='__main__':unittest.main()
