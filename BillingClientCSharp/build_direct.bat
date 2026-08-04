@echo off
setlocal

echo ========================================
echo  Membangun BillingClient C# Components
echo  (Direct csc.exe build)
echo ========================================
echo.

set CSC="C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\Roslyn\csc.exe"
set REFDIR=C:\Windows\Microsoft.NET\Framework64\v4.0.30319
set OUTDIR=%~dp0dist

if not exist "%OUTDIR%" mkdir "%OUTDIR%"

set COMMON_REF=/reference:"%REFDIR%\System.dll" /reference:"%REFDIR%\System.Core.dll" /reference:"%REFDIR%\Microsoft.CSharp.dll"

REM ── [1/3] Build BillingLockScreenUI ──
echo [1/3] Membangun BillingLockScreenUI...
%CSC% /target:winexe /platform:x64 /optimize+ %COMMON_REF% /reference:"%REFDIR%\System.Windows.Forms.dll" /reference:"%REFDIR%\System.Drawing.dll" /out:"%OUTDIR%\BillingLockScreenUI.exe" "%~dp0BillingLockScreenUI\Program.cs" "%~dp0BillingLockScreenUI\LockScreenForm.cs"

if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Gagal build BillingLockScreenUI!
    exit /b 1
)
echo OK - BillingLockScreenUI.exe
echo.

REM ── [2/3] Build BillingClientService ──
echo [2/3] Membangun BillingClientService...
%CSC% /target:exe /platform:x64 /optimize+ %COMMON_REF% /reference:"%REFDIR%\System.Configuration.Install.dll" /reference:"%REFDIR%\System.ServiceProcess.dll" /reference:"%REFDIR%\System.IO.Pipes.dll" /out:"%OUTDIR%\BillingClientService.exe" "%~dp0BillingClientService\Program.cs" "%~dp0BillingClientService\ServiceCore.cs" "%~dp0BillingClientService\DesktopLocker.cs"

if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Gagal build BillingClientService!
    exit /b 1
)
echo OK - BillingClientService.exe
echo.

REM ── [3/3] Build BillingClientApp ──
echo [3/3] Membangun BillingClientApp (Tray)...
%CSC% /target:winexe /platform:x64 /optimize+ %COMMON_REF% /reference:"%REFDIR%\System.Windows.Forms.dll" /reference:"%REFDIR%\System.Drawing.dll" /reference:"%REFDIR%\System.IO.Pipes.dll" /out:"%OUTDIR%\BillingClientApp.exe" "%~dp0BillingClientApp\Program.cs" "%~dp0BillingClientApp\ClientAppForm.cs" "%~dp0BillingClientApp\DesktopLocker.cs"

if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Gagal build BillingClientApp!
    exit /b 1
)
echo OK - BillingClientApp.exe
echo.

echo ========================================
echo  BUILD SELESAI!
echo  Output: %OUTDIR%
echo.
echo  Files:
echo    BillingLockScreenUI.exe  - Lock Screen (virtual desktop)
echo    BillingClientService.exe - Windows Service (LocalSystem)
echo    BillingClientApp.exe     - System Tray Client App
echo ========================================
echo.
echo  Cara install service:
echo    cd dist ^&^& BillingClientService.exe -i
echo.
echo  Cara start service:
echo    net start RRBillingClientService
echo.
echo  Cara run tray app:
echo    BillingClientApp.exe
echo.
echo  Cara test console:
echo    BillingClientService.exe -c
echo ========================================

endlocal
pause
