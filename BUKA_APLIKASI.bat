@echo off
title RR BILLING PRO — Sistem Billing Rental TV & PS
color 0B

:: ── Jalankan dari folder yang sama ───────────────────────────────────────────
cd /d "%~dp0"

:: ── Pastikan ADB & Git di PATH ──────────────────────────────────────────────
set "PATH=%PATH%;%LOCALAPPDATA%\Android\platform-tools;C:\Program Files\Git\cmd;C:\Program Files\Git\bin"

where python >nul 2>&1
if %errorlevel% neq 0 (
    set PYTHON=python3
) else (
    set PYTHON=python
)

%PYTHON% main.py

if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Aplikasi berhenti dengan error.
    pause
)
