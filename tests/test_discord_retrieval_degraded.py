"""Owner-approved B: memory unavailable is not an empty historical search."""
import asyncio
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, PropertyMock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from gregory_core.discord_text import DiscordTextAdapter, GregoryCoreClient, Message
from gregory_core.memory import MemoryStore
from gregory_core.runtime import Core, FixtureProvider
from core_fixture_experience import capture_fixture


class RetrievalDegradedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.calls=[];self.posts=[]
        calls=self.calls
        class Provider(FixtureProvider):
            def generate(self,profile,prompt):
                calls.append(prompt)
                return {'say':'oil drum'}
        self.core=Core(self.root/'character',provider=Provider()).start()
        self.mid=self.core.call('import',capture_fixture(self.root/'capture'))['memory_id']
        posts=self.posts
        class Transport:
            async def send(self,channel,body,**kwargs):
                posts.append((channel,body,kwargs))
                return '900'
        self.adapter=DiscordTextAdapter(GregoryCoreClient(self.core),Transport(),
            guild_id='1',channel_id='2',bot_id='3',users=['4'],
            model_seconds=25,retrieval_seconds=15).start()

    async def asyncTearDown(self):
        await self.adapter.close()
        if self.core.accepting:
            stop=self.core.call('stop')
            self.assertTrue(stop['databases_closed'])
            self.assertTrue(stop['fully_drained'])
        self.core.thread.join(5)
        self.tmp.cleanup()

    async def turn(self,content='gregory: unrelatedxyz'):
        return await self.adapter.offer(Message('1','2','10','4',content,time.time()))

    async def test_failed_lookup_sends_fixed_reply_and_preserves_existing_memory(self):
        before=self.core.call('lookup',{'memory_id':self.mid})['hits'][0]
        with patch.object(MemoryStore,'search',side_effect=OSError('private backend details')):
            result=await self.turn()
        after=self.core.call('lookup',{'memory_id':self.mid})['hits'][0]
        self.assertEqual(after,before)
        self.assertEqual(result['state'],'accepted')
        self.assertEqual(result['error_category'],'OSError')
        self.assertEqual(self.calls,[])
        self.assertEqual(len(self.posts),1)
        body=self.posts[0][1]
        self.assertIn('My memory is temporarily unavailable',body)
        self.assertIn('[Memory temporarily unavailable; retrieval did not complete]',body)
        self.assertNotIn('no matching persisted memory',body)
        self.assertNotIn('private backend details',body)
        events=self.core.call('correlation',{'correlation_id':result['correlation_id']})['events']
        accepted=[e for e in events if e['payload'].get('type')=='conversation.accepted']
        self.assertEqual(accepted[0]['payload']['error_category'],'OSError')
        self.assertEqual(accepted[0]['correlation_id'],result['correlation_id'])
        self.assertFalse(any(e['payload'].get('type')=='model.request' for e in events))

    async def test_rewritten_lookup_failure_skips_answer_model_call(self):
        search=MemoryStore.search
        seen=[]
        def second_lookup_fails(memory,*args,**kwargs):
            seen.append(args[0])
            if len(seen)==2:raise ConnectionError('test embedding outage')
            return search(memory,*args,**kwargs)
        with patch.object(MemoryStore,'search',second_lookup_fails):
            result=await self.turn()
        self.assertEqual(result['state'],'accepted')
        self.assertEqual(result['error_category'],'ConnectionError')
        self.assertEqual(len(seen),2)
        self.assertEqual(len(self.calls),1)  # Rewrite only, not another model call to explain failure.
        self.assertIn('Write a search query',self.calls[0])
        self.assertIn('Memory temporarily unavailable',self.posts[0][1])

    async def test_successful_zero_match_search_keeps_the_miss_footer(self):
        result=await self.turn()
        self.assertEqual(result['state'],'accepted')
        self.assertIsNone(result['error_category'])
        self.assertNotIn('[Retrieval:',self.posts[0][1])
        self.assertNotIn('Memory temporarily unavailable',self.posts[0][1])

    async def test_degraded_reply_uses_normal_ambiguous_send_contract(self):
        async def failed_send(*args,**kwargs):
            self.posts.append(args)
            raise ConnectionError('test uncertain API acceptance')
        self.adapter.transport.send=failed_send
        with patch.object(MemoryStore,'search',side_effect=OSError('test unavailable')):
            result=await self.turn()
        self.assertEqual(result['state'],'unknown')
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.calls,[])
        events=self.core.call('correlation',{'correlation_id':result['correlation_id']})['events']
        self.assertTrue(any(e['payload'].get('type')=='conversation.intent' and
            e['payload'].get('error_category')=='OSError' for e in events))

    async def test_outer_turn_deadline_is_real_and_keeps_correlation(self):
        search=MemoryStore.search
        def slow_lookup(memory,*args,**kwargs):
            time.sleep(.2)
            return search(memory,*args,**kwargs)
        with patch.object(DiscordTextAdapter,'turn_seconds',new_callable=PropertyMock,return_value=.05):
            with patch.object(MemoryStore,'search',slow_lookup):
                result=await self.turn()
        self.assertEqual(result['state'],'error')
        self.assertEqual(result['error_category'],'TurnTimeout')
        self.assertTrue(result['correlation_id'])
        self.assertEqual(self.calls,[])
        self.assertEqual(self.posts,[])

    async def test_phase_envelope_and_short_shutdown_bound_are_separate(self):
        # 2*lookup18 + rewrite18 + answer28 + send5 + 4 journal calls*3 = 99.
        self.assertEqual(self.adapter.turn_seconds,99)
        self.assertEqual(self.adapter.shutdown_drain_seconds,20)
        self.assertEqual(self.adapter.drain_bound,22)
        self.assertLess(self.adapter.shutdown_drain_seconds+2,30)
        self.adapter.retrieval_seconds=5;self.adapter.model_seconds=15
        self.assertEqual(self.adapter.turn_seconds,59)

    async def test_queue_wait_does_not_reset_an_expired_turn_allowance(self):
        await self.adapter.close()
        self.adapter=DiscordTextAdapter(GregoryCoreClient(self.core),self.adapter.transport,
            guild_id='1',channel_id='2',bot_id='3',users=['4'])
        with patch.object(DiscordTextAdapter,'turn_seconds',new_callable=PropertyMock,return_value=.03):
            future=self.adapter.offer(Message('1','2','10','4','gregory: test',time.time()))
            await asyncio.sleep(.05)
            self.adapter.start()
            result=await future
        self.assertEqual(result['state'],'error')
        self.assertEqual(result['error_category'],'TurnTimeout')
        self.assertEqual(self.calls,[])
        self.assertEqual(self.posts,[])

    async def test_outer_deadline_cancels_active_send_and_records_unknown(self):
        cancelled=asyncio.Event()
        async def pending_send(*args,**kwargs):
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:cancelled.set();raise
        self.adapter.transport.send=pending_send
        with patch.object(DiscordTextAdapter,'turn_seconds',new_callable=PropertyMock,return_value=.5):
            result=await self.turn('gregory: wood_crate001a')
        self.assertEqual(result['state'],'unknown')
        self.assertEqual(result['error_category'],'TurnTimeout')
        await asyncio.wait_for(cancelled.wait(),.5)
        self.assertEqual(self.posts,[])


class ShutdownBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_drain_start_cancels_active_work_without_waiting_out_its_deadline(self):
        started=asyncio.Event();cancelled=asyncio.Event();posts=[]
        class Client:
            async def call(self,action,payload):
                if action=='conversation':
                    return {'duplicate':False,'state':payload.get('state','received'),
                        'correlation_id':'00000000-0000-0000-0000-000000000001'}
                started.set()
                try:await asyncio.Event().wait()
                except asyncio.CancelledError:cancelled.set();raise
        class Transport:
            async def send(self,*args,**kwargs):posts.append(args);return '900'
        adapter=DiscordTextAdapter(Client(),Transport(),guild_id='1',channel_id='2',
            bot_id='3',users=['4'],model_seconds=25,retrieval_seconds=15).start()
        adapter.shutdown_drain_seconds=.03
        future=adapter.offer(Message('1','2','10','4','gregory: test',time.time()))
        await started.wait()
        await asyncio.wait_for(adapter.close(),.5)
        self.assertTrue(cancelled.is_set())
        self.assertEqual((await future)['state'],'cancelled')
        self.assertTrue(adapter.task.done())
        self.assertTrue(adapter.queue.empty())
        self.assertEqual(posts,[])

    async def test_unfinished_queue_drain_is_bounded_and_not_claimed_clean(self):
        adapter=DiscordTextAdapter(None,None,guild_id='1',channel_id='2',bot_id='3',users=['4']).start()
        adapter.shutdown_drain_seconds=.03
        async def never_drained():await asyncio.Event().wait()
        with patch.object(adapter.queue,'join',never_drained):
            with self.assertRaises(TimeoutError):await asyncio.wait_for(adapter.close(),.5)
        self.assertTrue(adapter.task.done())


if __name__=='__main__':unittest.main()
