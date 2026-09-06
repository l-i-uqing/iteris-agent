# -*- coding: utf-8 -*-
"""
mcp_manager.py · MCP（Model Context Protocol）服务管理
- stdio 传输：asyncio 子进程 + JSON-RPC over stdin/stdout（换行帧），初始化→tools/list→tools/call
- http 传输：Streamable HTTP（POST JSON / SSE 响应，Mcp-Session-Id 会话跟踪）
- 按项目隔离：每个项目的服务配置与连接状态独立（data/projects/<pid>/mcp.json）
"""
import asyncio
import json
import os
import shlex
import time

from . import config
from .storage import project_dir, read_json, write_json

TIMEOUT = 30  # 单次 MCP 请求超时（秒）


def _gen_id(prefix):
    return prefix + hex(int(time.time() * 1000))[2:] + os.urandom(3).hex()


class MCPManager:
    def __init__(self):
        self._state = {}  # pid -> [server dicts]

    # ---------------- 配置持久化 ----------------

    def _config_file(self, pid):
        return project_dir(pid) / "mcp.json"

    def _load_config(self, pid):
        servers = read_json(self._config_file(pid), [])
        for s in servers:
            s.setdefault("status", "offline")
            s.setdefault("tools", [])
            s["error"] = ""
            s["proc"] = None
            s["session"] = None
            s["next_id"] = 1
            s["pending"] = {}
            s["last_err"] = ""
        self._state[pid] = servers
        return servers

    def _save_config(self, pid):
        cfg = []
        for s in self._state.get(pid, []):
            cfg.append({
                "id": s.get("id"),
                "name": s.get("name"),
                "transport": s.get("transport"),
                "command": s.get("command"),
                "args": s.get("args", []),
                "url": s.get("url"),
                "headers": s.get("headers", {}),
            })
        write_json(self._config_file(pid), cfg)

    def _list(self, pid):
        if pid not in self._state:
            self._load_config(pid)
        return self._state[pid]

    @staticmethod
    def _pub(s):
        return {
            "id": s.get("id"),
            "name": s.get("name"),
            "transport": s.get("transport"),
            "command": s.get("command"),
            "args": s.get("args", []),
            "url": s.get("url"),
            "headers": s.get("headers", {}),
            "status": s.get("status"),
            "error": s.get("error", ""),
            "tools": s.get("tools", []),
        }

    # ---------------- stdio 传输 ----------------

    async def _stdio_read_loop(self, srv):
        """后台任务：逐行读取子进程 stdout，分发 JSON-RPC 响应"""
        buf = ""
        try:
            while True:
                chunk = await srv["proc"].stdout.read(4096)
                if not chunk:
                    break
                buf += chunk.decode("utf-8", "replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except Exception:
                        continue
                    sid = msg.get("id")
                    if sid is not None and sid in srv.get("pending", {}):
                        fut = srv["pending"].pop(sid)
                        if not fut.done():
                            if msg.get("error"):
                                err = msg["error"].get("message") or "MCP 错误"
                                fut.set_exception(RuntimeError(err))
                            else:
                                fut.set_result(msg.get("result"))
        except Exception:
            pass
        finally:
            srv["proc"] = None
            for sid, fut in list(srv.get("pending", {}).items()):
                if not fut.done():
                    fut.set_exception(RuntimeError("MCP 进程已退出"))
            srv["pending"] = {}
            if srv.get("status") in ("connected", "connecting"):
                srv["status"] = "error"
                srv["error"] = "MCP 进程已退出（" + (srv.get("last_err") or "") + "）"

    async def _stdio_send(self, srv, method, params):
        sid = srv["next_id"]
        srv["next_id"] += 1
        fut = asyncio.get_event_loop().create_future()
        srv.setdefault("pending", {})[sid] = fut
        try:
            line = json.dumps(
                {"jsonrpc": "2.0", "id": sid, "method": method, "params": params}
            ) + "\n"
            srv["proc"].stdin.write(line.encode("utf-8"))
            await srv["proc"].stdin.drain()
            return await asyncio.wait_for(fut, TIMEOUT)
        except asyncio.TimeoutError:
            srv["pending"].pop(sid, None)
            raise RuntimeError("MCP 请求超时：" + method)
        except Exception as e:
            srv["pending"].pop(sid, None)
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError("MCP 传输失败：" + str(e))

    async def _connect_stdio(self, srv):
        srv["status"] = "connecting"
        cmd = (srv.get("command") or "").strip()
        args = srv.get("args") or []
        if isinstance(args, str):
            args = shlex.split(args)
        if not cmd:
            srv["status"] = "error"
            srv["error"] = "缺少启动命令"
            return {"ok": False, "error": srv["error"]}

        cmdline = cmd
        if args:
            cmdline += " " + " ".join(shlex.quote(str(a)) for a in args)

        try:
            if os.name == "nt":
                proc = await asyncio.create_subprocess_shell(
                    cmdline,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *shlex.split(cmdline),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
        except Exception as e:
            srv["status"] = "error"
            srv["error"] = "无法启动进程：" + str(e)
            return {"ok": False, "error": srv["error"]}

        srv["proc"] = proc
        srv["pending"] = {}

        async def _drain_stderr():
            try:
                while True:
                    d = await proc.stderr.read(512)
                    if not d:
                        break
                    srv["last_err"] = d.decode("utf-8", "replace")[-400:]
            except Exception:
                pass

        asyncio.create_task(self._stdio_read_loop(srv))
        asyncio.create_task(_drain_stderr())

        try:
            await self._stdio_send(srv, "initialize", {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "iteris-agent", "version": "1.0"},
            })
            proc.stdin.write(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8") + b"\n"
            )
            await proc.stdin.drain()
            res = await self._stdio_send(srv, "tools/list", {})
            srv["tools"] = [
                {
                    "name": t.get("name"),
                    "description": t.get("description") or "",
                    "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}},
                }
                for t in (res.get("tools") or [])
            ]
            srv["status"] = "connected"
            srv["error"] = ""
            return {"ok": True, "tools": len(srv["tools"])}
        except Exception as e:
            srv["status"] = "error"
            srv["error"] = str(e)
            try:
                proc.kill()
            except Exception:
                pass
            return {"ok": False, "error": srv["error"]}

    # ---------------- http 传输（Streamable HTTP / SSE） ----------------

    @staticmethod
    def _parse_sse(text):
        for block in text.split("\n\n"):
            data = ""
            for line in block.split("\n"):
                if line.startswith("data:"):
                    data += line[5:].lstrip()
            if data:
                yield data

    async def _http_rpc(self, srv, method, params):
        import httpx

        sid = srv["next_id"]
        srv["next_id"] += 1
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if srv.get("session"):
            headers["Mcp-Session-Id"] = srv["session"]
        headers.update(srv.get("headers") or {})
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": sid, "method": method, "params": params}
        )
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.post(srv["url"], headers=headers, content=payload)
        except Exception as e:
            raise RuntimeError("MCP HTTP 请求失败：" + str(e))

        if resp.headers.get("mcp-session-id"):
            srv["session"] = resp.headers["mcp-session-id"]

        ct = resp.headers.get("content-type", "")
        msg = None
        if "text/event-stream" in ct:
            for d in self._parse_sse(resp.text):
                try:
                    j = json.loads(d)
                    if j.get("id") == sid:
                        msg = j
                        break
                except Exception:
                    continue
        else:
            try:
                j = resp.json()
                if j.get("id") == sid:
                    msg = j
            except Exception:
                pass
        if msg is None:
            raise RuntimeError("MCP HTTP 无匹配响应（HTTP %s）" % resp.status_code)
        if msg.get("error"):
            raise RuntimeError(msg["error"].get("message") or "MCP 错误")
        return msg.get("result")

    async def _connect_http(self, srv):
        srv["status"] = "connecting"
        try:
            await self._http_rpc(srv, "initialize", {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "iteris-agent", "version": "1.0"},
            })
            # notifications/initialized（fire-and-forget）
            await self._http_notify(srv, "notifications/initialized")
            res = await self._http_rpc(srv, "tools/list", {})
            srv["tools"] = [
                {
                    "name": t.get("name"),
                    "description": t.get("description") or "",
                    "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}},
                }
                for t in (res.get("tools") or [])
            ]
            srv["status"] = "connected"
            srv["error"] = ""
            return {"ok": True, "tools": len(srv["tools"])}
        except Exception as e:
            srv["status"] = "error"
            srv["error"] = str(e)
            return {"ok": False, "error": srv["error"]}

    async def _http_notify(self, srv, method):
        import httpx

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if srv.get("session"):
            headers["Mcp-Session-Id"] = srv["session"]
        headers.update(srv.get("headers") or {})
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    srv["url"],
                    headers=headers,
                    content=json.dumps({"jsonrpc": "2.0", "method": method}),
                )
                if resp.headers.get("mcp-session-id"):
                    srv["session"] = resp.headers["mcp-session-id"]
        except Exception:
            pass

    # ---------------- 对外操作 ----------------

    async def connect(self, pid, server_id=None, new_cfg=None):
        servers = self._list(pid)
        if server_id:
            srv = next((s for s in servers if s.get("id") == server_id), None)
            if srv is None:
                return {"ok": False, "error": "服务不存在"}
        elif new_cfg:
            name = str(new_cfg.get("name") or "").strip()
            if not name:
                return {"ok": False, "error": "服务名称不能为空"}
            transport = "http" if new_cfg.get("transport") == "http" else "stdio"
            if transport == "stdio" and not str(new_cfg.get("command") or "").strip():
                return {"ok": False, "error": "stdio 模式需要启动命令"}
            if transport == "http" and not str(new_cfg.get("url") or "").strip():
                return {"ok": False, "error": "http 模式需要 URL"}
            srv = {
                "id": _gen_id("mcp_"),
                "name": name,
                "transport": transport,
                "command": str(new_cfg.get("command") or "").strip(),
                "args": new_cfg.get("args") or [],
                "url": str(new_cfg.get("url") or "").strip(),
                "headers": new_cfg.get("headers") or {},
                "tools": [],
                "status": "offline",
                "error": "",
                "proc": None,
                "session": None,
                "next_id": 1,
                "pending": {},
                "last_err": "",
            }
            servers.append(srv)
            self._save_config(pid)
        else:
            return {"ok": False, "error": "缺少服务参数"}

        result = (
            await self._connect_stdio(srv)
            if srv["transport"] == "stdio"
            else await self._connect_http(srv)
        )
        self._save_config(pid)
        return {**result, "server": self._pub(srv)}

    def disconnect(self, pid, server_id):
        servers = self._list(pid)
        srv = next((s for s in servers if s.get("id") == server_id), None)
        if srv is None:
            return {"ok": False, "error": "服务不存在"}
        self._kill(srv)
        self._save_config(pid)
        return {"ok": True}

    def disconnect_all(self, pid):
        for srv in self._list(pid):
            self._kill(srv)
        self._save_config(pid)
        return {"ok": True}

    def remove(self, pid, server_id):
        servers = self._list(pid)
        srv = next((s for s in servers if s.get("id") == server_id), None)
        if srv is None:
            return {"ok": False, "error": "服务不存在"}
        self._kill(srv)
        self._state[pid] = [s for s in servers if s.get("id") != server_id]
        self._save_config(pid)
        return {"ok": True}

    def state(self, pid):
        return [self._pub(s) for s in self._list(pid)]

    async def call(self, pid, server_id, name, args):
        servers = self._list(pid)
        srv = next((s for s in servers if s.get("id") == server_id), None)
        if srv is None:
            return {"ok": False, "error": "服务不存在"}
        if srv.get("status") != "connected":
            return {"ok": False, "error": "MCP 服务未连接"}
        try:
            if srv["transport"] == "stdio":
                raw = await self._stdio_send(
                    srv, "tools/call", {"name": name, "arguments": args or {}}
                )
            else:
                raw = await self._http_rpc(
                    srv, "tools/call", {"name": name, "arguments": args or {}}
                )
            return {"ok": True, "result": self._text_result(raw)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------------- 工具 ----------------

    @staticmethod
    def _kill(srv):
        proc = srv.get("proc")
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
            srv["proc"] = None
        for sid, fut in list(srv.get("pending", {}).items()):
            if not fut.done():
                fut.set_exception(RuntimeError("MCP 已断开"))
        srv["pending"] = {}
        srv["status"] = "offline"
        srv["error"] = ""
        srv["tools"] = []
        srv["session"] = None

    @staticmethod
    def _text_result(res):
        if isinstance(res, dict) and res.get("isError"):
            return "错误：MCP 工具返回错误：" + MCPManager._text_result(res)
        parts = []
        for c in (res or {}).get("content") or []:
            t = c.get("type")
            if t == "text":
                parts.append(c.get("text", ""))
            elif t == "resource":
                r = c.get("resource")
                parts.append(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False))
            else:
                parts.append(json.dumps(c, ensure_ascii=False))
        return "\n".join(parts) or "（无返回内容）"
