"""Retrieval naturalness: a model-formed query after a literal miss, and the semantic lane."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from gregory_core.runtime import Core, FixtureProvider
from gregory_core.embeddings import EmbeddingSpace, unit_vector
from gregory_core.discord_text import DiscordTextAdapter, GregoryCoreClient, Message
from core_fixture_experience import capture_fixture

# The synthetic fixture episode observes models/props_junk/wood_crate001a.mdl.
LITERAL = 'wood_crate001a'
SYNONYM = 'box'


class FakeEmbedder:
    """Deterministic 4-dim space where 'box' shares a dimension with 'crate'."""
    def __init__(self, revision='rev1'):
        self.space = EmbeddingSpace('fake-local-embed', revision, dimensions=4)

    def _vector(self, text):
        text = text.lower()
        values = [1.0, 0.0, 0.0, 0.0]
        if 'crate' in text or 'box' in text:
            values[1] = 6.0
        return values

    def document(self, text):
        return unit_vector(self._vector(text), 4)

    def query(self, text):
        return unit_vector(self._vector(text), 4)


class EmbeddingLane(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        if getattr(self, 'core', None) is not None:
            if self.core.accepting:
                self.core.call('stop')
            self.core.thread.join(3)
        self.tmp.cleanup()

    def start(self, embedder=None):
        self.core = Core(self.root / 'character', provider=FixtureProvider(), embedder=embedder).start()
        return self.core

    def import_episode(self):
        return self.core.call('import', capture_fixture(self.root / 'episode'))

    def test_vector_written_on_import_and_semantic_lane_finds_a_keyword_miss(self):
        embedder = FakeEmbedder()
        self.start(embedder)
        imported = self.import_episode()
        status = self.core.call('status')['embedding']
        self.assertEqual((status['connected'], status['space_key'], status['vector_count']),
                         (True, embedder.space.key, 1))
        # 'box' is not a token of 'wood_crate001a', so a semantic-only channel
        # proves the vector lane found what keyword search could not.
        result = self.core.call('lookup', {'query': SYNONYM})
        self.assertEqual([h['memory_id'] for h in result['hits']], [imported['memory_id']])
        self.assertEqual(result['hits'][0]['retrieval_channels'], ['semantic'])
        self.assertIs(result['historical_only'], True)
        self.assertEqual(result['current_world_state'], 'unknown; requires fresh adapter observations')

    def test_keyword_cannot_match_the_synonym_without_the_vector_lane(self):
        self.start()
        imported = self.import_episode()
        self.assertEqual(self.core.call('lookup', {'query': SYNONYM})['hits'], [])
        result = self.core.call('lookup', {'query': LITERAL})
        self.assertEqual([h['memory_id'] for h in result['hits']], [imported['memory_id']])
        self.assertEqual(result['hits'][0]['retrieval_channels'], ['keyword'])
        self.assertEqual(self.core.call('status')['embedding'],
                         {'connected': False, 'space_key': None, 'vector_count': 0})

    def test_backfill_indexes_what_import_could_not_and_is_idempotent(self):
        class Fragile(FakeEmbedder):
            broken = True

            def document(self, text):
                if self.broken:
                    raise TimeoutError('embedding endpoint not ready')
                return super().document(text)
        embedder = Fragile()
        self.start(embedder)
        imported = self.import_episode()
        self.assertEqual(self.core.call('status')['embedding']['vector_count'], 0)
        self.assertEqual(self.core.call('lookup', {'query': SYNONYM})['hits'], [])
        embedder.broken = False
        first = self.core.call('reembed', {'limit': 10})
        self.assertEqual((first['candidates'], first['indexed'], first['failed']), (1, 1, []))
        self.assertEqual(first['space_key'], embedder.space.key)
        again = self.core.call('reembed', {'limit': 10})
        self.assertEqual((again['candidates'], again['indexed']), (0, 0))
        self.assertEqual(self.core.call('status')['embedding']['vector_count'], 1)
        self.assertEqual([h['memory_id'] for h in self.core.call('lookup', {'query': SYNONYM})['hits']],
                         [imported['memory_id']])

    def test_failed_embedding_never_removes_the_episode(self):
        class Broken(FakeEmbedder):
            def document(self, text):
                raise TimeoutError('embedding endpoint unreachable')
        self.start(Broken())
        imported = self.import_episode()
        self.assertIn('memory_id', imported)
        self.assertEqual(self.core.call('status')['memory_count'], 1)
        self.assertEqual(self.core.call('status')['embedding']['vector_count'], 0)
        events = self.core.call('status')['events']
        self.assertTrue(any(e['payload'].get('type') == 'embedding.failed' for e in events))
        self.assertEqual([h['memory_id'] for h in self.core.call('lookup', {'query': LITERAL})['hits']],
                         [imported['memory_id']])

    def test_semantic_failure_degrades_to_keyword_with_a_warning(self):
        class Flaky(FakeEmbedder):
            def __init__(self):
                super().__init__()
                self.broken = False

            def query(self, text):
                if self.broken:
                    raise ConnectionError('blip')
                return super().query(text)
        embedder = Flaky()
        self.start(embedder)
        imported = self.import_episode()
        embedder.broken = True
        result = self.core.call('lookup', {'query': LITERAL})
        self.assertEqual([h['memory_id'] for h in result['hits']], [imported['memory_id']])
        self.assertTrue(any('semantic_unavailable' in w for w in result['warnings']))


    def test_index_embeds_the_observation_claim_not_the_summary(self):
        class Recording(FakeEmbedder):
            def __init__(self):
                super().__init__()
                self.documents = []

            def document(self, text):
                self.documents.append(text)
                return super().document(text)
        embedder = Recording()
        self.start(embedder)
        self.import_episode()
        self.assertEqual(len(embedder.documents), 1)
        text = embedder.documents[0]
        self.assertIn(LITERAL, text)
        self.assertNotIn('I attempted an action', text)
        self.assertNotIn('final world outcome is unknown', text)

    def test_semantic_floor_rejects_an_unrelated_query(self):
        self.start(FakeEmbedder())
        imported = self.import_episode()
        result = self.core.call('lookup', {'query': 'weather forecast'})
        self.assertEqual(result['hits'], [])
        self.assertIn('semantic_below_floor', result['warnings'])
        # The same query still finds it when the floor is lowered: the lane is
        # rejected by relevance, not by a broken vector.
        loose = self.core.call('lookup', {'query': 'weather forecast', 'min_similarity': 0.0})
        self.assertEqual([h['memory_id'] for h in loose['hits']], [imported['memory_id']])
        self.assertEqual(loose['hits'][0]['retrieval_channels'], ['semantic'])

    def test_floor_never_suppresses_the_keyword_lane(self):
        class KeywordOnly(FakeEmbedder):
            def document(self, text):
                # Orthogonal to the crate query: semantic always lands below the floor.
                return unit_vector([1.0, 0.0, 0.0, 0.0], 4)
        self.start(KeywordOnly())
        imported = self.import_episode()
        result = self.core.call('lookup', {'query': LITERAL})
        self.assertEqual([h['memory_id'] for h in result['hits']], [imported['memory_id']])
        self.assertEqual(result['hits'][0]['retrieval_channels'], ['keyword'])

    def test_floor_is_bounded(self):
        self.start(FakeEmbedder())
        self.import_episode()
        for bad in (1.5, -0.1, 'high', True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.core.call('lookup', {'query': LITERAL, 'min_similarity': bad})


class RewriteProvider(FixtureProvider):
    """Serves both the rewrite pass and the answer turn; records every prompt."""
    def __init__(self, rewrite=LITERAL + ' prop', mode='ok'):
        self.calls = []
        self.rewrite = rewrite
        self.mode = mode

    def generate(self, profile, prompt):
        self.calls.append(prompt)
        if 'Write a search query' in prompt:
            if self.mode == 'raise':
                raise ConnectionError('provider down')
            if self.mode == 'junk':
                return {'say': 'Sure! Here is a query: "crate".'}
            if self.mode == 'echo':
                return {'say': prompt.rsplit('MESSAGE: ', 1)[-1]}
            return {'say': self.rewrite, 'intent': {'kind': 'shell', 'command': 'NEVER_EXECUTE'}}
        remembered = 'HISTORICAL_RETRIEVAL: []' not in prompt
        return {'say': 'I remember the crate.' if remembered else 'I do not remember that.',
                'used_memory_ids':[h['memory_id'] for h in json.loads(prompt.split('HISTORICAL_RETRIEVAL: ',1)[1])][:1],
                'intent': {'kind': 'shell', 'command': 'NEVER_EXECUTE'}}


class Transport:
    def __init__(self):
        self.posts = []

    async def send(self, channel, body, **kwargs):
        self.posts.append((channel, body, kwargs))
        return str(700 + len(self.posts))


class RewriteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.provider = RewriteProvider()
        self.core = Core(self.root / 'character', provider=self.provider).start()
        self.imported = self.core.call('import', capture_fixture(self.root / 'episode'))
        self.transport = Transport()
        self.adapter = DiscordTextAdapter(GregoryCoreClient(self.core), self.transport,
            guild_id='1', channel_id='2', bot_id='3', users={'4'}, bots={'5'}).start()

    async def asyncTearDown(self):
        await self.adapter.close()
        if self.core.accepting:
            self.core.call('stop')
        self.core.thread.join(3)
        self.tmp.cleanup()

    async def turn(self, content, message_id='10'):
        future = self.adapter.offer(Message('1', '2', message_id, '4', content, time.time()))
        return await asyncio.wait_for(future, 6)

    async def test_literal_hit_never_spends_a_rewrite_call(self):
        await self.turn('gregory: ' + LITERAL)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertIn(self.imported['memory_id'], self.provider.calls[0])

    async def test_miss_on_nonempty_store_rewrites_then_answers_from_memory(self):
        await self.turn('gregory: what did you see back there')
        self.assertEqual(len(self.provider.calls), 2)
        self.assertIn('Write a search query', self.provider.calls[0])
        self.assertIn(self.imported['memory_id'], self.provider.calls[1])
        self.assertIn('not current state', self.transport.posts[0][1])

    async def test_rewrite_runs_on_its_own_correlation(self):
        result = await self.turn('gregory: what did you see back there')
        events = sorted(self.core.call('status')['events'], key=lambda e: e['seq'])
        requests = [e for e in events if e['payload'].get('type') == 'model.request']
        self.assertEqual(len(requests), 2)
        turn_correlation = result['correlation_id']
        self.assertEqual(requests[0]['correlation_id'],
                         str(uuid.uuid5(uuid.UUID(turn_correlation), 'retrieval-rewrite')))
        self.assertNotEqual(requests[0]['correlation_id'], turn_correlation)
        self.assertEqual(requests[1]['correlation_id'], turn_correlation)

    async def test_unusable_rewrite_falls_back_to_the_literal_query(self):
        for index, mode in enumerate(('raise', 'junk', 'echo')):
            self.provider.mode = mode
            self.provider.calls.clear()
            self.transport.posts.clear()
            await self.turn('gregory: nonsense phrase', message_id='1%d' % index)
            self.assertEqual(len(self.transport.posts), 1, mode)
            answer = self.provider.calls[-1]
            self.assertIn('QUESTION: nonsense phrase', answer, mode)
            self.assertIn('HISTORICAL_RETRIEVAL: []', answer, mode)
            self.assertNotIn('[Retrieval:', self.transport.posts[0][1], mode)

    async def test_rewrite_that_stays_a_miss_invents_nothing(self):
        self.provider.rewrite = 'blue elephant'
        await self.turn('gregory: what did you see back there')
        self.assertIn('HISTORICAL_RETRIEVAL: []', self.provider.calls[1])
        self.assertNotIn('[Retrieval:', self.transport.posts[0][1])


if __name__ == '__main__':
    unittest.main()
