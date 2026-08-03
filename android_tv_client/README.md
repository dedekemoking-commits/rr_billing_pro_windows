# RR Billing TV — Android Client (Floating Overlay Timer & Lockscreen)

Aplikasi Android (Kotlin) untuk Smart TV / Android Box / STB. Menampilkan
**Floating Overlay Widget** (sisa waktu sewa) di atas game/aplikasi lain dan
**Lockscreen fullscreen** saat waktu habis — dikontrol realtime dari server
kasir (RR Billing Pro) lewat WebSocket.

```
Kasir (main.py) ──ws://:8080──►  Android TV / STB
  START_TIMER / PAUSE_TIMER / RESUME_TIMER / STOP_TIMER / LOCK_SCREEN / UNLOCK_SCREEN / SHOW_MEDIA / HIDE_MEDIA / PING
```

## Struktur Project

```
android_tv_client/
├── settings.gradle / build.gradle / gradle.properties
├── gradle/wrapper/              ← Gradle 8.7 (wrapper siap pakai)
└── app/src/main/
    ├── AndroidManifest.xml
    ├── java/com/rrbillingpro/tvclient/
    │   ├── MainActivity.kt            # setup: IP server, port, meja_id
    │   ├── BootReceiver.kt            # autostart service saat boot (opsional)
    │   ├── service/TvOverlayService.kt# Foreground Service (inti)
    │   ├── net/WebSocketManager.kt    # OkHttp WS + auto-reconnect
    │   ├── net/TimerEngine.kt         # countdown HH:MM:SS
    │   ├── overlay/OverlayWidget.kt   # WindowManager overlay (top-right, neon)
    │   ├── lockscreen/LockScreenActivity.kt  # lockscreen fullscreen
    │   ├── media/MediaActivity.kt     # pemutar video/gambar promosi fullscreen
    │   ├── model/Protocol.kt          # parsing JSON protokol
    │   └── util/Prefs.kt              # SharedPreferences
    └── res/layout/  activity_main.xml, overlay_view.xml, activity_lock_screen.xml, activity_media.xml
```

## Build

Butuh: JDK 17 + Android SDK (compileSdk 34). Semua sudah tersedia di mesin ini.

```
cd android_tv_client
gradlew.bat assembleDebug
```

Hasil: `app/build/outputs/apk/debug/app-debug.apk` (~1,4 MB).

## Install ke Android TV / STB

```
adb connect <IP-STB>:5555        # bila belum terhubung via ADB
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

Tanpa ADB: salin APK ke flashdisk, install lewat file manager STB.

## Setup Awal di STB

1. Buka aplikasi **RR Billing TV**.
2. Isi **IP Server Kasir** (PC tempat main.py berjalan), **Port** (default `8080`),
   dan **ID Meja** — **harus sama persis dengan nama TV di dashboard kasir**
   (misal `TV 1`).
3. Tekan **SIMPAN & MULAI OVERLAY**.
4. Tekan **IZIN OVERLAY** dan izinkan ("Display over other apps") — wajib agar
   widget sisa waktu muncul di atas game.
5. (Agar tombol HOME tidak bisa keluar dari lock) jadikan aplikasi ini
   **Aplikasi beranda**:
   - Menu STB: *Settings → Apps → Default apps → Home app → RR Billing TV*
   - atau via ADB:
     ```
     adb shell cmd package set-home-activity com.rrbillingpro.tvclient/.lockscreen.LockScreenActivity
     ```

## Cara Kerja

| Pesan dari kasir | Reaksi di TV |
|---|---|
| `START_TIMER` | Overlay muncul di kanan atas (nama rental, meja, countdown neon, tagihan). `sisa_detik:-1` = mode Main Bebas (`∞`). |
| `PAUSE_TIMER` / `RESUME_TIMER` | Countdown pause/lanjut (tanpa menutup overlay). |
| `STOP_TIMER` | Overlay hilang (sesi selesai manual / lock dibuka). |
| `LOCK_SCREEN` | Overlay hilang, Lockscreen fullscreen muncul (logo, meja, rincian tagihan). Tombol BACK/HOME/APP_SWITCH diblokir. |
| `UNLOCK_SCREEN` | Lockscreen tertutup, kembali ke aplikasi yang sedang berjalan. |
| `SHOW_MEDIA` | Buka `MediaActivity` fullscreen: video (looping) atau gambar dari URL kasir (`http://<kasir>:8082/media/...`). |
| `HIDE_MEDIA` | Tutup media promosi. |
| `PING` (tiap 5 dtk) | Heartbeat server → client (OkHttp auto-pong). |

