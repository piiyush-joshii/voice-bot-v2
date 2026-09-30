"""Embedder interface with the MiniLM implementation and a dependency-free fake for tests."""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray:
        """Returns L2-normalized embeddings, shape (len(texts), dim)."""
        ...


class MiniLMEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name, device="cpu")

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self._model.encode(texts, normalize_embeddings=True, convert_to_numpy=True))


class HashingEmbedder:
    """Bag-of-words hashing embedder. Deterministic and offline; used only in tests."""

    def __init__(self, dim: int = 512):
        self._dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self._dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for word in re.findall(r"[a-z]+", text.lower()):
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                out[i, h % self._dim] += 1.0
            norm = np.linalg.norm(out[i])
            if norm:
                out[i] /= norm
        return out


def build_embedder(model_name: str) -> Embedder:
    return MiniLMEmbedder(model_name)
