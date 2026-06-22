# ✅ GitHub Release Integration - Komplet!

## Status: SIAP DIGUNAKAN

Integrasi GitHub sudah selesai! Sekarang aplikasi dapat mengunduh update otomatis dari GitHub.

---

## 🚀 Langkah-Langkah Selanjutnya

### STEP 1️⃣: Setup GitHub Secret (WAJIB!)

Ini adalah langkah TERPENTING untuk automated releases:

**Lokasi**: https://github.com/dedekemoking-commits/rr_billing_pro_windows/settings/secrets/actions

**Cara**:
1. Buka GitHub repo settings → Secrets and variables → Actions
2. Klik **New repository secret**
3. **Name**: `SIGNING_PRIVATE_KEY`
4. **Value**: Copy-paste isi file `keys/private_key.pem` yang ada di lokal folder
   - Pastikan termasuk `-----BEGIN PRIVATE KEY-----` dan `-----END PRIVATE KEY-----`
   - Jangan tambah spasi atau karakter lain

**Contoh format yang benar:**
```
-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC...
[banyak baris base64]
...ZnUF8A5h3wg==
-----END PRIVATE KEY-----
```

### STEP 2️⃣: Test Release (Opsional)

Untuk test apakah workflow bekerja dengan baik:

```bash
cd c:\BillingPSkuDesktop

# 1. Update APP_VERSION di main.py (cari baris: APP_VERSION = "...")
# Ubah ke: APP_VERSION = "2.1.0"

# 2. Commit
git add main.py
git commit -m "Bump version to v2.1.0 for testing"
git push origin master

# 3. Create tag untuk trigger workflow
git tag v2.1.0
git push origin v2.1.0
```

**Monitor**:
- Buka: https://github.com/dedekemoking-commits/rr_billing_pro_windows/actions
- Tunggu workflow selesai (~5-10 menit)
- Jika sukses, akan ada release baru dengan:
  - `RRBilling.exe`
  - `manifest.json`

### STEP 3️⃣: Verifikasi di Aplikasi

Setelah ada release, test di aplikasi:

1. Update APP_VERSION di `main.py` ke versi baru (misal v2.2.0)
2. Jalankan aplikasi
3. Klik menu **Cek Pembaruan** (di sidebar)
4. Aplikasi akan:
   - Download `manifest.json` dari GitHub
   - Verify signature dengan public key
   - Jika versi lebih baru, download EXE
   - Verify SHA256
   - Tawarkan install update

---

## 📋 Proses Release untuk Production

### Proses Cepat (Recommended):

```bash
# 1. Update versi di main.py
# APP_VERSION = "2.2.0"

# 2. Commit & push
git add main.py
git commit -m "Release v2.2.0 - add new features"
git push origin master

# 3. Create release tag
git tag v2.2.0
git push origin v2.2.0
```

**GitHub Actions akan otomatis**:
1. ✅ Build EXE dari latest code
2. ✅ Hitung SHA256
3. ✅ Generate manifest.json dengan signature
4. ✅ Upload ke GitHub Release

### Verifikasi Release:

- Buka: https://github.com/dedekemoking-commits/rr_billing_pro_windows/releases
- Pastikan ada release baru dengan file:
  - `RRBilling.exe` (executable)
  - `manifest.json` (signed update metadata)

---

## 🔒 Security Architecture

```
┌──────────────────────┐
│   Developer/CI       │
│ (Private Key)        │ ← GitHub Secret: SIGNING_PRIVATE_KEY
│ Sign manifest.json   │
└──────────────────────┘
         ↓
┌──────────────────────┐
│ GitHub Release       │
│ - manifest.json ✅   │ (signed)
│ - RRBilling.exe ✅   │ (with sha256)
└──────────────────────┘
         ↓
┌──────────────────────┐
│ User's PC            │
│ (Public Key)         │ ← update_pubkey.pem
│ Verify signature     │
│ Check SHA256         │
│ Run installer        │
└──────────────────────┘
```

### Keamanan:
- ✅ Manifest di-sign dengan RSA-2048 + SHA256
- ✅ Signature di-verify di client sebelum execute
- ✅ SHA256 checksum di-verify
- ✅ Private key tidak pernah di-commit (hanya di GitHub Secret)
- ✅ Public key aman untuk di-distribute dengan aplikasi

---

## 📂 Files yang Berubah

| File | Perubahan | Alasan |
|------|-----------|--------|
| `rr_billing_config.json` | Tambah `update_manifest_url` | Tunjuk ke GitHub Release |
| `.github/workflows/release.yml` | Update workflow | Optimasi auto-build |
| `GITHUB_RELEASE_SETUP.md` | Baru | Dokumentasi lengkap |
| `update_pubkey.pem` | Sudah ada | Public key untuk verify |

---

## ❓ Troubleshooting

### ❌ Workflow gagal di GitHub Actions

**Check**:
- Buka: https://github.com/dedekemoking-commits/rr_billing_pro_windows/actions
- Klik workflow yang gagal
- Lihat log error

**Common issues**:
- ❌ `SIGNING_PRIVATE_KEY secret not set` → Setup secret dulu
- ❌ Build error → Check `requirements.txt` ada semua dependency

### ❌ Aplikasi: "Signature manifest tidak valid"

**Cause**: Public key tidak cocok dengan private key

**Fix**:
- Pastikan `update_pubkey.pem` sama dengan `keys/public_key.pem`
- Pastikan `keys/private_key.pem` di GitHub Secret benar

### ❌ Aplikasi: "Checksum tidak cocok"

**Cause**: SHA256 di manifest tidak cocok dengan file yang diunduh

**Fix**:
- Re-build EXE
- Re-generate manifest
- Re-upload ke GitHub

### ❌ Aplikasi tidak mau download update

**Check**:
- Pastikan `update_manifest_url` di config benar
- Pastikan manifest.json ada di release
- Pastikan public key file ada

---

## 📝 Commands Reference

### Lihat current config:
```bash
# Manifest URL
cat rr_billing_config.json | grep update_manifest_url
```

### Generate manifest manual:
```bash
python scripts/generate_manifest_and_sign.py \
  --version "v2.1.0" \
  --asset_url "https://github.com/dedekemoking-commits/rr_billing_pro_windows/releases/download/v2.1.0/RRBilling.exe" \
  --sha256 "abc123..." \
  --signing_key "$(cat keys/private_key.pem)" \
  --out manifest.json
```

### Test verify signature:
```bash
# Check public key
cat update_pubkey.pem
```

---

## 🎯 Next: Distribute ke Users

### Paket distribusi:
- `RRBilling.exe` (dari GitHub Release)
- `update_pubkey.pem` (sudah ada)
- Installation guide (buat baru)

### User experience:
1. ✅ Install aplikasi dari `RRBilling.exe`
2. ✅ Aplikasi auto-check update saat startup (opsional config)
3. ✅ User klik "Cek Pembaruan" → download & install update
4. ✅ Aplikasi restart dengan versi baru

---

## 📞 Summary

| Item | Status | Next Action |
|------|--------|-------------|
| Config setup | ✅ DONE | - |
| Workflow created | ✅ DONE | - |
| GitHub Secret | ⏳ PENDING | Setup SIGNING_PRIVATE_KEY |
| Test release | ⏳ PENDING | Tag v2.1.0 & verify |
| User distribution | ⏳ PENDING | Download from Release |

---

**Ready to distribute updates! 🚀**

Setelah GitHub Secret diset, workflow akan otomatis run saat ada tag push. User bisa langsung download update dari GitHub.
