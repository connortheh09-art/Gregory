from pathlib import Path
import sys,time,tempfile,unittest,json,threading
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
from PIL import Image
from gregory_core.screen import ScreenBuffer,CaptureLoop,generate_with_screen
from greg_game_tasks import GameScreen
from greg_game_tasks import GameTasks
from greg_supervised import RunVoiceLog
from greg_playercore import Runtime,NavGraph,EventMemory
import test_supervised_sensor as fixture
import test_vc_game_tasks as tasks_fixture
from test_screen_tool import Provider,LOOK,answer

class BindingTests(unittest.TestCase):
 def test_map_epoch_change_drops_old_frames_and_late_capture(self):
  game=GameScreen(lambda:(Image.new('RGB',(10,10)),time.time()))
  state=dict(map='a',bridgeSession='s',controlEpoch=1)
  game.update(state,True);old=game.buffer.session
  game.buffer.publish(Image.new('RGB',(10,10)),time.time(),time.monotonic(),session=old)
  game.update(dict(state,map='b'),True)
  self.assertNotEqual(game.buffer.session,old)
  self.assertEqual(game.buffer.inspect(game.buffer.session)[1]['status'],'unavailable')
  with self.assertRaises(ValueError):game.buffer.publish(Image.new('RGB',(10,10)),time.time(),time.monotonic(),session=old)
  game.update(state,True);self.assertNotEqual(game.buffer.session,old)
 def test_inactive_capture_never_starts_and_stop_closes(self):
  calls=[];game=GameScreen(lambda:calls.append(1),seconds=1).start()
  time.sleep(.03);self.assertEqual(calls,[]);self.assertTrue(game.stop())
  self.assertTrue(game.buffer.closed)
 def test_inflight_capture_cannot_cross_world_transition(self):
  entered=threading.Event();release=threading.Event()
  def capture():entered.set();release.wait(1);return Image.new('RGB',(10,10)),time.time()
  game=GameScreen(capture,seconds=2);state=dict(map='a',bridgeSession='s',controlEpoch=1)
  game.update(state,True);game.start();self.assertTrue(entered.wait(1))
  game.update(dict(state,controlEpoch=2),False);release.set();time.sleep(.03)
  self.assertEqual(len(game.buffer.frames),0);self.assertTrue(game.stop())
 def test_hung_capture_is_reported_not_hidden_as_clean_shutdown(self):
  from greg_producers import ProducerDeadline
  entered=threading.Event();release=threading.Event()
  def capture():entered.set();release.wait(2);return Image.new('RGB',(10,10)),time.time()
  game=GameScreen(capture,seconds=3);game.update(dict(map='a',bridgeSession='s',controlEpoch=1),True)
  game.start();self.assertTrue(entered.wait(1));game.request_stop()
  try:
   with self.assertRaises(ProducerDeadline):game.join_until(time.monotonic()+.01)
   self.assertTrue(game.buffer.closed);self.assertEqual(game.pending,1)
  finally:release.set();game.join_until(time.monotonic()+1)
  self.assertEqual(len(game.buffer.frames),0)
 def test_readonly_default_still_discards_task_but_trusted_game_turn_returns_proposal(self):
  b=ScreenBuffer('oldpc','s');b.publish(Image.new('RGB',(10,10)),time.time(),time.monotonic())
  task=dict(action='game_task',kind='hold')
  for allowed in [False,True]:
   receipts=[];provider=Provider([LOOK,answer('I will wait.',task)])
   result=generate_with_screen(provider,{},'q',b,'s',time.monotonic()+3,receipts,allow_game_task=allowed)
   self.assertEqual(result.get('intent'),task if allowed else None)

