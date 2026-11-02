# -*- coding: utf-8 -*-
"""
features.py · 考察点特征提取（读取侧注入用）

从题目（question + schema）规则提取：
  vuln_type —— 漏洞类型（关键词命中）
  tables    —— 数据库表名（用于 gold 同题精确匹配）
  query_text—— 检索用文本（question + 类型 + 表名拼接）

预留：后续可换 LLM 提取（接口不变）。
"""
import re
from typing import Dict, List

VULN_KEYWORDS: Dict[str, List[str]] = {
    "sql_injection": ["sql", "注入", "injection", "union", "sqlmap", "数据库", "database", "查询", "query", "login", "登录", "表", "字段"],
    "command_injection": ["命令执行", "command injection", "系统命令", "shell", "rce", "命令注入", "ping", "ping 注入"],
    "path_traversal": ["目录穿越", "path traversal", "任意文件", "文件读取", "文件下载", "lfi", "rfi", "文件包含"],
    "ssrf": ["ssrf", "服务端请求伪造", "url 请求", "内网探测", "gopher", "file://"],
    "xss": ["xss", "跨站脚本", "script", "反射型", "存储型"],
    "auth_bypass": ["越权", "权限绕过", "auth bypass", "未授权", "弱口令", "登录绕过"],
    "deserialization": ["反序列化", "serialize", "deserialize", "php unserialize", "pickle"],
}

DEFAULT_VULN = "other"


def extract_table_names(schema) -> List[str]:
    """从 schema 提取表名（不包含列名）：dict 的 table/tables/table_names 键 + DDL 的 CREATE TABLE"""
    tables = set()
    if isinstance(schema, dict):
        for key in ("table", "tables", "table_names"):
            v = schema.get(key)
            if isinstance(v, str):
                tables.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", v))
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, str):
                        tables.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", x))
        for key in ("schema_sql", "sql", "ddl"):
            v = schema.get(key)
            if isinstance(v, str):
                for m in re.finditer(r"CREATE\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)", v, re.I):
                    tables.add(m.group(1))
    elif isinstance(schema, str):
        for m in re.finditer(r"CREATE\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)", schema, re.I):
            tables.add(m.group(1))
    return sorted(t for t in tables if t.lower() not in {"table", "tables"})


def detect_vuln_type(text: str) -> str:
    """关键词命中漏洞类型；多个命中取命中词最多的类型"""
    t = str(text or "").lower()
    best, best_hits = DEFAULT_VULN, 0
    for vtype, kws in VULN_KEYWORDS.items():
        hits = sum(1 for k in kws if k in t)
        if hits > best_hits:
            best, best_hits = vtype, hits
    return best


def extract_features(question: str, schema) -> dict:
    """提取考察点特征，用于检索与 gold 精确匹配"""
    vuln_type = detect_vuln_type(question)
    tables = extract_table_names(schema)
    parts = [str(question or "")]
    if vuln_type != DEFAULT_VULN:
        parts.append(vuln_type)
    if tables:
        parts.append(" ".join(tables))
    return {"vuln_type": vuln_type, "tables": tables, "query_text": " ".join(parts)}
