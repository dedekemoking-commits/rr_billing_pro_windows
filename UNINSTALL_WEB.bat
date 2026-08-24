@echo off
title RR Billing Pro - Uninstall Web Kasir
setlocal
set "WEB_DIR=C:\RRBillingWeb"
set "DESK=%PUBLIC%\Desktop"
if not exist "%DESK%" set "DESK=%USERPROFILE%\Desktop"

echo ====================================================
echo   RR Billing Pro - Uninstall Web Kasir
echo ====================================================
echo.
echo   Akan menghentikan server dan menghapus:
echo     - %WEB_DIR%
echo     - Shortcut: %DESK%\RR Billing Web Kasir.lnk
echo.
set /p "CONF=Ketik 'HAPUS' (tanpa tanda kutip) untuk lanjut: "
if not "%CONF%"=="HAPUS" (
    echo   Dibatalkan.
    pause
    exit /b 0
)

echo.
echo   Menghentikan proses server...
for /f "tokens=2" %%P in ('tasklist /fi "IMAGENAME eq python.exe" /fo list ^| findstr /i "PID"') do (
    wmic process where "ProcessId=%%P" get CommandLine 2>nul | findstr /i "server.py" >nul && taskkill /f /pid %%P >nul 2>&1
)

if exist "%DESK%\RR Billing Web Kasir.lnk" del /q "%DESK%\RR Billing Web Kasir.lnk" >nul 2>&1
if exist "%WEB_DIR%" (
    rmdir /s /q "%WEB_DIR%" >nul 2>&1
    if exist "%WEB_DIR%" (
        echo   PERINGATAN: folder %WEB_DIR% tidak bisa dihapus (masih terkunci?).
        echo   Tutup window server/python lalu hapus manual.
    ) else (
        echo   OK - %WEB_DIR% dihapus.
    )
) else (
    echo   Folder %WEB_DIR% sudah tidak ada.
)
echo.
echo   Selesai. (Python yang terinstall TIDAK dihapus - aman dibiarkan.)
echo ====================================================
pause
exit /b 0
