"""Shared, opt-in generation budget for local reasoning models.

The token cap includes private reasoning, not just the final answer. Defaults
preserve the original request limits; configure before starting worker threads.
"""
import math

_min_tokens = 0
_timeout = 8.0
_reasoning = 'default'


def configure(min_tokens=0, timeout=8.0, reasoning='default'):
    global _min_tokens, _timeout, _reasoning
    if isinstance(min_tokens, bool) or not isinstance(min_tokens, int) or not 0 <= min_tokens <= 8192:
        raise ValueError('model minimum tokens must be an integer from 0 to 8192')
    if not math.isfinite(timeout) or not 0 < timeout <= 120:
        raise ValueError('model timeout must be finite and between 0 and 120 seconds')
    if reasoning not in {'default', 'off'}:
        raise ValueError('model reasoning must be default or off')
    _min_tokens, _timeout = min_tokens, float(timeout)
    _reasoning = reasoning


def post_chat(url, *, json, timeout=8):
    import requests
    body = dict(json)
    body['max_tokens'] = max(body.get('max_tokens', 0), _min_tokens)
    if _reasoning == 'off':
        # Verified against this deployment's LM Studio Chat Completions endpoint.
        body['reasoning_effort'] = 'none'
    return requests.post(url, json=body, timeout=max(timeout, _timeout))
