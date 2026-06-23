@echo off
REM ═════════════════════════════════════════════════════════════════════════════
REM RR BILLING PRO v2.3 - Final Installer Build
REM Using Inno Setup
REM ═════════════════════════════════════════════════════════════════════════════

echo.
echo ╔════════════════════════════════════════════════════════════════════════╗
echo ║  RR BILLING PRO v2.3 - Creating Installer                            ║
echo ╚════════════════════════════════════════════════════════════════════════╝
echo.

REM Check if Inno Setup is installed
set "INNO_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if not exist "%INNO_PATH%" (
    echo ⚠ Inno Setup 6 not found at: %INNO_PATH%
    echo.
    echo Please install from: https://jrsoftware.org/isdl.php
    echo.
    echo After installation, run this script again.
    pause
    exit /b 1
)

echo ✓ Found Inno Setup: %INNO_PATH%
echo.

REM Check if .iss file exists
if not exist "RR_BILLING_PRO_v2.3.iss" (
    echo ✗ FATAL: RR_BILLING_PRO_v2.3.iss not found
    exit /b 1
)
echo ✓ Found Inno Setup script: RR_BILLING_PRO_v2.3.iss
echo.

REM Create Output directory if not exists
if not exist "Output" mkdir Output
echo ✓ Output directory ready

REM Compile installer
echo.
echo Compiling installer... (this may take a minute)
echo.

"%INNO_PATH%" "RR_BILLING_PRO_v2.3.iss"

if %errorlevel% neq 0 (
    echo.
    echo ✗ Inno Setup compilation FAILED
    pause
    exit /b 1
)

echo.
echo ╔════════════════════════════════════════════════════════════════════════╗
echo ║  ✓ Installer Created Successfully!                                    ║
echo ╚════════════════════════════════════════════════════════════════════════╝
echo.

REM List the created installer
if exist "Output\RR_BILLING_PRO_v2.3_Setup.exe" (
    for /f %%A in ('dir "Output\RR_BILLING_PRO_v2.3_Setup.exe" /s ^| find /c /v ""') do (
        echo ✓ Installer: Output\RR_BILLING_PRO_v2.3_Setup.exe
        dir "Output\RR_BILLING_PRO_v2.3_Setup.exe"
    )
) else (
    echo ✗ Installer not found in Output folder
    pause
    exit /b 1
)

echo.
echo Ready for distribution!
echo.
echo Next steps:
echo 1. Test: Run Output\RR_BILLING_PRO_v2.3_Setup.exe
echo 2. Distribute to users
echo 3. For updates: Users can use Git or check app menu
echo.
pause
