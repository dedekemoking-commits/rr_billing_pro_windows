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

set "BUILD_SPEC=RRBILLINGPRO.spec"
set "DIST_DIR=dist\RRBILLINGPRO"
set "EXE_NAME=RRBILLINGPRO.exe"

REM Check if build spec exists
if not exist "%BUILD_SPEC%" (
    echo ✗ FATAL: %BUILD_SPEC% not found
    exit /b 1
)
echo ✓ Build spec found: %BUILD_SPEC%

REM Clean previous builds
echo.
echo Cleaning previous builds...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist
echo ✓ Clean complete

REM Build with PyInstaller
echo.
echo Building with PyInstaller...
python -m PyInstaller "%BUILD_SPEC%"
if %errorlevel% neq 0 (
    echo ✗ PyInstaller build failed!
    exit /b 1
)
echo ✓ PyInstaller build successful

if not exist "%DIST_DIR%" (
    echo ✗ Build output folder not found: %DIST_DIR%
    exit /b 1
)

REM Ensure required runtime files exist in output folder
echo.
echo Ensuring required runtime files in %DIST_DIR%...
if not exist "%DIST_DIR%\logo.png" copy logo.png "%DIST_DIR%\logo.png" >nul
if not exist "%DIST_DIR%\rr_billing_config.json" copy rr_billing_config.json "%DIST_DIR%\" >nul
if not exist "%DIST_DIR%\rr_billing_license.json" copy rr_billing_license.json "%DIST_DIR%\" >nul
if not exist "%DIST_DIR%\update_pubkey.pem" copy update_pubkey.pem "%DIST_DIR%\" >nul

REM Verify all required files exist
echo.
echo Verifying build files...
set missing=0
if not exist "%DIST_DIR%\%EXE_NAME%" (
    echo ✗ %EXE_NAME% not found in %DIST_DIR%
    set missing=1
)
if not exist "%DIST_DIR%\logo.png" (
    echo ✗ logo.png not found in %DIST_DIR%
    set missing=1
)
if not exist "%DIST_DIR%\rr_billing_config.json" (
    echo ✗ rr_billing_config.json not found in %DIST_DIR%
    set missing=1
)
if not exist "%DIST_DIR%\rr_billing_license.json" (
    echo ✗ rr_billing_license.json not found in %DIST_DIR%
    set missing=1
)
if not exist "%DIST_DIR%\update_pubkey.pem" (
    echo ✗ update_pubkey.pem not found in %DIST_DIR%
    set missing=1
)
if %missing% equ 1 (
    echo ✗ Some files are missing!
    exit /b 1
)
echo ✓ All required files present

REM List dist folder
echo.
echo Build artifacts in %DIST_DIR%\ folder:
dir "%DIST_DIR%\" /s

echo.
echo ╔════════════════════════════════════════════════════════════════════════╗
echo ║  ✓ Build preparation complete!                                        ║
echo ║  Next: Run Inno Setup with inno_build\RR_BILLING_PRO_V2.3.1.iss       ║
echo ╚════════════════════════════════════════════════════════════════════════╝
echo.
pause
