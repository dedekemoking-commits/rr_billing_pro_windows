"""
migrate_trial_users.py — Migrate Existing Trial Data to New Per-Username Format

Scenario: Existing users punya trial data di license.json
Perlu: Migrate ke config.json trial_users format agar tidak reset saat PC swap

Usage: python migrate_trial_users.py
"""

import os
import json
import shutil
from datetime import date, datetime

CONFIG_FILE = "rr_billing_config.json"
LICENSE_FILE = "rr_billing_license.json"
BACKUP_DIR = "backups"


def create_backup():
    """Backup existing files before migration."""
    print("\n" + "="*70)
    print("STEP 1: Backup Existing Files")
    print("="*70)
    
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        print(f"✓ Created backup directory: {BACKUP_DIR}")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    files_backed = []
    for src_file in [CONFIG_FILE, LICENSE_FILE]:
        if os.path.exists(src_file):
            backup_file = os.path.join(BACKUP_DIR, f"{src_file}.{timestamp}.backup")
            shutil.copy2(src_file, backup_file)
            files_backed.append(backup_file)
            print(f"✓ Backed up: {src_file} → {backup_file}")
    
    if not files_backed:
        print("ℹ No files to backup (fresh install)")
    
    return timestamp


def load_config():
    """Load config.json safely."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠ Error loading config.json: {e}")
            return {}
    return {}


def load_license():
    """Load license.json safely."""
    if os.path.exists(LICENSE_FILE):
        try:
            with open(LICENSE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠ Error loading license.json: {e}")
            return {}
    return {}


def save_config(cfg):
    """Save config.json with proper formatting."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"✗ Error saving config.json: {e}")
        return False


def detect_trial_users():
    """Detect existing trial users from license.json."""
    print("\n" + "="*70)
    print("STEP 2: Detect Existing Trial Users")
    print("="*70)
    
    lic = load_license()
    
    # Check jika ada trial data
    if not lic:
        print("ℹ No license.json found (fresh install)")
        return {}
    
    if not lic.get("aktif"):
        print("ℹ License is not active (no binding)")
        trial_start = lic.get("mulai_date") or lic.get("mulai", "")[:10]
        if trial_start:
            print(f"  Trial started: {trial_start}")
        else:
            print("  No trial data found")
        return {}
    
    # Ada lisensi aktif → tidak perlu migration
    print("✓ License is active (no migration needed for active licenses)")
    return {}


def migrate_to_per_username():
    """Migrate trial data to per-username format."""
    print("\n" + "="*70)
    print("STEP 3: Migrate Trial Data to Per-Username Format")
    print("="*70)
    
    cfg = load_config()
    lic = load_license()
    
    # Initialize trial_users jika belum ada
    if "trial_users" not in cfg:
        cfg["trial_users"] = {}
        print("✓ Created trial_users field in config")
    
    trial_users = cfg.get("trial_users", {})
    migrated_count = 0
    
    # ── Case 1: License exists with trial data ────────────────────────────
    if lic and not lic.get("aktif"):
        # Ada trial di license.json, cek perlu migrate
        mulai_str = lic.get("mulai_date") or lic.get("mulai", "")[:10]
        
        if mulai_str:
            # Cari username dari license binding
            username = lic.get("username", "")
            
            if username:
                # License sudah ada username binding
                if username not in trial_users:
                    trial_users[username] = {
                        "trial_start": mulai_str,
                        "trial_days": 3,  # default
                    }
                    print(f"✓ Migrated trial data for user: {username}")
                    print(f"  Trial started: {mulai_str}")
                    migrated_count += 1
            else:
                # License tidak ada username (fallback)
                print("⚠ License exists but no username binding")
                print("  (This is OK for machine-bound licenses)")
    
    # ── Case 2: Check config for existing users ────────────────────────────
    users = cfg.get("users", {})
    for username in users.keys():
        if username not in ["admin", "kasir"]:  # Skip default users
            if username not in trial_users:
                # Coba infer trial start dari license
                if lic and lic.get("username") == username and not lic.get("aktif"):
                    mulai_str = lic.get("mulai_date") or lic.get("mulai", "")[:10]
                    if mulai_str:
                        trial_users[username] = {
                            "trial_start": mulai_str,
                            "trial_days": 3,
                        }
                        print(f"✓ Migrated trial for existing user: {username}")
                        migrated_count += 1
    
    cfg["trial_users"] = trial_users
    
    if migrated_count == 0:
        print("ℹ No trial data to migrate (empty or fresh install)")
    
    return cfg, migrated_count


def verify_migration(cfg, migrated_count):
    """Verify migration was successful."""
    print("\n" + "="*70)
    print("STEP 4: Verify Migration")
    print("="*70)
    
    trial_users = cfg.get("trial_users", {})
    
    print(f"\nTrial Users in Config: {len(trial_users)}")
    for username, data in trial_users.items():
        trial_start = data.get("trial_start", "—")
        trial_days = data.get("trial_days", "—")
        print(f"  • {username}")
        print(f"    Start: {trial_start}")
        print(f"    Days: {trial_days}")
    
    if migrated_count > 0:
        print(f"\n✓ Successfully migrated {migrated_count} trial user(s)")
    else:
        print("\nℹ No users were migrated")
    
    return True


def main():
    print("\n" + "="*70)
    print("RR BILLING PRO — Trial Users Migration Script")
    print("="*70)
    print("\nMigrates existing trial data to new per-username format.")
    print("This prevents trial reset when user switches PC.")
    
    # Step 1: Backup
    timestamp = create_backup()
    
    # Step 2: Detect trial users
    detect_trial_users()
    
    # Step 3: Migrate
    cfg, migrated_count = migrate_to_per_username()
    
    # Step 4: Save
    print("\n" + "="*70)
    print("STEP 5: Save Config")
    print("="*70)
    
    if save_config(cfg):
        print(f"✓ Config saved successfully")
    else:
        print("✗ Error saving config! Check backup in: " + os.path.join(BACKUP_DIR, f"{CONFIG_FILE}.{timestamp}.backup"))
        return False
    
    # Step 5: Verify
    verify_migration(cfg, migrated_count)
    
    # Summary
    print("\n" + "="*70)
    print("MIGRATION SUMMARY")
    print("="*70)
    
    if migrated_count > 0:
        print(f"\n✓✓✓ Migration successful!")
        print(f"\nMigrated {migrated_count} trial user(s).")
        print(f"Backups saved in: {BACKUP_DIR}/")
        print(f"\nNOTE: Existing trial data is now stored per-username in config.json")
        print(f"      Trial will no longer reset when user switches PC!")
    else:
        print(f"\nℹ No trial data was migrated.")
        print(f"  This is normal for fresh installs or machines with active licenses.")
        print(f"  Any new users will automatically use the per-username trial system.")
    
    print("\nBackup timestamp: " + timestamp)
    print("\n" + "="*70)
    
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
