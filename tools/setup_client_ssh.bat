@echo off
title RR Billing Pro - Setup SSH Client
color 0B
echo ====================================================
echo    RR Billing Pro v2.3
echo    Setup OpenSSH Server untuk PC Client Warnet
echo ====================================================
echo.
echo Script ini akan mengaktifkan SSH Server di PC ini
echo agar bisa di-deploy otomatis dari PC Admin.
echo.
echo Pastikan:
echo   - PC ini dalam keadaan ADMIN (Run as Administrator)
echo   - Firewall Windows aktif
echo.
pause
echo.

:: ── 1. Cek Admin ───────────────────────────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Jalankan script ini sebagai Administrator!
    echo        Klik kanan ^> "Run as Administrator"
    pause
    exit /b 1
)
echo [✓] Running as Administrator

:: ── 2. Cek ketersediaan OpenSSH ─────────────────────────────
echo.
echo [*] Mengecek OpenSSH Server...
dism /online /get-capabilities | findstr "OpenSSH.Server~~~~0.0.1.0" >nul
if %errorlevel% equ 0 (
    echo [✓] OpenSSH Server sudah tersedia
) else (
    echo [!] OpenSSH Server belum terinstall. Menginstall...
    dism /online /add-capability /capabilityname:OpenSSH.Server~~~~0.0.1.0
    if %errorlevel% neq 0 (
        echo ERROR: Gagal menginstall OpenSSH Server.
        echo        Coba install manual: Settings ^> Apps ^> Optional Features
        pause
        exit /b 1
    )
    echo [✓] OpenSSH Server berhasil diinstall
)

:: ── 3. Start & Enable SSH Service ───────────────────────────
echo.
echo [*] Mengaktifkan SSH Service...
net start sshd >nul 2>&1
if %errorlevel% equ 2 (
    echo [✓] SSH Service sudah berjalan
) else if %errorlevel% equ 0 (
    echo [✓] SSH Service berhasil di-start
) else (
    echo [!] Gagal start SSH service, mencoba cara lain...
)

sc config sshd start=auto >nul
echo [✓] SSH Service diatur ke Auto Start

:: ── 4. Firewall ─────────────────────────────────────────────
echo.
echo [*] Membuka port 22 di Firewall...
netsh advfirewall firewall show rule name="OpenSSH Server (sshd)" >nul 2>&1
if %errorlevel% neq 0 (
    netsh advfirewall firewall add rule name="OpenSSH Server (sshd)" dir=in action=allow protocol=TCP localport=22
    echo [✓] Firewall port 22 dibuka
) else (
    echo [✓] Firewall port 22 sudah terbuka
)

:: ── 5. Admin Password ───────────────────────────────────────
echo.
echo [*] Set password untuk Administrator (sama untuk semua PC)
echo.
echo Masukkan password yang SAMA untuk semua PC client:
set /p "SSH_PASS=Password Administrator: "

net user Administrator "%SSH_PASS%" >nul
if %errorlevel% neq 0 (
    echo [!] Gagal ganti password Administrator.
    echo     Mungkin user 'Administrator' didisable.
    echo     Mengaktifkan Administrator...
    net user Administrator /active:yes >nul
    net user Administrator "%SSH_PASS%" >nul
    if %errorlevel% equ 0 (
        echo [✓] Administrator diaktifkan dan password di-set
    ) else (
        echo ERROR: Gagal mengatur Administrator. Buat user baru.
        net user sshadmin "%SSH_PASS%" /add
        net localgroup Administrators sshadmin /add
        echo [✓] User 'sshadmin' dibuat dengan password yang sama
    )
) else (
    echo [✓] Password Administrator berhasil di-update
)

:: ── 6. Verifikasi ───────────────────────────────────────────
echo.
echo ====================================================
echo    VERIFIKASI
echo ====================================================
sc query sshd | findstr "RUNNING" >nul
if %errorlevel% equ 0 (
    echo [✓] SSH Server: RUNNING
) else (
    echo [✗] SSH Server: TIDAK BERJALAN
)

echo.
echo Cek koneksi lokal:
ssh Administrator@localhost "echo SSH OK"
if %errorlevel% equ 0 (
    echo [✓] SSH local: BERHASIL
) else (
    echo [!] SSH local gagal. Pastikan password benar.
)

echo.
echo ====================================================
echo    SETUP SELESAI
echo ====================================================
echo.
echo Sekarang PC ini bisa di-deploy dari PC Admin:
echo   IP PC ini   : 
ipconfig | findstr /i "IPv4"
echo   Username    : Administrator (atau sshadmin)
echo   Password    : (yang baru di-set)
echo.
echo Jalankan ini di SEMUA PC client warnet.
echo Setelah selesai, deploy dari admin tinggal satu klik.
echo.
pause
