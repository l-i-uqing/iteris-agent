# -*- coding: utf-8 -*-
"""
memory_smoke_test.py · 经验记忆存储层最小测试脚本

验证（mock 向量，临时库 data/memory_test.db，测完自动删除）：
  1. insert_pattern / search_patterns（增 + 查）
  2. 去重：几乎相同 → merge（不新增、计数 +1）
  3. insert_error_fix / search_error_fixes
  4. Gold：insert_gold / exact_match_gold（精确匹配命中与未命中）
  5. CRUD：get / update / delete（改 + 删）

运行：python memory_smoke_test.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend.memory.models import Pattern, ErrorFix, Gold  # noqa: E402
from backend.memory.service import MemoryService  # noqa: E402

DB_PATH = ROOT / "data" / "memory_test.db"

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


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()
    svc = MemoryService(db_path=str(DB_PATH), embed_backend="mock")
    print("== 1. 插入 Pattern + 检索 ==")

    p1 = Pattern(
        id="pat_01",
        title="堆叠注入 + sql_mode 切换",
        cat="漏洞利用",
        abstract="当登录/查询页面无报错回显、|| 被当作逻辑或而非连接符、且支持堆叠注入时：先执行 set sql_mode=PIPES_AS_CONCAT; 让 || 变为字符串连接，再 select 拼接结果回显。",
        steps=["探测堆叠注入（1;show databases;）", "执行 set sql_mode=PIPES_AS_CONCAT;", "select 拼接回显"],
        source_episodes=["ep_8f2a"],
        human_verified=True,
    )
    r1 = svc.insert_pattern(p1)
    check("insert_pattern 返回 insert", r1.action == "insert", "action=%s" % r1.action)

    p2 = Pattern(
        id="pat_02",
        title="目录枚举定位敏感文件",
        cat="信息收集",
        abstract="先用字典枚举常见目录与备份文件（robots.txt / .git / .bak），命中后继续深挖其子路径。",
        steps=["gobuster/ffuf 枚举", "检查 robots.txt 与备份文件", "深挖命中路径"],
        source_episodes=["ep_77aa"],
    )
    r2 = svc.insert_pattern(p2)
    check("insert_pattern #2 返回 insert", r2.action == "insert", "action=%s" % r2.action)
    check("库内 pattern 数 = 2", svc.list_patterns().__len__() == 2, "n=%d" % len(svc.list_patterns()))

    hits = svc.search_patterns("登录页面堆叠注入 sql_mode 拼接回显拿数据", top_k=3)
    check("search_patterns 命中堆叠注入", len(hits) > 0 and hits[0]["id"] == "pat_01",
          "top1=%s score=%.3f" % (hits[0]["id"] if hits else None, hits[0]["score"] if hits else 0))
    check("命中结果带公共字段", hits and "human_verified" in hits[0] and "success_count" in hits[0] and "created_at" in hits[0])

    print("== 2. 去重：几乎相同 → merge ==")
    p1_dup = Pattern(
        id="pat_01_dup",
        title="堆叠注入 + sql_mode 切换",
        cat="漏洞利用",
        abstract=p1.abstract + "（这次也是这么解的）",
        steps=list(p1.steps),
        source_episodes=["ep_9b3c"],
    )
    before = svc.list_patterns().__len__()
    rm = svc.insert_pattern(p1_dup)
    check("重复沉淀 → merge（不新增）", rm.action == "merge" and svc.list_patterns().__len__() == before,
          "action=%s score=%.3f" % (rm.action, rm.score))
    merged = svc.get_pattern("pat_01")
    check("merge 后 hit_count +1", merged.hit_count == 1, "hit_count=%d" % merged.hit_count)
    check("merge 后 success_count +1", merged.success_count == 1)
    check("merge 后来源合并", "ep_9b3c" in merged.source_episodes, "src=%s" % merged.source_episodes)

    print("== 3. ErrorFix 插入 + 检索 ==")
    e1 = ErrorFix(
        id="ef_01",
        error_type="url_encode",
        error_signature="ERR_HTTP_RESPONSE_CODE_FAILURE，URL 中 %23 注释符失效",
        fix_strategy="改用 -- - 或行内注释 /*!*/；%23 先做 URL 编码再发包",
        applies_to=["sql_injection"],
        source_episodes=["ep_8f2a"],
    )
    re1 = svc.insert_error_fix(e1)
    check("insert_error_fix 返回 insert", re1.action == "insert", "action=%s" % re1.action)
    e2 = ErrorFix(
        id="ef_02",
        error_type="timeout",
        error_signature="请求超时，靶场响应缓慢",
        fix_strategy="降低并发、增大超时时间、分批探测",
        applies_to=["general"],
        source_episodes=["ep_77aa"],
    )
    svc.insert_error_fix(e2)
    ehits = svc.search_error_fixes("ERR_HTTP_RESPONSE_CODE_FAILURE 注释符在 URL 里失效", top_k=3)
    check("search_error_fixes 命中 ef_01", len(ehits) > 0 and ehits[0]["id"] == "ef_01",
          "top1=%s score=%.3f" % (ehits[0]["id"] if ehits else None, ehits[0]["score"] if ehits else 0))

    print("== 4. Gold 精确匹配 ==")
    fp = {"vuln_type": "sql_injection", "weakness": "stacked_queries",
          "signature": "无报错回显 | || 被当逻辑或 | 堆叠注入可行"}
    g1 = Gold(
        id="gold_01",
        source_episode="ep_8f2a",
        fingerprint=fp,
        payload="1;set sql_mode=PIPES_AS_CONCAT;select 1",
    )
    rg = svc.insert_gold(g1)
    check("insert_gold 返回 insert", rg.action == "insert", "action=%s" % rg.action)
    got = svc.exact_match_gold(fp)
    check("exact_match_gold 命中", got is not None and got.payload == "1;set sql_mode=PIPES_AS_CONCAT;select 1",
          "payload=%s" % (got.payload if got else None))
    rg2 = svc.insert_gold(Gold(id="gold_01_dup", source_episode="ep_x", fingerprint=fp, payload="same"))
    check("重复 Gold 指纹 → merge 不新增", rg2.action == "merge" and svc.list_gold().__len__() == 1,
          "action=%s n=%d" % (rg2.action, len(svc.list_gold())))
    miss = svc.exact_match_gold({"vuln_type": "command_injection", "weakness": "pipe"})
    check("exact_match_gold 未命中返回 None", miss is None)

    print("== 5. CRUD（改 / 删） ==")
    p = svc.get_pattern("pat_01")
    p.abstract += "（补充：分号在 payload 中也需注意编码）"
    p.version = p.version + 1
    p.human_verified = True
    svc.patterns.update(p)
    p2 = svc.get_pattern("pat_01")
    check("update 后内容变化", "分号在 payload" in p2.abstract, "v=%d" % p2.version)
    check("delete_pattern", svc.delete_pattern("pat_02") is True and svc.get_pattern("pat_02") is None)
    check("delete_error_fix", svc.delete_error_fix("ef_02") is True and svc.get_error_fix("ef_02") is None)
    check("delete_gold", svc.delete_gold("gold_01") is True and svc.get_gold("gold_01") is None)
    check("删除不存在的返回 False", svc.delete_pattern("pat_none") is False)

    svc.close()
    if DB_PATH.exists():
        DB_PATH.unlink()
        print("\n临时库已清理:", DB_PATH)

    print("\n======== 结果：%d PASS / %d FAIL ========" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
