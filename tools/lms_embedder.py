#!/usr/bin/env python3
"""Host-layer embedder for Core: HTTP to a pinned local model server.

`gregory_core.embeddings` stays transport-free by design; this module is the one
place that talks to a model server. The weights are pinned by revision, so a
re-quantized or replaced file produces a different space key and can never be
compared against vectors built from the old bytes.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gregory_core.embeddings import LocalNomic

# nomic-embed-text-v2-moe is a 512-token model; LM Studio also advertises 512 for
# the official Q6_K. Keep the input bounded here rather than trusting the server.
MAX_INPUT_CHARS = 2000
MAX_BATCH = 64
PINNED_MODEL = 'nomic-ai/nomic-embed-text-v2-moe'


class EmbeddingUnavailable(RuntimeError):
    """Typed transport failure: callers degrade to keyword, never invent vectors."""


def build_embedder(endpoint, *, model_id, revision, timeout=10.0):
    if not endpoint or not model_id or not revision:
        raise ValueError('explicit endpoint, model id and revision required')
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
        raise ValueError('bounded embedding timeout required')
    url = endpoint.rstrip('/') + '/embeddings'

    def encode(texts):
        if not isinstance(texts, list) or not 1 <= len(texts) <= MAX_BATCH:
            raise ValueError('bounded embedding batch required')
        if any(not isinstance(t, str) or not t or len(t) > MAX_INPUT_CHARS for t in texts):
            raise ValueError('bounded embedding input required')
        body = json.dumps({'model': model_id, 'input': texts}).encode('utf8')
        request = urllib.request.Request(url, data=body,
                                         headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
            data = payload['data']
            if len(data) != len(texts):
                raise EmbeddingUnavailable('embedding count mismatch')
            ordered = sorted(data, key=lambda item: item.get('index', 0))
            return [item['embedding'] for item in ordered]
        except EmbeddingUnavailable:
            raise
        except urllib.error.HTTPError as exc:
            raise EmbeddingUnavailable('embedding http ' + str(exc.code)) from exc
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
            raise EmbeddingUnavailable('embedding unavailable: ' + type(exc).__name__) from exc

    return LocalNomic(encode, revision=revision, model=PINNED_MODEL)
