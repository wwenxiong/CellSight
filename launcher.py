# -*- coding: utf-8 -*-
"""
Wmap - 专业桌面客户端启动器
PyWebView 原生独立窗口 + 内置 FastAPI 后台服务 + 系统托盘驻留 + 窗口记忆 + 动态端口

运行方式（Windows）：
  1. 双击 启动Wmap.bat (无黑框启动)
  2. python launcher.py 或 python run.py
  3. 双击打包生成的 应急保障.exe
"""
import os
import sys
import json
import time
import socket
import threading
import urllib.request

# 无控制台模式（pythonw 或 PyInstaller console=False）下 stdout/stderr 为 None，
# 提前兜底重定向到 devnull，避免 uvicorn/logging 写入空流抛出异常
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

DEFAULT_PORT = 8080
MUTEX_NAME = "Local\\EmergencySupportAppMutex_wwx"
WINDOW_TITLE = "wmap"
WINDOW_WIDTH = 1440
WINDOW_HEIGHT = 900
STATE_FILE_NAME = "window_state.json"

_window = None
_server = None
_server_thread = None
_tray_icon = None
_active_port = DEFAULT_PORT


def get_base_dir() -> str:
    """获取程序运行根目录（兼容源码运行与 PyInstaller 打包目录）"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return meipass
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_free_port(preferred: int = DEFAULT_PORT) -> int:
    """获取可用空闲端口（优先使用首选端口，被占用时自动分配随机端口）"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get_state_file_path() -> str:
    return os.path.join(get_base_dir(), STATE_FILE_NAME)


def load_window_state() -> dict:
    """读取上次关闭时记忆的窗口几何尺寸与位置"""
    try:
        p = get_state_file_path()
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {"width": WINDOW_WIDTH, "height": WINDOW_HEIGHT}


