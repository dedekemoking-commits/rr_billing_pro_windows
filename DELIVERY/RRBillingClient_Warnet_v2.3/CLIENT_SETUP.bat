@echo off
setlocal
set "SRC=%~dp0"
set "TARGET=C:\RRBillingClient"

echo ==========================================
echo   RRBillingClient Simple Installer v2.3
echo ==========================================
echo.

echo Installing to %TARGET%...
if not exist "%TARGET%" mkdir "%TARGET%"
copy /Y "%SRC%RRBILLINGCLIENT.exe" "%TARGET%\RRBILLINGCLIENT.exe" >nul
copy /Y "%SRC%logo.ico" "%TARGET%\logo.ico" >nul
copy /Y "%SRC%CLIENT_README.txt" "%TARGET%\CLIENT_README.txt" >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command "$desktop=[Environment]::GetFolderPath('Desktop');$shortcut=Join-Path $desktop 'RRBillingClient.lnk';$shell=New-Object -ComObject WScript.Shell;$link=$shell.CreateShortcut($shortcut);$link.TargetPath='C:\RRBillingClient\RRBILLINGCLIENT.exe';$link.WorkingDirectory='C:\RRBillingClient';$link.IconLocation='C:\RRBillingClient\logo.ico';$link.Save()" >nul 2>&1

echo.
echo Installation finished.
echo - Folder   : %TARGET%
echo - Shortcut : Desktop\\RRBillingClient.lnk
echo.
echo Next steps:
echo 1. Run RRBILLINGCLIENT.exe
echo 2. Open Settings
echo 3. Fill in server IP and port
echo.
pause
