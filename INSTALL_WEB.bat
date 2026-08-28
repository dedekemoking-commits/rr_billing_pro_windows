@echo off
title RR Billing Pro - Install Web Kasir (localhost:8000)
setlocal enabledelayedexpansion

REM ============================================================
REM  RR Billing Pro - Web Kasir Installer
REM  - Install Python 3.12 (bila belum ada)
REM  - Install dependency (Flask + modul pendukung)
REM  - Salin billing_web + modul parent ke C:\RRBillingWeb
REM  - Hilangkan MotW (popup "Open File - Security Warning")
REM  - Jalankan server + buka browser otomatis
REM ============================================================

set "WEB_DIR=C:\RRBillingWeb"
set "SERVICE_NAME=RRBillingWeb"
set "LOG_FILE=%WEB_DIR%\install_web_log.txt"
set "PKG=%~dp0"
set "PY=python"

REM ============================================================
REM  RELAUNCH AMAN - window TIDAK tertutup sendiri
REM  Lokasi paket asli diwarisi via env var PKG_ORIGINAL,
REM  karena %~dp0 di mode RUNNING menunjuk ke folder TEMP.
REM ============================================================
if /i "%~1"=="RUNNING" (
    if defined PKG_ORIGINAL set "PKG=%PKG_ORIGINAL%"
    goto :MAIN
)
set "PKG_ORIGINAL=%~dp0"
set "TMPBAT=%TEMP%\rr_billing_web_install.cmd"
copy /Y "%~f0" "%TMPBAT%" >nul 2>&1
powershell -NoProfile -Command "Unblock-File -LiteralPath '%TMPBAT%' -ErrorAction SilentlyContinue" >nul 2>&1
start "RR Billing Web Installer" cmd /k ""%TMPBAT%" RUNNING %*"
exit /b 0

:MAIN
REM ================= CEK ADMIN =================
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Jalankan sebagai Administrator!
    echo Klik kanan file ini ^> "Run as Administrator"
    pause
    exit /b 1
)

if not exist "%WEB_DIR%" mkdir "%WEB_DIR%"

echo ====================================================
echo   RR Billing Pro - Install Web Kasir
echo ====================================================
echo.
echo   Paket dari  : !PKG!
echo   Instal ke   : %WEB_DIR%
echo.
echo   Installer sedang berjalan. JANGAN TUTUP window ini.
echo   Log detail : %LOG_FILE%
echo.

REM Jalankan inti installer, semua output direkam ke log.
call :CORE > "%LOG_FILE%" 2>&1
set RC=!errorlevel!

echo ====================================================
echo   SELESAI - hasil dari %LOG_FILE%:
echo ====================================================
if exist "%LOG_FILE%" type "%LOG_FILE%"
echo ====================================================
if "!RC!"=="0" (
    echo   STATUS: INSTALASI SUKSES
) else (
    echo   STATUS: INSTALLASI GAGAL - kode !RC!
    echo   Cek pesan error di atas, lalu perbaiki dan jalankan lagi.
)
echo ====================================================
echo.
pause
exit /b !RC!

REM ============================================================
REM  INTI INSTALLER
REM ============================================================
:CORE

REM ---- LANGKAH 1 - pastikan Python ada ----
echo [1/7] Memeriksa Python 3.x...
set "PYFOUND=0"
where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PY=python"
    for /f "delims=" %%V in ('python -c "import sys;print(sys.version_info[0])" 2^>nul') do set "PYMAJ=%%V"
)
if "!PYMAJ!"=="3" set "PYFOUND=1"
where py >nul 2>&1
if %errorlevel% equ 0 (
    if not defined PYFOUND (
        set "PY=py -3"
        set "PYFOUND=1"
    )
)
if "!PYFOUND!"=="1" goto :PY_OK

echo   Python TIDAK ditemukan. Menginstall Python 3.12...
echo   (perlu koneksi internet; proses beberapa menit)
echo.

REM Coba winget dulu
winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements >nul 2>&1
if %errorlevel% equ 0 (
    echo   winget: Python 3.12 terinstall.
    goto :PY_INSTALLED
)

