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

  /* =========================================================
     16.5 渗透流程面板（六阶段工作流：侦察→扫描→枚举→利用→后渗透→报告）
     ========================================================= */
  var FLOW_ST = { pending:"待执行", running:"进行中", done:"完成", failed:"失败", skipped:"跳过" };
  function loadFlowPanel(){
    var panel = document.getElementById("flowPanel");
    if(!panel) return;
    fetch("/api/workflow/state?projectId=" + encodeURIComponent(currentProject.id))
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(!d.ok || !d.active || !d.workflow){
          panel.innerHTML = '<div class="obs-card"><h3>渗透流程 <span class="pl-tag">未启动</span></h3>' +
            '<div class="obs-empty">发送包含渗透目标的任务后，Agent 会按 侦察→扫描→枚举→利用→后渗透→报告 六阶段推进；也可手动启动。</div>' +
            '<button class="btn ghost" id="btnFlowStart" type="button" style="margin-top:8px">手动启动流程</button></div>';
          bindFlowStart();
          return;
        }
        var wf = d.workflow;
        var html = '<div class="obs-card"><h3>渗透流程 <span class="pl-tag">' +
          (wf.status === "done" ? "已完成" : (wf.status === "interrupted" ? "已中断（可恢复）" : "进行中")) +
          '</span></h3>';
        html += '<div class="flow-strip">';
        wf.phases.forEach(function(ph, i){
          var cls = "flow-" + (FLOW_ST[ph.status] ? ph.status : "pending");
          if(i === wf.current && ph.status === "pending") cls += " flow-cur";
          html += '<div class="flow-item ' + cls + '"><b>' + esc(ph.name) + '</b>' +
            '<small>' + (FLOW_ST[ph.status] || ph.status) + '</small>' +
            '<em>' + (ph.tools_used || []).length + ' 次工具</em></div>';
        });
        html += '</div>';
        var cur = wf.phases[wf.current] || wf.phases[wf.phases.length - 1];
        if(cur){
          html += '<div class="obs-step" style="margin-top:10px"><span class="cur">当前：' + esc(cur.name) + '</span><br>' +
            esc(cur.desc) + '<br><small>推荐工具：' + esc((cur.tools || []).join("、")) + '</small></div>';
        }
        if(wf.status !== "done"){
          html += '<div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">' +
            '<button class="btn ghost" data-flow="' + cur.id + '" data-flow-st="done" type="button">标记完成</button>' +
            '<button class="btn ghost" data-flow="' + cur.id + '" data-flow-st="failed" type="button">标记失败</button>' +
            '<button class="btn ghost" data-flow="' + cur.id + '" data-flow-st="skipped" type="button">跳过</button>' +
            '</div>';
        }
        html += '<div style="margin-top:6px;display:flex;gap:6px">' +
          '<button class="btn ghost" id="btnFlowReset" type="button">重置流程</button>' +
          (wf.status === "interrupted" ? '<button class="btn" id="btnFlowResume" type="button">恢复流程</button>' : '') +
          '</div>';
        html += '</div>';
        panel.innerHTML = html;
        bindFlowEvents();
      }).catch(function(){});
  }
  function bindFlowEvents(){
    var panel = document.getElementById("flowPanel");
    if(!panel) return;
    panel.querySelectorAll("[data-flow]").forEach(function(b){
      b.addEventListener("click", function(){
        fetch("/api/workflow/advance", { method:"POST", headers:{ "Content-Type":"application/json" },
          body: JSON.stringify({ projectId: currentProject.id, phaseId: b.getAttribute("data-flow"), status: b.getAttribute("data-flow-st") }) })
          .then(function(r){ return r.json(); })
          .then(function(d){ if(d.ok){ log("plan", "流程推进：" + b.getAttribute("data-flow") + " → " + b.getAttribute("data-flow-st")); } loadFlowPanel(); });
      });
    });
    var reset = document.getElementById("btnFlowReset");
    if(reset) reset.addEventListener("click", function(){
      if(!window.confirm("确认重置当前项目的渗透流程？进度将清空。")) return;
      fetch("/api/workflow/reset", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ projectId: currentProject.id }) })
        .then(function(r){ return r.json(); })
        .then(function(){ log("plan", "渗透流程已重置"); loadFlowPanel(); });
    });
    var resume = document.getElementById("btnFlowResume");
    if(resume) resume.addEventListener("click", function(){
      fetch("/api/workflow/start", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ projectId: currentProject.id, target: "恢复" }) })
        .then(function(r){ return r.json(); })
        .then(function(d){ if(d.ok){ log("plan", "流程已恢复"); window.iterisFlowProgress = d.progress || ""; } loadFlowPanel(); });
    });
  }
  function bindFlowStart(){
    var btn = document.getElementById("btnFlowStart");
    if(!btn) return;
    btn.addEventListener("click", function(){
      fetch("/api/workflow/start", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ projectId: currentProject.id, target: "手动启动" }) })
        .then(function(r){ return r.json(); })
        .then(function(d){ if(d.ok){ log("plan", "渗透流程已启动"); window.iterisFlowProgress = d.progress || ""; } loadFlowPanel(); });
    });
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
      var argTxt = Array.isArray(s.args) ? s.args.join(" ") : String(s.args || "").trim();
      var meta = s.transport === "stdio" ? ((s.command || "") + (argTxt ? " " + argTxt : "")) : (s.url || "");
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
      '<div id="flowPanel"></div>' +
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
      if(m.role === "tool") return; // 工具结果不展开在聊天区（见 assistant 工具卡片与右侧「可观测」面板）
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
        if(!String(m.content || "").trim() && m.toolCalls && m.toolCalls.length){
          content.innerHTML = '<span class="tc-note">正在调用工具：' + m.toolCalls.map(function(t){ return esc(String(t.name || "")); }).join("、") + '…</span>';
        }else{
          content.innerHTML = md(stripDSML(m.content));
        }
        body.appendChild(content);
        if(m.toolCalls && m.toolCalls.length){
          var chips = document.createElement("div");
          chips.className = "tool-chips";
          m.toolCalls.forEach(function(tc){
            var tcName = String(tc.name || "");
            if(/^unknown_/i.test(tcName) || tcName.toLowerCase().indexOf("unknown") >= 0) return; // 跳过无效工具
            var cls = "tool-chip";
            if(tc.status === "running") cls += " running";
            else if(tc.status === "fail") cls += " fail";
            var spinner = tc.status === "running" ? '<span class="spinner"></span>' : "";
            var result = "";
            if(tc.status === "running") result = "执行中…";
            else if(tc.status === "fail") result = String(tc.result !== undefined ? tc.result : "失败");
            // 成功时不在聊天卡片展开结果，完整内容见右侧「可观测」面板
            if(result.length > 120) result = result.slice(0, 120) + "…";
            var resultLine = result ? '<span>' + esc(result) + '</span>' : "";
            var chip = document.createElement("div");
            chip.className = cls;
            var argsStr = String(tc.args || "");
            if(argsStr.length > 100) argsStr = argsStr.slice(0, 100) + "…";
            chip.innerHTML =
              '<span class="tic">' + toolIcon(tc.name) + '</span>' +
              '<div class="td"><b>' + esc(tc.name) + ' <span>(' + esc(argsStr) + ')</span></b>' + resultLine + '</div>';
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
  var drawerPrescan = document.getElementById("drawerPrescan");

  function closeAllDrawers(){
    drawer.classList.remove("show");
    drawerLogs.classList.remove("show");
    drawerMem.classList.remove("show");
    drawerTools.classList.remove("show");
    drawerObs.classList.remove("show");
    drawerProj.classList.remove("show");
    drawerPrescan.classList.remove("show");
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
      fLogCap=document.getElementById("fLogCap"), fAuthz=document.getElementById("fAuthz");

  function switchUI(btn, on){
    btn.classList.toggle("on", on);
    btn.setAttribute("aria-checked", on ? "true" : "false");
  }

  (function(){
    var st = document.createElement("style");
    st.textContent = ".prescan-box{display:flex;gap:8px;align-items:center}" +
      ".ps-sec{margin-bottom:16px}" +
      ".ps-sec h3{font-size:13px;margin:0 0 8px;padding-bottom:6px;border-bottom:1px solid var(--line);color:var(--acc);font-weight:600}" +
      ".ps-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:8px}" +
      ".ps-card{background:var(--bg2);border:1px solid var(--line);border-radius:8px;padding:10px;font-size:12px}" +
      ".ps-card b{display:block;margin-bottom:4px}" +
      ".ps-card .tag{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;margin:2px 3px 2px 0;background:rgba(0,200,160,.12);color:#22c7a5}" +
      ".ps-card .warn-tag{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;margin:2px 3px 2px 0;background:rgba(255,170,0,.14);color:#ffb020}" +
      ".ps-badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;margin-left:6px;background:rgba(255,170,0,.14);color:#ffb020}" +
      ".ps-table{width:100%;border-collapse:collapse;font-size:12px}" +
      ".ps-table th,.ps-table td{border:1px solid var(--line);padding:5px 8px;text-align:left}" +
      ".ps-table th{background:var(--bg2);font-weight:600}" +
      ".ps-verdict{margin:8px 0;padding:8px 10px;border-radius:8px;background:rgba(255,170,0,.1);border:1px solid rgba(255,170,0,.35);color:#ffb020;font-weight:600}" +
      ".ps-verdict.ok{background:rgba(0,200,160,.08);border-color:rgba(0,200,160,.3);color:#22c7a5}" +
      ".ps-card{overflow-wrap:break-word;word-break:break-word;line-height:1.6}" +
      ".ps-card .note{display:inline-block;margin-top:2px}" +
      ".ps-paths{margin:5px 0 3px;line-height:22px}" +
      ".ps-path{display:inline-block;vertical-align:middle;background:rgba(120,140,180,.12);color:#8fa3c8;border-radius:4px;padding:1px 6px;margin:1px 4px 1px 0;font-size:11px;word-break:break-all;max-width:100%}" +
      ".ps-more{display:inline-block;vertical-align:middle;color:#8fa3c8;font-size:11px;margin-left:2px}" +
      ".ps-table td{word-break:break-all;overflow-wrap:break-word}";
    document.head.appendChild(st);
  })();

  /* 授权白名单渲染（后端 /api/authz/list，按项目隔离） */
  function renderAuthz(){
    var el = document.getElementById("authzList");
    if(!el) return;
    fetch("/api/authz/list?projectId=" + encodeURIComponent(currentProject.id))
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(!d.ok || !d.items || !d.items.length){
          el.innerHTML = '<span class="authz-empty">尚未配置授权目标——白名单为空时，Agent 对任何外部目标的工具调用都会被拦截。</span>';
          return;
        }
        el.innerHTML = d.items.map(function(it){
          return '<span class="authz-tag" title="' + esc(it.note || it.type) + '">' + esc(it.target) +
            '<button type="button" data-del-authz="' + it.id + '" aria-label="删除">×</button></span>';
        }).join("");
      }).catch(function(){});
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
    switchUI(fAuthz, settings.authzOn !== false);
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
    settings.authzOn = fAuthz.classList.contains("on");
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
    var onKb = document.getElementById("tabKb").classList.contains("on");
    document.getElementById("memPane").hidden = !onMem;
    document.getElementById("kbPane").hidden = !onKb;
    document.getElementById("graphPane").hidden = onMem || onKb;
  }

  /* 漏洞知识图谱渲染（后端 /api/memory/graph） */
  function renderGraph(){
    var el = document.getElementById("graphList");
    if(!el) return;
    el.innerHTML = '<div class="log-empty">图谱加载中…</div>';
    fetch("/api/memory/graph").then(function(r){ return r.json(); }).then(function(d){
      if(!d.ok || !d.nodes || !d.nodes.length){
        el.innerHTML = '<div class="log-empty">暂无漏洞图谱节点。完成一次「复盘入库」（用户给出正确 payload 后）会自动聚合，也可在下方手动添加。</div>';
        return;
      }
      el.innerHTML = d.nodes.map(function(n){
        var s = '<div class="mem-item"><div class="mi-h"><b>' + esc(n.vuln_type) + '</b>' +
          '<span class="mi-meta">成功 ' + n.success_count + ' 次' + (n.human_verified ? ' · 已验证' : '') + (n.cve_id ? ' · ' + esc(n.cve_id) : '') + '</span>' +
          '<button class="mi-del" type="button" data-del-graph="' + n.id + '">删除</button></div>';
        if(n.trigger) s += '<p><b>触发：</b>' + esc(n.trigger) + '</p>';
        if(n.technique && n.technique.length) s += '<p><b>利用：</b>' + esc(n.technique.join(" → ")) + '</p>';
        if(n.remediation) s += '<p style="color:var(--ok,#2ecc71)"><b>修复：</b>' + esc(n.remediation) + '</p>';
        return s + '</div>';
      }).join("");
    }).catch(function(e){
      el.innerHTML = '<div class="log-empty">图谱读取失败：' + esc(String(e && e.message || e)) + '</div>';
    });
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

  document.getElementById("btnSettings").addEventListener("click", function(){ fillForm(); renderAuthz(); openDrawer("drawer"); });
  document.getElementById("btnClose").addEventListener("click", closeAllDrawers);
  document.getElementById("btnLogs").addEventListener("click", function(){ renderLogs(); openDrawer("drawerLogs"); });
  document.getElementById("btnCloseLogs").addEventListener("click", closeAllDrawers);
  document.getElementById("btnMem").addEventListener("click", function(){ renderMem(); renderMemTabs(); renderGraph(); openDrawer("drawerMem"); });
  document.getElementById("btnCloseMem").addEventListener("click", closeAllDrawers);
  document.getElementById("btnTools").addEventListener("click", function(){ renderTools(); renderMcp(); openDrawer("drawerTools"); });
  document.getElementById("btnCloseTools").addEventListener("click", closeAllDrawers);
  document.getElementById("btnObs").addEventListener("click", function(){ renderObs(); loadFlowPanel(); openDrawer("drawerObs"); });
  document.getElementById("btnCloseObs").addEventListener("click", closeAllDrawers);
  overlay.addEventListener("click", closeAllDrawers);

  /* 多项目：切换 / 新建 / 重命名 / 删除 */
  function openProjDrawer(){ renderProjects(); openDrawer("drawerProj"); }
  document.getElementById("projChip").addEventListener("click", openProjDrawer);
  document.getElementById("btnProjNew").addEventListener("click", createProject);
  /* ===== 初扫 ===== */
  var psTarget = document.getElementById("prescanTarget");
  document.getElementById("btnPrescan").addEventListener("click", function(){
    openDrawer("drawerPrescan");
    if(psTarget && !psTarget.value){ psTarget.value = (window.lastTask || "").replace(/^.*?https?:\/\//, "").split(/[\s?]/)[0] || ""; psTarget.focus(); }
  });
  document.getElementById("btnClosePrescan").addEventListener("click", closeAllDrawers);
  document.getElementById("btnPrescanClose").addEventListener("click", closeAllDrawers);
  document.getElementById("btnPrescanRun").addEventListener("click", runPrescan);
  function esc(s){ return String(s == null ? "" : s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
  function runPrescan(){
    var target = (psTarget ? psTarget.value : "").trim();
    if(!target){ toast("请输入目标"); return; }
    var box = document.getElementById("prescanResult");
    box.innerHTML = '<div class="note">初扫进行中：指纹识别 → CVE 匹配 → 路径浅探测（并发）…</div>';
    document.getElementById("btnPrescanRun").disabled = true;
    log("sys", "初扫开始：" + target);
    fetch("/api/prescan", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ projectId: currentProject.id, target: target, maxPaths: 60, mode: (document.getElementById('prescanMode') || {}).value || 'standard' }) })
      .then(function(r){ return r.json(); })
      .then(function(d){
        document.getElementById("btnPrescanRun").disabled = false;
        if(!d.ok){ box.innerHTML = '<div class="ps-verdict">初扫失败：' + esc(d.error || "未知错误") + "</div>"; return; }
        log("sys", "初扫完成：" + (d.site ? d.site.target : "") + " 判定=" + d.verdict);
        renderPrescan(box, d);
      })
      .catch(function(e){ document.getElementById("btnPrescanRun").disabled = false; box.innerHTML = '<div class="ps-verdict">请求失败：' + esc(e) + "</div>"; });
  }
  function renderPrescan(box, d){
    var h = "";
    var st = d.site || {};
    h += '<div class="ps-sec"><h3>目标指纹</h3><div class="ps-card">' +
      "<b>" + esc(st.target || "") + "（HTTP " + esc(st.status || "?") + "）</b>" +
      (st.title ? "标题：" + esc(st.title) + "<br>" : "") +
      (st.server ? "Server：" + esc(st.server) + "<br>" : "") +
      (st.powered_by ? "X-Powered-By：" + esc(st.powered_by) + "<br>" : "") +
      (st.components && st.components.length ? "组件指纹：" + st.components.map(function(c){ return '<span class="tag">' + esc(c) + "</span>"; }).join("") : '<span class="note">未识别到已知组件</span>') +
      "</div></div>";
    h += '<div class="ps-sec"><h3>CVE 匹配' + (d.cves && d.cves.length ? '<span class="ps-badge">' + d.cves.length + " 个</span>" : "") + '</h3>';
    if(d.cves && d.cves.length){
      h += '<table class="ps-table"><tr><th>CVE</th><th>组件/版本</th><th>漏洞类型</th><th>风险</th><th>说明</th></tr>';
      d.cves.forEach(function(c){
        h += "<tr><td><b>" + esc(c.cve) + "</b></td><td>" + esc(c.component) + " " + esc(c.version) + "</td><td>" + esc(c.type) + "</td><td>" + esc(c.risk) + "</td><td>" + esc(c.note) + "</td></tr>";
      });
      h += "</table>";
    }else{
      h += '<div class="note">未匹配到已知高危 CVE（指纹库覆盖常见组件）</div>';
    }
    h += "</div>";
    h += '<div class="ps-sec"><h3>漏洞类型覆盖' + (d.vuln_types && d.vuln_types.length ? '<span class="ps-badge">' + d.vuln_types.length + " 类</span>" : "") + '</h3>';
    if(d.vuln_types && d.vuln_types.length){
      h += '<div class="ps-grid">';
      d.vuln_types.forEach(function(v){
        var cls = v.verdict.indexOf("迹象") >= 0 ? "warn-tag" : "tag";
        h += '<div class="ps-card"><b>' + esc(v.type) + ' <span class="' + cls + '">' + esc(v.verdict) + "</span></b>" +
          (v.owasp ? '<span class="tag">' + esc(v.owasp) + "</span><br>" : "") +
          "探测点：" + v.probe_points + " 处" + (v.paths && v.paths.length ? '<div class="ps-paths">' + v.paths.slice(0,6).map(function(p){ return '<span class="ps-path">' + esc(p) + "</span>"; }).join("") + (v.paths.length > 6 ? '<span class="ps-more">…等 ' + v.paths.length + " 个</span>" : "") + "</div>" : "") +
          (v.evidence ? '<br><span class="note">证据：' + esc(v.evidence.length > 60 ? v.evidence.slice(0, 60) + "…" : v.evidence) + "</span>" : "") +
          (v.cve_hits && v.cve_hits.length ? "<br>CVE：" + v.cve_hits.map(function(c){ return esc(c); }).join("、") : "") +
          "</div>";
      });
      h += "</div>";
    }else{
      h += '<div class="note">未发现明显漏洞类型迹象</div>';
    }
    h += "</div>";
    var eps = d.endpoints || [];
    if(eps.length){
      var epSignal = eps.filter(function(x){ return x.verdict === "有迹象"; });
      var epWait = eps.filter(function(x){ return x.verdict === "待验证"; });
      h += '<div class="ps-sec"><h3>功能点参数探测' +
        (epSignal.length ? '<span class="ps-badge">' + epSignal.length + " 个有迹象</span>" : "") +
        (epWait.length ? '<span class="ps-badge" style="background:rgba(90,140,255,.15);color:#7aa5ff">' + epWait.length + " 个待验证</span>" : "") +
        '</h3>';
      h += '<table class="ps-table"><tr><th>接口</th><th>方法</th><th>参数</th><th>判定</th><th>说明</th></tr>';
      eps.forEach(function(e){
        var cls = e.verdict === "有迹象" ? "warn-tag" : (e.verdict === "待验证" ? "tag" : "note");
        h += "<tr><td><b>" + esc(e.path) + "</b></td><td>" + esc(e.method) + "</td><td>" +
          (e.params && e.params.length ? esc(e.params.join(", ")) : "—") + "</td><td>" + '<span class="' + cls + '">' +
          esc(e.verdict) + "</span></td><td>" +
          (e.evidence ? esc(e.evidence) : esc(e.note || "")) + "</td></tr>";
      });
      h += "</table>";
    }
    var reach = (d.reachable_paths || []).filter(function(x){ return x.reachable; });
    h += '<div class="ps-sec"><h3>接口点 / 功能点排查' + (reach.length ? '<span class="ps-badge">' + reach.length + " 个可达</span>" : "") + '</h3>';
    if(reach.length){
      h += '<table class="ps-table"><tr><th>路径</th><th>状态</th><th>标题/特征</th><th>可能漏洞类型</th></tr>';
      reach.forEach(function(r){
        var types = (r.types || []).map(function(t){ return '<span class="warn-tag">' + esc(t) + "</span>"; }).join("");
        h += "<tr><td><b>" + esc(r.path) + "</b></td><td>" + esc(r.status) + "</td><td>" + esc((r.title || "") + (r.features && r.features.length ? " · " + r.features.join(" · ") : "")) + "</td><td>" + (types || '<span class="note">—</span>') + "</td></tr>";
      });
      h += "</table>";
    }else{
      h += '<div class="note">无可达路径</div>';
    }
    h += "</div>";
    h += '<div class="ps-sec"><h3>结论</h3><div class="ps-verdict' + (d.verdict.indexOf("风险面") >= 0 ? "" : " ok") + '">' + esc(d.verdict) + "</div>";
    if(d.suspects && d.suspects.length){
      h += '<div class="ps-grid">';
      d.suspects.slice(0,8).forEach(function(x){
        h += '<div class="ps-card"><b>' + esc(x.path) + "（" + esc(x.status) + "）</b>" +
          x.types.map(function(t){ return '<span class="warn-tag">' + esc(t) + "</span>"; }).join("") +
          (x.title ? "<br>" + esc(x.title) : "") +
          (x.evidence ? '<br><span class="note">证据：' + esc(x.evidence.length > 60 ? x.evidence.slice(0, 60) + "…" : x.evidence) + "</span>" : "") +
          (x.note ? "<br><span class='note'>" + esc(x.note) + "</span>" : "") +
          "</div>";
      });
      h += "</div>";
    }
    h += '<div class="note" style="margin-top:8px">' + esc(d.note || "") + "</div></div>";
    box.innerHTML = h;
  }
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
  fAuthz.addEventListener("click", function(){ switchUI(fAuthz, !fAuthz.classList.contains("on")); });
  document.getElementById("btnAuthzAdd").addEventListener("click", function(){
    var t = document.getElementById("authzInput").value.trim();
    if(!t){ warnInput("authzInput", "请填写授权目标"); return; }
    fetch("/api/authz/add", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ projectId: currentProject.id, target: t }) })
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(!d.ok){ log("err", "添加授权失败：" + (d.error || "")); return; }
        document.getElementById("authzInput").value = "";
        log("sys", "已添加授权目标：" + t);
        renderAuthz();
      });
  });
  document.getElementById("authzList").addEventListener("click", function(e){
    var b = e.target.closest("[data-del-authz]");
    if(!b) return;
    fetch("/api/authz/remove", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ projectId: currentProject.id, id: b.getAttribute("data-del-authz") }) })
      .then(function(r){ return r.json(); })
      .then(function(d){ if(d.ok) log("sys", "已移除授权目标"); renderAuthz(); });
  });

  document.getElementById("btnClearLogs").addEventListener("click", function(){
    logs = [];
    STORE.logs = logs;
    persist();
    renderLogs();
  });

  document.getElementById("tabMemory").addEventListener("click", function(){
    document.getElementById("tabMemory").classList.add("on");
    document.getElementById("tabKb").classList.remove("on");
    document.getElementById("tabGraph").classList.remove("on");
    renderMemTabs();
  });
  document.getElementById("tabKb").addEventListener("click", function(){
    document.getElementById("tabKb").classList.add("on");
    document.getElementById("tabMemory").classList.remove("on");
    document.getElementById("tabGraph").classList.remove("on");
    renderMemTabs();
  });
  document.getElementById("tabGraph").addEventListener("click", function(){
    document.getElementById("tabGraph").classList.add("on");
    document.getElementById("tabMemory").classList.remove("on");
    document.getElementById("tabKb").classList.remove("on");
    renderMemTabs();
    renderGraph();
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
    }else if(document.getElementById("tabKb").classList.contains("on")){
      kb = [];
      STORE.kb = kb;
      log("mem", "已清空知识库");
    }else{
      log("mem", "漏洞图谱不支持一键清空，请在列表中逐条删除");
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

  document.getElementById("graphList").addEventListener("click", function(e){
    var btn = e.target.closest("[data-del-graph]");
    if(!btn) return;
    var id = btn.getAttribute("data-del-graph");
    fetch("/api/memory/graph/delete", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ id: id }) })
      .then(function(r){ return r.json(); })
      .then(function(d){
        log(d.ok ? "mem" : "err", d.ok ? "已删除图谱节点" : "删除失败：" + (d.error || ""));
        renderGraph();
      });
  });
  document.getElementById("btnGraphAdd").addEventListener("click", function(){
    var vuln_type = document.getElementById("graphType").value.trim();
    if(!vuln_type){ warnInput("graphType", "请填写漏洞类型"); return; }
    var body = {
      vuln_type: vuln_type,
      trigger: document.getElementById("graphTrigger").value.trim(),
      technique: document.getElementById("graphTechnique").value.split("\n").map(function(x){ return x.trim(); }).filter(function(x){ return x; }),
      remediation: document.getElementById("graphRemediation").value.trim(),
      cve_id: document.getElementById("graphCve").value.trim()
    };
    fetch("/api/memory/graph/upsert", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify(body) })
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(!d.ok){ log("err", "图谱保存失败：" + (d.error || "未知错误")); return; }
        log("mem", "图谱节点已保存：" + vuln_type);
        document.getElementById("graphType").value = "";
        document.getElementById("graphTrigger").value = "";
        document.getElementById("graphTechnique").value = "";
        document.getElementById("graphRemediation").value = "";
        document.getElementById("graphCve").value = "";
        renderGraph();
      });
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
  /* 一键接入浏览器控制（Playwright MCP，stdio 驱动本机 Edge/Chrome） */
  document.getElementById("btnMcpQuickBrowser").addEventListener("click", function(){
    var btn = document.getElementById("btnMcpQuickBrowser");
    btn.disabled = true; btn.textContent = "接入中…";
    fetch("/api/mcp/state?projectId=" + encodeURIComponent(currentProject.id))
      .then(function(r){ return r.json(); })
      .then(function(d){
        var existing = (d.servers || []).filter(function(s){ return s.name === "browser-control"; })[0];
        var body = existing
          ? { id: existing.id, projectId: currentProject.id }
          : { name: "browser-control", transport: "stdio", command: "npx", args: "-y @playwright/mcp@latest --browser msedge --idle-timeout 0", projectId: currentProject.id };
        return fetch("/api/mcp/connect", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify(body) }).then(function(r){ return r.json(); });
      })
      .then(function(d){
        btn.disabled = false; btn.textContent = "一键接入浏览器控制";
        if(d.ok){
          log("sys", "浏览器控制 MCP 已接入（" + d.tools + " 个工具可用：browser_navigate / browser_click / browser_snapshot 等）");
          toast("浏览器控制 MCP 已接入，Agent 可打开网页、点击、输入、截图");
        }else{
          log("err", "浏览器控制 MCP 接入失败：" + (d.error || "未知错误"));
          toast("浏览器控制 MCP 接入失败：" + (d.error || ""));
        }
        loadMcpState();
      })
      .catch(function(e){
        btn.disabled = false; btn.textContent = "一键接入浏览器控制";
        log("err", "浏览器控制 MCP 请求失败：" + (e && e.message ? e.message : e));
      });
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
