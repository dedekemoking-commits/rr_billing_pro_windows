Panduan singkat: Enkripsi data at-rest (Windows DPAPI)

1) Instal dependensi:
   - Aktifkan virtualenv, lalu jalankan:
     pip install -r requirements.txt
   - Jika masalah, jalankan: pip install pywin32
   - Jika diminta, jalankan postinstall: python -m pywin32_postinstall -install

2) Catatan penggunaan:
   - Kunci master disimpan terenkripsi di %APPDATA%\\RRBilling\\data_key.bin oleh Windows DPAPI.
   - Jangan commit file data_key.bin ke repositori.
   - Atur izin folder agar hanya user yang dapat mengakses:
     icacls "%APPDATA%\\RRBilling" /inheritance:r
     icacls "%APPDATA%\\RRBilling" /grant:r "%USERNAME%:(OI)(CI)F"
   - Gunakan atomic write ketika menyimpan kunci (rr_crypto telah menggunakan write dan rename pattern).
   - Untuk produksi multi-host, gunakan Cloud KMS karena DPAPI terikat ke user/machine.

3) Migrasi:
   - Jalankan tool migrasi untuk mere-enkripsi file plaintext. Contoh:
     python scripts/migrate_plaintext_configs.py C:\\path\\to\\project

4) Key rotation & backup:
   - Backup DPAPI blob: skrip akan menyimpan salinan %APPDATA%\\RRBilling\\data_key.bin ke folder backups.
   - Rotasi kunci: python scripts/key_rotate.py C:\\path\\to\\project

5) Secure deletion & permissions:
   - Skrip secure_delete.py menyertakan fungsi overwrite+hapus. Tidak 100% efektif pada beberapa filesystem.

6) Multi-host/Server:
   - DPAPI terikat ke user/machine. Untuk multi-host produksi gunakan Cloud KMS (AWS KMS, Azure Key Vault, GCP KMS)."}