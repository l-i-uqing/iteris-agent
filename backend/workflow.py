# -*- coding: utf-8 -*-
"""
workflow.py · 六阶段渗透流程引擎（显式工作流 + 断点恢复）

把 Agent 的渗透任务组织成标准流程：
  侦察(Recon) → 扫描(Scan) → 枚举(Enum) → 利用(Exploit) → 后渗透(Post) → 报告(Report)

能力：
  - 显式工作流：每个阶段有状态（pending/running/done/failed/skipped），记录工具调用；
  - 阶段推进：标记完成/失败/跳过，自动定位下一未执行阶段；
  - 断点恢复：任务中断（关页面/切项目/Agent 停止）后，进度持久化在项目目录，
    重新发起时返回上次进度，Agent 从断点继续；
  - 按项目隔离：data/projects/<pid>/workflow.json（default 项目在 data/workflow.json）。

前端 Agent 集成：
  - 系统提示词注入当前阶段与推荐工具；
  - workflow_advance 工具由 Agent 调用以推进阶段；
  - run_command / vuln_lookup 等工具调用自动记录到当前阶段（/api/workflow/tool）。
"""
import json
import time
from typing import List, Optional

from . import storage

PHASES = [
    {"id": "recon", "name": "侦察", "en": "Recon",
     "desc": "信息收集：确认目标归属、存活主机、子域名/技术栈识别、whois/证书信息",
     "tools": ["whois", "dig", "nmap -sn", "浏览器侦察", "子域名枚举"]},
    {"id": "scan", "name": "扫描", "en": "Scan",
     "desc": "端口与服务扫描：开放端口、服务版本、操作系统指纹",
     "tools": ["nmap", "masscan"]},
    {"id": "enum", "name": "枚举", "en": "Enum",
     "desc": "应用层枚举：目录/文件/参数、用户枚举、版本漏洞探测",
     "tools": ["gobuster", "ffuf", "nikto", "wpscan"]},
    {"id": "exploit", "name": "利用", "en": "Exploit",
     "desc": "漏洞验证与利用：SQL 注入、RCE、认证绕过、文件读取/上传",
     "tools": ["sqlmap", "burp", "metasploit", "vuln_lookup"]},
    {"id": "post", "name": "后渗透", "en": "Post",
     "desc": "权限提升、数据提取、凭据获取（严格限于授权范围）",
     "tools": ["hashcat", "john", "数据提取"]},
    {"id": "report", "name": "报告", "en": "Report",
     "desc": "汇总发现、CVSS 评级、修复建议、输出报告",
     "tools": ["vuln_lookup", "报告生成"]},
]

PHASE_MAP = {p["id"]: p for p in PHASES}
STATUS_ORDER = ["pending", "running", "done", "failed", "skipped"]


def new_phase(pid: str, now: int) -> dict:
    return {
        "id": pid, "name": PHASE_MAP[pid]["name"], "en": PHASE_MAP[pid]["en"],
        "desc": PHASE_MAP[pid]["desc"], "tools": PHASE_MAP[pid]["tools"],
        "status": "pending", "note": "", "tools_used": [],
        "started_at": 0, "finished_at": 0,
    }


def workflow_file(pid: str):
    return storage.project_dir(pid) / "workflow.json"


def _now_ms() -> int:
    return int(time.time() * 1000)


