# -*- coding: utf-8 -*-
"""
storage.py · 文件持久化
- data/settings.json            全局设置（跨项目共享）
- data/{messages,memory,kb,tools,logs,mcp}.json    默认项目（default）
- data/projects/<pid>/*.json    其他项目（每项目隔离）
"""
import json
import shutil

from . import config

FILES = {
    "settings": "settings.json",
    "messages": "messages.json",
    "memory": "memory.json",
    "kb": "kb.json",
    "logs": "logs.json",
    "tools": "tools.json",
    "assets": "assets.json",
}

GLOBAL_SKILLS_FILE = config.DATA_DIR / "skills.json"
GLOBAL_KB_FILE = config.DATA_DIR / "kb_global.json"


def global_skills_file():
    return GLOBAL_SKILLS_FILE


def global_kb_file():
    return GLOBAL_KB_FILE


def load_global_kb():
    """全局知识库（跨项目共享的“记住”内容，多项目共用）"""
    return read_json(GLOBAL_KB_FILE, [])


def save_global_kb(items):
    write_json(GLOBAL_KB_FILE, items)


def private_skills_file(pid):
    """项目私有技能文件；default 项目落 data/skills_private.json（避免与全局 skills.json 冲突）"""
    if pid and pid != "default":
        return config.DATA_DIR / "projects" / pid / "skills.json"
    return config.DATA_DIR / "skills_private.json"


def load_skills(pid):
    return {
        "global": read_json(GLOBAL_SKILLS_FILE, []),
        "private": read_json(private_skills_file(pid), []),
    }


def save_skills(pid, global_items=None, private_items=None):
    """global_items / private_items 为 None 表示不写该文件"""
    if global_items is not None:
        write_json(GLOBAL_SKILLS_FILE, global_items)
    if private_items is not None:
        private_skills_file(pid).parent.mkdir(parents=True, exist_ok=True)
        write_json(private_skills_file(pid), private_items)


def read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_projects():
    """项目列表；为空时回退默认项目"""
    lst = read_json(config.PROJECTS_FILE, None)
    if isinstance(lst, list) and lst:
        return lst
    return [{"id": "default", "name": "默认项目", "ts": 0}]


def save_projects(lst):
    write_json(config.PROJECTS_FILE, lst)


def project_dir(pid):
    """项目数据目录：default 落在 data/ 根，其他在 data/projects/<pid>/"""
    if pid and pid != "default":
        return config.DATA_DIR / "projects" / pid
    return config.DATA_DIR


def project_file(pid, key):
    """settings 全局共享，其余按项目隔离"""
    if key == "settings":
        return config.DATA_DIR / FILES["settings"]
    return project_dir(pid) / FILES[key]


def is_project_fresh(pid):
    """项目是否全新：目标目录下不存在任何项目数据文件（settings 除外）"""
    d = project_dir(pid)
    for key, fname in FILES.items():
        if key == "settings":
            continue
        if (d / fname).exists():
            return False
    return True


def load_project_data(pid):
    payload = {}
    for key in FILES:
        payload[key] = read_json(
            project_file(pid, key), {} if key in ("settings", "assets") else []
        )
    payload["fresh"] = is_project_fresh(pid)
    return payload


def save_project_data(pid, data):
    project_dir(pid).mkdir(parents=True, exist_ok=True)
    for key in FILES:
        if key in data and data[key] is not None:
            write_json(project_file(pid, key), data[key])


def load_assets(pid):
    """读取项目资产（初扫沉淀）：[{target,scanned_at,status,components,paths,cves,suspects}]"""
    a = read_json(project_file(pid, "assets"), [])
    return a if isinstance(a, list) else []


def merge_assets(pid, result):
    """把初扫结果合并进项目资产（按 target 去重更新，最多保留 20 个目标）"""
    import time
    assets = load_assets(pid)
    site = result.get("site") or {}
    target = site.get("target") or result.get("target") or ""
    if not target:
        return assets
    entry = {
        "target": target,
        "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": site.get("status"),
        "components": site.get("components") or [],
        "paths": [{"path": r["path"], "status": r.get("status")}
                  for r in result.get("reachable_paths", []) if r.get("reachable")],
        "cves": [{"cve": c["cve"], "type": c.get("type")} for c in result.get("cves", [])],
        "suspects": [{"path": s2["path"], "types": s2.get("types", [])}
                     for s2 in result.get("suspects", [])],
    }
    assets = [a for a in assets if a.get("target") != target]
    assets.insert(0, entry)
    assets = assets[:20]
    write_json(project_file(pid, "assets"), assets)
    return assets


def delete_project_files(pid):
    """删除项目全部数据文件与 MCP 配置；default 保留目录本身，其他删除整个目录"""
    d = project_dir(pid)
    for key, fname in FILES.items():
        if key == "settings":
            continue
        p = d / fname
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    m = d / "mcp.json"
    if m.exists():
        try:
            m.unlink()
        except Exception:
            pass
    sp = private_skills_file(pid)
    if sp.exists():
        try:
            sp.unlink()
        except Exception:
            pass
    if pid != "default":
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
