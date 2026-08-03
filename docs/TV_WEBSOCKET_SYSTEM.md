# Sistem Overlay Timer & Lockscreen TV (WebSocket Realtime)

Sistem client-server untuk menampilkan **Floating Overlay Widget** (sisa waktu
sewa) dan **Lockscreen fullscreen** di Android TV/STB, dikontrol realtime dari
dashboard kasir RR Billing Pro.

```
┌─ Kasir (main.py, Windows) ─────────────────────────────────────┐
│  TvWsHub        — WebSocket push server  ws://0.0.0.0:8080     │
│  TvTestApi      — REST API test          http://0.0.0.0:8081   │
│  TvMediaServer  — HTTP media promosi     http://0.0.0.0:8082   │
│  KartuTV hooks: start/lock/selesai/pause/media → kirim push    │
└──────────────────────┬─────────────────────────────────────────┘
                       │ ws://<ip-kasir>:8080 (JSON + PING 5 dtk)
        ┌──────────────┴───────────────┐
        │ Android TV / STB (client)    │
        │ Foreground Service + OkHttp  │
        │ Overlay widget + Lockscreen  │
        │ Media promosi (video/gambar) │
        └──────────────────────────────┘
```

## File Server (Python — terintegrasi dengan main.py)

| File | Keterangan |
|---|---|
| `tv_ws_hub.py` | Hub WebSocket push (port 8080). Registri `meja_id`, heartbeat tiap 5 dtk, resync state saat client reconnect. **Tanpa dependency baru** (pakai `websockets` yang sudah ada). |
| `tv_test_api.py` | REST API test (port 8081, `http.server` bawaan, tanpa dependency). |
| `tv_media_server.py` | HTTP server media promosi (port 8082) — menyajikan video/gambar dari folder `media_promo/`. Tanpa dependency. |
| `tools/tv_ws_test.py` | Simulasi client TV untuk tes tanpa Android. |

Perubahan di `main.py` (surgikal):
1. Start `TvWsHub` + `TvTestApi` + `TvMediaServer` saat aplikasi dibuka
   (dapat dimatikan dengan config `tv_ws_enabled: false`).
2. `KartuTV._on_paket_confirm` → kirim `START_TIMER` (tambah waktu = kirim ulang).
3. `KartuTV._timer_habis` → kirim `LOCK_SCREEN` + rincian tagihan.
4. `KartuTV._klik_selesai` / `_reset_sesi` → kirim `STOP_TIMER` + `UNLOCK_SCREEN`.
5. Tombol **PAUSE** baru di kartu TV → `PAUSE_TIMER` / `RESUME_TIMER`.
6. Tombol **VIDEO / GAMBAR / LOGO** (Row 3) → salin file ke `media_promo/`
   (VIDEO/GAMBAR kirim `SHOW_MEDIA`; LOGO menyimpan `logo_lock.png` — global,
   tanpa ADB/port 5555, dipakai lockscreen saat waktu sewa habis).
7. Badge **CLI✓/CLI✗** di header kartu (refresh 5 dtk) + tombol **APK**
   (cek terpasang via ADB & install).
8. Media aktif ikut di-resync saat client reconnect (`state_extra`).

Config opsional di `rr_billing_config.json`:

```json
{
  "tv_ws_enabled": true,
  "warnet_tv_ws_port": 8080,
  "warnet_tv_api_port": 8081,
  "warnet_media_port": 8082
}
```

## Protokol WebSocket (ws://<ip-kasir>:8080)

Semua pesan JSON (`ensure_ascii=False` → teks Indonesia aman).

### Server → Client TV

**a. Mulai / Update timer (juga saat tambah waktu):**
```json
{
  "action": "START_TIMER",
  "meja_id": "TV 1",
  "sisa_detik": 3600,
  "nama_rental": "RR Billing Pro",
  "total_tagihan": "Rp 6.000"
}
```
`sisa_detik: -1` = mode **Main Bebas** (client menampilkan `∞` tanpa countdown).

