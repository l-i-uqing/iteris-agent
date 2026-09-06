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
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from . import config, skills, storage
from .mcp_manager import MCPManager

app = FastAPI(title="iteris-agent Backend", version="1.1")
mcp = MCPManager()

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
    return JSONResponse(storage.load_project_data(_pid(request)))


@app.post("/api/data")
async def api_data_post(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "请求体不是合法 JSON"})
    storage.save_project_data(_pid(request), body)
    return JSONResponse({"ok": True})


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
                            yield "data: " + json.dumps({
                                "choices": [{"delta": {"content": "【后端代理错误】" + msg}}]
                            }, ensure_ascii=False) + "\n\n"
                            yield "data: [DONE]\n\n"
                            return
                        async for chunk in resp.aiter_bytes():
                            yield chunk
            except Exception as e:
                yield "data: " + json.dumps({
                    "choices": [{"delta": {"content": "【后端代理异常】" + str(e)}}]
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
    return FileResponse(config.WEB_DIR / "index.html", media_type="text/html; charset=utf-8")


@app.get("/{path:path}")
async def api_static(path: str):
    entry = _STATIC.get("/" + path)
    if entry is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "Not Found"})
    rel, mime = entry
    f = config.ROOT / rel
    if not f.exists():
        return JSONResponse(status_code=404, content={"ok": False, "error": "Not Found"})
    return FileResponse(f, media_type=mime)
