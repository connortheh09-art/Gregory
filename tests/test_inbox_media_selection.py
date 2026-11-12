import sqlite3,unittest,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'deployments/oldpc')]
from gregory_core.inbox_media import images_for_turn
class MediaSelection(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
  self.db.executescript('CREATE TABLE inbox_messages(bot_id,channel_id,peer_id,message_id); CREATE TABLE inbox_attachments(bot_id,channel_id,peer_id,message_id,status);')
  self.scope=dict(bot_id='1',channel_id='2',author_id='3');self.core=SimpleNamespace(db=self.db,inbox_config={'media_enabled':True})
 def add(self,mid,status=None):
  self.db.execute('INSERT INTO inbox_messages VALUES(?,?,?,?)',('1','2','3',mid))
  if status:self.db.execute('INSERT INTO inbox_attachments VALUES(?,?,?,?,?)',('1','2','3',mid,status))
 def test_failed_latest_upload_cannot_reuse_older_screenshot(self):
  self.add('100','ready');self.add('101','failed')
  with patch('gregory_core.inbox_media.read_preview') as read:
   self.assertEqual(images_for_turn(self.core,self.scope),([],[]));read.assert_not_called()
 def test_old_screenshot_outside_current_tail_not_attached_to_new_chat(self):
  self.add('100','ready')
  for n in range(101,110):self.add(str(n))
  with patch('gregory_core.inbox_media.read_preview') as read:
   self.assertEqual(images_for_turn(self.core,self.scope),([],[]));read.assert_not_called()
if __name__=='__main__':unittest.main()
