# Kompatibilitas Video Promosi - SEMUA Android TV

Dokumen ini menjelaskan strategi agar video promo **tidak pernah gagal** diputar di
TV Android mana pun: semua merk, semua versi Android, semua SoC (chipset).

## Strategi 3 lapis

| Lapisan | Apa yang dilakukan | Mengatasi apa |
|---|---|---|
| 1. Server media (kasir) | HEAD/Range/206/keep-alive/Content-Length, URL-encode, sniff Content-Type, honor Connection: close | Perbedaan perilaku HTTP MediaPlayer antar versi Android |
| 2. Normalisasi video (ffmpeg di kasir) | Video otomatis dikonversi ke **MP4 H.264 Main L4.0 + yuv420p + <=1080p30 + AAC 128k stereo + faststart** | Codec/audio/resolusi yang tidak dimiliki decoder SoC lama (HEVC/VP9/AV1/AC3/DTS/4K/HDR/10-bit) |
| 3. Client TV (APK) | ExoPlayer (media3) + retry otomatis + kode error di layar | Player paling tahan banting, dipakai Netflix/YouTube di Android TV |

**Format target (satu-satunya yang dijamin jalan di SEMUA Android 4.x-14):**

```
container : MP4 (moov di depan / faststart)
video     : H.264 Main Profile, level 4.0, yuv420p (8-bit 4:2:0), <= 1920x1080, <= 30 fps
audio     : AAC-LC 128 kbps stereo 48 kHz (atau MP3), boleh tanpa audio
```

## Matriks merk TV Android

Semua merk Android TV menjalankan AOSP MediaPlayer (sekarang ExoPlayer via APK ini),
sehingga perilaku ditentukan oleh **versi Android + chipset**, bukan merk. Namun
catatan khusus per merk/pabrikan:

| Merk / Perangkat | Android | Catatan khusus |
|---|---|---|
| Google Chromecast w/ Google TV, Nvidia Shield | 12-14 | Decoder lengkap; jarang bermasalah |
| Sony Bravia | 9-12 | NuPlayer standar; HEAD/Range fix sudah menutup |
| TCL (Google TV & Android TV) | 9-13 | Beberapa seri pakai custom video settings; aman |
| Xiaomi Mi TV / Mi Box S | 9-11 | Mi Box S (Amlogic) mulus H.264; HEVC ada |
| Sharp Android TV | 9-11 | Standar AOSP |
| Philips Android TV | 9-12 | Standar AOSP; energi saving bisa matikan service - jaga app di recent |
| Hisense (Android TV) | 9-11 | Standar AOSP |
| Skyworth / Coocaa | 9-11 | Standar AOSP |
| Panasonic / Toshiba (Android TV) | 9-11 | Standar AOSP |
| Vizio (Android TV) | 9-10 | Standar AOSP |
| Dahua 4K (yang dipakai tes) | 14 | Sudah terverifikasi jalan |
| STB murah Amlogic (S905/S912) | 6-11 | H.264 OK, HEVC Main 8-bit sebagian; **tanpa AC3/DTS**; tanpa HDR |
| STB Rockchip (RK3229/RK3328) | 7-11 | H.264 OK; HEVC 10-bit TIDAK; **tanpa AC3/DTS** |
| STB Allwinner (H3/H616) | 6-11 | H.264 OK; HEVC terbatas |
| STB HiSilicon | 5-9 | H.264 OK |
| Box tua Android 4.4-6 | 4.4-6 | H.264 + AAC saja; butuh faststart; HEAD/Range penting |

### Perilaku player per era Android (kenapa dulu gagal)

| Android | Perilaku HTTP player | Dulu masalahnya |
|---|---|---|
| 4.x - 6.x | Kirim HEAD dulu untuk cek ukuran/tipe; lalu GET + Range seek | Server lama jawab 501 di HEAD -> gagal total |
| 7.x - 10.x | HEAD/Range aktif; decoder HEVC bervariasi | Sama; plus codec video eksotik tidak terbaca |
| 11 | NuPlayer matang; masih kirim HEAD/Range | HEAD fix menutup |
| 12 - 14 | HTTP source sangat toleran; decoder modern | Jarang masalah (mengapa Dahua 14 jalan) |

### Kenapa video HEVC/4K/HDR gagal di Android 11 ke bawah

Video hasil rekam HP modern hampir selalu **HEVC (H.265)**, kadang **10-bit**,
**4K**, **HDR10**, atau audio **AC3/DTS** (dari rekam TV). Decoder codec ini
**tidak diwajibkan** Android untuk perangkat lama, dan STB murah tidak
membelinya karena lisensi. Akibatnya MediaPlayer gagal di API <31 sementara
box baru (Dahua 14) mulus -> persis pola error yang pernah terjadi.

## Cara kerja normalisasi (kasir)

Saat kasir menekan tombol VIDEO dan memilih file:

1. `ffprobe` (via ffmpeg) menganalisis codec/resolusi/fps/audio/posisi moov.
2. Sudah sesuai target + faststart -> file dikirim langsung (tanpa proses).
3. Hanya moov di belakang -> `ffmpeg -c copy -movflags +faststart` (detik).
4. Lainnya -> transcode penuh (progress bar di layar kasir, bisa dibatalkan).
5. Gagal/batal -> file asli tetap dikirim + peringatan.

Output selalu disimpan dengan akhiran `_tv.mp4` di `media_promo/`.

## Tooling verifikasi

```bash
# 1) Server lolos semua pola request MediaPlayer lintas versi (wajib sebelum rilis)
python tools/media_flow_test.py

# 2) Cek video tertentu aman atau tidak untuk semua TV
python tools/check_video.py "path/video.mp4"
```

## Checklist tes lapangan (setelah update v2.4.0)

- [ ] Kasir sudah versi v2.4.0 (cek pojok bawah halaman login)
- [ ] APK baru (ExoPlayer) terpasang di TV (sideload `RRBillingTV.apk`)
- [ ] Pilih video hasil HP (HEVC) -> kasir menampilkan progress konversi -> terkirim
- [ ] Video diputar 1x lalu TV pindah ke input/port terakhir
- [ ] Uji di setidaknya: 1 TV Android 11 ke bawah (yang dulu gagal) + 1 TV Android 12+
- [ ] Ganti logo lock tetap berfungsi (gambar tidak ikut dikonversi)
- [ ] Jika ada TV yang masih gagal: catat **kode error di layar TV** (fitur ExoPlayer)
      lalu laporkan - kode error menunjukkan penyebab pasti (codec vs jaringan vs server)
