# -*- coding: utf-8 -*-
"""
authz.py · 授权范围护栏（目标白名单校验，越权立即终止）

合规定位：Agent 只允许对「当前项目已授权」的目标执行渗透操作。
  - 白名单按项目隔离：data/projects/<pid>/authz.json（default 项目在 data/authz.json）；
  - 规则支持：精确域名（含子域）、通配子域（*.example.com）、IP、CIDR（10.0.0.0/8）、完整 URL；
  - 校验入口：
      1) 前端 Agent 工具调用前（execTool 统一闸口）；
      2) 后端 /api/shell 二次校验（纵深防御，命令含未授权目标直接 400 拦截）；
      3) Agent 工具 authz_check / authz_add（添加必须经用户确认）。
  - 白名单为空时默认拦截一切外部目标（安全优先），提示用户先添加授权。
"""
import ipaddress
import json
import re
import time
from typing import List, Optional, Tuple

from . import config, storage

_URL_RE = re.compile(r"https?://([^/\s\"'<>\\]+)", re.I)
_IP_RE = re.compile(r"\b((?:\d{1,3}\.){3}\d{1,3})\b")
_DOMAIN_RE = re.compile(r"\b([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+)\b", re.I)

# 本地/环回等无风险主机：不拦截
_SAFE_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

# 常见文件扩展名：路径中的 check.php / index.html 不是主机，排除
_KNOWN_EXTS = {
    "php","html","htm","js","css","png","jpg","jpeg","gif","ico","svg","webp","bmp",
    "json","xml","txt","zip","rar","7z","gz","tar","pdf","doc","docx","xls","xlsx",
    "csv","map","env","log","md","yml","yaml","toml","ini","cfg","conf","sql","db",
    "aspx","asp","jsp","do","action","cgi","pl","py","sh","bat","ps1",
}
# 常见顶级域：用于判定“裸域名”（文本中未带协议的主机名）
_COMMON_TLDS = {
    "com","net","org","io","cn","edu","gov","mil","info","me","cc","tv","xyz","top",
    "tech","cloud","app","dev","ai","ru","de","jp","uk","co","biz","online","site",
    "fun","club","shop","store","live","pro","link","world","asia","mobi","name",
    "tel","int","jobs","icu","vip","red","space","host","website","wiki","social",
    "wang","xin","ltd","center","digital","media","network","solutions","moe","id",
}


def authz_file(pid: str):
    return storage.project_dir(pid) / "authz.json"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except Exception:
        return False


def extract_hosts(text: str) -> List[str]:
    """从文本中提取候选目标（去重）：URL 主机 / 裸 IP / 域名"""
    out, seen = [], set()
    for m in _URL_RE.finditer(text or ""):
        host = m.group(1).split("/")[0].split(":")[0].lower().strip(".")
        if host and host not in seen:
            seen.add(host)
            out.append(host)
    for m in _IP_RE.finditer(text or ""):
        ip = m.group(1)
        parts = ip.split(".")
        if all(0 <= int(x) <= 255 for x in parts) and ip not in seen:
            seen.add(ip)
            out.append(ip)
    for m in _DOMAIN_RE.finditer(text or ""):
        d = m.group(1).lower().strip(".")
        if d not in seen and not _is_ip(d):
            tld = d.rsplit(".", 1)[-1]
            if tld in _KNOWN_EXTS or tld not in _COMMON_TLDS:
                continue  # 路径文件（check.php）或非标准 TLD 的裸主机，不作为目标
            seen.add(d)
            out.append(d)
    return out


def _host_matches_rule(host: str, rule_target: str) -> bool:
    """域名/URL 规则匹配：自身或子域（rule=example.com 匹配 example.com 与 a.example.com）"""
    host = host.lower().rstrip(".")
    rule = rule_target.lower().rstrip(".")
    # URL 规则剥离协议与路径，仅取主机部分
    if "://" in rule:
        rule = rule.split("://", 1)[1]
    rule = rule.split("/")[0].split(":")[0].rstrip(".")
    if not rule:
        return False
    if rule.startswith("*."):
        base = rule[2:]
        return host.endswith("." + base)
    return host == rule or host.endswith("." + rule)


def _ip_matches_rule(ip: str, rule_target: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        if "/" in rule_target:
            net = ipaddress.ip_network(rule_target, strict=False)
            return addr in net
        return ip == rule_target
    except Exception:
        return False


def _rule_type(target: str) -> str:
    t = (target or "").strip()
    if "/" in t and _is_ip(t.split("/")[0]):
        return "cidr"
    if _is_ip(t):
        return "ip"
    if t.startswith("*.") or t.startswith("."):
        return "wildcard"
    if t.startswith(("http://", "https://")):
        return "url"
    if re.match(r"^[a-z0-9.\-]+$", t, re.I):
        return "host"
    return "unknown"


class AuthzService:
    def __init__(self):
        pass

    # ---------- 管理 ----------

    def list(self, pid: str) -> List[dict]:
        items = storage.read_json(authz_file(pid), None)
        return items if isinstance(items, list) else []

    def add(self, pid: str, target: str, note: str = "") -> dict:
        target = (target or "").strip()
        if not target:
            return {"ok": False, "error": "目标不能为空"}
        ttype = _rule_type(target)
        if ttype == "unknown":
            return {"ok": False, "error": "无法识别的目标格式（支持域名/IP/CIDR/URL/通配符 *.example.com）"}
        items = self.list(pid)
        norm = target.lower().rstrip(".")
        for it in items:
            if it.get("target", "").lower().rstrip(".") == norm:
                return {"ok": False, "error": "该目标已在授权列表中"}
        item = {
            "id": "az_" + str(_now_ms()),
            "target": target,
            "type": ttype,
            "note": (note or "").strip(),
            "ts": _now_ms(),
        }
        items.append(item)
        storage.write_json(authz_file(pid), items)
        return {"ok": True, "item": item, "count": len(items)}

    def remove(self, pid: str, item_id: str) -> bool:
        items = self.list(pid)
        kept = [it for it in items if it.get("id") != item_id]
        if len(kept) == len(items):
            return False
        storage.write_json(authz_file(pid), kept)
        return True

    # ---------- 校验 ----------

    def is_host_authorized(self, pid: str, host: str) -> bool:
        # 总开关：白名单功能关闭时全部放行
        if not config.AUTHZ_ENABLED:
            return True
        if host in _SAFE_HOSTS:
            return True
        rules = self.list(pid)
        if not rules:
            return False  # 白名单为空 → 默认拦截
        if _is_ip(host):
            return any(
                _ip_matches_rule(host, r.get("target", ""))
                for r in rules if r.get("type") in ("ip", "cidr")
            )
        return any(
            _host_matches_rule(host, r.get("target", ""))
            for r in rules if r.get("type") in ("host", "wildcard", "url")
        )

    def check(self, pid: str, text: str) -> dict:
        """校验文本中的所有目标 → {ok, authorized, hosts:[{host, ok}], first_unauthorized}"""
        hosts = extract_hosts(text or "")
        if not hosts:
            return {"ok": True, "authorized": True, "hosts": [], "first_unauthorized": ""}
        results = []
        first_bad = ""
        for h in hosts:
            ok = self.is_host_authorized(pid, h)
            results.append({"host": h, "ok": ok})
            if not ok and not first_bad:
                first_bad = h
        return {
            "ok": True,
            "authorized": not first_bad,
            "hosts": results,
            "first_unauthorized": first_bad,
        }
