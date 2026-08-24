# RR Billing Pro — Web Kasir (localhost)

Versi **web** dari aplikasi kasir RR Billing Pro. Tampilannya modern (dark,
responsif) dan berjalan di browser: **http://localhost:8000**.

Semua data **sama** dengan aplikasi desktop:
- Config & tarif: `rr_billing_config.json`
- Riwayat transaksi: `rr_billing_riwayat.json`
- Cloud (Firestore): `billingps_users/{admin_utama}.transaksiList` — dashboard
  Netlify tetap menampilkan transaksi yang dicatat dari web ini.

## Cara menjalankan

1. Klik dua kali **`jalankan_web.bat`** (atau `python server.py` dari folder ini).
2. Buka browser ke **http://localhost:8000**.
3. **Login pertama kali**: belum ada akun di komputer ini? Klik *"Daftar admin
   pertama"* untuk membuat akun admin (tersimpan di config lokal, sama seperti
   pendaftaran di aplikasi desktop). Kasir didaftarkan admin lewat tab **Akun**.

> ⚠️ **Jangan jalankan aplikasi desktop (main.py) bersamaan dengan web ini.**
> Keduanya punya state sesi sendiri dan menulis file yang sama. Salah satu saja
> yang aktif untuk pemakaian (mulai paket, timer, dll).

## Fitur

- **Login admin/kasir** (bcrypt, sama dengan akun desktop) + pendaftaran admin
  pertama kali + kelola akun kasir (tab Akun, khusus admin).
- **Kartu TV & Warnet** live: hitung mundur real-time (1 detik), Main Bebas
  dengan biaya berjalan, PAUSE/RESUME, badge LUNAS/BELUM LUNAS.
- **Pilih Paket**: daftar paket sesuai grup (Reguler/PS3/PS4/Room VIP/Warnet)
  + diskon (Rp / %) + pesanan makanan/minuman sekaligus.
- **SHOP**: tambah/kurangi pesanan saat sesi berjalan — total & cloud diupdate.
- **Struk**: preview + cetak (printer ESC/POS sesuai `printer_settings` di
  config; tanpa printer → tersimpan di folder `receipts/`).
- **Riwayat**: tabel transaksi + cari + cetak ulang struk.
- **Sinkronisasi cloud**: upload transaksi & update otomatis (antrian + retry
  30 detik), identik dengan desktop.
- **Panel TV (tab Kelola → tombol 🖥)**: status koneksi APK client (ws :8080),
  status layar & lock admin, pairing TV, tombol **Kunci/Buka TV**,
  **kirim media promosi** (gambar langsung / video dinormalisasi ffmpeg),
  **sembunyikan media**, dan **ganti logo lock** (broadcast ke semua TV).
- **Scan TV di LAN (tab Kelola → 📡)**: temukan IP TV/STB yang belum terdaftar
  (deteksi ping + port ADB 5555 / pairing 6466/6467) lalu daftarkan
  langsung lewat tombol "➕".

## Koneksi APK client → TV (hub WebSocket :8080)

- APK **RRBillingPro-TV** yang terpasang di Android TV menyambung terus ke
  `ws://<ip-kasir>:8080` dan me-register `meja_id`-nya.
- Endpoint media promosi disajikan `TvMediaServer` di port **8082**
  (`http://<lan-ip>:8082/media/<file>`); APK mengambil sendiri.
- Video promo diproses **ffmpeg** (`media_prepare`) supaya kompatibel semua
  TV/box (copy → remux → transcode H.264+faststart + audio).
- Logo lock tersimpan sebagai `logo_lock.png` di `media_promo/` lalu
  dibroadcast `UPDATE_LOGO` ke semua TV.

Endpoint baru di `server.py`:
`/api/tv/status`, `/api/tv/test`, `/api/tv/lock`, `/api/tv/unlock`,
`/api/tv/media`, `/api/tv/media/status`, `/api/tv/media/hide`,
`/api/tv/logo`, `/api/scan`, `/api/scan/status`.

## Cara kerja teknis

- Backend **Flask** (satu-satunya dependensi baru) di `server.py`.
- Logika billing diangkat dari `main.py` tanpa GUI: class `Sesi` (state machine
  TV/warnet dari `KartuTV`/`KartuWarnet`), `Store` (riwayat + cloud + timer,
  dari `AutoRentApp`). `main.py` tidak diubah sama sekali.
- Timer: thread tick 1 detik; state sesi disimpan ke config tiap 30 detik
  (`timer_state`) dan dipulihkan saat server start — seperti desktop.
- Akses dibatasi ke **127.0.0.1:8000** (tidak terbuka ke jaringan).
- API dilindungi token acak per login (header `X-Auth-Token`).
- Lockscreen otomatis saat waktu sewa habis tetap jalan (via hub WS), sama
  seperti desktop.

## Catatan

- Jika port 8000 dipakai, server tidak mau start dua kali (proteksi).
- Fitur kontrol TV Android (lockscreen/remote) belum di port — sesi berjalan
  tetap dicatat & dihitung normal.
