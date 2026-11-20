# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：Wmap 桌面版（PyWebView 原生窗口 + 内置 FastAPI 服务）。

在 Windows 电脑上打包（打包命令见 BUILD_WINDOWS.md）：
    pyinstaller --distpath dist_release 应急保障.spec
产物：dist_release\\应急保障\\应急保障.exe（+ static/、data/ 等配套文件）
该路径与 installer.iss 的 [Files] Source（dist_release\\应急保障\\*）一致，
所以 installer.iss 不用改。

关键点：
- main.py / app/ 直接冻进 exe（PyInstaller 会分析 launcher.py 的 import，
  把 main.py 及其依赖 numpy/pandas/fastapi 等一并打进去）。
  冻进去的 main.py 的 __file__ 会指向 _internal/main.py，
  所以 BASE_DIR（按 __file__ 定位 data/ 与 static/）在打包后仍然正确。
- static/、data/、config.json、app.ico 以数据文件形式打进包（都在 _internal/ 里）。
- config.local.json（含高德 Key）不进包，装好后按需复制到安装目录。
- 托盘图标 app.ico、默认配置 config.json 一并打进包。
"""
import os

block_cipher = None

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config.json', '.'),
        ('app.ico', '.'),
        ('static', 'static'),
        ('data', 'data'),
    ],
    hiddenimports=[
        # PyWebView 的 Windows 后端（Edge WebView2）是动态加载的，显式声明防止漏打
        'webview.platforms.edgechromium',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='应急保障',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='应急保障',
)
