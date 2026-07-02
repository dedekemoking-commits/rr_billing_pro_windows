╔════════════════════════════════════════════════════════════════════════════╗
║                       RR BILLING PRO v2.3 - FINAL RELEASE                  ║
║              Sistem Manajemen Billing Warnet & Penyewaan TV                ║
╚════════════════════════════════════════════════════════════════════════════╝

📋 DAFTAR ISI
═════════════════════════════════════════════════════════════════════════════
1. Persyaratan Sistem
2. Cara Instalasi
3. Panduan Penggunaan Awal
4. Fitur Utama
5. Troubleshooting
6. Kontak & Dukungan

═════════════════════════════════════════════════════════════════════════════

1️⃣  PERSYARATAN SISTEM
═════════════════════════════════════════════════════════════════════════════

MINIMUM:
  • Windows 7 atau lebih baru
  • RAM: 2 GB
  • Ruang disk: 500 MB
  • Koneksi internet (untuk email verification)

RECOMMENDED:
  • Windows 10/11
  • RAM: 4 GB atau lebih
  • SSD (lebih cepat)
  • Koneksi internet stabil


2️⃣  CARA INSTALASI
═════════════════════════════════════════════════════════════════════════════

INSTALASI OTOMATIS (RECOMMENDED):
  1. Klik kanan file "SETUP_INSTALLER.bat"
  2. Pilih "Run as administrator"
  3. Ikuti instruksi di layar
  4. Aplikasi akan diinstal ke: C:\RRBillingPro

INSTALASI MANUAL:
  1. Buat folder: C:\RRBillingPro
  2. Copy semua file dari package ke folder tersebut
  3. Jalankan RRBILLINGPRO.exe


3️⃣  PANDUAN PENGGUNAAN AWAL
═════════════════════════════════════════════════════════════════════════════

FIRST TIME SETUP:

  1. LAUNCH APLIKASI
     • Double-click "RR Billing Pro" shortcut
     • Atau jalankan: C:\RRBillingPro\RRBILLINGPRO.exe

  2. LOGIN DEFAULT
     • Username: admin
     • Password: admin123
     
     ⚠️  PENTING: Ubah password setelah login pertama!

  3. SETUP AWAL (di TAB AKTIVASI):
     ✓ Konfigurasi Email (untuk verifikasi user)
     ✓ Setup Paket Penyewaan (TV, Warnet, PC)
     ✓ Setup Menu Makanan & Minuman
     ✓ Konfigurasi Server (IP & Port)

  4. TAMBAH USER & WARNET CLIENT:
     • Admin → Kelola User
     • Admin → Setup Warnet Client

  5. MULAI OPERASIONAL
     • Tab "Pesanan" untuk transaksi
     • Tab "Riwayat" untuk laporan
     • Tab "Warnet & TV" untuk monitor


4️⃣  FITUR UTAMA
═════════════════════════════════════════════════════════════════════════════

🔐 KEAMANAN & AUTENTIKASI
  ✓ Login dengan username/password
  ✓ Password hashing dengan bcrypt (aman)
  ✓ Email verification untuk registrasi user
  ✓ Reset password via email
  ✓ Admin code untuk akses client warnet

📝 MANAJEMEN PESANAN
  ✓ Input pesanan makanan, minuman, warnet, TV
  ✓ Hitung total otomatis
  ✓ Diskon & pajak
  ✓ Simpan data ke database
  ✓ Print struk

📊 LAPORAN & RIWAYAT
  ✓ Lihat riwayat semua pesanan
  ✓ Filter berdasarkan tanggal & kategori
  ✓ Export laporan ke Excel
  ✓ Analisis penjualan

🖥️  MANAJEMEN WARNET CLIENT
  ✓ Tambah & kelola PC client
  ✓ Monitor PC status real-time
  ✓ Kirim perintah ke client (shutdown, restart, dll)
  ✓ Charging session management

📱 PROFILE & SETTING
  ✓ Edit profil warnet/rental
  ✓ Konfigurasi email SMTP
  ✓ Setup paket rental dan harga
  ✓ Backup & restore database

💳 PEMBAYARAN
  ✓ Cash
  ✓ Debit/Credit Card (manual)
  ✓ QRIS (dengan QR code viewer)
  ✓ Transfer Bank (manual)
  ✓ Cicilan (khusus paket rental)


5️⃣  TROUBLESHOOTING
═════════════════════════════════════════════════════════════════════════════

❌ MASALAH: Aplikasi tidak bisa buka
   ✓ Pastikan sudah install .NET Framework
   ✓ Coba buka lagi (restart)
   ✓ Jika masih gagal, cek file log di C:\RRBillingPro\

❌ MASALAH: Email verification tidak bisa
   ✓ Cek koneksi internet
   ✓ Pastikan SMTP sudah dikonfigurasi di TAB AKTIVASI
   ✓ Gunakan app password untuk Gmail (jangan password biasa)
   ✓ Lihat log: rr_billing_audit.jsonl

❌ MASALAH: Warnet Client tidak bisa connect
   ✓ Pastikan IP address server benar
   ✓ Check firewall (port 8888 harus terbuka)
   ✓ Pastikan client dan server di network yang sama
   ✓ Coba restart client app

❌ MASALAH: Database error
   ✓ Backup file: rr_billing_config.json
   ✓ Delete file cache: rr_billing_config.json.lock
   ✓ Restart aplikasi

❌ MASALAH: Pesanan tidak masuk ke total
   ✓ Pastikan item sudah di-add ke database
   ✓ Check kategori item (makanan/minuman/warnet/tv)
   ✓ Coba refresh atau restart aplikasi


6️⃣  KONTAK & DUKUNGAN
═════════════════════════════════════════════════════════════════════════════

Email Support: dedekemoking@gmail.com
Dokumentasi: Lihat file dokumentasi di folder aplikasi

VERSI INFO:
  • Version: 2.3 (Final Release)
  • Build Date: 2026-07-03
  • Platform: Windows 7, 8, 10, 11
  • Language: Indonesian (Bahasa Indonesia)

═════════════════════════════════════════════════════════════════════════════

🎉 TERIMA KASIH TELAH MENGGUNAKAN RR BILLING PRO!

Silakan hubungi support jika ada pertanyaan atau masalah.

═════════════════════════════════════════════════════════════════════════════
