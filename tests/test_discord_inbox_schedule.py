import asyncio,importlib.util,json
from pathlib import Path
from types import SimpleNamespace
import unittest
spec=importlib.util.spec_from_file_location('inbox_runner',Path(__file__).resolve().parents[1]/'tools/gregory_discord_inbox.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
class ScheduledTests(unittest.IsolatedAsyncioTestCase):
 async def test_oldest_first_paging_and_restart_cursor(self):
  class Sink:
   cursor='100'
   calls=[]
   def call(self,p):
    self.calls.append(p)
    if p['operation']=='bind':return dict(cursor=self.cursor)
    self.cursor=p['messages'][-1]['message_id']
    return dict(cursor=self.cursor,inserted=len(p['messages']),duplicates=0,correlation_ids=[])
  class Channel:
   id=200
   async def history(self,limit,after,oldest_first):
    assert oldest_first and limit==25
    for mid in range(max(101,after.id+1),137):
     if mid>=after.id+1+limit:break
     yield SimpleNamespace(id=mid,author=SimpleNamespace(id=300),content='data',guild=None,webhook_id=None)
  sink=Sink();self.assertEqual(await r.check_channel(sink,Channel(),'400','300'),36)
  self.assertEqual(await r.check_channel(sink,Channel(),'400','300'),0)
  self.assertEqual(sink.cursor,'136')
 async def test_failed_commit_does_not_advance_cursor(self):
  class Sink:
   def call(self,p):
    if p['operation']=='bind':return dict(cursor='100')
    raise ConnectionError('transport down')
  class Channel:
   id=200
   async def history(self,**kw):yield SimpleNamespace(id=101,author=SimpleNamespace(id=300),content='data',guild=None,webhook_id=None)
  with self.assertRaises(ConnectionError):await r.check_channel(Sink(),Channel(),'400','300')
 def test_transport_rejects_nonloopback(self):
  for url in ['http://192.168.1.2:18667','https://127.0.0.1:18667','http://127.0.0.1:18667/api']:
   with self.assertRaises(ValueError):r.Intake(dict(url=url,capability='x'))
