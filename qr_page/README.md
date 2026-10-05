# QR Panggil Kasir + Login Member — Halaman Web Pelanggan

Halaman statis di-deploy ke **Firebase Hosting** (project `rrbillingpro`):
- `https://rrbillingpro.web.app/call.html` — Panggil Kasir
- `https://rrbillingpro.web.app/member.html` — Login Member via QR

## 1. call.html — QR Panggil Kasir (tidak berubah)

QR kasir menunjuk ke `.../call.html?tv=<TV>&k=<kode>&o=<owner>`.
Pelanggan scan → pilih layanan (keluhan / tambah paket / pesan makan & minum)
→ kirim. Dokumen masuk tabel Supabase `calls`; aplikasi kasir mem-poll
setiap 6 detik → popup + bunyi bel + rate-limit 90 detik per TV.

## 2. member.html — Mulai Sesi Member dari HP Pelanggan

Alur:
1. Kasir tekan tombol **👤 MEMBER** pada kartu TV (atau 📷 Via QR di DialogPaket).
2. TV menampilkan overlay QR: QR di kiri ¼ layar, kanan panel info rental +
   video gambar bergerak. QR berisi URL:
   `.../member.html?tv=<TV>&k=<kode>&o=<owner>&g=<grup>`
3. Pelanggan scan → mengetik **nama member** → halaman menampilkan sisa waktu
   per grup (grup TV ditandai "dipakai").
4. Pelanggan mengetik **PIN** → kasir memvalidasi:
   - nama tidak ada → "ID tidak ditemukan"
   - nama dipakai >1 member → "Nama dipakai lebih dari satu member"
   - PIN salah → "PIN anda masukkan salah" (maks 5× percobaan)
   - saldo grup TV tidak cukup → "Saldo tidak cukup"
   - member sedang main di kartu lain → "sedang aktif di <TV>"
   - benar → sesi member berjalan otomatis di TV tersebut.

Dokumen sesi memakai tabel **`qr_sessions`** yang sama dengan QR Panggil
Kasir, dengan status berawalan `mem_` agar tidak tertangkap poller PIN biasa:

| status | makna |
|---|---|
| `mem_await` | QR tampil, menunggu nama pelanggan |
| `mem_saldo` | nama valid, saldo dikirim, menunggu PIN |
| `mem_ok` | PIN benar → sesi berjalan |
| `mem_notfound` / `mem_ambigu` / `mem_badpin` / `mem_nosaldo` / `mem_busy` | gagal, pesan tampil di halaman |
| `mem_cancel` / `mem_expired` / `mem_blocked` | dibatalkan kasir / lewat 5 menit / PIN salah 5× |

Kolom yang dipakai: `id` (id sesi), `tv`, `kode`, `owner`, `status`,
`pin` (jawaban JSON kasir), `pin_user` (permintaan JSON pelanggan:
`{"n": nama, "p": pin}`), `tries` (percobaan PIN), `created`.

**Tidak perlu tabel baru** — RLS `qr_sessions` sudah mengizinkan
insert/update/select dengan anon key.

## Deploy (perubahan halaman web)

```powershell
cd qr_page
firebase deploy --only hosting
```

`firebase.json` sudah diberi rewrite khusus `/member.html` supaya tidak ikut
dialihkan ke `call.html`.

Media server lokal (port 8082) juga menyajikan salinan sebagai cadangan:
`http://<ip-kasir>:8082/qr/member.html`, dan PNG QR di
`http://<ip-kasir>:8082/qr/member_<sid>.png`.

## Verifikasi

- Panggil Kasir: buka `https://rrbillingpro.web.app/call.html?tv=TV+1&k=TEST1234`
- Member: klik 👤 MEMBER di kartu TV, scan QR yang tampil di TV, halaman harus
  terbuka dan nama+PIN berfungsi.

## Catatan keamanan
- PIN member dikirim lewat kolom `pin_user` (sama seperti alur PIN Panggil
  Kasir yang sudah berjalan). Nilai ini bukan rahasia absolut — tapi dengan
  kode sekali-pakai per sesi, PIN hanya berlaku untuk 1 TV dan 5 menit.
- Data member (nama, saldo) TIDAK disimpan di cloud: hanya dikirim balik ke
  halaman pelanggan untuk sesi yang sedang berjalan.
- Kalau kasir offline, halaman akan menunggu (loading) sampai kasir online lagi.
