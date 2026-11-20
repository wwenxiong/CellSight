# -*- coding: utf-8 -*-
"""
LTE/NR 应急事件无线保障处置系统 - Python 原生免批处理启动入口
可以直接使用 python run.py 运行，或在支持的系统上直接双击该脚本。
"""

import os
import sys

# 保护无控制台环境 (避免 pythonw 或无窗口模式下 sys.stdout 为 None 导致 uvicorn logging 崩溃)
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import time
import threading
import webbrowser
import uvicorn

def auto_open_browser(url: str, delay: float = 1.5):
    """延时自动打开默认浏览器"""
    time.sleep(delay)
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"[提示] 请手动在浏览器中打开: {url} ({e})")

def main():
    port = 8080
    host = "0.0.0.0"
    url = f"http://localhost:{port}"

    print("=" * 66)
    print("      📡 LTE/NR 应急事件无线保障处置系统 - 原生启动服务")
    print(f"      本地访问地址: {url}")
    print("      提示: 已尝试自动为您唤起系统默认浏览器...")
    print("=" * 66)

    # 启动后台线程唤起浏览器（仅当未指定 --no-browser 时）
    if "--no-browser" not in sys.argv:
        threading.Thread(target=auto_open_browser, args=(url, 1.5), daemon=True).start()

    # 是否开启热更新开发模式
    reload = "--dev" in sys.argv

    # 启动 Web 服务
    uvicorn.run("main:app", host=host, port=port, log_level="info", access_log=False, reload=reload)

if __name__ == "__main__":
    main()
