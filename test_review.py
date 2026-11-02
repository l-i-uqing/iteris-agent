# -*- coding: utf-8 -*-
"""
test_review.py · 复盘模块测试（3 个用例：语法错 / 逻辑错 / 遗漏边界）

- mock LLM（可注入响应队列，验证打回重生成）
- 打印每步中间结果（res.log）
- 临时库 data/memory_review_test.db，测完删除

运行：python test_review.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend.memory.review import ReviewService  # noqa: E402
from backend.memory.service import MemoryService  # noqa: E402

DB_PATH = ROOT / "data" / "memory_review_test.db"

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS]", name, extra)
    else:
        FAIL += 1
        print("  [FAIL]", name, extra)


class MockLLM:
    """响应队列 mock：第一次调用返回第 1 个，打回后返回第 2 个……"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, messages, response_format=None):
        self.calls += 1
        if not self.responses:
            raise RuntimeError("mock 响应耗尽")
        return self.responses.pop(0)


def load(fn):
    return json.loads(Path(fn).read_text(encoding="utf-8"))


# ---------------- 用例 1：语法错（含校验打回重生成） ----------------

CASE1_QUESTION = "登录框存在 SQL 注入，提交查询后报语法错误，目标是从数据库中读取 flag。"
CASE1_SCHEMA = {"table": "flag", "columns": ["flag"]}
CASE1_ATTEMPTS = [
    {"payload": "admin' or '1'='1", "error": "You have an error in your SQL syntax near '1'='1'"},
    {"payload": "admin' --+", "error": "ERR_HTTP_RESPONSE_CODE_FAILURE，--+ 在 URL 中失效"},
]
CASE1_GOLD = "1' union select 1,2 -- -"
CASE1_NOTE = "注意：注释符用 -- - 或 %23，--+ 会被过滤。"

CASE1_RESPONSES = [
    # 第 1 次：patterns 泄漏表名 flag → 应打回
    json.dumps({
        "episode": {"id": "ep_c1", "goal": "登录框 SQL 注入取 flag", "target": "登录页",
                    "status": "corrected", "user_hint": CASE1_NOTE, "final_payload": CASE1_GOLD,
                    "trajectory": [{"step": 1, "kind": "attempt", "payload": "admin' or '1'='1", "error": "syntax error", "ok": False}]},
        "gold": {"fingerprint": {"vuln_type": "sql_injection", "weakness": "quote_closure",
                                 "signature": "单引号触发语法报错，注释符在 URL 中失效"},
                 "payload": CASE1_GOLD, "confidence": 0.9},
        "patterns": [{"title": "单引号闭合注入", "cat": "漏洞利用",
                      "abstract": "输入单引号报语法错误说明存在字符型注入，闭合后查 flag 表内容",
                      "steps": ["闭合引号", "union 查询 flag 表"], "confidence": 0.8,
                      "reason": "报错直接佐证"}],
        "error_fixes": [{"error_type": "syntax_error",
                         "error_signature": "You have an error in your SQL syntax，单引号未闭合",
                         "fix_strategy": "正确闭合单引号，再拼接 union 语句", "applies_to": ["sql_injection"], "confidence": 0.85},
                        {"error_type": "url_encode",
                         "error_signature": "ERR_HTTP_RESPONSE_CODE_FAILURE，--+ 在 URL 中失效",
                         "fix_strategy": "改用 -- - 或 %23，特殊字符先 URL 编码", "applies_to": ["sql_injection"], "confidence": 0.8}],
    }, ensure_ascii=False),
    # 第 2 次（打回后）：patterns 已剥离表名
    json.dumps({
        "episode": {"id": "ep_c1", "goal": "登录框 SQL 注入取 flag", "target": "登录页",
                    "status": "corrected", "user_hint": CASE1_NOTE, "final_payload": CASE1_GOLD,
                    "trajectory": [{"step": 1, "kind": "attempt", "payload": "admin' or '1'='1", "error": "syntax error", "ok": False}]},
        "gold": {"fingerprint": {"vuln_type": "sql_injection", "weakness": "quote_closure",
                                 "signature": "单引号触发语法报错，注释符在 URL 中失效"},
                 "payload": CASE1_GOLD, "confidence": 0.9},
        "patterns": [{"title": "单引号闭合注入", "cat": "漏洞利用",
                      "abstract": "输入单引号报语法错误说明存在字符型注入，闭合后按目标表字段数对齐 union 查询目标数据",
                      "steps": ["闭合引号", "order by 探测列数", "union 对齐查询目标数据"], "confidence": 0.8,
                      "reason": "报错直接佐证"}],
        "error_fixes": [{"error_type": "syntax_error",
                         "error_signature": "You have an error in your SQL syntax，单引号未闭合",
                         "fix_strategy": "正确闭合单引号，再拼接 union 语句", "applies_to": ["sql_injection"], "confidence": 0.85},
                        {"error_type": "url_encode",
                         "error_signature": "ERR_HTTP_RESPONSE_CODE_FAILURE，--+ 在 URL 中失效",
                         "fix_strategy": "改用 -- - 或 %23，特殊字符先 URL 编码", "applies_to": ["sql_injection"], "confidence": 0.8}],
    }, ensure_ascii=False),
]

