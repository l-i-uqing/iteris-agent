# -*- coding: utf-8 -*-
"""
insight_store.py · Insight 层（发现思路，向量检索）
检索：全表加载 → 余弦相似度 → 按 (score, human_verified, success_count) 排序。
"""
from typing import List, Optional

from ..db import insight_to_row, row_to_insight
from ..models import Insight, insight_index_text
from ..vector import cosine


class SearchHit:
    __slots__ = ("item", "score")

    def __init__(self, item, score):
        self.item = item
        self.score = score


class InsightStore:
    def __init__(self, db):
        self.db = db

    def insert(self, i: Insight):
        self.db.execute(
            "INSERT OR REPLACE INTO insights(id, app_type, tech_stack_json,"
            " feature_points_json, mindset, source_episodes_json, embedding_json,"
            " hit_count, human_verified, success_count, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            tuple(insight_to_row(i).values()),
        )
        return i

    def get(self, iid: str) -> Optional[Insight]:
        rows = self.db.query("SELECT * FROM insights WHERE id=?", (iid,))
        return row_to_insight(rows[0]) if rows else None

    def update(self, i: Insight):
        self.insert(i)

    def delete(self, iid: str):
        self.db.execute("DELETE FROM insights WHERE id=?", (iid,))

    def _all(self) -> List[Insight]:
        return [row_to_insight(r) for r in self.db.query("SELECT * FROM insights")]

    def search(self, embedding: List[float], top_k: int = 5) -> List[SearchHit]:
        hits = []
        for i in self._all():
            if not i.embedding:
                continue
            score = cosine(embedding, i.embedding)
            if score <= 0:
                continue
            hits.append(SearchHit(i, round(score, 4)))
        hits.sort(key=lambda h: (int(h.item.human_verified), h.item.success_count, h.score), reverse=True)
        return hits[:top_k]

    def list_all(self):
        return self._all()

    def count(self) -> int:
        return self.db.query("SELECT COUNT(*) AS n FROM insights")[0]["n"]
