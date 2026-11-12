import unittest,sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'deployments/oldpc')]
from greg_supervised import reply_surface

class ReplySurfaceTests(unittest.TestCase):
 def test_game_chat_not_redirected_to_configured_but_disconnected_voice(self):
  self.assertEqual(reply_surface({'request':{'kind':'chat','delivery_stamp':(None,0)}},True),'game')
 def test_voice_turn_stays_voice(self):
  self.assertEqual(reply_surface({'request':{'kind':'chat','voice_metadata':{'author_id':'1001'}}},True),'voice')
 def test_private_turn_never_falls_back_to_game(self):
  for configured in (False,True):
   self.assertEqual(reply_surface({'request':{'kind':'chat','inbox_voice_claim':'fixture'}},configured),'voice' if configured else 'unavailable')
 def test_missing_voice_does_not_leak_voice_turn_into_game(self):
  self.assertEqual(reply_surface({'request':{'kind':'chat','voice_metadata':{'author_id':'1001'}}},False),'unavailable')
 def test_existing_sensor_delivery_unchanged(self):
  for configured in (False,True):
   self.assertEqual(reply_surface({'request':{'kind':'sensor'}},configured),'voice' if configured else 'game')
 def test_game_inspect_returns_to_game_despite_voice_configuration(self):
  self.assertEqual(reply_surface({'request':{'kind':'sensor','output_surface':'game'}},True),'game')
 def test_voice_inspect_never_falls_back_to_public_game(self):
  self.assertEqual(reply_surface({'request':{'kind':'sensor','output_surface':'voice'}},False),'unavailable')
 def test_private_claim_cannot_be_overridden_by_game_surface(self):
  self.assertEqual(reply_surface({'request':{'kind':'chat','inbox_voice_claim':'fixture','output_surface':'game'}},True),'voice')
