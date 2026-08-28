@echo off
chcp 65001 >nul
title Stop RR Billing Web Kasir
echo Menghentikan server web kasir ^(port 8000^)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do (
    taskkill /f /pid %%a >nul 2>&1 && echo   Dihentikan PID %%a
)
echo Selesai.
pause