def save_window_state(state: dict) -> None:
    """持久化保存当前窗口状态"""
    try:
        p = get_state_file_path()
        with open(p, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def is_server_ready(port: int) -> bool:
    """检测指定端口上的后台服务是否已就绪"""
    health_url = f"http://127.0.0.1:{port}/api/health"
    app_url = f"http://127.0.0.1:{port}/"
    try:
        handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(handler)
        req = urllib.request.Request(health_url, headers={"User-Agent": "HealthCheck"})
        with opener.open(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        try:
            handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(handler)
            req = urllib.request.Request(app_url, headers={"User-Agent": "HealthCheck"})
            with opener.open(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False


def wait_for_server(port: int, timeout: float = 35.0) -> bool:
    """轮询等待后台服务启动完成"""
    start = time.time()
    while time.time() - start < timeout:
        if is_server_ready(port):
            return True
        time.sleep(0.3)
    return False


def start_server(port: int):
    """在后台守护线程启动内置 uvicorn 服务"""
    global _server, _server_thread
    import uvicorn
    from main import app
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    _server = uvicorn.Server(config)
    _server_thread = threading.Thread(target=_server.run, daemon=True, name="wmap-server")
    _server_thread.start()
    return _server


def stop_server(timeout: float = 1.5):
    """安全停止后台服务：先优雅退出避免 lifespan CancelledError，超时再强制退出"""
    global _server, _server_thread
    srv = _server
    _server = None
    th = _server_thread
    _server_thread = None

    if srv is not None:
        try:
            srv.should_exit = True
        except Exception:
            pass

    if th is not None and th.is_alive():
        th.join(timeout=timeout)
        if th.is_alive() and srv is not None:
            try:
                srv.force_exit = True
            except Exception:
                pass
            th.join(timeout=0.2)


def show_window():
    """把已有窗口置于前台"""
    global _window
    if _window is not None:
        try:
            _window.restore()
            _window.show()
        except Exception:
            pass


def quit_app():
    """退出桌面应用程序"""
    global _window
    if _window is not None:
        try:
            _window.destroy()
        except Exception:
            pass


def run_tray():
    """在独立线程运行 Windows 任务栏系统托盘图标"""
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
            img = Image.open(ico_path).convert("RGBA")
        else:
            img = Image.new("RGBA", (64, 64), color=(0, 113, 227, 255))

        def on_open(icon, item):
            show_window()

        def on_quit(icon, item):
            quit_app()

        menu = pystray.Menu(
            pystray.MenuItem("打开主界面", on_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出系统", on_quit)
        )
        _tray_icon = pystray.Icon("wmap", img, "wmap (运行中)", menu)
        _tray_icon.run()
    except Exception:
        return


def stop_tray():
    """停止系统托盘"""
    global _tray_icon
    icon = _tray_icon
    _tray_icon = None
    if icon is not None:
        try:
            icon.visible = False
        except Exception:
            pass
        try:
            icon.stop()
        except Exception:
            pass


def acquire_mutex():
    """Windows 单实例互斥量；已有实例在运行返回 False，非 Windows 返回 None"""
    if sys.platform != "win32":
        return None
    import ctypes
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        if mutex:
            kernel32.CloseHandle(mutex)
        return False
    return mutex


def release_mutex(mutex):
    if mutex:
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(mutex)
        except Exception:
            pass


def activate_existing_window() -> bool:
    """当检测到已有进程运行时，将已有桌面窗口激活唤醒至前台"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if not hwnd:
            def _enum_cb(h, _):
                nonlocal hwnd
                length = user32.GetWindowTextLengthW(h)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(h, buf, length + 1)
                    if "wmap" in buf.value.lower():
                        hwnd = h
                        return False
                return True

            cb_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(cb_type(_enum_cb), 0)

        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


def show_message(text: str, title: str = "Wmap", error: bool = False):
    """弹出原生对话框提示"""
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


def _apply_win32_window_icon():
    """在 Windows 下为 PyWebView 窗口设置左上角标题栏图标与任务栏图标（替换默认 Python 图标）"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ico_path = os.path.join(get_base_dir(), "app.ico")
        if not os.path.exists(ico_path):
            return
        user32 = ctypes.windll.user32
        hwnd = 0
        for _ in range(25):
            hwnd = user32.FindWindowW(None, WINDOW_TITLE)
            if hwnd:
                break
            time.sleep(0.1)
        if not hwnd:
            return
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        WM_SETICON = 0x0080
        hicon_small = user32.LoadImageW(0, ico_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        hicon_big = user32.LoadImageW(0, ico_path, IMAGE_ICON, 48, 48, LR_LOADFROMFILE)
        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, 0, hicon_small)
        if hicon_big:
            user32.SendMessageW(hwnd, WM_SETICON, 1, hicon_big)
    except Exception:
        pass


class _WindowApi:
    """暴露给前端无边框顶栏的原生窗口控制接口"""
    def __init__(self):
        self._maximized = False
        self._restore_rect = None

    def minimize(self):
        if _window:
            _window.minimize()

    def toggle_maximize(self):
        if not _window:
            return False
        if sys.platform != "win32":
            try:
                if self._maximized:
                    _window.restore()
                    self._maximized = False
                else:
                    _window.maximize()
                    self._maximized = True
            except Exception:
                pass
            return self._maximized

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, WINDOW_TITLE)
            if not hwnd:
                return self._maximized

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            hmon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
            work = mi.rcWork

            SWP_NOZORDER = 0x0004
            SWP_SHOWWINDOW = 0x0040

            # 若当前已处于工作区最大化状态，则还原到上次保存的窗口位置与尺寸
            is_at_work_area = (
                abs(rect.left - work.left) <= 2
                and abs(rect.top - work.top) <= 2
                and abs(rect.right - work.right) <= 2
                and abs(rect.bottom - work.bottom) <= 2
            )
            if self._maximized or is_at_work_area:
                if self._restore_rect:
                    rx, ry, rw, rh = self._restore_rect
                else:
                    rx, ry, rw, rh = 120, 80, WINDOW_WIDTH, WINDOW_HEIGHT
                user32.SetWindowPos(hwnd, 0, rx, ry, rw, rh, SWP_NOZORDER | SWP_SHOWWINDOW)
                self._maximized = False
            else:
                self._restore_rect = (
                    rect.left,
                    rect.top,
                    max(800, rect.right - rect.left),
                    max(600, rect.bottom - rect.top),
                )
                user32.SetWindowPos(
                    hwnd, 0,
                    work.left, work.top,
                    work.right - work.left, work.bottom - work.top,
                    SWP_NOZORDER | SWP_SHOWWINDOW,
                )
                self._maximized = True
        except Exception:
            pass
        return self._maximized

    def close(self):
        if _window:
            _window.destroy()


def open_ui(url: str):
    """创建并显示 PyWebView 原生桌面窗口"""
    import webview
    global _window

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("wmap.desktop.app")
        except Exception:
            pass

    # 允许 WebView2 内置原生下载通道
    webview.settings['ALLOW_DOWNLOADS'] = True

    # 恢复窗口位置与尺寸
    saved_state = load_window_state()
    width = saved_state.get("width", WINDOW_WIDTH)
    height = saved_state.get("height", WINDOW_HEIGHT)
    x = saved_state.get("x")
    y = saved_state.get("y")

    _window = webview.create_window(
        WINDOW_TITLE,
        url,
        width=width,
        height=height,
        x=x,
        y=y,
        min_size=(1024, 680),
        frameless=True,
        easy_drag=False,
        js_api=_WindowApi(),
        confirm_close=False,
        text_select=True
    )

    def on_closed():
        try:
            if _window:
                save_window_state({
                    "width": getattr(_window, "width", WINDOW_WIDTH),
                    "height": getattr(_window, "height", WINDOW_HEIGHT),
                    "x": getattr(_window, "x", None),
                    "y": getattr(_window, "y", None),
                })
        except Exception:
            pass
        stop_tray()

    _window.events.closed += on_closed
    webview.start(func=_apply_win32_window_icon)


def _force_exit(code: int = 0):
    """清理完成后强制结束进程，避免 CLR/WebView2 后台线程阻塞导致僵尸进程残留"""
    os._exit(code)


def main():
    base_dir = get_base_dir()
    os.chdir(base_dir)

    mutex = acquire_mutex()
    if mutex is False:
        if not activate_existing_window():
            show_message("Wmap 桌面客户端已在运行中。")
        return

    try:
        import webview  # noqa: F401
    except ImportError:
        show_message("未安装 pywebview 桌面组件，请执行：pip install pywebview", error=True)
        release_mutex(mutex)
        return

    # 动态检测可用端口
    global _active_port
    _active_port = get_free_port(DEFAULT_PORT)
    app_url = f"http://127.0.0.1:{_active_port}"

    # 注册自动更新安装钩子：优雅释放锁与服务后拉起安装包并退出旧进程
    from app.updater import update_manager, launch_installer

    def _on_install_update(installer_path):
        time.sleep(0.35)
        try:
            quit_app()
        except Exception:
            pass
        stop_tray()
        stop_server(timeout=1.0)
        release_mutex(mutex)
        try:
            launch_installer(installer_path)
        finally:
            _force_exit(0)

    update_manager.set_install_handler(_on_install_update)

    # 启动后台服务
    if not is_server_ready(_active_port):
        try:
            start_server(_active_port)
        except Exception as e:
            show_message(f"启动内置服务失败：{e}", error=True)
            release_mutex(mutex)
            return

        if not wait_for_server(_active_port, timeout=35):
            show_message("后台服务启动超时，请重试或检查端口。", error=True)
            stop_server()
            release_mutex(mutex)
            return

    # 启动托盘图标（独立守护线程）
    threading.Thread(target=run_tray, daemon=True, name="wmap-tray").start()

    # 后台静默检测一次更新（不阻塞界面启动）
    threading.Thread(
        target=update_manager.check_update,
        daemon=True,
        name="wmap-auto-update-check",
    ).start()

    # 原生桌面窗口运行（阻塞主线程，直到窗口关闭）
    try:
        open_ui(app_url)
    finally:
        stop_tray()
        stop_server(timeout=1.0)
        release_mutex(mutex)
    _force_exit(0)


if __name__ == "__main__":
    main()
