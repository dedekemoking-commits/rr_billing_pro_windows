# Git Update Feature - Panduan Lengkap

## 📡 Fitur Update via Git

Aplikasi RR Billing Pro sekarang mendukung **update otomatis langsung dari GitHub** tanpa perlu download manual atau installer baru!

### ✨ Cara Kerja

1. **Cek Update dari Git** → Aplikasi akan check apakah ada commit baru di GitHub
2. **Tampilkan Perubahan** → Daftar commit yang akan di-pull ditampilkan ke user
3. **Pull & Restart** → Jika user setuju, aplikasi pull perubahan dan restart otomatis

---

## 🚀 Cara Menggunakan

### Di Aplikasi

1. Masuk ke akun kasir (login)
2. Lihat tombol **"📡 Update via Git"** di sidebar (sebelah kanan bawah)
3. Klik tombol tersebut
4. Aplikasi akan check apakah ada update di GitHub
   - **Jika up-to-date**: Pesan "Aplikasi sudah up-to-date"
   - **Jika ada update**: Tanyakan apakah ingin lanjut
5. Klik **"Yes"** untuk mulai update
6. Tunggu sampai pull selesai, aplikasi akan restart otomatis

### Proses Update Secara Detail

```
Cek Server → Ada Update? → Tampilkan Commits → Konfirmasi User
                ↓                                        ↓
              TIDAK  → Pesan "Up-to-date"         YA → Pull Updates
                                                        ↓
                                                    Restart Aplikasi
```

---

## 📋 Persyaratan

### Client (End User)
- ✅ Git sudah terpasang di komputer (minimal v2.x)
- ✅ Internet connection untuk akses GitHub
- ✅ Aplikasi berjalan dari folder yang same (jangan ubah path)

### Server (Developer)
- ✅ Repository di GitHub public atau accessible
- ✅ Aplikasi di-push ke `master` branch atau branch yang dikonfigurasi

---

## ⚙️ Konfigurasi

### Default Configuration
```json
{
  "git_update_enabled": true,
  "git_remote": "origin",
  "git_branch": "master",
  "git_auto_check_interval_hours": 6
}
```

### Mengubah Konfigurasi (Optional)

Edit `rr_billing_config.json`:

```json
{
  "git_update_enabled": true,
  "git_remote": "origin",
  "git_branch": "master",
  "git_auto_check_interval_hours": 6
}
```

**Opsi:**
- `git_update_enabled`: Enable/disable fitur (true/false)
- `git_remote`: Remote name, biasanya "origin"
- `git_branch`: Branch to track, default "master"
- `git_auto_check_interval_hours`: Auto check interval (setiap N jam)

---

## 📊 Update Log

Setiap kali update dilakukan, log disimpan di: **`update.log`**

Contoh isi:
```
[2026-06-23 00:15:30] Checking for updates...
[2026-06-23 00:15:31] Fetch successful
[2026-06-23 00:15:32] Update tersedia: 2 commit(s) di remote (abc1234 → def5678)
[2026-06-23 00:15:33] Pulling updates dari origin/master...
[2026-06-23 00:15:35] Pull successful
[2026-06-23 00:15:35] Update successful, restarting application...
```

Lihat log dengan: `tail -f update.log` (di terminal)

---

## 🔍 Troubleshooting

### "Git command not found"
**Solusi:**
- Pastikan Git sudah di-install
- Di Windows: Gunakan Git Bash atau Git for Windows
- Restart aplikasi setelah install Git

### "Cannot access repository"
**Penyebab & Solusi:**
- Repository private → Butuh authentication
- Network/internet error → Check koneksi internet
- URL salah → Periksa `git remote -v`

### "Merge conflict detected"
**Solusi:**
- Aplikasi auto-stash local changes sebelum pull
- Jika tetap error, manual resolve di terminal:
  ```bash
  cd C:\BillingPSkuDesktop
  git status
  git merge --abort
  ```

### Update "failed" tapi aplikasi masih berjalan
**Ini normal** - aplikasi tidak restart jika pull gagal, sehingga data aman. Coba lagi atau check internet.

---

## 🔐 Keamanan

### Authentication
- Jika repository private, Git akan minta password/token
- Gunakan SSH keys untuk automation yang lebih aman:
  ```bash
  git remote set-url origin git@github.com:username/repo.git
  ```

### Data Safety
- Sebelum pull, aplikasi **auto-stash** local uncommitted changes
- Jika pull gagal, local changes tidak hilang (di-restore)
- Audit log dicatat: siapa update, kapan, status

---

## 🛠️ Developer Reference

### GitUpdater Class (scripts/git_updater.py)

```python
from scripts.git_updater import GitUpdater

# Inisialisasi
updater = GitUpdater(repo_path="/path/to/repo", remote="origin", branch="master")

# Check for updates
has_update, msg, info = updater.check_for_updates()
# Returns:
#   has_update: bool
#   msg: str (human-readable message)
#   info: dict {local_commit, remote_commit, behind_count, commits_info}

# Pull updates
success, pull_msg = updater.pull_updates()

# Update and restart
success, msg = updater.update_and_restart(app_exe_path="/path/to/app.exe")

# Get info
version = updater.get_current_version()  # e.g., "c0da7aa"
url = updater.get_remote_url()           # e.g., "https://..."
log = updater.get_update_log()           # Last 20 lines dari update.log
```

### Main App Integration (main.py)

```python
def _on_git_update(self):
    """Triggered by '📡 Update via Git' button"""
    threading.Thread(target=self._git_update_thread, daemon=True).start()

def _git_update_thread(self):
    """Background thread untuk check & update via Git"""
    # ... implementation ...
```

---

## 📝 Release Notes

### v2.2.2+
✅ Git Update feature ditambahkan
✅ Manual check update via "📡 Update via Git" button
✅ Auto-restart setelah update
✅ Update log tracking
✅ Local changes protection (auto-stash)

---

## 💡 Tips & Tricks

### Tip 1: Check log kapan saja
```bash
cd C:\BillingPSkuDesktop
type update.log
```

### Tip 2: Manual pull (jika button error)
```bash
cd C:\BillingPSkuDesktop
git fetch origin master
git pull origin master
```

### Tip 3: Rollback ke versi sebelumnya
```bash
cd C:\BillingPSkuDesktop
git log --oneline        # Lihat history
git reset --hard <hash>  # Reset ke commit sebelumnya
```

### Tip 4: Auto-update interval
Atur di config.json `git_auto_check_interval_hours` - aplikasi akan otomatis check setiap N jam

---

## 🆘 Support

Jika ada error, save log file dan error message:
```bash
cd C:\BillingPSkuDesktop
type update.log > update_error_report.txt
```

Lalu attach file ke issue di GitHub atau hubungi developer.

---

## 📅 Changelog

| Tanggal | Versi | Perubahan |
|---------|-------|----------|
| 2026-06-23 | 2.2.2 | Initial Git Update Feature |
| ... | ... | ... |

---

**Selamat! Aplikasi Anda sekarang bisa update dengan mudah dari Git! 🚀**
