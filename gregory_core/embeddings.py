"""Local-only embedding boundary; no HTTP clients, keys, downloads or model startup."""
from dataclasses import dataclass
import hashlib
import json
import math


def unit_vector(values, dimensions):
    values = tuple(float(v) for v in values)
    if len(values) != dimensions or not all(math.isfinite(v) for v in values):
        raise ValueError('invalid embedding dimensions or nonfinite values')
    norm = math.hypot(*values)
    if not norm or not math.isfinite(norm):
        raise ValueError('zero or invalid embedding norm')
    return tuple(v / norm for v in values)


@dataclass(frozen=True)
class EmbeddingSpace:
    model: str
    revision: str
    dimensions: int = 768
    document_prefix: str = 'search_document: '
    query_prefix: str = 'search_query: '
    normalization: str = 'l2-full-dimension-v1'

    def __post_init__(self):
        if not self.model or not self.revision or not 1 <= self.dimensions <= 4096:
            raise ValueError('explicit model, revision and valid dimensions required')

    @property
    def key(self):
        return hashlib.sha256(json.dumps(self.__dict__, sort_keys=True).encode()).hexdigest()


class LocalNomic:
    """Wrap an already-loaded LOCAL callable encode(list[str]) -> list[vectors].

    Full 768 dimensions only: no implicit Matryoshka truncation or cross-model mix.
    The host must pin model/weights/runtime and load it separately; this class
    neither imports an ML runtime nor connects to a model server.
    """
    def __init__(self, encode, *, revision, model='nomic-ai/nomic-embed-text-v1.5'):
        if model not in {'nomic-ai/nomic-embed-text-v1.5', 'nomic-ai/nomic-embed-text-v2-moe'}:
            raise ValueError('unsupported Nomic profile')
        self.space = EmbeddingSpace(model, revision)
        self._encode = encode

    def _one(self, text, prefix):
        output = self._encode([prefix + text])
        if len(output) != 1:
            raise ValueError('expected exactly one embedding')
        return unit_vector(output[0], self.space.dimensions)

    def document(self, text):
        return self._one(text, self.space.document_prefix)

    def query(self, text):
        return self._one(text, self.space.query_prefix)