**b. Pause / Lanjut:**
```json
{ "action": "PAUSE_TIMER",  "meja_id": "TV 1" }
{ "action": "RESUME_TIMER", "meja_id": "TV 1", "sisa_detik": 3550 }
```

**c. Selesai manual (sembunyikan overlay):**
```json
{ "action": "STOP_TIMER", "meja_id": "TV 1" }
```

**d. Waktu habis / Lock screen:**
```json
{
  "action": "LOCK_SCREEN",
  "pesan": "WAKTU SEWA HABIS",
  "detail_transaksi": {
    "meja": "TV 1",
    "sewa": "Paket 1 Jam",
    "sewa_harga": "Rp 10.000",
    "makanan": [{"item": "1x Jus Mangga", "harga": "Rp 12.000"}],
    "minuman": [],
    "fnb": "Rp 12.000",
    "total": "Rp 22.000",
    "logo_url": "http://<ip-kasir>:8082/media/logo_lock.png",
    "promo_url": "http://<ip-kasir>:8082/media/iklan.mp4"
  }
}
```
- `sewa`, `sewa_harga`, `makanan[]`, `minuman[]`, `fnb`, `total` — rincian
  tagihan **lengkap**, dikirim **langsung saat waktu habis** (tidak menunggu
  admin klik OK pada dialog kasir).
- `logo_url` — logo lock screen global (bisa diganti kasir via tombol
  **"🖼 LOGO"** di kartu TV atau **"🖼 Ganti Logo Lock"** di remote dialog;
  file disimpan sebagai `media_promo/logo_lock.png`). URL memakai cache-buster
  (`logo_lock.png?v=<mtime>`) sehingga setiap penggantian logo menghasilkan URL
  baru. Client memakai logo bawaan APK bila kosong.
- `promo_url` — video promosi aktif (dari `TvMediaServer.current_media`).
  Saat TV **bangun dari tidur** dalam keadaan terkunci, client memutar video
  ini **1x** lalu otomatis pindah ke port/input terakhir yang dipakai
  (`tv_last_used_input_id`).

Alur tidur TV saat waktu habis:
1. Waktu habis → `LOCK_SCREEN` (dengan rincian + logo + promo) dikirim segera.
2. Dialog "Waktu TV Habis" muncul di kasir; setelah admin klik **OK**,
   server mengirim `STOP_TIMER` + `UNLOCK_SCREEN` (lockscreen ditutup — sama
   seperti tombol SELESAI), lalu perintah ADB `power_toggle` → **TV sleep** (±2
   detik). Selama admin belum klik OK, TV tetap terkunci.
3. Saat user membangunkan TV → video promosi diputar 1x (walau app sudah
   di-unlock, selama `promo_url` masih terisi) → pindah ke input terakhir
   (mis. port PlayStation) sebelum TV tidur. **Lockscreen "WAKTU SEWA HABIS"
   tidak muncul lagi** di alur bangun-tidur — hanya muncul saat paket habis
   (dan dikonfirmasi kasir).

**e. Buka kunci:**
```json
{ "action": "UNLOCK_SCREEN", "meja_id": "TV 1" }
```

**f. Heartbeat** (server → client tiap 5 detik; client balas `PONG`):
```json
{ "action": "PING", "timestamp": 1785592117 }
```

**g. Media promosi (video/gambar):**
```json
{ "action": "SHOW_MEDIA", "meja_id": "TV 1", "type": "video", "url": "http://192.168.1.100:8082/media/iklan.mp4" }
{ "action": "HIDE_MEDIA", "meja_id": "TV 1" }
```
`type`: `video` (mp4/webm/3gp — diputar looping fullscreen) atau `image`
(jpg/png/gif/webp — ditampilkan fullscreen). URL mengarah ke `TvMediaServer`
(port 8082) di mesin kasir; media aktif dikirim ulang otomatis saat client
reconnect.

