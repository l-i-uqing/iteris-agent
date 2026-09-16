# iteris-agent（渗透测试 AI Agent）

一个面向网络安全渗透测试的本地 AI Agent 应用：**浏览器前端负责"大脑编排"**（ReAct 循环、任务规划、记忆检索、工具 schema 生成、流式对话渲染），**Python 后端（FastAPI）承担 IO 执行层**（MCP 进程管理、文件持久化、LLM 代理转发）。API 密钥只存在后端，不再暴露到浏览器。

内置渗透工具库、MCP 服务对接、渗透技能库（Skills）复盘闭环、多项目会话隔离、可视化观测台，开箱即用，数据全部本地持久化。

> 合规声明：本工具面向**已获授权**的安全评估、CTF 竞赛、靶场与自建实验环境。请勿对未授权目标执行任何扫描、探测或利用操作，使用者应自行承担违规使用的法律风险。

## 快速开始

前置要求：Python 3.9+（含 pip），联网安装依赖。

```bash
python start.py          # 双击 start.py 亦可；首次运行自动安装依赖
```

然后浏览器打开 `http://127.0.0.1:8899`。

配置模型密钥（二选一）后**重启服务**：

| 方式 | 说明 |
|---|---|
| 编辑 `backend/config.json` | 填入 `api_key`（键：`api_key` / `base_url` / `model`） |
| 环境变量 | `LLM_API_KEY`（另可 `LLM_BASE_URL`、`LLM_MODEL` 覆盖默认值） |

配置优先级：**环境变量 > backend/config.json > 内置默认**（`https://api.deepseek.com` / `deepseek-chat`）。

## 功能总览

| 模块 | 能力 |
|---|---|
| Agent 对话 | 多轮上下文、流式输出（SSE）、思考过程展示、角色预设（Agent 助手 / 多角色团队 / 渗透测试 / 简洁助手 / 翻译助手） |
| 任务规划 | ReAct 循环：任务拆解 → 方案 → 执行 → 反思重规划；失败自动调整而非直接终止；人机确认（可开启「工具调用前询问」） |
| 记忆系统 | 长短期记忆分开存储；按需召回（BM25 + 语义相似度）；开关可控；防止上下文爆炸 |
| 知识库 RAG | 简易 BM25 知识库（`kbTopK` 条召回注入上下文） |
| 工具调用 | 内置 13 款渗透工具库（官方下载链接、可移除/新增/恢复默认）；内置 calculator 等函数工具；工具结果喂回模型继续推理；超时与重试 |
| MCP 服务 | stdio 子进程 + Streamable HTTP 双传输，真实拉起进程，工具列表动态加载，自动重连 |
| 渗透 Skills | 技能库沉淀（步骤/经验/踩坑），任务语义按需召回注入，复盘闭环（AI 只建议、人工确认写入） |
| 多项目会话 | 侧边栏项目列表，新建/切换/重命名/删除；对话、记忆、知识库、工具、MCP、日志、技能按项目隔离 |
| 可视化观测台 | 当前计划卡片、工具调用时间线、Agent 运行参数实时展示；运行日志面板按类型过滤 |
| 后端安全 | API 密钥仅存后端；LLM 请求经 `/api/proxy/llm` 代理；服务仅监听 127.0.0.1 |

## 架构分层

```
浏览器前端（web/）                        Python 后端（backend/）
─────────────────────────────          ─────────────────────────────
· 对话渲染 / 消息气泡                    · FastAPI 服务入口（main.py）
· ReAct Agent 循环（agent-core）         · MCP 服务管理（mcp_manager.py）
· 任务规划 / 反思重规划                  · 文件持久化（storage.py）
· 记忆 / 知识库检索（BM25）              · 全局配置 / API 密钥（config.py）
· 工具 schema 生成 / 人机确认            · 渗透技能库检索（skills.py）
· 渗透 Skills 面板 / 复盘优化            · LLM 请求代理（/api/proxy/llm）
· 观测台 / 日志 / 设置面板                · 静态托管 web/
```

前端负责「大脑编排」，后端只做 IO、进程、存储与 MCP 执行层。前后端通过 HTTP 接口通信。

## 目录结构

