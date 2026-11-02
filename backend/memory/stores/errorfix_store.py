# -*- coding: utf-8 -*-
"""
errorfix_store.py · ErrorFix 层（错误特征 → 修正策略，向量检索）
"""
from typing import List, Optional

from ..db import errorfix_to_row, row_to_errorfix
from ..models import ErrorFix, errorfix_index_text
from ..vector import cosine


class SearchHit:
    __slots__ = ("item", "score")

    def __init__(self, item, score):
        self.item = item
        self.score = score


class ErrorFixStore:
    def __init__(self, db):
        self.db = db

    def insert(self, e: ErrorFix):
        self.db.execute(
            "INSERT OR REPLACE INTO error_fixes(id, source_episodes_json, error_type,"
            " error_signature, fix_strategy, applies_to_json, embedding_json, hit_count,"
            " human_verified, success_count, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            tuple(errorfix_to_row(e).values()),
        )
        return e

    def get(self, eid: str) -> Optional[ErrorFix]:
        rows = self.db.query("SELECT * FROM error_fixes WHERE id=?", (eid,))
        return row_to_errorfix(rows[0]) if rows else None

    def update(self, e: ErrorFix):
        self.insert(e)

    def delete(self, eid: str):
        self.db.execute("DELETE FROM error_fixes WHERE id=?", (eid,))

    def _all(self) -> List[ErrorFix]:
        return [row_to_errorfix(r) for r in self.db.query("SELECT * FROM error_fixes")]

    def search(self, embedding: List[float], top_k: int = 5) -> List[SearchHit]:
        hits = []
        for e in self._all():
            if not e.embedding:
                continue
            score = cosine(embedding, e.embedding)
            if score <= 0:
                continue
            hits.append(SearchHit(e, round(score, 4)))
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
        return self.db.query("SELECT COUNT(*) AS n FROM error_fixes")[0]["n"]
