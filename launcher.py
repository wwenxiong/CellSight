# -*- coding: utf-8 -*-
"""
应急保障 - 桌面客户端启动器
集成单实例互斥、自动拉起后台服务、Edge独立视窗及系统托盘驻留
"""
import os
import sys
import time
import socket
import ctypes
import subprocess
import threading
import urllib.request

PORT = 8080
HEALTH_URL = f"http://127.0.0.1:{PORT}/api/health"
APP_URL = f"http://127.0.0.1:{PORT}"
MUTEX_NAME = "Local\\EmergencySupportAppMutex_wwx"

def get_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

def is_server_ready():
    try:
        handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(handler)
        req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "HealthCheck"})
        with opener.open(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        # 兼容未包含 /api/health 的旧版，尝试请求根路径
        try:
            handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(handler)
            req = urllib.request.Request(APP_URL, headers={"User-Agent": "HealthCheck"})
            with opener.open(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False

def wait_for_server(backend_proc=None, timeout=35):
    start = time.time()
    while time.time() - start < timeout:
        if backend_proc and backend_proc.poll() is not None:
            return False
        if is_server_ready():
            return True
        time.sleep(0.3)
    return False

def find_edge_path():
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None

def open_ui():
    """打开应用主界面（优先使用 Edge 独立窗口 App 模式，若无则使用系统默认浏览器）"""
    edge_path = find_edge_path()
    if edge_path:
        try:
            subprocess.Popen([
                edge_path,
                f"--app={APP_URL}",
                "--window-size=1440,900"
            ])
            return
        except Exception:
            pass

    import webbrowser
    webbrowser.open(APP_URL)

def run_tray(backend_proc, base_dir, mutex):
    """托盘图标运行管理器"""
    icon_obj = None
    try:
        import pystray
        from PIL import Image

        ico_path = os.path.join(base_dir, "app.ico")
        if os.path.isfile(ico_path):
            img = Image.open(ico_path)
        else:
            # 动态生成简易图标避免崩溃
            img = Image.new("RGBA", (64, 64), color=(30, 144, 255, 255))

        def on_open(icon, item):
            open_ui()

        def on_quit(icon, item):
            icon.stop()

        menu = pystray.Menu(
            pystray.MenuItem("打开界面", on_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出系统", on_quit)
        )

        icon_obj = pystray.Icon("emergency_support", img, "应急保障系统 (运行中)", menu)
        icon_obj.run()
    except Exception:
        # 若 pystray 失败，退化为守护等待后台进程
        if backend_proc:
            backend_proc.wait()
    finally:
        # 退出清理
        if backend_proc and backend_proc.poll() is None:
            try:
                backend_proc.terminate()
                backend_proc.wait(timeout=3)
            except Exception:
                try:
                    backend_proc.kill()
                except Exception:
                    pass
        if mutex:
            try:
                ctypes.windll.kernel32.CloseHandle(mutex)
            except Exception:
                pass

def main():
    base_dir = get_base_dir()
    os.chdir(base_dir)

    # 单实例互斥量检查
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_error = kernel32.GetLastError()
    ERROR_ALREADY_EXISTS = 183

    if last_error == ERROR_ALREADY_EXISTS:
        # 已有实例在运行，直接唤起前端界面并退出本次启动
        if not is_server_ready():
            wait_for_server(timeout=10)
        open_ui()
        if mutex:
            kernel32.CloseHandle(mutex)
        sys.exit(0)

    # 首次启动：准备启动后台
    runtime_python = os.path.join(base_dir, "runtime", "python.exe")
    runtime_pythonw = os.path.join(base_dir, "runtime", "pythonw.exe")

    if os.path.isfile(runtime_python):
        python_cmd = runtime_python
    elif os.path.isfile(runtime_pythonw):
        python_cmd = runtime_pythonw
    else:
        python_cmd = "python"

    backend_proc = None
    log_fp = None

    if not is_server_ready():
        run_script = os.path.join(base_dir, "run.py")
        startupinfo = None
        creationflags = 0
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW

        log_path = os.path.join(base_dir, "server.log")
        try:
            log_fp = open(log_path, "a", encoding="utf-8")
        except Exception:
            log_fp = subprocess.DEVNULL

        backend_proc = subprocess.Popen(
            [python_cmd, run_script, "--no-browser"],
            cwd=base_dir,
            stdin=subprocess.DEVNULL,
            stdout=log_fp,
            stderr=log_fp,
            startupinfo=startupinfo,
            creationflags=creationflags
        )

        if not wait_for_server(backend_proc=backend_proc, timeout=35):
            err_detail = ""
            try:
                if os.path.isfile(log_path):
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        if lines:
                            err_detail = "\n\n日志详情:\n" + "".join(lines[-5:])
            except Exception:
                pass

            msg = f"后台服务启动超时，请重试或检查端口占用情况。{err_detail}"
            ctypes.windll.user32.MessageBoxW(0, msg, "应急保障", 0x10)
            if backend_proc:
                try:
                    backend_proc.kill()
                except Exception:
                    pass
            if mutex:
                kernel32.CloseHandle(mutex)
            return

    # 打开客户端主界面
    open_ui()

    # 进入托盘驻留管理循环
    run_tray(backend_proc, base_dir, mutex)

    if log_fp and log_fp != subprocess.DEVNULL:
        try:
            log_fp.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
