==============================================
 RR Billing Pro - Client Warnet (Package)
 Panduan Singkat - Baca juga PANDUAN lengkap di
 repo server: docs/PANDUAN_PASANG_CLIENT_WARNET.md
==============================================

FILE DI FOLDER INI
------------------
- BillingClientService.exe   -> Windows Service (LocalSystem)
- BillingLockScreenUI.exe    -> Lock Screen (desktop virtual)
- BillingClientApp.exe       -> System Tray (info billing)
- rr_billing_config.json     -> Konfigurasi koneksi (WAJIB diedit)
- INSTALL_CLIENT.bat         -> Installer (jalankan sebagai Administrator)

PERSYARATAN
-----------
- Windows 10 / 11 (64-bit)
- PC kasir (server billing) hidup dan firewall mengizinkan port 5000
- client_id + password terdaftar di config server (warnet_clients)

CARA PASANG (ringkas)
---------------------
1. COPY SELURUH folder ini ke C:\RRBillingClient di PC client
   (JANGAN install dari flashdisk - service akan mati saat
   flashdisk dicabut. INSTALL_CLIENT.bat menyalin otomatis,
   jadi boleh juga dijalankan langsung dari flashdisk.)
2. Edit C:\RRBillingClient\rr_billing_config.json:
     server_host : IP LAN PC kasir (bukan 127.0.0.1)
     server_port : 5000
     client_id   : nama client (mis. WARNET_1)
     password    : password client (plaintext)
     pc_id       : ID PC ini, unik per kursi (PC_1, PC_2, ...)
3. Klik kanan INSTALL_CLIENT.bat -> "Run as Administrator"
4. Selesai. Verifikasi di server: tab Warnet -> "Client: Tersambung"

VERIFIKASI & DEBUG
------------------
- Log service : type C:\RRBillingClient\rr_billing_client_service.log
  Harus ada "Connected. Sending AUTH..." lalu "AUTH successful."
- Mode console:  C:\RRBillingClient\BillingClientService.exe -c
- Restart setelah ubah config:
    net stop RRBillingClientService
    net start RRBillingClientService
- Uninstall:
    net stop RRBillingClientService
    BillingClientService.exe -u

PENYEBAB UMUM TIDAK TERSAMBUNG
------------------------------
- server_host salah / server tidak hidup / firewall blokir 5000
- client_id tidak terdaftar di config server
- password salah (hash di server beda)
- pc_id tidak cocok dengan daftar pcs di config server
- config tidak terbaca (jangan lupa restart service setelah edit)

PERILAKU LOCK SCREEN (OTOMATIS, TIDAK PERLU SETUP)
---------------------------------------------------
- Waktu paket habis / admin menekan SELESAI / tombol OFF
  -> PC terkunci otomatis, lock screen tampil fullscreen.
- Koneksi server putus >15 detik -> PC auto-lock (anti kabur).
- Setelah PC reboot, PC akan TERKUNCI KEMBALI otomatis bila
  sebelumnya terkunci (state disimpan di file, dibuka lewat UNLOCK).
- Service memantau BillingClientApp (tray) tiap 10 detik dan
  menyalakan ulang otomatis bila mati/hang (watchdog).
- Bila aplikasi lock screen (BillingLockScreenUI) mati/di-kill
  saat PC terkunci, otomatis dijalankan ulang dalam <=3 detik.
- Buka kunci hanya dari server (tombol UNLOCK / mulai paket baru).

INFO REAL-TIME DI TRAY (KANAN BAWAH)
-------------------------------------
- Ikon tray menampilkan countdown sisa waktu: "Paket mm:ss".
- Balloon otomatis saat: sesi baru dimulai, sisa waktu tinggal
  5 / 3 / 1 menit (pengingat tambah waktu).
