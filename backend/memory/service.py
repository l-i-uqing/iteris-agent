# -*- coding: utf-8 -*-
"""
service.py · MemoryService 门面

对外统一接口（契约）：
  写入（含去重）
    insert_pattern(pattern) -> InsertResult
    insert_error_fix(ef)    -> InsertResult
    insert_gold(gold)       -> InsertResult   （Gold 走指纹精确查重，不走向量）
  读取
    search_patterns(situation, top_k)  -> List[dict]
    search_error_fixes(error_text, top_k) -> List[dict]
    exact_match_gold(fingerprint)      -> Gold | None
  CRUD
    get/delete/list × pattern / error_fix / gold
"""
import time
from typing import List, Optional

from .. import config
from .db import MemoryDB
from .dedup import DedupService
from .embed import EmbedService
from .models import ErrorFix, Episode, Gold, Insight, Pattern, errorfix_index_text, insight_index_text, pattern_index_text
from .stores.episode_store import EpisodeStore
from .stores.errorfix_store import ErrorFixStore
from .stores.gold_store import GoldStore
from .stores.insight_store import InsightStore
from .stores.pattern_store import PatternStore
from .stores.pending_store import PendingItem, PendingStore
from .graph import VulnGraphService


class InsertResult:
    __slots__ = ("action", "id", "reason", "score", "candidates")

    def __init__(self, action, item_id=None, reason="", score=0.0, candidates=None):
        self.action = action          # insert | merge | update | conflict
        self.id = item_id
        self.reason = reason
        self.score = score
        self.candidates = candidates or []

    def to_dict(self):
        return {
            "action": self.action, "id": self.id, "reason": self.reason,
            "score": self.score,
            "candidates": [
                {"id": c.item.id, "title": getattr(c.item, "title", "") or getattr(c.item, "error_type", ""),
                 "score": c.score}
                for c in self.candidates
            ],
        }


