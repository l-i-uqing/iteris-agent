# -*- coding: utf-8 -*-
"""
graph.py · 漏洞知识图谱（经验库的结构化升级层）

把四层经验（Episode/Gold/Pattern/ErrorFix）从"文本召回"升级为
"漏洞类型 ↔ 触发条件 ↔ 利用方法 ↔ 修复方案"的结构化图谱，并与 CVE 情报对齐：

  漏洞类型 (vuln_type)          ← 聚类键（SQL注入 / 命令注入 / XSS / SSRF / 文件包含 / 认证绕过 …）
    ├── trigger                 触发条件（什么现象/场景可切入）
    ├── technique               利用方法（抽象自多条 Pattern 的通用步骤）
    ├── remediation             修复方案（防御视角，回溯到真实修复）
    ├── cve_id                  关联 CVE 编号（可与 vuln_lookup 联动核实）
    └── source_patterns/episodes 溯源引用

数据来源：
  1. 自动聚合：review 复盘入库的 Pattern（带 vuln_type/remediation）按类型聚合成节点；
  2. 人工维护：/api/memory/graph/upsert 手动新增/编辑（类型、触发、利用、修复、CVE）。

读取侧：pre_solve 注入时，命中的经验类型若有图谱节点，把修复方案一并注入，
让 Agent 不仅会"解题"，也能给出"修复"（防御视角）。
"""
import time
from typing import List, Optional

from .db import MemoryDB
from .models import VulnNode


