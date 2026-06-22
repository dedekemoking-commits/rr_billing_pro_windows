"""Simple updater client:
- Fetch manifest.json from a URL (HTTPS)
- Manifest JSON fields: version, asset_url, sha256, sig (base64 of signature over 'version\nasset_url\nsha256')
- Verify signature with provided RSA public key (PEM)
- Download asset to temp, verify sha256
- Launch updater helper to replace binary

Usage: call check_for_update(manifest_url, public_key_path, current_version, app_exe_path)
"""
from __future__ import annotations
import json
import os
import tempfile
import urllib.request
import hashlib
import base64
import subprocess
from typing import Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key


def _download_url(url: str, out_path: str):
    with urllib.request.urlopen(url, timeout=30) as r:
        data = r.read()
    with open(out_path, 'wb') as f:
        f.write(data)


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _verify_signature(pubkey_path: str, message: bytes, signature_b64: str) -> bool:
    with open(pubkey_path, 'rb') as f:
        pub = load_pem_public_key(f.read())
    sig = base64.b64decode(signature_b64)
    try:
        pub.verify(sig, message, padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:
        return False


def check_for_update(manifest_url: str, public_key_path: str, current_version: str, app_exe_path: Optional[str] = None) -> str:
    """Return a human-readable message. May raise exceptions for fatal errors."""
    # 1) Fetch manifest
    with urllib.request.urlopen(manifest_url, timeout=30) as r:
        manifest = json.loads(r.read().decode('utf-8'))

    version = manifest.get('version')
    asset_url = manifest.get('asset_url')
    sha256 = manifest.get('sha256')
    sig = manifest.get('sig')

    if not all([version, asset_url, sha256, sig]):
        raise ValueError('Manifest missing required fields')

    if version == current_version:
        return f"Versi terbaru terpasang ({current_version})."

    # Verify signature over canonical message
    msg = (version + "\n" + asset_url + "\n" + sha256).encode('utf-8')
    if not _verify_signature(public_key_path, msg, sig):
        raise ValueError('Signature manifest tidak valid')

    # Download asset
    tmp = tempfile.mkdtemp(prefix='rr_update_')
    asset_path = os.path.join(tmp, os.path.basename(asset_url))
    _download_url(asset_url, asset_path)

    # Verify sha256
    got = _sha256_of_file(asset_path)
    if got.lower() != sha256.lower():
        raise ValueError('Checksum tidak cocok')

    # Launch updater helper to replace binary (if provided)
    if not app_exe_path:
        return f"Update tersedia: {version}. File diunduh ke {asset_path}."

    updater = os.path.join(os.path.dirname(__file__), 'updater_helper.py')
    # run updater as separate process: python updater_helper.py <old_exe> <new_file>
    proc = subprocess.Popen([os.sys.executable, updater, app_exe_path, asset_path], close_fds=True)
    return f"Update {version} terunduh. Proses updater dimulai (PID {proc.pid})."