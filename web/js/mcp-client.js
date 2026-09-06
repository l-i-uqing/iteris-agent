/* =========================================================
   mcp-client.js · MCP（Model Context Protocol）客户端
   - MCP 服务状态管理（按项目隔离，全部经 Python 后端）
   - 服务连接状态加载 / 自动重连 / 工具调用
   ========================================================= */
"use strict";
  var mcpServers = [];          // MCP 服务列表（来自 /api/mcp/state）
  var mcpToolMap = {};          // 注入名 -> {serverId, realName}

  function autoConnectMcp(){
    loadMcpState().then(function(list){
      if(settings.autoMcp === false) return;
      list.forEach(function(s){
        if(s.status === "offline" || s.status === "error"){
          fetch("/api/mcp/connect", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ id: s.id, projectId: currentProject.id }) })
            .then(function(r){ return r.json(); })
            .then(function(d){
              if(d.ok) log("sys", "MCP 服务已连接：" + s.name + "（" + d.tools + " 个工具）");
              loadMcpState();
            });
        }
      });
    });
  }

  function loadMcpState(){
    return fetch("/api/mcp/state?projectId=" + encodeURIComponent(currentProject.id)).then(function(r){ return r.json(); }).then(function(d){
      mcpServers = (d.servers || []).map(function(s){
        return { id:s.id, name:s.name, transport:s.transport, command:s.command, args:s.args||[], url:s.url, status:s.status, error:s.error, tools:s.tools||[] };
      });
      renderMcp();
      renderObs();
      return mcpServers;
    }).catch(function(){
      mcpServers = [];
      renderMcp();
      renderObs();
      return [];
    });
  }

  function execToolMcp(tc){
    var map = mcpToolMap[tc.name];
    if(!map) return Promise.resolve("错误：MCP 工具未就绪");
    var args = {};
    try{ args = JSON.parse(tc.args || "{}"); }catch(e){}
    return fetch("/api/mcp/call", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({ id: map.serverId, name: map.realName, args: args, projectId: currentProject.id })
    }).then(function(r){
      return r.json().then(function(d){
        if(!r.ok) throw new Error(d.error || ("HTTP " + r.status));
        return d.result;
      });
    });
  }
