@echo off
title RR Billing Pro - Update Client Warnet v2.4
setlocal enabledelayedexpansion

REM ============================================================
REM  UPDATE_CLIENT.bat — perbarui client yang SUDAH terinstall
REM  di C:\RRBillingClient tanpa mengubah config per-PC.
REM
REM  Cara pakai (Run as Administrator):
REM    UPDATE_CLIENT.bat                -> update + pertahankan config
REM    UPDATE_CLIENT.bat --keep-config  -> sama (default, config aman)
REM    UPDATE_CLIENT.bat --overwrite-config -> timpa config dengan yang baru
REM
REM  Aman dijalankan berkali-kali (idempotent).
REM  Tanpa sc/reg/netsh/relaunch cmd /k  -> bebas dari "invalid argument/option".
REM ============================================================

set "CLIENT_DIR=C:\RRBillingClient"
set "SRC=%~dp0"
set "SERVICE_NAME=RRBillingClientService"
set "OVERWRITE=0"
if /i "%~1"=="--overwrite-config" set "OVERWRITE=1"

for %%I in ("%CLIENT_DIR%") do if not exist "%%~I\" mkdir "%%~I"

REM ---------------- CEK ADMIN ----------------
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Jalankan sebagai Administrator!
    echo  Klik kanan file ini -^> "Run as Administrator"
    echo.
    pause
    exit /b 1
)

echo ============================================
echo   RR Billing Pro - Updater Client Warnet
echo   Sumber : %SRC%
echo   Target : %CLIENT_DIR%
echo ============================================
echo.

REM ---------------- [1/6] PASTIKAN FILE SUMBER LENGKAP ----------------
echo [1/6] Memeriksa file sumber...
for %%F in (BillingClientService.exe BillingLockScreenUI.exe BillingClientApp.exe INSTALL_CLIENT.bat) do (
    if not exist "%SRC%%%F" (
        echo   [MISSING] %%F  ^<- file tidak ada di folder ini!
        echo   Jalankan dari folder hasil ekstrak yang LENGKAP.
        echo.
        pause
        exit /b 1
    )
)
echo   OK - file sumber lengkap.
echo.

REM ---------------- [2/6] STOP SERVICE + KILL PROSES ----------------
echo [2/6] Menghentikan service & proses lama (buka kunci file)...
net stop %SERVICE_NAME% >nul 2>&1
taskkill /f /im BillingClientApp.exe >nul 2>&1
taskkill /f /im BillingLockScreenUI.exe >nul 2>&1
timeout /t 2 /nobreak >nul
echo   OK - proses dihentikan.
echo.

REM ---------------- [3/6] SALIN FILE BARU ----------------
echo [3/6] Menyalin file baru ke %CLIENT_DIR%...

REM Hapus MotW di SUMBER dulu: copy /Y ikut menyalin tanda "dari internet"
REM (Zone.Identifier ADS) dari file sumber ke tujuan.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Path '%SRC%*' -File -Include *.exe,*.dll,*.bat,*.cmd,*.vbs,*.ps1 | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1

:COPY_START
set COPY_FAIL=0
copy /Y "%SRC%BillingClientService.exe"   "%CLIENT_DIR%\" >nul || set COPY_FAIL=1
copy /Y "%SRC%BillingLockScreenUI.exe"    "%CLIENT_DIR%\" >nul || set COPY_FAIL=1
copy /Y "%SRC%BillingClientApp.exe"       "%CLIENT_DIR%\" >nul || set COPY_FAIL=1
copy /Y "%SRC%INSTALL_CLIENT.bat"         "%CLIENT_DIR%\" >nul || set COPY_FAIL=1

if "%COPY_FAIL%"=="1" (
    echo   WARNA: file masih terkunci. Coba lagi dalam 3 detik...
    timeout /t 3 /nobreak >nul
    net stop %SERVICE_NAME% >nul 2>&1
    taskkill /f /im BillingClientApp.exe >nul 2>&1
    taskkill /f /im BillingLockScreenUI.exe >nul 2>&1
    timeout /t 2 /nobreak >nul
    goto :COPY_START
)

REM Logo lockscreen (opsional - salah satu format saja yang tersedia)
if exist "%SRC%lockscreen_logo.png" copy /Y "%SRC%lockscreen_logo.png" "%CLIENT_DIR%\" >nul 2>&1
if exist "%SRC%lockscreen_logo.jpg" copy /Y "%SRC%lockscreen_logo.jpg" "%CLIENT_DIR%\" >nul 2>&1
if exist "%SRC%lockscreen_logo.jpeg" copy /Y "%SRC%lockscreen_logo.jpeg" "%CLIENT_DIR%\" >nul 2>&1

