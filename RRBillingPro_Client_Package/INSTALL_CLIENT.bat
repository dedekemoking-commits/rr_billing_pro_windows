@echo off
title RR Billing Pro - Install Client Warnet
setlocal enabledelayedexpansion

set "CLIENT_DIR=C:\RRBillingClient"
set "SERVICE_NAME=RRBillingClientService"
set "LOG_FILE=%CLIENT_DIR%\install_log.txt"
set "PKG=%~dp0"

REM ============================================================
REM  MODE CEK (dry run) - tidak mengubah apa pun di sistem
REM  Jalankan:  INSTALL_CLIENT.bat --check
REM ============================================================
if /i "%~1"=="--check" goto :CHECK

REM ============================================================
REM  RELAUNCH AMAN - window TIDAK AKAN tertutup sendiri
REM  Installer asli dijalankan ulang di window baru via
REM  "cmd /k" sehingga walaupun terjadi error apa pun,
REM  window tetap terbuka dan error terlihat.
REM ============================================================
if /i "%~1"=="RUNNING" goto :MAIN
start "RR Billing Installer" cmd /k ""%~f0" RUNNING %*"
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

if not exist "%CLIENT_DIR%" mkdir "%CLIENT_DIR%"

echo ========================================
echo   RR Billing Pro - Install Client Warnet
echo ========================================
echo.
echo   Paket dari  : %PKG%
echo   Instal ke   : %CLIENT_DIR%
echo.
echo   Installer sedang berjalan - hasilnya akan
echo   ditampilkan setelah selesai. JANGAN TUTUP window ini.
echo.
echo   Log detail disimpan ke: %LOG_FILE%
echo.

REM Jalankan inti installer, semua output direkam ke log.
call :CORE > "%LOG_FILE%" 2>&1
set RC=!errorlevel!

echo ========================================
echo   SELESAI - hasil dari %LOG_FILE%:
echo ========================================
if exist "%LOG_FILE%" type "%LOG_FILE%"
echo ========================================
if "!RC!"=="0" (
    echo   STATUS: INSTALLASI SUKSES
) else (
    echo   STATUS: INSTALLASI GAGAL - kode !RC!
    echo   Cek pesan error di atas, lalu perbaiki dan jalankan lagi.
)
echo ========================================
echo.
pause
exit /b !RC!

REM ============================================================
REM  INTI INSTALLER
REM ============================================================
:CORE

REM ---- LANGKAH 0 - pastikan file di C:\RRBillingClient ----
echo [1/6] Memeriksa lokasi install...
taskkill /f /im BillingClientApp.exe >nul 2>&1
taskkill /f /im BillingLockScreenUI.exe >nul 2>&1
net stop %SERVICE_NAME% >nul 2>&1
timeout /t 2 /nobreak >nul
if /i "%PKG%" NEQ "%CLIENT_DIR%\" (
    echo   Dijalankan dari: !PKG!
    echo   Menyalin file ke %CLIENT_DIR% ...
    copy /Y "!PKG!INSTALL_CLIENT.bat" "%CLIENT_DIR%\INSTALL_CLIENT.bat" >nul
    copy /Y "!PKG!BillingClientService.exe" "%CLIENT_DIR%\" >nul
    if errorlevel 1 goto :COPY_RETRY
    copy /Y "!PKG!BillingLockScreenUI.exe" "%CLIENT_DIR%\" >nul
    if errorlevel 1 goto :COPY_RETRY
    copy /Y "!PKG!BillingClientApp.exe" "%CLIENT_DIR%\" >nul
    if errorlevel 1 goto :COPY_RETRY
    REM jangan timpa config kalau flag --keep-config (update eksisting)
    if /i "%~2"=="--keep-config" (
        echo   Config DIPERTAHANKAN --keep-config
    ) else (
        if exist "!PKG!rr_billing_config.json" copy /Y "!PKG!rr_billing_config.json" "%CLIENT_DIR%\" >nul
    )
    echo   OK - file disalin ke %CLIENT_DIR%
) else (
    echo   OK - sudah berada di %CLIENT_DIR%
)
echo.
goto :skip_retry

:COPY_RETRY
echo   WARNA: file masih terkunci (mungkin lock screen UI). Stop service dulu...
timeout /t 3 /nobreak >nul
net stop %SERVICE_NAME% >nul 2>&1
taskkill /f /im BillingClientApp.exe >nul 2>&1
taskkill /f /im BillingLockScreenUI.exe >nul 2>&1
timeout /t 2 /nobreak >nul
copy /Y "!PKG!BillingClientService.exe" "%CLIENT_DIR%\" >nul
copy /Y "!PKG!BillingLockScreenUI.exe" "%CLIENT_DIR%\" >nul
copy /Y "!PKG!BillingClientApp.exe" "%CLIENT_DIR%\" >nul
echo   OK: salinan ulang berhasil.
echo.
:skip_retry

