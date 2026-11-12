"""Real Core, SQLite memory and journal; synthetic Discord transport/model."""
import asyncio
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from gregory_core.runtime import Core,FixtureProvider
from gregory_core.discord_text import DiscordTextAdapter,GregoryCoreClient,Message,sha
from gregory_core.conversation import ConversationConflict
from core_fixture_experience import capture_fixture


class Provider(FixtureProvider):
    def __init__(self):self.calls=[];self.used_memory_ids=[]
    def generate(self,profile,prompt):
        self.calls.append((profile,prompt))
        return {'say':'Synthetic Gregory response; not a live Gemma acceptance.',
                'used_memory_ids':list(self.used_memory_ids),
                'intent':{'kind':'shell','command':'NEVER_EXECUTE'}}


class Transport:
    def __init__(self):self.posts=[];self.fail=False;self.hang=False
    async def send(self,channel,body,**kwargs):
        if self.hang:await asyncio.Event().wait()
        self.posts.append((channel,body,kwargs))
        if self.fail:raise ConnectionError('API may already have accepted')
        return str(900+len(self.posts))


class TextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.provider=Provider()
        self.core=Core(self.root/'character',provider=self.provider).start()
        self.transport=Transport()
        self.adapter=self.new_adapter()

    def new_adapter(self,**kw):
        return DiscordTextAdapter(GregoryCoreClient(self.core),self.transport,
            guild_id='1',channel_id='2',bot_id='3',users={'4'},bots={'5','6'},
            turns_per_minute=12,**kw).start()

    def message(self,id='10',content='gregory: hello',**kw):
        return Message('1','2',id,'4',content,time.time(),**kw)

    async def turn(self,m):
        future=self.adapter.offer(m)
        self.assertIsNotNone(future)
        return await asyncio.wait_for(future,4)

    async def asyncTearDown(self):
        await self.adapter.close()
        if self.core.accepting:self.core.call('stop')
        self.core.thread.join(3)
        self.tmp.cleanup()

    async def test_filters_explicit_trigger_bot_loops_and_mentions(self):
        base=self.message()
        invalid=[replace(base,guild_id='8'),replace(base,channel_id='9'),replace(base,author_id='3',bot=True),
            replace(base,author_id='8',bot=True),replace(base,author_id='8'),replace(base,webhook=True),
            replace(base,reply_to_own=True),replace(base,content='ordinary ambient message')]
        for message in invalid:self.assertIsNone(self.adapter.offer(message))
        answer=await self.turn(replace(base,author_id='5',bot=True,content='<@3> hello'))
        self.assertEqual(answer['state'],'accepted')
        self.assertFalse(self.transport.posts[0][2]['allowed_mentions'])
        self.assertEqual(len(self.provider.calls),1)

    async def test_real_memory_identity_and_citations_unchanged_no_chat_promotion(self):
        imported=self.core.call('import',capture_fixture(self.root/'experience'))
        self.provider.used_memory_ids=[imported['memory_id']]
        profile=self.core.call('status')['profile']
        before=self.core.call('lookup',{'memory_id':imported['memory_id']})['hits'][0]
        result=await self.turn(self.message(content='gregory: wood_crate001a'))
        after=self.core.call('lookup',{'memory_id':imported['memory_id']})['hits'][0]
        self.assertEqual(after['evidence'],before['evidence'])
        self.assertEqual(after['claims'],before['claims'])
        self.assertEqual(self.core.call('status')['memory_count'],1)
        self.assertEqual(self.provider.calls[0][0],profile)
        self.assertIn(imported['memory_id'],self.provider.calls[0][1])
        self.assertIn(before['evidence'][0]['event_id'],json.dumps(self.core.call('lookup',{'memory_id':imported['memory_id']})))
        self.assertIn('Historical memory '+imported['memory_id'],self.transport.posts[0][1])
        chain=self.core.call('correlation',{'correlation_id':result['correlation_id']})['events']
        self.assertTrue({'conversation','memory','model','inference','decision','outcome'}<={e['kind'] for e in chain})
        self.assertFalse(any(e['kind']=='observation' for e in chain))
        self.assertNotIn('wood_crate001a',json.dumps(chain))
        self.assertNotIn('Synthetic Gregory response',json.dumps(chain))
        self.assertTrue(any(e['payload'].get('type')=='conversation.accepted' for e in chain))
        self.assertTrue(all(e['fixture'] for e in chain if e['kind']=='conversation'))
        self.assertFalse(hasattr(self.adapter,'db'))
        self.assertFalse(hasattr(self.adapter.client,'db'))

    async def test_empty_and_wrong_memory_have_no_substitute_claim(self):
        await self.turn(self.message(content='gregory: nonexistentXQZ'))
        self.assertIn('HISTORICAL_RETRIEVAL: []',self.provider.calls[0][1])
        self.assertNotIn('[Retrieval:',self.transport.posts[0][1])
        self.core.call('import',capture_fixture(self.root/'wrong'))
        await self.turn(self.message(id='11',content='gregory: nonexistentXQZ'))
        # Non-empty store plus a literal miss now spends one bounded rewrite call
        # first; the rewrite is unusable here, so the literal query stands and the
        # answer turn still reaches the model with no retrieved memory.
        self.assertIn('Write a search query',self.provider.calls[1][1])
        self.assertIn('HISTORICAL_RETRIEVAL: []',self.provider.calls[2][1])
        self.assertNotIn('[Retrieval:',self.transport.posts[1][1])
        self.assertEqual(self.core.call('status')['memory_count'],1)

    async def test_duplicate_across_adapter_and_core_restart_one_model_one_post(self):
        m=self.message()
        first=await self.turn(m)
        original=self.core.call('status')
        await self.adapter.close()
        self.core.call('stop');self.core.thread.join(3)
        self.core=Core(self.root/'character',provider=self.provider).start()
        self.adapter=self.new_adapter()
        second=await self.turn(m)
        self.assertTrue(second['duplicate'])
        self.assertEqual(first['correlation_id'],second['correlation_id'])
        self.assertEqual(len(self.provider.calls),1)
        self.assertEqual(len(self.transport.posts),1)
        current=self.core.call('status')
        self.assertEqual(current['profile'],original['profile'])
        self.assertNotEqual(current['core']['run_id'],original['core']['run_id'])

    async def test_duplicate_content_conflict_never_reruns_or_posts(self):
        await self.turn(self.message())
        result=await self.turn(self.message(content='gregory: DIFFERENT'))
        self.assertEqual(result['error_category'],'ConversationConflict')
        self.assertEqual(len(self.provider.calls),1)
        self.assertEqual(len(self.transport.posts),1)

    async def test_ambiguous_send_not_retried_even_after_restart(self):
        self.transport.fail=True
        first=await self.turn(self.message())
        self.assertEqual(first['state'],'unknown')
        await self.adapter.close();self.adapter=self.new_adapter()
        repeated=await self.turn(self.message())
        self.assertTrue(repeated['duplicate'])
        self.assertEqual(repeated['state'],'unknown')
        self.assertEqual(len(self.transport.posts),1)

    async def test_hung_send_has_bounded_unknown_outcome(self):
        self.transport.hang=True
        self.adapter.send_seconds=.05
        row=await self.turn(self.message())
        self.assertEqual(row['state'],'unknown')
        self.assertEqual(row['error_category'],'TimeoutError')

    async def test_hung_model_timeout_disconnect_and_close_never_post_late(self):
        began,release=threading.Event(),threading.Event()
        provider=self.provider
        def generate(profile,prompt):
            began.set();release.wait(3)
            return {'say':'LATE MUST NOT POST'}
        provider.generate=generate
        self.adapter.model_seconds=.05
        future=self.adapter.offer(self.message())
        try:
            while not began.is_set():await asyncio.sleep(.005)
            self.adapter.disconnect()
            result=await asyncio.wait_for(future,1)
            self.assertEqual(result['state'],'error')
            self.assertEqual(result['error_category'],'TimeoutError')
            await asyncio.wait_for(self.adapter.close(),.5)
            self.assertEqual(self.transport.posts,[])
            release.set();await asyncio.sleep(.1)
            events=self.core.call('correlation',{'correlation_id':result['correlation_id']})['events']
            self.assertFalse(any(e['kind']=='inference' for e in events))
        finally:release.set()

    async def test_disconnect_during_model_no_post_and_no_replay(self):
        began,release=threading.Event(),threading.Event()
        def generate(profile,prompt):
            began.set();release.wait(2);return {'say':'must not post'}
        self.provider.generate=generate
        future=self.adapter.offer(self.message())
        try:
            while not began.is_set():await asyncio.sleep(.005)
            self.adapter.disconnect();release.set()
            row=await future
            self.assertEqual(row['state'],'cancelled')
            self.adapter.reconnect()
            duplicate=await self.turn(self.message())
            self.assertTrue(duplicate['duplicate'])
            self.assertEqual(self.transport.posts,[])
        finally:release.set()

    async def test_queue_rate_and_serial_admission_are_bounded(self):
        self.adapter.limit=2
        one=self.adapter.offer(self.message())
        two=self.adapter.offer(self.message(id='11'))
        self.assertIsNone(self.adapter.offer(self.message(id='12')))
        results=await asyncio.gather(one,two)
        self.assertTrue(all(r['state']=='accepted' for r in results))
        self.assertEqual(len(self.provider.calls),2)
        self.assertEqual(self.core.call('status')['memory_count'],0)

    async def test_queue_capacity_and_shutdown_discard_pending_posts(self):
        futures=[self.adapter.offer(self.message(id=str(20+i))) for i in range(4)]
        self.assertTrue(all(f is not None for f in futures))
        self.assertIsNone(self.adapter.offer(self.message(id='30')))
        await self.adapter.close()
        rows=await asyncio.gather(*futures)
        self.assertTrue(all(r['state']=='cancelled' for r in rows))
        self.assertEqual(self.transport.posts,[])

    async def test_model_busy_refusal_is_logged_without_send(self):
        began,release=threading.Event(),threading.Event()
        def generate(profile,prompt):began.set();release.wait(2);return {'say':'other call'}
        self.provider.generate=generate
        unrelated=self.core.submit('think',{'prompt':'other owner call'})
        try:
            while not began.is_set():await asyncio.sleep(.005)
            result=await self.turn(self.message())
            self.assertEqual(result['state'],'error')
            self.assertEqual(result['error_category'],'AdmissionRefused')
            self.assertEqual(self.transport.posts,[])
        finally:
            release.set()
            await asyncio.wrap_future(unrelated)

    async def test_core_ledger_failure_is_atomic_no_send(self):
        with closing(sqlite3.connect(self.core.root/'core.sqlite3')) as db, db:
            db.execute("CREATE TRIGGER fail_conversation BEFORE INSERT ON events WHEN NEW.kind='conversation' BEGIN SELECT RAISE(ABORT,'fixture-ledger-failure'); END")
        row=await self.turn(self.message())
        self.assertEqual(row['state'],'error')
        self.assertEqual(len(self.provider.calls),0)
        self.assertEqual(self.transport.posts,[])
        with closing(sqlite3.connect(self.core.root/'core.sqlite3')) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM conversation_turns').fetchone()[0],0)

    async def test_restart_sending_marker_is_unknown_not_resend(self):
        m=self.message()
        ids=dict(guild_id=m.guild_id,channel_id=m.channel_id,message_id=m.message_id)
        self.core.call('conversation',dict(ids,operation='reserve',author_id=m.author_id,
            content_sha256=sha(m.content),source_at=m.source_at,received_at=time.time(),trigger='prefix'))
        for state in ('intent','sending'):
            self.core.call('conversation',dict(ids,operation='transition',state=state))
        await self.adapter.close();self.adapter=self.new_adapter()
        row=await self.turn(m)
        self.assertEqual(row['state'],'unknown')
        self.assertTrue(row['duplicate'])
        self.assertEqual(self.transport.posts,[])

if __name__=='__main__':unittest.main()
