# -*- coding: utf-8 -*-
"""
start.py · 一键启动脚本（Python 版后端）
用法：双击或在命令行执行  python start.py
首次运行会自动安装依赖（fastapi / uvicorn / httpx）。
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQ = ROOT / "backend" / "requirements.txt"


def ensure_deps():
    try:
        import fastapi  # noqa: F401
        import httpx  # noqa: F401
        import uvicorn  # noqa: F401
        return True
    except ImportError:
        pass
    print("[init] 首次运行，正在安装后端依赖（fastapi / uvicorn / httpx）…")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(REQ)])
        return True
    except Exception as e:
        print("[init] 依赖安装失败：" + str(e))
        print("[init] 请手动执行：python -m pip install -r backend/requirements.txt")
        return False


if __name__ == "__main__":
    if not ensure_deps():
        sys.exit(1)
    # 保证后端包可导入（无论从哪个目录启动）
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)

    from backend import config

    config.ensure_dirs()
    config.ensure_config_file()

    import uvicorn

    print("=" * 52)
    print("  iteris-agent · Python 后端启动")
    print("  访问地址：http://127.0.0.1:%d" % config.PORT)
    print("  数据目录：%s（多项目隔离）" % config.DATA_DIR)
    print("  关闭窗口或按 Ctrl+C 停止服务")
    print("=" * 52)
    uvicorn.run("backend.main:app", host="127.0.0.1", port=config.PORT, log_level="info")
