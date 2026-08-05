# Panduan Pasang Client Warnet (RR Billing Pro)

Panduan langkah demi langkah untuk menghubungkan **PC warnet** ke **server
billing (PC kasir)**. Dibuat untuk dipasang manual lewat flashdisk.

```
┌─────────────────────────┐   TCP :5000   ┌─────────────────────────┐
│  PC KASIR (SERVER)      │ ◄────────────►│  PC WARNET (CLIENT)     │
│  main.py                │  AUTH/PING/   │  BillingClientService   │
│  WarnetSocketServer     │  GET_STATUS   │  (Windows Service)      │
│  port TCP 5000          │               │  + LockScreenUI         │
└─────────────────────────┘               │  + Tray App             │
                                          └─────────────────────────┘
```

---

## Bagian A — Setup di PC Kasir (Server) — SEKALI SAJA

### A.1 Daftarkan client di config server

Tutup aplikasi kasir dulu (config dibaca saat start).

Buka `rr_billing_config.json` di folder aplikasi server, tambahkan client
ke daftar `warnet_clients`:

```json
{
  "warnet_clients": [
    {
      "client_id": "WARNET_01",
      "password_hash": "<hash password>",
      "location": "Warnet Cabang 1",
      "pcs": [
        { "pc_id": "PC_1", "ip": "192.168.1.15",  "name": "Kursi 1" },
        { "pc_id": "PC_2", "ip": "192.168.1.16",  "name": "Kursi 2" }
      ],
      "allowed_actions": ["ON", "OFF", "VOL+", "VOL-"],
      "created_at": "2026-08-03T00:00:00",
      "tokens": []
    }
  ]
}
```

- `client_id` + `password_hash` dipakai client untuk AUTH.
- `pcs` = daftar PC milik client ini. **`pc_id` harus unik** (PC_1, PC_2, ...)
  dan nanti dipakai client di config-nya.
- Buat `password_hash` (SHA256):

```
python -c "import hashlib; print(hashlib.sha256(b'PASSWORD_ANDA').hexdigest())"
```

> Tanpa Python, pakai plaintext biasa sebagai `password_hash` (server tetap
> menerima dan otomatis meng-upgrade ke hash setelah login pertama sukses).

### A.2 Restart aplikasi kasir

Jalankan ulang `RRBILLINGPRO.exe` agar config terbaca.

### A.3 Buka firewall untuk port 5000

Di PC kasir (CMD Administrator):

```
netsh advfirewall firewall add rule name="RR Billing Warnet 5000" dir=in action=allow protocol=TCP localport=5000
```

### A.4 Catat IP LAN PC kasir

Jalankan `ipconfig` di PC kasir, catat alamat IPv4 (mis. `192.168.1.17`).
IP ini yang akan diisi di config client.

---

## Bagian B — Pasang di PC Client (per PC warnet)

### B.1 Salin folder package ke PC client

Bawa folder `RRBillingPro_Client_Package` via flashdisk ke PC warnet.

> **PENTING — jangan install dari flashdisk.** Service membaca config dan
> `BillingLockScreenUI.exe` dari folder tempat exe berada; jika diinstall dari
> flashdisk, PC akan terkunci/mati layanannya begitu flashdisk dicabut.
>
> Tenang: `INSTALL_CLIENT.bat` sudah pintar — kalau dijalankan dari flashdisk,
> ia otomatis menyalin semuanya ke `C:\RRBillingClient` lalu melanjutkan
> install dari sana.

### B.2 Edit `rr_billing_config.json`

Buka file `rr_billing_config.json` (mis. dengan Notepad) di folder package,
sesuaikan:

```json
{
  "server_host": "192.168.1.17",
  "server_port": 5000,
  "client_id": "WARNET_01",
  "password": "admin123",
  "pc_id": "PC_1"
}
```

| Field          | Isi                                                                 |
|----------------|---------------------------------------------------------------------|
| `server_host`  | IP LAN PC kasir (lihat A.4). **Bukan** `127.0.0.1`                  |
| `server_port`  | `5000` (default, jangan diubah kalau tidak yakin)                   |
| `client_id`    | Harus sama dengan `client_id` di config server (A.1)                |
| `password`     | Password plaintext yang di-hash di A.1                              |
| `pc_id`        | ID PC ini — **unik per kursi**, harus ada di daftar `pcs` server    |

> Setiap PC warnet pakai `pc_id` yang berbeda (PC_1, PC_2, ...). Kalau semua
> PC memakai PC_1, semua akan menampilkan billing kursi yang sama.

### B.3 Jalankan installer

Klik kanan `INSTALL_CLIENT.bat` → **Run as Administrator**.