REM Fallback: download installer resmi
echo   winget gagal, download installer dari python.org...
set "PYINST=%TEMP%\python-3.12.9-amd64.exe"
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe' -OutFile '%PYINST%'" >nul 2>&1
if not exist "%PYINST%" (
    echo   ERROR: Gagal mengunduh Python installer. Cek koneksi internet.
    exit /b 1
)
start /wait "" "%PYINST%" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1
del /q "%PYINST%" >nul 2>&1

:PY_INSTALLED
REM Refresh PATH dengan lokasi install umum
set "PATH=%PATH%;C:\Python312\;C:\Python312\Scripts\;%LOCALAPPDATA%\Programs\Python\Python312\;%LOCALAPPDATA%\Programs\Python\Python312\Scripts\"
where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PY=python"
) else (
    set "PY=py -3"
)

:PY_OK
%PY% --version
if %errorlevel% neq 0 (
    echo   ERROR: Python tetap tidak bisa dipanggil.
    exit /b 1
)
echo.

REM ---- LANGKAH 2 - install dependency ----
echo [2/7] Menginstall dependency Python (Flask + modul pendukung)...
REM Pastikan pip tersedia (offline, tanpa internet)
%PY% -m ensurepip >nul 2>&1
REM Upgrade pip best-effort (butuh internet; di-skip kalau gagal/offline)
%PY% -m pip install --upgrade pip >nul 2>&1
REM Install SEMUA dependency dari wheel LOKAL (offline, tanpa PyPI)
if exist "!PKG!billing_web\wheels\*.whl" (
    echo   Menginstall dependency dari wheel lokal ^(offline^)...
    %PY% -m pip install --no-index --find-links "!PKG!billing_web\wheels" flask pillow customtkinter openpyxl bcrypt PyJWT cryptography websockets androidtvremote2 requests qrcode ecdsa tinytuya pycryptodome
    if %errorlevel% neq 0 (
        echo   ERROR: Gagal install dependency dari wheel lokal. Pastikan folder billing_web\wheels lengkap.
        exit /b 1
    )
) else (
    echo   ERROR: folder wheel tidak ditemukan di !PKG!billing_web\wheels
    exit /b 1
)
echo   OK - dependency terinstall (offline).
echo.

REM ---- LANGKAH 3 - salin modul parent ----
echo [3/7] Menyalin modul aplikasi ke %WEB_DIR% ...
set "PARENT_MODS=main.py rr_license.py firestore_sync.py firebase_auth.py tv_ws_hub.py tv_media_server.py tv_mesin.py media_prepare.py tv_test_api.py"
for %%M in (%PARENT_MODS%) do (
    if exist "!PKG!%%M" (
        copy /Y "!PKG!%%M" "%WEB_DIR%\%%M" >nul
        echo   + %%M
    ) else (
        echo   PERINGATAN: %%M tidak ada di paket ^(!PKG!^)
    )
)
echo.

REM ---- LANGKAH 4 - salin folder billing_web ----
echo [4/7] Menyalin folder billing_web ...
if not exist "!PKG!billing_web" (
    echo   ERROR: folder billing_web tidak ditemukan di !PKG!
    exit /b 1
)
robocopy "!PKG!billing_web" "%WEB_DIR%\billing_web" /E /NFL /NDL /NJH /NJS >nul 2>&1
echo   OK - billing_web disalin.
echo.

REM ---- LANGKAH 5 - siapkan config di root (main.py muat dari dir-nya sendiri) ----
echo [5/7] Menyiapkan config di root %WEB_DIR% ...
if /i "%~2"=="--keep-config" (
    echo   --keep-config: config dipertahankan ^(tidak ditimpa^).
) else (
    if exist "!PKG!billing_web\rr_billing_config.json" (
        if not exist "%WEB_DIR%\rr_billing_config.json" (
            copy /Y "!PKG!billing_web\rr_billing_config.json" "%WEB_DIR%\rr_billing_config.json" >nul
            echo   + rr_billing_config.json ^(dari billing_web^)
        ) else (
            echo   . rr_billing_config.json sudah ada - dipertahankan.
        )
    )
    if exist "!PKG!billing_web\rr_billing_license.json" (
        if not exist "%WEB_DIR%\rr_billing_license.json" (
            copy /Y "!PKG!billing_web\rr_billing_license.json" "%WEB_DIR%\rr_billing_license.json" >nul
            echo   + rr_billing_license.json ^(dari billing_web^)
        ) else (
            echo   . rr_billing_license.json sudah ada - dipertahankan.
        )
    )
)
echo.