class CoreTaskVisionTests(unittest.TestCase):
 setUp=fixture.SensorTests.setUp
 cleanup=fixture.SensorTests.cleanup
 wait_for=fixture.SensorTests.wait_for
 def enable(self):
  tasks_fixture.VoiceCoreTests.enable(self)
  self.state["capabilities"]={"playercore":True}
  self.buffer=ScreenBuffer('oldpc-game','bound')
  self.buffer.publish(Image.new('RGB',(100,100),'green'),time.time(),time.monotonic())
  self.core.screen_source=self.buffer;self.lane.screen_source=self.buffer
  self.calls=[]
  def generate(profile,prompt,**kw):
   self.calls.append((prompt,kw))
   if len(self.calls)==1:return LOOK
   return answer('I will try that spot.',dict(action='game_task',kind='visit',target='D1',stay_seconds=120))
  self.provider.generate=generate
 def test_voice_to_core_look_to_image_to_validated_route(self):
  self.enable();self.assertTrue(self.lane.hear_voice('Go hide somewhere.',self.meta))
  self.wait_for(lambda:self.lane.ready is not None);row=self.lane.take()
  self.assertEqual(len(self.calls),2);self.assertIn('images',self.calls[1][1])
  self.assertNotEqual(row['say'],LOOK['say']);self.assertEqual(row['screen_observations'][0]['status'],'ready')
  rows=[]
  for i,x in [(1,0),(2,500)]:
   rows.append(dict(i=i,c=dict(x=x,y=0,z=0),a=[3-i],k=[dict(x=xx,y=yy,z=0) for xx,yy in [(x-250,-100),(x+250,-100),(x+250,100),(x-250,100)]]))
  runtime=Runtime(NavGraph(dict(map=self.state['map'],areas=rows)),EventMemory(self.root/'nav-memory'))
  self.tasks.apply(row['game_intent'],row['game_task_view'],self.state,runtime,time.monotonic())
  self.assertEqual(self.tasks.tick(runtime,self.state,time.monotonic())['action'],'navigate')
 def test_plain_non_voice_turn_has_no_screen_offer(self):
  self.enable();self.provider.generate=lambda profile,prompt,**kw: self.calls.append((prompt,kw)) or answer()
  self.lane.hear('hi');self.wait_for(lambda:self.lane.ready is not None)
  self.assertNotIn('AVAILABLE TOOL',self.calls[0][0])
 def test_stale_world_after_image_cannot_publish_task(self):
  self.enable();original=self.provider.generate
  def generate(profile,prompt,**kw):
   result=original(profile,prompt,**kw)
   if kw.get('images'):
    self.lane.update(dict(self.state,controlEpoch=2))
   return result
  self.provider.generate=generate
  self.lane.hear_voice('Go hide',self.meta)
  self.wait_for(lambda:self.lane.future is None and not self.lane.queue)
  self.assertIsNone(self.lane.ready);self.assertFalse(self.tasks.engaged)
 def test_arrival_offers_one_internal_decision_without_faking_owner_words(self):
  self.enable();self.tasks.view['current_task']=dict(id='t',phase='arrived')
  self.assertTrue(self.lane.consider_game_feedback());request=self.lane.queue[-1]
  self.assertTrue(request['game_attention']);self.assertNotIn('voice_metadata',request)
  self.assertFalse(self.lane.consider_game_feedback());self.lane.queue.clear()
  self.assertFalse(self.lane.consider_game_feedback())

class LocalLogTests(unittest.TestCase):
 def test_owner_only_bounded_and_no_dm_disclosure(self):
  with tempfile.TemporaryDirectory() as tmp:
   log=RunVoiceLog(Path(tmp)/'turns.jsonl','owner',limit=1000)
   self.assertFalse(log.utterance('guest words',dict(author_id='guest',request_id='g')))
   self.assertTrue(log.utterance('go hide',dict(author_id='owner',request_id='r')))
   row=dict(request=dict(voice_metadata=dict(author_id='owner',request_id='r'),inbox_voice_claim='private'),say='private DM content')
   self.assertFalse(log.reply(row,True))
   self.assertFalse(log.utterance('x'*1000,dict(author_id='owner',request_id='r2')))
   text=log.path.read_text();self.assertIn('go hide',text);self.assertNotIn('private DM content',text)
   with self.assertRaises(FileExistsError):RunVoiceLog(log.path,'owner')
if __name__=='__main__':unittest.main()
