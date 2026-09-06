/* =========================================================
   project-store.js · 多项目会话管理（Python 后端版）
   - 存储层：全部经后端 API（/api/data、/api/projects），数据落盘 data/ 按项目隔离
   - 项目 CRUD：新建 / 切换 / 重命名 / 删除（数据、MCP 配置按项目隔离）
   - 项目初始化：工具库种子 / 全局设置共享
   ========================================================= */
"use strict";
  var STORE = { settings:{}, messages:[], memory:[], kb:[], logs:[], tools:[] };
  var storageMode = "file";     // 恒为后端文件模式（localStorage 数据分支已移除）
  var saveTimer = null;
  var ready = false;

  /* 多项目：每个项目隔离 对话/记忆/知识库/工具库/日志/MCP */
  var projects = [];                                  // [{id,name,ts}]
  var currentProject = { id:"default", name:"默认项目" };
  var pendingDelete = null;

  function detectMode(){
    return Promise.resolve("file");
  }

  /* 仅用于记住上次选中的项目 id（轻量偏好，非项目数据） */
  function loadLS(k, fallback){
    try{
      var raw = localStorage.getItem(k);
      if(raw === null) return fallback;
      var v = JSON.parse(raw);
      return v === null || v === undefined ? fallback : v;
    }catch(e){ return fallback; }
  }

  function freshStore(){
    return { settings:{}, messages:[], memory:[], kb:[], logs:[], tools:[] };
  }

  /* 项目列表（后端 data/projects.json） */
  function loadProjectsList(){
    return fetch("/api/projects").then(function(r){ return r.json(); }).then(function(d){
      projects = (d.projects || []).map(function(p){ return { id:p.id, name:p.name, ts:p.ts||0 }; });
      if(!projects.length) projects = [{ id:"default", name:"默认项目", ts:0 }];
      return projects;
    }).catch(function(){
      projects = [{ id:"default", name:"默认项目", ts:0 }];
      return projects;
    });
  }

  /* 加载指定项目数据，返回 fresh（全新项目标记） */
  function loadProjectData(pid){
    return fetch("/api/data?projectId=" + encodeURIComponent(pid)).then(function(r){ return r.json(); }).then(function(data){
      STORE = {
        settings: data.settings || {},
        messages: data.messages || [],
        memory: data.memory || [],
        kb: data.kb || [],
        logs: data.logs || [],
        tools: data.tools || []
      };
      return !!data.fresh;
    }).catch(function(){
      STORE = freshStore();
      return true;
    });
  }

  /* 防抖落盘：切换项目前调用 saveNow() 立即写入 */
  function persist(){
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function(){ saveNow(); }, 400);
  }
  function saveNow(){
    fetch("/api/data?projectId=" + encodeURIComponent(currentProject.id), {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify(STORE)
    }).catch(function(){});
  }

  /* ---- 多项目：切换 / 新建 / 重命名 / 删除 ---- */
  function seedProjectTools(){
    tools = DEFAULT_TOOLS.map(function(t){ return Object.assign({}, t, { ts: Date.now() }); });
    if(!settings.toolsSeeded){
      settings.toolsSeeded = true;
      settings.preset = "pentest";
      settings.systemPrompt = PRESETS.pentest;
      STORE.settings = settings;
    }
    STORE.tools = tools;
    persist();
  }

  function switchProject(pid){
    var p = projects.filter(function(x){ return x.id === pid; })[0];
    if(!p || pid === currentProject.id) return;
    if(sending){ toast("任务运行中：请等待完成或点击停止后再切换项目"); return; }
    persist();
    saveNow();
    fetch("/api/mcp/disconnectAll", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ projectId: currentProject.id }) }).catch(function(){});
    currentProject = { id: p.id, name: p.name };
    try{ localStorage.setItem("agentChat.proj", p.id); }catch(e){}
    loadProjectData(p.id).then(function(fresh){
      settings = Object.assign({}, DEFAULTS, STORE.settings || {});
      messages = STORE.messages || [];
      memory = STORE.memory || [];
      kb = STORE.kb || [];
      logs = STORE.logs || [];
      tools = STORE.tools || [];
      if(fresh){
        seedProjectTools();
        log("sys", "项目「" + p.name + "」已初始化：内置渗透工具库与默认角色");
      }else{
        log("sys", "已切换到项目「" + p.name + "」");
      }
      updateProjUI();
      updateStatus();
      updateSendState();
      render();
      renderLogs();
      renderMem();
      renderMemTabs();
      renderTools();
      skillsInjected = [];
      lastSkillsTask = "";
      loadSkills();
      renderObs();
      autoConnectMcp();
    });
  }

  function createProject(){
    var name = window.prompt("新建项目名称：", "");
    if(name === null) return;
    name = (name || "").trim();
    if(!name){ toast("项目名称不能为空"); return; }
    fetch("/api/projects", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ action:"create", name: name }) })
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(!d.ok){ toast(d.error || "创建失败"); return; }
        projects.push({ id: d.project.id, name: d.project.name, ts: d.project.ts || 0 });
        switchProject(d.project.id);
      });
  }

  function renameProject(pid){
    var p = projects.filter(function(x){ return x.id === pid; })[0];
    if(!p) return;
    var name = window.prompt("重命名项目「" + p.name + "」：", p.name);
    if(name === null) return;
    name = (name || "").trim();
    if(!name){ toast("项目名称不能为空"); return; }
    p.name = name;
    if(currentProject.id === pid) currentProject.name = name;
    fetch("/api/projects", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ action:"rename", id: pid, name: name }) }).catch(function(){});
    updateProjUI();
    log("sys", "项目已重命名为「" + name + "」");
  }

  function confirmDeleteProject(pid){
    var p = projects.filter(function(x){ return x.id === pid; })[0];
    if(!p) return;
    if(sending){ toast("任务运行中：请等待完成或停止后再删除项目"); return; }
    pendingDelete = pid;
    document.getElementById("delTitle").textContent = "删除项目「" + p.name + "」";
    document.getElementById("delWarn").textContent = p.id === "default"
      ? "「默认项目」承载升级前的原有数据（旧版对话、记忆、知识库、日志等）。删除后旧数据将一并清除且无法恢复。"
      : "该项目的对话记录、记忆、知识库、工具库、MCP 配置与审计日志将全部删除，且无法恢复。";
    document.getElementById("delText").textContent = "确认删除该项目及其全部本地数据吗？";
    document.getElementById("delMask").hidden = false;
  }

  function doDeleteProject(){
    if(!pendingDelete) return;
    var pid = pendingDelete;
    pendingDelete = null;
    document.getElementById("delMask").hidden = true;
    var finish = function(){
      projects = projects.filter(function(x){ return x.id !== pid; });
      if(!projects.length) projects = [{ id:"default", name:"默认项目", ts:0 }];
      if(currentProject.id === pid) switchProject(projects[0].id);
      else{ updateProjUI(); log("sys", "已删除项目"); }
    };
    fetch("/api/projects", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ action:"delete", id: pid }) })
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(!d.ok){ toast(d.error || "删除失败"); return; }
        finish();
      });
  }
