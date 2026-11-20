# PowerShell 启动脚本
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   LTE/NR 应急事件无线保障处置系统 (PowerShell 启动)" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan

Start-Process "http://localhost:8080"
python main.py