REM ---- LANGKAH 1 - cek konfigurasi ----
echo [2/6] Memeriksa rr_billing_config.json...
if not exist "%CLIENT_DIR%\rr_billing_config.json" (
    echo   ERROR: rr_billing_config.json TIDAK ditemukan di %CLIENT_DIR%
    echo.
    echo   Buat file tersebut dengan isi, sesuaikan contoh di bawah
    echo   {
    echo     "server_host": "192.168.1.17",
    echo     "server_port": 5000,
    echo     "client_id": "WARNET_1",
    echo     "password": "admin123",
    echo     "pc_id": "PC_1"
    echo   }
    echo.
    echo   server_host  = IP LAN PC kasir, bukan 127.0.0.1
    echo   client_id    = harus terdaftar di config SERVER
    echo   password     = password client, diisi plaintext
    echo   pc_id        = ID PC ini, unik per kursi, misal PC_1
    exit /b 1
)

findstr /i /c:"127.0.0.1" /c:"localhost" "%CLIENT_DIR%\rr_billing_config.json" >nul 2>&1
if !errorlevel! equ 0 (
    echo   PERINGATAN: server_host masih 127.0.0.1 atau localhost.
    echo   Server billing berada di PC LAIN. Isi dengan IP LAN PC kasir
    echo   lihat dengan perintah ipconfig di PC kasir.
    echo   Melanjutkan dalam 8 detik - tutup window untuk membatalkan.
    timeout /t 8 /nobreak >nul
)

findstr /c:"pc_id" "%CLIENT_DIR%\rr_billing_config.json" >nul 2>&1
if !errorlevel! neq 0 (
    echo   PERINGATAN: pc_id tidak ada di config. Client akan memakai
    echo   PC pertama dari daftar server. Sebaiknya isi pc_id eksplisit
    echo   misal PC_1, PC_2, dst - agar tiap kursi unik.
)

echo   Isi config saat ini:
echo   -------------------------------
type "%CLIENT_DIR%\rr_billing_config.json"
echo   -------------------------------
echo   Melanjutkan dalam 8 detik - tutup window untuk membatalkan.
timeout /t 8 /nobreak >nul
echo.

REM ---- LANGKAH 2 - install Windows Service ----
REM (aman dijalankan ulang: service lama di-stop & dihapus dulu)
echo [3/6] Menginstall Windows Service...
net stop %SERVICE_NAME% >nul 2>&1
sc query %SERVICE_NAME% >nul 2>&1
if !errorlevel! equ 0 (
    echo   Service lama ditemukan - uninstall dulu...
    "%CLIENT_DIR%\BillingClientService.exe" -u >nul 2>&1
)
"%CLIENT_DIR%\BillingClientService.exe" -i
sc query %SERVICE_NAME% >nul 2>&1
if !errorlevel! neq 0 (
    echo   ERROR: Gagal install service!
    echo   Pastikan BillingClientService.exe ada di %CLIENT_DIR%
    exit /b 1
)
echo   OK
echo.

REM ---- LANGKAH 3 - start service ----
echo [4/6] Menjalankan service...
net start %SERVICE_NAME% >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: Service tidak bisa start!
    echo.
    echo   ------ Isi log service ------
    if exist "%CLIENT_DIR%\rr_billing_client_service.log" (
        type "%CLIENT_DIR%\rr_billing_client_service.log"
    ) else (
        echo   belum ada log. Jalankan "%CLIENT_DIR%\BillingClientService.exe -c" untuk debug
    )
    echo.
    echo   Penyebab umum:
    echo    - server_host salah / server billing tidak hidup
    echo    - client_id / password tidak cocok dengan config server
    echo    - firewall server memblokir port 5000
    exit /b 1
)
echo   OK
echo.

REM ---- LANGKAH 4 - verifikasi service berjalan ----
echo [5/6] Verifikasi service...
sc query %SERVICE_NAME% | findstr /i "RUNNING" >nul
if !errorlevel! neq 0 (
    echo   ERROR: Service terpasang tapi tidak RUNNING.
    sc query %SERVICE_NAME%
    if exist "%CLIENT_DIR%\rr_billing_client_service.log" type "%CLIENT_DIR%\rr_billing_client_service.log"
    exit /b 1
)
echo   OK - Service RUNNING
echo.

