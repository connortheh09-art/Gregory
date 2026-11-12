"""Independent regression contract for the observed Discord provider failure.

No endpoint, token, authoritative database, or Discord SDK is used here.
Empty final content may be retried once; reasoning is never a final reply.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gregory_core.runtime import Core, LMStudioProvider
from gregory_core.provider_reply import ProviderReplyError


class FinalMessage(dict):
    """Trap attempts to use a private reasoning field, even without logging it."""

    def __getitem__(self, key):
        if key in {'reasoning', 'reasoning_content'}:
            raise AssertionError('Private reasoning must not be accessed')
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key in {'reasoning', 'reasoning_content'}:
            raise AssertionError('Private reasoning must not be accessed')
        return super().get(key, default)


class Response:
    def __init__(self, content, finish_reason='stop'):
        self.value = {'choices': [{'finish_reason': finish_reason,
            'message': FinalMessage(content=content,
                reasoning_content='{"say":"PRIVATE reasoning is not speech"}')}]}

    def raise_for_status(self):
        pass

    def json(self):
        return self.value


class ProviderReplyContractTests(unittest.TestCase):
    def setUp(self):
        self.provider = LMStudioProvider('http://127.0.0.1:1234/v1/chat/completions', 'test-gemma')
        self.profile = {'persona': 'Test character', 'goals': []}

    def generate(self):
        return self.provider.generate(self.profile, 'Test-only prompt')

    def test_valid_final_reply_does_not_read_reasoning_or_retry(self):
        with patch('greg_model.post_chat', return_value=Response('{"say":"hello"}')) as post:
            self.assertEqual(self.generate(), {'say': 'hello'})
        self.assertEqual(post.call_count, 1)

    def test_empty_final_content_recovers_with_one_retry(self):
        for empty in ('', None, '  \n'):
            with self.subTest(empty=empty), patch('greg_model.post_chat',
                    side_effect=[Response(empty), Response('{"say":"recovered"}')]) as post:
                self.assertEqual(self.generate(), {'say': 'recovered'})
                self.assertEqual(post.call_count, 2)
                self.assertNotIn('chat_template_kwargs', post.call_args_list[0].kwargs['json'])
                self.assertEqual(post.call_args_list[1].kwargs['json']['chat_template_kwargs'],
                    {'enable_thinking': False})
                self.assertEqual(post.call_args_list[1].kwargs['json']['reasoning_effort'], 'none')

    def test_complete_outer_json_or_bare_fence_is_accepted(self):
        for opening in ('```json', '```', '```JSON'):
            text = ' \n' + opening + '\r\n{\r\n "say": "brace } and backtick ` are text"\r\n}\r\n```\n '
            with self.subTest(opening=opening), patch('greg_model.post_chat', return_value=Response(text)) as post:
                self.assertEqual(self.generate(), {'say': 'brace } and backtick ` are text'})
                self.assertEqual(post.call_count, 1)

    def test_arbitrary_prose_incomplete_or_multiple_fences_are_not_scanned(self):
        for text in ('Here is my answer: {"say":"no"}',
                '```json\n{"say":"no"}', '```python\n{"say":"no"}\n```',
                '```json\n{"say":"no"}\n```\nExtra text',
                '```json\n{"say":"no"}\n```\n```json\n{"say":"also no"}\n```'):
            with self.subTest(text=text), patch('greg_model.post_chat', return_value=Response(text)) as post:
                with self.assertRaises(ProviderReplyError):
                    self.generate()
                self.assertEqual(post.call_count, 1)

    def test_two_empty_responses_fail_bounded_without_reasoning_substitution(self):
        with patch('greg_model.post_chat', side_effect=[Response(''), Response('')]) as post:
            with self.assertRaises(ProviderReplyError) as caught:
                self.generate()
        self.assertEqual(post.call_count, 2)
        self.assertNotIn('PRIVATE', str(caught.exception))

    def test_retry_uses_remaining_transport_budget_and_does_not_mutate_globals(self):
        import greg_model
        before = greg_model._min_tokens, greg_model._timeout, greg_model._reasoning
        with patch('greg_model.post_chat', side_effect=[Response(''), Response('{"say":"ok"}')]) as post:
            with patch('gregory_core.runtime.time.monotonic', side_effect=[100, 101, 111]):
                self.assertEqual(self.generate(), {'say': 'ok'})
        self.assertEqual([call.kwargs['timeout'] for call in post.call_args_list], [29, 19])
        self.assertEqual(before, (greg_model._min_tokens, greg_model._timeout, greg_model._reasoning))

    def test_expired_budget_does_not_start_a_second_request(self):
        with patch('greg_model.post_chat', return_value=Response('')) as post:
            with patch('gregory_core.runtime.time.monotonic', side_effect=[100, 101, 131]):
                with self.assertRaisesRegex(ProviderReplyError, 'provider_reply_deadline'):
                    self.generate()
        self.assertEqual(post.call_count, 1)

    def test_transport_failure_is_not_retried_as_empty_content(self):
        with patch('greg_model.post_chat', side_effect=TimeoutError('test transport')) as post:
            with self.assertRaises(TimeoutError):
                self.generate()
        self.assertEqual(post.call_count, 1)

    def test_failure_is_correlated_without_private_text_and_next_turn_can_complete(self):
        correlation = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as directory:
            core = Core(Path(directory) / 'character', provider=self.provider).start()
            try:
                with patch('greg_model.post_chat', side_effect=[Response(''), Response('')]):
                    with self.assertRaises(ProviderReplyError):
                        core.call('think', {'prompt': 'test only', 'correlation_id': correlation})
                events = core.call('correlation', {'correlation_id': correlation})['events']
                self.assertTrue(any(row['kind'] == 'error' and
                    row['payload'].get('error_category') == 'ProviderReplyError' for row in events))
                self.assertFalse(any(row['kind'] in ('inference', 'decision') for row in events))
                self.assertNotIn('PRIVATE', json.dumps(events))
                with patch('greg_model.post_chat', return_value=Response('```json\n{"say":"next turn"}\n```')):
                    result = core.call('think', {'prompt': 'another test-only turn'})
                self.assertEqual(result['say'], 'next turn')
                self.assertFalse(result['dispatched'])
            finally:
                if core.accepting:
                    stopped = core.call('stop')
                    self.assertTrue(stopped['databases_closed'])
                core.thread.join(5)

    def test_valid_looking_but_truncated_content_is_not_accepted(self):
        with patch('greg_model.post_chat', return_value=Response('{"say":"partial"}', 'length')):
            with self.assertRaises(ValueError):
                self.generate()

    def test_malformed_or_non_dialogue_final_output_is_refused(self):
        for text in ('not JSON', '[]', 'null', '{}', '{"say":null}',
                '{"say":123}', '{"say":""}', '{"say":"  "}',
                '{"say":"hello","shell":"execute"}'):
            with self.subTest(text=text), patch('greg_model.post_chat', return_value=Response(text)):
                with self.assertRaises(ValueError):
                    self.generate()

    def test_oversized_final_reply_is_refused(self):
        with patch('greg_model.post_chat', return_value=Response(json.dumps({'say': 'x' * 3000}))):
            with self.assertRaises(ValueError):
                self.generate()


if __name__ == '__main__':
    unittest.main()
