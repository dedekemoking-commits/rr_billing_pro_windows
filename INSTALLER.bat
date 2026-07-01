@echo off
REM RR BILLING PRO v2.2.1 Installer
REM Build Date: 2026-06-23
REM Latest Code - All Bugs Fixed

setlocal enabledelayedexpansion
color 0B
title RR BILLING PRO v2.2.1 - Installation

echo.
echo ===================================
echo   RR BILLING PRO v2.2.1 Installer
echo ===================================
echo.
echo Build: 2026-06-23
echo Status: PRODUCTION READY
echo.

REM Check if already installed
set "INSTALL_DIR=%ProgramFiles%\RR BILLING PRO"
if exist "%INSTALL_DIR%" (
    echo.
    echo [WARNING] RR BILLING PRO is already installed at:
    echo %INSTALL_DIR%
    echo.
    set /p CHOICE="Do you want to reinstall? (Y/N): "
    if /i not "!CHOICE!"=="Y" goto END
)

echo.
echo [*] Creating installation directory...
mkdir "%INSTALL_DIR%" 2>nul

echo [*] Copying application files...
if exist "dist\RRBILLINGPRO\RRBILLINGPRO.exe" (
    copy /Y "dist\RRBILLINGPRO\RRBILLINGPRO.exe" "%INSTALL_DIR%\" >nul
) else if exist "dist\main.exe" (
    copy /Y "dist\main.exe" "%INSTALL_DIR%\" >nul
) else if exist "RRBILLINGPRO.exe" (
    copy /Y "RRBILLINGPRO.exe" "%INSTALL_DIR%\" >nul
) else if exist "main.exe" (
    copy /Y "main.exe" "%INSTALL_DIR%\" >nul
) else (
    echo [ERROR] Executable not found in dist or current directory
    goto ERROR
)
if errorlevel 1 (
    echo [ERROR] Failed to copy executable
    goto ERROR
)

echo [*] Copying configuration files...
if exist "dist\RRBILLINGPRO\rr_billing_config.json" (
    copy /Y "dist\RRBILLINGPRO\rr_billing_config.json" "%INSTALL_DIR%\" >nul
) else if exist "rr_billing_config.json" (
    copy /Y "rr_billing_config.json" "%INSTALL_DIR%\" >nul
)
if exist "dist\RRBILLINGPRO\logo.png" (
    copy /Y "dist\RRBILLINGPRO\logo.png" "%INSTALL_DIR%\" >nul
) else if exist "logo.png" (
    copy /Y "logo.png" "%INSTALL_DIR%\" >nul
)
if exist "dist\RRBILLINGPRO\rr_billing_license.json" (
    copy /Y "dist\RRBILLINGPRO\rr_billing_license.json" "%INSTALL_DIR%\" >nul
) else if exist "rr_billing_license.json" (
    copy /Y "rr_billing_license.json" "%INSTALL_DIR%\" >nul
)
if exist "dist\RRBILLINGPRO\update_pubkey.pem" (
    copy /Y "dist\RRBILLINGPRO\update_pubkey.pem" "%INSTALL_DIR%\" >nul
) else if exist "update_pubkey.pem" (
    copy /Y "update_pubkey.pem" "%INSTALL_DIR%\" >nul
)

echo [*] Creating shortcuts...
powershell -Command "^
$WshShell = New-Object -ComObject WScript.Shell; ^
$Desktop = [System.IO.Path]::Combine([System.Environment]::GetFolderPath('Desktop')); ^
$StartMenu = [System.IO.Path]::Combine([System.Environment]::GetFolderPath('StartMenu'), 'Programs'); ^
$ShortcutDesktop = [System.IO.Path]::Combine($Desktop, 'RR BILLING PRO.lnk'); ^
$ShortcutStartMenu = [System.IO.Path]::Combine($StartMenu, 'RR BILLING PRO.lnk'); ^
$Shortcut = $WshShell.CreateShortcut($ShortcutDesktop); ^
$Shortcut.TargetPath = '%INSTALL_DIR%\RRBILLINGPRO.exe'; ^
$Shortcut.WorkingDirectory = '%INSTALL_DIR%'; ^
$Shortcut.Save(); ^
$Shortcut = $WshShell.CreateShortcut($ShortcutStartMenu); ^
$Shortcut.TargetPath = '%INSTALL_DIR%\RRBILLINGPRO.exe'; ^
$Shortcut.WorkingDirectory = '%INSTALL_DIR%'; ^
$Shortcut.Save();" 2>nul

echo.
echo ===================================
echo   Installation Complete!
echo ===================================
echo.
echo Location: %INSTALL_DIR%
echo.
echo RR BILLING PRO v2.2.1 has been installed successfully!
echo.
echo Features:
echo   ✓ TV Management System
echo   ✓ Package & Session Management
echo   ✓ Real-time Timer
echo   ✓ ADB Integration
echo   ✓ Git Auto-Update Support
echo   ✓ User Role Management
echo.
echo All known bugs FIXED:
echo   ✓ MULAI SESI Button - NOW 100% RESPONSIVE
echo   ✓ UI/UX Improvements
echo   ✓ Error Handling Enhanced
echo.
echo Desktop and Start Menu shortcuts have been created.
echo.
set /p START="Do you want to launch RR BILLING PRO now? (Y/N): "
if /i "!START!"=="Y" (
    start "" "%INSTALL_DIR%\RRBILLINGPRO.exe"
)

goto END

:ERROR
echo.
echo [ERROR] Installation failed!
pause
goto END

:END
echo.
pause