Script akan:
1. Menyalin seluruh file ke `C:\RRBillingClient` (jika belum di sana)
2. Mengecek config (menolak `127.0.0.1`, menampilkan isi config untuk konfirmasi)
3. Menginstall `RRBillingClientService` (LocalSystem, auto start, aman
   dijalankan ulang — service lama dihapus dulu)
4. Menjalankan service dan memverifikasi status RUNNING
5. Menambahkan tray app `BillingClientApp.exe` ke Startup (auto mulai saat login)

### B.4 Jalankan tray app (sekali, kalau tidak mau menunggu login ulang)

Jalankan `C:\RRBillingClient\BillingClientApp.exe` — ikon muncul di taskbar
sebelah jam, menampilkan status billing (paket, sisa waktu, biaya).

---

## Bagian C — Verifikasi & Tes

### C.1 Cek log koneksi di client

```
type C:\RRBillingClient\rr_billing_client_service.log
```

Harus terlihat:

```
[...] Connecting to 192.168.1.17:5000...
[...] Connected. Sending AUTH...
[...] AUTH successful.
[...] Authenticated as WARNET_01, PC: PC_1
```

Jika `AUTH failed` atau `Connection failed`, lihat Bagian D.

### C.2 Cek di server (dashboard kasir)

- Header tab **Warnet**: label **"Client: Tersambung"**.
- Tiap kartu kursi: **● Connected** (diperbarui tiap 5 detik).

### C.3 Tambah Kursi (ikatan PC ↔ kartu billing)

1. Di tab **Warnet**, klik **➕ Tambah Kursi** (aktif setelah client terhubung).
2. Isi nama kursi, pilih grup, lalu pilih **PC dari dropdown**
   (label = nama PC + IP, dari daftar `pcs` di config server).
3. Kartu muncul dan otomatis terikat ke `pc_id` itu — billing & lock/unlock
   kini mengikuti kartu ini.

### C.4 Tes LOCK/UNLOCK

| Aksi di kasir                         | Efek di PC client                          |
|---------------------------------------|--------------------------------------------|
| Mulai paket (dialog paket)            | PC **UNLOCK** (terbuka, game bisa jalan)   |
| Waktu habis / tombol SELESAI          | PC **LOCK** (muncul lock screen)           |
| Tombol ON / OFF di kartu              | **UNLOCK** / **LOCK** manual               |
| Koneksi putus >15 detik               | PC auto-**LOCK** (keamanan)                |

---

## Bagian D — Perawatan & Troubleshooting

### D.1 Ubah config (IP server, password, pc_id)

Edit `C:\RRbillingClient\rr_billing_config.json`, lalu restart service:

```
net stop RRBillingClientService
net start RRBillingClientService
```

### D.2 Update client (file EXE versi baru)

```
net stop RRBillingClientService
copy /Y <exe baru> C:\RRBillingClient\
net start RRBillingClientService
```

(File EXE yang sama diganti; config tidak berubah.)

### D.3 Uninstall

```
net stop RRBillingClientService
C:\RRBillingClient\BillingClientService.exe -u
```

### D.4 Tabel masalah umum

| Gejala                                   | Penyebab                                    | Solusi                                              |
|------------------------------------------|---------------------------------------------|-----------------------------------------------------|
| Log `Connection failed`                  | Server mati / IP salah / firewall           | Cek server hidup, `ping` IP server, buka port 5000   |
| Log `AUTH failed`                        | client_id/password tidak cocok di server    | Samakan dengan `warnet_clients` di config server     |
| Dashboard "Belum tersambung"             | Service client tidak jalan / AUTH gagal     | Cek log client (C.1), `sc query RRBillingClientService` |
| Kartu "Disconnected" tapi client OK      | Kartu belum di-Tambah Kursi / pc_id beda    | C.3, pastikan `pc_id` config client ada di `pcs`     |
| PC tidak terkunci saat waktu habis       | Kartu tidak terikat PC / command terlewat   | C.3 + tes ulang; restart service client              |
| PC terkunci terus padahal waktu ada      | Koneksi putus (auto-lock)                   | Cek jaringan & firewall; restart service             |
| Service gagal start (error 1053 dll)     | File config salah / exe tidak lengkap       | Pastikan 3 exe + config di `C:\RRbillingClient`      |

### D.5 Tes dari server tanpa PC fisik

Gunakan simulator (di PC kasir):

```
python tools/warnet_sim_client.py --host 127.0.0.1 --port 5000 --client WARNET_01 --password admin123 --pc PC_1 --iterations 3
```

Harus tampil `AUTH OK` lalu baris status billing tiap iterasi — cara cepat
memastikan bagian server beres sebelum mengejar masalah di client.

---

## Referensi

- Protokol lengkap: `docs/WARNET_CLIENT_SYSTEM.md`
- Kode client C#: `BillingClientCSharp/` (build: `build_direct.bat`)
- Package untuk flashdisk: `RRBillingPro_Client_Package/`
