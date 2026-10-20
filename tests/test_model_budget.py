import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deployments' / 'oldpc'))
import greg_model


class ModelBudget(unittest.TestCase):
    def tearDown(self):
        greg_model.configure()

    def request(self, body):
        post = Mock(return_value='response')
        with patch.dict(sys.modules, requests=SimpleNamespace(post=post)):
            self.assertEqual(greg_model.post_chat('local', json=body), 'response')
        return post.call_args.kwargs

    def test_default_preserves_existing_limits(self):
        args = self.request({'model':'local-model', 'max_tokens':32})
        self.assertEqual(args['json']['max_tokens'], 32)
        self.assertEqual(args['timeout'], 8)
        self.assertNotIn('reasoning_effort', args['json'])

    def test_reasoning_off_is_explicit_and_reversible(self):
        greg_model.configure(0, 8, 'off')
        body = {'model':'google/gemma-4-12b-qat', 'max_tokens':200}
        self.assertEqual(self.request(body)['json']['reasoning_effort'], 'none')
        self.assertNotIn('reasoning_effort', body)
        greg_model.configure()
        self.assertNotIn('reasoning_effort', self.request(body)['json'])

    def test_unknown_reasoning_setting_rejected(self):
        with self.assertRaises(ValueError): greg_model.configure(0, 8, 'guess')

    def test_reasoning_budget_does_not_mutate_caller_or_change_model(self):
        greg_model.configure(1024, 30)
        body = {'model':'google/gemma-4-12b-qat', 'max_tokens':32}
        args = self.request(body)
        self.assertEqual(args['json']['max_tokens'], 1024)
        self.assertEqual(args['json']['model'], body['model'])
        self.assertEqual(args['timeout'], 30)
        self.assertEqual(body['max_tokens'], 32)

    def test_larger_existing_budget_is_not_reduced(self):
        greg_model.configure(1024, 30)
        self.assertEqual(self.request({'max_tokens':2048})['json']['max_tokens'], 2048)

    def test_invalid_limits_rejected(self):
        for value in [-1, 8193, True, 2.5]:
            with self.assertRaises(ValueError): greg_model.configure(value, 30)
        for value in [0, -1, 121, float('nan'), float('inf')]:
            with self.assertRaises(ValueError): greg_model.configure(1024, value)