REM Config: default DIPERTAHANKAN (IP server / client_id / pc_id per PC)
if "%OVERWRITE%"=="1" (
    if exist "%SRC%rr_billing_config.json" copy /Y "%SRC%rr_billing_config.json" "%CLIENT_DIR%\" >nul
    echo   INFO : rr_billing_config.json DITIMPA dengan config paket.
) else (
    echo   INFO : rr_billing_config.json DIPERTAHANKAN (config per-PC aman).
)
echo   OK - file disalin.
echo.

REM ---------------- [3b] WOL SETUP + UNBLOCK (fix popup "Open File") ----------------
echo [3b/6] Wake-on-LAN setup + unblock file...
REM Hapus tanda "dari internet" (MotW) -> hilangkan popup Open File saat boot/login
REM Pakai -Path dengan wildcard ('dir\*') agar -Include benar-benar memfilter.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Path '%CLIENT_DIR%\*' -File -Include *.exe,*.dll,*.bat,*.cmd,*.vbs,*.ps1 | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1
REM Aktifkan Wake-on-Magic-Packet di adapter jaringan (Win8/10/11)
powershell -NoProfile -Command "Get-NetAdapter -ErrorAction SilentlyContinue | Set-NetAdapterPowerManagement -WakeOnMagicPacket Enabled -WakeOnPattern Enabled -ErrorAction SilentlyContinue" >nul 2>&1
REM Fallback powercfg (semua versi Windows, termasuk 7)
for /f "delims=" %%N in ('wmic nic where "NetEnabled=true" get Name /value 2^>nul') do (
    set "WLDEV=%%N"
    if not "!WLDEV:Name=!"=="!WLDEV!" (
        set "WLDEV=!WLDEV:*Name=!"
        powercfg -deviceenablewake "!WLDEV!" >nul 2>&1
    )
)
echo   [WOL] Adapter yang siap menerima bangun (wake_armed):
powercfg /devicequery wake_armed
echo.

REM Verifikasi MotW: hitung file yang MASIH bertanda "dari internet"
set "MOTW_TMP=%TEMP%\rr_motw_left.txt"
del "%MOTW_TMP%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Path '%CLIENT_DIR%\*' -File -Include *.exe,*.dll,*.bat | Where-Object { $s = Get-Item -LiteralPath $_.FullName -Stream * -ErrorAction SilentlyContinue; $s -and ($s.Stream -contains 'Zone.Identifier') } | Select-Object -ExpandProperty Name | Out-File -LiteralPath '%MOTW_TMP%' -Encoding ascii" >nul 2>&1
set MOTW_LEFT=0
if exist "%MOTW_TMP%" (
    for /f "usebackq delims=" %%Z in ("%MOTW_TMP%") do set /a MOTW_LEFT+=1
)
del "%MOTW_TMP%" >nul 2>&1
if not "%MOTW_LEFT%"=="0" (
    echo.
    echo   ERROR: %MOTW_LEFT% file MASIH bertanda "dari internet"!
    echo   Popup "Open File - Security Warning" akan MUNCUL saat login.
    echo   Hapus manual: klik kanan file -^> Properties -^> Unblock, lalu ulangi.
    echo.
    pause
    exit /b 1
)
echo   [MOTW] OK - semua file BERSIH dari tanda internet (popup tidak akan muncul).
echo.

REM ---------------- [4/6] START SERVICE ----------------
echo [4/6] Menjalankan service...
net start %SERVICE_NAME% >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: Service tidak bisa start!
    echo.
    echo   ------ Isi log service ------
    if exist "%CLIENT_DIR%\rr_billing_client_service.log" (
        type "%CLIENT_DIR%\rr_billing_client_service.log"
    ) else (
        echo   belum ada log. Jalankan "%CLIENT_DIR%\BillingClientService.exe -c" untuk debug.
    )
    echo.
    pause
    exit /b 1
)
echo   OK - service RUNNING.
echo.

REM ---------------- [5/6] START TRAY APP ----------------
echo [5/6] Menjalankan tray app...
tasklist /fi "IMAGENAME eq BillingClientApp.exe" 2>nul | findstr /i "BillingClientApp.exe" >nul
if %errorlevel% neq 0 (
    start "" "%CLIENT_DIR%\BillingClientApp.exe"
    echo   OK - BillingClientApp dijalankan (ikon di kanan bawah).
) else (
    echo   OK - BillingClientApp sudah berjalan.
)
echo.

REM ---------------- [6/6] VERIFIKASI ----------------
echo [6/6] Verifikasi...
echo   Service : sc query %SERVICE_NAME%  ^(seharusnya RUNNING^)
echo   Log     : type %CLIENT_DIR%\rr_billing_client_service.log
echo   Harus ada baris: "AUTH successful."  bila terhubung ke server.
echo   Bila "AUTH failed" pastikan server_host/port/client_id benar.
echo.
echo ============================================
echo   UPDATE SELESAI!
echo ============================================
pause
exit /b 0