@echo off
title LG TV Controller - Setup
echo.
echo ============================================
echo   LG TV Controller - Setup & Install
echo ============================================
echo.
echo [1/3] Install dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Gagal install dependencies!
    echo Pastikan Python dan pip sudah terinstall.
    echo.
    pause
    exit /b 1
)
echo.
echo [2/3] Dependencies berhasil diinstall!
echo.
echo [3/3] Menjalankan aplikasi test...
echo.
python test_tv_controller.py
pause
