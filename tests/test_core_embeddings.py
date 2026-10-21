import unittest
from unittest.mock import Mock
from gregory_core.embeddings import EmbeddingSpace, LocalNomic, unit_vector
import test_core_memory as memory_tests
from _core_fixtures import FixtureEmbedder


class EmbeddingTests(unittest.TestCase):
    def test_local_nomic_prefixes_full_dimensions_and_no_automatic_loading(self):
        encode = Mock(return_value=[[2.0] + [0.0]*767])
        backend = LocalNomic(encode, revision='fixture-only-NOT-model-acceptance')
        encode.assert_not_called()
        self.assertEqual(backend.document('episode')[0], 1)
        self.assertEqual(encode.call_args.args[0], ['search_document: episode'])
        backend.query('question')
        self.assertEqual(encode.call_args.args[0], ['search_query: question'])

    def test_model_revision_dimensions_and_profile_isolate_spaces(self):
        a = EmbeddingSpace('nomic-v1', 'rev1')
        self.assertNotEqual(a.key, EmbeddingSpace('nomic-v1', 'rev2').key)
        self.assertNotEqual(a.key, EmbeddingSpace('nomic-v2', 'rev1').key)
        self.assertNotEqual(a.key, EmbeddingSpace('nomic-v1', 'rev1', dimensions=256).key)
        with self.assertRaises(ValueError):LocalNomic(lambda x:x, revision='x', model='remote-unknown')

    def test_invalid_vectors_never_normalized_into_plausible_values(self):
        for values in ([0,0], [float('nan'),1], [float('inf'),1], [1]):
            with self.assertRaises(ValueError):unit_vector(values, 2)


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.fixture = memory_tests.MemoryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store

    def test_semantic_fixture_finds_a_lexical_miss_and_explains_channel(self):
        key, _, _, _ = self.fixture.episode()
        self.store.correct(key, 'synthetic orchard episode', actor='owner', reason='fixture')
        self.store.index(key, FixtureEmbedder(), actor='owner')
        self.assertFalse(self.store.search('fruit', actor='owner')['hits'])
        result = self.store.search('fruit', actor='owner', embedder=FixtureEmbedder())
        self.assertEqual(result['hits'][0]['memory_id'], key)
        self.assertEqual(result['hits'][0]['retrieval_channels'], ['semantic'])

    def test_hybrid_fusion_preserves_both_lane_explanations(self):
        key, _, _, _ = self.fixture.episode()
        self.store.index(key, FixtureEmbedder(), actor='owner')
        hit = self.store.search('follow', actor='owner', embedder=FixtureEmbedder())['hits'][0]
        self.assertEqual(hit['retrieval_channels'], ['keyword', 'semantic'])

    def test_semantic_failure_returns_explicit_keyword_fallback(self):
        self.fixture.episode()
        broken = FixtureEmbedder();broken.query = Mock(side_effect=RuntimeError('private details'))
        result = self.store.search('follow', actor='owner', embedder=broken)
        self.assertEqual(len(result['hits']), 1)
        self.assertEqual(result['warnings'], ['semantic_unavailable:RuntimeError'])
        self.assertNotIn('private details', str(result))
        self.assertEqual(result['mode'], 'keyword')

    def test_different_model_revision_cannot_search_old_vectors(self):
        key, _, _, _ = self.fixture.episode()
        self.store.correct(key, 'synthetic orchard episode', actor='owner', reason='fixture')
        self.store.index(key, FixtureEmbedder(), actor='owner')
        newer = FixtureEmbedder();newer.space = EmbeddingSpace('synthetic-fixture-NOT-Nomic', 'fixture-v2', 3)
        result = self.store.search('fruit', actor='owner', embedder=newer)
        self.assertFalse(result['hits'])
        self.assertEqual(result['warnings'], ['no_vectors_for_selected_model_revision'])

    def test_bad_document_vectors_do_not_create_an_index_entry(self):
        key, _, _, _ = self.fixture.episode()
        invalid = FixtureEmbedder();invalid.document = lambda x:[0,0,0]
        with self.assertRaises(ValueError):self.store.index(key, invalid, actor='owner')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM vectors').fetchone()[0], 0)

    def test_correction_during_encoding_cannot_reinsert_stale_vector(self):
        key, _, _, _ = self.fixture.episode()
        backend = FixtureEmbedder()
        def encode(text):
            self.store.correct(key, 'new orchard correction', actor='owner', reason='concurrent fixture')
            return [1,0,0]
        backend.document = encode
        with self.assertRaises(ValueError):self.store.index(key, backend, actor='owner')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM vectors').fetchone()[0], 0)