class WorkflowService:
    """工作流状态机（JSON 持久化，按项目隔离）"""

    # ---------- 读取 ----------

    def get(self, pid: str) -> Optional[dict]:
        wf = storage.read_json(workflow_file(pid), None)
        if wf and isinstance(wf, dict) and wf.get("phases"):
            wf["current"] = self._current_index(wf)
            return wf
        return None

    @staticmethod
    def _current_index(wf: dict) -> int:
        # 优先指向“进行中”的阶段，其次第一个待执行阶段
        phases = wf.get("phases") or []
        for i, ph in enumerate(phases):
            if ph.get("status") == "running":
                return i
        for i, ph in enumerate(phases):
            if ph.get("status") == "pending":
                return i
        return len(phases) - 1

    # ---------- 启动 / 恢复 ----------

    def start(self, pid: str, target: str) -> dict:
        exist = self.get(pid)
        if exist is not None:
            exist["current"] = self._current_index(exist)
            return exist  # 断点恢复：返回上次进度
        now = _now_ms()
        wf = {
            "id": "wf_" + str(now),
            "projectId": pid,
            "target": (target or "").strip(),
            "status": "active",          # active | done | interrupted
            "created_at": now,
            "updated_at": now,
            "current": 0,
            "phases": [new_phase(p["id"], now) for p in PHASES],
        }
        self._save(pid, wf)
        return wf

    # ---------- 阶段推进 ----------

    def advance(self, pid: str, phase_id: str, status: str, note: str = "") -> dict:
        wf = self.get(pid)
        if wf is None:
            raise ValueError("尚未启动渗透流程（先调用 /api/workflow/start）")
        if status not in ("done", "failed", "skipped"):
            raise ValueError("status 只能是 done/failed/skipped")
        target = None
        for ph in wf["phases"]:
            if ph["id"] == phase_id:
                target = ph
                break
        if target is None:
            raise ValueError("阶段不存在：" + phase_id)
        now = _now_ms()
        target["status"] = status
        target["note"] = str(note or "")
        target["finished_at"] = now
        wf["updated_at"] = now
        # 全部阶段终结 → 流程完成
        if all(p["status"] != "pending" for p in wf["phases"]):
            wf["status"] = "done"
        else:
            wf["status"] = "active"
            nxt = self._current_index(wf)
            if nxt < len(wf["phases"]) and wf["phases"][nxt]["status"] == "pending":
                wf["phases"][nxt]["status"] = "running"
                wf["phases"][nxt]["started_at"] = now
        wf["current"] = self._current_index(wf)
        self._save(pid, wf)
        return wf

    # ---------- 工具调用记录 ----------

    def log_tool(self, pid: str, phase_id: str, tool: str, args: str,
                 ok: bool, summary: str = "") -> dict:
        wf = self.get(pid)
        if wf is None:
            return {"ok": False, "error": "无进行中的流程"}
        if not phase_id or phase_id not in PHASE_MAP:
            idx = self._current_index(wf)
            if idx >= len(wf["phases"]):
                return {"ok": False, "error": "流程已完成"}
            phase_id = wf["phases"][idx]["id"]
        for ph in wf["phases"]:
            if ph["id"] == phase_id:
                ph.setdefault("tools_used", []).append({
                    "tool": str(tool or ""), "args": str(args or "")[:200],
                    "ok": bool(ok), "summary": str(summary or "")[:200],
                    "ts": _now_ms(),
                })
                ph["tools_used"] = ph["tools_used"][-60:]  # 只留最近 60 条
                break
        wf["updated_at"] = _now_ms()
        self._save(pid, wf)
        return {"ok": True}

    # ---------- 中断 / 重置 ----------

    def abort(self, pid: str) -> dict:
        wf = self.get(pid)
        if wf is None:
            return {"ok": False, "error": "无进行中的流程"}
        wf["status"] = "interrupted"
        wf["updated_at"] = _now_ms()
        self._save(pid, wf)
        return {"ok": True, "workflow": wf}

    def reset(self, pid: str) -> bool:
        f = workflow_file(pid)
        if f.exists():
            try:
                f.unlink()
                return True
            except Exception:
                return False
        return False

    # ---------- 内部 ----------

    def _save(self, pid: str, wf: dict):
        storage.write_json(workflow_file(pid), wf)


def phase_progress_text(wf: dict) -> str:
    """把工作流渲染为给 Agent 的进度提示（注入系统提示词）"""
    if not wf:
        return ""
    lines = ["【渗透流程进度】当前任务按标准六阶段推进："]
    for i, ph in enumerate(wf.get("phases") or []):
        mark = {"done": "✔", "failed": "✘", "skipped": "➤", "running": "▶", "pending": "○"}.get(ph.get("status"), "○")
        cur = "（当前）" if i == wf.get("current") else ""
        cnt = len(ph.get("tools_used") or [])
        lines.append("%s %s %s%s：%s%s" % (
            mark, ph["name"], cur,
            ("[工具 " + str(cnt) + "]") if cnt else "",
            ph.get("desc", ""),
            (" 注意：" + ph.get("note", "")) if ph.get("note") else "",
        ))
    cur_ph = wf["phases"][wf.get("current", 0)] if wf.get("phases") else None
    if cur_ph and cur_ph.get("status") in ("running", "pending"):
        lines.append("当前阶段【%s】推荐动作：%s" % (cur_ph["name"], "；".join(cur_ph.get("tools", []))))
    lines.append("推进规则：一个阶段完成后调用 workflow_advance 工具标记（done/failed/skipped）并进入下一阶段；禁止跳阶段执行。")
    return "\n".join(lines)
