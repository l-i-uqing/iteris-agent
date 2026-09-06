# -*- coding: utf-8 -*-
"""
skills.py · 渗透技能库（Skills）
- 全局库：data/skills.json（多项目共用）；项目私有：data/projects/<pid>/skills.json
- 内置种子技能（方法论级，面向 CTF/靶场/授权评估场景）
- 按任务语义 BM25 召回相关技能（不全量灌入，防止 token 爆炸）
- 仅提供检索与结构化；AI 生成"优化建议"在前端完成，写入必须人工确认
"""
import math
import re
import time

from . import storage

SKILL_CATS = ["信息收集", "漏洞探测", "漏洞利用", "后渗透", "报告编写", "其他"]

_STOP = set("的 了 是 在 我 你 他 她 它 这 那 有 和 与 就 也 都 而 及 等 被 把 让 向 从 对 用 以 为 于 其 或 并 但 只 还 可 已 很 最 更 要 会 能 应 需 请问 怎么 如何 为什么 什么 一个 扫描 渗透 测试 目标 任务".split())


def _now():
    return int(time.time() * 1000)


def build_seed():
    """内置种子技能：方法论 + 授权边界提示，面向 CTF/靶场/已授权评估"""
    ts = _now()
    raw = [
        {
            "id": "s-info-001", "title": "Nmap 端口与服务识别", "cat": "信息收集",
            "steps": [
                "nmap -sV -sC -T4 <目标>：快速识别开放端口与服务版本",
                "nmap -p- -T4 <目标>：全端口扫描，补足默认端口之外的发现",
                "nmap -O <目标>：操作系统指纹（需管理员权限）",
                "按端口/服务分组整理结果，再决定下一步探测方向",
            ],
            "exp": "靶场/CTF 先 -sV -sC 一把梭；全端口扫描慢时可加 --min-rate 1000；端口少时优先看常见服务的默认配置",
            "pit": "-sV 对 UDP 无效；仅可扫描 CTF/靶场/已获授权的目标",
        },
        {
            "id": "s-info-002", "title": "目录与子域枚举", "cat": "信息收集",
            "steps": [
                "gobuster dir -u http://<目标> -w <字典>：枚举目录",
                "ffuf -w <字典> -u http://<目标>/FUZZ：快速模糊",
                "gobuster dns -d <域名> -w <子域字典>：子域名枚举",
                "关注 robots.txt、sitemap.xml、.git 泄露、备份文件",
            ],
            "exp": "字典质量决定效率；命中 200/301 后继续深挖其子路径；403 目录可能可绕过",
            "pit": "大字典会刷爆访问日志，靶场小站点建议限速 --rate；枚举前确认目标在授权范围内",
        },
        {
            "id": "s-info-003", "title": "Web 指纹识别", "cat": "信息收集",
            "steps": [
                "whatweb <目标>：快速识别中间件/框架",
                "观察响应头（Server、X-Powered-By、Cookie 特征）",
                "根据指纹与版本匹配已知漏洞",
            ],
            "exp": "指纹+版本能直接命中已知 CVE，省去盲目扫描",
            "pit": "部分框架会伪装 Server 头；指纹识别结果要与实际功能交叉验证",
        },
        {
            "id": "s-vuln-001", "title": "Web 应用漏洞扫描", "cat": "漏洞探测",
            "steps": [
                "对已确认的服务做针对性探测（nikto -h <目标> 快速基线）",
                "手工验证自动化扫描结果，避免误报",
                "按 OWASP Top 10 逐类检查（注入/认证/越权/XSS 等）",
            ],
            "exp": "自动化扫描结果必须手工复现确认；先看认证与授权逻辑，越权类漏洞性价比最高",
            "pit": "全站主动扫描可能破坏功能或触发 WAF 拦截；扫描前确认授权与范围",
        },
        {
            "id": "s-vuln-002", "title": "SQL 注入检测", "cat": "漏洞探测",
            "steps": [
                "输入 ' 与 \" 观察报错与行为差异",
                "时间盲注判断：SLEEP(5) / pg_sleep / WAITFOR DELAY",
                "手工确认注入类型（字符型/数字型）与数据库类型",
            ],
            "exp": "先手工判断注入点再上自动化工具；输出受限时用时间盲注或 OAST",
            "pit": "报错信息可能被框架吞掉；post 参数注入要带请求体；未授权目标禁止测试",
        },
        {
            "id": "s-exploit-001", "title": "SQLMap 自动化利用", "cat": "漏洞利用",
            "steps": [
                "sqlmap -u \"<URL>\" --batch：基础检测",
                "--dbs / -D <库> --tables / -T <表> --dump：逐级提取数据",
                "需要写文件时尝试 --os-shell（需高权限与特定数据库）",
                "把完整利用链记录进报告",
            ],
            "exp": "--batch 避免交互卡住；--risk=3 --level=3 提高检出但更慢",
            "pit": "数据量大时控制 --dump 的列数；仅限授权目标",
        },
        {
            "id": "s-exploit-002", "title": "弱口令与凭据爆破", "cat": "漏洞利用",
            "steps": [
                "hydra -l admin -P <字典> ssh://<目标> 等协议爆破",
                "先试默认凭据与常见弱口令组合",
                "Web 登录接口用 Burp 拦截后爆破，或 hydra http-post-form",
            ],
            "exp": "先收集有效用户名再爆破密码效率更高；观察锁定策略避免封禁",
            "pit": "有验证码/锁定策略的接口爆破会失败或封 IP；爆破务必限速",
        },
        {
            "id": "s-post-001", "title": "反弹 Shell 与权限提升（仅授权环境）", "cat": "后渗透",
            "steps": [
                "确认可利用漏洞后生成 payload（msfvenom）并在攻击机监听",
                "获得反弹 shell 后先加固会话（TTY、环境变量）",
                "权限提升排查：sudo -l、SUID 文件、内核版本对应利用",
                "每步操作留痕，便于复盘与报告",
            ],
            "exp": "反弹 shell 不稳定时改用多次重连或换监听端口；linpeas 可一键收集提权信息",
            "pit": "后渗透只允许在授权靶场/实验环境执行；禁止对生产未授权系统操作",
        },
        {
            "id": "s-post-002", "title": "内网信息收集与横向移动", "cat": "后渗透",
            "steps": [
                "获得权限后先收集本机信息（用户、网络、进程、凭据缓存）",
                "探测内网存活主机与开放端口",
                "寻找可横向移动的凭据与服务",
                "记录完整攻击链",
            ],
            "exp": "凭据复用（相同密码）是横向移动最常见入口",
            "pit": "横向移动必须在授权范围内；注意审计日志，避免留下过多痕迹",
        },
        {
            "id": "s-report-001", "title": "渗透测试报告框架", "cat": "报告编写",
            "steps": [
                "封面与摘要：范围、时间、总体结论、风险统计",
                "按风险等级列出漏洞：位置、复现步骤、影响、修复建议",
                "附录：测试范围、工具清单、免责声明",
                "用可复现的步骤与截图支撑每个发现",
            ],
            "exp": "复现步骤要能让工程师直接照做；修复建议要具体（配置/补丁/代码示例）",
            "pit": "报告避免夸大危害或漏报中高危；截图注意打码敏感信息",
        },
    ]
    seed = []
    for item in raw:
        item["version"] = 1
        item["updated"] = ts
        item["scope"] = "global"
        item.setdefault("exp", "")
        item.setdefault("pit", "")
        item["steps"] = [s for s in (item.get("steps") or []) if s]
        seed.append(item)
    return seed