# ---------------- 用例 2：逻辑错（列数不匹配 / || 被当逻辑或） ----------------

CASE2_QUESTION = "查询页面能回显结果，但 || 被当作逻辑或而非连接符，需要堆叠注入拿数据。"
CASE2_SCHEMA = {"table": "flag", "columns": ["flag"]}
CASE2_ATTEMPTS = [
    {"payload": "1' union select 1,2", "error": "The used SELECT statements have a different number of columns"},
    {"payload": "1 || flag", "error": "无回显，|| 被当作逻辑或 OR"},
]
CASE2_GOLD = "1;set sql_mode=PIPES_AS_CONCAT;select 1||flag from flag"
CASE2_NOTE = "提示：先试堆叠注入，再 set sql_mode=PIPES_AS_CONCAT 让 || 变连接符"

CASE2_RESPONSES = [json.dumps({
    "episode": {"id": "ep_c2", "goal": "堆叠注入取数据", "target": "查询页",
                "status": "corrected", "user_hint": CASE2_NOTE, "final_payload": CASE2_GOLD,
                "trajectory": [{"step": 1, "kind": "attempt", "payload": "1' union select 1,2", "error": "columns mismatch", "ok": False}]},
    "gold": {"fingerprint": {"vuln_type": "sql_injection", "weakness": "stacked_queries",
                             "signature": "无报错回显，|| 被当逻辑或，堆叠注入可行"},
             "payload": CASE2_GOLD, "confidence": 0.95},
    "patterns": [{"title": "堆叠注入配合 sql_mode 切换让 || 变连接符", "cat": "漏洞利用",
                  "abstract": "当回显无报错、|| 被当作逻辑或而非连接符、且支持堆叠注入时：先执行 set sql_mode=PIPES_AS_CONCAT; 让 || 变为字符串连接，再通过 select 拼接查询结果回显",
                  "steps": ["用分号探测堆叠注入（1;show databases;）", "执行 set sql_mode=PIPES_AS_CONCAT;", "select 拼接目标数据到回显"],
                  "confidence": 0.9, "reason": "gold_sql 直接支持"}],
    "error_fixes": [{"error_type": "column_mismatch",
                     "error_signature": "The used SELECT statements have a different number of columns",
                     "fix_strategy": "用 order by N 逐次探测正确列数，union 的列数必须与目标查询一致",
                     "applies_to": ["sql_injection"], "confidence": 0.85}],
}, ensure_ascii=False)]

# ---------------- 用例 3：遗漏边界（数据截断 → 低置信度待审） ----------------

CASE3_QUESTION = "union 注入能读出第一行数据，但后续行全部丢失，怀疑存在数据截断边界。"
CASE3_SCHEMA = {"table": "users", "columns": ["id", "username", "password"]}
CASE3_ATTEMPTS = [
    {"payload": "1' union select username from users", "error": "只回显第一行，后续数据全部丢失"},
]
CASE3_GOLD = "1' union select group_concat(username) from users -- -"
CASE3_NOTE = ""

CASE3_RESPONSES = [json.dumps({
    "episode": {"id": "ep_c3", "goal": "解决数据截断", "target": "查询页",
                "status": "corrected", "user_hint": "", "final_payload": CASE3_GOLD,
                "trajectory": [{"step": 1, "kind": "attempt", "payload": "1' union select username from users", "error": "只回显第一行", "ok": False}]},
    "gold": {"fingerprint": {"vuln_type": "sql_injection", "weakness": "truncation",
                             "signature": "union 只回显第一行，疑似截断"},
             "payload": CASE3_GOLD, "confidence": 0.88},
    "patterns": [{"title": "回显截断时用聚合函数拼接", "cat": "漏洞利用",
                  "abstract": "当 union 注入只回显第一行、后续数据丢失时，可用聚合函数把多行拼接为单行，绕过回显条数限制",
                  "steps": ["确认只回显第一行", "用聚合函数拼接目标字段为单行", "在回显点读取"], "confidence": 0.4,
                  "reason": "证据间接，成功方法未经完整复现验证"}],
    "error_fixes": [{"error_type": "truncation",
                     "error_signature": "只回显第一行，后续数据丢失",
                     "fix_strategy": "改用聚合函数（group_concat 等）把多行拼成单行，或分页限制偏移逐批提取",
                     "applies_to": ["sql_injection"], "confidence": 0.45}],
}, ensure_ascii=False)]


