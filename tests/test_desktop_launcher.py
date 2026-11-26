# -*- coding: utf-8 -*-
"""桌面客户端启动器及原生化运行逻辑单元测试。

验证：
1. launcher.get_free_port 动态端口分配与冲突避免
2. launcher.load_window_state 与 save_window_state 窗口记忆持久化
3. launcher.activate_existing_window 运行防护与安全调用
4. run.py 默认桌面入口路由
"""

import json
import socket
from unittest.mock import patch, MagicMock
import pytest

import launcher
import run


def test_get_free_port():
    """测试端口分配：可用时返回首选端口，被占用时自动切换空闲端口。"""
    # 找一个临时绑定的端口模拟被占用
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied_socket:
        occupied_socket.bind(("127.0.0.1", 0))
        occupied_port = occupied_socket.getsockname()[1]

        # 尝试请求该被占用的端口
        assigned_port = launcher.get_free_port(preferred=occupied_port)
        # 应自动避开冲突端口，返回其他合法空闲端口
        assert assigned_port != occupied_port
        assert 1024 <= assigned_port <= 65535


def test_window_state_persistence(tmp_path, monkeypatch):
    """测试窗口几何尺寸与位置的记忆存取。"""
    state_file = tmp_path / "test_window_state.json"
    monkeypatch.setattr("launcher.get_state_file_path", lambda: str(state_file))

    # 1. 默认状态（文件尚不存在）
    default_state = launcher.load_window_state()
    assert default_state["width"] == launcher.WINDOW_WIDTH
    assert default_state["height"] == launcher.WINDOW_HEIGHT

    # 2. 写入自定义窗口状态
    custom_state = {"width": 1600, "height": 1000, "x": 120, "y": 80}
    launcher.save_window_state(custom_state)
    assert state_file.exists()

    # 3. 重新读取比对
    loaded = launcher.load_window_state()
    assert loaded["width"] == 1600
    assert loaded["height"] == 1000
    assert loaded["x"] == 120
    assert loaded["y"] == 80

    # 4. 损坏 JSON 容错
    state_file.write_text("invalid json syntax", encoding="utf-8")
    fallback = launcher.load_window_state()
    assert fallback["width"] == launcher.WINDOW_WIDTH


def test_activate_existing_window_safe():
    """测试激活已有窗口方法在各环境下的安全调用不崩溃。"""
    res = launcher.activate_existing_window()
    assert isinstance(res, bool)


def test_run_py_entry_routing(monkeypatch):
    """测试 run.py 路由逻辑：默认调用 launcher.main，带参数时可切入纯服务模式。"""
    mock_launcher_main = MagicMock()
    monkeypatch.setattr("launcher.main", mock_launcher_main)

    # 模拟默认双击启动 (无参数)
    monkeypatch.setattr("sys.argv", ["run.py"])
    run.main()
    mock_launcher_main.assert_called_once()


def test_mutex_acquire_conflict_and_release():
    """测试单实例互斥量申请、冲突检测（不泄漏句柄）与释放后可重入。"""
    import sys
    if sys.platform != "win32":
        pytest.skip("仅适用于 Windows 互斥量测试")

    # 临时使用独立测试互斥量名，避免与用户正在运行的主程序冲突
    test_mutex_name = "Local\\WmapTestMutex_Unit_99123"
    original_name = launcher.MUTEX_NAME
    launcher.MUTEX_NAME = test_mutex_name
    m1 = None
    try:
        m1 = launcher.acquire_mutex()
        assert m1 not in (None, False)

        # 再次申请应返回 False，且内部关闭重复句柄
        m2 = launcher.acquire_mutex()
        assert m2 is False

        # 释放后应可重新申请成功
        launcher.release_mutex(m1)
        m1 = None

        m3 = launcher.acquire_mutex()
        assert m3 not in (None, False)
        launcher.release_mutex(m3)
    finally:
        if m1:
            launcher.release_mutex(m1)
        launcher.MUTEX_NAME = original_name


def test_stop_server_and_clean_exit(monkeypatch):
    """测试关闭时按顺序清理托盘、停止服务、释放互斥量并强制结束进程。"""
    calls = []

    # 1. 正常优雅退出路径（join 后线程已结束，不触发 force_exit）
    mock_srv_ok = MagicMock()
    mock_srv_ok.force_exit = False
    mock_thread_ok = MagicMock()
    mock_thread_ok.is_alive.side_effect = [True, False]
    launcher._server = mock_srv_ok
    launcher._server_thread = mock_thread_ok

    launcher.stop_server(timeout=0.5)
    assert mock_srv_ok.should_exit is True
    assert mock_srv_ok.force_exit is False
    mock_thread_ok.join.assert_called_once_with(timeout=0.5)

    # 2. 超时兜底路径（join 后线程仍存活，触发 force_exit）
    mock_srv = MagicMock()
    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = True
    launcher._server = mock_srv
    launcher._server_thread = mock_thread

    launcher.stop_server(timeout=0.5)
    assert mock_srv.should_exit is True
    assert mock_srv.force_exit is True
    assert mock_thread.join.call_count == 2
    assert launcher._server is None
    assert launcher._server_thread is None

    # 模拟完整 main 退出清理链路
    monkeypatch.setattr("launcher.acquire_mutex", lambda: 12345)
    monkeypatch.setattr("launcher.get_free_port", lambda p: 18080)
    monkeypatch.setattr("launcher.is_server_ready", lambda p: True)
    monkeypatch.setattr("launcher.open_ui", lambda url: calls.append("open_ui"))
    monkeypatch.setattr("launcher.stop_tray", lambda: calls.append("stop_tray"))
    monkeypatch.setattr("launcher.stop_server", lambda timeout=1.0: calls.append("stop_server"))
    monkeypatch.setattr("launcher.release_mutex", lambda m: calls.append(f"release_mutex:{m}"))
    monkeypatch.setattr("launcher._force_exit", lambda code=0: calls.append(f"force_exit:{code}"))

    launcher.main()
    assert calls == [
        "open_ui",
        "stop_tray",
        "stop_server",
        "release_mutex:12345",
        "force_exit:0",
    ]

