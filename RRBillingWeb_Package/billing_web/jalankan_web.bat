@echo off
chcp 65001 >nul
title RR Billing Pro - Web Kasir (localhost:8000)
cd /d %~dp0
where python >nul 2>nul
if errorlevel 1 (
  echo Python tidak ditemukan. Install Python lalu jalankan lagi.
  pause
  exit /b 1
)
echo Menjalankan server web kasir... ^(berjalan di background, tanpa jendela cmd^)
python -c "import flask" 2>nul || (
  echo Menginstall Flask ^(pertama kali^)...
  python -m pip install --no-index --find-links "%~dp0wheels" flask >nul 2>&1 || python -m pip install flask
)
start "" pythonw server.py