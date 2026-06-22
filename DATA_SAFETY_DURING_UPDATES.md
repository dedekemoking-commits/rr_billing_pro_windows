# 🔒 Data Safety During Updates - Dokumentasi Lengkap

## ✅ JAWABAN: DATA TIDAK AKAN HILANG!

Ketika user melakukan update aplikasi, **SEMUA data aman dan tidak akan dihapus**.

---

## 📊 Bagaimana Data Disimpan?

### 1. **Executable File** (Python Bytecode)
- **File**: `RRBilling.exe` (atau `main.py`)
- **Isi**: Hanya kode aplikasi
- **Saat Update**: ✅ **Diganti dengan versi baru**
- **Data**: ❌ **Tidak ada data di sini**

### 2. **Config File** (Semua Data User)
- **File**: `rr_billing_config.json` (di folder aplikasi)
- **Isi**:
  - ✅ User credentials (username, password hash)
  - ✅ Tarif/Paket yang sudah diatur
  - ✅ Menu Makanan & Minuman
  - ✅ Profil Rental
  - ✅ Email settings
  - ✅ Trial user status
  
- **Saat Update**: ⏸️ **TIDAK DISENTUH** (tetap di folder)
- **Data**: ✅ **100% AMAN**

### 3. **Riwayat Transaksi** (Database)
- **File**: In-memory list (saat aplikasi berjalan)
- **Saat Update**: ⏹️ **App closes, riwayat dihapus dari memory**
- **NOTE**: Riwayat TIDAK persistent (hanya saat session app berjalan)
- **Data**: ✅ Riwayat session hilang, tapi itu normal

---

## 🔄 Proses Update: Apa Yang Terjadi?

```
SEBELUM UPDATE:
┌─────────────────────────┐
│ RRBilling.exe (v2.1)    │
│ rr_billing_config.json  │ ← SEMUA SETTING & USER PRESERVED
│ logo.png                │
│ update_pubkey.pem       │
└─────────────────────────┘

SAAT UPDATE (updater_helper.py):
┌─────────────────────────┐
│ 1. App tutup (exit)     │
│ 2. New exe ditunggu     │
│ 3. Old exe → .old       │
│ 4. New exe → old nama   │
│ 5. Restart app          │
└─────────────────────────┘

SETELAH UPDATE:
┌─────────────────────────┐
│ RRBilling.exe (v2.2.0)  │ ← EXECUTABLE BARU
│ rr_billing_config.json  │ ← SETTING TETAP SAMA! ✅
│ logo.png                │ ← TETAP                 ✅
│ update_pubkey.pem       │ ← TETAP                 ✅
│ RRBilling.exe.old       │ ← BACKUP (bisa dihapus) 
└─────────────────────────┘
```

---

## 📋 Checklist Data Yang Aman

| Data | Tipe Penyimpanan | Saat Update | Status |
|------|-----------------|------------|--------|
| **Username/Password** | `rr_billing_config.json` | Preserved | ✅ AMAN |
| **Tarif Paket** | `rr_billing_config.json` | Preserved | ✅ AMAN |
| **Menu Makanan** | `rr_billing_config.json` | Preserved | ✅ AMAN |
| **Menu Minuman** | `rr_billing_config.json` | Preserved | ✅ AMAN |
| **Profil Rental** | `rr_billing_config.json` | Preserved | ✅ AMAN |
| **Email Settings** | `rr_billing_config.json` | Preserved | ✅ AMAN |
| **Trial Status** | `rr_billing_config.json` | Preserved | ✅ AMAN |
| **License Key** | `rr_billing_license.json` | Preserved | ✅ AMAN |
| **Riwayat Transaksi** | Memory (session) | Cleared | ⚠️ Normal (session data) |

---

## 🎯 Contoh Konkret

### Skenario: User dengan Setting Custom

**Sebelum Update (v2.1.0)**:
```json
{
  "menu_makanan": {
    "Indomie Goreng": 8000,
    "Nasi Kuning RR": 18000,      ← Custom user
    "Es Cendol": 7000              ← Custom user
  },
  "menu_minuman": {
    "Es Teh": 5000,
    "Kopi Spesial RR": 12000       ← Custom user
  },
  "grup_tarif": {
    "Reguler": {
      "1 Jam": {"harga": 10000, "menit": 60},
      "Promo 2 Jam": {"harga": 15000, "menit": 120}  ← Custom user
    }
  }
}
```

