"""Text embedding.

The platform must be able to do semantic retrieval with no external provider
configured, so the default embedder is deterministic and local: a hashed
character/word n-gram projection into a fixed-dimension unit vector.

It is genuinely useful for near-duplicate and topical retrieval within a brand's
own memory, and it is honest about what it is — it is *not* a learned semantic
model, and :attr:`Embedder.quality` says so.  A provider-backed embedder
implements the same interface and is selected by configuration.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from abc import ABC, abstractmethod

from seo_engine.domain.models.memory import EMBEDDING_DIM

_TOKEN = re.compile(r"[a-z0-9']+")


def tokenise(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


class Embedder(ABC):
    model: str
    dimensions: int
    #: "lexical" or "semantic" — surfaced so retrieval quality is never overstated.
    quality: str

    @abstractmethod
    def embed(self, text: str) -> list[float]: ...

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class HashingEmbedder(Embedder):
    """Deterministic local embedder.  No network, no credentials, no drift."""

    model = "hashing-v1"
    quality = "lexical"

    def __init__(self, dimensions: int = EMBEDDING_DIM) -> None:
        self.dimensions = dimensions

    def _bucket(self, token: str, salt: str = "") -> int:
        digest = hashlib.blake2b(f"{salt}{token}".encode(), digest_size=8).digest()
        return int.from_bytes(digest, "big") % self.dimensions

    def _sign(self, token: str) -> float:
        digest = hashlib.blake2b(token.encode(), digest_size=1).digest()
        return 1.0 if digest[0] % 2 == 0 else -1.0

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = tokenise(text)
        if not tokens:
            # A zero vector has no direction; pgvector cosine distance is
            # undefined for it, so anchor empty text to a fixed basis instead.
            vector[0] = 1.0
            return vector

        # Unigrams carry topic; bigrams carry a little word order.
        for token in tokens:
            vector[self._bucket(token)] += self._sign(token)
        for left, right in itertools.pairwise(tokens):
            bigram = f"{left}_{right}"
            vector[self._bucket(bigram, salt="bi:")] += 0.5 * self._sign(bigram)

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:  # pragma: no cover - collisions cancelling exactly
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    return max(-1.0, min(1.0, dot))


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = HashingEmbedder()
    return _embedder


def set_embedder(embedder: Embedder | None) -> None:
    global _embedder
    _embedder = embedder


__all__ = [
    "Embedder",
    "HashingEmbedder",
    "cosine_similarity",
    "get_embedder",
    "set_embedder",
    "tokenise",
]
