@echo off
REM ════════════════════════════════════════════════════════════════════════════════
REM   CONVERT ZIP TO RAR - RRBILLING PACKAGE CONVERTER
REM   
REM   Petunjuk: Jalankan script ini di folder yang berisi .zip files
REM   Pastikan WinRAR sudah terinstall di C:\Program Files\WinRAR\
REM   
REM ════════════════════════════════════════════════════════════════════════════════

SETLOCAL ENABLEDELAYEDEXPANSION
cd /d "%~dp0"

color 0A
cls

echo.
echo ╔════════════════════════════════════════════════════════════════════════════════╗
echo ║                                                                                ║
echo ║         RRBILLING ZIP to RAR CONVERTER - Powered by WinRAR                    ║
echo ║                                                                                ║
echo ╚════════════════════════════════════════════════════════════════════════════════╝
echo.

REM Check if WinRAR is installed
if not exist "C:\Program Files\WinRAR\rar.exe" (
    color 0C
    echo ERROR: WinRAR not found!
    echo.
    echo Please install WinRAR from: https://www.rarlab.com/rar_add.htm
    echo.
    echo Default installation path: C:\Program Files\WinRAR\
    echo.
    pause
    exit /b 1
)

color 0A
echo [OK] WinRAR found at: C:\Program Files\WinRAR\rar.exe
echo.

REM Check for zip files
if not exist "RRBILLINGPRO.zip" if not exist "RRBILLINGCLIENT.zip" (
    color 0C
    echo ERROR: No ZIP files found in current directory!
    echo.
    echo Expected files:
    echo   - RRBILLINGPRO.zip
    echo   - RRBILLINGCLIENT.zip
    echo.
    echo Current directory: %cd%
    echo.
    pause
    exit /b 1
)

echo ════════════════════════════════════════════════════════════════════════════════
echo CONVERSION PROCESS STARTING...
echo ════════════════════════════════════════════════════════════════════════════════
echo.

set "WINRAR=C:\Program Files\WinRAR\rar.exe"
set SUCCESS=0
set FAILED=0

REM Convert RRBILLINGPRO.zip
if exist "RRBILLINGPRO.zip" (
    echo [1] Processing: RRBILLINGPRO.zip
    echo     Extracting...
    
    if exist "RRBILLINGPRO" (
        rmdir /s /q "RRBILLINGPRO" >nul 2>&1
    )
    
    cd /d "%cd%"
    powershell -Command "Expand-Archive -Path '.\RRBILLINGPRO.zip' -DestinationPath '.\' -Force" >nul 2>&1
    
    if exist "RRBILLINGPRO" (
        echo     Creating RAR archive...
        "%WINRAR%" a -r -ep1 -m5 "RRBILLINGPRO.rar" "RRBILLINGPRO\" >nul 2>&1
        
        if exist "RRBILLINGPRO.rar" (
            echo     ✓ Success! Created: RRBILLINGPRO.rar
            set /a SUCCESS+=1
            
            REM Optional: delete source ZIP and folder
            REM del "RRBILLINGPRO.zip"
            REM rmdir /s /q "RRBILLINGPRO"
            
        ) else (
            echo     ✗ Failed to create RAR file
            set /a FAILED+=1
        )
    ) else (
        echo     ✗ Failed to extract ZIP
        set /a FAILED+=1
    )
    echo.
)

REM Convert RRBILLINGCLIENT.zip
if exist "RRBILLINGCLIENT.zip" (
    echo [2] Processing: RRBILLINGCLIENT.zip
    echo     Extracting...
    
    if exist "RRBILLINGCLIENT" (
        rmdir /s /q "RRBILLINGCLIENT" >nul 2>&1
    )
    
    cd /d "%cd%"
    powershell -Command "Expand-Archive -Path '.\RRBILLINGCLIENT.zip' -DestinationPath '.\' -Force" >nul 2>&1
    
    if exist "RRBILLINGCLIENT" (
        echo     Creating RAR archive...
        "%WINRAR%" a -r -ep1 -m5 "RRBILLINGCLIENT.rar" "RRBILLINGCLIENT\" >nul 2>&1
        
        if exist "RRBILLINGCLIENT.rar" (
            echo     ✓ Success! Created: RRBILLINGCLIENT.rar
            set /a SUCCESS+=1
            
            REM Optional: delete source ZIP and folder
            REM del "RRBILLINGCLIENT.zip"
            REM rmdir /s /q "RRBILLINGCLIENT"
            
        ) else (
            echo     ✗ Failed to create RAR file
            set /a FAILED+=1
        )
    ) else (
        echo     ✗ Failed to extract ZIP
        set /a FAILED+=1
    )
    echo.
)

echo ════════════════════════════════════════════════════════════════════════════════
echo CONVERSION SUMMARY
echo ════════════════════════════════════════════════════════════════════════════════
echo.
echo Success: %SUCCESS%
echo Failed:  %FAILED%
echo.

if %FAILED% equ 0 (
    color 0A
    echo ✓ All files converted successfully!
    echo.
    echo RAR files created:
    if exist "RRBILLINGPRO.rar" echo   - RRBILLINGPRO.rar
    if exist "RRBILLINGCLIENT.rar" echo   - RRBILLINGCLIENT.rar
    echo.
    echo Optional: You can now delete the .zip files and extracted folders
    echo.
) else (
    color 0C
    echo ✗ Some files failed to convert
    echo.
)

echo.
pause
exit /b %FAILED%