class VulnGraphService:
    def __init__(self, db: MemoryDB):
        self.db = db

    # ---------- 读取 ----------

    def list_nodes(self) -> List[VulnNode]:
        rows = self.db.query("SELECT * FROM vuln_graph ORDER BY success_count DESC, updated_at DESC")
        return [row_to_node(r) for r in rows]

    def get_by_vuln_type(self, vuln_type: str) -> Optional[VulnNode]:
        rows = self.db.query("SELECT * FROM vuln_graph WHERE vuln_type=?", (vuln_type,))
        return row_to_node(rows[0]) if rows else None

    def get(self, node_id: str) -> Optional[VulnNode]:
        rows = self.db.query("SELECT * FROM vuln_graph WHERE id=?", (node_id,))
        return row_to_node(rows[0]) if rows else None

    # ---------- 写入 ----------

    def sync_from_pattern(self, vuln_type: str, technique: List[str], trigger: str,
                          remediation: str, pattern_id: str, episode_id: str = "",
                          human_verified: bool = False, confidence: float = 0.0) -> VulnNode:
        """
        复盘入库的 Pattern → 聚合/更新图谱节点。
        vuln_type 为空时归入"其他"；节点按类型唯一，多条经验合并 technique 并计数。
        """
        vt = (vuln_type or "").strip() or "其他"
        node = self.get_by_vuln_type(vt)
        now = int(time.time() * 1000)
        if node is None:
            node = VulnNode(
                id="vn_" + str(now) + "_" + hex(hash(vt) % 0xffff)[2:],
                vuln_type=vt,
                trigger=trigger or "",
                technique=[s for s in (technique or []) if s and str(s).strip()],
                remediation=remediation or "",
                cve_id="",
                source_patterns=[pattern_id] if pattern_id else [],
                source_episodes=[episode_id] if episode_id else [],
                confidence=confidence,
                human_verified=bool(human_verified),
                success_count=1,
                created_at=now, updated_at=now,
            )
            self.insert(node)
            return node
        # 已有节点：合并利用步骤（去重）、补触发/修复、计数
        merged = list(node.technique)
        for s in (technique or []):
            s = str(s).strip()
            if s and s not in merged:
                merged.append(s)
        node.technique = merged
        if not node.trigger and trigger:
            node.trigger = trigger
        if not node.remediation and remediation:
            node.remediation = remediation
        if pattern_id and pattern_id not in node.source_patterns:
            node.source_patterns.append(pattern_id)
        if episode_id and episode_id not in node.source_episodes:
            node.source_episodes.append(episode_id)
        node.success_count += 1
        node.confidence = max(node.confidence, confidence)
        node.human_verified = node.human_verified or bool(human_verified)
        node.updated_at = now
        self.update(node)
        return node

    def upsert(self, data: dict) -> VulnNode:
        """人工新增/编辑节点。传入 id 则更新，否则新建。"""
        now = int(time.time() * 1000)
        node_id = str(data.get("id") or "").strip()
        vuln_type = str(data.get("vuln_type") or "").strip() or "其他"
        if node_id:
            node = self.get(node_id)
            if node is None:
                raise ValueError("节点不存在：" + node_id)
            node.vuln_type = vuln_type
            node.trigger = str(data.get("trigger") or "")
            node.technique = [str(x).strip() for x in (data.get("technique") or []) if str(x).strip()]
            node.remediation = str(data.get("remediation") or "")
            node.cve_id = str(data.get("cve_id") or "").strip()
            node.updated_at = now
            self.update(node)
            return node
        # 新建：按类型查重，存在则更新
        exist = self.get_by_vuln_type(vuln_type)
        if exist is not None:
            exist.trigger = str(data.get("trigger") or exist.trigger)
            techs = [str(x).strip() for x in (data.get("technique") or []) if str(x).strip()]
            for t in techs:
                if t and t not in exist.technique:
                    exist.technique.append(t)
            if data.get("remediation"):
                exist.remediation = str(data.get("remediation"))
            if data.get("cve_id"):
                exist.cve_id = str(data.get("cve_id")).strip()
            exist.updated_at = now
            self.update(exist)
            return exist
        node = VulnNode(
            id="vn_" + str(now) + "_" + hex(hash(vuln_type) % 0xffff)[2:],
            vuln_type=vuln_type,
            trigger=str(data.get("trigger") or ""),
            technique=[str(x).strip() for x in (data.get("technique") or []) if str(x).strip()],
            remediation=str(data.get("remediation") or ""),
            cve_id=str(data.get("cve_id") or "").strip(),
            source_patterns=[],
            source_episodes=[],
            confidence=float(data.get("confidence") or 0.0),
            human_verified=bool(data.get("human_verified")),
            success_count=int(data.get("success_count") or 1),
            created_at=now, updated_at=now,
        )
        self.insert(node)
        return node

    def delete(self, node_id: str) -> bool:
        existed = self.get(node_id) is not None
        if existed:
            self.db.execute("DELETE FROM vuln_graph WHERE id=?", (node_id,))
        return existed

    # ---------- 底层 ----------

    def insert(self, node: VulnNode):
        self.db.execute(
            "INSERT INTO vuln_graph(id, vuln_type, trigger, technique_json, remediation, cve_id,"
            " source_patterns_json, source_episodes_json, confidence, human_verified, success_count,"
            " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            node_to_row(node),
        )

    def update(self, node: VulnNode):
        self.db.execute(
            "UPDATE vuln_graph SET vuln_type=?, trigger=?, technique_json=?, remediation=?, cve_id=?,"
            " source_patterns_json=?, source_episodes_json=?, confidence=?, human_verified=?,"
            " success_count=?, updated_at=? WHERE id=?",
            (node.vuln_type, node.trigger, _j(node.technique), node.remediation, node.cve_id,
             _j(node.source_patterns), _j(node.source_episodes), node.confidence,
             int(node.human_verified), node.success_count, node.updated_at, node.id),
        )


# ---------- 行 ↔ 模型 转换 ----------

def _j(v):
    import json
    return json.dumps(v, ensure_ascii=False) if v is not None else None


def _u(s):
    import json
    return json.loads(s) if s else None


def node_to_row(n: VulnNode):
    return (n.id, n.vuln_type, n.trigger, _j(n.technique), n.remediation, n.cve_id,
            _j(n.source_patterns), _j(n.source_episodes), n.confidence,
            int(n.human_verified), n.success_count, n.created_at, n.updated_at)


def row_to_node(r) -> VulnNode:
    return VulnNode(
        id=r["id"], vuln_type=r["vuln_type"], trigger=r["trigger"],
        technique=_u(r["technique_json"]) or [], remediation=r["remediation"],
        cve_id=r["cve_id"], source_patterns=_u(r["source_patterns_json"]) or [],
        source_episodes=_u(r["source_episodes_json"]) or [],
        confidence=r["confidence"] or 0.0,
        human_verified=bool(r["human_verified"]),
        success_count=r["success_count"] or 0,
        created_at=r["created_at"], updated_at=r["updated_at"],
    )
