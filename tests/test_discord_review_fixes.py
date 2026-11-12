"""Greg's concrete A-review findings, pinned to 044953e3 before correction."""
import asyncio
from concurrent.futures import Future
from dataclasses import replace
from unittest.mock import patch
import unittest
import test_discord_text as fixture
from test_discord_text import Transport
from gregory_core.discord_text import DiscordTextAdapter,GregoryCoreClient,sha
from gregory_core.memory import MemoryStore


class ReviewFixes(unittest.IsolatedAsyncioTestCase):
    # Reuse fixtures/helpers, never collect the parent's existing test cases twice.
    asyncSetUp=fixture.TextTests.asyncSetUp
    asyncTearDown=fixture.TextTests.asyncTearDown
    new_adapter=fixture.TextTests.new_adapter
    message=fixture.TextTests.message
    turn=fixture.TextTests.turn

    async def test_close_timeout_always_cancels_send_and_stops_it(self):
        adapter=DiscordTextAdapter(GregoryCoreClient(self.core),Transport(),
            guild_id='1',channel_id='2',bot_id='3',users={'4'})
        began=asyncio.Event()
        async def send():
            began.set()
            await asyncio.Event().wait()
        task=asyncio.create_task(send())
        adapter.active_sends.add(task)
        await began.wait()
        result=asyncio.get_running_loop().create_future()
        adapter.queue.put_nowait((self.message(),'hello','prefix',1,result,adapter.delivery_generation))
        wait_for=asyncio.wait_for
        late=[]
        async def short_budget(awaitable,seconds):
            # A send admitted during the drain must be cancelled by finally,
            # not merely by disconnect() at close entry.
            pending=asyncio.create_task(send())
            adapter.active_sends.add(pending);late.append(pending)
            return await wait_for(awaitable,.01)
        try:
            with patch('gregory_core.discord_text.asyncio.wait_for',short_budget):
                with self.assertRaises(TimeoutError):await adapter.close()
            await asyncio.sleep(0)
            self.assertTrue(task.cancelled(),'close timeout bypassed active-send cancellation')
            self.assertTrue(late[0].cancelled(),'finally failed to cancel a send added during drain')
            self.assertFalse(adapter.active_sends)
        finally:
            for pending in [task]+late:pending.cancel()
            await asyncio.gather(task,*late,return_exceptions=True)

    async def test_client_think_requires_explicit_deadline_before_core_admission(self):
        class Stub:
            called=False
            def submit(self,*args):
                self.called=True
                f=Future();f.set_result({'say':'fixture'});return f
        core=Stub()
        with self.assertRaisesRegex(ValueError,'explicit.*deadline'):
            await GregoryCoreClient(core).call('think',{'prompt':'hello'})
        self.assertFalse(core.called)

    async def test_disconnect_during_send_then_reconnect_never_claims_accepted(self):
        began=asyncio.Event()
        class SlowSend:
            async def send(self,*args,**kwargs):
                began.set()
                await asyncio.sleep(.08)
                return '950'
        self.adapter.transport=SlowSend()
        future=self.adapter.offer(self.message())
        await asyncio.wait_for(began.wait(),1)
        self.adapter.disconnect();self.adapter.reconnect()
        row=await asyncio.wait_for(future,1)
        self.assertEqual(row['state'],'unknown')
        self.assertEqual(row['error_category'],'SendInterrupted')
        chain=self.core.call('correlation',{'correlation_id':row['correlation_id']})['events']
        self.assertFalse(any(e['payload'].get('type')=='conversation.accepted' for e in chain))

    async def test_disconnect_after_sending_marker_never_starts_http(self):
        original=self.adapter.client.call
        async def disconnect_after_commit(action,payload=None):
            result=await original(action,payload)
            if action=='conversation' and payload.get('state')=='sending':
                self.adapter.disconnect();self.adapter.reconnect()
            return result
        with patch.object(self.adapter.client,'call',disconnect_after_commit):
            row=await self.turn(self.message())
        self.assertEqual(row['state'],'unknown')
        self.assertEqual(self.transport.posts,[],'send started after the delivery generation was invalidated')

    async def test_same_message_id_other_channel_has_distinct_correlation(self):
        m=self.message()
        payload=dict(operation='reserve',guild_id='1',channel_id='2',message_id=m.message_id,
            author_id=m.author_id,content_sha256=sha(m.content),source_at=m.source_at,
            received_at=m.source_at,trigger='prefix',fixture=True)
        first=await self.adapter.client.call('conversation',payload)
        second=await self.adapter.client.call('conversation',dict(payload,channel_id='99'))
        self.assertNotEqual(first['correlation_id'],second['correlation_id'])
        self.assertNotEqual(first['source_key'],second['source_key'])

    async def test_same_id_same_content_other_author_conflicts(self):
        m=self.message()
        await self.turn(m)
        self.adapter.users.add('7')
        result=await self.turn(replace(m,author_id='7'))
        self.assertEqual(result['error_category'],'ConversationConflict')
        self.assertEqual(len(self.provider.calls),1)
        self.assertEqual(len(self.transport.posts),1)

    async def test_faulted_history_flag_is_visible_and_refuses_post_not_false_footer(self):
        bad=dict(hits=[dict(memory_id='fault',historical_only=False,current_world_state='FAULT',
            origin='recorder',summary='FAULT present claim',evidence=[])],
            mode='keyword',historical_only=False,current_world_state='FAULT')
        with patch.object(MemoryStore,'search',return_value=bad):
            result=await self.turn(self.message())
        self.assertEqual(result['state'],'error')
        self.assertEqual(result['error_category'],'MemoryContractViolation')
        self.assertEqual(self.transport.posts,[])
        self.assertEqual(len(self.provider.calls),0)
        chain=self.core.call('correlation',{'correlation_id':result['correlation_id']})['events']
        self.assertIs(next(e['payload'] for e in chain if e['kind']=='memory')['historical_only'],False)

    async def test_terminal_failure_states_require_typed_error_category(self):
        m=self.message()
        for n,state in enumerate(('error','cancelled','unknown')):
            ids=dict(guild_id='1',channel_id='2',message_id=str(60+n))
            await self.adapter.client.call('conversation',dict(ids,operation='reserve',author_id='4',
                content_sha256=sha(m.content),source_at=m.source_at,received_at=m.source_at,
                trigger='prefix',fixture=True))
            if state=='unknown':
                for step in ('intent','sending'):
                    await self.adapter.client.call('conversation',dict(ids,operation='transition',state=step))
            with self.assertRaisesRegex(ValueError,'error category'):
                await self.adapter.client.call('conversation',dict(ids,operation='transition',state=state))

    async def test_boolean_deadlines_and_queue_settings_are_not_numbers(self):
        for kwargs in ({'model_seconds':True},{'send_seconds':True},{'queue_limit':True},{'turns_per_minute':True}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                DiscordTextAdapter(GregoryCoreClient(self.core),Transport(),guild_id='1',
                    channel_id='2',bot_id='3',users={'4'},**kwargs)


if __name__=='__main__':unittest.main()
