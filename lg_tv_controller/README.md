# LG TV Controller — Test Tool

Kontrol LG Smart TV (webOS 22) via LAN/Wi-Fi untuk sistem billing.

## Fitur

- **Power ON** — Nyalakan TV via Wake-on-LAN (WOL)
- **Power OFF** — Matikan TV via WebSocket (standby)
- **Toast Message** — Tampilkan popup peringatan di layar TV
- **Check Status** — Cek status power TV (menyala/mati)

## Persiapan

### 1. Pastikan Python Terinstall

Buka Command Prompt / Terminal, ketik:

```
python --version
```

Jika muncul `Python 3.x.x`, berarti sudah terinstall.
Jika belum, download dari https://www.python.org/downloads/

### 2. Cari MAC Address TV

Di LG TV:
- **Settings → General → About This TV → MAC Address**

Atau di komputer (Command Prompt):

```
arp -a | findstr 192.168.1
```

### 3. Aktifkan Wake-on-LAN di TV

Di LG TV:
- **Settings → General → SIMPLINK (HDMI-CEC)** → nyalakan

## Cara Jalankan

### Windows

1. Klik ganda `setup.bat`
2. Tunggu sampai dependencies terinstall
3. Aplikasi test akan terbuka

### Linux/Mac

```bash
chmod +x setup.sh
./setup.sh
```

### Manual

```bash
pip install -r requirements.txt
python test_tv_controller.py
```

## Cara Pakai

1. Masukkan **MAC Address** TV di field yang tersedia
2. Masukkan **IP Address** TV di jaringan lokal
3. Klik tombol aksi:
   - **POWER ON** — Menyalakan TV via WOL
   - **CEK STATUS** — Mengecek status power TV
   - **TOAST MESSAGE** — Mengirim popup ke layar TV
   - **POWER OFF** — Mematikan TV

## Pairing Pertama Kali

Saat pertama kali connect ke TV (klik CEK STATUS atau TOAST):

1. Popup pairing akan muncul di layar TV
2. Tekan **Allow** atau **OK** di remote TV
3. Pairing key otomatis tersimpan di file `.aiopylgtv.sqlite`
4. Koneksi berikutnya tidak perlu pairing lagi

## Troubleshooting

| Masalah | Solusi |
|---------|--------|
| "Connection refused" | TV mati atau IP salah. Cek IP TV |
| "Timeout" | TV belum menyala. Cek koneksi jaringan |
| Toast tidak muncul | TV perlu pairing dulu. Klik CEK STATUS dulu |
| WOL tidak works | Pastikan SIMPLINK/HDMI-CEC aktif di TV |

## File

- `tv_controller.py` — Core library
- `test_tv_controller.py` — GUI test aplikasi
- `requirements.txt` — Python dependencies
- `setup.bat` — Setup otomatis (Windows)
- `setup.sh` — Setup otomatis (Linux/Mac)
- `.aiopylgtv.sqlite` — Auto-generated pairing key (jangan hapus)
- `tv_controller_config.json` — Auto-generated config tersimpan
