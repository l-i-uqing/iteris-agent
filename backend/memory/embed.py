# -*- coding: utf-8 -*-
"""
embed.py · 向量化服务

本期默认 MockEmbedding（确定性 n-gram 哈希）跑通链路；
预留 set_backend("llm", ...) 切到真实 LLM embedding（下一阶段接 /api/embed）。
"""
from typing import List

from .vector import MockEmbedding, normalize


class EmbedService:
    def __init__(self, backend: str = "mock", dim: int = 96):
        self.backend = backend
        self._mock = MockEmbedding(dim=dim)
        self._llm_fn = None

    def set_backend(self, backend: str, llm_fn=None):
        """切到真实 embedding：llm_fn(texts: List[str]) -> List[List[float]]"""
        self.backend = backend
        if llm_fn is not None:
            self._llm_fn = llm_fn

    def embed(self, text: str) -> List[float]:
        if self.backend == "llm" and self._llm_fn is not None:
            return normalize(self._llm_fn([str(text)])[0])
        return self._mock.embed(text)

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        if self.backend == "llm" and self._llm_fn is not None:
            return [normalize(v) for v in self._llm_fn([str(t) for t in texts])]
        return self._mock.embed_many(texts)
