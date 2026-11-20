@echo off
chcp 65001 >nul
title Wmap 启动器
cd /d "%~dp0"
echo 正在启动 Wmap 桌面客户端...
start "" pythonw launcher.py
