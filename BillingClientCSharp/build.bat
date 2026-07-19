@echo off
setlocal enabledelayedexpansion

echo ========================================
echo  Membangun BillingClient C# Components
echo ========================================
echo.

set MSBUILD="C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe"
set CONFIG=Release
set PLATFORM=x64

REM Build Lock Screen UI first
echo [1/2] Membangun BillingLockScreenUI...
%MSBUILD% "%~dp0BillingLockScreenUI\BillingLockScreenUI.csproj" /p:Configuration=%CONFIG% /p:Platform=%PLATFORM% /t:Build /v:q
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Gagal build BillingLockScreenUI!
    exit /b 1
)
echo OK - BillingLockScreenUI berhasil dibangun.
echo.

REM Build Windows Service
echo [2/2] Membangun BillingClientService...
%MSBUILD% "%~dp0BillingClientService\BillingClientService.csproj" /p:Configuration=%CONFIG% /p:Platform=%PLATFORM% /t:Build /v:q
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Gagal build BillingClientService!
    exit /b 1
)
echo OK - BillingClientService berhasil dibangun.
echo.

REM Copy output to dist folder
set DIST=%~dp0dist
if not exist "%DIST%" mkdir "%DIST%"

copy /Y "%~dp0BillingLockScreenUI\bin\x64\%CONFIG%\BillingLockScreenUI.exe" "%DIST%\" >nul
copy /Y "%~dp0BillingLockScreenUI\bin\x64\%CONFIG%\BillingLockScreenUI.pdb" "%DIST%\" >nul
copy /Y "%~dp0BillingClientService\bin\x64\%CONFIG%\BillingClientService.exe" "%DIST%\" >nul
copy /Y "%~dp0BillingClientService\bin\x64\%CONFIG%\BillingClientService.pdb" "%DIST%\" >nul

echo.
echo ========================================
echo  BUILD SELESAI!
echo  Output: %DIST%
echo.
echo  BillingLockScreenUI.exe - Lock Screen
echo  BillingClientService.exe - Windows Service
echo ========================================
echo.
echo  Cara install service:
echo    BillingClientService.exe -i
echo.
echo  Cara jalankan di console (debug):
echo    BillingClientService.exe -c
echo.
echo  Cara uninstall service:
echo    BillingClientService.exe -u
echo ========================================

endlocal