def ensure_seeded():
    """全局技能库为空时写入内置种子（仅首次）"""
    if not storage.global_skills_file().exists():
        storage.write_json(storage.global_skills_file(), build_seed())


# ---------------------------------------------------------------
# 召回：中文分词 + BM25 风格打分（与前端知识库 RAG 同源思路）
# ---------------------------------------------------------------

def _tokenize(s):
    grams = []
    for w in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fa5]+", str(s).lower()):
        if re.fullmatch(r"[\u4e00-\u9fa5]+", w):
            if len(w) <= 4:
                grams.append(w)
            for i in range(len(w) - 1):
                grams.append(w[i:i + 2])
        else:
            grams.append(w)
    return grams


def _query_terms(s):
    return [g for g in _tokenize(s) if len(g) >= 2 and g not in _STOP]


def _score(text, q_set, df, n):
    grams = _tokenize(text)
    if not grams:
        return 0.0
    tf = {}
    for g in grams:
        tf[g] = tf.get(g, 0) + 1
    length = len(grams)
    k1, b, avg = 1.5, 0.75, 120.0
    total = 0.0
    for g in q_set:
        if g not in tf:
            continue
        f = df.get(g, 0)
        idf = math.log(1 + (n - f + 0.5) / (f + 0.5))
        total += idf * tf[g] * (k1 + 1) / (tf[g] + k1 * (1 - b + b * length / avg))
    return total


def recall_skills(pid, task, top_k=3):
    """合并全局+项目私有技能，按任务语义召回 top_k 条"""
    data = storage.load_skills(pid)
    items = list(data["global"]) + list(data["private"])
    q_terms = _query_terms(task)
    if not items:
        return []
    if not q_terms:
        return items[:top_k]  # 无有效检索词时取前 top_k 条兜底
    q_set = set(q_terms)
    n = len(items)
    df = {}
    for it in items:
        seen = set()
        for g in _tokenize(it.get("title", "") + " " + " ".join(it.get("steps") or []) + " " + (it.get("exp") or "") + " " + (it.get("pit") or "")):
            if g not in seen:
                seen.add(g)
                df[g] = df.get(g, 0) + 1
    hits = []
    for it in items:
        body = it.get("title", "") + "\n" + "\n".join(it.get("steps") or []) + "\n" + (it.get("exp") or "") + "\n" + (it.get("pit") or "")
        score = _score(body, q_set, df, n)
        if score <= 0:
            continue
        out = dict(it)
        out["score"] = round(score, 3)
        hits.append(out)
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:top_k]