REM ---- LANGKAH 5 - auto-start Tray App via Registry Run (semua user) ----
echo [6/6] Mendaftarkan Tray App ke auto-start (HKLM Run)...
set "RUN_KEY=HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
reg add "%RUN_KEY%" /v "RRBillingClientApp" /d "\"%CLIENT_DIR%\BillingClientApp.exe\"" /f >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: Gagal menulis Registry Run. Tray app TIDAK auto-start.
    echo   Tambahkan manual: reg add "%RUN_KEY%" /v RRBillingClientApp
    echo   /d "\"%CLIENT_DIR%\BillingClientApp.exe\"" /f
) else (
    echo   OK - BillingClientApp akan jalan otomatis setiap login/reboot
    echo   - berlaku untuk semua user di PC ini.
)

REM ---- LANGKAH 5b - jalankan Tray App sekarang (jika belum jalan) ----
tasklist /fi "IMAGENAME eq BillingClientApp.exe" 2>nul | findstr /i "BillingClientApp.exe" >nul
if %errorlevel% neq 0 (
    start "" "%CLIENT_DIR%\BillingClientApp.exe"
    echo   Tray app dijalankan sekarang - ikon di kanan bawah.
) else (
    echo   Tray app sudah berjalan - tidak perlu dijalankan ulang.
)

REM ---- LANGKAH 5c - firewall port 8082 (logo lock screen) ----
netsh advfirewall firewall add rule name="RR Billing Lock Media 8082" dir=in action=allow protocol=TCP localport=8082 >nul 2>&1
if %errorlevel% equ 0 (
    echo   OK - Firewall port 8082 dibuka - media lock screen.
) else (
    echo   PERINGATAN: gagal membuka firewall port 8082 - tidak fatal.
)

echo.
echo ========================================
echo   INSTALLASI SELESAI!
echo ========================================
echo.
echo   Lokasi : %CLIENT_DIR%
echo   Service: %SERVICE_NAME% (LocalSystem, auto start)
echo   Tray   : auto-start via Registry Run (HKLM), berlaku semua user.
echo            Service juga memantau tray app dan menyalakan ulang
echo            otomatis bila dimatikan (watchdog tiap 10 detik).
echo.
echo   Verifikasi:
echo    - Cek log : type %CLIENT_DIR%\rr_billing_client_service.log
echo      Harus ada baris: "Connected. Sending AUTH..." lalu "AUTH successful."
echo    - Di server: tab Warnet, label "Client: Tersambung" dan
echo      kartu kursi menampilkan "Connected".
echo    - Ikon tray di kanan bawah TIDAK bisa ditutup dari menu.
echo      Lock PC hanya bisa dibuka dari server (tombol UNLOCK).
echo.
echo   Jika config diubah (IP server / password / pc_id), restart service:
echo     net stop %SERVICE_NAME%
echo     net start %SERVICE_NAME%
echo.
echo   Untuk uninstall:
echo     net stop %SERVICE_NAME%
echo     "%CLIENT_DIR%\BillingClientService.exe" -u
echo ========================================
exit /b 0

REM ============================================================
REM  MODE CEK (dry run - tidak mengubah apa pun)
REM ============================================================
:CHECK
echo ========================================
echo   CEK PACKAGE CLIENT - tidak mengubah apa pun
echo ========================================
echo.
echo   Paket di folder: %PKG%
echo.
if not exist "%PKG%rr_billing_config.json" (
    echo   ERROR: rr_billing_config.json TIDAK ditemukan di !PKG!
    pause
    exit /b 1
)
echo   Isi rr_billing_config.json saat ini:
echo   ------------------------------------
type "%PKG%rr_billing_config.json"
echo   ------------------------------------
echo.
echo   File yang akan disalin ke C:\RRBillingClient:
for %%F in (BillingClientService.exe BillingLockScreenUI.exe BillingClientApp.exe rr_billing_config.json) do (
    if exist "!PKG!%%F" (
        echo    [OK]    %%F
    ) else (
        echo    [MISSING] %%F  -- file TIDAK ada di package ini!
    )
)
echo.
echo   Auto-start yang akan didaftarkan (HKLM Run, semua user):
echo     reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
echo     /v RRBillingClientApp /d "\"C:\RRBillingClient\BillingClientApp.exe\"" /f
echo.
echo   Cek saat ini (jika sudah terdaftar, akan ditimpa):
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v RRBillingClientApp 2>nul
echo.
pause
exit /b 0
