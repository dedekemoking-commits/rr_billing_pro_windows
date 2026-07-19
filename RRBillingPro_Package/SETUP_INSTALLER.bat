@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul

cls
color 0A
echo.
echo ╔════════════════════════════════════════════════════════════════════════╗
echo ║                   RR BILLING PRO v2.3 - INSTALLATION                   ║
echo ║           Sistem Billing Warnet ^& Penyewaan TV                        ║
echo ╚════════════════════════════════════════════════════════════════════════╝
echo.

REM Check Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ✗  Jalankan sebagai Administrator!
    echo    Klik kanan -^> "Run as administrator"
    pause
    exit /b 1
)

set INSTALL_PATH=C:\RRBillingPro

echo ✓ Lokasi instalasi: %INSTALL_PATH%
echo.

if exist "%INSTALL_PATH%" (
    echo ℹ Folder sudah ada. Backup data lama...
    if exist "%INSTALL_PATH%\rr_billing_config.json" (
        set BACKUP_TIME=%date:~10,4%%date:~4,2%%date:~7,2%_%time:~0,2%%time:~3,2%
        set BACKUP_TIME=!BACKUP_TIME: =0!
        copy "%INSTALL_PATH%\rr_billing_config.json" "%INSTALL_PATH%\rr_billing_config.json.backup.!BACKUP_TIME!" > nul
        echo ✓ Config dibackup
    )
)

mkdir "%INSTALL_PATH%" 2>nul
cd /d "%~dp0"

echo ────────────────────────────────────────────────────────────────────────
echo  COPY FILES
echo ────────────────────────────────────────────────────────────────────────
echo.

if exist "RRBILLINGPRO.exe" (
    copy "RRBILLINGPRO.exe" "%INSTALL_PATH%\RRBILLINGPRO.exe" > nul && echo ✓ RRBILLINGPRO.exe
) else (
    echo ✗ RRBILLINGPRO.exe tidak ditemukan!
    pause
    exit /b 1
)

if exist "_internal" (
    if exist "%INSTALL_PATH%\_internal" rmdir /s /q "%INSTALL_PATH%\_internal"
    robocopy "_internal" "%INSTALL_PATH%\_internal" /E /NFL /NDL /NJH /NJS /NP > nul
    echo ✓ _internal\ (dependencies)
)

if not exist "%INSTALL_PATH%\rr_billing_config.json" (
    if exist "rr_billing_config.json" (
        copy "rr_billing_config.json" "%INSTALL_PATH%\rr_billing_config.json" > nul && echo ✓ rr_billing_config.json
    )
) else (
    echo ℹ rr_billing_config.json sudah ada, tidak ditimpa
)

if exist "rr_billing_license.json" (
    if not exist "%INSTALL_PATH%\rr_billing_license.json" (
        copy "rr_billing_license.json" "%INSTALL_PATH%\rr_billing_license.json" > nul && echo ✓ rr_billing_license.json
    )
)

if exist "logo.ico" (
    copy "logo.ico" "%INSTALL_PATH%\logo.ico" > nul && echo ✓ logo.ico
)
if exist "logo.png" (
    copy "logo.png" "%INSTALL_PATH%\logo.png" > nul && echo ✓ logo.png
)
if exist "logo_billingpro.b64" (
    copy "logo_billingpro.b64" "%INSTALL_PATH%\logo_billingpro.b64" > nul
)
if exist "lock_screen.jpg" (
    copy "lock_screen.jpg" "%INSTALL_PATH%\lock_screen.jpg" > nul
)
if exist "update_pubkey.pem" (
    copy "update_pubkey.pem" "%INSTALL_PATH%\update_pubkey.pem" > nul
)
if exist "android_tv_certs" (
    if not exist "%INSTALL_PATH%\android_tv_certs" (
        robocopy "android_tv_certs" "%INSTALL_PATH%\android_tv_certs" /E /NFL /NDL /NJH /NJS /NP > nul
    )
)

echo.
echo ────────────────────────────────────────────────────────────────────────
echo  MEMBUAT SHORTCUT
echo ────────────────────────────────────────────────────────────────────────
echo.

powershell -NoProfile -Command ^
"$WshShell = New-Object -ComObject WScript.Shell; ^
$lnk = $WshShell.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\RR Billing Pro.lnk'); ^
$lnk.TargetPath = '%INSTALL_PATH%\RRBILLINGPRO.exe'; ^
$lnk.WorkingDirectory = '%INSTALL_PATH%'; ^
$lnk.IconLocation = '%INSTALL_PATH%\logo.ico'; ^
$lnk.Save(); ^
Write-Host '✓ Shortcut Desktop dibuat'" 2>nul

echo.
echo ════════════════════════════════════════════════════════════════════════
echo  INSTALASI SELESAI!
echo ════════════════════════════════════════════════════════════════════════
echo.
echo Aplikasi terinstal di: %INSTALL_PATH%
echo.
echo Jalankan sekarang? (1=Ya / 2=Tutup)
set /p CHOICE="Pilih (1/2): "

if "%CHOICE%"=="1" (
    start "" "%INSTALL_PATH%\RRBILLINGPRO.exe"
    echo Aplikasi dimulai...
    timeout /t 2 /nobreak
)

echo.
echo Terima kasih!
pause
exit /b 0
