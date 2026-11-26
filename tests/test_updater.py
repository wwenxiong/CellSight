# -*- coding: utf-8 -*-
import hashlib
import http.server
import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.updater import UpdateManager, get_current_version, is_newer_version, parse_version
from main import app


def test_version_parsing_and_comparison():
    assert parse_version("1.0.0") == (1, 0, 0)
    assert parse_version("v1.2.10") == (1, 2, 10)
    assert is_newer_version("1.1.0", "1.0.0") is True
    assert is_newer_version("1.0.10", "1.0.2") is True
    assert is_newer_version("1.0.0", "1.0.0") is False
    assert is_newer_version("0.9.9", "1.0.0") is False
    assert get_current_version() == "1.0.0"


def _start_static_server(directory: Path):
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, format, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    return server, server.server_address[1]


def test_update_check_download_verify_and_install(tmp_path):
    payload = b"fake-inno-setup-binary-content-for-test" * 100
    exe_path = tmp_path / "应急保障_Setup_v9.9.9.exe"
    exe_path.write_bytes(payload)
    sha256 = hashlib.sha256(payload).hexdigest()

    server, port = _start_static_server(tmp_path)
    try:
        manifest = {
            "version": "9.9.9",
            "force_update": False,
            "url": f"http://127.0.0.1:{port}/%E5%BA%94%E6%80%A5%E4%BF%9D%E9%9A%9C_Setup_v9.9.9.exe",
            "sha256": sha256,
            "size": len(payload),
            "changelog": ["新增自动更新", "优化性能"],
        }
        (tmp_path / "latest.json").write_text(json.dumps(manifest), encoding="utf-8")

        mgr = UpdateManager()
        st = mgr.check_update(update_url=f"http://127.0.0.1:{port}/latest.json")
        assert st["status"] == "available"
        assert st["latest_version"] == "9.9.9"
        assert st["changelog"] == ["新增自动更新", "优化性能"]

        mgr.start_download()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            st = mgr.get_status()
            if st["status"] in ("ready", "error"):
                break
            time.sleep(0.05)

        assert st["status"] == "ready"
        assert st["progress"] == 100
        assert Path(st["installer_path"]).is_file()

        called = []
        mgr.set_install_handler(lambda p: called.append(p))
        st_install = mgr.install_and_restart()
        assert st_install["status"] == "installing"
        time.sleep(0.1)
        assert len(called) == 1
        assert called[0].name == "应急保障_Setup_v9.9.9.exe"
    finally:
        server.shutdown()
        server.server_close()


def test_update_download_rejects_bad_sha256(tmp_path):
    payload = b"corrupted-or-tampered-bytes"
    (tmp_path / "setup.exe").write_bytes(payload)
    server, port = _start_static_server(tmp_path)
    try:
        manifest = {
            "version": "9.9.9",
            "url": f"http://127.0.0.1:{port}/setup.exe",
            "sha256": "0" * 64,
            "size": len(payload),
        }
        (tmp_path / "latest.json").write_text(json.dumps(manifest), encoding="utf-8")

        mgr = UpdateManager()
        assert mgr.check_update(update_url=f"http://127.0.0.1:{port}/latest.json")["status"] == "available"
        mgr.start_download()

        deadline = time.time() + 5.0
        while time.time() < deadline:
            st = mgr.get_status()
            if st["status"] in ("ready", "error"):
                break
            time.sleep(0.05)

        assert st["status"] == "error"
        assert "SHA256" in st["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_fastapi_update_endpoints():
    client = TestClient(app)
    res_health = client.get("/api/health")
    assert res_health.status_code == 200
    assert res_health.json()["version"] == get_current_version()

    res_status = client.get("/api/update/status")
    assert res_status.status_code == 200
    assert res_status.json()["current_version"] == get_current_version()
