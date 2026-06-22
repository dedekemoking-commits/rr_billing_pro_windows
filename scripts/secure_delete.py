import os


def secure_delete(path: str, passes: int = 1):
    """Overwrite file content then delete. Not guaranteed on certain filesystems, but helps reduce recovery.
    """
    if not os.path.exists(path):
        return
    try:
        length = os.path.getsize(path)
        with open(path, 'r+b') as f:
            for _ in range(passes):
                f.seek(0)
                f.write(b'\x00' * length)
                f.flush()
                os.fsync(f.fileno())
        os.remove(path)
    except Exception:
        try:
            os.remove(path)
        except Exception:
            pass
