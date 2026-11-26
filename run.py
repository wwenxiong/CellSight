# -*- coding: utf-8 -*-
"""
LTE/NR 应急事件无线保障处置系统 - 原生桌面客户端入口
可以直接使用 python run.py 运行，或在支持的系统上双击该脚本。
全局默认启动专业原生桌面窗口（基于 Edge WebView2），不再通过浏览器打开。
"""

import os
import sys

# 保护无控制台环境 (避免 pythonw 或无窗口模式下 sys.stdout 为 None 导致 logging 崩溃)
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")


def main():
    # 若显式传入 --server-only、--headless 或 --web，则以纯后端 Web 服务模式运行
    if any(arg in sys.argv for arg in ("--server-only", "--headless", "--web")):
        import uvicorn
        port = 8080
        host = "0.0.0.0"
        url = f"http://localhost:{port}"

        print("=" * 66)
        print("      📡 LTE/NR 应急事件无线保障处置系统 - 后台服务模式")
        print(f"      本地访问地址: {url}")
        print("=" * 66)

        reload = "--dev" in sys.argv
        uvicorn.run("main:app", host=host, port=port, log_level="info", access_log=False, reload=reload)
    else:
        # 全局默认：启动原生桌面窗口应用程序
        import launcher
        launcher.main()


if __name__ == "__main__":
    main()