Jika koneksi WebSocket putus (Wi-Fi mati dsb.), service otomatis **reconnect**
(backoff 2→10 detik) dan server kasir mengirim ulang state terakhir saat
client tersambung kembali (termasuk media promosi yang sedang tampil).

## Media Promosi (Video/Gambar)

Dari dashboard kasir: klik tombol **VIDEO** / **GAMBAR** pada kartu TV untuk
mengirim video/gambar promosi ke client — file disalin ke folder `media_promo/`
di mesin kasir dan diputar/ditampilkan **fullscreen looping** di TV.
Klik **✕MEDIA** untuk menyembunyikan. Format didukung:

- Video: `mp4`, `webm`, `3gp` (MKV tidak didukung player bawaan Android).
- Gambar: `jpg`, `png`, `gif`, `webp`, `bmp`.

Client menarik file dari `http://<ip-kasir>:8082/media/<file>` (TvMediaServer).
Pastikan port `8082` terbuka di firewall kasir. Media yang sedang tampil
otomatis dikirim ulang saat client reconnect.

## Tetap Berjalan Saat TV di Input HDMI Lain

Service client memegang **partial wake lock** + **wifi lock** sehingga proses
tetap berjalan (timer + koneksi WebSocket + lock screen) meski layar TV dialihkan
ke port HDMI lain atau display mati. Saat kembali ke input STB, overlay/lock
langsung tampil lagi. Lampu power STB mati = STB mati total, aplikasi tidak
bisa dihidupkan dari jarak jauh.

## Izin di AndroidManifest

| Izin | Fungsi |
|---|---|
| `INTERNET` + `ACCESS_NETWORK_STATE` | Koneksi WebSocket ke kasir |
| `SYSTEM_ALERT_WINDOW` | Overlay di atas aplikasi lain (diberi manual lewat tombol **IZIN OVERLAY**) |
| `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_SPECIAL_USE` | Service tetap hidup walau game terbuka (wajib targetSdk 34) |
| `POST_NOTIFICATIONS` | Notifikasi service (Android 13+) |
| `WAKE_LOCK` | Layar tetap nyala saat lockscreen; **partial wake lock** agar service tetap jalan saat TV di input HDMI lain |
| `ACCESS_WIFI_STATE` | Wifi lock (jaringan tetap hidup saat display mati) |
| `RECEIVE_BOOT_COMPLETED` | Autostart service saat STB dinyalakan |

Catatan: pada sebagian STB Android TV versi lama, halaman izin overlay
(`Settings.ACTION_MANAGE_OVERLAY_PERMISSION`) tidak tersedia — alternatifnya
izinkan via `adb shell appops set com.rrbillingpro.tvclient SYSTEM_ALERT_WINDOW allow`.

## Catatan Keamanan / Pembatasan

- Memblokir **HOME** hanya berfungsi jika aplikasi dijadikan **Aplikasi
  beranda** (lihat setup). Tanpa itu, tombol HOME tetap bisa keluar dari lock
  (BACK tetap terblokir).
- `Ctrl+Alt+Del` / tombol *power* / factory reset tidak bisa diblokir oleh
  aplikasi biasa — itu di luar batas Android.
- Jika STB mematikan service karena hemat daya, nonaktifkan *battery
  optimization* untuk RR Billing TV (Settings → Apps → Battery).
