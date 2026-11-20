# -*- coding: utf-8 -*-
"""
Wmap - 桌面客户端启动器
PyWebView 原生窗口 + 内置 FastAPI 服务 + 系统托盘驻留

运行方式（Windows）：双击打包后的 应急保障.exe，或 python launcher.py
窗口是原生桌面窗口（Windows 上用系统 Edge WebView2 渲染），不再打开浏览器。
"""
import os
import sys
import time
import threading
import urllib.request

# 无窗口模式（PyInstaller console=False）下 stdout/stderr 为 None，
# 提前兜底，避免 uvicorn 日志写入空流崩溃
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

PORT = 8080
HEALTH_URL = f"http://127.0.0.1:{PORT}/api/health"
APP_URL = f"http://127.0.0.1:{PORT}"
# 互斥量名沿用旧版（EmergencySupportApp），避免新旧两个版本同时跑起来抢 8080 端口
MUTEX_NAME = "Local\\EmergencySupportAppMutex_wwx"
WINDOW_TITLE = "Wmap"
WINDOW_WIDTH = 1440
WINDOW_HEIGHT = 900

_window = None
_server = None
_tray_icon = None


def get_base_dir():
    if getattr(sys, "frozen", False):
        # PyInstaller 6.x onedir：配套文件在 _internal/（sys._MEIPASS）里，不在 exe 旁边
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return meipass
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


def wait_for_server(timeout=35):
    start = time.time()
    while time.time() - start < timeout:
        if is_server_ready():
            return True
        time.sleep(0.3)
    return False


def start_server():
    """在后台线程启动内置 uvicorn 服务，返回 server 对象（供关闭时用）。"""
    global _server
    import uvicorn
    from main import app
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    _server = uvicorn.Server(config)
    thread = threading.Thread(target=_server.run, daemon=True, name="wmap-server")
    thread.start()
    return _server


def stop_server():
    global _server
    if _server is not None:
        _server.should_exit = True
        _server = None


def open_ui():
    """打开应用主界面：创建 PyWebView 原生窗口并进入 GUI 循环（阻塞，直到窗口关闭）。"""
    import webview
    global _window
    _window = webview.create_window(WINDOW_TITLE, APP_URL, width=WINDOW_WIDTH, height=WINDOW_HEIGHT)
    webview.start()


def show_window():
    """托盘“打开界面”：把已有窗口带到前台（尽力而为）。"""
    global _window
    if _window is not None:
        try:
            _window.restore()
            _window.show()
        except Exception:
            pass


def quit_app():
    """托盘“退出系统”：关闭窗口，主线程随之走清理流程。"""
    global _window
    if _window is not None:
        try:
            _window.destroy()
        except Exception:
            pass


def run_tray():
    """托盘图标（跑在独立线程）。"""
    global _tray_icon
    try:
        import pystray
        from PIL import Image
    except Exception:
        return
    try:
        base_dir = get_base_dir()
        ico_path = os.path.join(base_dir, "app.ico")
        if os.path.isfile(ico_path):
            img = Image.open(ico_path)
        else:
            # 动态生成简易图标避免崩溃
            img = Image.new("RGBA", (64, 64), color=(30, 144, 255, 255))

        def on_open(icon, item):
            show_window()

        def on_quit(icon, item):
            quit_app()

        menu = pystray.Menu(
            pystray.MenuItem("打开界面", on_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出系统", on_quit)
        )
        _tray_icon = pystray.Icon("wmap", img, "Wmap (运行中)", menu)
        _tray_icon.run()
    except Exception:
        return


def stop_tray():
    global _tray_icon
    if _tray_icon is not None:
        try:
            _tray_icon.stop()
        except Exception:
            pass
        _tray_icon = None


def acquire_mutex():
    """Windows 单实例互斥量；已有实例在运行返回 False，非 Windows 返回 None（不做互斥）。"""
    if sys.platform != "win32":
        return None
    import ctypes
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return False
    return mutex


def release_mutex(mutex):
    if mutex:
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(mutex)
        except Exception:
            pass


def show_message(text, title="Wmap", error=False):
    """Windows 用消息框，其他平台打印到终端。"""
    if sys.platform == "win32":
        try:
            import ctypes
            icon = 0x10 if error else 0x40
            ctypes.windll.user32.MessageBoxW(0, text, title, icon)
            return
        except Exception:
            pass
    stream = sys.stderr if error else sys.stdout
    print(f"[{title}] {text}", file=stream)


def main():
    base_dir = get_base_dir()
    os.chdir(base_dir)

    mutex = acquire_mutex()
    if mutex is False:
        show_message("Wmap 已在运行。")
        return

    # 先确认桌面窗口组件可用，避免服务起来了窗口却打不开
    try:
        import webview  # noqa: F401
    except ImportError:
        show_message("未安装 pywebview，请先执行：pip install pywebview", error=True)
        release_mutex(mutex)
        return

    # 启动内置服务（后台线程）；若 8080 上已有服务在跑，直接复用
    if not is_server_ready():
        try:
            start_server()
        except Exception as e:
            show_message(f"启动内置服务失败：{e}", error=True)
            release_mutex(mutex)
            return
        if not wait_for_server(timeout=35):
            show_message("后台服务启动超时，请重试或检查端口占用情况。", error=True)
            stop_server()
            release_mutex(mutex)
            return

    # 托盘（独立线程）
    threading.Thread(target=run_tray, daemon=True, name="wmap-tray").start()

    # 原生窗口（阻塞主线程，直到窗口关闭）
    try:
        open_ui()
    finally:
        # 窗口关闭后的清理
        stop_tray()
        stop_server()
        release_mutex(mutex)


if __name__ == "__main__":
    main()
