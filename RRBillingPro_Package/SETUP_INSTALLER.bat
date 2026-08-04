@echo off
REM ============================================================================
REM  RR BILLING PRO - INSTALASI DAN SETUP LENGKAP
REM ============================================================================
REM  Script ini akan:
REM  1. Extract atau copy files ke lokasi instalasi
REM  2. Setup database dan konfigurasi awal
REM  3. Create shortcuts di Desktop dan Start Menu
REM  4. Launch aplikasi setelah instalasi selesai
REM ============================================================================

setlocal enabledelayedexpansion
chcp 65001 > nul

cls
color 0A
echo.
echo ╔════════════════════════════════════════════════════════════════════════╗
echo ║                   RR BILLING PRO - INSTALLATION v2.3                    ║
echo ║                   Sistem Billing Warnet & Penyewaan TV                  ║
echo ╚════════════════════════════════════════════════════════════════════════╝
echo.

REM Check if running as Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ✗ ERROR: Script ini harus dijalankan sebagai Administrator
    echo.
    echo Silakan:
    echo 1. Klik kanan file ini
    echo 2. Pilih "Run as administrator"
    echo.
    pause
    exit /b 1
)

REM Define installation paths
set INSTALL_DRIVE=%SystemDrive%
set INSTALL_PATH=%INSTALL_DRIVE%\RRBillingPro
set SHORTCUT_DESKTOP=%USERPROFILE%\Desktop
set SHORTCUT_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs

echo ✓ Menjalankan sebagai Administrator
echo ✓ Lokasi instalasi: %INSTALL_PATH%
echo.
echo ────────────────────────────────────────────────────────────────────────
echo  TAHAP 1: MEMBUAT FOLDER INSTALASI
echo ────────────────────────────────────────────────────────────────────────
echo.

if exist "%INSTALL_PATH%" (
    echo ℹ Folder sudah ada. Backup data lama...
    if exist "%INSTALL_PATH%\rr_billing_config.json" (
        set BACKUP_TIME=%date:~10,4%%date:~4,2%%date:~7,2%_%time:~0,2%%time:~3,2%
        set BACKUP_TIME=!BACKUP_TIME: =0!
        copy "%INSTALL_PATH%\rr_billing_config.json" "%INSTALL_PATH%\rr_billing_config.json.backup.!BACKUP_TIME!" > nul
        echo ✓ Backup config: rr_billing_config.json.backup.!BACKUP_TIME!
    )
)

mkdir "%INSTALL_PATH%" 2>nul

REM Copy files from package
echo.
echo ────────────────────────────────────────────────────────────────────────
echo  TAHAP 2: COPY FILES KE FOLDER INSTALASI
echo ────────────────────────────────────────────────────────────────────────
echo.

cd /d "%~dp0"

if exist "RRBILLINGPRO.exe" (
    copy "RRBILLINGPRO.exe" "%INSTALL_PATH%\RRBILLINGPRO.exe" > nul && echo ✓ RRBILLINGPRO.exe
) else (
    echo ✗ ERROR: RRBILLINGPRO.exe tidak ditemukan di folder instalasi
    pause
    exit /b 1
)

if exist "RRBILLINGCLIENT.exe" (
    copy "RRBILLINGCLIENT.exe" "%INSTALL_PATH%\RRBILLINGCLIENT.exe" > nul && echo ✓ RRBILLINGCLIENT.exe
)

if exist "rr_billing_config.json" (
    if not exist "%INSTALL_PATH%\rr_billing_config.json" (
        copy "rr_billing_config.json" "%INSTALL_PATH%\rr_billing_config.json" > nul && echo ✓ rr_billing_config.json
    ) else (
        echo ℹ Config file sudah ada, tidak ditimpa
    )
)

if exist "logo.ico" (
    copy "logo.ico" "%INSTALL_PATH%\logo.ico" > nul && echo ✓ logo.ico
)

if exist "logo.png" (
    copy "logo.png" "%INSTALL_PATH%\logo.png" > nul && echo ✓ logo.png
)

if exist "README.txt" (
    copy "README.txt" "%INSTALL_PATH%\README.txt" > nul && echo ✓ README.txt
)

echo.
echo ────────────────────────────────────────────────────────────────────────
echo  TAHAP 3: MEMBUAT SHORTCUTS
echo ────────────────────────────────────────────────────────────────────────
echo.

REM Create Desktop shortcuts using PowerShell (more reliable than VBS)
powershell -NoProfile -Command ^
"$WshShell = New-Object -ComObject WScript.Shell; ^
$lnk = $WshShell.CreateShortcut('%SHORTCUT_DESKTOP%\RR Billing Pro.lnk'); ^
$lnk.TargetPath = '%INSTALL_PATH%\RRBILLINGPRO.exe'; ^
$lnk.WorkingDirectory = '%INSTALL_PATH%'; ^
$lnk.IconLocation = '%INSTALL_PATH%\logo.ico'; ^
$lnk.Save(); ^
Write-Host '✓ Shortcut created: Desktop\RR Billing Pro.lnk'" 2>nul || (
    echo ℹ Shortcut dengan PowerShell gagal, skip
)

REM Create Start Menu folder
if not exist "%SHORTCUT_MENU%\RR Billing Pro" mkdir "%SHORTCUT_MENU%\RR Billing Pro"

REM Create Start Menu shortcuts using PowerShell
powershell -NoProfile -Command ^
"$WshShell = New-Object -ComObject WScript.Shell; ^
$lnk = $WshShell.CreateShortcut('%SHORTCUT_MENU%\RR Billing Pro\RR Billing Pro.lnk'); ^
$lnk.TargetPath = '%INSTALL_PATH%\RRBILLINGPRO.exe'; ^
$lnk.WorkingDirectory = '%INSTALL_PATH%'; ^
$lnk.IconLocation = '%INSTALL_PATH%\logo.ico'; ^
$lnk.Save()" 2>nul || (
    echo ℹ Start Menu shortcut gagal, skip
)

echo ✓ Shortcuts dibuat

echo.
echo ────────────────────────────────────────────────────────────────────────
echo  TAHAP 4: VERIFIKASI INSTALASI
echo ────────────────────────────────────────────────────────────────────────
echo.

set ERROR_COUNT=0

if not exist "%INSTALL_PATH%\RRBILLINGPRO.exe" (
    echo ✗ RRBILLINGPRO.exe tidak ditemukan
    set /a ERROR_COUNT+=1
)

if not exist "%INSTALL_PATH%\rr_billing_config.json" (
    echo ✗ rr_billing_config.json tidak ditemukan
    set /a ERROR_COUNT+=1
)

if %ERROR_COUNT% equ 0 (
    echo ✓ Semua file terinstal dengan benar
) else (
    echo ✗ Ada %ERROR_COUNT% file yang tidak lengkap
    pause
    exit /b 1
)

echo.
echo ════════════════════════════════════════════════════════════════════════
echo  INSTALASI SELESAI!
echo ════════════════════════════════════════════════════════════════════════
echo.
echo Aplikasi telah diinstal di: %INSTALL_PATH%
echo.
echo Pilihan Anda:
echo   1. Jalankan RR Billing Pro sekarang
echo   2. Tutup
echo.

set /p CHOICE="Pilih (1/2): "

if "%CHOICE%"=="1" (
    start "" "%INSTALL_PATH%\RRBILLINGPRO.exe"
    echo Aplikasi dimulai...
    timeout /t 2 /nobreak
)

echo.
echo Terima kasih telah menggunakan RR Billing Pro!
echo.
pause
exit /b 0
