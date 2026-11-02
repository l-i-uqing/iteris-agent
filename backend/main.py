# -*- coding: utf-8 -*-
"""
main.py · FastAPI 服务入口
- 静态托管 web/（index.html + css/ + js/）
- /api/projects：项目 CRUD
- /api/data：项目会话数据读写（settings 全局共享，其余按项目隔离）
- /api/mcp/*：MCP 服务管理（stdio 子进程 / http SSE，真正由后端拉起进程）
- /api/proxy/llm：LLM 请求代理（API 密钥仅存后端，前端不再持有）
- /api/config：后端就绪状态查询
"""
import json
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from . import authz, config, playbook, prescan, skills, storage, vuln, workflow
from .mcp_manager import MCPManager

app = FastAPI(title="iteris-agent Backend", version="1.1")
mcp = MCPManager()
az = authz.AuthzService()

config.ensure_dirs()
config.ensure_config_file()
skills.ensure_seeded()


# =========================================================
# 项目 API
# =========================================================

@app.get("/api/projects")
async def api_projects_get():
    return JSONResponse({"projects": storage.load_projects()})


@app.post("/api/projects")
async def api_projects_post(body: dict):
    action = body.get("action")
    lst = storage.load_projects()
    if action == "create":
        name = str(body.get("name") or "").strip()
        if not name:
            return JSONResponse(status_code=400, content={"ok": False, "error": "项目名称不能为空"})
        import time

        proj = {
            "id": "p" + hex(int(time.time() * 1000))[2:][:8] + hex(id(body))[-4:],
            "name": name,
            "ts": int(time.time() * 1000),
        }
        lst.append(proj)
        storage.save_projects(lst)
        return JSONResponse({"ok": True, "project": {**proj, "fresh": True}})

    if action == "rename":
        proj = next((p for p in lst if p.get("id") == body.get("id")), None)
        if proj is None:
            return JSONResponse(status_code=404, content={"ok": False, "error": "项目不存在"})
        name = str(body.get("name") or "").strip()
        if not name:
            return JSONResponse(status_code=400, content={"ok": False, "error": "项目名称不能为空"})
        proj["name"] = name
        storage.save_projects(lst)
        return JSONResponse({"ok": True})

    if action == "delete":
        idx = next((i for i, p in enumerate(lst) if p.get("id") == body.get("id")), None)
        if idx is None:
            return JSONResponse(status_code=404, content={"ok": False, "error": "项目不存在"})
        pid = lst[idx]["id"]
        mcp.disconnect_all(pid)
        mcp._state.pop(pid, None)
        storage.delete_project_files(pid)
        lst.pop(idx)
        if not lst:
            lst.append({"id": "default", "name": "默认项目", "ts": 0})
        storage.save_projects(lst)
        return JSONResponse({"ok": True})

    return JSONResponse(status_code=400, content={"ok": False, "error": "未知操作"})


# =========================================================
# 数据 API（settings 全局，其余按项目隔离）
# =========================================================

def _pid(request: Request):
    q = request.query_params
    return q.get("projectId") or q.get("project") or "default"


@app.get("/api/data")
async def api_data_get(request: Request):
    data = storage.load_project_data(_pid(request))
    gkb = storage.load_global_kb()
    if gkb:
        # 合并全局知识（跨项目“记住”的内容），前端 RAG 自动召回
        data["kb"] = list(data.get("kb") or []) + gkb
    return JSONResponse(data)


@app.post("/api/data")
async def api_data_post(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "请求体不是合法 JSON"})
    storage.save_project_data(_pid(request), body)
    return JSONResponse({"ok": True})


