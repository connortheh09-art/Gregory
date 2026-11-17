"""Lean D1/L8: provider-boundary capture labels finalization calls as speech (null-only intent schema)."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'deployments' / 'oldpc')]

from gregory_core.decision_contract import envelope, obj, enum
from gregory_core.runtime import _call_kind, capture_model_call


def body(schema=None):
    b = dict(model='m', messages=[dict(role='system', content='sys'), dict(role='user', content='hello')])
    if schema is not None:
        b['response_format'] = dict(type='json_schema', json_schema=dict(name='gregory_decision', strict=True, schema=schema))
    return b


class CaptureKind(unittest.TestCase):
    def test_finalization_schema_is_speech_and_decisions_are_decisions(self):
        self.assertEqual(_call_kind(body(envelope([dict(type='null')]))), 'speech')
        self.assertEqual(_call_kind(body()), 'speech')
        choice = envelope([dict(type='null'), obj(dict(action=enum(['game_task']), kind=enum(['continue'])))])
        self.assertEqual(_call_kind(body(choice)), 'decision')

    def test_capture_writes_the_full_body_and_kind_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'calls.jsonl')
            capture_model_call(body(), 0, time.perf_counter(), error='x')  # disabled: no file, no raise
            self.assertFalse(os.path.exists(path))
            os.environ['GREG_MODEL_CAPTURE'] = path
            try:
                capture_model_call(body(envelope([dict(type='null')])), 1, time.perf_counter(), error='TimeoutError: t')
            finally:
                del os.environ['GREG_MODEL_CAPTURE']
            row = json.loads(open(path, encoding='utf8').read())
            self.assertEqual((row['kind'], row['attempt'], row['error']), ('speech', 1, 'TimeoutError: t'))
            self.assertEqual(row['body']['messages'][0], dict(role='system', content='sys'))


if __name__ == '__main__':
    unittest.main()
