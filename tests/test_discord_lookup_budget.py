"""The evidenced slow-embedding lookup path, using disposable Core roots only."""
import asyncio
from concurrent.futures import Future
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gregory_core.discord_text as port
from gregory_core.memory import MemoryStore
from gregory_core.runtime import Core, FixtureProvider


class ImmediateCore:
    def __init__(self, error=None):
        self.submissions = []
        self.error = error

    def submit(self, action, payload):
        self.submissions.append((action, payload))
        future = Future()
        if self.error is None:
            future.set_result({'ok': True})
        else:
            future.set_exception(self.error)
        return future

    def status_snapshot(self):
        return {'snapshot': True}


class ClientBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_budget_is_stripped_without_mutating_caller(self):
        core = ImmediateCore()
        payload = {'query': 'drum', 'retrieval_seconds': 15, 'metadata_only': True}
        result = await port.GregoryCoreClient(core).call('lookup', payload)
        self.assertEqual(result, {'ok': True})
        self.assertEqual(core.submissions, [('lookup', {'query': 'drum', 'metadata_only': True})])
        self.assertEqual(payload['retrieval_seconds'], 15)

    async def test_lookup_requires_a_finite_bounded_retrieval_lane(self):
        for bad in (None, 0, -1, True, '15', 15.1, float('nan'), float('inf')):
            core = ImmediateCore()
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                await port.GregoryCoreClient(core).call('lookup',
                    {'query': 'drum', 'retrieval_seconds': bad})
            self.assertEqual(core.submissions, [])

    async def test_think_keeps_its_seconds_plus_three_wait_and_payload(self):
        for seconds in (0.1, 15, 25):
            core = ImmediateCore()
            payload = {'prompt': 'test only', 'deadline_seconds': seconds}
            original = asyncio.wait_for
            with patch.object(port.asyncio, 'wait_for', wraps=original) as wait:
                await port.GregoryCoreClient(core).call('think', payload)
            self.assertEqual(wait.call_args.args[1], seconds + 3)
            self.assertEqual(core.submissions, [('think', payload)])

    async def test_control_wait_and_status_snapshot_are_unchanged(self):
        core = ImmediateCore()
        client = port.GregoryCoreClient(core)
        original = asyncio.wait_for
        with patch.object(port.asyncio, 'wait_for', wraps=original) as wait:
            await client.call('conversation', {'operation': 'get'})
        self.assertEqual(wait.call_args.args[1], 3)
        self.assertEqual(await client.call('status'), {'snapshot': True})
        self.assertEqual(len(core.submissions), 1)

    async def test_backend_timeout_is_not_mislabelled_as_client_expiry(self):
        failure = TimeoutError('test backend failure')
        with self.assertRaises(TimeoutError) as caught:
            await port.GregoryCoreClient(ImmediateCore(failure)).call('lookup',
                {'query': 'drum', 'retrieval_seconds': 1})
        # asyncio.wrap_future may recreate concurrent-future timeout objects.
        self.assertEqual(type(caught.exception), type(failure))
        self.assertEqual(str(caught.exception), str(failure))
        self.assertNotIsInstance(caught.exception, port.RetrievalTimeout)

    async def test_lookup_caller_cancellation_does_not_cancel_core_future(self):
        future = Future()
        class PendingCore:
            def submit(self, action, payload):
                return future
        task = asyncio.create_task(port.GregoryCoreClient(PendingCore()).call('lookup',
            {'query': 'drum', 'retrieval_seconds': 1}))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(future.cancelled())
        future.set_result({'hits': []})
        await asyncio.sleep(0)


class AdapterBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_literal_and_rewritten_lookup_get_existing_lane_budget(self):
        calls = []
        class Client:
            async def call(self, action, payload):
                calls.append((action, payload))
                if action == 'conversation':
                    if payload['operation'] == 'reserve':
                        return {'duplicate': False, 'correlation_id': '00000000-0000-0000-0000-000000000001'}
                    return dict(payload)
                if action == 'lookup':
                    return {'hits': [], 'memory_count': 1, 'historical_only': True}
                if action == 'think':
                    return {'say': 'oil drum' if 'Write a search query' in payload['prompt'] else 'test reply'}
                raise AssertionError(action)
        class Transport:
            async def send(self, *args, **kwargs):
                return '900'
        adapter = port.DiscordTextAdapter(Client(), Transport(), guild_id='1',
            channel_id='2', bot_id='3', users=['4'], retrieval_seconds=7).start()
        try:
            result = await adapter.offer(port.Message('1', '2', '10', '4', 'gregory: test', time.time()))
            self.assertEqual(result['state'], 'accepted')
            lookups = [payload for action, payload in calls if action == 'lookup']
            self.assertEqual([p.get('retrieval_seconds') for p in lookups], [7, 7])
            self.assertEqual([p['query'] for p in lookups], ['test', 'oil drum'])
        finally:
            await adapter.close()

    async def delayed_turn(self, retrieval_seconds):
        with tempfile.TemporaryDirectory(prefix='gregory-lookup-budget-test-') as directory:
            core = Core(Path(directory) / 'character', provider=FixtureProvider()).start()
            posts = []
            class Transport:
                async def send(self, *args, **kwargs):
                    posts.append(args)
                    return '900'
            adapter = port.DiscordTextAdapter(port.GregoryCoreClient(core), Transport(),
                guild_id='1', channel_id='2', bot_id='3', users=['4'],
                model_seconds=25, retrieval_seconds=retrieval_seconds).start()
            search = MemoryStore.search
            def delayed_search(self, *args, **kwargs):
                time.sleep(3.2)
                return search(self, *args, **kwargs)
            try:
                with patch.object(MemoryStore, 'search', delayed_search):
                    result = await adapter.offer(port.Message('1', '2', '10', '4', 'gregory: test', time.time()))
                events = core.call('correlation', {'correlation_id': result['correlation_id']})['events']
                return result, posts, events
            finally:
                await adapter.close()
                stop = core.call('stop')
                core.thread.join(5)
                self.assertTrue(stop['databases_closed'])
                self.assertTrue(stop['fully_drained'])

    async def test_lookup_slower_than_old_three_second_wait_can_send_reply(self):
        result, posts, events = await self.delayed_turn(1)
        self.assertEqual(result['state'], 'accepted')
        self.assertEqual(len(posts), 1)
        self.assertTrue(any(row['payload'].get('type') == 'model.request' for row in events))

    async def test_lookup_overrun_sends_fixed_unavailable_reply_without_model(self):
        result, posts, events = await self.delayed_turn(.02)
        self.assertEqual(result['state'], 'accepted')
        self.assertEqual(result['error_category'], 'RetrievalTimeout')
        self.assertEqual(len(posts), 1)
        self.assertIn('[Memory temporarily unavailable; retrieval did not complete]', posts[0][1])
        self.assertNotIn('no matching persisted memory', posts[0][1])
        self.assertFalse(any(row['payload'].get('type') == 'model.request' for row in events))
        self.assertTrue(any(row['payload'].get('error_category') == 'RetrievalTimeout' for row in events))


if __name__ == '__main__':
    unittest.main()
