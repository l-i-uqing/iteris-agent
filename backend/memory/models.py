# -*- coding: utf-8 -*-
"""
models.py · 经验记忆四层数据契约（Pydantic v2）

分层：
  Episode   —— 完整轨迹（仅审计，不参与检索）
  Gold      —— 题目指纹 → 正确 payload（仅精确匹配）
  Pattern   —— 抽象成功模式（向量检索）
  ErrorFix  —— 错误特征 → 修正策略（向量检索）

公共字段：human_verified / success_count / created_at（用于检索排序加权）
"""
import hashlib
import json
import time
from typing import Any, Dict, List

from pydantic import BaseModel, Field


def _now_ms() -> int:
    return int(time.time() * 1000)


def canonical_fingerprint_hash(fingerprint: Dict[str, Any]) -> str:
    """指纹规范化 → sha256（Gold 精确匹配的唯一键）"""
    canonical = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Episode(BaseModel):
    """完整轨迹，仅审计，不参与检索。"""
    id: str
    project_id: str = ""
    task_id: str = ""
    ts_start: int = 0
    ts_end: int = 0
    status: str = "failed"                 # solved | failed | corrected
    goal: str = ""                          # 用户原始目标
    target: str = ""                        # 目标 URL / 描述
    user_hint: str = ""                     # 用户纠正的原话（复盘触发源）
    final_payload: str = ""                 # 最终成功的 payload
    trajectory: List[Dict[str, Any]] = Field(default_factory=list)
    human_verified: bool = False
    success_count: int = 0
    created_at: int = Field(default_factory=_now_ms)


class Gold(BaseModel):
    """题目指纹 → 正确 payload。仅精确匹配（signature_hash），不做向量检索。"""
    id: str
    source_episode: str = ""
    fingerprint: Dict[str, Any] = Field(default_factory=dict)   # {vuln_type, weakness, signature}
    payload: str = ""
    hit_count: int = 0
    last_hit: int = 0
    human_verified: bool = False
    success_count: int = 0
    created_at: int = Field(default_factory=_now_ms)

    @property
    def signature_hash(self) -> str:
        return canonical_fingerprint_hash(self.fingerprint)


class Pattern(BaseModel):
    """抽象成功模式，向量检索。"""
    id: str
    title: str
    cat: str = "其他"                        # 信息收集|漏洞探测|漏洞利用|后渗透|报告编写|其他
    vuln_type: str = ""                      # 具体漏洞类型（图谱聚类键：SQL注入/命令注入/XSS/SSRF/文件包含/反序列化/认证绕过...）
    remediation: str = ""                    # 修复方案（防御视角，图谱节点用）
    abstract: str = ""                       # 抽象后的成功模式描述
    steps: List[str] = Field(default_factory=list)
    embedding: List[float] = Field(default_factory=list)
    hit_count: int = 0
    version: int = 1
    source_episodes: List[str] = Field(default_factory=list)
    human_verified: bool = False
    success_count: int = 0
    created_at: int = Field(default_factory=_now_ms)


class ErrorFix(BaseModel):
    """错误特征 → 修正策略，向量检索。"""
    id: str
    source_episodes: List[str] = Field(default_factory=list)
    error_type: str = "unknown"              # url_encode | no_echo | waf | timeout | tool_fail ...
    error_signature: str = ""                # 报错特征原文（用于向量检索）
    fix_strategy: str = ""                   # 修正策略
    applies_to: List[str] = Field(default_factory=list)   # 适用场景
    embedding: List[float] = Field(default_factory=list)
    hit_count: int = 0
    human_verified: bool = False
    success_count: int = 0
    created_at: int = Field(default_factory=_now_ms)


def pattern_index_text(p: Pattern) -> str:
    """Pattern 参与向量化的文本（标题+抽象+步骤）"""
    return " ".join([p.title, p.abstract] + p.steps)


def errorfix_index_text(e: ErrorFix) -> str:
    """ErrorFix 参与向量化的文本（错误特征+策略）"""
    return " ".join([e.error_signature, e.fix_strategy])


class Insight(BaseModel):
    """发现思路层（第五层）：应用类型/功能点 → 漏洞类型 → 测试切入点。
    回答"这类应用/这类功能点该往哪想"，是可迁移的漏洞发现方法论，
    不是"这道题怎么做"的答案。解题前注入优先于 Pattern。"""
    id: str
    app_type: str = ""                        # 应用类型（CMS 后台/API 网关/文件上传站/论坛...）
    tech_stack: List[str] = Field(default_factory=list)   # 技术栈/指纹（PHP/MySQL/海洋CMS...）
    feature_points: List[Dict[str, Any]] = Field(default_factory=list)
    # [{name: 功能点, vuln_hint: 该功能点常出的漏洞, why: 为什么, test_method: 怎么测}]
    mindset: str = ""                         # 抽象发现思路（一句话方法论，可跨题迁移）
    source_episodes: List[str] = Field(default_factory=list)
    embedding: List[float] = Field(default_factory=list)
    hit_count: int = 0
    human_verified: bool = False
    success_count: int = 0
    created_at: int = Field(default_factory=_now_ms)


def insight_index_text(i: "Insight") -> str:
    """Insight 参与向量化的文本（应用类型+技术栈+思路+功能点）"""
    fpts = []
    for fp in i.feature_points or []:
        fpts.append(" ".join([str(fp.get("name", "")), str(fp.get("vuln_hint", "")),
                              str(fp.get("why", "")), str(fp.get("test_method", ""))]))
    return " ".join([i.app_type, " ".join(i.tech_stack), i.mindset] + fpts)

class VulnNode(BaseModel):
    """漏洞知识图谱节点：漏洞类型 ↔ 触发条件 ↔ 利用方法 ↔ 修复方案 ↔ CVE。

    从已验证的 Pattern 按 vuln_type 聚合而来，也可人工维护（/api/memory/graph/upsert）。
    读取侧在 pre_solve 注入修复方案，让 Agent 从"会解题"升级到"会修复"。"""
    id: str
    vuln_type: str = ""                      # 聚类键（唯一）
    trigger: str = ""                        # 触发条件（什么现象/场景可切入）
    technique: List[str] = Field(default_factory=list)   # 利用方法步骤（合并自多条 Pattern）
    remediation: str = ""                    # 修复方案（防御视角）
    cve_id: str = ""                         # 关联 CVE 编号（可与 vuln_lookup 联动）
    source_patterns: List[str] = Field(default_factory=list)
    source_episodes: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    human_verified: bool = False
    success_count: int = 0
    created_at: int = Field(default_factory=_now_ms)
    updated_at: int = Field(default_factory=_now_ms)
