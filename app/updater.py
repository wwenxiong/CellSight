# -*- coding: utf-8 -*-
"""
版本管理与在线自动更新核心模块（纯 Python 标准库实现）。
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_DEFAULT_VERSION = "1.0.0"
_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$", re.IGNORECASE)


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_current_version() -> str:
    """从 VERSION 文件读取当前应用版本号。"""
    base_dir = _get_base_dir()
    for candidate in (base_dir / "VERSION", Path(__file__).resolve().parent.parent / "VERSION"):
        try:
            if candidate.is_file():
                text = candidate.read_text(encoding="utf-8").strip()
                if text:
                    return text.lstrip("vV")
        except Exception:
            pass
    return _DEFAULT_VERSION


def parse_version(version_str: str) -> tuple:
    """将语义化版本号解析为可比较的整数元组。"""
    if not version_str:
        return (0, 0, 0)
    cleaned = str(version_str).strip()
    m = _SEMVER_RE.match(cleaned)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    parts = re.findall(r"\d+", cleaned)
    nums = [int(p) for p in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def is_newer_version(remote_version: str, local_version: str) -> bool:
    """判断远端版本是否高于本地版本。"""
    return parse_version(remote_version) > parse_version(local_version)


def get_update_url() -> str:
    """读取更新清单 URL（优先 config.local.json，其次 config.json）。"""
    base_dir = _get_base_dir()
    roots = [base_dir]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if exe_dir not in roots:
            roots.insert(0, exe_dir)

    for root in roots:
        for fname in ("config.local.json", "config.json"):
            cfg_path = root / fname
            if cfg_path.is_file():
                try:
                    data = json.loads(cfg_path.read_text(encoding="utf-8"))
                    url = str(data.get("update_url") or "").strip()
                    if url:
                        return url
                except Exception:
                    pass
    return ""


def _compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest().lower()


class UpdateManager:
    """线程安全的客户端更新管理器。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._install_handler: Optional[Callable[[Path], None]] = None
        self._state = {
            "status": "idle",  # idle | checking | up_to_date | available | downloading | ready | installing | error
            "current_version": get_current_version(),
            "latest_version": "",
            "released_at": "",
            "changelog": [],
            "download_url": "",
            "sha256": "",
            "size": 0,
            "downloaded_bytes": 0,
            "progress": 0,
            "force_update": False,
            "installer_path": "",
            "error": "",
            "update_configured": bool(get_update_url()),
        }

    def set_install_handler(self, handler: Optional[Callable[[Path], None]]) -> None:
        """注册桌面端退出并拉起安装包的回调。"""
        self._install_handler = handler

    def get_status(self) -> dict:
        with self._lock:
            snap = dict(self._state)
            snap["changelog"] = list(self._state["changelog"])
            snap["update_configured"] = bool(get_update_url())
            return snap

    def check_update(self, update_url: Optional[str] = None, timeout: float = 6.0) -> dict:
        """请求远端 latest.json 检查是否存在新版本。"""
        target_url = (update_url or get_update_url()).strip()
        current_ver = get_current_version()

        if not target_url:
            with self._lock:
                self._state.update({
                    "status": "idle",
                    "current_version": current_ver,
                    "update_configured": False,
                    "error": "未配置更新服务器地址 (update_url)",
                })
            return self.get_status()

        with self._lock:
            if self._state["status"] in ("downloading", "installing"):
                return self.get_status()
            self._state.update({
                "status": "checking",
                "current_version": current_ver,
                "update_configured": True,
                "error": "",
            })

        try:
            req = urllib.request.Request(
                target_url,
                headers={"User-Agent": f"CellSightUpdater/{current_ver}", "Cache-Control": "no-cache"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            manifest = json.loads(raw)
            if not isinstance(manifest, dict):
                raise ValueError("更新清单格式无效")

            remote_ver = str(manifest.get("version") or "").strip().lstrip("vV")
            dl_url = str(manifest.get("url") or "").strip()
            if not remote_ver or not dl_url:
                raise ValueError("更新清单缺少 version 或 url 字段")

            changelog = manifest.get("changelog") or []
            if isinstance(changelog, str):
                changelog = [line.strip() for line in changelog.splitlines() if line.strip()]

            has_update = is_newer_version(remote_ver, current_ver)
            with self._lock:
                self._state.update({
                    "status": "available" if has_update else "up_to_date",
                    "current_version": current_ver,
                    "latest_version": remote_ver,
                    "released_at": str(manifest.get("released_at") or ""),
                    "changelog": list(changelog),
                    "download_url": dl_url,
                    "sha256": str(manifest.get("sha256") or "").strip().lower(),
                    "size": int(manifest.get("size") or 0),
                    "force_update": bool(manifest.get("force_update", False)),
                    "downloaded_bytes": 0,
                    "progress": 0,
                    "error": "",
                })
        except Exception as exc:
            logger.warning("检查更新失败: %s", exc)
            with self._lock:
                self._state.update({
                    "status": "error",
                    "error": f"检查更新失败: {exc}",
                })

        return self.get_status()

    def start_download(self) -> dict:
        """在后台线程下载新版安装包。"""
        with self._lock:
            if self._state["status"] in ("downloading", "installing"):
                return self.get_status()
            if self._state["status"] == "ready" and self._state["installer_path"]:
                if Path(self._state["installer_path"]).is_file():
                    return self.get_status()

            dl_url = self._state.get("download_url", "")
            latest_ver = self._state.get("latest_version", "")
            if not dl_url:
                self._state.update({"status": "error", "error": "缺少安装包下载地址，请先检查更新"})
                return self.get_status()

            self._state.update({
                "status": "downloading",
                "downloaded_bytes": 0,
                "progress": 0,
                "installer_path": "",
                "error": "",
            })

        threading.Thread(
            target=self._download_worker,
            args=(dl_url, latest_ver),
            daemon=True,
            name="cellsight-update-download",
        ).start()
        return self.get_status()

    def _download_worker(self, url: str, version: str) -> None:
        update_dir = Path(tempfile.gettempdir()) / "cellsight_update"
        update_dir.mkdir(parents=True, exist_ok=True)
        safe_ver = re.sub(r"[^0-9A-Za-z._-]", "_", version or "latest")
        final_path = update_dir / f"CellSight_Setup_v{safe_ver}.exe"
        part_path = update_dir / f"CellSight_Setup_v{safe_ver}.exe.part"

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": f"CellSightUpdater/{get_current_version()}"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                header_len = int(resp.headers.get("Content-Length") or 0)
                with self._lock:
                    expected_size = self._state.get("size") or header_len
                    expected_sha = self._state.get("sha256") or ""

                downloaded = 0
                with part_path.open("wb") as out:
                    while True:
                        chunk = resp.read(1024 * 128)
                        if not chunk:
                            break
                        out.write(chunk)
                        downloaded += len(chunk)
                        progress = min(99, int(downloaded * 100 / expected_size)) if expected_size > 0 else 0
                        with self._lock:
                            self._state["downloaded_bytes"] = downloaded
                            self._state["progress"] = progress

            if expected_size > 0 and downloaded != expected_size:
                raise ValueError(f"安装包大小不匹配（预期 {expected_size} 字节，实际 {downloaded} 字节）")

            if expected_sha:
                actual_sha = _compute_sha256(part_path)
                if actual_sha != expected_sha:
                    raise ValueError("安装包 SHA256 校验失败，文件可能已损坏")

            if final_path.exists():
                final_path.unlink()
            part_path.replace(final_path)

            with self._lock:
                self._state.update({
                    "status": "ready",
                    "downloaded_bytes": downloaded,
                    "progress": 100,
                    "installer_path": str(final_path),
                    "error": "",
                })
        except Exception as exc:
            logger.error("下载更新安装包失败: %s", exc)
            try:
                if part_path.exists():
                    part_path.unlink()
            except Exception:
                pass
            with self._lock:
                self._state.update({
                    "status": "error",
                    "progress": 0,
                    "error": f"下载失败: {exc}",
                })

    def install_and_restart(self) -> dict:
        """校验安装包就绪后触发静默安装（带进度条）并重启应用。"""
        with self._lock:
            installer = Path(self._state.get("installer_path") or "")
            if self._state.get("status") != "ready" or not installer.is_file():
                self._state.update({"status": "error", "error": "安装包尚未下载就绪"})
                return self.get_status()
            self._state["status"] = "installing"

        if self._install_handler is not None:
            threading.Thread(
                target=self._install_handler,
                args=(installer,),
                daemon=True,
                name="cellsight-update-install",
            ).start()
        else:
            # 非 launcher 桌面模式兜底：直接拉起安装包
            launch_installer(installer)

        return self.get_status()


def launch_installer(installer_path: Path) -> None:
    """使用 Inno Setup /SILENT 参数拉起安装包（显示简洁安装进度条）。"""
    cmd = [
        str(installer_path),
        "/SILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CLOSEAPPLICATIONS",
        "/FORCECLOSEAPPLICATIONS",
    ]
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
        )
    subprocess.Popen(cmd, close_fds=True, creationflags=creationflags)


update_manager = UpdateManager()
