╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║                 📦 RRBILLING DELIVERY PACKAGE - README                       ║
║                                                                              ║
║                    Build: 27 Juni 2026 | Version 2.3.2                      ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝


🎯 ISI PACKAGE
═════════════════════════════════════════════════════════════════════════════════

Folder ini berisi 2 paket aplikasi lengkap:

1. RRBILLINGPRO.zip (23.50 MB)
   - Server/Dashboard aplikasi warnet
   - File: RRBILLINGPRO.exe + config + icon
   - Dokumentasi lengkap: PANDUAN_INSTALASI_SERVER.txt

2. RRBILLINGCLIENT.zip (19.24 MB)
   - Client aplikasi untuk PC monitoring
   - File: RRBILLINGCLIENT.exe + logo + panduan
   - Dokumentasi lengkap: PANDUAN_LENGKAP_CLIENT.txt

3. README_CONVERT_TO_RAR.txt (ini file)
   - Cara convert ZIP ke RAR format


═════════════════════════════════════════════════════════════════════════════════
🚀 QUICK START
═════════════════════════════════════════════════════════════════════════════════

UNTUK SERVER:
1. Extract RRBILLINGPRO.zip
2. Double-click RRBILLINGPRO.exe
3. Setup admin account
4. Konfigurasi TV/kursi, paket billing, dll

UNTUK CLIENT (setiap PC):
1. Extract RRBILLINGCLIENT.zip
2. Double-click RRBILLINGCLIENT.exe
3. Masukkan Server IP
4. Klik Connect
5. Monitor billing real-time


═════════════════════════════════════════════════════════════════════════════════
🔄 CONVERT ZIP KE RAR FORMAT (OPTIONAL)
═════════════════════════════════════════════════════════════════════════════════

ZIP dan RAR adalah format archive yang sama-sama bisa di-extract.
Jika Anda lebih suka RAR format, ikuti langkah di bawah.

OPSI 1: MENGGUNAKAN WINRAR (RECOMMENDED)
─────────────────────────────────────────

Pastikan WinRAR sudah terinstall: https://www.rarlab.com/rar_add.htm

STEP 1: Convert RRBILLINGPRO.zip ke RAR
1. Klik kanan file: RRBILLINGPRO.zip
2. Pilih: "Extract to RRBILLINGPRO\"
3. Folder RRBILLINGPRO akan terbuat
4. Klik kanan folder RRBILLINGPRO
5. Pilih: "Add to archive"
6. Dialog WinRAR muncul
7. Change name: RRBILLINGPRO.rar
8. Set compression level: Normal atau Best
9. Klik OK
10. File RRBILLINGPRO.rar akan dibuat

STEP 2: Convert RRBILLINGCLIENT.zip ke RAR
(Ulangi langkah di atas untuk RRBILLINGCLIENT.zip)

Hasil akhir:
  ✓ RRBILLINGPRO.rar (bisa dihapus .zip setelah selesai)
  ✓ RRBILLINGCLIENT.rar (bisa dihapus .zip setelah selesai)

OPSI 2: MENGGUNAKAN 7-ZIP
────────────────────────────

Jika punya 7-Zip terinstall:

1. Klik kanan RRBILLINGPRO.zip
2. Pilih: "7-Zip" → "Extract Here"
3. Folder RRBILLINGPRO akan terbuat
4. Klik kanan folder RRBILLINGPRO
5. Pilih: "7-Zip" → "Add to Archive"
6. Extension: rar (atau biarkan default)
7. Compression level: 5 (normal)
8. Klik OK

OPSI 3: DIRECT EDIT NAMA FILE (SIMPLE)
──────────────────────────────────────

Jika hanya perlu ubah nama file:
(Note: Ini hanya rename, bukan re-compress)

1. Klik kanan: RRBILLINGPRO.zip
2. Pilih: Rename
3. Ubah extension: .zip → .rar
   Dari: RRBILLINGPRO.zip
   Ke: RRBILLINGPRO.rar
4. Click OK

⚠️  WARNING: Format masih tetap ZIP! Hanya nama yang berubah.
    Ini tidak recommended, lebih baik gunakan OPSI 1 atau 2.


═════════════════════════════════════════════════════════════════════════════════
📋 FILE CHECKLIST
═════════════════════════════════════════════════════════════════════════════════