```
iteris-agent/
├── web/                        # 前端（静态托管）
│   ├── index.html              # 页面入口（界面结构，抽屉/面板）
│   ├── css/style.css           # 样式（含渗透 Skills 样式）
│   └── js/
│       ├── project-store.js    # 多项目会话管理（全部走后端 API）
│       ├── mcp-client.js       # MCP 客户端（状态 / 重连 / 调用）
│       ├── agent-core.js       # Agent 循环（规划 / 工具 / 记忆 / 技能召回 / 流式）
│       └── ui-render.js        # 界面渲染 + 事件 + 启动（含 Skills 面板）
├── backend/
│   ├── main.py                 # FastAPI 服务入口（全部路由 + 静态托管）
│   ├── mcp_manager.py          # MCP 服务管理（stdio 子进程 / http SSE）
│   ├── storage.py              # 文件持久化（项目会话 / 技能库 JSON）
│   ├── skills.py               # 渗透技能库（内置种子 + 中文分词 BM25 召回）
│   ├── config.py               # 全局配置（路径 / 端口 / API 密钥优先级）
│   ├── config.json             # 运行时自动生成（api_key / base_url / model）
│   └── requirements.txt
├── data/                       # 运行时自动生成（各项目会话与全局数据）
├── start.py                    # 一键启动（自动安装依赖 + uvicorn）
└── README.md
```

## 配置

### backend/config.json（自动生成，勿提交到公共仓库）

```json
{
  "api_key": "",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat"
}
```

### 环境变量

| 变量 | 作用 | 默认值 |
|---|---|---|
| `LLM_API_KEY` | 模型密钥（优先于 config.json） | — |
| `LLM_BASE_URL` | OpenAI 兼容接口地址 | `https://api.deepseek.com` |
| `LLM_MODEL` | 模型名 | `deepseek-chat` |
| `PORT` | 服务端口（仅监听 127.0.0.1） | `8899` |

### 前端设置面板（运行时配置，自动持久化到 data/settings.json）

| 参数 | 默认值 | 说明 |
|---|---|---|
| 服务商地址 / 模型 | deepseek / deepseek-chat | LLM 端点（密钥仍在后端） |
| 温度 | 0.7 | 采样随机性 |
| 角色预设 | 渗透测试 | 系统提示词（可自定义） |
| 任务规划 | auto | 复杂任务自动拆解规划 |
| 工具调用前询问 | 关 | 开启后每次工具调用需人工确认 |
| 置信度 / 结构化输出 | 关 / 自然语言 | 输出风格选项 |
| 最大执行轮次 | 6 | 工具循环上限（防死循环） |
| 失败重试次数 | 1 | 模型/工具异常自动重试 |
| 上下文保留条数 | 30 | 最近消息截断策略 |
| 知识库召回数 | 3 | RAG 注入条数 |
| 记忆召回数 | 3 | 长期记忆注入条数 |
| 反思阈值 | 2 | 连续失败触发反思重规划 |
| 日志上限 | 300 | 运行日志保留条数 |
| 开关 | 思考展示/记忆/知识库/工具库/MCP 自动连/技能注入 | 各能力独立开关 |

## 接口清单

| 接口 | 作用 |
|---|---|
| `GET /api/data?projectId=xxx` | 读取项目全部数据（settings/messages/memory/kb/logs/tools + fresh） |
| `POST /api/data` | 保存项目数据到磁盘 JSON |
| `GET/POST /api/projects` | 项目列表 / 新建、重命名、删除（action=create/rename/delete） |
| `POST /api/mcp/connect` | 连接 MCP 服务：stdio 拉起子进程；http 建立 Streamable HTTP 会话 |
| `POST /api/mcp/disconnect` / `disconnectAll` | 杀掉 MCP 子进程、断开连接 |
| `POST /api/mcp/remove` | 断开并移除服务配置 |
| `POST /api/mcp/call` | 调用 MCP 工具，返回执行结果 |
| `GET /api/mcp/state` | 全部 MCP 服务状态与工具列表 |
| `GET /api/skills?projectId=xxx` | 读取技能库（global 全局 + private 项目私有） |
| `POST /api/skills/save` | 保存技能库（global / private 可分别提交） |
| `POST /api/skills/recall` | 按任务语义 BM25 召回相关技能（topK，不全量注入） |
| `POST /api/skills/reset` | 重置技能库（scope=global 恢复内置种子 / private 清空私有） |
| `POST /api/proxy/llm` | LLM 请求代理（密钥在后端；支持流式 SSE 透传；请求体 `{model, baseUrl, messages, stream, temperature, tools?}`） |
| `GET /api/config` | 后端就绪状态（是否已配置密钥） |

所有 `/api/data`、`/api/mcp/*`、`/api/skills/*` 请求带 `projectId` 参数实现多项目隔离；后端同时兼容 `project` 参数名。静态资源按白名单托管（`/`、`/index.html`、`/css/style.css`、`/js/*.js`），其余路径返回 404。

## 内置渗透工具库

「渗透工具库」抽屉内置 13 款工具，均为官方发布页「下载」链接；支持自定义添加、移除、恢复默认工具集：