class MemoryService:
    def __init__(self, db_path=None, embed_backend: str = "mock", judge=None):
        self.db = MemoryDB(db_path or (config.DATA_DIR / "memory.db"))
        self.db.init_schema()
        self.embedder = EmbedService(backend=embed_backend)
        self.patterns = PatternStore(self.db)
        self.insights = InsightStore(self.db)
        self.errorfixes = ErrorFixStore(self.db)
        self.gold = GoldStore(self.db)
        self.episodes = EpisodeStore(self.db)
        self.pending = PendingStore(self.db)
        self.dedup = DedupService(judge=judge)
        self.graph = VulnGraphService(self.db)

    # ================= 写入（含去重） =================

    def _fill_pattern_embedding(self, p: Pattern) -> Pattern:
        if not p.embedding:
            p.embedding = self.embedder.embed(pattern_index_text(p))
        return p

    def _fill_errorfix_embedding(self, e: ErrorFix) -> ErrorFix:
        if not e.embedding:
            e.embedding = self.embedder.embed(errorfix_index_text(e))
        return e

    def insert_pattern(self, p: Pattern) -> InsertResult:
        self._fill_pattern_embedding(p)
        top = self.patterns.search(p.embedding, top_k=5)
        dec = self.dedup.decide("pattern", p, top)
        if dec.action == "insert":
            self.patterns.insert(p)
            return InsertResult("insert", p.id, dec.reason, dec.score, top)
        if dec.action == "merge":
            t = self.patterns.get(dec.target_id)
            t = self.dedup.apply_merge(t, p, "pattern")
            self.patterns.update(t)
            return InsertResult("merge", t.id, dec.reason, dec.score, top)
        if dec.action == "update":
            t = self.patterns.get(dec.target_id)
            t = self.dedup.apply_update(t, p, "pattern")
            self.patterns.update(t)
            return InsertResult("update", t.id, dec.reason, dec.score, top)
        # conflict：不写入，返回相近候选供上层/人工裁决
        return InsertResult("conflict", None, dec.reason, dec.score, top)

    def insert_error_fix(self, e: ErrorFix) -> InsertResult:
        self._fill_errorfix_embedding(e)
        top = self.errorfixes.search(e.embedding, top_k=5)
        dec = self.dedup.decide("error_fix", e, top)
        if dec.action == "insert":
            self.errorfixes.insert(e)
            return InsertResult("insert", e.id, dec.reason, dec.score, top)
        if dec.action == "merge":
            t = self.errorfixes.get(dec.target_id)
            t = self.dedup.apply_merge(t, e, "error_fix")
            self.errorfixes.update(t)
            return InsertResult("merge", t.id, dec.reason, dec.score, top)
        if dec.action == "update":
            t = self.errorfixes.get(dec.target_id)
            t = self.dedup.apply_update(t, e, "error_fix")
            self.errorfixes.update(t)
            return InsertResult("update", t.id, dec.reason, dec.score, top)
        return InsertResult("conflict", None, dec.reason, dec.score, top)

    def insert_insight(self, i: Insight) -> InsertResult:
        if not i.embedding:
            i.embedding = self.embedder.embed(insight_index_text(i))
        top = self.insights.search(i.embedding, top_k=5)
        dec = self.dedup.decide("insight", i, top)
        if dec.action == "insert":
            self.insights.insert(i)
            return InsertResult("insert", i.id, dec.reason, dec.score, top)
        if dec.action == "merge":
            t = self.insights.get(dec.target_id)
            t = self.dedup.apply_merge(t, i, "insight")
            self.insights.update(t)
            return InsertResult("merge", t.id, dec.reason, dec.score, top)
        if dec.action == "update":
            t = self.insights.get(dec.target_id)
            t = self.dedup.apply_update(t, i, "insight")
            self.insights.update(t)
            return InsertResult("update", t.id, dec.reason, dec.score, top)
        return InsertResult("conflict", None, dec.reason, dec.score, top)

    def insert_gold(self, g: Gold) -> InsertResult:
        """Gold 精确查重：指纹 hash 命中 → 计数 +1 不新增；否则插入"""
        exist = self.gold.exact_match(g.fingerprint)
        if exist is not None:
            self.gold.increment_hit(exist.id)
            return InsertResult("merge", exist.id, "指纹已存在（%s），命中计数 +1" % exist.payload, 1.0)
        self.gold.insert(g)
        return InsertResult("insert", g.id, "新指纹入库")

    # ================= 读取 =================

    def search_insights(self, situation: str, top_k: int = 3) -> List[dict]:
        vec = self.embedder.embed(situation)
        hits = self.insights.search(vec, top_k)
        out = [self._hit_dict("insight", h.item, h.score) for h in hits]
        # 兜底：弱向量/mock 环境下按关键词匹配 app_type / tech_stack / mindset
        if len(out) < top_k:
            import re as _re
            kw = [w for w in _re.findall(r"[一-龥]{2,}|[A-Za-z]{3,}", str(situation))
                  if w.lower() not in {"flag", "http", "https", "www", "com", "admin", "html", "php"}]
            for ins in self.insights.list_all():
                if len(out) >= top_k:
                    break
                blob = (ins.app_type + " " + " ".join(ins.tech_stack) + " " + ins.mindset).lower()
                if any(k.lower() in blob for k in kw) and not any(o["id"] == ins.id for o in out):
                    out.append(self._hit_dict("insight", ins, 0.5))
        return out

    def search_patterns(self, situation: str, top_k: int = 5) -> List[dict]:
        vec = self.embedder.embed(situation)
        hits = self.patterns.search(vec, top_k)
        return [self._hit_dict("pattern", h.item, h.score) for h in hits]

    def search_error_fixes(self, error_text: str, top_k: int = 5) -> List[dict]:
        vec = self.embedder.embed(error_text)
        hits = self.errorfixes.search(vec, top_k)
        return [self._hit_dict("error_fix", h.item, h.score) for h in hits]

    def exact_match_gold(self, fingerprint: dict) -> Optional[Gold]:
        return self.gold.exact_match(fingerprint)

    @staticmethod
    def _hit_dict(kind, item, score) -> dict:
        d = item.model_dump()
        d["score"] = score
        return d

    # ================= CRUD =================

    def get_pattern(self, pid: str) -> Optional[Pattern]:
        return self.patterns.get(pid)

    def delete_pattern(self, pid: str) -> bool:
        existed = self.patterns.get(pid) is not None
        if existed:
            self.patterns.delete(pid)
        return existed

    def get_error_fix(self, eid: str) -> Optional[ErrorFix]:
        return self.errorfixes.get(eid)

    def delete_error_fix(self, eid: str) -> bool:
        existed = self.errorfixes.get(eid) is not None
        if existed:
            self.errorfixes.delete(eid)
        return existed

    def get_gold(self, gid: str) -> Optional[Gold]:
        return self.gold.get(gid)

    def delete_gold(self, gid: str) -> bool:
        existed = self.gold.get(gid) is not None
        if existed:
            self.gold.delete(gid)
        return existed

    def list_patterns(self) -> List[Pattern]:
        return self.patterns.list_all()

    def list_error_fixes(self) -> List[ErrorFix]:
        return self.errorfixes.list_all()

    def list_gold(self) -> List[Gold]:
        return self.gold.list_all()

    # ================= Episode / 待审 =================

    def insert_episode(self, e: Episode):
        return self.episodes.insert(e)

    def list_episodes(self, limit: int = 100):
        return self.episodes.list_all(limit)

    def add_pending(self, kind: str, payload: dict, reason: str, confidence: float) -> PendingItem:
        return self.pending.add(kind, payload, reason, confidence)

    # ================= 召回日志（命中率统计） =================

    def log_recall(self, project_id: str, phase: str, query: str,
                   kind: str, hit_ids, ts: int = None) -> None:
        import json as _json
        import time as _time
        self.db.execute(
            "INSERT INTO recall_logs(project_id, phase, query, kind, hit_ids, hit_count, ts)"
            " VALUES(?,?,?,?,?,?,?)",
            (project_id or "", phase, str(query)[:500], kind,
             _json.dumps(list(hit_ids or []), ensure_ascii=False), len(list(hit_ids or [])),
             ts or int(_time.time() * 1000)),
        )

    def recall_stats(self, project_id: str = "") -> dict:
        """命中率统计：按 phase/kind 汇总召回次数与命中次数"""
        if project_id:
            rows = self.db.query(
                "SELECT phase, kind, COUNT(*) AS n, SUM(hit_count>0) AS hit FROM recall_logs"
                " WHERE project_id=? GROUP BY phase, kind", (project_id,))
        else:
            rows = self.db.query(
                "SELECT phase, kind, COUNT(*) AS n, SUM(hit_count>0) AS hit FROM recall_logs GROUP BY phase, kind")
        out = {}
        for r in rows:
            key = "%s/%s" % (r["phase"], r["kind"])
            total = r["n"] or 0
            hit = r["hit"] or 0
            out[key] = {"total": total, "hit": hit,
                        "rate": round(hit / total, 3) if total else 0.0}
        return out

    def list_pending(self) -> List[PendingItem]:
        return self.pending.list_all()

    def delete_pending(self, pid: str) -> bool:
        existed = self.pending.get(pid) is not None
        if existed:
            self.pending.delete(pid)
        return existed

    def close(self):
        self.db.close()
