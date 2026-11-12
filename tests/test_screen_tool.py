import base64
import io
from pathlib import Path
import sys
import tempfile
import time
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
from PIL import Image
from gregory_core.screen import ScreenBuffer,CaptureLoop,generate_with_screen
from gregory_core.runtime import Core,FixtureProvider

class Provider(FixtureProvider):
 def __init__(self, replies):self.replies=list(replies);self.calls=[]
 def generate(self,profile,prompt,**kw):
  self.calls.append((prompt,kw));return self.replies.pop(0)
def answer(say='fixture',intent=None):
 r=dict(say=say,used_memory_ids=[])
 if intent is not None:r['intent']=intent
 return r
LOOK=answer('provisional, never publish',dict(action='inspect_screen'))

class ScreenTests(unittest.TestCase):
 def setUp(self):
  self.now=10.;self.buffer=ScreenBuffer('oldpc-game','session-1',clock=lambda:self.now)
 def publish(self,color='red'):
  return self.buffer.publish(Image.new('RGB',(100,100),color),1000+self.now,self.now)
 def run_tool(self,replies):
  p=Provider(replies);receipts=[]
  result=generate_with_screen(p,{},'What shall I do next?',self.buffer,'session-1',time.monotonic()+5,receipts)
  return result,p,receipts
 def test_selected_frame_label_matches_capture_in_est(self):
  from datetime import datetime,timezone
  self.buffer=ScreenBuffer('oldpc','s',game='gmod',clock=lambda:self.now)
  meta=self.buffer.publish(Image.new('RGB',(10,10)),datetime(2026,11,5,1,2,3,tzinfo=timezone.utc).timestamp(),self.now)
  image,selected=self.buffer.inspect('s')
  self.assertTrue(selected['display_name'].startswith('2026-11-04_20-02-03-000000_EST_gmod_'))
  self.assertIn(meta['frame_id'],selected['display_name'])
  self.assertEqual(self.buffer.inspect('s')[1]['display_name'],selected['display_name'])
 def test_model_can_decline_without_accessing_frames(self):
  self.publish();result,p,r=self.run_tool([answer('Keep walking.')])
  self.assertEqual(result['say'],'Keep walking.');self.assertEqual(len(p.calls),1)
  self.assertEqual(p.calls[0][1],{});self.assertEqual(r,[])
 def test_model_selected_read_passes_exact_latest_image(self):
  self.publish('red');meta=self.publish('blue')
  result,p,r=self.run_tool([LOOK,answer('Blue view.')])
  self.assertEqual(result['say'],'Blue view.');self.assertEqual(p.calls[0][1],{})
  data=base64.b64decode(p.calls[1][1]['images'][0].split(',')[1])
  import hashlib
  self.assertEqual(hashlib.sha256(data).hexdigest(),meta['sha256'])
  self.assertGreater(Image.open(io.BytesIO(data)).getpixel((10,10))[2],200)
  self.assertEqual(r[0]['status'],'ready');self.assertEqual(r[0]['session'],'session-1')
 def test_expired_frame_never_reused(self):
  self.publish();self.now+=4
  result,p,r=self.run_tool([LOOK,answer('Could not get a fresh look.')])
  self.assertEqual(r[0]['status'],'unavailable');self.assertEqual(p.calls[1][1],{})
 def test_clock_reversal_fails_closed(self):
  self.publish();self.now-=1
  self.assertEqual(self.buffer.inspect('session-1')[1]['status'],'unavailable')
 def test_wrong_session_refused(self):
  self.publish()
  with self.assertRaises(ValueError):self.buffer.inspect('other')
 def test_stale_publish_refused(self):
  with self.assertRaises(ValueError):self.buffer.publish(Image.new('RGB',(5,5)),1010,5)
 def test_capacity_and_byte_budget(self):
  self.buffer=ScreenBuffer('oldpc','s',capacity=3,byte_limit=10000,clock=lambda:self.now)
  for _ in range(40):self.publish()
  self.assertLessEqual(len(self.buffer.frames),3)
  self.assertLessEqual(sum(len(r[0]) for r in self.buffer.frames),10000)
 def test_inflight_copy_survives_eviction(self):
  self.publish();image,meta=self.buffer.inspect('session-1');self.buffer.invalidate()
  self.assertTrue(image.startswith('data:image/jpeg;base64,'))
  self.assertEqual(self.buffer.inspect('session-1')[1]['status'],'unavailable')
 def test_closed_capture_cannot_publish_late_frame(self):
  self.publish();self.buffer.close()
  with self.assertRaises(ValueError):self.publish()
  self.assertEqual(self.buffer.inspect('session-1')[1]['status'],'unavailable')
 def test_followup_action_is_discarded_never_executed(self):
  self.publish()
  result,p,r=self.run_tool([LOOK,answer('A view.',dict(action='move',direction='forward'))])
  self.assertNotIn('intent',result);self.assertTrue(r[0]['followup_intent_discarded'])
 def test_second_tool_is_refused(self):
  self.publish()
  with self.assertRaises(ValueError):self.run_tool([LOOK,LOOK])
 def test_expired_turn_does_not_start_image_inference(self):
  p=Provider([LOOK]);r=[]
  with self.assertRaises(TimeoutError):generate_with_screen(p,{},'q',self.buffer,'session-1',0,r)
  self.assertEqual(len(p.calls),0);self.assertEqual(r,[])
 def test_malformed_inspection_cannot_pretend_execution(self):
  with self.assertRaises(ValueError):self.run_tool([answer('Looking',dict(action='inspect_screen',path='other'))])
 def test_failed_capture_invalidates_last_frame_and_stops(self):
  self.publish()
  def fail():raise RuntimeError('not foreground')
  loop=CaptureLoop(self.buffer,fail,interval=.1,seconds=1).start()
  deadline=time.monotonic()+1
  while not loop.failures and time.monotonic()<deadline:time.sleep(.01)
  self.assertGreater(loop.failures,0)
  self.assertEqual(self.buffer.inspect('session-1')[1]['status'],'unavailable')
  self.assertTrue(loop.stop())

class CoreScreenTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.buffer=ScreenBuffer('oldpc-game','s')
  self.buffer.publish(Image.new('RGB',(100,100),'green'),time.time(),time.monotonic())
 def start(self,replies):
  self.provider=Provider(replies)
  self.core=Core(Path(self.tmp.name)/'core',provider=self.provider,screen_source=self.buffer,
     inbox_config=dict(bot_id='1563299893014036550',users=['1200889100379639899'],after_id='100')).start()
  self.addCleanup(self.stop)
 def stop(self):
  if self.core.accepting:self.core.call('stop')
  self.core.thread.join(5)
 def test_core_turn_executes_model_choice_not_provisional_speech(self):
  self.start([LOOK,answer('A green frame.')])
  result=self.core.call('think',dict(prompt='What interests you?',screen_session='s'))
  self.assertEqual(result['say'],'A green frame.')
  self.assertEqual(len(self.provider.calls),2)
  import sqlite3,json
  from contextlib import closing
  with closing(sqlite3.connect(self.core.root/'core.sqlite3')) as db:
   rows=[json.loads(row[0]) for row in db.execute("SELECT payload FROM events WHERE kind='observation'")]
  receipts=[r for r in rows if r.get('type')=='screen.tool_result']
  self.assertEqual(len(receipts),1);self.assertEqual(receipts[0]['status'],'ready')
  self.assertNotIn('data:image',json.dumps(receipts))
 def test_ordinary_turn_does_not_offer_screen(self):
  self.start([answer()]);self.core.call('think',dict(prompt='hello'))
  self.assertNotIn('AVAILABLE TOOL',self.provider.calls[0][0])
 def test_request_journal_delay_cannot_extend_original_turn_deadline(self):
  self.start([answer()]);original=self.core._event
  def slow(kind,payload,**kwargs):
   if kind=='model' and payload.get('type')=='model.request':time.sleep(.06)
   return original(kind,payload,**kwargs)
  self.core._event=slow
  import uuid
  correlation=str(uuid.uuid4())
  with self.assertRaises(TimeoutError):self.core.call('think',dict(prompt='q',correlation_id=correlation),timeout=.03)
  time.sleep(.1)
  events=self.core.call('correlation',dict(correlation_id=correlation))['events']
  self.assertFalse(any(e['kind']=='inference' for e in events))
 def test_wrong_session_never_calls_provider(self):
  self.start([])
  with self.assertRaises(ValueError):self.core.call('think',dict(prompt='q',screen_session='other'))
  self.assertEqual(self.provider.calls,[])
 def test_private_inbox_cannot_gain_screen_context(self):
  self.start([])
  scope=dict(bot_id='1563299893014036550',channel_id='200',peer_id='1200889100379639899')
  self.core.call('inbox',dict(scope,operation='bind'))
  turn=dict(bot_id=scope['bot_id'],channel_id='200',author_id=scope['peer_id'],surface='dm')
  with self.assertRaises(ValueError):self.core.call('think',dict(prompt='q',screen_session='s',inbox_scope=turn))
  self.assertEqual(self.provider.calls,[])

if __name__=='__main__':unittest.main()