| 工具 | 分类 | 用途 | 官方下载 |
|---|---|---|---|
| Nmap | 信息收集 | 网络发现、端口扫描、服务/版本识别（NSE 脚本引擎） | [nmap.org](https://nmap.org/download.html) |
| Gobuster | 信息收集 | 目录 / 子域名 / DNS 爆破 | [GitHub](https://github.com/OJ/gobuster/releases) |
| FFUF | 信息收集 | Web 目录 / 参数 / vhost 模糊测试 | [GitHub](https://github.com/ffuf/ffuf/releases) |
| Nikto | 信息收集 | Web 服务器配置与已知漏洞扫描 | [GitHub](https://github.com/sullo/nikto) |
| Burp Suite Community | Web 测试 | Web 抓包、代理与安全测试集成环境 | [PortSwigger](https://portswigger.net/burp/communitydownload) |
| sqlmap | Web 测试 | SQL 注入检测与自动化利用 | [sqlmap.org](https://sqlmap.org/) |
| WPScan | Web 测试 | WordPress 漏洞 / 主题 / 插件 / 用户枚举 | [GitHub](https://github.com/wpscanteam/wpscan) |
| OWASP ZAP | Web 测试 | 开源 Web 应用安全扫描器 | [zaproxy.org](https://www.zaproxy.org/download/) |
| Metasploit Framework | 漏洞利用 | 漏洞利用、载荷生成与后渗透框架 | [metasploit.com](https://www.metasploit.com/) |
| John the Ripper | 口令安全 | 离线密码破解 | [openwall.com](https://www.openwall.com/john/) |
| THC-Hydra | 口令安全 | 在线口令爆破（SSH/FTP/HTTP 等） | [GitHub](https://github.com/vanhauser-thc/thc-hydra) |
| hashcat | 口令安全 | GPU 加速密码恢复 | [hashcat.net](https://hashcat.net/hashcat/) |
| Wireshark | 流量分析 | 抓包与网络协议分析 | [wireshark.org](https://www.wireshark.org/download.html) |

## MCP 对接（真实子进程，非占位）

Python 后端真正负责拉起/管理 MCP 进程：

- **stdio 模式**：后端用 asyncio 子进程执行启动命令，JSON-RPC over stdin/stdout（换行帧），流程 initialize → notifications/initialized → tools/list → tools/call，单请求 30s 超时，进程退出自动标记错误
- **http 模式**：Streamable HTTP（POST JSON + SSE 响应），跟踪 `Mcp-Session-Id` 会话头

在「渗透工具库 → MCP 服务」页添加服务，例如 Burp Suite MCP（stdio）：

```
名称：burp-mcp
传输：stdio
命令：npx -y burp-suite-mcp-server   （按实际包名填写）
参数：（可选，空格分隔）
```

或远程 MCP（http）：填写 `http://127.0.0.1:8000/mcp` 类地址。配置按项目保存在 `data/projects/<pid>/mcp.json`，切换项目自动断开旧连接并按新项目配置重连。

### 浏览器控制（Playwright MCP）

Agent 可操纵真实浏览器（打开网页、点击、输入、截图、提取文本、管理标签页、抓网络请求等），内置一键接入：

- **UI 入口**：「渗透工具库 → MCP 服务」页点击 **「一键接入浏览器控制（Playwright MCP）」**，自动创建并连接服务 `browser-control`（stdio）
- **等效手动配置**：

```
名称：browser-control
传输：stdio
命令：npx
参数：-y @playwright/mcp@latest --browser msedge
```

- 参数 `--browser msedge` 使用本机 Microsoft Edge（也可换 `chrome` / `--channel chromium`），无需单独安装浏览器；首次连接 npx 会自动下载 MCP 包（需 Node.js 18+）
- 连接成功后约 **26 个工具**可用：`browser_navigate`、`browser_click`、`browser_type`、`browser_fill_form`、`browser_snapshot`、`browser_find`、`browser_take_screenshot`、`browser_tabs`、`browser_press_key`、`browser_evaluate`、`browser_network_requests` 等
- Agent 在任务中会自动决定何时调用浏览器工具（打开目标站点 → 快照 → 点击/输入 → 提取结果），执行链路完整记录在观测台
- 安全提示：浏览器 MCP 会真实操作系统浏览器，建议仅在授权范围内使用，并在「设置」开启「工具调用前询问」

## 渗透 Skills 技能库（迭代闭环）

「渗透工具库 → 渗透 Skills」标签页沉淀渗透方法论并形成迭代闭环：

```
执行渗透任务 → Agent 按任务语义召回 Skills 注入上下文 → 任务结束复盘
→ 人工 / AI 辅助提出修改建议 → 人工确认更新 Skills → 下次任务使用优化后的 Skills
```

- **技能管理**：内置 10 条种子技能（信息收集 / 漏洞探测 / 漏洞利用 / 后渗透 / 报告编写），支持新增、编辑、复制、删除、分类筛选、搜索；每条含标题、分类、步骤、经验、踩坑案例、版本号、更新时间
- **全局库 / 项目私有**：`data/skills.json` 为全局技能库（多项目共用）；`data/projects/<pid>/skills.json` 为项目私有（default 项目私有存 `data/skills_private.json`）。新增/采纳时可选保存到哪个库，两个库都参与召回
- **按需召回（RAG 同源）**：执行任务时若开关开启，前端向后端 `/api/skills/recall` 按任务语义做中文分词 + BM25 打分，只把 topK 条相关技能注入系统提示词（防止 token 爆炸）；无关任务不注入
- **复盘优化（AI 只建议，写入必须人工确认）**：任务完成后点「AI 生成优化建议」，把本次对话日志与工具调用记录交给大模型分析，输出 新增/更新/无变化 的结构化建议；每条建议由你审核后点「采纳并写入」才会落库，可自选写入全局库或私有库。**AI 不会直接修改技能库**
- **开关**：设置面板与技能页顶部均可开关「执行任务时自动加载 Skills」；切换项目自动加载该项目视角的技能库

## 多项目会话（环境隔离）

侧边栏项目列表支持**新建、切换、重命名、删除**；每个项目独立保存对话、记忆、知识库、工具库、MCP 配置、日志与私有技能，任务数据互相隔离，防止上下文串扰：

- 数据按 `data/projects/<项目id>/` 分目录持久化（default 项目承载升级前的旧数据）
- 删除项目弹出确认弹窗，并说明不可恢复
- **任务运行中禁止删除项目**（会提示先等待完成或停止）
- 切换项目自动断开当前项目的 MCP 连接，并按新项目配置重连

## 数据持久化（不再依赖浏览器 localStorage）

```
data/
├── projects.json            # 项目列表
├── settings.json            # 全局设置（跨项目共享；密钥已移出，仅剩模型/参数）
├── skills.json              # 全局渗透技能库（多项目共用）
├── messages.json            # 「默认项目」会话（旧版数据自动归属）
├── memory.json / kb.json / tools.json / logs.json / mcp.json
└── projects/<项目id>/       # 其他项目（同构文件，互相隔离，含私有 skills.json）
```

## 与 Node 版（server.js）的差异

| 维度 | Node 版 | Python 版 |
|---|---|---|
| 后端 | server.js（零依赖） | FastAPI + uvicorn + httpx |
| MCP stdio | 后端子进程 | 后端 asyncio 子进程（真拉起进程） |
| API 密钥 | data/settings.json（可被前端读取） | backend/config.json / 环境变量（不出后端） |
| LLM 请求 | 前端直连第三方接口（CORS / 暴露密钥） | 后端代理 /api/proxy/llm |
| 浏览器 localStorage 存储 | 有（双模式） | 已移除，全部走后端 API |
| 启动 | start.bat | start.py |

## 常见问题（FAQ）

| 问题 | 处理 |
|---|---|
| 端口被占用 | 设置环境变量 `PORT` 换端口（如 `$env:PORT=8900; python start.py`），浏览器访问对应端口 |
| 聊天提示「后端未配置 API 密钥」 | 编辑 `backend/config.json` 填入 `api_key`，或设 `LLM_API_KEY`，重启服务 |
| 启动输出带红色 `NativeCommandError` | PowerShell 把 uvicorn 的 stderr 日志误判为错误；服务实际正常，以 `curl.exe http://127.0.0.1:8899/` 能否返回 200 为准 |
| 页面打开是旧版界面 | 浏览器强刷（Ctrl+F5）清除 JS 缓存 |
| MCP 连接后工具未出现 | 检查服务命令是否可独立运行、是否输出换行帧 JSON-RPC；查看「运行日志」中的错误 |
| 换模型 | 改 `backend/config.json` 的 `base_url`/`model` 或环境变量 `LLM_BASE_URL`/`LLM_MODEL` |
| 数据备份 | 直接复制整个 `data/` 目录即可（JSON 明文） |
| 想恢复内置技能库 | 技能页「恢复默认技能集」或调用 `POST /api/skills/reset`（scope=global） |

## 安全提示

- API 密钥仅存于 `backend/config.json`（或环境变量），请勿将 `data/`、`backend/config.json` 分享给他人
- MCP 服务配置由你手动填写，仅连接可信服务；高危工具调用可在「设置」开启「工具调用前询问」
- 服务仅监听 `127.0.0.1` 回环地址
- 渗透技能与内置工具仅用于授权评估 / CTF / 靶场，请遵守当地法律与目标方授权边界