REM ---- LANGKAH 6 - hilangkan MotW (popup Open File) ----
echo [6/7] Menghapus tanda blokir internet (MotW) ...
powershell -NoProfile -Command "Get-ChildItem -Path '%WEB_DIR%\*' -Recurse -File -Include *.py,*.bat,*.cmd,*.whl | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1

set "MOTW_TMP=%TEMP%\rr_web_motw.txt"
del "%MOTW_TMP%" >nul 2>&1
powershell -NoProfile -Command "Get-ChildItem -Path '%WEB_DIR%\*' -Recurse -File -Include *.py,*.bat,*.whl | Where-Object { $s = Get-Item -LiteralPath $_.FullName -Stream * -ErrorAction SilentlyContinue; $s -and ($s.Stream -contains 'Zone.Identifier') } | Select-Object -ExpandProperty Name | Out-File -LiteralPath '%MOTW_TMP%' -Encoding ascii" >nul 2>&1
set MOTW_LEFT=0
if exist "%MOTW_TMP%" (
    for /f "usebackq delims=" %%Z in ("%MOTW_TMP%") do set /a MOTW_LEFT+=1
)
del "%MOTW_TMP%" >nul 2>&1
if not "%MOTW_LEFT%"=="0" (
    echo   PERINGATAN: %MOTW_LEFT% file masih bertanda internet ^(MotW^).
    echo   Popup "Open File" mungkin muncul. Unblock manual lalu ulangi.
) else (
    echo   [MOTW] OK - semua file bersih.
)
echo.

REM ---- LANGKAH 7 - shortcut Desktop + jalankan ----
echo [7/7] Membuat shortcut ^& menjalankan server ...
set "DESK=%PUBLIC%\Desktop"
if not exist "%DESK%" set "DESK=%USERPROFILE%\Desktop"
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut('%DESK%\RR Billing Web Kasir.lnk'); $s.TargetPath='%WEB_DIR%\billing_web\jalankan_web.bat'; $s.WorkingDirectory='%WEB_DIR%\billing_web'; $s.Description='RR Billing Pro - Web Kasir (localhost:8000)'; $s.Save()" >nul 2>&1
if exist "%DESK%\RR Billing Web Kasir.lnk" (
    echo   OK - Shortcut dibuat: %DESK%\RR Billing Web Kasir.lnk
) else (
    echo   PERINGATAN: gagal membuat shortcut ^(tidak fatal^).
)

echo.
echo   Menjalankan server web kasir di background...
start "RR Billing Web" cmd /k "cd /d %WEB_DIR%\billing_web && %PY% server.py"
timeout /t 4 /nobreak >nul
echo   Membuka browser http://localhost:8000 ...
start "" "http://localhost:8000"

echo.
echo ====================================================
echo   INSTALASI WEB KASIR SELESAI!
echo ====================================================
echo.
echo   Lokasi    : %WEB_DIR%
echo   Akses     : http://localhost:8000  (buka di browser kasir)
echo   Shortcut  : %DESK%\RR Billing Web Kasir.lnk
echo.
echo   CATATAN PENTING:
echo    - JANGAN jalankan aplikasi desktop (main.py) bersamaan dengan
echo      web ini, keduanya menulis file config/riwayat yang sama.
echo    - Untuk menghentikan: tutup window "RR Billing Web" (python server.py).
echo    - Log server: %WEB_DIR%\billing_web\web_app.log
echo.
echo   Untuk install ulang / update: jalankan INSTALL_WEB.bat lagi.
echo ====================================================
exit /b 0
