"""Updater helper (Windows):
Usage: python updater_helper.py <old_exe_path> <new_file_path>
Behavior:
 - Wait for old_exe_path to be not locked (i.e., process exited)
 - Replace old_exe_path with new_file_path atomically
 - Restart the new executable
Note: This helper runs as a separate Python process so the main app can exit.
"""
import os
import shutil
import sys
import time


def _is_file_locked(path: str) -> bool:
    # Try open for exclusive write on Windows; if fails, assume locked
    try:
        if not os.path.exists(path):
            return False
        fh = open(path, 'a')
        try:
            fh.close()
            return False
        except Exception:
            return True
    except Exception:
        return True


def main():
    if len(sys.argv) < 3:
        print('Usage: updater_helper.py <old_exe> <new_file>')
        sys.exit(2)
    old_exe = sys.argv[1]
    new_file = sys.argv[2]

    # Wait for old exe to be unlocked
    for i in range(60):
        if not _is_file_locked(old_exe):
            break
        time.sleep(0.5)
    # Try replace
    try:
        bak = old_exe + '.old'
        if os.path.exists(bak):
            try:
                os.remove(bak)
            except Exception:
                pass
        os.replace(old_exe, bak)
        os.replace(new_file, old_exe)
        # Restart
        os.execv(old_exe, [old_exe])
    except Exception as e:
        print('Updater failed:', e)
        # Attempt rollback
        try:
            if os.path.exists(bak) and not os.path.exists(old_exe):
                os.replace(bak, old_exe)
        except Exception:
            pass
        sys.exit(1)

if __name__ == '__main__':
    main()
