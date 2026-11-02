# -*- coding: utf-8 -*-
"""
playbook.py · 预置攻击思路库（Playbook）
按目标描述检索，把「应用类型/功能点 → 漏洞思路」注入 Agent 解题前先验。
与经验记忆（Insight 层）互补：Playbook 是预置方法论，Insight 是实战沉淀。
"""
import json
import re
from pathlib import Path

PLAYBOOK_FILE = Path(__file__).resolve().parent.parent / "data" / "playbook.json"

STOP = {"flag", "http", "https", "www", "com", "admin", "html", "php", "拿", "获得", "测试", "帮我", "一个", "这个", "那个", "网站", "站点", "目标", "进行", "然后", "以及"}


def _kw(text: str):
    return [w for w in re.findall(r"[\u4e00-\u9fa5]{2,}|[A-Za-z]{3,}", str(text))
            if w.lower() not in STOP]


class PlaybookService:
    def __init__(self, path=None):
        self.path = Path(path) if path else PLAYBOOK_FILE
        self.items = []
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.items = (json.load(f) or {}).get("items", []) or []
        except Exception:
            self.items = []

    def reload(self):
        self._load()

    @staticmethod
    def _kw(text: str):
        """任务侧分词：中文连续块切成 2 字滑窗；英文/数字块原样"""
        out = set()
        for blk in re.findall(r"[\u4e00-\u9fa5]{2,}|[A-Za-z0-9]{3,}", str(text)):
            if blk and blk[0].isascii():
                out.add(blk.lower())
            else:
                for i in range(len(blk) - 1):
                    out.add(blk[i:i + 2])
        return out

    def recall(self, task: str, top_k: int = 3) -> list:
        """混合召回：①条目关键词整词出现在任务中（+3，最可靠）；②任务 2 字滑窗命中条目词料（title/app_type/keywords/功能点名，+1）。
        中文不依赖分词，英文不区分大小写。"""
        if not self.items:
            return []
        t = (task or "").lower()
        if not t:
            return []
        kws = self._kw(task)
        scored = []
        for it in self.items:
            score = 0
            for kw in (it.get("keywords") or []):
                kl = str(kw).lower()
                if kl and kl in t:
                    score += 3
            blob = " ".join([
                str(it.get("title", "")), str(it.get("app_type", "")),
                " ".join(it.get("keywords", [])),
                " ".join(fp.get("name", "") for fp in (it.get("feature_points") or [])),
            ]).lower()
            for k in kws:
                if k in blob:
                    score += 1
            if score > 0:
                scored.append((score, it))
        scored.sort(key=lambda x: -x[0])
        return [dict(x[1]) for x in scored[:top_k]]

    def get(self, iid: str):
        for it in self.items:
            if it.get("id") == iid:
                return it
        return None

    def format_for_inject(self, items: list) -> str:
        lines = ["【攻击思路库（Playbook）：思路 + 知识点 + 可执行动作，与当前目标相关，规划与执行时优先参考】"]
        for i, it in enumerate(items, 1):
            lines.append("%d) %s（适用：%s）" % (i, it.get("title", ""), it.get("app_type", "")))
            lines.append("   思路：%s" % (it.get("mindset", "") or ""))
            # 知识点（原理，最多 2 条）
            for kn in (it.get("knowledge") or [])[:2]:
                lines.append("   知识点·%s：%s" % (kn.get("topic", ""), kn.get("content", "")))
            # 攻击面功能点（最多 2 个）
            for fp in (it.get("feature_points") or [])[:2]:
                lines.append("   攻击面·%s：%s → %s" % (
                    fp.get("name", ""), fp.get("vuln_hint", ""), fp.get("test_method", "")))
            # 可执行动作（命令/payload/验证/产出，最多 3 条）
            acts = (it.get("actionable") or [])[:3]
            if acts:
                lines.append("   可执行动作：")
                for a in acts:
                    lines.append("   - [%s] %s" % (a.get("type", ""), a.get("content", "")))
            if it.get("need_user"):
                lines.append("   ⚠️ 需要用户提供：%s" % it["need_user"])
        return "\n".join(lines)