RRBILLINGPRO PACKAGE:
✓ RRBILLINGPRO.exe (23.71 MB) - Main server executable
✓ rr_billing_config.json (0.03 MB) - Configuration file
✓ logo.ico (0.05 MB) - Application icon
✓ PANDUAN_INSTALASI_SERVER.txt - Server installation guide (Indonesian)

RRBILLINGCLIENT PACKAGE:
✓ RRBILLINGCLIENT.exe (19.42 MB) - Client executable
✓ logo.ico (0.05 MB) - Application icon
✓ PANDUAN_LENGKAP_CLIENT.txt - Complete client guide (Indonesian)


═════════════════════════════════════════════════════════════════════════════════
🔐 SYSTEM ARCHITECTURE
═════════════════════════════════════════════════════════════════════════════════

ARCHITECTURE OVERVIEW:

Server PC (Main Admin)
├─ RRBILLINGPRO.exe
├─ Dashboard UI (CustomTkinter)
├─ Socket Server (Port 5000)
├─ Config Database
└─ ADB Controller (untuk TV/Device)

Client PCs (Monitoring Stations) - 1 atau lebih
├─ RRBILLINGCLIENT.exe
├─ TCP Client (connect ke port 5000)
├─ Real-time Polling (2 detik)
└─ Display UI (billing info)

Data Flow:
Server → GET_STATUS request → Query app state → Return real data → Client display


═════════════════════════════════════════════════════════════════════════════════
🌐 NETWORK REQUIREMENTS
═════════════════════════════════════════════════════════════════════════════════

SERVER SIDE:
  • IP Address: Static recommended (e.g., 192.168.1.100)
  • Port: 5000 (must be open in firewall)
  • Network: Ethernet recommended (stable)
  • UPS: Recommended (untuk 24/7 operation)

CLIENT SIDE:
  • Must be in same network as server (LAN)
  • Can be WiFi or Ethernet
  • Need server IP address to connect
  • No internet needed (local network only)

FIREWALL CONFIGURATION:
  Windows Firewall → Allow RRBILLINGPRO.exe → Port 5000 inbound


═════════════════════════════════════════════════════════════════════════════════
📊 FEATURES INCLUDED
═════════════════════════════════════════════════════════════════════════════════

SERVER FEATURES:
✓ Dashboard dengan real-time status semua TV/Kursi
✓ Manajemen paket billing (1 Jam, 2 Jam, Overnight, Custom)
✓ Menu makanan & minuman dengan pricing
✓ Warnet tab untuk monitor PC client connections
✓ Transaction history & reporting (export to Excel)
✓ ADB integration untuk TV control
✓ Multi-user support dengan role management
✓ Backup & restore configuration
✓ License activation & management

CLIENT FEATURES:
✓ Real-time billing status polling (every 2 seconds)
✓ Display: Paket aktif | Sisa waktu (MM:SS) | Total biaya (Rp)
✓ Auto reconnect jika koneksi terputus
✓ Heartbeat monitoring untuk koneksi stability
✓ JWT token authentication
✓ IP address auto-detection
✓ Admin code generation per hari
✓ Responsive dark theme UI

DATA SYNC:
✓ Real-time data (no caching delay)
✓ Accurate to-the-second timing
✓ Minimal bandwidth usage (~1 KB/poll)


═════════════════════════════════════════════════════════════════════════════════
🛠️  TECHNICAL DETAILS
═════════════════════════════════════════════════════════════════════════════════

TECHNOLOGY STACK:
• Language: Python 3.14
• GUI Framework: CustomTkinter (modern Windows theme)
• Network: Socket programming (TCP/IP)
• Authentication: JWT tokens
• Protocol: Custom JSON over TCP
• Database: JSON config files (no SQL needed)
• Build Tool: PyInstaller (single EXE)

REQUIREMENTS:
• Windows 7 SP1+ (64-bit)
• .NET Framework 4.5+ (usually pre-installed)
• Visual C++ Redistributable (included in modern Windows)

FILE SIZES:
• Server: 23.71 MB (standalone executable)
• Client: 19.42 MB (standalone executable)
• Config: 0.03 MB
• Total: ~43 MB (both apps)


═════════════════════════════════════════════════════════════════════════════════
📖 DOCUMENTATION STRUCTURE
═════════════════════════════════════════════════════════════════════════════════

