# -*- coding: utf-8 -*-
"""
pattern_store.py · Pattern 层（抽象成功模式，向量检索）

检索：全表加载 → 余弦相似度 → 按 (score, human_verified, success_count) 排序。
数据量 <1 万条时纯 Python 足够；后续可替换为真实向量库（接口不变）。
"""
from typing import List, Optional

from ..db import pattern_to_row, row_to_pattern
from ..models import Pattern, pattern_index_text
from ..vector import cosine


class SearchHit:
    __slots__ = ("item", "score")

    def __init__(self, item, score):
        self.item = item
        self.score = score


class PatternStore:
    def __init__(self, db):
        self.db = db

    def insert(self, p: Pattern):
        self.db.execute(
            "INSERT OR REPLACE INTO patterns(id, title, cat, vuln_type, remediation, abstract,"
            " steps_json, embedding_json,"
            " hit_count, version, source_episodes_json, human_verified, success_count, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            tuple(pattern_to_row(p).values()),
        )
        return p

    def get(self, pid: str) -> Optional[Pattern]:
        rows = self.db.query("SELECT * FROM patterns WHERE id=?", (pid,))
        return row_to_pattern(rows[0]) if rows else None

    def update(self, p: Pattern):
        self.insert(p)

    def delete(self, pid: str):
        self.db.execute("DELETE FROM patterns WHERE id=?", (pid,))

    def _all(self) -> List[Pattern]:
        return [row_to_pattern(r) for r in self.db.query("SELECT * FROM patterns")]

    def search(self, embedding: List[float], top_k: int = 5) -> List[SearchHit]:
        hits = []
        for p in self._all():
            if not p.embedding:
                continue
            score = cosine(embedding, p.embedding)
            if score <= 0:
                continue
            hits.append(SearchHit(p, round(score, 4)))
        # 排序权重：human_verified > success_count > 向量相似度
        hits.sort(key=lambda h: (int(h.item.human_verified), h.item.success_count, h.score), reverse=True)
        return hits[:top_k]

    def search_by_text(self, text: str, top_k: int = 5, embedder=None) -> List[SearchHit]:
        if embedder is None:
            from ..embed import EmbedService
            embedder = EmbedService()
        return self.search(embedder.embed(str(text)), top_k)

    def list_all(self):
        return self._all()

    def count(self) -> int:
        return self.db.query("SELECT COUNT(*) AS n FROM patterns")[0]["n"]
