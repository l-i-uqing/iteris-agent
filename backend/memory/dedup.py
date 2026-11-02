# -*- coding: utf-8 -*-
"""
dedup.py · 去重服务

入库前对 Pattern / ErrorFix 做向量检索 Top5，交给 judge 决策：
  merge    —— 视为同一条经验的重复沉淀：合并计数（hit_count / success_count +1），不新增
  update   —— 同主题但内容有更新：目标版本 +1，内容替换，保留 id 与计数
  insert   —— 无相近经验：新增
  conflict —— 相近但可能不同：不写入，返回候选供上层/人工裁决

judge 本期默认 MockJudge（确定性阈值规则）跑通链路；
LLMDedupJudge 已预留接口（调后端 LLM 代理），下一阶段启用。
"""
from typing import List, Optional

from .models import Pattern, ErrorFix, pattern_index_text, errorfix_index_text
from .vector import cosine


class DedupDecision:
    __slots__ = ("action", "target_id", "reason", "score")

    def __init__(self, action: str, target_id: Optional[str] = None, reason: str = "", score: float = 0.0):
        self.action = action          # merge | update | insert | conflict
        self.target_id = target_id
        self.reason = reason
        self.score = score


# 默认阈值（MockJudge；接入 LLM judge 后可放宽为模型判断）
MERGE_MIN = 0.90
UPDATE_MIN = 0.75
CONFLICT_MIN = 0.55


class MockJudge:
    """确定性规则 judge：按 Top1 相似度阈值决策（跑通链路的默认实现）"""

    def judge(self, kind: str, item, top_hits) -> DedupDecision:
        if not top_hits:
            return DedupDecision("insert", None, "无相近经验，直接新增", 0.0)
        best = top_hits[0]
        s = best.score
        if s >= MERGE_MIN:
            return DedupDecision("merge", best.item.id,
                                 "与现有 %s 相似度 %.3f，视为同一条经验，合并计数" % (kind, s), s)
        if s >= UPDATE_MIN:
            return DedupDecision("update", best.item.id,
                                 "与现有 %s 相似度 %.3f，内容有更新，版本 +1 覆盖" % (kind, s), s)
        if s >= CONFLICT_MIN:
            return DedupDecision("conflict", None,
                                 "存在相近经验（%.3f）但不足以合并，需人工裁决" % s, s)
        return DedupDecision("insert", None, "相似度 %.3f 低于阈值，作为新经验入库" % s, s)


class LLMDedupJudge:
    """LLM judge（预留）：把 Top5 候选 + 新条目构造 prompt，交给大模型判 merge/update/insert/conflict。
    下一阶段接入后端 /api/proxy/llm 启用。"""

    def __init__(self, llm_call=None):
        self.llm_call = llm_call

    def judge(self, kind: str, item, top_hits) -> DedupDecision:
        # TODO(下一阶段)：构造 prompt（新条目 + Top5 候选文本/分数）→ llm_call → 解析 JSON 决策
        # 未启用前退化为 MockJudge 规则
        return MockJudge().judge(kind, item, top_hits)


class DedupService:
    def __init__(self, judge=None):
        self.judge = judge or MockJudge()

    def decide(self, kind: str, item, top_hits) -> DedupDecision:
        return self.judge.judge(kind, item, top_hits)

    # ---------- 合并 / 升级 的具体动作 ----------

    def apply_merge(self, target, incoming, kind: str):
        """merge：合并计数与来源，不替换内容"""
        target.hit_count = (target.hit_count or 0) + 1
        target.success_count = (target.success_count or 0) + 1
        src = list(target.source_episodes or [])
        for s in (incoming.source_episodes or []):
            if s not in src:
                src.append(s)
        target.source_episodes = src
        return target

    def apply_update(self, target, incoming, kind: str):
        """update：版本 +1，内容以新条目为准，保留 id / 计数 / 人工验证标记"""
        keep_id, keep_hit, keep_ok, keep_created = target.id, target.hit_count, target.human_verified, target.created_at
        merged_src = list(target.source_episodes or [])
        for s in (incoming.source_episodes or []):
            if s not in merged_src:
                merged_src.append(s)
        incoming.id = keep_id
        incoming.version = (target.version or 1) + 1
        incoming.hit_count = keep_hit + 1
        incoming.success_count = (target.success_count or 0) + 1
        incoming.human_verified = keep_ok or incoming.human_verified
        incoming.created_at = keep_created
        incoming.source_episodes = merged_src
        return incoming
