/* =========================================================
   ui-render.js · 界面渲染
   - 消息区 / 工具库 / 观测台 / 日志 / 记忆面板 / 设置面板 / 项目侧边栏
   - 全部事件绑定与启动初始化
   ========================================================= */
"use strict";
  var toastTimer = null;
  function toast(msg){
    var el = document.getElementById("toast");
    if(!el) return;
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function(){ el.classList.remove("show"); }, 2400);
  }

  function updateProjUI(){
    var n = document.getElementById("projName");
    if(n) n.textContent = currentProject.name;
    var c = document.getElementById("sbCount");
    if(c) c.textContent = projects.length + " 个";
    renderProjects();
    renderObs();
  }

  function renderProjects(){
    var sidebar = document.getElementById("projectList");
    var drawer = document.getElementById("projDrawerList");
    var html = projects.map(function(p){
      return '<div class="sb-item' + (p.id === currentProject.id ? " active" : "") + '" data-proj="' + esc(p.id) + '">' +
        '<span class="sb-n">' + esc(p.name) + '</span>' +
        '<span class="sb-op">' +
          '<button type="button" title="重命名" data-ren-proj="' + esc(p.id) + '"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg></button>' +
          '<button type="button" class="del" title="删除" data-del-proj="' + esc(p.id) + '"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg></button>' +
        '</span></div>';
    }).join("");
    if(sidebar) sidebar.innerHTML = html;
    if(drawer) drawer.innerHTML = html;
  }

  function renderLogs(){
    var list = document.getElementById("logList");
    if(!list) return;
    if(!logs.length){
      list.innerHTML = '<div class="log-empty">暂无日志。开始一次对话后，这里会记录接口、工具、记忆与规划过程。</div>';
      return;
    }
    var show = logs.slice(-100).reverse();
    list.innerHTML = show.map(function(l){
      return '<div class="log-item type-' + l.type + '">' +
        '<span class="lt">' + l.time + '</span>' +
        '<span class="lb">' + (LOG_TAG[l.type] || l.type) + '</span>' +
        '<span class="ltx">' + esc(l.text) + '</span></div>';
    }).join("");
  }

  /* =========================================================
     3.5 渗透工具库
     ========================================================= */
  var CAT_CLS = { "信息收集":"cat-info", "Web 测试":"cat-web", "漏洞利用":"cat-exploit", "口令安全":"cat-pass", "流量分析":"cat-net", "其他":"" };
  /* ---- 渗透 Skills 状态 ---- */
  var SKILL_CATS = ["信息收集", "漏洞探测", "漏洞利用", "后渗透", "报告编写", "其他"];
  var skillsGlobal = [];            // 全局技能库（多项目共用）
  var skillsPrivate = [];           // 当前项目私有技能库
  var skillCat = "全部";            // 分类筛选
  var skillEditId = null;           // 正在编辑的技能 id
  var skillSuggestions = [];        // AI 生成、待人工确认的建议

  function normalizeSkill(x){
    return {
      id: x.id || uid(), title: x.title || "未命名技能", cat: x.cat || "其他",
      steps: Array.isArray(x.steps) ? x.steps : String(x.steps || "").split(/\n+/).filter(Boolean),
      exp: x.exp || "", pit: x.pit || "",
      version: x.version || 1, updated: x.updated || 0, scope: x.scope === "private" ? "private" : "global"
    };
  }
  function allSkills(){ return skillsGlobal.concat(skillsPrivate); }
  function findSkill(id){ return allSkills().filter(function(x){ return x.id === id; })[0]; }
  function findSkillByTitle(title, scope){
    var list = scope ? (scope === "global" ? skillsGlobal : skillsPrivate) : allSkills();
    return list.filter(function(x){ return x.title === title; })[0];
  }

  function renderTools(){
    var list = document.getElementById("toolList");
    if(!list) return;
    var kw = (document.getElementById("toolSearch").value || "").trim().toLowerCase();
    var arr = tools.filter(function(t){
      if(!kw) return true;
      return (t.name + " " + t.cat + " " + t.desc).toLowerCase().indexOf(kw) >= 0;
    });
    if(!arr.length){
      list.innerHTML = '<div class="log-empty">' + (tools.length ? "没有匹配的工具，换个关键词试试。" : "工具库为空：可点击下方「恢复默认工具集」，或在上方添加自定义工具。") + '</div>';
      return;
    }
    list.innerHTML = arr.map(function(t){
      return '<div class="tool-card">' +
        '<div class="tc-top"><span class="tc-cat ' + (CAT_CLS[t.cat] || "") + '">' + esc(t.cat || "其他") + '</span>' +
        '<button class="tc-del" type="button" data-del-tool="' + esc(t.id) + '">移除</button></div>' +
        '<h4>' + esc(t.name) + '</h4>' +
        '<p>' + esc(t.desc || "") + '</p>' +
        '<div class="tc-foot"><a class="tc-dl" href="' + esc(t.url) + '" target="_blank" rel="noopener noreferrer">' + ICONS.down + ' 下载</a></div>' +
        '</div>';
    }).join("");
  }

  function removeTool(id){
    var t = tools.filter(function(x){ return x.id === id; })[0];
    if(!t) return;
    tools = tools.filter(function(x){ return x.id !== id; });
    STORE.tools = tools;
    persist();
    log("sys", "已从工具库移除：" + t.name);
    renderTools();
  }

  function restoreDefaultTools(){
    var have = {};
    tools.forEach(function(t){ have[t.id] = true; });
    var added = 0;
    DEFAULT_TOOLS.forEach(function(t){
      if(!have[t.id]){
        tools.push(Object.assign({}, t, { ts: Date.now() }));
        added++;
      }
    });
    STORE.tools = tools;
    persist();
    log("sys", added ? "恢复默认工具集，新增 " + added + " 个工具" : "默认工具已齐全，无需恢复");
    renderTools();
  }

  /* ---- MCP 服务面板 ---- */
  var MCP_LABEL = { connected:"已连接", connecting:"连接中", error:"异常", offline:"未连接" };

  function renderMcp(){
    var list = document.getElementById("mcpList");
    if(!list) return;
    if(!mcpServers.length){
      list.innerHTML = '<div class="log-empty">尚未配置 MCP 服务。填写上方表单添加并连接（stdio 本地命令 或 Streamable HTTP 地址）。</div>';
      return;
    }
    list.innerHTML = mcpServers.map(function(s){
      var cls = s.status === "connected" ? "on" : (s.status === "error" ? "err" : "");
      var meta = s.transport === "stdio" ? (s.command || "") + (s.args && s.args.length ? " " + s.args.join(" ") : "") : (s.url || "");
      var toolsTxt = s.status === "connected" ? (s.tools.length ? s.tools.length + " 个工具" : "无工具") : "";
      return '<div class="mcp-item">' +
        '<div class="mcp-head"><span class="mcp-name">' + esc(s.name) + '</span>' +
        '<span class="mcp-status ' + cls + '">' + (MCP_LABEL[s.status] || s.status) + '</span></div>' +
        '<div class="mcp-meta">' + esc(meta) + (toolsTxt ? " · " + toolsTxt : "") + '</div>' +
        (s.error ? '<div class="mcp-err">' + esc(s.error) + '</div>' : '') +
        (s.status === "connected" && s.tools.length ? '<div class="mcp-tools">' + s.tools.slice(0, 16).map(function(t){ return '<span class="mcp-tool">' + esc(t.name) + '</span>'; }).join("") + (s.tools.length > 16 ? '<span class="mcp-tool">+' + (s.tools.length - 16) + '</span>' : '') + '</div>' : '') +
        '<div class="mcp-ops">' +
        (s.status === "connected"
          ? '<button type="button" data-mcp-dis="' + esc(s.id) + '">断开</button>'
          : '<button type="button" data-mcp-con="' + esc(s.id) + '">' + (s.status === "connecting" ? "连接中…" : "连接") + '</button>') +
        '<button type="button" class="del" data-mcp-del="' + esc(s.id) + '">移除</button>' +
        '</div></div>';
    }).join("");
  }

  /* =========================================================
     3.7 观测台：阶段状态机 + 工具时间线 + 参数总览
     ========================================================= */
  var loopCount = 0;
  var obsPhase = "idle";
  var toolLog = [];
  var PHASE = { idle:"空闲", planning:"规划中", reasoning:"思考/推理中", tool:"调用工具", streaming:"生成回答", reflecting:"反思中", done:"已完成", error:"出错" };

  function setPhase(p){
    obsPhase = p;
    renderObs();
  }

  function renderObs(){
    var body = document.getElementById("obsBody");
    if(!body) return;
    var dotCls = obsPhase === "done" ? "ok" : (obsPhase === "error" ? "err" : (obsPhase === "idle" ? "" : "live"));
    var lastThinking = "";
    for(var i = messages.length - 1; i >= 0; i--){
      if(messages[i].role === "assistant" && messages[i].reasoning){ lastThinking = messages[i].reasoning.slice(0, 240); break; }
    }
    var params = [
      ["模型", settings.model], ["服务商", String(settings.baseUrl || "").replace(/^https?:\/\//, "")],
      ["角色预设", settings.preset], ["温度", settings.temperature],
      ["规划模式", settings.planning], ["工具确认", settings.confirmTools ? "开" : "关"],
      ["最大轮次", settings.maxRounds], ["失败重试", settings.retries],
      ["上下文保留", settings.ctxKeep], ["知识库召回", settings.kbTopK],
      ["记忆召回", settings.memTopK], ["反思阈值", settings.reflStreak],
      ["技能注入", settings.skillsOn !== false ? "开" : "关"],
      ["输出格式", settings.format], ["置信度", settings.confidence ? "开" : "关"]
    ];
    body.innerHTML =
      '<div class="obs-card"><h3>运行状态</h3>' +
        '<div class="obs-phase"><span class="dot ' + dotCls + '"></span><b>' + (PHASE[obsPhase] || obsPhase) + '</b>' +
        '<span>' + (sending ? "任务执行中" : "等待指令") + '</span></div>' +
        '<div class="obs-grid" style="margin-top:11px">' +
          '<div><div class="obs-k">循环轮次</div><div class="obs-v">' + loopCount + ' / ' + settings.maxRounds + '</div></div>' +
          '<div><div class="obs-k">连续工具失败</div><div class="obs-v ' + (failStreak > 0 ? "warn" : "") + '">' + failStreak + '</div></div>' +
          '<div><div class="obs-k">会话消息数</div><div class="obs-v">' + messages.filter(function(m){ return m.role !== "error" && m.role !== "plan"; }).length + ' / ' + settings.ctxKeep + '</div></div>' +
          '<div><div class="obs-k">已用工具</div><div class="obs-v">' + toolLog.length + '</div></div>' +
        '</div></div>' +
      '<div class="obs-card"><h3>任务计划' + (currentPlan ? '<span class="pl-tag">' + currentPlan.length + ' 步</span>' : '') + '</h3>' +
        (currentPlan
          ? '<div class="obs-step">' + currentPlan.map(function(p,i){ return '<span class="' + (i === 0 ? "cur" : "") + '">' + (i+1) + '. ' + esc(p.step) + (p.detail ? " <small>" + esc(p.detail) + "</small>" : "") + '</span>'; }).join("<br>") + '</div>'
          : '<div class="obs-empty">暂无计划。复杂目标会自动拆解为步骤。</div>') +
        '</div>' +
      '<div class="obs-card"><h3>工具调用时间线</h3>' +
        (toolLog.length
          ? '<div class="obs-tl">' + toolLog.slice().reverse().map(function(t){
              var st = t.status === "done" ? "done" : (t.status === "fail" ? "fail" : "run");
              var stTxt = t.status === "done" ? "成功" : (t.status === "fail" ? "失败" : "执行中");
              return '<div class="obs-tl-item"><span class="tl-t">' + t.ts + '</span>' +
                '<span class="tl-n">' + esc(t.name) + '</span>' +
                '<span class="tl-s ' + st + '">' + stTxt + '</span>' +
                '<span class="tl-r">' + (t.cost > 0 ? t.cost + "ms" : "") + (t.status === "fail" ? " " + esc(String(t.result).slice(0, 28)) : "") + '</span></div>';
            }).join("") + '</div>'
          : '<div class="obs-empty">尚无工具调用。Agent 每次调用工具会实时显示在这里。</div>') +
        '</div>' +
      '<div class="obs-card"><h3>MCP 服务状态</h3>' +
        (mcpServers.length
          ? '<div class="obs-mcp">' + mcpServers.map(function(s){
              return '<div class="obs-mcp-row"><span class="dot ' + (s.status === "connected" ? "on" : (s.status === "error" ? "err" : "")) + '"></span><b>' + esc(s.name) + '</b>' +
                '<span>' + (s.status === "connected" ? (s.tools.length + " 个工具") : (s.status === "error" ? "异常" : (s.status === "connecting" ? "连接中" : "未连接"))) + '</span></div>';
            }).join("") + '</div><div class="obs-hint">管理入口：工具库 → MCP 服务 tab</div>'
          : '<div class="obs-empty">未配置 MCP 服务。</div>') +
        '</div>' +
      '<div class="obs-card"><h3>思考过程流</h3>' +
        (lastThinking
          ? '<div class="obs-step" style="font-size:12px;color:var(--ink-soft);font-weight:300">' + esc(lastThinking) + '</div>'
          : '<div class="obs-empty">当前对话暂无思考记录。</div>') +
        '</div>' +
      '<div class="obs-card"><h3>生效参数</h3><div class="obs-params">' +
        params.map(function(p){ return '<div class="obs-p"><b>' + p[0] + '</b><i>' + esc(String(p[1])) + '</i></div>'; }).join("") +
        '</div><div class="obs-hint">全部参数可在「设置」面板调整，无需改源码。</div></div>';
  }

  /* =========================================================
     5. 图标
     ========================================================= */
  var ICONS = {
    loop: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 3v4h-4"/></svg>',
    bolt: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>',
    clock:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>',
    calc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="2" width="16" height="20" rx="2"/><path d="M8 6h8"/><path d="M8 11h.01"/><path d="M12 11h.01"/><path d="M16 11h.01"/><path d="M8 15h.01"/><path d="M12 15h.01"/><path d="M16 15h.01"/><path d="M8 19h.01"/><path d="M12 19h.01"/><path d="M16 19h.01"/></svg>',
    down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="M6 11l6 6 6-6"/><path d="M4 21h16"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>'
  };

  function toolIcon(name){
    return name === "get_current_time" ? ICONS.clock : name === "calculator" ? ICONS.calc : ICONS.bolt;
  }

  /* =========================================================
     6. 渲染
     ========================================================= */
  var chatIn = document.getElementById("chatIn");
  var chatEl = document.getElementById("chat");

  function esc(s){
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  function md(plain){
    var out = "";
    var lines = String(plain).split("\n");
    var inCode = false, codeBuf = [], listBuf = [];
    function flushList(){
      if(listBuf.length){
        out += "<ul>" + listBuf.map(function(l){ return "<li>" + inline(l) + "</li>"; }).join("") + "</ul>";
        listBuf = [];
      }
    }
    function inline(t){
      var s = esc(t);
      s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
      s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      s = s.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
      return s;
    }
    lines.forEach(function(line){
      if(line.trim().indexOf("```") === 0){
        if(inCode){
          out += "<pre><code>" + codeBuf.join("\n") + "</code></pre>";
          codeBuf = []; inCode = false;
        }else{ flushList(); inCode = true; }
        return;
      }
      if(inCode){ codeBuf.push(esc(line)); return; }
      var t = line.trim();
      if(t === ""){ flushList(); return; }
      if(/^#{1,3}\s/.test(t)){ flushList(); out += "<h4>" + inline(t.replace(/^#{1,3}\s/,"")) + "</h4>"; return; }
      if(/^[-*]\s/.test(t)){ listBuf.push(t.replace(/^[-*]\s/,"")); return; }
      flushList();
      out += "<p>" + inline(line) + "</p>";
    });
    if(inCode){ out += "<pre><code>" + codeBuf.join("\n") + "</code></pre>"; }
    flushList();
    return out;
  }

  function render(){
    chatIn.innerHTML = "";
    if(!messages.length){
      chatIn.innerHTML =
        '<div class="welcome">' +
          '<div class="wm">' + ICONS.loop + '</div>' +
          '<h1>开始一段 Agent 对话</h1>' +
          '<p>真实调用大模型 · 记忆检索 · 任务规划 · 工具调用 · 反思与重试</p>' +
          '<div class="tip">' + (storageMode === "file" ? "数据保存在 data/ 目录（文件模式）" : "数据保存在本机浏览器（浏览器模式）") + '</div>' +
          '<div class="egs">' +
            '<button class="eg" type="button" data-eg="time"><b>时间查询（工具调用）</b><span>现在几点了？帮我看看今天的日期</span></button>' +
            '<button class="eg" type="button" data-eg="calc"><b>数学计算（工具调用）</b><span>帮我算一下 (128+64)*3.5 等于多少</span></button>' +
            '<button class="eg" type="button" data-eg="plan"><b>任务规划（拆解复杂目标）</b><span>帮我规划一次三亚三天两夜的行程，包含景点、交通和预算</span></button>' +
            '<button class="eg" type="button" data-eg="concept"><b>概念问答（纯对话）</b><span>用大白话介绍一下什么是 AI Agent</span></button>' +
          '</div>' +
        '</div>';
      chatIn.querySelectorAll("[data-eg]").forEach(function(b){
        b.addEventListener("click", function(){
          var map = {
            time:"现在几点了？帮我看看今天的日期",
            calc:"帮我算一下 (128+64)*3.5 等于多少",
            plan:"帮我规划一次三亚三天两夜的行程，包含景点、交通和预算",
            concept:"用大白话介绍一下什么是 AI Agent"
          };
          inputEl.value = map[b.getAttribute("data-eg")];
          send();
        });
      });
      scrollBottom();
      return;
    }
    messages.forEach(function(m){
      var el = document.createElement("div");
      el.className = "msg " + m.role;
      var av = m.role === "user"
        ? '<span class="av">' + ICONS.bolt + '</span>'
        : m.role === "plan"
          ? '<span class="av">' + ICONS.loop + '</span>'
          : '<span class="av">' + ICONS.loop + '</span>';
      el.innerHTML = av + '<div class="body"></div>';
      var body = el.querySelector(".body");

      if(m.role === "user"){
        body.textContent = m.content;
      }else if(m.role === "error"){
        body.innerHTML = md(m.content);
      }else if(m.role === "plan"){
        var pc = document.createElement("div");
        pc.className = "plan-card";
        pc.innerHTML = '<div class="plan-h">' + ICONS.loop + '任务计划<span class="pl-tag">已确定</span></div>';
        var ol = document.createElement("ol");
        (m.plan || []).forEach(function(s){
          var li = document.createElement("li");
          li.innerHTML = "<div><b>" + esc(s.step) + "</b><span>" + esc(s.detail || "") + "</span></div>";
          ol.appendChild(li);
        });
        pc.appendChild(ol);
        var f = document.createElement("div");
        f.className = "plan-f";
        f.textContent = "将按此计划执行：规划 → 调用工具 → 校验结果 → 交付";
        pc.appendChild(f);
        body.appendChild(pc);
      }else{
        if(m.reasoning && settings.showReasoning !== false){
          var det = document.createElement("details");
          det.className = "reasoning";
          det.innerHTML = "<summary>思考过程</summary><div class='rc'></div>";
          det.querySelector(".rc").textContent = m.reasoning;
          body.appendChild(det);
        }
        var content = document.createElement("div");
        content.innerHTML = md(m.content);
        body.appendChild(content);
        if(m.toolCalls && m.toolCalls.length){
          var chips = document.createElement("div");
          chips.className = "tool-chips";
          m.toolCalls.forEach(function(tc){
            var cls = "tool-chip";
            if(tc.status === "running") cls += " running";
            else if(tc.status === "fail") cls += " fail";
            var spinner = tc.status === "running" ? '<span class="spinner"></span>' : "";
            var result = tc.result !== undefined ? esc(tc.result) : (tc.status === "done" ? "" : "执行中…");
            var resultLine = result ? '<span>' + result + '</span>' : "";
            var chip = document.createElement("div");
            chip.className = cls;
            chip.innerHTML =
              '<span class="tic">' + toolIcon(tc.name) + '</span>' +
              '<div class="td"><b>' + esc(tc.name) + ' <span>(' + esc(tc.args) + ')</span></b>' + resultLine + '</div>';
            chips.appendChild(chip);
          });
          body.appendChild(chips);
        }
      }
      chatIn.appendChild(el);
    });
    scrollBottom();
  }

  function scrollBottom(){
    requestAnimationFrame(function(){ chatEl.scrollTop = chatEl.scrollHeight; });
  }

  /* =========================================================
     7. 状态栏 / 任务条
     ========================================================= */
  var statusBadge = document.getElementById("statusBadge");
  var statusText = document.getElementById("statusText");
  var taskBar = document.getElementById("taskBar");
  var taskText = document.getElementById("taskText");
  var taskMeta = document.getElementById("taskMeta");
  var taskFlag = document.getElementById("taskFlag");

  function updateStatus(){
    if(!ready){ statusText.textContent = "初始化"; return; }
    if(backendReady === true){
      statusBadge.classList.remove("warn"); statusBadge.classList.add("ok");
      statusText.textContent = "模型就绪 · " + settings.model;
    }else if(backendReady === false){
      statusBadge.classList.remove("ok"); statusBadge.classList.add("warn");
      statusText.textContent = "后端未配置密钥";
    }else{
      statusBadge.classList.remove("ok"); statusBadge.classList.remove("warn");
      statusText.textContent = "检查后端配置…";
    }
  }

  function updateTask(text, meta, flag){
    taskText.textContent = text;
    taskMeta.textContent = meta || "";
    if(flag){ taskFlag.textContent = flag; taskFlag.hidden = false; }
    else taskFlag.hidden = true;
    taskBar.hidden = false;
  }
  function hideTask(){ taskBar.hidden = true; }

  /* =========================================================
     8. 输入与发送按钮
     ========================================================= */
  var inputEl = document.getElementById("input");
  var btnSend = document.getElementById("btnSend");
  var sendIcon = document.getElementById("sendIcon");
  var sending = false;
  var currentCtrl = null;

  function updateSendState(){
    btnSend.disabled = sending;
    btnSend.classList.toggle("stop", sending);
    sendIcon.innerHTML = sending
      ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6h12v12H6z"/></svg>'
      : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>';
  }

  function autosize(){
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
  }

  /* =========================================================
     15. 设置面板
     ========================================================= */
  var drawer = document.getElementById("drawer");
  var overlay = document.getElementById("overlay");
  var drawerLogs = document.getElementById("drawerLogs");
  var drawerMem = document.getElementById("drawerMem");
  var drawerTools = document.getElementById("drawerTools");
  var drawerObs = document.getElementById("drawerObs");
  var drawerProj = document.getElementById("drawerProj");

  function closeAllDrawers(){
    drawer.classList.remove("show");
    drawerLogs.classList.remove("show");
    drawerMem.classList.remove("show");
    drawerTools.classList.remove("show");
    drawerObs.classList.remove("show");
    drawerProj.classList.remove("show");
    overlay.classList.remove("show");
  }
  function openDrawer(id){
    closeAllDrawers();
    var el = document.getElementById(id);
    if(el) el.classList.add("show");
    overlay.classList.add("show");
  }

  var fBase=document.getElementById("fBase"),
      fModel=document.getElementById("fModel"), fTemp=document.getElementById("fTemp"),
      fTempOut=document.getElementById("fTempOut"), fPrompt=document.getElementById("fPrompt"),
      fToolTime=document.getElementById("fToolTime"), fToolCalc=document.getElementById("fToolCalc"),
      fPlan=document.getElementById("fPlan"), fConfirm=document.getElementById("fConfirm"),
      fFormat=document.getElementById("fFormat"), fConfidence=document.getElementById("fConfidence"),
      fShowReasoning=document.getElementById("fShowReasoning"),
      fMemOn=document.getElementById("fMemOn"), fKbOn=document.getElementById("fKbOn"),
      fToolsOn=document.getElementById("fToolsOn"), fAutoMcp=document.getElementById("fAutoMcp"),
      fSkillsOn=document.getElementById("fSkillsOn"),
      fRounds=document.getElementById("fRounds"), fRetries=document.getElementById("fRetries"),
      fCtx=document.getElementById("fCtx"), fKbTopK=document.getElementById("fKbTopK"),
      fMemTopK=document.getElementById("fMemTopK"), fReflStreak=document.getElementById("fReflStreak"),
      fLogCap=document.getElementById("fLogCap");

  function switchUI(btn, on){
    btn.classList.toggle("on", on);
    btn.setAttribute("aria-checked", on ? "true" : "false");
  }
  function syncPresetUI(){
    document.querySelectorAll("#presets .preset").forEach(function(b){
      b.classList.toggle("on", b.getAttribute("data-p") === settings.preset);
    });
  }
  function fillForm(){
    /* API 密钥已由 Python 后端统一管理（backend/config.json / 环境变量 LLM_API_KEY），前端不再持有 */
    fBase.value = settings.baseUrl;
    fModel.value = settings.model;
    fTemp.value = settings.temperature;
    fTempOut.value = settings.temperature;
    fPrompt.value = settings.systemPrompt;
    switchUI(fToolTime, settings.toolTime);
    switchUI(fToolCalc, settings.toolCalc);
    fPlan.value = settings.planning;
    switchUI(fConfirm, settings.confirmTools);
    fFormat.value = settings.format;
    switchUI(fConfidence, settings.confidence);
    switchUI(fShowReasoning, settings.showReasoning !== false);
    switchUI(fMemOn, settings.memOn !== false);
    switchUI(fKbOn, settings.kbOn !== false);
    switchUI(fToolsOn, settings.toolsOn !== false);
    switchUI(fAutoMcp, settings.autoMcp !== false);
    switchUI(fSkillsOn, settings.skillsOn !== false);
    fRounds.value = settings.maxRounds;
    fRetries.value = settings.retries;
    fCtx.value = settings.ctxKeep;
    fKbTopK.value = settings.kbTopK;
    fMemTopK.value = settings.memTopK;
    fReflStreak.value = settings.reflStreak;
    fLogCap.value = settings.logCap;
    syncPresetUI();
  }
  function saveSettings(){
    /* API 密钥不再保存在前端设置 */
    settings.baseUrl = fBase.value.trim() || DEFAULTS.baseUrl;
    settings.model = fModel.value.trim() || DEFAULTS.model;
    settings.temperature = parseFloat(fTemp.value) || 0.7;
    settings.systemPrompt = fPrompt.value.trim() || PRESETS.agent;
    settings.toolTime = fToolTime.classList.contains("on");
    settings.toolCalc = fToolCalc.classList.contains("on");
    settings.planning = fPlan.value;
    settings.confirmTools = fConfirm.classList.contains("on");
    settings.format = fFormat.value;
    settings.confidence = fConfidence.classList.contains("on");
    settings.showReasoning = fShowReasoning.classList.contains("on");
    settings.memOn = fMemOn.classList.contains("on");
    settings.kbOn = fKbOn.classList.contains("on");
    settings.toolsOn = fToolsOn.classList.contains("on");
    settings.autoMcp = fAutoMcp.classList.contains("on");
    settings.skillsOn = fSkillsOn.classList.contains("on");
    settings.maxRounds = Math.min(10, Math.max(2, parseInt(fRounds.value, 10) || 6));
    settings.retries = Math.min(3, Math.max(0, parseInt(fRetries.value, 10) || 0));
    settings.ctxKeep = Math.min(60, Math.max(10, parseInt(fCtx.value, 10) || 30));
    settings.kbTopK = Math.min(6, Math.max(1, parseInt(fKbTopK.value, 10) || 3));
    settings.memTopK = Math.min(6, Math.max(1, parseInt(fMemTopK.value, 10) || 3));
    settings.reflStreak = Math.min(4, Math.max(1, parseInt(fReflStreak.value, 10) || 2));
    settings.logCap = Math.min(500, Math.max(100, parseInt(fLogCap.value, 10) || 300));
    STORE.settings = settings;
    persist();
    updateStatus();
    log("sys", "设置已保存");
    closeAllDrawers();
  }

  /* =========================================================
     16. 记忆 / 知识库面板
     ========================================================= */
  function renderMem(){
    var memList = document.getElementById("memList");
    var kbList = document.getElementById("kbList");
    if(memList){
      if(!memory.length){
        memList.innerHTML = '<div class="log-empty">暂无长期记忆条目。</div>';
      }else{
        memList.innerHTML = memory.slice().reverse().map(function(x){
          return '<div class="mem-item"><div class="mi-h"><b>记忆</b>' +
            '<button class="mi-del" type="button" data-del-mem="' + x.id + '">删除</button></div>' +
            '<p>' + esc(x.text) + '</p>' +
            '<span class="mi-meta">' + new Date(x.ts).toLocaleString("zh-CN",{hour12:false}) + '</span></div>';
        }).join("");
      }
    }
    if(kbList){
      if(!kb.length){
        kbList.innerHTML = '<div class="log-empty">暂无知识库条目。</div>';
      }else{
        kbList.innerHTML = kb.slice().reverse().map(function(x){
          var nChunks = x.chunks ? x.chunks.length : chunkText(x.content || "").length;
          var preview = x.chunks && x.chunks[0] ? x.chunks[0].text : (x.content || "");
          return '<div class="mem-item"><div class="mi-h"><b>' + esc(x.title) + '</b>' +
            '<button class="mi-del" type="button" data-del-kb="' + x.id + '">删除</button></div>' +
            '<p>' + esc(preview.slice(0, 180)) + (preview.length > 180 ? "…" : "") + '</p>' +
            '<span class="mi-meta">' + new Date(x.ts).toLocaleString("zh-CN",{hour12:false}) + ' · ' + nChunks + ' 块</span></div>';
        }).join("");
      }
    }
  }

  function renderMemTabs(){
    var onMem = document.getElementById("tabMemory").classList.contains("on");
    document.getElementById("memPane").hidden = !onMem;
    document.getElementById("kbPane").hidden = onMem;
  }

  /* =========================================================
     17. 事件绑定
     ========================================================= */
  inputEl.addEventListener("input", autosize);
  inputEl.addEventListener("keydown", function(e){
    if(e.key === "Enter" && !e.shiftKey){ e.preventDefault(); send(); }
  });
  btnSend.addEventListener("click", send);

  document.getElementById("btnClear").addEventListener("click", function(){
    if(sending) stopGenerate();
    messages = [];
    STORE.messages = messages;
    toolLog = [];
    currentPlan = null;
    loopCount = 0;
    failStreak = 0;
    setPhase("idle");
    persist();
    log("sys", "对话已清空");
    render();
  });

  document.getElementById("btnSettings").addEventListener("click", function(){ fillForm(); openDrawer("drawer"); });
  document.getElementById("btnClose").addEventListener("click", closeAllDrawers);
  document.getElementById("btnLogs").addEventListener("click", function(){ renderLogs(); openDrawer("drawerLogs"); });
  document.getElementById("btnCloseLogs").addEventListener("click", closeAllDrawers);
  document.getElementById("btnMem").addEventListener("click", function(){ renderMem(); renderMemTabs(); openDrawer("drawerMem"); });
  document.getElementById("btnCloseMem").addEventListener("click", closeAllDrawers);
  document.getElementById("btnTools").addEventListener("click", function(){ renderTools(); renderMcp(); openDrawer("drawerTools"); });
  document.getElementById("btnCloseTools").addEventListener("click", closeAllDrawers);
  document.getElementById("btnObs").addEventListener("click", function(){ renderObs(); openDrawer("drawerObs"); });
  document.getElementById("btnCloseObs").addEventListener("click", closeAllDrawers);
  overlay.addEventListener("click", closeAllDrawers);

  /* 多项目：切换 / 新建 / 重命名 / 删除 */
  function openProjDrawer(){ renderProjects(); openDrawer("drawerProj"); }
  document.getElementById("projChip").addEventListener("click", openProjDrawer);
  document.getElementById("btnProjNew").addEventListener("click", createProject);
  document.getElementById("btnProjNewSide").addEventListener("click", createProject);
  document.getElementById("btnCloseProj").addEventListener("click", closeAllDrawers);
  function bindProjectList(el){
    if(!el) return;
    el.addEventListener("click", function(e){
      var ren = e.target.closest("[data-ren-proj]");
      var del = e.target.closest("[data-del-proj]");
      var item = e.target.closest("[data-proj]");
      if(ren){ e.stopPropagation(); renameProject(ren.getAttribute("data-ren-proj")); return; }
      if(del){ e.stopPropagation(); confirmDeleteProject(del.getAttribute("data-del-proj")); return; }
      if(item){ switchProject(item.getAttribute("data-proj")); }
    });
  }
  bindProjectList(document.getElementById("projectList"));
  bindProjectList(document.getElementById("projDrawerList"));
  document.getElementById("delCancel").addEventListener("click", function(){ pendingDelete = null; document.getElementById("delMask").hidden = true; });
  document.getElementById("delOk").addEventListener("click", doDeleteProject);
  document.getElementById("delMask").addEventListener("click", function(e){
    if(e.target === e.currentTarget){ pendingDelete = null; document.getElementById("delMask").hidden = true; }
  });

  document.getElementById("btnSave").addEventListener("click", saveSettings);
  document.getElementById("btnDefault").addEventListener("click", function(){
    settings = Object.assign({}, DEFAULTS);
    STORE.settings = settings;
    persist();
    fillForm();
    updateStatus();
    log("sys", "已恢复默认设置");
  });
  document.querySelectorAll("#presets .preset").forEach(function(b){
    b.addEventListener("click", function(){
      document.querySelectorAll("#presets .preset").forEach(function(x){ x.classList.remove("on"); });
      b.classList.add("on");
      settings.preset = b.getAttribute("data-p");
      fPrompt.value = PRESETS[settings.preset];
      syncPresetUI();
    });
  });
  fTemp.addEventListener("input", function(){ fTempOut.value = fTemp.value; });
  fToolTime.addEventListener("click", function(){ switchUI(fToolTime, !fToolTime.classList.contains("on")); });
  fToolCalc.addEventListener("click", function(){ switchUI(fToolCalc, !fToolCalc.classList.contains("on")); });
  fConfirm.addEventListener("click", function(){ switchUI(fConfirm, !fConfirm.classList.contains("on")); });
  fConfidence.addEventListener("click", function(){ switchUI(fConfidence, !fConfidence.classList.contains("on")); });
  fShowReasoning.addEventListener("click", function(){ switchUI(fShowReasoning, !fShowReasoning.classList.contains("on")); });
  fMemOn.addEventListener("click", function(){ switchUI(fMemOn, !fMemOn.classList.contains("on")); });
  fKbOn.addEventListener("click", function(){ switchUI(fKbOn, !fKbOn.classList.contains("on")); });
  fToolsOn.addEventListener("click", function(){ switchUI(fToolsOn, !fToolsOn.classList.contains("on")); });
  fAutoMcp.addEventListener("click", function(){ switchUI(fAutoMcp, !fAutoMcp.classList.contains("on")); });
  fSkillsOn.addEventListener("click", toggleSkillsOn);

  document.getElementById("btnClearLogs").addEventListener("click", function(){
    logs = [];
    STORE.logs = logs;
    persist();
    renderLogs();
  });

  document.getElementById("tabMemory").addEventListener("click", function(){
    document.getElementById("tabMemory").classList.add("on");
    document.getElementById("tabKb").classList.remove("on");
    renderMemTabs();
  });
  document.getElementById("tabKb").addEventListener("click", function(){
    document.getElementById("tabKb").classList.add("on");
    document.getElementById("tabMemory").classList.remove("on");
    renderMemTabs();
  });

  document.getElementById("btnMemAdd").addEventListener("click", function(){
    var v = document.getElementById("memInput").value.trim();
    if(!v) return;
    memory.push({ id: uid(), text: v, ts: Date.now() });
    document.getElementById("memInput").value = "";
    STORE.memory = memory;
    persist();
    log("mem", "新增长期记忆：" + v.slice(0, 50));
    renderMem();
  });
  document.getElementById("btnKbAdd").addEventListener("click", function(){
    var t = document.getElementById("kbTitle").value.trim();
    var c = document.getElementById("kbContent").value.trim();
    if(!t || !c) return;
    var chunks = chunkText(c).map(function(x){ return { id: uid(), text: x }; });
    kb.push({ id: uid(), title: t, content: c, chunks: chunks, ts: Date.now() });
    document.getElementById("kbTitle").value = "";
    document.getElementById("kbContent").value = "";
    STORE.kb = kb;
    persist();
    log("mem", "新增知识条目：" + t + "（" + chunks.length + " 块）");
    renderMem();
  });
  document.getElementById("btnClearMem").addEventListener("click", function(){
    if(document.getElementById("tabMemory").classList.contains("on")){
      memory = [];
      STORE.memory = memory;
      log("mem", "已清空长期记忆");
    }else{
      kb = [];
      STORE.kb = kb;
      log("mem", "已清空知识库");
    }
    persist();
    renderMem();
  });
  document.getElementById("memList").addEventListener("click", function(e){
    var btn = e.target.closest("[data-del-mem]");
    if(!btn) return;
    memory = memory.filter(function(x){ return x.id !== btn.getAttribute("data-del-mem"); });
    STORE.memory = memory;
    persist();
    log("mem", "删除一条长期记忆（遗忘）");
    renderMem();
  });
  document.getElementById("kbList").addEventListener("click", function(e){
    var btn = e.target.closest("[data-del-kb]");
    if(!btn) return;
    kb = kb.filter(function(x){ return x.id !== btn.getAttribute("data-del-kb"); });
    STORE.kb = kb;
    persist();
    log("mem", "删除一条知识条目");
    renderMem();
  });

  /* 工具库事件 */
  document.getElementById("toolSearch").addEventListener("input", renderTools);
  document.getElementById("toolAddToggle").addEventListener("click", function(){
    document.getElementById("toolAddForm").hidden = !document.getElementById("toolAddForm").hidden;
  });
  document.getElementById("btnToolAdd").addEventListener("click", function(){
    var name = document.getElementById("taName").value.trim();
    var url = document.getElementById("taUrl").value.trim();
    var cat = document.getElementById("taCat").value;
    var desc = document.getElementById("taDesc").value.trim();
    if(!name){ warnInput("taName", "请填写工具名称"); return; }
    if(!/^https?:\/\/\S+$/i.test(url)){ warnInput("taUrl", "链接需以 http(s):// 开头"); return; }
    tools.push({ id: uid(), name: name, cat: cat, desc: desc, url: url, builtin: false, ts: Date.now() });
    STORE.tools = tools;
    persist();
    log("sys", "添加自定义工具：" + name);
    document.getElementById("taName").value = "";
    document.getElementById("taUrl").value = "";
    document.getElementById("taDesc").value = "";
    document.getElementById("toolAddForm").hidden = true;
    renderTools();
  });
  document.getElementById("toolList").addEventListener("click", function(e){
    var btn = e.target.closest("[data-del-tool]");
    if(!btn) return;
    removeTool(btn.getAttribute("data-del-tool"));
  });
  /* ---- 渗透 Skills：渲染 / 保存 / 编辑 / 复制 / 删除 / 复盘 ---- */
  function loadSkills(){
    return fetch("/api/skills?projectId=" + encodeURIComponent(currentProject.id)).then(function(r){ return r.json(); }).then(function(d){
      skillsGlobal = (d.global || []).map(normalizeSkill);
      skillsPrivate = (d.private || []).map(normalizeSkill);
      renderSkills();
      return { global: skillsGlobal, private: skillsPrivate };
    }).catch(function(){
      skillsGlobal = []; skillsPrivate = [];
      renderSkills();
      return { global: [], private: [] };
    });
  }

  function saveSkillsToBackend(){
    return fetch("/api/skills/save?projectId=" + encodeURIComponent(currentProject.id), {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({ projectId: currentProject.id, global: skillsGlobal, private: skillsPrivate })
    }).then(function(r){ return r.json(); }).then(function(d){
      if(d.ok){ toast("技能库已保存"); renderSkills(); }
      else{ toast("技能库保存失败：" + (d.error || "")); }
    }).catch(function(){ toast("技能库保存失败：网络错误"); });
  }

  function renderSkillCats(){
    var el = document.getElementById("skillCats");
    if(!el) return;
    el.innerHTML = ["全部"].concat(SKILL_CATS).map(function(c){
      return '<button type="button" class="skill-cat' + (skillCat === c ? " on" : "") + '" data-skcat="' + esc(c) + '">' + esc(c) + '</button>';
    }).join("");
  }

  function renderSkills(){
    var list = document.getElementById("skillList");
    if(!list) return;
    renderSkillCats();
    var kw = (document.getElementById("skillSearch").value || "").trim().toLowerCase();
    var arr = allSkills().filter(function(x){
      if(skillCat !== "全部" && x.cat !== skillCat) return false;
      if(!kw) return true;
      return (x.title + " " + x.cat + " " + x.exp + " " + x.pit + " " + (x.steps || []).join(" ")).toLowerCase().indexOf(kw) >= 0;
    });
    if(!arr.length){
      list.innerHTML = '<div class="log-empty">' + (allSkills().length ? "没有匹配的技能，换个关键词或分类试试。" : "技能库为空：可点「新增技能」沉淀第一条，或在全局库恢复默认技能集。") + '</div>';
      return;
    }
    list.innerHTML = arr.map(function(x){
      var steps = (x.steps || []).slice(0, 3).map(function(st){ return '<li>' + esc(st) + '</li>'; }).join("");
      if((x.steps || []).length > 3) steps += '<li>…共 ' + x.steps.length + ' 步</li>';
      return '<div class="skill-item">' +
        '<div class="sk-head">' +
          '<span class="sk-title">' + esc(x.title) + '</span>' +
          '<span class="sk-badge ' + (x.scope === "global" ? "g" : "p") + '">' + (x.scope === "global" ? "全局" : "私有") + '</span>' +
          '<span class="sk-ver">v' + x.version + '</span>' +
          '<span class="sk-meta">' + new Date(x.updated).toLocaleDateString("zh-CN") + '</span>' +
        '</div>' +
        '<div class="sk-body"><b>' + esc(x.cat) + '</b>' +
          '<ol class="sk-steps">' + steps + '</ol>' +
          (x.exp ? '<div class="sk-exp"><b>经验</b> ' + esc(x.exp) + '</div>' : '') +
          (x.pit ? '<div class="sk-pit"><b>踩坑</b> ' + esc(x.pit) + '</div>' : '') +
        '</div>' +
        '<div class="sk-ops">' +
          '<button type="button" data-sk-edit="' + esc(x.id) + '">编辑</button>' +
          '<button type="button" data-sk-copy="' + esc(x.id) + '">复制</button>' +
          '<button type="button" class="del" data-sk-del="' + esc(x.id) + '">删除</button>' +
        '</div></div>';
    }).join("");
  }

  function closeSkillForm(){
    skillEditId = null;
    document.getElementById("skillForm").hidden = true;
    document.getElementById("skillAddToggle").style.display = "";
    document.getElementById("btnSkillCancel").hidden = true;
    document.getElementById("btnSkillSave").textContent = "保存技能";
  }

  function openSkillEdit(id){
    var item = findSkill(id);
    if(!item) return;
    skillEditId = id;
    document.getElementById("skTitle").value = item.title;
    document.getElementById("skCat").value = item.cat;
    document.getElementById("skScope").value = item.scope;
    document.getElementById("skSteps").value = (item.steps || []).join("\n");
    document.getElementById("skExp").value = item.exp || "";
    document.getElementById("skPit").value = item.pit || "";
    document.getElementById("skillAddToggle").style.display = "none";
    document.getElementById("skillForm").hidden = false;
    document.getElementById("btnSkillCancel").hidden = false;
    document.getElementById("btnSkillSave").textContent = "保存修改";
  }

  function saveSkillForm(){
    var title = document.getElementById("skTitle").value.trim();
    if(!title){ warnInput("skTitle", "请填写技能标题"); return; }
    var steps = document.getElementById("skSteps").value.split(/\n+/).map(function(x){ return x.trim(); }).filter(Boolean);
    var scope = document.getElementById("skScope").value;
    var form = {
      title: title,
      cat: document.getElementById("skCat").value,
      scope: scope,
      steps: steps,
      exp: document.getElementById("skExp").value.trim(),
      pit: document.getElementById("skPit").value.trim()
    };
    if(skillEditId){
      var item = findSkill(skillEditId);
      if(item){
        item.title = form.title; item.cat = form.cat; item.steps = form.steps;
        item.exp = form.exp; item.pit = form.pit;
        item.scope = form.scope;
        item.version = (parseInt(item.version, 10) || 0) + 1;
        item.updated = Date.now();
      }
      skillEditId = null;
    }else{
      var list = form.scope === "global" ? skillsGlobal : skillsPrivate;
      list.push({ id: uid(), title: form.title, cat: form.cat, steps: form.steps, exp: form.exp, pit: form.pit, version: 1, updated: Date.now(), scope: form.scope });
    }
    closeSkillForm();
    saveSkillsToBackend();
    log("sys", "技能已保存：" + form.title + "（" + (form.scope === "global" ? "全局库" : "本项目私有") + "）");
  }

  function copySkill(id){
    var item = findSkill(id);
    if(!item) return;
    var list = item.scope === "global" ? skillsGlobal : skillsPrivate;
    list.push(Object.assign({}, item, { id: uid(), title: item.title + "（副本）", version: 1, updated: Date.now() }));
    saveSkillsToBackend();
    toast("已复制技能，可在列表中找到「副本」并编辑");
  }

  function deleteSkill(id){
    var item = findSkill(id);
    if(!item) return;
    if(!window.confirm("确认删除技能「" + item.title + "」吗？")) return;
    if(item.scope === "global") skillsGlobal = skillsGlobal.filter(function(x){ return x.id !== id; });
    else skillsPrivate = skillsPrivate.filter(function(x){ return x.id !== id; });
    saveSkillsToBackend();
    log("sys", "已删除技能：" + item.title);
  }

  /* ---- 复盘优化：AI 生成建议（只建议，写入需人工确认） ---- */
  function runSkillOptimize(){
    if(backendReady !== true){
      toast("请先在 backend/config.json 或环境变量 LLM_API_KEY 中配置模型密钥");
      return;
    }
    var box = document.getElementById("skillSugg");
    var btn = document.getElementById("btnSkillOptimize");
    btn.disabled = true; btn.textContent = "分析中…";
    box.innerHTML = '<div class="sk-sugg-empty">正在把本次对话日志与工具调用记录交给模型分析…</div>';
    generateSkillSuggestions().then(function(list){
      skillSuggestions = list;
      if(!list.length){
        box.innerHTML = '<div class="sk-sugg-empty">模型未给出有效建议。可以手动新增/编辑技能来沉淀本次经验。</div>';
        return;
      }
      box.innerHTML = '<div class="note" style="margin-bottom:12px">以下为 AI 生成的复盘分析与修改建议，<b>尚未写入技能库</b>。请逐条审核，确认后点「采纳并写入」才会落库（可自选写入全局库或本项目私有）。</div>';
      list.forEach(function(sugg, i){ box.appendChild(buildSuggCard(sugg, i)); });
    }).catch(function(e){
      box.innerHTML = '<div class="sk-sugg-empty">优化建议生成失败：' + esc(String(e && e.message ? e.message : e)) + '</div>';
    }).then(function(){
      btn.disabled = false; btn.textContent = "AI 生成优化建议";
    });
  }

  function buildSuggCard(sugg, i){
    var card = document.createElement("div");
    card.className = "sug-card";
    var label = sugg.action === "add" ? "新增" : sugg.action === "update" ? "更新" : "无变化";
    var bodyHtml = "";
    if((sugg.steps || []).length) bodyHtml += "<div><b>步骤：</b>" + esc((sugg.steps || []).join(" → ")) + "</div>";
    if(sugg.exp) bodyHtml += "<div><b>经验：</b>" + esc(sugg.exp) + "</div>";
    if(sugg.pit) bodyHtml += "<div><b>踩坑：</b>" + esc(sugg.pit) + "</div>";
    var applyHtml = sugg.action === "none"
      ? '<span class="sug-ok">无需改动</span>'
      : '<select data-sug-scope="' + i + '"><option value="global">写入全局库</option><option value="private">写入本项目私有</option></select>' +
        '<button class="btn" type="button" data-sug-apply="' + i + '">采纳并写入</button>';
    card.innerHTML =
      '<div class="sug-head"><span class="sug-act ' + esc(sugg.action) + '">' + label + '</span>' +
      '<span class="sug-title">' + esc(sugg.title || "未命名技能") + '</span></div>' +
      '<div class="sug-reason"><b>理由：</b>' + esc(sugg.reason || "") + '</div>' +
      (bodyHtml ? '<div class="sug-body">' + bodyHtml + '</div>' : '') +
      '<div class="sug-foot">' + applyHtml + '</div>';
    return card;
  }

  function applySuggestion(i){
    var sugg = skillSuggestions[i];
    if(!sugg || sugg.action === "none") return;
    var scopeSel = document.querySelector('[data-sug-scope="' + i + '"]');
    var target = (scopeSel && scopeSel.value) || "global";
    var list = target === "global" ? skillsGlobal : skillsPrivate;
    if(sugg.action === "add"){
      list.push({ id: uid(), title: sugg.title || "未命名技能", cat: (sugg.cat && SKILL_CATS.indexOf(sugg.cat) >= 0) ? sugg.cat : "其他", steps: sugg.steps || [], exp: sugg.exp || "", pit: sugg.pit || "", version: 1, updated: Date.now(), scope: target });
    }else if(sugg.action === "update"){
      var hit = findSkillByTitle(sugg.title, target) || findSkillByTitle(sugg.title, null);
      if(hit){
        hit.title = sugg.title || hit.title;
        if(sugg.cat && SKILL_CATS.indexOf(sugg.cat) >= 0) hit.cat = sugg.cat;
        if(sugg.steps && sugg.steps.length) hit.steps = sugg.steps;
        if(sugg.exp) hit.exp = sugg.exp;
        if(sugg.pit) hit.pit = sugg.pit;
        hit.version = (parseInt(hit.version, 10) || 0) + 1;
        hit.updated = Date.now();
      }else{
        list.push({ id: uid(), title: sugg.title || "未命名技能", cat: (sugg.cat && SKILL_CATS.indexOf(sugg.cat) >= 0) ? sugg.cat : "其他", steps: sugg.steps || [], exp: sugg.exp || "", pit: sugg.pit || "", version: 1, updated: Date.now(), scope: target });
      }
    }else{ return; }
    var btn = document.querySelector('[data-sug-apply="' + i + '"]');
    if(btn){ btn.disabled = true; btn.textContent = "已写入"; }
    saveSkillsToBackend();
    log("sys", "已人工确认并写入 AI 技能建议：" + (sugg.title || ""));
  }

  /* ---- Skills 开关（设置面板 fSkillsOn 与技能页 sSkillsOn 同步） ---- */
  function syncSkillsSwitchUI(){
    var on = settings.skillsOn !== false;
    var f = document.getElementById("fSkillsOn");
    var s = document.getElementById("sSkillsOn");
    if(f) switchUI(f, on);
    if(s) switchUI(s, on);
  }
  function toggleSkillsOn(){
    settings.skillsOn = !(settings.skillsOn !== false);
    STORE.settings = settings;
    persist();
    syncSkillsSwitchUI();
    log("sys", "渗透技能注入已" + (settings.skillsOn ? "开启" : "关闭"));
  }

  document.getElementById("btnRestoreTools").addEventListener("click", restoreDefaultTools);

  function warnInput(id, msg){
    var el = document.getElementById(id);
    el.style.borderColor = "#e2524a";
    el.setAttribute("placeholder", msg);
    setTimeout(function(){ el.style.borderColor = ""; }, 1800);
  }

  /* 渗透 Skills 面板事件 */
  document.getElementById("tabSkills").addEventListener("click", function(){
    document.getElementById("tabSkills").classList.add("on");
    document.getElementById("tabBuiltin").classList.remove("on");
    document.getElementById("tabMcp").classList.remove("on");
    document.getElementById("skillsPanel").hidden = false;
    document.getElementById("builtinPanel").hidden = true;
    document.getElementById("mcpPanel").hidden = true;
    renderSkills();
  });
  document.getElementById("skillCats").addEventListener("click", function(e){
    var b = e.target.closest("[data-skcat]");
    if(!b) return;
    skillCat = b.getAttribute("data-skcat");
    renderSkills();
  });
  document.getElementById("skillSearch").addEventListener("input", renderSkills);
  document.getElementById("skillAddToggle").addEventListener("click", function(){
    if(skillEditId) closeSkillForm();
    document.getElementById("skillForm").hidden = !document.getElementById("skillForm").hidden;
  });
  document.getElementById("btnSkillCancel").addEventListener("click", closeSkillForm);
  document.getElementById("btnSkillSave").addEventListener("click", saveSkillForm);
  document.getElementById("skillList").addEventListener("click", function(e){
    var ed = e.target.closest("[data-sk-edit]");
    var cp = e.target.closest("[data-sk-copy]");
    var del = e.target.closest("[data-sk-del]");
    if(ed){ openSkillEdit(ed.getAttribute("data-sk-edit")); }
    else if(cp){ copySkill(cp.getAttribute("data-sk-copy")); }
    else if(del){ deleteSkill(del.getAttribute("data-sk-del")); }
  });
  document.getElementById("btnSkillOptimize").addEventListener("click", runSkillOptimize);
  document.getElementById("skillSugg").addEventListener("click", function(e){
    var b = e.target.closest("[data-sug-apply]");
    if(b) applySuggestion(parseInt(b.getAttribute("data-sug-apply"), 10));
  });
  document.getElementById("sSkillsOn").addEventListener("click", toggleSkillsOn);

  /* MCP 面板事件 */
  document.getElementById("tabBuiltin").addEventListener("click", function(){
    document.getElementById("tabBuiltin").classList.add("on");
    document.getElementById("tabMcp").classList.remove("on");
    document.getElementById("tabSkills").classList.remove("on");
    document.getElementById("builtinPanel").hidden = false;
    document.getElementById("mcpPanel").hidden = true;
    document.getElementById("skillsPanel").hidden = true;
  });
  document.getElementById("tabMcp").addEventListener("click", function(){
    document.getElementById("tabMcp").classList.add("on");
    document.getElementById("tabBuiltin").classList.remove("on");
    document.getElementById("tabSkills").classList.remove("on");
    document.getElementById("mcpPanel").hidden = false;
    document.getElementById("builtinPanel").hidden = true;
    document.getElementById("skillsPanel").hidden = true;
  });
  document.getElementById("mcpAddToggle").addEventListener("click", function(){
    document.getElementById("mcpAddForm").hidden = !document.getElementById("mcpAddForm").hidden;
  });
  document.getElementById("mcTransport").addEventListener("change", function(){
    var isHttp = document.getElementById("mcTransport").value === "http";
    document.getElementById("mcCommand").disabled = isHttp;
    document.getElementById("mcArgs").disabled = isHttp;
    document.getElementById("mcUrl").disabled = !isHttp;
  });
  document.getElementById("btnMcpAdd").addEventListener("click", function(){
    var name = document.getElementById("mcName").value.trim();
    var transport = document.getElementById("mcTransport").value;
    var command = document.getElementById("mcCommand").value.trim();
    var args = document.getElementById("mcArgs").value.trim();
    var url = document.getElementById("mcUrl").value.trim();
    if(!name){ warnInput("mcName", "请填写服务名称"); return; }
    if(transport === "stdio" && !command){ warnInput("mcCommand", "请填写启动命令"); return; }
    if(transport === "http" && !/^https?:\/\/\S+$/i.test(url)){ warnInput("mcUrl", "链接需以 http(s):// 开头"); return; }
    var btn = document.getElementById("btnMcpAdd");
    btn.disabled = true; btn.textContent = "连接中…";
    fetch("/api/mcp/connect", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({ name: name, transport: transport, command: command, args: args, url: url, projectId: currentProject.id })
    }).then(function(r){ return r.json(); }).then(function(d){
      btn.disabled = false; btn.textContent = "连接该服务";
      if(!d.ok){ log("err", "MCP 连接失败（" + name + "）：" + (d.error || "未知错误")); }
      else{ log("sys", "MCP 服务已连接：" + name + "（" + d.tools + " 个工具）"); }
      loadMcpState();
    }).catch(function(e){
      btn.disabled = false; btn.textContent = "连接该服务";
      log("err", "MCP 请求失败：" + (e && e.message ? e.message : e));
    });
  });
  document.getElementById("mcpList").addEventListener("click", function(e){
    var con = e.target.closest("[data-mcp-con]");
    var dis = e.target.closest("[data-mcp-dis]");
    var del = e.target.closest("[data-mcp-del]");
    if(con){
      var id = con.getAttribute("data-mcp-con");
      fetch("/api/mcp/connect", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ id: id, projectId: currentProject.id }) })
        .then(function(r){ return r.json(); })
        .then(function(d){
          if(d.ok) log("sys", "MCP 服务已连接：" + d.server.name + "（" + d.tools + " 个工具）");
          else log("err", "MCP 连接失败：" + (d.error || ""));
          loadMcpState();
        });
    }else if(dis){
      var sid = dis.getAttribute("data-mcp-dis");
      fetch("/api/mcp/disconnect", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ id: sid, projectId: currentProject.id }) })
        .then(function(){ loadMcpState(); });
    }else if(del){
      var did = del.getAttribute("data-mcp-del");
      fetch("/api/mcp/remove", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ id: did, projectId: currentProject.id }) })
        .then(function(){ loadMcpState(); });
    }
  });

  /* =========================================================
     18. 启动
     ========================================================= */
  detectMode().then(function(mode){
    ready = true;
    loadProjectsList().then(function(){
      var savedId = loadLS("agentChat.proj", "");
      var target = projects.filter(function(p){ return p.id === savedId; })[0] || projects[0];
      currentProject = { id: target.id, name: target.name };
      loadProjectData(currentProject.id).then(function(fresh){
        settings = Object.assign({}, DEFAULTS, STORE.settings || {});
        messages = STORE.messages || [];
        memory = STORE.memory || [];
        kb = STORE.kb || [];
        logs = STORE.logs || [];
        tools = STORE.tools || [];
        if(fresh){
          seedProjectTools();
          log("sys", "项目「" + currentProject.name + "」已初始化：内置渗透工具库（" + tools.length + " 个默认工具，可移除或扩展），默认角色「渗透测试」");
        }else{
          log("sys", "已加载项目「" + currentProject.name + "」");
        }
        var hint = document.getElementById("modeHint");
        hint.textContent = "文件存储模式：项目数据按目录隔离保存在 data/（对话/记忆/知识库/工具/日志/MCP），全局设置共享";
        log("sys", "已连接 Python 后端（FastAPI），LLM 请求经后端代理转发");
        updateProjUI();
        updateStatus();
        updateSendState();
        render();
        renderLogs();
        renderMem();
        renderMemTabs();
        renderTools();
        loadSkills();
        renderObs();
        autoConnectMcp();
        checkBackend();
      });
    });
  });
