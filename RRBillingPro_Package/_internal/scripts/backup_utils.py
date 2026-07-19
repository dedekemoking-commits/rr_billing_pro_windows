import base64
import json
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


def _derive_from_passphrase(passphrase: str, salt: bytes, iterations: int = 200000) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(passphrase.encode('utf-8'))


def encrypt_file_with_passphrase(in_path: str, out_path: str, passphrase: str) -> None:
    """Encrypt a file using a passphrase. Produces a JSON wrapper with salt+nonce+data."""
    salt = os.urandom(16)
    key = _derive_from_passphrase(passphrase, salt)
    aes = AESGCM(key)
    nonce = os.urandom(12)
    with open(in_path, 'rb') as f:
        data = f.read()
    ct = aes.encrypt(nonce, data, None)
    wrapper = {
        'v': 1,
        'salt': base64.b64encode(salt).decode('ascii'),
        'nonce': base64.b64encode(nonce).decode('ascii'),
        'data': base64.b64encode(ct).decode('ascii'),
    }
    with open(out_path, 'wb') as f:
        f.write(json.dumps(wrapper).encode('utf-8'))


def decrypt_file_with_passphrase(in_path: str, passphrase: str) -> bytes:
    with open(in_path, 'rb') as f:
        raw = f.read()
    obj = json.loads(raw.decode('utf-8'))
    if obj.get('v') != 1:
        raise ValueError('Unsupported format')
    salt = base64.b64decode(obj['salt'])
    nonce = base64.b64decode(obj['nonce'])
    ct = base64.b64decode(obj['data'])
    key = _derive_from_passphrase(passphrase, salt)
    aes = AESGCM(key)
    return aes.decrypt(nonce, ct, None)
