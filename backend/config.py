# -*- coding: utf-8 -*-
"""
config.py · 全局配置
- API 密钥只存在后端（backend/config.json 或环境变量），绝不下发浏览器
- 读取优先级：环境变量 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL > backend/config.json > 默认值
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # iteris-agent/
WEB_DIR = ROOT / "web"                                 # 前端静态目录
DATA_DIR = ROOT / "data"                               # 项目数据目录（运行时自动创建）
PROJECTS_FILE = DATA_DIR / "projects.json"             # 项目列表
BACKEND_DIR = Path(__file__).resolve().parent          # backend/
CONFIG_FILE = BACKEND_DIR / "config.json"              # 后端配置（含 API 密钥）

PORT = int(os.environ.get("PORT", "8899"))

DEFAULTS = {
    "api_key": "",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",
}


def llm_config():
    """返回 LLM 代理配置：{api_key, base_url, model}"""
    cfg = dict(DEFAULTS)
    try:
        if CONFIG_FILE.exists():
            cfg.update(json.loads(CONFIG_FILE.read_text("utf-8")))
    except Exception:
        pass
    if os.environ.get("LLM_API_KEY"):
        cfg["api_key"] = os.environ["LLM_API_KEY"]
    if os.environ.get("LLM_BASE_URL"):
        cfg["base_url"] = os.environ["LLM_BASE_URL"]
    if os.environ.get("LLM_MODEL"):
        cfg["model"] = os.environ["LLM_MODEL"]
    return cfg


def ensure_config_file():
    """首次运行时生成 backend/config.json 模板，提示用户填入密钥"""
    if not CONFIG_FILE.exists():
        try:
            CONFIG_FILE.write_text(
                json.dumps(DEFAULTS, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print("已生成后端配置文件：" + str(CONFIG_FILE))
            print("  请在其中填入 api_key（或设置环境变量 LLM_API_KEY）后重启服务。")
        except Exception as e:
            print("生成配置文件失败：" + str(e))


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    sf = DATA_DIR / "settings.json"
    if not sf.exists():
        sf.write_text("{}", encoding="utf-8")
