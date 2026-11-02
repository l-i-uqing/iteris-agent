# -*- coding: utf-8 -*-
"""
review.py · 复盘模块（独立 LLM 调用，不嵌入主 Agent）

输入：question, schema, attempts（失败 payload+报错列表）, gold_sql, user_note
输出：四层 JSON（episode / gold / patterns / error_fixes）

流程：
  1. 组装 prompt（prompts.py）→ LLM 结构化输出（JSON mode，经后端 /api/proxy/llm）
  2. 解析 JSON
  3. 校验：patterns 中出现 schema 表名/列名 → 打回重生成（最多 MAX_RETRY 次）
  4. 置信度过滤：confidence < 0.5 的 pattern / error_fix → 待审队列（不入库）
  5. 其余 → 调存储层去重接口入库（MemoryService.insert_*）

依赖注入：
  llm_call: call_llm(messages, response_format) -> str（默认走本地后端代理；测试注入 mock）
  memory:   MemoryService（默认 data/memory.db）
"""
import json
import re
import time
import urllib.request
from typing import Callable, Dict, List, Optional

from . import prompts
from .features import extract_table_names
from .models import ErrorFix, Episode, Gold, Insight, Pattern
from .service import MemoryService

MAX_RETRY = 2          # 校验打回最多重生成次数
CONFIDENCE_MIN = 0.5   # 低于此值进待审队列
PROXY_URL = "http://127.0.0.1:8899/api/proxy/llm"


class ReviewResult:
    __slots__ = ("ok", "llm_raw", "parsed", "schema_terms", "validation",
                 "pending", "stored", "log", "error")

    def __init__(self):
        self.ok = False
        self.llm_raw = ""
        self.parsed = None
        self.schema_terms = []
        self.validation = {"rounds": 0, "violations": [], "passed": False}
        self.pending = []      # [{kind, title/error_type, confidence, reason}]
        self.stored = []       # [{kind, id, action, confidence}]
        self.log = []
        self.error = ""

    def to_dict(self):
        return {
            "ok": self.ok, "validation": self.validation,
            "pending": self.pending, "stored": self.stored,
            "error": self.error,
        }


