# -*- coding: utf-8 -*-
"""
test_recall.py · 读取侧（经验注入）端到端测试

每个阶段用独立临时库，避免数据串扰。

覆盖：
  1. 假数据：pre_solve_inject 拼接（Top3 上限 / gold 同题标记 / 排序 / 文本截断）
  2. 排序权重：human_verified > success_count > 向量相似度
  3. 报错后：error_fix_inject 命中（真实报错）与未命中（空库 miss）
  4. 端到端：同一道题 错一次 → 纠正 → 复盘入库 → 变体题同题命中 → 无关题不命中
  5. 召回日志与命中率统计

说明：mock 向量（n-gram 哈希）对"中文题目 vs 英文报错"语义不敏感，
     英文报错检索用原文 query 验证（阶段 3）；真实 embedding 接入后语义匹配自动增强。

运行：python test_recall.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend.memory.features import extract_features  # noqa: E402
from backend.memory.models import ErrorFix, Gold, Pattern  # noqa: E402
from backend.memory.recall import RecallService  # noqa: E402
from backend.memory.review import ReviewService  # noqa: E402
from backend.memory.service import MemoryService  # noqa: E402

DB1 = ROOT / "data" / "mem_r1.db"   # 阶段1/3：假数据 + 报错注入
DB2 = ROOT / "data" / "mem_r2.db"   # 阶段2：排序
DB3 = ROOT / "data" / "mem_r3.db"   # 阶段4/5：端到端
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


def rm(path):
    if path.exists():
        path.unlink()


def seed_fake(m: MemoryService):
    """假数据：3 pattern + 2 error_fix + 1 gold（模拟复盘入库产物）"""
    m.insert_pattern(Pattern(
        id="p_a", title="堆叠注入配合 sql_mode 切换", cat="漏洞利用",
        abstract="当回显无报错、|| 被当作逻辑或而非连接符、且支持堆叠注入时：先执行 set sql_mode=PIPES_AS_CONCAT; "
                 "让 || 变为字符串连接，再通过 select 拼接查询结果回显。这是经过多次实战验证的有效路径，"
                 "适用面覆盖登录框、查询框、留言板等常见回显场景，遇到同类现象应优先尝试此方向，"
                 "同时注意分号与空格的编码处理。",
        steps=["探测堆叠", "切 sql_mode", "select 拼接"], human_verified=True, success_count=3))
    m.insert_pattern(Pattern(
        id="p_b", title="目录枚举定位敏感文件", cat="信息收集",
        abstract="用字典枚举目录与备份文件，命中后深挖。", steps=["枚举", "深挖"],
        human_verified=False, success_count=0))
    m.insert_pattern(Pattern(
        id="p_c", title="SSRF 探测内网", cat="漏洞利用",
        abstract="存在 url 参数时尝试内网地址探测。", steps=["探测", "读内网"],
        human_verified=True, success_count=1))
    m.insert_error_fix(ErrorFix(
        id="e_a", error_type="column_mismatch",
        error_signature="The used SELECT statements have a different number of columns",
        fix_strategy="用 order by N 逐次探测正确列数，union 列数必须一致",
        applies_to=["sql_injection"], human_verified=True, success_count=5))
    m.insert_error_fix(ErrorFix(
        id="e_b", error_type="url_encode",
        error_signature="ERR_HTTP_RESPONSE_CODE_FAILURE，注释符在 URL 中失效",
        fix_strategy="改用 -- - 或 %23，特殊字符 URL 编码",
        applies_to=["sql_injection"], human_verified=False, success_count=1))
    m.insert_gold(Gold(
        id="g_a", source_episode="ep_x",
        fingerprint={"vuln_type": "sql_injection", "weakness": "stacked_queries",
                     "signature": "无报错回显，|| 被当逻辑或", "tables": ["flag"]},
        payload="1;set sql_mode=PIPES_AS_CONCAT;select 1||flag from flag",
        human_verified=True, success_count=2))


def main():
    rm(DB1); rm(DB2); rm(DB3)

    # ========== 1. 假数据：拼接正确 ==========
    print("== 1. 假数据：pre_solve_inject 拼接 ==")
    m1 = MemoryService(db_path=str(DB1), embed_backend="mock")
    seed_fake(m1)
    r = RecallService(m1)

    feats = extract_features("登录页存在 SQL 注入，页面无报错回显且 || 被当逻辑或，目标是拿到 flag",
                             {"table": "flag", "columns": ["flag"]})
    check("特征提取：vuln_type=sql_injection", feats["vuln_type"] == "sql_injection", feats["vuln_type"])
    check("特征提取：tables=[flag]", feats["tables"] == ["flag"], str(feats["tables"]))

    q_a = "登录页存在 SQL 注入，页面无报错回显且 || 被当逻辑或，目标是拿到 flag"
    ctx = r.pre_solve_inject(q_a, {"table": "flag", "columns": ["flag"]}, project_id="t1")
    print("  ---- 注入的先验提示 ----")
    print(ctx["prior_prompt"])
    check("patterns 取 Top3", len(ctx["patterns"]) <= 3, "n=%d" % len(ctx["patterns"]))
    check("error_fixes 取 Top3", len(ctx["error_fixes"]) <= 3, "n=%d" % len(ctx["error_fixes"]))
    check("排序权重：已验证的堆叠注入排第一",
          ctx["patterns"][0]["id"] == "p_a" and ctx["patterns"][0]["human_verified"] is True,
          "top1=%s" % (ctx["patterns"][0]["id"] if ctx["patterns"] else "None"))
    check("gold 同题精确命中", ctx["gold_hit"] is not None and ctx["gold_payload"].startswith("1;set"))
    check("先验提示含【同题提示】与历史 payload", "【同题提示】" in ctx["prior_prompt"] and "1;set sql_mode" in ctx["prior_prompt"])
    check("先验提示含【相似解法】", "【先验经验·相似解法】" in ctx["prior_prompt"])
    check("长文本已截断", "…" in ctx["prior_prompt"])

    # ========== 2. 排序权重 ==========
    print("== 2. 排序权重：human_verified > success_count > 相似度 ==")
    m2 = MemoryService(db_path=str(DB2), embed_backend="mock")
    m2.insert_pattern(Pattern(id="p_low", title="SQL 注入基础探测",
                              abstract="输入单引号观察报错，union 对齐列数，读取数据库中的数据。与登录注入高度相关的详细描述。",
                              human_verified=False, success_count=0))
    m2.insert_pattern(Pattern(id="p_high", title="注入类通用思路",
                              abstract="注入优先确认类型与列数", human_verified=True, success_count=10))
    hits = m2.patterns.search(m2.embedder.embed("SQL 注入 union 探测列数 读取数据库数据"), 3)
    order = [h.item.id for h in hits]
    check("已验证条目优先于高相似度未验证条目", order[0] == "p_high",
          "order=%s" % order)
    m2.close()

    # ========== 3. 报错后注入 ==========
    print("== 3. 报错后：error_fix_inject ==")
    hit = r.error_fix_inject("The used SELECT statements have a different number of columns", project_id="t1")
    check("命中历史错误 → miss=False + 修正提示", hit["miss"] is False and hit["fix_prompt"].startswith("【报错修正】"))
    check("修正策略注入（order by）", "order by" in hit["fix_prompt"])
    # 空库 miss：确定性验证
    m_empty = MemoryService(db_path=str(DB2), embed_backend="mock")
    r_empty = RecallService(m_empty)
    miss = r_empty.error_fix_inject("任意报错：UNKNOWN_ERR_9x9x9x", project_id="t_empty")
    check("空库未命中 → miss=True 且不注入", miss["miss"] is True and miss["fix_prompt"] == "")
    m_empty.close()

    # ========== 4. 端到端：错→纠正→复盘→变体题 ==========
    print("== 4. 端到端：同一题错→纠正→复盘→变体题注入 ==")
    m3 = MemoryService(db_path=str(DB3), embed_backend="mock")
    qA = "登录页面存在 SQL 注入，查询结果回显但 || 被当作逻辑或，目标是拿到 flag。"
    schemaA = {"table": "flag", "columns": ["flag"]}
    attemptsA = [
        {"payload": "1' union select 1,2", "error": "The used SELECT statements have a different number of columns"},
        {"payload": "1 || flag", "error": "无回显，|| 被当作逻辑或"},
    ]
    goldA = "1;set sql_mode=PIPES_AS_CONCAT;select 1||flag from flag"
    review_payload = json.dumps({
        "episode": {"id": "ep_a", "goal": qA, "target": "登录页", "status": "corrected",
                    "user_hint": "提示：堆叠注入+sql_mode", "final_payload": goldA,
                    "trajectory": [{"step": 1, "kind": "attempt", "payload": "1' union select 1,2", "error": "columns mismatch", "ok": False}]},
        "gold": {"fingerprint": {"vuln_type": "sql_injection", "weakness": "stacked_queries",
                                 "signature": "无报错回显，|| 被当逻辑或"},
                 "payload": goldA, "confidence": 0.95},
        "patterns": [{"title": "堆叠注入配合 sql_mode 切换让 || 变连接符", "cat": "漏洞利用",
                      "abstract": "当回显无报错、|| 被当作逻辑或而非连接符、且支持堆叠注入时：先执行 set sql_mode=PIPES_AS_CONCAT; 让 || 变为字符串连接，再 select 拼接查询结果回显",
                      "steps": ["探测堆叠", "切 sql_mode", "select 拼接"], "confidence": 0.9}],
        "error_fixes": [{"error_type": "column_mismatch",
                         "error_signature": "The used SELECT statements have a different number of columns",
                         "fix_strategy": "用 order by N 探测列数，union 对齐",
                         "applies_to": ["sql_injection"], "confidence": 0.85}],
    }, ensure_ascii=False)
    rs = ReviewService(memory=m3, llm_call=lambda msgs, rf=None: review_payload)
    rr = rs.review(qA, schemaA, attemptsA, goldA, "提示：堆叠注入+sql_mode")
    check("复盘成功且 gold 入库", rr.ok and len(m3.list_gold()) == 1, "gold=%d" % len(m3.list_gold()))
    check("gold fingerprint 带 tables=[flag]", m3.list_gold()[0].fingerprint.get("tables") == ["flag"])

    r3 = RecallService(m3)
    ctxA = r3.pre_solve_inject(qA, schemaA, project_id="e2e")
    check("原题再次出现 → gold 同题命中", ctxA["gold_hit"] is not None)

    qB = "另一个查询页面也有 SQL 注入，flag 表，回显无报错，|| 被当逻辑或，帮我拿数据。"
    schemaB = {"table": "flag", "columns": ["flag"]}
    ctxB = r3.pre_solve_inject(qB, schemaB, project_id="e2e")
    check("变体题 B → gold 同题命中（vuln_type+表名精确）",
          ctxB["gold_hit"] is not None and ctxB["gold_payload"] == goldA)
    check("变体题 B 先验提示含历史解法", "1;set sql_mode" in ctxB["prior_prompt"])

    qC = "目标存在路径遍历，能读取服务器任意文件，目标是读取系统配置。"
    ctxC = r3.pre_solve_inject(qC, {}, project_id="e2e")
    check("无关题 C → gold 不命中", ctxC["gold_hit"] is None)
    check("无关题 C → 无同题提示", "【同题提示】" not in ctxC["prior_prompt"])

    # 报错后注入（e2e 库内）→ 计入统计
    ef = r3.error_fix_inject("The used SELECT statements have a different number of columns", project_id="e2e")
    check("e2e 报错命中列数不匹配 fix", ef["miss"] is False and "order by" in ef["fix_prompt"])

    # ========== 5. 召回日志与命中率 ==========
    print("== 5. 召回日志与命中率统计 ==")
    stats = m3.recall_stats(project_id="e2e")
    for k, v in sorted(stats.items()):
        print("    %s: 召回 %d 次，命中 %d 次，命中率 %.1f%%" % (k, v["total"], v["hit"], v["rate"] * 100))
    check("召回日志已记录（pre_solve/gold）", "pre_solve/gold" in stats, str(sorted(stats.keys())))
    check("gold 同题命中率 = 66.7%（3 次 pre_solve 命中 2 次）",
          stats.get("pre_solve/gold", {}).get("rate", 0) == round(2 / 3, 3),
          "rate=%s" % stats.get("pre_solve/gold", {}).get("rate"))
    check("error_fix 命中已记录", stats.get("error_fix/error_fix", {}).get("hit", 0) >= 1,
          str(stats.get("error_fix/error_fix")))

    m1.close(); m3.close()
    rm(DB1); rm(DB2); rm(DB3)
    print("\n临时库已清理")
    print("\n======== 结果：%d PASS / %d FAIL ========" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
