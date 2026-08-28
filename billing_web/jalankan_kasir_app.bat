@echo off
chcp 65001 >nul
title RR Billing Pro - Aplikasi Kasir
cd /d %~dp0
where python >nul 2>nul
if errorlevel 1 (
  echo Python tidak ditemukan. Install Python lalu jalankan lagi.
  pause
  exit /b 1
)
python -c "import webview" 2>nul || (
  echo Menginstall pywebview ^(pertama kali^)...
  python -m pip install --no-index --find-links "%~dp0wheels" pywebview >nul 2>&1 || python -m pip install pywebview
)
echo Membuka jendela aplikasi kasir... ^(tanpa jendela cmd^)
start "" pythonw kasir_window.py