def default_llm_call(messages: List[dict], response_format: Optional[dict] = None) -> str:
    """默认 LLM 调用：走本地后端代理（key 在后端），支持 JSON mode"""
    body = {
        "model": "deepseek-chat",
        "messages": messages,
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 4096,
    }
    if response_format:
        body["response_format"] = response_format
    req = urllib.request.Request(
        PROXY_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read().decode("utf-8", "replace")
    j = json.loads(raw)
    return (j.get("choices") or [{}])[0].get("message", {}).get("content") or ""


def _extract_json(text: str) -> dict:
    """容错提取 JSON 对象（剥离 Markdown 代码块/前后杂文）"""
    t = str(text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```\s*$", "", t)
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", t)
        if m:
            return json.loads(m.group(0))
        raise ValueError("无法从 LLM 输出中解析 JSON")


def extract_schema_terms(schema) -> List[str]:
    """从 schema 提取表名/列名（敏感标识符），用于校验 patterns 是否泄漏"""
    terms = set()
    if isinstance(schema, dict):
        for key in ("table", "tables", "table_names"):
            v = schema.get(key)
            if isinstance(v, str):
                terms.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", v))
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, str):
                        terms.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", x))
        for key in ("columns", "column_names", "cols"):
            v = schema.get(key)
            if isinstance(v, str):
                terms.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", v))
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, str):
                        terms.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", x))
        for key in ("schema_sql", "sql", "ddl"):
            v = schema.get(key)
            if isinstance(v, str):
                for m in re.finditer(r"CREATE\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)", v, re.I):
                    terms.add(m.group(1))
                for m in re.finditer(r"`([A-Za-z_][A-Za-z0-9_]*)`", v):
                    terms.add(m.group(1))
    elif isinstance(schema, str):
        for m in re.finditer(r"CREATE\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)", schema, re.I):
            terms.add(m.group(1))
        for m in re.finditer(r"`([A-Za-z_][A-Za-z0-9_]*)`", schema):
            terms.add(m.group(1))
    # 去掉真正的通用词（保留 flag 等 CTF 常见表名，它们必须参与泄漏校验）
    stop = {"table", "tables", "select", "from", "where", "column", "columns", "insert", "into", "values", "union", "and", "or", "not", "null", "limit"}
    return sorted(t for t in terms if t.lower() not in stop)


def _check_pattern_leaks(patterns: List[dict], schema_terms: List[str]) -> List[str]:
    """patterns 文本中出现 schema 表名/列名 → 返回违规标识符列表"""
    if not schema_terms:
        return []
    violations = []
    for p in patterns or []:
        blob = " ".join([
            str(p.get("title", "")), str(p.get("abstract", "")),
            " ".join(str(x) for x in (p.get("steps") or [])),
        ])
        for term in schema_terms:
            if re.search(r"\b" + re.escape(term) + r"\b", blob, re.I):
                violations.append(term)
    return sorted(set(violations))


class ReviewService:
    def __init__(self, memory: Optional[MemoryService] = None,
                 llm_call: Optional[Callable] = None,
                 max_retry: int = MAX_RETRY,
                 confidence_min: float = CONFIDENCE_MIN):
        self.memory = memory or MemoryService()
        self.llm_call = llm_call or default_llm_call
        self.max_retry = max_retry
        self.confidence_min = confidence_min

    # ---------- 主入口 ----------

    def review(self, question: str, schema, attempts: List[dict],
               gold_sql: str, user_note: str = "") -> ReviewResult:
        res = ReviewResult()
        res.log.append("[1] 组装 prompt")
        schema_terms = extract_schema_terms(schema)
        res.schema_terms = schema_terms
        res.log.append("    敏感标识符（校验用）：%s" % (schema_terms or "无"))
        tables = extract_table_names(schema)
        res.log.append("    表名（gold 同题识别用）：%s" % (tables or "无"))

        attempts_text = self._format_attempts(attempts)
        user_msg = prompts.USER_TEMPLATE.format(
            question=question,
            schema=self._format_schema(schema),
            attempts=attempts_text,
            gold_sql=gold_sql,
            user_note=user_note or "（无）",
        )
        messages = [{"role": "system", "content": prompts.SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg}]
        res.log.append("    prompt 总长 %d 字符" % sum(len(m["content"]) for m in messages))

        # LLM 结构化输出 + 校验打回循环
        parsed = None
        for rnd in range(self.max_retry + 1):
            res.validation["rounds"] = rnd + 1
            res.log.append("[2] 第 %d 次调用 LLM（JSON mode）" % (rnd + 1))
            try:
                raw = self.llm_call(messages, {"type": "json_object"})
            except Exception as e:
                res.error = "LLM 调用失败：%s" % e
                res.log.append("    LLM 调用失败：" + str(e))
                return res
            res.llm_raw = raw
            res.log.append("    原始返回 %d 字符，前 120 字：%s" % (len(raw), raw[:120].replace("\n", " ")))
            try:
                parsed = _extract_json(raw)
            except Exception as e:
                res.log.append("    JSON 解析失败：" + str(e))
                if rnd == self.max_retry:
                    res.error = "多次输出无法解析为 JSON"
                    return res
                messages = messages + [{"role": "user", "content": "上一轮输出不是合法 JSON，请只输出一个 JSON 对象。"}]
                continue

            # 校验：patterns 泄漏 schema 标识符
            violations = _check_pattern_leaks(parsed.get("patterns") or [], schema_terms)
            res.validation["violations"] = violations
            if violations:
                res.log.append("    【打回】patterns 泄漏表名/列名：%s" % violations)
                if rnd == self.max_retry:
                    res.error = "重试 %d 次后 patterns 仍包含 schema 标识符：%s" % (self.max_retry, violations)
                    return res
                messages = messages + [{"role": "user", "content": prompts.RETRY_SUFFIX.format(
                    violations="、".join(violations))}]
                continue
            res.validation["passed"] = True
            res.log.append("    校验通过（无 schema 标识符泄漏）")
            break

        res.parsed = parsed
        res.ok = True

        # 入库（置信度过滤 + 存储层去重）
        self._store(res, parsed, tables)
        return res

    # ---------- 入库 ----------

    def _store(self, res: ReviewResult, parsed: dict, tables: List[str] = None):
        m = self.memory

        # Episode：审计归档，直接入库
        ep = parsed.get("episode") or {}
        ep_id = str(ep.get("id") or ("ep_" + str(int(time.time() * 1000))))
        if ep:
            try:
                episode = Episode(
                    id=ep_id,
                    project_id=str(ep.get("project_id") or ""),
                    task_id=str(ep.get("task_id") or ""),
                    ts_start=int(ep.get("ts_start") or 0),
                    ts_end=int(ep.get("ts_end") or 0),
                    status=str(ep.get("status") or "corrected"),
                    goal=str(ep.get("goal") or ""),
                    target=str(ep.get("target") or ""),
                    user_hint=str(ep.get("user_hint") or ""),
                    final_payload=str(ep.get("final_payload") or ""),
                    trajectory=[dict(x) for x in (ep.get("trajectory") or []) if isinstance(x, dict)],
                )
                m.insert_episode(episode)
                res.stored.append({"kind": "episode", "id": episode.id, "action": "insert",
                                   "confidence": 1.0})
                res.log.append("    episode 已归档：" + episode.id)
            except Exception as e:
                res.log.append("    episode 入库失败：" + str(e))

        # Gold：指纹精确去重
        g = parsed.get("gold") or {}
        if g and g.get("payload"):
            try:
                gold = Gold(
                    id=g.get("id") or ("gold_" + str(int(time.time() * 1000))),
                    source_episode=ep_id,
                    fingerprint=dict(g.get("fingerprint") or {}),
                    payload=str(g.get("payload") or ""),
                )
                if tables and not gold.fingerprint.get("tables"):
                    gold.fingerprint["tables"] = list(tables)
                r = m.insert_gold(gold)
                res.stored.append({"kind": "gold", "id": r.id, "action": r.action,
                                   "confidence": float(g.get("confidence") or 1.0)})
                res.log.append("    gold 去重入库：action=%s id=%s" % (r.action, r.id))
            except Exception as e:
                res.log.append("    gold 入库失败：" + str(e))

        # Patterns / ErrorFixes / Insights：置信度过滤 + 向量去重
        self._store_typed(res, "pattern", parsed.get("patterns") or [], m, ep_id)
        self._store_typed(res, "error_fix", parsed.get("error_fixes") or [], m, ep_id)
        self._store_typed(res, "insight", parsed.get("insights") or [], m, ep_id)

    def _store_typed(self, res: ReviewResult, kind: str, items: List[dict],
                     m: MemoryService, ep_id: str = ""):
        for it in items or []:
            try:
                conf = float(it.get("confidence") or 0.0)
            except Exception:
                conf = 0.0
            if conf < self.confidence_min:
                # 低置信度 → 待审队列
                item = m.add_pending(kind, dict(it),
                                     "confidence %.2f < %.2f" % (conf, self.confidence_min), conf)
                res.pending.append({"kind": kind, "id": item.id,
                                    "title": it.get("title") or it.get("error_type") or "",
                                    "confidence": conf})
                res.log.append("    [待审] %s %s confidence=%.2f（%s）" % (
                    kind, it.get("title") or it.get("error_type") or "", conf, item.id))
                continue
            # 置信度达标 → 存储层去重入库
            if kind == "pattern":
                p = Pattern(
                    id=it.get("id") or ("pat_" + str(int(time.time() * 1000))),
                    title=str(it.get("title") or ""),
                    cat=str(it.get("cat") or "其他"),
                    vuln_type=str(it.get("vuln_type") or ""),
                    remediation=str(it.get("remediation") or ""),
                    abstract=str(it.get("abstract") or ""),
                    steps=[str(x) for x in (it.get("steps") or [])],
                    source_episodes=[ep_id] if ep_id else [],
                )
                r = m.insert_pattern(p)
                label = p.title
                # 同步漏洞知识图谱（按 vuln_type 聚合节点）
                try:
                    m.graph.sync_from_pattern(
                        vuln_type=p.vuln_type, technique=p.steps, trigger=p.abstract,
                        remediation=p.remediation, pattern_id=r.id, episode_id=ep_id,
                        human_verified=True, confidence=conf,
                    )
                    res.log.append("    [图谱] 已同步漏洞类型「%s」（node=%s）" % (
                        p.vuln_type or "其他", m.graph.get_by_vuln_type(p.vuln_type or "其他").id))
                except Exception as ge:
                    res.log.append("    [图谱] 同步失败：" + str(ge))
            elif kind == "insight":
                ins = Insight(
                    id=it.get("id") or ("ins_" + str(int(time.time() * 1000))),
                    app_type=str(it.get("app_type") or ""),
                    tech_stack=[str(x) for x in (it.get("tech_stack") or [])],
                    feature_points=[dict(x) for x in (it.get("feature_points") or []) if isinstance(x, dict)],
                    mindset=str(it.get("mindset") or ""),
                    source_episodes=[ep_id] if ep_id else [],
                )
                r = m.insert_insight(ins)
                label = ins.app_type or "未分类"
            else:
                e = ErrorFix(
                    id=it.get("id") or ("ef_" + str(int(time.time() * 1000))),
                    source_episodes=[ep_id] if ep_id else [],
                    error_type=str(it.get("error_type") or "unknown"),
                    error_signature=str(it.get("error_signature") or ""),
                    fix_strategy=str(it.get("fix_strategy") or ""),
                    applies_to=[str(x) for x in (it.get("applies_to") or [])],
                )
                r = m.insert_error_fix(e)
                label = e.error_type
            res.stored.append({"kind": kind, "id": r.id, "action": r.action, "confidence": conf})
            res.log.append("    [入库] %s %s action=%s score=%.3f" % (kind, label, r.action, r.score))

    # ---------- 格式化辅助 ----------

    @staticmethod
    def _format_schema(schema) -> str:
        if isinstance(schema, (dict, list)):
            return json.dumps(schema, ensure_ascii=False, indent=2)
        return str(schema)

    @staticmethod
    def _format_attempts(attempts: List[dict]) -> str:
        lines = []
        for i, a in enumerate(attempts or [], 1):
            lines.append("%d) payload: %s" % (i, a.get("payload") or a.get("sql") or ""))
            lines.append("   报错/现象: %s" % (a.get("error") or a.get("result") or ""))
        return "\n".join(lines) if lines else "（无失败尝试）"