**Setelah Update (v2.2.0)**:
```json
{
  "menu_makanan": {
    "Indomie Goreng": 8000,
    "Nasi Kuning RR": 18000,      ✅ MASIH ADA
    "Es Cendol": 7000              ✅ MASIH ADA
  },
  "menu_minuman": {
    "Es Teh": 5000,
    "Kopi Spesial RR": 12000       ✅ MASIH ADA
  },
  "grup_tarif": {
    "Reguler": {
      "1 Jam": {"harga": 10000, "menit": 60},
      "Promo 2 Jam": {"harga": 15000, "menit": 120}  ✅ MASIH ADA
    }
  }
}
```

**HASIL**: Semua setting custom user TETAP PRESERVED! ✅

---

## 🛡️ Bagaimana Ini Bekerja?

### Update Mechanism (updater_helper.py)

```python
1. Wait for old app to exit (tidak locked)
2. Backup: old.exe → old.exe.old
3. Replace: new.exe → old.exe location
4. Restart: Launch new exe
5. Config: Load dari rr_billing_config.json (unchanged!)
```

**Key Point**: Update hanya replace **executable binary**, bukan config files!

---

## ⚠️ Edge Cases

### Riwayat Transaksi (Session Data)
- **Status**: Disimpan di memory saat app berjalan
- **Saat Update**: Hilang (app ditutup saat update)
- **Behavior**: **NORMAL** - ini session data, bukan persistent

**Solusi**: Jika perlu persistent, user harus export riwayat SEBELUM update

### Jika User Restart App Saat Download
- ✅ Update dibatalkan otomatis
- ✅ Config tetap aman
- ✅ User bisa retry update nanti

### Update Gagal / Corrupted File
- ✅ Auto-rollback ke `.old` file
- ✅ Config tetap aman
- ✅ App tetap bisa dijalankan

---

## 📝 FAQ

### Q: Apakah semua tarif saya akan hilang?
**A**: ❌ Tidak. Semua tarif disimpan di `rr_billing_config.json` yang TIDAK dihapus saat update.

### Q: Menu makanan & minuman custom saya bagaimana?
**A**: ✅ Preserved. Data disimpan di config file yang tetap ada.

### Q: Gimana dengan data user/akun?
**A**: ✅ Preserved. Username, email, profil semuanya di config file yang aman.

### Q: Riwayat transaksi kemana?
**A**: ⚠️ Riwayat dalam memory hilang saat app ditutup (normal). Jika perlu di-backup, export sebelum update.

### Q: Aman tidak kalau internet putus saat download?
**A**: ✅ Aman. Update dibatalkan, config tetap utuh, app tetap bisa dijalankan.

### Q: Kalau EXE corrupted saat download?
**A**: ✅ Auto-check SHA256 sebelum install. Jika invalid, download retry.

---

## 🔐 Data Backup Best Practice

### Untuk Production Use:

```bash
# SEBELUM UPDATE:
1. Backup config file
   cp rr_billing_config.json rr_billing_config.json.backup

2. Backup license
   cp rr_billing_license.json rr_billing_license.json.backup

3. Export riwayat (jika penting)
   File → Export Riwayat → riwayat.xlsx

4. Baru update
   Cek Pembaruan → Download & Install
```

### Untuk Recovery (Jika Terjadi Masalah):
```bash
# Restore dari backup
cp rr_billing_config.json.backup rr_billing_config.json
cp rr_billing_license.json.backup rr_billing_license.json
# Restart app
```

---

## 🎯 Kesimpulan

| Pertanyaan | Jawaban | Bukti |
|-----------|--------|-------|
| **Data hilang saat update?** | ❌ Tidak | Config file preserved |
| **Tarif hilang?** | ❌ Tidak | Di config file |
| **Menu custom hilang?** | ❌ Tidak | Di config file |
| **User akun hilang?** | ❌ Tidak | Di config file |
| **Riwayat transaksi?** | ⚠️ Session data | Normal (in-memory only) |
| **License tetap berlaku?** | ✅ Ya | Di license file |

---

## 📞 Support

### Jika User Khawatir:
1. ✅ Backup config sebelum update
2. ✅ Update hanya replace executable
3. ✅ Config tetap di folder original
4. ✅ Setelah update, semua setting kembali sama

### Jika Terjadi Masalah:
1. Restore dari backup
2. Restart aplikasi
3. Hubungi support dengan log file

---

**KESIMPULAN AKHIR: 100% DATA SAFE! ✅**

Semua data penting user (tarif, menu, akun, profil, lisensi) tersimpan di file terpisah dari executable, sehingga update hanya akan replace code, bukan data.