def run_case(name, question, schema, attempts, gold, note, responses, expect_pending=0):
    print("\n" + "=" * 60)
    print("用例：%s" % name)
    print("=" * 60)
    svc = MemoryService(db_path=str(DB_PATH), embed_backend="mock")
    mock = MockLLM(responses)
    rs = ReviewService(memory=svc, llm_call=mock)
    res = rs.review(question, schema, attempts, gold, note)

    print("---- 逐步中间结果 ----")
    for line in res.log:
        print("  " + line)
    print("---- 断言 ----")
    check("复盘成功 ok=True", res.ok, res.error)
    check("schema 标识符提取", res.schema_terms == sorted(["flag"]) or res.schema_terms == sorted(["users", "id", "username", "password"]),
          "terms=%s" % res.schema_terms)
    check("patterns 无 schema 泄漏", not res.validation.get("violations"),
          "violations=%s" % res.validation.get("violations"))
    check("gold 已入库", any(s["kind"] == "gold" for s in res.stored),
          "stored=%s" % [s["kind"] for s in res.stored])
    check("待审数符合预期", len(res.pending) == expect_pending,
          "pending=%d（预期 %d）" % (len(res.pending), expect_pending))
    if res.pending:
        check("待审条目置信度 < 0.5", all(p["confidence"] < 0.5 for p in res.pending),
              "confs=%s" % [p["confidence"] for p in res.pending])
    svc.close()
    return res


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()

    # 用例 1：语法错（mock 第一次泄漏表名 → 打回 → 第二次修正）
    r1 = run_case("语法错 + 校验打回重生成", CASE1_QUESTION, CASE1_SCHEMA,
                  CASE1_ATTEMPTS, CASE1_GOLD, CASE1_NOTE, CASE1_RESPONSES)
    check("打回发生过（调用 2 次 LLM，最终通过）", r1.validation["rounds"] == 2,
          "rounds=%d（第 1 次泄漏 flag 被拦截）" % r1.validation["rounds"])
    check("error_fixes 贴近报错", any("SQL syntax" in s.get("error_signature", "") or
                                      "ERR_HTTP" in s.get("error_signature", "") for s in
                                      r1.parsed.get("error_fixes", [])),
          "ef=%s" % [e["error_signature"][:30] for e in r1.parsed.get("error_fixes", [])])

    # 用例 2：逻辑错（列数不匹配 + || 逻辑或）
    r2 = run_case("逻辑错（列数不匹配 / || 当逻辑或）", CASE2_QUESTION, CASE2_SCHEMA,
                  CASE2_ATTEMPTS, CASE2_GOLD, CASE2_NOTE, CASE2_RESPONSES)
    pat_titles = [p["title"] for p in r2.parsed.get("patterns", [])]
    check("patterns 含堆叠注入思路", any("堆叠" in t for t in pat_titles), "titles=%s" % pat_titles)
    check("patterns 已剥离表名列名", all("flag" not in (p.get("title", "") + p.get("abstract", "")) for p in r2.parsed.get("patterns", [])))
    # 重复复盘（同一题）→ gold 指纹 merge 不新增
    svc = MemoryService(db_path=str(DB_PATH), embed_backend="mock")
    rs = ReviewService(memory=svc, llm_call=MockLLM(CASE2_RESPONSES))
    res2 = rs.review(CASE2_QUESTION, CASE2_SCHEMA, CASE2_ATTEMPTS, CASE2_GOLD, CASE2_NOTE)
    print("    重复复盘 stored:", res2.stored)
    golds = svc.list_gold()
    check("重复复盘 gold 指纹去重（不新增第 3 条）", len(golds) == 2,
          "gold 数=%d（用例1 + 用例2 各一条，重复复盘 merge 未新增）" % len(golds))
    check("重复复盘 gold 返回 merge", any(s["kind"] == "gold" and s["action"] == "merge" for s in res2.stored))
    svc.close()

    # 用例 3：遗漏边界（低置信度 → 待审队列）
    r3 = run_case("遗漏边界（数据截断，低置信度待审）", CASE3_QUESTION, CASE3_SCHEMA,
                  CASE3_ATTEMPTS, CASE3_GOLD, CASE3_NOTE, CASE3_RESPONSES, expect_pending=2)
    svc = MemoryService(db_path=str(DB_PATH), embed_backend="mock")
    pend = svc.list_pending()
    check("待审队列持久化", len(pend) == 2, "pending=%d" % len(pend))
    check("低置信度条目未进正式库", not any(p.title == "回显截断时用聚合函数拼接" for p in svc.list_patterns()),
          "patterns=%d" % len(svc.list_patterns()))
    svc.close()

    # 清理
    if DB_PATH.exists():
        DB_PATH.unlink()
    print("\n临时库已清理:", DB_PATH)
    print("\n======== 结果：%d PASS / %d FAIL ========" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