RRBILLINGPRO (Server):
  PANDUAN_INSTALASI_SERVER.txt
  ├─ Persyaratan Sistem
  ├─ Instalasi Step-by-step
  ├─ First Time Setup
  ├─ Fitur Utama Dashboard
  ├─ Konfigurasi Lanjutan
  ├─ Troubleshooting
  ├─ Backup & Recovery
  └─ Maintenance Checklist

RRBILLINGCLIENT (Client):
  PANDUAN_LENGKAP_CLIENT.txt
  ├─ Persyaratan Sistem
  ├─ Instalasi
  ├─ Konfigurasi Awal
  ├─ Menghubungkan ke Server
  ├─ Menggunakan Aplikasi
  ├─ Troubleshooting
  ├─ Fitur Utama
  └─ FAQ


═════════════════════════════════════════════════════════════════════════════════
✅ PRE-DELIVERY CHECKLIST
═════════════════════════════════════════════════════════════════════════════════

SERVER:
☑ RRBILLINGPRO.exe tested & working
☑ Config file included & valid
☑ Port 5000 configurable
☑ All features functional
☑ Documentation complete
☑ Package created & verified

CLIENT:
☑ RRBILLINGCLIENT.exe tested & working
☑ Auto IP detection working
☑ Server connection tested
☑ Real-time polling verified (2s interval)
☑ Billing display accurate
☑ Documentation complete
☑ Package created & verified

INTEGRATION:
☑ Server-Client communication tested
☑ Real data (not demo) from server to client
☑ No demo data left
☑ Git commits completed
☑ Code verified for production


═════════════════════════════════════════════════════════════════════════════════
🎯 DEPLOYMENT GUIDE (SUMMARY)
═════════════════════════════════════════════════════════════════════════════════

STEP 1: SETUP SERVER
1. Extract RRBILLINGPRO.zip
2. Run RRBILLINGPRO.exe
3. Setup admin account
4. Configure TV/kursi
5. Set paket billing
6. Note server IP address

STEP 2: SETUP CLIENT (repeat for each PC)
1. Extract RRBILLINGCLIENT.zip on each PC
2. Run RRBILLINGCLIENT.exe
3. Enter server IP
4. Click Connect
5. Verify status shows "Connected"

STEP 3: VERIFY
1. On server dashboard → check Warnet tab
2. Should see all connected client PCs
3. Try adding paket on TV
4. Verify client billing info updates in real-time

STEP 4: PRODUCTION
1. Configure auto-start (optional)
2. Setup backup schedule
3. Monitor logs daily
4. Train staff on usage


═════════════════════════════════════════════════════════════════════════════════
⚙️  CONFIGURATION REFERENCE
═════════════════════════════════════════════════════════════════════════════════

SERVER PORT:
  Default: 5000
  Can change in rr_billing_config.json:
  "socket_warnet": { "port": 5000 }

CLIENT CONNECTION TIMEOUT:
  Default: 6 seconds
  Edit in code if needed

POLLING INTERVAL:
  Default: 2 seconds (client)
  Edit STATUS_POLL_INTERVAL_SECONDS in code

TOKEN VALIDITY:
  Default: 180 days
  Auto-refresh on reconnect


═════════════════════════════════════════════════════════════════════════════════
📞 SUPPORT & UPDATES
═════════════════════════════════════════════════════════════════════════════════

VERSION: 2.3.2
BUILD DATE: 27 Juni 2026
GITHUB: https://github.com/dedekemoking-commits/rr_billing_pro_windows

For support:
Email: dedekemoking@gmail.com

When reporting issues, include:
• Windows version
• Error message (if any)
• Steps to reproduce
• Network configuration


═════════════════════════════════════════════════════════════════════════════════
🎉 READY FOR DEPLOYMENT!
═════════════════════════════════════════════════════════════════════════════════

Paket ini sudah lengkap dan siap digunakan:
✓ Executable files (no installation needed)
✓ Complete documentation
✓ Configuration ready
✓ All features included
✓ Production-tested

Untuk pertanyaan atau bantuan, hubungi developer.

Selamat menggunakan RRBILLING! 🚀


╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║               Thank you for choosing RRBILLING Solution                     ║
║                                                                              ║
║                              Happy Billing! 💰                               ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