**h. Ganti logo lock (kasir → TV, broadcast):**
```json
{ "action": "UPDATE_LOGO", "meja_id": "TV 1", "logo_url": "http://192.168.1.100:8082/media/logo_lock.png?v=1785592117" }
```
Dikirim ke **semua TV terhubung** setiap kasir mengganti logo (tombol LOGO di
kartu / Ganti Logo Lock di remote). TV yang sedang menampilkan lockscreen
langsung me-refresh logonya tanpa menunggu waktu sewa habis berikutnya. TV yang
tidak terkunci akan memakai logo baru otomatis saat LOCK_SCREEN berikutnya
(URL cache-busted memastikan file terbaru selalu diunduh).

### Client TV → Server

```json
{ "type": "REGISTER", "meja_id": "TV 1", "device": "android_tv", "nama": "TV 1" }
{ "type": "PONG" }
{ "type": "GET_TVS" }
{ "type": "SCREEN_STATE", "meja_id": "TV 1", "screen_on": true }
```

- **`SCREEN_STATE`** — status layar TV (hidup/mati) yang dilaporkan APK sendiri:
  dikirim saat TV nyala (`ACTION_SCREEN_ON`), saat mati (`ACTION_SCREEN_OFF`),
  dan sekali lagi saat koneksi WebSocket (re)connect (menggunakan
  `PowerManager.isInteractive`). Ini sumber status **paling akurat** untuk
  dashboard kasir — tidak memerlukan ADB port 5555.

Saat REGISTER, server membalas `REGISTERED` + mengirim ulang state terakhir
(`START_TIMER` dengan sisa waktu terkini, `LOCK_SCREEN`, atau `STOP_TIMER`) —
jadi TV yang baru nyala / koneksinya putus langsung sinkron.

## Status TV di Dashboard Kasir

Prioritas penentuan status **HIDUP/MATI** di kartu TV (diperbarui tiap 10 dtk):

1. **WebSocket `SCREEN_STATE`** dari APK (paling akurat) → `📺 HIDUP` / `📺 MATI`
2. Fallback: remote atpv2 `is_on` → ADB `dumpsys power` (mWakefulness=Awake)
3. Belum ada sumber sama sekali → **`📺 ?`** abu-abu (bukan label basi)

Dot **ONLINE** hijau bila APK terhubung WebSocket (`is_meja_connected`), walau
port ADB 5555 ditutup; TCP ping 5555 hanya fallback saat APK tidak terhubung.

## Auto-Off TV Tanpa Paket Aktif (Anti-Kasir Nakal)

Tujuan: mematikan TV yang menyala tapi **tidak ada paket/sewa aktif**, agar
kasir tidak bisa memberi main gratis tanpa dimasukkan ke penjualan.

Cara kerja (server, poller tiap 30 dtk):

1. Status layar dibaca dari `SCREEN_STATE` APK (bukan ADB). Status tak
   diketahui → tidak bertindak (aman).
2. TV **menyala** + **tidak ada sesi aktif** (`sesi_kosong()`) → counter
   `idle_on_seconds` bertambah.
3. Ambang:
   - **Pertama kali**: `tv_auto_off_first_minutes` (default **10 menit**).
   - **Setelah pernah di-auto-mati**: `tv_auto_off_minutes` (default **5 menit**)
     — berlaku sampai paket sah dibuka lagi.
4. Saat ambang tercapai → server mengirim perintah **sleep TV**:
   remote atpv2 `turn_off` (tidak butuh ADB 5555) → fallback
   `adb shell input keyevent 26`.
5. **Audit log** (`AuditLogger`, file `audit_*.jsonl`): action `TV_AUTO_OFF`
   berisi label TV, IP, durasi idle, jam — bukti untuk owner.
6. **Reset**: paket sah dibuka (START_TIMER) → counter nol & kembali ke ambang
   10 menit. Layar mati → counter nol (ambang tetap).

Config di `rr_billing_config.json`:

```json
{
  "tv_auto_off_enabled": true,
  "tv_auto_off_first_minutes": 10,
  "tv_auto_off_minutes": 5
}
```

`tv_auto_off_enabled: false` → fitur nonaktif total (mis. saat setting TV).

## REST API Test (http://<ip-kasir>:8081)

