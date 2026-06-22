# GitHub Integration untuk RR Billing PRO - Setup Guide

## Tujuan
Automasi distribusi update aplikasi melalui GitHub Releases. User dapat mengunduh update terbaru dari GitHub dengan verifikasi signature otomatis.

## Prerequisites
✅ Repository GitHub sudah dibuat: `https://github.com/dedekemoking-commits/rr_billing_pro_windows`
✅ RSA signing keys sudah ada (`keys/private_key.pem`, `update_pubkey.pem`)
✅ Update manifest script sudah ada (`scripts/generate_manifest_and_sign.py`)
✅ GitHub Actions workflow sudah ada (`.github/workflows/release.yml`)

## Setup GitHub Secret (PENTING!)

### 1. Buka GitHub Repository Settings
- Buka: https://github.com/dedekemoking-commits/rr_billing_pro_windows/settings
- Klik menu **Secrets and variables** → **Actions**

### 2. Add Secret `SIGNING_PRIVATE_KEY`
- Klik **New repository secret**
- **Name**: `SIGNING_PRIVATE_KEY`
- **Value**: Copy-paste isi file `keys/private_key.pem` (termasuk `-----BEGIN PRIVATE KEY-----` dan `-----END PRIVATE KEY-----`)

Contoh:
```
-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC...
(banyak karakter base64)
...-----END PRIVATE KEY-----
```

> ⚠️ **PENTING**: Private key TIDAK boleh di-commit ke repository! Hanya simpan di GitHub Secret.

## Cara Rilis Update

### Opsi 1: Manual Release via Git Tag
```bash
# 1. Update versi di aplikasi (di main.py)
# Cari: APP_VERSION = "X.X.X"
# Ubah ke versi baru: APP_VERSION = "2.1.0"

# 2. Commit perubahan
git add main.py
git commit -m "Bump version to v2.1.0"
git push origin main

# 3. Create tag untuk trigger release workflow
git tag v2.1.0
git push origin v2.1.0
```

Workflow akan otomatis:
1. ✅ Build EXE dari `main.py`
2. ✅ Hitung SHA256 dari EXE
3. ✅ Generate `manifest.json` dengan signature (menggunakan private key dari secret)
4. ✅ Upload ke GitHub Release:
   - `RRBilling.exe`
   - `manifest.json`

### Opsi 2: Manual Release via GitHub UI
- Buka: https://github.com/dedekemoking-commits/rr_billing_pro_windows/releases
- Klik **Draft a new release**
- **Tag**: `v2.1.0`
- **Release name**: `v2.1.0`
- Upload files:
  - `dist/RRBilling.exe`
  - `manifest.json` (generate lokal dulu)

## Cara Generate Manifest Lokal (untuk development)

```bash
# 1. Build EXE dulu
pyinstaller --onefile --windowed main.py

# 2. Hitung SHA256
import hashlib
with open('dist/main.exe','rb') as f:
    sha256 = hashlib.sha256(f.read()).hexdigest()
print(sha256)  # Copy nilai ini

# 3. Generate signed manifest
python scripts/generate_manifest_and_sign.py \
  --version "v2.1.0" \
  --asset_url "https://github.com/dedekemoking-commits/rr_billing_pro_windows/releases/download/v2.1.0/RRBilling.exe" \
  --sha256 "<SHA256_DARI_STEP_2>" \
  --signing_key "$(cat keys/private_key.pem)" \
  --out manifest.json
```

## Verifikasi Setup di Aplikasi

### 1. User Install Aplikasi
- Download `RRBilling.exe` dari release
- Sertakan `update_pubkey.pem` dalam package (atau sudah ada di folder instalasi)

### 2. Cek Update di Aplikasi
- Buka aplikasi → Menu **Cek Pembaruan**
- Aplikasi akan:
  1. Fetch `manifest.json` dari GitHub Release
  2. Verify signature dengan `update_pubkey.pem` (public key)
  3. Download EXE jika versi lebih baru
  4. Verify SHA256
  5. Jalankan updater untuk replace executable

### Troubleshooting

#### ❌ "Signature manifest tidak valid"
- Pastikan `SIGNING_PRIVATE_KEY` secret benar di GitHub
- Pastikan `update_pubkey.pem` sesuai dengan public key dari private key

#### ❌ "Checksum tidak cocok"
- Pastikan SHA256 di manifest.json benar
- Pastikan asset di GitHub Release benar

#### ❌ "Manifest missing required fields"
- Pastikan manifest.json memiliki: `version`, `asset_url`, `sha256`, `sig`

## Release Workflow

```mermaid
graph LR
    A["1. Update versi + tag git<br/>git tag v2.1.0<br/>git push"] 
    B["2. GitHub Actions<br/>Build EXE<br/>Sign manifest"]
    C["3. Upload ke Release<br/>RRBilling.exe<br/>manifest.json"]
    D["4. User klik Cek Update<br/>Verify signature<br/>Download & install"]
    A --> B --> C --> D
```

## Checklist Setup

- [ ] Private key disimpan di GitHub Secret `SIGNING_PRIVATE_KEY`
- [ ] Public key (`update_pubkey.pem`) ada di repository
- [ ] Config `rr_billing_config.json` point ke GitHub Release manifest URL
- [ ] GitHub Actions workflow ada dan aktif
- [ ] Test: create test release tag, verify workflow runs
- [ ] Test: aplikasi bisa cek update dan download manifest

## Files Terkait

| File | Purpose |
|------|---------|
| `.github/workflows/release.yml` | GitHub Actions workflow untuk auto-build & release |
| `keys/private_key.pem` | Private key (JANGAN di-commit! Simpan di Secret) |
| `update_pubkey.pem` | Public key (commit ke repo) |
| `scripts/generate_manifest_and_sign.py` | Script untuk generate signed manifest |
| `scripts/check_update.py` | Client-side update checker di aplikasi |
| `scripts/updater_helper.py` | Helper untuk replace executable |
| `rr_billing_config.json` | Berisi `update_manifest_url` untuk download manifest |

## Security Notes

- ✅ Manifest di-sign dengan RSA private key
- ✅ Signature di-verify dengan RSA public key di client
- ✅ SHA256 di-verify sebelum execute
- ✅ Private key hanya di GitHub Secret, tidak di-commit
- ⚠️ Untuk production: Pertimbangkan code signing dengan Authenticode (signtool) untuk SmartScreen di Windows

## Next Steps

1. Pastikan GitHub Secret sudah diset ✅
2. Test release workflow dengan tag `v2.1.0` ✅
3. Monitor workflow di Actions tab
4. Download manifest dari release, verify signature
5. Test di aplikasi: Cek Pembaruan → verifikasi bisa detect & download update
