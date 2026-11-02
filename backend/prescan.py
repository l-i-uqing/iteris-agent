# -*- coding: utf-8 -*-
"""
prescan.py · 初扫服务
输入 IP/网址 → 结构化初扫报告（只判可能性，不深入利用）：
  1. 漏洞类型覆盖清单（尝试了哪些漏洞类型，每类：探测点/迹象/判定）
  2. CVE 匹配（指纹 → 符合类型的 CVE 列表）
  3. 接口点/功能点排查（路径 → 状态 → 特征 → 可能漏洞类型）
  4. 结论（可能的漏洞面 + 建议深入项）
"""
import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CVE_FILE = Path(__file__).resolve().parent.parent / "data" / "prescan_cve.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


class PrescanService:
    def __init__(self, path=None):
        self.path = Path(path) if path else CVE_FILE
        self.data = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f) or {}
        except Exception:
            self.data = {}

    def _get(self, url, timeout=8):
        """进程内 HTTP 获取，返回 (ok, status, headers, body)"""
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(200000).decode("utf-8", "replace")
                return True, r.status, dict(r.headers), body
        except urllib.error.HTTPError as e:
            try:
                body = e.read(60000).decode("utf-8", "replace")
            except Exception:
                body = ""
            return True, e.code, dict(e.headers) if e.headers else {}, body
        except Exception:
            return False, 0, {}, ""

    def _request(self, method, url, data=None, timeout=8):
        """GET/POST（表单编码）请求，返回 (ok, status, headers, body)"""
        import urllib.request, urllib.parse
        headers = {"User-Agent": UA}
        payload = None
        if method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            payload = urllib.parse.urlencode(data).encode() if data else b""
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(200000).decode("utf-8", "replace")
                return True, r.status, dict(r.headers), body
        except urllib.error.HTTPError as e:
            try:
                body = e.read(60000).decode("utf-8", "replace")
            except Exception:
                body = ""
            return True, e.code, dict(e.headers) if e.headers else {}, body
        except Exception:
            return False, 0, {}, ""

    def _normalize_target(self, target):
        t = (target or "").strip()
        if not t:
            return None
        if not t.startswith("http://") and not t.startswith("https://"):
            t = "http://" + t
        t = t.rstrip("/")
        return t

    def _fingerprint(self, headers, body):
        """指纹识别：返回命中的组件列表"""
        hit = []
        text = str(body) + "\n" + " ".join("%s: %s" % (k, v) for k, v in (headers or {}).items())
        for fp in (self.data.get("fingerprints") or []):
            ok = False
            for pat in (fp.get("patterns") or []):
                if pat.get("type") == "body" and pat.get("match", "").lower() in text.lower():
                    ok = True
                elif pat.get("type") == "header":
                    # header 匹配：形如 "Server: nginx"
                    h = pat.get("match", "").lower()
                    if h in text.lower():
                        ok = True
            if ok:
                hit.append(fp["component"])
        return hit

    def _match_cves(self, components):
        """组件 → CVE 匹配"""
        out = []
        seen = set()
        for c in components:
            for cve in (self.data.get("cves") or []):
                if cve.get("component") == c and cve.get("cve") not in seen:
                    seen.add(cve.get("cve"))
                    out.append(dict(cve))
        return out

    def _probe_path(self, base, path, timeout=6):
        """浅探测单个路径：状态/标题/特征"""
        url = base + path
        ok, status, headers, body = self._get(url, timeout=timeout)
        if not ok:
            return {"path": path, "status": None, "reachable": False, "title": "", "features": [], "types": []}
        features = []
        m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
        title = (m.group(1).strip()[:80] if m else "")
        # 特征嗅探仅对 2xx/3xx（status<400）执行：404/5xx 不可达，不算迹象
        low = body.lower() if (status or 0) < 400 else ""
        sniffs = [
            ("phpinfo", "phpinfo()"),
            ("swagger", "swagger"),
            ("druid", "druid"),
            ("actuator", "actuator|whitelabel"),
            ("login", "<form"),
            ("json-api", r"^\s*\{"),
            ("thinkphp", "thinkphp"),
            ("wordpress", "wp-content"),
            ("sourcemap", "sourceMappingURL|.js.map"),
            ("webpack", "webpackJsonp|__webpack_require__"),
            ("vue", "vue.runtime|new Vue|createApp"),
            ("minio", "minio"),
            ("ollama", "ollama"),
            ("jwt", r"eyJ[A-Za-z0-9_-]{8,}\."),
            ("appid", r'appid\s*[=:"]|appsecret\s*[=:"]|access[_-]?key\s*[=:]'),
            ("aksk", "AKIA[0-9A-Z]{16}|LTAI[0-9A-Za-z]{12,}|AccessKeyId"),
            ("k8s", "kube-system|kubernetes"),
        ]
        for name, pat in sniffs:
            if re.search(pat, low):
                features.append(name)
        # 路径对应的漏洞类型（从字典取）
        types = []
        for p in (self.data.get("paths") or []):
            if p.get("path") == path:
                types = list(p.get("types") or [])
                break
        evidence = ""
        if (status or 0) < 400:
            evidence = "HTTP %s" % status
            if title: evidence += " · 标题:%s" % title[:40]
            if features: evidence += " · 特征:" + ",".join(features[:5])
        return {
            "path": path, "status": status, "reachable": True,
            "title": title, "features": features, "types": types,
            "evidence": evidence,
            "note": next((p.get("note", "") for p in (self.data.get("paths") or []) if p.get("path") == path), ""),
        }

    def _probe_endpoint(self, base, ep, timeout=6):
        """功能点浅探测：按探针类型对接口参数发温和探测（只判可能性，不深入利用）"""
        path = ep.get("path", "")
        method = (ep.get("method") or "GET").upper()
        probe = ep.get("probe") or "plain"
        ps = ep.get("params") or []
        # 构造探针参数值
        vals = {}
        for p in ps:
            n = p["name"]
            if probe == "sqli":
                vals[n] = "1'"
            elif probe == "xss":
                vals[n] = "<script>alert(1)</script>"
            elif probe == "ssrf":
                vals[n] = "http://127.0.0.1/"
            elif probe == "traversal":
                vals[n] = "../../../../etc/passwd"
            elif probe == "auth":
                vals[n] = "admin" if n.lower() in ("username", "user", "account", "email", "login") else "admin"
            elif probe == "id":
                vals[n] = "1"
            else:
                vals[n] = "1" if p.get("type") in ("int", "float") else "test"
        url = base + path
        try:
            if method == "POST":
                ok, status, headers, body = self._request("POST", url, vals, timeout)
            else:
                import urllib.parse
                qs = urllib.parse.urlencode(vals)
                ok, status, headers, body = self._request("GET", url + ("?" + qs if qs else ""), None, timeout)
        except Exception:
            return {"path": path, "method": method, "params": [p["name"] for p in ps],
                    "types": ep.get("types", []), "status": None, "verdict": "探测失败",
                    "evidence": "请求异常", "note": ep.get("note", "")}
        if not ok:
            return {"path": path, "method": method, "params": [p["name"] for p in ps],
                    "types": ep.get("types", []), "status": None, "verdict": "不可达",
                    "evidence": "", "note": ep.get("note", "")}
        low = (body or "").lower()
        verdict, ev = "未见迹象", ""
        # 探针特征检测
        if (status or 0) < 400:
            if probe == "sqli":
                pats = ["sql syntax", "mysql", "sqlite", "postgres", "you have an error",
                        "warning: mysql", "ora-[0-9]", "jdbc", "sqlstate", "pdoexception"]
                hit = next((p for p in pats if re.search(p, low)), None)
                if hit:
                    verdict = "有迹象"
                    ev = "HTTP %s · 探针:' 触发SQL报错特征(%s)" % (status, hit)
                else:
                    verdict = "待验证"
                    ev = "HTTP %s · 接口可达，注入点需人工验证" % status
            elif probe == "xss":
                if "<script>alert(1)" in low:
                    verdict = "有迹象"
                    ev = "HTTP %s · 探针被原样反射（存储/反射型XSS可能）" % status
                else:
                    verdict = "待验证"
                    ev = "HTTP %s · 接口可达，XSS点需人工验证" % status
            elif probe == "traversal":
                if "root:" in low or "/bin/bash" in low or "/etc/passwd" in low:
                    verdict = "有迹象"
                    ev = "HTTP %s · 路径穿越探针读到文件内容特征" % status
                else:
                    verdict = "待验证"
                    ev = "HTTP %s · 下载接口可达，穿越需人工验证" % status
            elif probe == "ssrf":
                verdict = "待验证"
                ev = "HTTP %s · URL参数存在，SSRF需人工验证（本扫描不回连探测）" % status
            elif probe == "auth":
                if re.search(r"welcome|success|登录成功|dashboard|logout|退出登录", low):
                    verdict = "有迹象"
                    ev = "HTTP %s · admin/admin 弱口令组合疑似可登录" % status
                else:
                    verdict = "待验证"
                    ev = "HTTP %s · 登录接口可达，弱口令/绕过需人工验证" % status
            elif probe == "id":
                verdict = "待验证"
                ev = "HTTP %s · 对象ID参数存在，越权遍历需人工验证" % status
            else:  # plain
                if re.search(r"captcha|验证码|图形码", low):
                    verdict = "待验证"
                    ev = "HTTP %s · 接口含验证码校验，绕过需人工验证" % status
                elif re.search(r"频繁|太多次|稍后再试|try again later|limit|超时|频次", low):
                    verdict = "有迹象"
                    ev = "HTTP %s · 接口无频控/频控缺失（轰炸可能）" % status
                else:
                    verdict = "待验证"
                    ev = "HTTP %s · 功能点可达，参数存在，逻辑需人工验证" % status
        else:
            ev = "HTTP %s · 不可达/拒绝" % status
        return {"path": path, "method": method, "params": [p["name"] for p in ps],
                "types": ep.get("types", []), "status": status, "verdict": verdict,
                "evidence": ev, "note": ep.get("note", "")}

    MODES = {"quick": 20, "standard": 60, "deep": 100}

    def prescan(self, target, max_paths=40, timeout=8, mode="standard"):
        base = self._normalize_target(target)
        if not base:
            return {"ok": False, "error": "目标格式无效"}
        # 扫描档位：quick=浅(20路径) standard=标准(60) deep=深(100)；显式 max_paths 优先
        if mode in self.MODES and not (isinstance(max_paths, int) and max_paths != 40):
            max_paths = self.MODES[mode]

        # 1) 首页指纹
        ok, status, headers, body = self._get(base, timeout=timeout)
        if not ok:
            return {"ok": False, "error": "目标不可达", "target": base}
        components = self._fingerprint(headers, body)
        title_m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
        site = {
            "target": base, "status": status,
            "server": headers.get("Server", ""),
            "powered_by": headers.get("X-Powered-By", ""),
            "title": (title_m.group(1).strip()[:80] if title_m else ""),
            "components": components,
            "cookies": [c.split("=")[0] for c in headers.get("Set-Cookie", "").split(";") if "=" in c][:5],
        }

        # 2) CVE 匹配
        cves = self._match_cves(components)

        # 3) 路径浅探测（线程池）
        # 按漏洞类型轮询均衡取样：保证每种类型（含 Top10/逻辑漏洞）至少进入探测列表，
        # 再按原顺序补齐到 max_paths，避免新类型排在末尾而扫描不到
        from collections import defaultdict
        by_type = defaultdict(list)
        for p in (self.data.get("paths") or []):
            for t in (p.get("types") or []):
                by_type[t].append(p)
        selected, seen = [], set()
        for i in range(20):
            for t, plist in by_type.items():
                if len(selected) >= max_paths:
                    break
                if i < len(plist) and plist[i]["path"] not in seen:
                    seen.add(plist[i]["path"])
                    selected.append(plist[i])
            if len(selected) >= max_paths:
                break
        for p in (self.data.get("paths") or []):
            if len(selected) >= max_paths:
                break
            if p["path"] not in seen:
                seen.add(p["path"])
                selected.append(p)
        paths = selected[:max_paths]
        probed = []
        with ThreadPoolExecutor(max_workers=6) as ex:
            for r in ex.map(lambda p: self._probe_path(base, p, timeout), [p["path"] for p in paths]):
                probed.append(r)
        reachable = [r for r in probed if r.get("reachable")]

        # 3.5) 功能点/参数浅探测（并发，温和探针）
        eps = (self.data.get("endpoints") or [])
        ep_results = []
        if eps:
            with ThreadPoolExecutor(max_workers=6) as ex2:
                for r2 in ex2.map(lambda ep: self._probe_endpoint(base, ep, timeout), eps):
                    ep_results.append(r2)

        # 4) 漏洞类型覆盖统计（探测点=全部可达含404；迹象=仅 status<400 或有特征命中）
        vuln_summary = []
        type_map = {}          # 类型 -> 全部可达探测点
        signal_map = {}        # 类型 -> 有迹象路径（status<400 或特征命中）
        for r in reachable:
            for t in (r.get("types") or []):
                type_map.setdefault(t, []).append(r["path"])
                # 迹象仅算 2xx/3xx（status<400）；404/5xx 只计为探测点
                if (r.get("status") or 0) < 400:
                    signal_map.setdefault(t, []).append(r["path"])
        for vt in (self.data.get("vuln_types") or []):
            t = vt["type"]
            hits = type_map.get(t, [])
            signals = signal_map.get(t, [])
            cve_hits = [c for c in cves if c.get("type") == t]
            if hits or cve_hits:
                # 该类型首个有迹象路径的证据
                ev = next((r.get("evidence", "") for r in reachable
                           if r["path"] in signals and r.get("evidence")), "")
                vuln_summary.append({
                    "type": t,
                    "probe_points": len(hits),
                    "paths": signals[:8],
                    "evidence": ev,
                    "cve_hits": [c["cve"] for c in cve_hits],
                    "owasp": vt.get("owasp", ""),
                    "verdict": "⚠️ 有迹象" if (signals or cve_hits) else "未见明显迹象",
                    "desc": vt.get("desc", ""),
                })

        # 5) 结论：可能漏洞面（仅 status<400 或特征命中，带证据链）
        suspects = []
        for r in reachable:
            if r.get("types") and (r.get("status") or 0) < 400:
                suspects.append({
                    "path": r["path"], "status": r["status"],
                    "types": r.get("types", []), "title": r.get("title", ""),
                    "evidence": r.get("evidence", ""), "note": r.get("note", ""),
                })
        verdict = "存在潜在风险面" if (suspects or cves) else "未发现明显风险面"

        # 功能点命中聚合（按漏洞类型）
        ep_by_type = {}
        for r2 in ep_results:
            for t in (r2.get("types") or []):
                ep_by_type.setdefault(t, []).append(r2)
        ep_summary = []
        for vt in (self.data.get("vuln_types") or []):
            t = vt["type"]
            hits = ep_by_type.get(t, [])
            if hits:
                signals = [h for h in hits if h.get("verdict") in ("有迹象", "待验证")]
                ep_summary.append({
                    "type": t,
                    "count": len(hits),
                    "signal_count": len(signals),
                    "endpoints": sorted({h["path"] for h in signals})[:8],
                    "owasp": vt.get("owasp", ""),
                    "verdict": "⚠️ 有迹象" if any(h.get("verdict") == "有迹象" for h in hits) else
                               ("待验证" if signals else "未见迹象"),
                })

        return {
            "ok": True,
            "mode": mode,
            "site": site,
            "cves": cves,
            "vuln_types": vuln_summary,
            "reachable_paths": reachable,
            "suspects": suspects,
            "endpoints": ep_results,
            "endpoint_summary": ep_summary,
            "verdict": verdict,
            "note": "初扫仅做可能性判断，未深入利用；功能点参数探测为温和探针（引号/无害值），如需深入请让 Agent 针对标 ⚠️ 项做验证。",
        }