| Method | Endpoint | Body (JSON) |
|---|---|---|
| POST | `/api/start-billing` | `{"meja_id":"TV 1","sisa_detik":3600,"total_tagihan":6000}` |
| POST | `/api/stop-billing` | `{"meja_id":"TV 1"}` |
| POST | `/api/pause-billing` | `{"meja_id":"TV 1"}` |
| POST | `/api/resume-billing` | `{"meja_id":"TV 1","sisa_detik":3550}` |
| POST | `/api/lock` | `{"meja_id":"TV 1","pesan":"WAKTU SEWA HABIS","sewa":"Paket 1 Jam","fnb":"Rp 0","total":"Rp 6.000"}` |
| POST | `/api/unlock` | `{"meja_id":"TV 1"}` |
| GET | `/api/tvs` | — (daftar TV terhubung) |
| GET | `/health` | — (status hub) |

Contoh curl:

```bash
curl -X POST http://127.0.0.1:8081/api/start-billing ^
  -H "Content-Type: application/json" ^
  -d "{\"meja_id\":\"TV 1\",\"sisa_detik\":600,\"total_tagihan\":6000}"
```

## Uji Tanpa Android (simulasi client TV)

```
python tools\tv_ws_test.py --host 192.168.1.100 --meja "TV 1"
```

Semua pesan dari kasir akan dicetak di konsol. Tekan Ctrl+C untuk keluar.

## Alur Penggunaan Nyata

1. Kasir membuka paket untuk `TV 1` → client menampilkan overlay countdown.
2. Waktu ≤ 2 menit → countdown di kartu kasir berkedip (perilaku lama tetap ada).
3. Waktu habis → `LOCK_SCREEN` (rincian lengkap + logo + promo) dikirim
   langsung → TV menampilkan lockscreen fullscreen (user tidak bisa keluar;
   tombol BACK/HOME diblokir).
4. Kasir klik **OK** pada dialog "Waktu TV Habis" → TV di-unlock (lockscreen
   ditutup) lalu masuk **mode sleep** otomatis (ADB). Saat TV dibangunkan,
   video promosi diputar 1x lalu pindah ke input terakhir yang dipakai —
   tanpa lockscreen.
5. Kasir menerima pembayaran lanjutan → buka paket lagi → `START_TIMER` dikirim
   → lockscreen tertutup, overlay muncul lagi dengan waktu baru.
6. Kasir klik **SELESAI** → `STOP_TIMER` + `UNLOCK_SCREEN` → TV kembali normal
   (SELESAI juga memicu sleep TV via ADB).

## Firewall Windows

Pastikan port `8080` (WebSocket), `8081` (REST test) dan `8082` (media) terbuka
di firewall Windows bila TV terhubung lewat jaringan berbeda:

```
netsh advfirewall firewall add rule name="RR TV WS 8080" dir=in action=allow protocol=TCP localport=8080
netsh advfirewall firewall add rule name="RR TV API 8081" dir=in action=allow protocol=TCP localport=8081
netsh advfirewall firewall add rule name="RR TV MEDIA 8082" dir=in action=allow protocol=TCP localport=8082
```

## Troubleshooting

| Gejala | Penyebab / Solusi |
|---|---|
| TV tidak muncul di `GET /api/tvs` | IP TV tidak bisa menjangkau PC kasir; cek firewall; pastikan port 8080; cek `[TV WS HUB]` di konsol kasir. |
| Status TV selalu "📺 ?" | APK belum versi baru (yang mengirim `SCREEN_STATE`); install ulang APK build terbaru. |
| Overlay tidak muncul padahal TV terhubung | Izin **Display over other apps** belum diberikan di STB. |
| Lockscreen tidak tampil | Pastikan `detail_transaksi` terkirim; cek log hub di konsol kasir. |
| Tombol HOME masih bisa keluar dari lock | Aplikasi belum dijadikan **Aplikasi beranda** (lihat README Android). |
| Koneksi sering putus | STB hemat daya; nonaktifkan *battery optimization* untuk RR Billing TV. |
