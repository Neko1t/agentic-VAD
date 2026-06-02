from __future__ import annotations

import hashlib
import math
import re
from typing import List, Sequence


class EmbeddingBuilder:
    """Embedding wrapper with a deterministic local fallback."""

    def __init__(self, model_name: str = "BAAI/bge-base-en-v1.5", vector_dim: int = 64):
        self.model_name = model_name
        self.vector_dim = vector_dim
        self._model = None
        self._load_error = None

    def _get_model(self):
        if self._model is not None or self._load_error is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        except Exception as exc:  # pragma: no cover - optional dependency path
            self._load_error = exc
            self._model = None
        return self._model

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        model = self._get_model()
        if model is not None:
            vectors = model.encode(list(texts), normalize_embeddings=True)
            return [list(map(float, vector)) for vector in vectors]
        return [self._fallback_embed(text) for text in texts]

    def _fallback_embed(self, text: str) -> List[float]:
        vector = [0.0] * self.vector_dim
        tokens = re.findall(r"[a-z0-9_]+", text.lower())
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.vector_dim
            vector[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]
