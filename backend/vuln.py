# -*- coding: utf-8 -*-
"""
vuln.py · 漏洞情报检索（CVE 查询）
- 数据源：NVD API 2.0（https://services.nvd.nist.gov/rest/json/cves/2.0）
- 支持：CVE 编号精确查询（如 CVE-2021-44228）与关键词/产品检索（如 log4j、nginx 1.18）
- 用途：Agent 在渗透测试中核实漏洞编号、评估 CVSS 危害等级、获取受影响版本与公开参考，减少模型幻觉
"""
import re

import httpx

NVD_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
TIMEOUT = 15.0
MAX_RESULTS = 5

_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)


def _pick_description(descs):
    """优先取英文描述，其次取第一条"""
    for d in descs or []:
        if d.get("lang") == "en":
            return (d.get("value") or "").strip()
    if descs:
        return (descs[0].get("value") or "").strip()
    return ""


def _cvss(metrics):
    """按 V31 > V30 > V2 顺序取评分"""
    for key in ("cvssMetricV31", "cvssMetricV30"):
        for m in metrics.get(key, []) or []:
            d = m.get("cvssData") or {}
            return {
                "version": d.get("version"),
                "score": d.get("baseScore"),
                "severity": d.get("baseSeverity"),
                "vector": d.get("vectorString"),
            }
    for m in metrics.get("cvssMetricV2", []) or []:
        return {
            "version": "2.0",
            "score": m.get("baseScore"),
            "severity": m.get("baseSeverity"),
            "vector": m.get("vectorString"),
        }
    return None


def _cpe_products(cve):
    """提取受影响的 CPE（仅 vulnerable=true 的匹配项），最多 8 条"""
    seen, out = set(), []
    for conf in cve.get("configurations") or []:
        for node in conf.get("nodes") or []:
            for m in node.get("cpeMatch") or []:
                if not m.get("vulnerable"):
                    continue
                c = m.get("criteria")
                if c and c not in seen:
                    seen.add(c)
                    out.append(c)
                if len(out) >= 8:
                    return out
    return out


def _references(cve):
    """公开参考链接，最多 5 条"""
    urls = []
    for r in cve.get("references") or []:
        u = (r.get("url") or "").strip()
        if u:
            urls.append(u)
        if len(urls) >= 5:
            break
    return urls


async def _query_nvd(params: dict) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(NVD_API, params=params)
        resp.raise_for_status()
        return resp.json()


async def lookup(query: str) -> dict:
    """
    统一入口：POST /api/vuln/lookup {query}
    返回 {ok, source:"NVD", query_type:"cve_id"|"keyword", total, results:[...]}
    """
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "query 不能为空"}

    if _CVE_RE.match(query):
        params = {"cveId": query.upper()}
        qtype = "cve_id"
    else:
        params = {"keywordSearch": query}
        qtype = "keyword"

    try:
        data = await _query_nvd(params)
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": "NVD 返回 HTTP %s（可能限流，请稍后重试）" % e.response.status_code, "source": "NVD"}
    except Exception as e:
        return {"ok": False, "error": "NVD 请求失败：" + str(e), "source": "NVD"}

    vulns = data.get("vulnerabilities") or []
    if not vulns:
        return {"ok": True, "source": "NVD", "query_type": qtype, "total": 0, "results": []}

    results = []
    for v in vulns[:MAX_RESULTS]:
        c = v.get("cve") or {}
        desc = _pick_description(c.get("descriptions"))
        results.append({
            "id": c.get("id"),
            "published": (c.get("published") or "")[:10],
            "lastModified": (c.get("lastModified") or "")[:10],
            "description": desc[:600],
            "cvss": _cvss(c.get("metrics") or {}),
            "cpes": _cpe_products(c),
            "references": _references(c),
        })
    return {
        "ok": True,
        "source": "NVD",
        "query_type": qtype,
        "total": data.get("totalResults", len(results)),
        "results": results,
    }
