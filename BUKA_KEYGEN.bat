@echo off
title RR BILLING PRO — Developer Keygen Tool
color 0A

echo.
echo  ============================================
echo   RR BILLING PRO ^| Developer Keygen Tool
echo  ============================================
echo.

:: ── Cari Python ──────────────────────────────────────────────────────────────
where python >nul 2>&1
if %errorlevel% neq 0 (
    where python3 >nul 2>&1
    if %errorlevel% neq 0 (
        echo  [ERROR] Python tidak ditemukan di sistem!
        echo.
        echo  Silakan install Python dari: https://www.python.org/downloads/
        echo  Pastikan centang "Add Python to PATH" saat instalasi.
        echo.
        pause
        exit /b 1
    )
    set PYTHON=python3
) else (
    set PYTHON=python
)

echo  Python ditemukan: 
%PYTHON% --version
echo.

:: ── Cek file rr_keygen.py ada ────────────────────────────────────────────────
if not exist "%~dp0rr_keygen.py" (
    echo  [ERROR] File rr_keygen.py tidak ditemukan!
    echo  Pastikan file rr_keygen.py ada di folder yang sama dengan file ini.
    echo.
    pause
    exit /b 1
)

:: ── Cek file rr_license.py ada ───────────────────────────────────────────────
if not exist "%~dp0rr_license.py" (
    echo  [ERROR] File rr_license.py tidak ditemukan!
    echo  Pastikan rr_license.py ada di folder yang sama.
    echo.
    pause
    exit /b 1
)

:: ── Cek dependensi customtkinter ─────────────────────────────────────────────
echo  Memeriksa dependensi...
%PYTHON% -c "import customtkinter" >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] customtkinter belum terinstall. Menginstall sekarang...
    %PYTHON% -m pip install customtkinter --quiet
    if %errorlevel% neq 0 (
        echo  [ERROR] Gagal install customtkinter. Cek koneksi internet.
        pause
        exit /b 1
    )
    echo  [OK] customtkinter berhasil diinstall.
)

%PYTHON% -c "import PIL" >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] Pillow belum terinstall. Menginstall sekarang...
    %PYTHON% -m pip install pillow --quiet
)

echo  [OK] Semua dependensi tersedia.
echo.
echo  Membuka Keygen Tool...
echo.

:: ── Jalankan dari folder yang sama (agar bisa baca config) ───────────────────
cd /d "%~dp0"
%PYTHON% rr_keygen.py

:: ── Jika crash, tampilkan error ───────────────────────────────────────────────
if %errorlevel% neq 0 (
    echo.
    echo  ============================================
    echo   [ERROR] Keygen Tool berhenti dengan error.
    echo  ============================================
    echo.
    echo  Kemungkinan penyebab:
    echo    1. File rr_license.py rusak atau tidak cocok versinya
    echo    2. rr_billing_config.json tidak ditemukan (belum ada user terdaftar)
    echo    3. Ada library yang belum terinstall
    echo.
    echo  Coba jalankan manual di CMD:
    echo    cd /d "%~dp0"
    echo    python rr_keygen.py
    echo.
    pause
)