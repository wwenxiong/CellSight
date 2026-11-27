# -*- coding: utf-8 -*-
"""
CellSight - 一键打包、生成更新清单 (latest.json) 与发布上传脚本。

用法示例：
  1. 仅打包并生成 latest.json（随后拖入宝塔面板网站目录）：
     python publish_release.py 1.1.0 -m "新增在线自动更新" "优化界面体验" --base-url https://your-domain.com/updates/

  2. 打包并自动通过 SCP 上传到宝塔网站目录：
     python publish_release.py 1.1.0 -m "修复若干问题" --base-url https://your-domain.com/updates/ --scp root@1.2.3.4:/www/wwwroot/your-domain.com/updates/
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

ROOT_DIR = Path(__file__).resolve().parent
VERSION_FILE = ROOT_DIR / "VERSION"
CONFIG_FILE = ROOT_DIR / "config.json"
SPEC_FILE = ROOT_DIR / "CellSight.spec"
ISS_FILE = ROOT_DIR / "installer.iss"
OUTPUT_DIR = ROOT_DIR / "installer_output"

DEFAULT_ISCC_PATHS = [
    r"C:\Users\wu_pa\AppData\Local\Programs\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def _find_iscc() -> str:
    for p in DEFAULT_ISCC_PATHS:
        if os.path.isfile(p):
            return p
    found = shutil.which("ISCC.exe") or shutil.which("iscc")
    if found:
        return found
    raise FileNotFoundError("未找到 Inno Setup 编译器 ISCC.exe，请先安装 Inno Setup 6。")


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def _resolve_base_url(cli_base_url: str) -> str:
    if cli_base_url:
        return cli_base_url.rstrip("/") + "/"
    if CONFIG_FILE.is_file():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            update_url = str(cfg.get("update_url") or "").strip()
            if update_url.endswith("/latest.json"):
                return update_url[: -len("latest.json")]
            if update_url:
                return update_url.rstrip("/") + "/"
        except Exception:
            pass
    return "https://cellsight.nelab.top/updates/"


def build_manifest(version: str, installer_path: Path, base_url: str, changelog: list, force_update: bool = False) -> dict:
    """生成客户端识别的 latest.json 版本清单。"""
    tz_cn = timezone(timedelta(hours=8))
    filename = installer_path.name
    encoded_name = quote(filename)
    return {
        "version": version,
        "force_update": bool(force_update),
        "released_at": datetime.now(tz_cn).isoformat(timespec="seconds"),
        "url": f"{base_url.rstrip('/')}/{encoded_name}",
        "sha256": _compute_sha256(installer_path),
        "size": installer_path.stat().st_size,
        "changelog": changelog or [f"发布 v{version} 更新"],
    }


def main():
    parser = argparse.ArgumentParser(description="CellSight 一键打包与发布工具")
    parser.add_argument("version", help="目标版本号，例如 1.1.0")
    parser.add_argument("-m", "--message", nargs="+", default=[], help="更新日志条目（可传多条）")
    parser.add_argument("--base-url", default="", help="宝塔更新目录公网 URL，例如 https://example.com/updates/")
    parser.add_argument("--force", action="store_true", help="标记为强制更新")
    parser.add_argument("--scp", default="", help="可选：SCP 目标路径，例如 root@ip:/www/wwwroot/site/updates/")
    parser.add_argument("--skip-build", action="store_true", help="跳过打包，仅基于已有安装包重新生成 latest.json")
    args = parser.parse_args()

    version = args.version.strip().lstrip("vV")
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        raise SystemExit(f"版本号格式无效: {args.version}（应为 X.Y.Z，例如 1.1.0）")

    # 1. 更新 VERSION
    VERSION_FILE.write_text(f"{version}\n", encoding="utf-8")
    print(f"[1/4] 已更新 VERSION -> {version}")

    installer_path = OUTPUT_DIR / f"CellSight_Setup_v{version}.exe"

    if not args.skip_build:
        # 清理旧构建残留
        release_dist = ROOT_DIR / "dist_release" / "CellSight"
        if release_dist.exists():
            shutil.rmtree(release_dist, ignore_errors=True)

        # 2. PyInstaller 打包
        print("[2/4] 正在执行 PyInstaller 打包...")
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", "dist_release", str(SPEC_FILE)],
            cwd=str(ROOT_DIR),
            check=True,
        )

        # 3. Inno Setup 编译安装包
        iscc = _find_iscc()
        print(f"[3/4] 正在使用 Inno Setup 编译安装包 ({iscc})...")
        subprocess.run(
            [iscc, f"/DMyAppVersion={version}", str(ISS_FILE)],
            cwd=str(ROOT_DIR),
            check=True,
        )
    else:
        print("[2/4] 跳过 PyInstaller 与 Inno Setup 编译")

    if not installer_path.is_file():
        raise SystemExit(f"未找到安装包产物: {installer_path}")

    # 4. 生成 latest.json
    base_url = _resolve_base_url(args.base_url)
    manifest = build_manifest(version, installer_path, base_url, args.message, force_update=args.force)
    manifest_path = OUTPUT_DIR / "latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[4/4] 已生成更新清单: {manifest_path}")
    print(f"      安装包: {installer_path} ({manifest['size']} bytes)")
    print(f"      SHA256: {manifest['sha256']}")

    if args.scp:
        print(f"[上传] 正在通过 SCP 推送到 {args.scp} ...")
        subprocess.run(["scp", str(installer_path), str(manifest_path), args.scp], check=True)
        print("[成功] 已上传至宝塔服务器！")
    else:
        print("\n下一步：请将以下两个文件上传至宝塔面板网站对应的 updates 目录：")
        print(f"  1. {installer_path}")
        print(f"  2. {manifest_path}")


if __name__ == "__main__":
    main()
