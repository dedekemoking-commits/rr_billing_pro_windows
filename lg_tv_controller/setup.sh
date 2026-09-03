#!/bin/bash
echo ""
echo "============================================"
echo "  LG TV Controller - Setup & Install"
echo "============================================"
echo ""
echo "[1/3] Install dependencies..."
pip3 install -r requirements.txt
if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Gagal install dependencies!"
    echo "Pastikan Python3 dan pip sudah terinstall."
    exit 1
fi
echo ""
echo "[2/3] Dependencies berhasil diinstall!"
echo ""
echo "[3/3] Menjalankan aplikasi test..."
echo ""
python3 test_tv_controller.py
