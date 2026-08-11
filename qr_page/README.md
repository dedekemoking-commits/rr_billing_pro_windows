# QR Panggil Kasir — Halaman Web Pelanggan

Halaman statis di-deploy ke **GitHub Pages**:
`https://dedekemoking-commits.github.io/rrbilling-callpage/call.html`

QR yang dicetak kasir menunjuk ke alamat itu dengan parameter:
`.../call.html?tv=<TV>&k=<kode>&o=<owner>`

Pelanggan scan QR (jaringan mana pun — WiFi rental maupun data seluler),
pilih layanan (keluhan / tambah paket / pesan makan & minum), lalu kirim.
Dokumen masuk Firestore collection `calls`; aplikasi kasir mem-poll-nya
setiap 3 detik → popup + bunyi bel + rate-limit 90 detik per TV.

## Status deploy (selesai)
- Repo: `dedekemoking-commits/rrbilling-callpage` (public)
- Pages aktif: `https://dedekemoking-commits.github.io/rrbilling-callpage/call.html`
- Update halaman: push commit baru ke branch `main` (Pages build otomatis).

## MASIH HARUS DILAKUKAN (sekali saja, di akun pemilik Firebase)
Set **Firestore rules** di Firebase Console → Project `rrbillingpro`
→ Firestore → Rules → tempel isi `firestore.rules` → **Publish**.

Tanpa rules ini, collection `calls` dan `call_meta` masih tertutup
(default deny) — panggilan tidak bisa masuk dan menu tidak tampil.

## Verifikasi
- Buka
  `https://dedekemoking-commits.github.io/rrbilling-callpage/call.html?tv=TV+1&k=TEST1234`
  → halaman tampil.
- Buka tombol QR di kartu TV → scan → panggilan harus masuk ke kasir.

## Catatan keamanan
- `calls` boleh ditulis siapa pun; validasi ada di aplikasi kasir:
  kode unik per TV + rate-limit 90 detik. Gelokan QR TV lain tidak valid
  untuk TV ini.
- `call_meta` boleh ditulis Firebase user login (halaman web & kasir pakai
  auth anonim). Menu bukan data rahasia; kasir mengirim ulang setiap 5 menit.
- QR berfungsi selama kasir ONLINE. Jika kasir offline, panggilan menunggu
  di `calls` dan muncul setelah aplikasi kembali online.