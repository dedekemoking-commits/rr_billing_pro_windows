"""Simple migration tool: find plaintext JSON files and re-encrypt using rr_crypto.save_json_file
Usage: python scripts/migrate_plaintext_configs.py [target_dir]
"""
import os
import json
import shutil
import sys

import rr_crypto


def is_plain_json(path: str) -> bool:
    try:
        raw = open(path, 'rb').read()
        # If it's wrapper JSON (v1), consider encrypted
        try:
            obj = json.loads(raw.decode('utf-8'))
            if isinstance(obj, dict) and obj.get('v') == 1 and 'nonce' in obj and 'data' in obj:
                return False
        except Exception:
            pass
        json.loads(raw.decode('utf-8'))
        return True
    except Exception:
        return False


def migrate(dir_path: str):
    for root, dirs, files in os.walk(dir_path):
        for fname in files:
            if not fname.lower().endswith('.json'):
                continue
            path = os.path.join(root, fname)
            if is_plain_json(path):
                bak = path + '.bak'
                shutil.copy2(path, bak)
                print('Migrating', path, '-> backup at', bak)
                try:
                    data = json.loads(open(path, 'rb').read().decode('utf-8'))
                    rr_crypto.save_json_file(path, data)
                except Exception as e:
                    print('Failed migrating', path, e)


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    migrate(target)
