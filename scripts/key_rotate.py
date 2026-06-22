"""Key rotation tool:
- Backup existing DPAPI blob
- Generate new random key and persist via DPAPI
- Re-encrypt JSON files found under target directory
Usage: python scripts/key_rotate.py [target_dir]
"""
import os
import shutil
import sys
import time

import rr_crypto


def backup_dpapi(blob_path: str, out_dir: str) -> str:
    if not os.path.exists(blob_path):
        raise FileNotFoundError(blob_path)
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime('%Y%m%d%H%M%S')
    out = os.path.join(out_dir, f'dpapi_backup_{ts}.bin')
    shutil.copy2(blob_path, out)
    return out


def rotate(target_dir: str):
    blob = getattr(rr_crypto, '_DPAPI_KEY_PATH', None)
    if blob and os.path.exists(blob):
        bkp = backup_dpapi(blob, os.path.join(os.getcwd(), 'backups'))
        print('Backed up DPAPI blob to', bkp)
        # Optionally encrypt backup with passphrase from env
        passphrase = os.environ.get('BACKUP_PASSPHRASE')
        if passphrase:
            try:
                from scripts import backup_utils
                encrypted_path = bkp + '.enc'
                backup_utils.encrypt_file_with_passphrase(bkp, encrypted_path, passphrase)
                print('Encrypted DPAPI backup to', encrypted_path)
            except Exception as e:
                print('Failed to encrypt backup:', e)
    else:
        print('No DPAPI blob found; continuing with in-memory key rotation')

    # generate new key and save
    new_key = os.urandom(32)
    try:
        rr_crypto._save_master_key_dpapi(new_key)
        print('Saved new master key to DPAPI')
    except Exception as e:
        print('Failed to persist new DPAPI key:', e)

    # Re-encrypt JSON files
    for root, dirs, files in os.walk(target_dir):
        for fname in files:
            if not fname.lower().endswith('.json'):
                continue
            path = os.path.join(root, fname)
            try:
                data = rr_crypto.load_json_file(path)
                rr_crypto.save_json_file(path, data)
                print('Re-encrypted', path)
            except Exception as e:
                print('Skipping', path, 'error:', e)


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    rotate(target)
