# -*- coding: utf-8 -*-
"""
vector.py · 纯 Python 向量工具（零依赖，无 numpy）

- cosine：余弦相似度
- normalize：L2 归一化
- MockEmbedding：确定性 n-gram 哈希向量（相似文本 → 相似向量，用于 mock 跑通链路）
  真实场景下由 embed.EmbedService 切换到 LLM embedding，维度可变，接口不变。
"""
import math
import re
from typing import List


def normalize(v: List[float]) -> List[float]:
    n = math.sqrt(sum(x * x for x in v))
    if n == 0:
        return v
    return [x / n for x in v]


def cosine(a: List[float], b: List[float]) -> float:
    """余弦相似度（两向量均应为归一化向量，或任一方为空返回 0）"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    for x, y in zip(a, b):
        dot += x * y
    return dot


class MockEmbedding:
    """确定性 mock 向量：字符 n-gram 哈希到 D 维桶，归一化。
    相似文本共享 n-gram → 余弦得分高，足以支撑去重/检索的链路验证。
    """

    DIM = 96

    def __init__(self, dim: int = DIM, ngram: int = 2):
        self.dim = dim
        self.ngram = ngram

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        s = re.sub(r"\s+", "", str(text or "")).lower()
        if not s:
            return vec
        grams = [s[i:i + self.ngram] for i in range(len(s) - self.ngram + 1)]
        if not grams:
            grams = [s]
        for g in grams:
            h = hash(g) & 0xFFFFFFFF
            idx = h % self.dim
            sign = 1.0 if (h >> 30) & 1 else -1.0
            vec[idx] += sign
        return normalize(vec)

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(t) for t in texts]
