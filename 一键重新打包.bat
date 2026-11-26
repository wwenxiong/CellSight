@echo off
chcp 65001 >nul
echo ===================================================
echo             CellSight - 一键安装包生成工具 (wwx)
echo ===================================================
echo 正在同步最新代码与静态资源...

python -c "
import os, shutil
release_dir = r'dist_release\CellSight'
os.makedirs(release_dir, exist_ok=True)
for fn in ['main.py', 'run.py', 'app.ico', 'launcher.py']:
    if os.path.exists(fn):
        shutil.copy2(fn, os.path.join(release_dir, fn))
for dn in ['app', 'data', 'static']:
    t = os.path.join(release_dir, dn)
    shutil.copytree(dn, t, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
"

echo 正在编译生成标准 Windows 安装包...
"C:\Users\wu_pa\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer.iss

echo.
echo ===================================================
echo [成功] 安装包已生成:
echo 路径: installer_output\CellSight_Setup_v1.0.exe
echo ===================================================
pause
