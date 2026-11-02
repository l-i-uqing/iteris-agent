# -*- coding: utf-8 -*-
"""
recall.py · 读取侧：经验注入主 Agent

两个注入点：
  1. 解题前 pre_solve_inject(question, schema)
     - 提取考察点特征（vuln_type / tables / query_text）
     - 检索 patterns Top3 + error_fixes Top3（排序：human_verified > success_count > 相似度）
     - gold 仅结构化精确匹配（vuln_type + 表名集合），禁止向量匹配 → 命中标记同题
     - 组装先验提示（长度受控），注入解题 prompt
  2. 报错后 error_fix_inject(error_text)
     - 用原始报错检索 error_fixes Top3
     - 命中 → 组装修正提示；未命中 → 标记新错误（miss），正常推理

每次召回写 recall_logs，供命中率统计（service.recall_stats）。
"""
from typing import Dict, List, Optional

from .features import extract_features
from .models import ErrorFix, Gold, Pattern
from .service import MemoryService

DEFAULT_TOP = 3
ABSTRACT_MAX = 120      # 注入时单条 abstract 截断长度
SIGNATURE_MAX = 100     # 注入时 error_signature 截断长度


def _short(s: str, n: int) -> str:
    s = str(s or "").strip()
    return s if len(s) <= n else s[:n] + "…"


class RecallService:
    def __init__(self, memory: MemoryService,
                 top_patterns: int = DEFAULT_TOP, top_fixes: int = DEFAULT_TOP):
        self.memory = memory
        self.top_patterns = top_patterns
        self.top_fixes = top_fixes

    # ================= 注入点 1：解题前 =================

    def pre_solve_inject(self, question: str, schema, project_id: str = "") -> dict:
        feats = extract_features(question, schema)
        q = feats["query_text"]

        # 1) 检索 patterns / error_fixes（排序权重已内置在 store.search）
        pats = self.memory.search_patterns(q, self.top_patterns)
        ins = self.memory.search_insights(q, top_k=2)
        fixes = self.memory.search_error_fixes(q, self.top_fixes)
        self.memory.log_recall(project_id, "pre_solve", q, "pattern",
                               [p["id"] for p in pats])
        self.memory.log_recall(project_id, "pre_solve", q, "error_fix",
                               [f["id"] for f in fixes])

        # 2) gold 同题识别（仅精确匹配）
        gold_hit = None
        if feats["vuln_type"] != "other" or feats["tables"]:
            gold_hit = self.memory.gold.find_by_type_and_tables(feats["vuln_type"], feats["tables"])
        self.memory.log_recall(project_id, "pre_solve", q, "gold",
                               [gold_hit.id] if gold_hit else [])

        # 3) 漏洞图谱：命中经验的漏洞类型 → 取修复方案（防御视角）
        graph_nodes = []
        seen_vt = set()
        for p_ in pats:
            vt = str(p_.get("vuln_type") or "").strip() or "其他"
            if vt in seen_vt:
                continue
            seen_vt.add(vt)
            n = self.memory.graph.get_by_vuln_type(vt)
            if n is not None:
                graph_nodes.append(n)
        self.memory.log_recall(project_id, "pre_solve", q, "graph",
                               [n.id for n in graph_nodes])

        # 4) 组装先验提示
        prior = self._assemble_prior(pats, fixes, gold_hit, ins, graph_nodes)

        return {
            "prior_prompt": prior,
            "insights": ins,
            "patterns": pats,
            "error_fixes": fixes,
            "graph_nodes": [{"vuln_type": n.vuln_type, "remediation": n.remediation,
                             "technique": n.technique} for n in graph_nodes],
            "gold_hit": gold_hit,
            "gold_payload": gold_hit.payload if gold_hit else None,
            "features": feats,
        }

    def _assemble_prior(self, pats: List[dict], fixes: List[dict], gold_hit: Optional[Gold], ins: List[dict] = None,
                        graph_nodes: List = None) -> str:
        lines = []
        if ins:
            lines.append("【漏洞发现思路（先验）】遇到这类目标，优先按以下思路找攻击面：")
            for i, it in enumerate(ins[:2], 1):
                fp_txt = "；".join(
                    "%s→%s（%s）" % (fp.get("name", "功能点"), fp.get("vuln_hint", ""), fp.get("test_method", ""))
                    for fp in (it.get("feature_points") or [])[:3]) if it.get("feature_points") else ""
                lines.append("%d) 应用类型：%s；思路：%s%s" % (
                    i, it.get("app_type", ""), it.get("mindset", ""),
                    ("；攻击面：%s" % fp_txt) if fp_txt else ""))
        if pats:
            lines.append("【先验经验·相似解法】遇到类似题目时优先参考（按可信度排序，成功次数越高越优先）：")
            for i, p in enumerate(pats, 1):
                mark = "已验证" if p.get("human_verified") else "经验"
                lines.append("%d) [%s] %s：%s（成功 %d 次）" % (
                    i, mark, p.get("title", ""),
                    _short(p.get("abstract", ""), ABSTRACT_MAX), p.get("success_count", 0)))
        if fixes:
            lines.append("【先验经验·易错提醒】")
            for i, f in enumerate(fixes, 1):
                lines.append("%d) 错误特征：%s → %s" % (
                    i, _short(f.get("error_signature", ""), SIGNATURE_MAX),
                    _short(f.get("fix_strategy", ""), ABSTRACT_MAX)))
        if gold_hit is not None:
            lines.append("【同题提示】检测到与历史题目指纹完全匹配（vuln_type=%s，表名集合一致）。"
                         "历史已解出的正确 payload：%s" % (gold_hit.fingerprint.get("vuln_type"), gold_hit.payload))
        if graph_nodes:
            parts = []
            for n in graph_nodes:
                if n.remediation:
                    parts.append("%s → %s" % (n.vuln_type, n.remediation))
            if parts:
                lines.append("【漏洞知识·修复视角】同类漏洞的通用修复方案（解题后可结合给出，防御视角）：")
                lines.append("； ".join(parts))
        return "\n".join(lines)

    # ================= 注入点 2：报错后 =================

    def error_fix_inject(self, error_text: str, project_id: str = "") -> dict:
        hits = self.memory.search_error_fixes(error_text, self.top_fixes)
        self.memory.log_recall(project_id, "error_fix", error_text, "error_fix",
                               [f["id"] for f in hits])
        miss = len(hits) == 0
        if miss:
            return {"fix_prompt": "", "hits": [], "miss": True}
        lines = ["【报错修正】检测到历史相似错误，按以下策略调整："]
        for i, f in enumerate(hits, 1):
            lines.append("%d) 错误特征：%s\n   修正策略：%s" % (
                i, _short(f.get("error_signature", ""), SIGNATURE_MAX),
                _short(f.get("fix_strategy", ""), ABSTRACT_MAX)))
        return {"fix_prompt": "\n".join(lines), "hits": hits, "miss": False}