@app.post("/api/kb")
async def api_kb_post(request: Request):
    """保存到全局知识库（跨项目共享的“记住”内容），前端 remember 工具调用"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "请求体不是合法 JSON"})
    content = str(body.get("content") or "").strip()
    if not content:
        return JSONResponse(status_code=400, content={"ok": False, "error": "内容不能为空"})
    title = str(body.get("title") or content[:24])
    ts = int(time.time() * 1000)
    items = storage.load_global_kb()
    items.append({
        "id": "kb" + str(ts),
        "title": title,
        "content": content,
        "ts": ts,
    })
    storage.save_global_kb(items)
    return JSONResponse({"ok": True, "count": len(items)})


# =========================================================
# MCP API（按项目隔离）
# =========================================================

@app.get("/api/mcp/state")
async def api_mcp_state(request: Request):
    return JSONResponse({"servers": mcp.state(_pid(request))})


@app.post("/api/mcp/connect")
async def api_mcp_connect(body: dict):
    pid = body.get("projectId") or body.get("project") or "default"
    result = await mcp.connect(
        pid,
        server_id=body.get("id"),
        new_cfg=body if not body.get("id") else None,
    )
    return JSONResponse(
        status_code=200 if result.get("ok") else 400,
        content=result,
    )


@app.post("/api/mcp/disconnect")
async def api_mcp_disconnect(body: dict):
    pid = body.get("projectId") or body.get("project") or "default"
    return JSONResponse(mcp.disconnect(pid, body.get("id")))


@app.post("/api/mcp/disconnectAll")
async def api_mcp_disconnect_all(body: dict):
    pid = body.get("projectId") or body.get("project") or "default"
    return JSONResponse(mcp.disconnect_all(pid))


@app.post("/api/mcp/remove")
async def api_mcp_remove(body: dict):
    pid = body.get("projectId") or body.get("project") or "default"
    return JSONResponse(mcp.remove(pid, body.get("id")))


@app.post("/api/mcp/call")
async def api_mcp_call(body: dict):
    pid = body.get("projectId") or body.get("project") or "default"
    result = await mcp.call(pid, body.get("id"), str(body.get("name") or ""), body.get("args") or {})
    return JSONResponse(status_code=200 if result.get("ok") else 400, content=result)


# =========================================================
# Skills API（全局库 data/skills.json + 项目私有 skills.json）
# =========================================================

@app.get("/api/skills")
async def api_skills_get(request: Request):
    return JSONResponse(storage.load_skills(_pid(request)))


@app.post("/api/skills/save")
async def api_skills_save(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "请求体不是合法 JSON"})
    pid = body.get("projectId") or body.get("project") or "default"
    storage.save_skills(pid, body.get("global"), body.get("private"))
    return JSONResponse({"ok": True})


@app.post("/api/skills/recall")
async def api_skills_recall(body: dict):
    pid = body.get("projectId") or body.get("project") or "default"
    task = str(body.get("task") or "")
    top_k = min(8, max(1, int(body.get("topK") or 3)))
    items = skills.recall_skills(pid, task, top_k)
    return JSONResponse({"ok": True, "skills": items})


@app.post("/api/skills/reset")
async def api_skills_reset(body: dict):
    pid = body.get("projectId") or body.get("project") or "default"
    scope = body.get("scope") or "global"
    if scope == "global":
        storage.save_skills(pid, skills.build_seed(), None)
    else:
        storage.save_skills(pid, None, [])
    return JSONResponse({"ok": True})


# =========================================================
# LLM 代理（API 密钥仅存后端）
# =========================================================

# =========================================================
# /api/playbook/*：预置攻击思路库（按目标检索注入解题先验）
# =========================================================

_pb = playbook.PlaybookService()


@app.post("/api/playbook/recall")
async def api_playbook_recall(body: dict):
    task = str(body.get("task") or "").strip()
    top_k = max(1, min(int(body.get("topK") or 3), 5))
    if not task:
        return JSONResponse(status_code=400, content={"ok": False, "error": "task 不能为空"})
    items = _pb.recall(task, top_k)
    return JSONResponse({"ok": True, "count": len(items), "items": items})


@app.get("/api/playbook/list")
async def api_playbook_list():
    return JSONResponse({"ok": True, "count": len(_pb.items), "items": _pb.items})


# =========================================================
# /api/prescan：初扫（指纹+CVE匹配+路径浅探测+漏洞类型覆盖，只判可能性）
# =========================================================

_prescan = prescan.PrescanService()


@app.post("/api/prescan")
async def api_prescan(body: dict):
    pid = _az_pid(body)
    target = str(body.get("target") or "").strip()
    if not target:
        return JSONResponse(status_code=400, content={"ok": False, "error": "target 不能为空"})
    # 授权检查（初扫同样受授权栅栏约束）
    chk = az.check(pid, target)
    if chk.get("hosts") and not chk.get("authorized"):
        return JSONResponse(status_code=403, content={
            "ok": False, "error": "授权拦截：目标 %s 不在当前项目授权白名单内" % (chk.get("first_unauthorized") or ""),
        })
    mode = str(body.get("mode") or "standard")
    if mode not in _prescan.MODES:
        mode = "standard"
    max_paths = max(5, min(int(body.get("maxPaths") or _prescan.MODES[mode]), 100))
    try:
        result = _prescan.prescan(target, max_paths=max_paths, mode=mode)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "初扫失败：" + str(e)})
    if not result.get("ok"):
        return JSONResponse(status_code=502, content=result)
    # 初扫结果自动沉淀进项目资产（PentAGI 借鉴：跨任务复用，避免重复扫描）
    try:
        assets = storage.merge_assets(pid, result)
        result["assets_count"] = len(assets)
        result["assets_saved"] = True
    except Exception as e:
        result["assets_saved"] = False
        result["assets_error"] = str(e)
    return JSONResponse(result)


@app.get("/api/prescan/config")
async def api_prescan_config():
    return JSONResponse({
        "ok": True,
        "cve_count": len(_prescan.data.get("cves") or []),
        "path_count": len(_prescan.data.get("paths") or []),
        "fingerprint_count": len(_prescan.data.get("fingerprints") or []),
    })


@app.get("/api/assets")
async def api_assets(projectId: str = ""):
    pid = projectId or "default"
    return JSONResponse({"ok": True, "assets": storage.load_assets(pid)})


@app.get("/api/playbook/detail")
async def api_playbook_detail(request: Request):
    iid = str(request.query_params.get("id") or "").strip()
    it = _pb.get(iid) if iid else None
    if not it:
        return JSONResponse(status_code=404, content={"ok": False, "error": "条目不存在"})
    return JSONResponse({"ok": True, "item": it})


@app.get("/api/config")
async def api_config():
    cfg = config.llm_config()
    return JSONResponse({
        "ok": True,
        "configured": bool(cfg["api_key"]),
        "baseUrl": cfg["base_url"],
        "model": cfg["model"],
    })


def _normalize_base(base):
    base = (base or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return base + "/chat/completions"


@app.post("/api/proxy/llm")
async def api_proxy_llm(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"message": "请求体不是合法 JSON"}})

    cfg = config.llm_config()
    if not cfg["api_key"]:
        return JSONResponse(status_code=400, content={
            "error": {"message": "后端未配置 API 密钥：请编辑 backend/config.json 或设置环境变量 LLM_API_KEY"}
        })

    url = _normalize_base(body.get("baseUrl") or cfg["base_url"])
    payload = {
        "model": body.get("model") or cfg["model"],
        "messages": body.get("messages") or [],
        "stream": bool(body.get("stream", False)),
        "temperature": body.get("temperature", 0.7),
    }
    if body.get("tools"):
        payload["tools"] = body["tools"]
    if body.get("tool_choice"):
        payload["tool_choice"] = body["tool_choice"]
    if body.get("response_format"):
        payload["response_format"] = body["response_format"]
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + cfg["api_key"],
    }

    if payload["stream"]:
        async def gen():
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("POST", url, headers=headers, json=payload) as resp:
                        if resp.status_code >= 400:
                            err = (await resp.aread()).decode("utf-8", "replace")
                            try:
                                j = json.loads(err)
                                msg = (j.get("error") or {}).get("message") or err[:300]
                            except Exception:
                                msg = err[:300]
                            yield "event: error\ndata: " + json.dumps({
                                "error": {"message": "HTTP " + str(resp.status_code) + " · " + msg}
                            }, ensure_ascii=False) + "\n\n"
                            yield "data: [DONE]\n\n"
                            return
                        async for chunk in resp.aiter_bytes():
                            yield chunk
            except Exception as e:
                yield "event: error\ndata: " + json.dumps({
                    "error": {"message": "后端代理异常：" + str(e)}
                }, ensure_ascii=False) + "\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            try:
                j = resp.json()
                msg = (j.get("error") or {}).get("message") or "HTTP " + str(resp.status_code)
            except Exception:
                msg = resp.text[:300] or "HTTP " + str(resp.status_code)
            return JSONResponse(status_code=resp.status_code, content={"error": {"message": msg}})
        return JSONResponse(resp.json())
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": {"message": "后端代理异常：" + str(e)}})


# =========================================================
# 经验记忆 API（四层经验：Episode / Gold / Pattern / ErrorFix）
# 读取侧：/api/memory/recall/pre（解题前注入）、/api/memory/recall/error（报错后注入）
# 写入侧：/api/memory/review（复盘入库，独立 LLM 调用）
# 统计：  /api/memory/stats（召回命中率）
# =========================================================

_memory_svc = None


def _memory():
    global _memory_svc
    if _memory_svc is None:
        from .memory.service import MemoryService
        _memory_svc = MemoryService(db_path=str(config.ROOT / "data" / "memory.db"),
                                    embed_backend="mock")
    return _memory_svc


def _llm_call_direct(messages, response_format=None) -> str:
    """复盘用 LLM 调用：直接请求上游（不经过本服务代理，避免自环）"""
    cfg = config.llm_config()
    if not cfg["api_key"]:
        raise RuntimeError("后端未配置 API 密钥（backend/config.json 或环境变量 LLM_API_KEY）")
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 4096,
    }
    if response_format:
        payload["response_format"] = response_format
    try:
        resp = httpx.post(_normalize_base(cfg["base_url"]), json=payload,
                          headers={"Content-Type": "application/json",
                                   "Authorization": "Bearer " + cfg["api_key"]},
                          timeout=180)
        if resp.status_code >= 400:
            raise RuntimeError("LLM HTTP " + str(resp.status_code) + "：" + resp.text[:200])
        j = resp.json()
        return (j.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError("LLM 调用失败：" + str(e))


@app.post("/api/memory/review")
async def api_memory_review(body: dict):
    """复盘入库：question/schema/attempts/gold_sql/user_note → 四层经验"""
    from .memory.review import ReviewService
    question = str(body.get("question") or "").strip()
    if not question:
        return JSONResponse(status_code=400, content={"ok": False, "error": "question 不能为空"})
    try:
        svc = ReviewService(memory=_memory(), llm_call=_llm_call_direct)
        res = svc.review(
            question,
            body.get("schema"),
            body.get("attempts") or [],
            str(body.get("gold_sql") or "").strip(),
            str(body.get("user_note") or "").strip(),
        )
        return JSONResponse({"ok": res.ok, "error": res.error,
                             "stored": res.stored, "pending": res.pending,
                             "validation": res.validation})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "复盘失败：" + str(e)})


@app.post("/api/memory/recall/pre")
async def api_memory_recall_pre(request: Request, body: dict):
    """解题前注入：提取考察点特征 → 检索 patterns/error_fixes → gold 同题精确匹配 → 先验提示"""
    from .memory.recall import RecallService
    question = str(body.get("question") or "").strip()
    if not question:
        return JSONResponse(status_code=400, content={"ok": False, "error": "question 不能为空"})
    pid = str(body.get("projectId") or _pid(request))
    ctx = RecallService(_memory()).pre_solve_inject(question, body.get("schema") or {}, project_id=pid)
    return JSONResponse({
        "ok": True,
        "prior_prompt": ctx["prior_prompt"],
        "patterns": [{"id": p["id"], "title": p.get("title", ""),
                      "human_verified": bool(p.get("human_verified")),
                      "success_count": p.get("success_count", 0)} for p in ctx["patterns"]],
        "error_fixes": [f["id"] for f in ctx["error_fixes"]],
        "graph_nodes": ctx.get("graph_nodes", []),
        "gold_hit": bool(ctx["gold_hit"] is not None),
        "gold_payload": ctx["gold_payload"],
        "features": ctx["features"],
    })


@app.post("/api/memory/recall/error")
async def api_memory_recall_error(body: dict):
    """报错后注入：用原始报错检索 error_fixes，命中返回修正提示"""
    from .memory.recall import RecallService
    error_text = str(body.get("error_text") or "").strip()
    if not error_text:
        return JSONResponse(status_code=400, content={"ok": False, "error": "error_text 不能为空"})
    pid = str(body.get("projectId") or "")
    ctx = RecallService(_memory()).error_fix_inject(error_text, project_id=pid)
    return JSONResponse({"ok": True, "fix_prompt": ctx["fix_prompt"],
                         "miss": ctx["miss"], "hits": [h["id"] for h in ctx["hits"]]})


@app.get("/api/memory/graph")
async def api_memory_graph():
    """漏洞知识图谱：全部节点（漏洞类型 ↔ 触发/利用/修复/CVE）"""
    try:
        nodes = [n.model_dump() for n in _memory().graph.list_nodes()]
        return JSONResponse({"ok": True, "count": len(nodes), "nodes": nodes})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "图谱读取失败：" + str(e)})


@app.post("/api/memory/graph/upsert")
async def api_memory_graph_upsert(body: dict):
    """人工新增/编辑图谱节点 {vuln_type, trigger, technique[], remediation, cve_id}"""
    try:
        node = _memory().graph.upsert(body)
        return JSONResponse({"ok": True, "node": node.model_dump()})
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.post("/api/memory/graph/delete")
async def api_memory_graph_delete(body: dict):
    try:
        ok = _memory().graph.delete(str(body.get("id") or ""))
        return JSONResponse({"ok": ok})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/api/memory/stats")
async def api_memory_stats(request: Request):
    """召回命中率统计（可按项目过滤）"""
    return JSONResponse({"ok": True, "stats": _memory().recall_stats(_pid(request))})


# =========================================================
# /api/vuln/*：漏洞情报检索（NVD CVE）
# 用途：Agent 核实漏洞编号 / CVSS 评级 / 受影响版本 / 公开参考，减少模型幻觉
# =========================================================


@app.post("/api/vuln/lookup")
async def api_vuln_lookup(body: dict):
    """CVE 查询：{query: CVE 编号或关键词/产品} → NVD 漏洞情报"""
    q = str(body.get("query") or "").strip()
    if not q:
        return JSONResponse(status_code=400, content={"ok": False, "error": "query 不能为空"})
    try:
        res = await vuln.lookup(q)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "漏洞情报查询失败：" + str(e)})
    return JSONResponse(res)


# =========================================================
# /api/authz/*：授权范围护栏（目标白名单校验，越权立即终止）
# 白名单按项目隔离；工具调用前统一校验，未授权目标直接拦截
# =========================================================


def _az_pid(body: dict) -> str:
    return str(body.get("projectId") or "default")


@app.get("/api/authz/list")
async def api_authz_list(request: Request):
    return JSONResponse({"ok": True, "items": az.list(_pid(request))})


@app.post("/api/authz/add")
async def api_authz_add(body: dict):
    res = az.add(_az_pid(body), str(body.get("target") or ""), str(body.get("note") or ""))
    if not res.get("ok"):
        return JSONResponse(status_code=400, content=res)
    return JSONResponse(res)


@app.post("/api/authz/remove")
async def api_authz_remove(body: dict):
    return JSONResponse({"ok": az.remove(_az_pid(body), str(body.get("id") or ""))})


@app.post("/api/authz/check")
async def api_authz_check(body: dict):
    """校验文本中所有目标是否授权：{projectId, text}"""
    res = az.check(_az_pid(body), str(body.get("text") or ""))
    return JSONResponse(res)


# =========================================================
# /api/http：进程内 HTTP 请求工具（Agent 的 curl 替代）
# 不走子进程（/api/shell 子进程访问部分内网目标会被拒），
# 由 FastAPI 进程内直接发起，复用授权护栏；支持 GET/POST 与自定义头
# =========================================================

@app.post("/api/http")
def api_http(body: dict):
    import urllib.request, urllib.parse
    pid = _az_pid(body)
    method = str(body.get("method") or "GET").upper()
    url = str(body.get("url") or "").strip()
    if not url:
        return JSONResponse(status_code=400, content={"ok": False, "error": "url 不能为空"})
    chk = az.check(pid, url)
    if chk.get("hosts") and not chk.get("authorized"):
        return JSONResponse(status_code=403, content={
            "ok": False, "error": "授权拦截：目标 %s 不在当前项目授权白名单内" % (chk.get("first_unauthorized") or ""),
        })
    headers = body.get("headers") or {}
    if not isinstance(headers, dict):
        headers = {}
    hdr = {}
    for k, v in headers.items():
        if k and v is not None:
            hdr[str(k)] = str(v)
    data_bytes = None
    if body.get("data") is not None:
        d = body["data"]
        if isinstance(d, dict):
            data_bytes = urllib.parse.urlencode(d).encode()
            hdr.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            data_bytes = str(d).encode()
    timeout = max(5, min(int(body.get("timeout") or 30), 120))
    req = urllib.request.Request(url, data=data_bytes, headers=hdr, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp_body = r.read().decode("utf-8", "replace")
            return JSONResponse({
                "ok": True,
                "status": r.status,
                "final_url": r.url,
                "headers": dict(r.headers),
                "body": resp_body[-20000:],
                "body_len": len(resp_body),
            })
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", "replace")
        except Exception:
            err_body = ""
        return JSONResponse({
            "ok": False,
            "status": e.code,
            "final_url": e.url,
            "headers": dict(e.headers) if e.headers else {},
            "body": err_body[-20000:],
            "body_len": len(err_body),
            "error": "HTTP %s" % e.code,
        })
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": "请求失败：" + str(e)})


# =========================================================
# /api/workflow/*：六阶段渗透流程引擎（侦察→扫描→枚举→利用→后渗透→报告）
# 显式工作流 + 断点恢复；按项目隔离（data/projects/<pid>/workflow.json）
# =========================================================

_wf = workflow.WorkflowService()


def _wf_pid(body: dict) -> str:
    return str(body.get("projectId") or "default")


@app.post("/api/workflow/start")
async def api_workflow_start(body: dict):
    """启动/恢复渗透流程：{projectId, target} → 已有则返回上次进度（断点恢复）"""
    pid = _wf_pid(body)
    wf = _wf.start(pid, str(body.get("target") or ""))
    return JSONResponse({"ok": True, "workflow": wf,
                         "progress": workflow.phase_progress_text(wf)})


@app.get("/api/workflow/state")
async def api_workflow_state(request: Request):
    pid = _pid(request)
    wf = _wf.get(pid)
    if wf is None:
        return JSONResponse({"ok": True, "active": False, "workflow": None})
    return JSONResponse({"ok": True, "active": wf.get("status") == "active",
                         "workflow": wf,
                         "progress": workflow.phase_progress_text(wf)})


@app.post("/api/workflow/advance")
async def api_workflow_advance(body: dict):
    """推进阶段：{projectId, phaseId, status(done|failed|skipped), note}"""
    pid = _wf_pid(body)
    try:
        wf = _wf.advance(pid, str(body.get("phaseId") or ""),
                         str(body.get("status") or ""),
                         str(body.get("note") or ""))
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    return JSONResponse({"ok": True, "workflow": wf,
                         "progress": workflow.phase_progress_text(wf)})


@app.post("/api/workflow/tool")
async def api_workflow_tool(body: dict):
    """记录工具调用到阶段：{projectId, phaseId?, tool, args, ok, summary}"""
    pid = _wf_pid(body)
    res = _wf.log_tool(pid, str(body.get("phaseId") or ""),
                       str(body.get("tool") or ""), str(body.get("args") or ""),
                       bool(body.get("ok")), str(body.get("summary") or ""))
    return JSONResponse(res)


@app.post("/api/workflow/abort")
async def api_workflow_abort(body: dict):
    """中断流程（保留断点）：{projectId}"""
    return JSONResponse(_wf.abort(_wf_pid(body)))


@app.post("/api/workflow/reset")
async def api_workflow_reset(body: dict):
    """清空流程：{projectId}"""
    return JSONResponse({"ok": _wf.reset(_wf_pid(body))})


# =========================================================
# /api/shell：系统命令执行（Agent 安装/调用命令行工具，如 sqlmap）
# 安全：危险命令黑名单拦截 + 超时限制；前端另有用户确认环节
# =========================================================

_DANGER_CMDS = [
    "rm -rf /", "rm -rf c:", "rd /s /q", "del /f /s /q", "format ",
    "shutdown", "reboot", "mkfs", "dd if=", "net user", "net localgroup",
    "reg delete", "reg add hklm", "sc delete", "taskkill /f /im svchost",
    "certutil -decode", "powershell -enc", "mshta", "bitsadmin /transfer",
    "curl -s http", "wget -q -o- | sh", "bash -c", "cmd /c del",
]


@app.post("/api/shell")
async def api_shell(body: dict):
    cmd = str(body.get("cmd") or "").strip()
    timeout = max(10, min(int(body.get("timeout") or 120), 600))
    if not cmd:
        return JSONResponse(status_code=400, content={"ok": False, "error": "命令不能为空"})
    _TMP = config.DATA_DIR / "tmp"
    try:
        _TMP.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    # 授权护栏（纵深防御）：命令中的 URL/IP/域名必须已授权（本地/环回豁免）
    chk = az.check(str(body.get("projectId") or "default"), cmd)
    if chk.get("hosts") and not chk.get("authorized"):
        bad = chk.get("first_unauthorized") or ""
        return JSONResponse(status_code=403, content={
            "ok": False, "error": "授权拦截：目标 %s 不在当前项目授权白名单内（可先添加授权再执行）" % bad,
            "authz": chk,
        })
    low = cmd.lower().replace("\\", "/")
    for d in _DANGER_CMDS:
        if d in low:
            return JSONResponse(status_code=400, content={"ok": False, "error": "命令被安全策略拦截：" + d})
    import asyncio
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(_TMP),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if proc.stdin:
            proc.stdin.close()  # EOF：交互式命令（如 sqlmap 的 Press Enter）不会卡住
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return JSONResponse(content={"ok": False, "error": "命令执行超时（%ss）" % timeout, "stdout": "", "stderr": "timeout"})
        return JSONResponse(content={
            "ok": True,
            "exit": proc.returncode,
            "stdout": out.decode("utf-8", "replace")[-8000:],
            "stderr": err.decode("utf-8", "replace")[-4000:],
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "命令执行失败：" + str(e)})


# =========================================================
# =========================================================
# /api/tmp/*：临时文件管理（data/tmp/，任务完成拿成果后可一键清理）
# =========================================================

@app.get("/api/tmp/list")
def api_tmp_list():
    TMP = config.DATA_DIR / "tmp"
    files = []
    if TMP.exists():
        for f in sorted(TMP.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.is_file():
                files.append({"name": f.name, "size": f.stat().st_size, "mtime": f.stat().st_mtime})
    return JSONResponse({"ok": True, "count": len(files), "files": files[:300]})


@app.post("/api/tmp/clean")
def api_tmp_clean(body: dict):
    TMP = config.DATA_DIR / "tmp"
    keep = str(body.get("keep") or "").strip()
    deleted = 0
    if TMP.exists():
        for f in TMP.iterdir():
            if f.is_file() and f.name != keep:
                try:
                    f.unlink()
                    deleted += 1
                except Exception:
                    pass
    return JSONResponse({"ok": True, "deleted": deleted, "tmp_dir": str(TMP)})


# 静态托管 web/
# =========================================================

_STATIC = {
    "/css/style.css": ("web/css/style.css", "text/css; charset=utf-8"),
    "/js/project-store.js": ("web/js/project-store.js", "text/javascript; charset=utf-8"),
    "/js/mcp-client.js": ("web/js/mcp-client.js", "text/javascript; charset=utf-8"),
    "/js/agent-core.js": ("web/js/agent-core.js", "text/javascript; charset=utf-8"),
    "/js/ui-render.js": ("web/js/ui-render.js", "text/javascript; charset=utf-8"),
}


@app.get("/")
@app.get("/index.html")
async def api_index():
    return FileResponse(config.WEB_DIR / "index.html", media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


@app.get("/{path:path}")
async def api_static(path: str):
    entry = _STATIC.get("/" + path)
    if entry is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "Not Found"})
    rel, mime = entry
    f = config.ROOT / rel
    if not f.exists():
        return JSONResponse(status_code=404, content={"ok": False, "error": "Not Found"})
    return FileResponse(f, media_type=mime, headers={"Cache-Control": "no-cache"})
