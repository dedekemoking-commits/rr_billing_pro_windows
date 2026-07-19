@echo off
title RR Billing Pro - Install Client Warnet
setlocal enabledelayedexpansion

echo ========================================
echo  RR Billing Pro v2.3 — Install Client
echo ========================================
echo.

REM Check Admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Jalankan sebagai Administrator!
    echo Klik kanan file ini ^> "Run as Administrator"
    pause
    exit /b 1
)

set SCRIPT_DIR=%~dp0

REM ── Install Windows Service ──
echo [1/4] Menginstall Windows Service...
"%SCRIPT_DIR%BillingClientService.exe" -i
if %errorLevel% neq 0 (
    echo ERROR: Gagal install service!
    pause
    exit /b 1
)
echo OK

REM ── Start Service ──
echo [2/4] Menjalankan Service...
net start RRBillingClientService
if %errorLevel% neq 0 (
    echo WARNING: Service tidak bisa start. Cek konfigurasi server.
) else (
    echo OK
)

REM ── Config ──
echo [3/4] Konfigurasi...
if not exist "%SCRIPT_DIR%rr_billing_config.json" (
    echo WARNING: rr_billing_config.json tidak ditemukan.
    echo Buat file config dengan format:
    echo {
    echo   "server_host": "IP_SERVER",
    echo   "server_port": 5000,
    echo   "client_id": "WARNET_01",
    echo   "password": "admin123"
    echo }
) else (
    echo File config ditemukan.
)

REM ── Auto-start Tray App ──
echo [4/4] Menambahkan Tray App ke Startup...
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
if exist "%STARTUP_DIR%" (
    copy /Y "%SCRIPT_DIR%BillingClientApp.exe" "%STARTUP_DIR%\RRBillingClientApp.exe" >nul
    echo OK - Tray app akan auto-start saat login.
) else (
    echo WARNING: Folder startup tidak ditemukan.
)

echo.
echo ========================================
echo  INSTALLASI SELESAI!
echo.
echo  Langkah selanjutnya:
echo  1. Edit rr_billing_config.json dengan
echo     IP server billing warnet anda
echo  2. Restart service:
echo     net stop RRBillingClientService
echo     net start RRBillingClientService
echo  3. Jalankan BillingClientApp.exe
echo     (atau reboot PC)
echo ========================================
echo.
echo  Untuk cek status:
echo    sc query RRBillingClientService
echo.
echo  Untuk uninstall:
echo    net stop RRBillingClientService
echo    BillingClientService.exe -u
echo.
pause
