@echo off
chcp 65001 >nul
title CellSight 桌面客户端
cd /d "%~dp0"
echo 正在启动 CellSight 桌面客户端...
start "" pythonw launcher.py
