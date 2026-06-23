@echo off
REM ═════════════════════════════════════════════════════════════════════════════
REM RR BILLING PRO v2.3 - Build & Package Script
REM ═════════════════════════════════════════════════════════════════════════════

echo.
echo ╔════════════════════════════════════════════════════════════════════════╗
echo ║  RR BILLING PRO v2.3 - Preparing Build                               ║
echo ╚════════════════════════════════════════════════════════════════════════╝
echo.

REM Check if logo.png exists
if not exist "logo.png" (
    echo ✗ FATAL: logo.png not found in current directory
    exit /b 1
)
echo ✓ Logo found: logo.png

REM Check if main.spec exists
if not exist "main.spec" (
    echo ✗ FATAL: main.spec not found
    exit /b 1
)
echo ✓ Build spec found: main.spec

REM Clean previous builds
echo.
echo Cleaning previous builds...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist
echo ✓ Clean complete

REM Build with PyInstaller
echo.
echo Building with PyInstaller...
python -m PyInstaller main.spec
if %errorlevel% neq 0 (
    echo ✗ PyInstaller build failed!
    exit /b 1
)
echo ✓ PyInstaller build successful

REM Copy logo to dist
echo.
echo Copying assets to dist folder...
copy logo.png dist\logo.png >nul
if errorlevel 1 (
    echo ✗ Failed to copy logo.png
    exit /b 1
)
echo ✓ Logo copied to dist\

REM Copy config files if they don't exist in dist
if not exist "dist\rr_billing_config.json" (
    copy rr_billing_config.json dist\ >nul
    echo ✓ Config file copied
)

if not exist "dist\rr_billing_license.json" (
    copy rr_billing_license.json dist\ >nul
    echo ✓ License file copied
)

if not exist "dist\update_pubkey.pem" (
    copy update_pubkey.pem dist\ >nul
    echo ✓ Update key copied
)

REM Verify all required files exist in dist
echo.
echo Verifying build files...
set missing=0
if not exist "dist\main.exe" (
    echo ✗ main.exe not found in dist
    set missing=1
)
if not exist "dist\logo.png" (
    echo ✗ logo.png not found in dist
    set missing=1
)
if %missing% equ 1 (
    echo ✗ Some files are missing!
    exit /b 1
)
echo ✓ All required files present

REM List dist folder
echo.
echo Build artifacts in dist\ folder:
dir dist\ /s

echo.
echo ╔════════════════════════════════════════════════════════════════════════╗
echo ║  ✓ Build preparation complete!                                        ║
echo ║  Next: Run Inno Setup with RR_BILLING_PRO_v2.3.iss                    ║
echo ╚════════════════════════════════════════════════════════════════════════╝
echo.
pause
