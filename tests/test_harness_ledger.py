"""More than an evening's turns must not consume the in-flight ledger forever."""
from pathlib import Path
from collections import deque
from concurrent.futures import Future
import copy,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'deployments/oldpc')]
from gregory_core.supervised_game import RecordingRefused
import test_core_harness as base

class LedgerTests(unittest.TestCase):
 setUp=base.HarnessTests.setUp
 publish=base.HarnessTests.publish
 finalize=base.HarnessTests.finalize
 def turn(self,n):
  self.row['request']['voice_metadata']['request_id']='turn-'+str(n)
  self.publish();final=self.finalize();self.publish(final)
  self.asked.clear()
 def test_200_completed_turns_keep_serving_without_pending_growth(self):
  for i in range(200):
   self.turn(i)
   self.assertEqual(len(self.lane.turn_ledger),0)
  self.assertEqual(len(self.spoken),200);self.assertEqual(len(self.lane.turn_history),200)
 def test_200_failed_finalizations_release_inflight_budget(self):
  self.lane.imports=deque();self.lane.ready=None
  for i in range(200):
   self.row['request']['voice_metadata']['request_id']='failed-'+str(i);self.publish()
   request=self.lane.queue.popleft();future=Future();future.set_exception(TimeoutError('fixture'))
   self.lane.future=future;self.lane.request=request;self.lane.poll()
   self.assertEqual(len(self.lane.turn_ledger),0)
  self.assertEqual(self.spoken,[]);self.assertEqual(len(self.lane.turn_history),200)
 def test_history_is_bounded_and_recent_duplicate_still_refused(self):
  for i in range(1100):self.turn(i)
  self.assertEqual(len(self.lane.turn_history),1024);self.assertEqual(len(self.lane.turn_ledger),0)
  count=len(self.spoken);self.publish()
  self.assertEqual(len(self.spoken),count);self.assertEqual(len(self.lane.queue),0)
 def test_pending_duplicate_does_not_cancel_original_finalization(self):
  self.publish();key=self.lane._turn_key(self.row)
  self.publish()
  self.assertIn(key,self.lane.turn_ledger);self.assertEqual(len(self.lane.queue),1)
  final=self.finalize();self.publish(final)
  self.assertEqual(len(self.spoken),1);self.assertEqual(len(self.lane.turn_ledger),0)
 def test_recent_completed_initial_and_final_replays_cannot_execute_again(self):
  self.row['game_intent']=dict(action='game_task',kind='hold',stay_seconds=20)
  original=copy.deepcopy(self.row);self.publish();final=self.finalize();self.publish(final)
  task=self.link.active['id'];self.publish(original);self.publish(final)
  self.assertEqual(self.link.active['id'],task);self.assertEqual(len(self.spoken),1)
 def test_queue_full_cancellation_retires_admitted_turn_without_eviction(self):
  self.lane.queue.extend([dict(n=i) for i in range(4)]);self.publish()
  self.assertEqual(len(self.lane.turn_ledger),0);self.assertEqual(len(self.lane.turn_history),1)
  self.assertEqual([r['n'] for r in self.lane.queue],list(range(4)))
 def test_stale_receipt_cancellation_retires_pending_turn(self):
  self.publish();final=self.finalize();self.link.invalidate();self.link.update(self.runtime,self.state,3)
  self.publish(final)
  self.assertEqual(len(self.lane.turn_ledger),0);self.assertEqual(len(self.lane.turn_history),1)
 def test_worker_stale_receipt_uses_countable_cancellation_log(self):
  self.publish();request=self.lane.queue.popleft()
  future=Future();future.set_exception(RecordingRefused('harness_receipt_stale'))
  self.lane.future=future;self.lane.request=request;self.lane.ready=None;self.lane.imports=deque()
  self.lane.poll()
  self.assertEqual(self.logs.count('HARNESS_SPEECH_CANCELLED stale_receipt'),1)
  self.assertEqual(len(self.lane.turn_ledger),0)

if __name__=='__main__':unittest.main()
