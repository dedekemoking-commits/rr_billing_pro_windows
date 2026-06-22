Panduan rilis otomatis (GitHub Releases) dan update otomatis

1) Hasilkan pasangan kunci RSA (jalankan secara lokal):
   python scripts/generate_rsa_keys.py --out-dir keys
   - File keys/private_key.pem (jangan commit) — isi GitHub Secret: SIGNING_PRIVATE_KEY
   - File keys/public_key.pem  (commit ke repo sebagai update_pubkey.pem)

2) Tambahkan Secret di GitHub:
   - SIGNING_PRIVATE_KEY: isi dengan konten PEM private key (-----BEGIN PRIVATE KEY-----...)

3) Pastikan release workflow ada (.github/workflows/release.yml). Cara rilis:
   - Buat tag: git tag v2.1.1 && git push origin v2.1.1
   - Workflow akan build EXE, hitung sha256, upload asset, buat manifest.json yang ditandatangani, dan upload manifest ke Release.

4) Distribusi klien:
   - Sertakan update_pubkey.pem (public key) di paket aplikasi atau set path di config 'update_pubkey_path'.
   - Aplikasi akan mem-fetch manifest.json, verifikasi signature dengan public key, unduh asset, verifikasi sha256, lalu jalankan updater_helper.py untuk mengganti executable.

5) Keamanan & tips:
   - Private key hanya di mesin yang dipercaya. Simpan di secret manager, jangan commit.
   - Pertimbangkan kode signing Authenticode (signtool) untuk menghindari SmartScreen.
   - Uji di VM bersih sebelum rilis publik.
