#!/usr/bin/env python3
"""Test script: generate RSA keys, fake asset, manifest, sign, then call check_update.check_for_update with file:// URLs."""
import os, json, base64, hashlib
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)

priv_path = os.path.join(REPO, 'signing_test_private.pem')
pub_path = os.path.join(REPO, 'update_pubkey.pem')
asset_dir = os.path.join(REPO, 'dist')
manifest_path = os.path.join(REPO, 'manifest.test.json')
asset_path = os.path.join(asset_dir, 'main_v2_test.exe')

os.makedirs(asset_dir, exist_ok=True)

# Generate RSA key pair
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
priv_pem = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
)
pub_pem = key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)
with open(priv_path, 'wb') as f:
    f.write(priv_pem)
with open(pub_path, 'wb') as f:
    f.write(pub_pem)
print('Wrote keys:', priv_path, pub_path)

# Create fake asset
with open(asset_path, 'wb') as f:
    f.write(b'This is a fake exe for testing auto-update.\nVersion 2.2')
print('Wrote asset:', asset_path)

# Compute sha256
h = hashlib.sha256()
with open(asset_path, 'rb') as f:
    while True:
        chunk = f.read(8192)
        if not chunk:
            break
        h.update(chunk)
sha256 = h.hexdigest()
print('SHA256:', sha256)

# Create manifest and sign
version = '2.2'
asset_url = 'file://' + asset_path.replace('\\', '/')
message = (version + "\n" + asset_url + "\n" + sha256).encode('utf-8')
sig = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
sig_b64 = base64.b64encode(sig).decode('ascii')
manifest = {'version': version, 'asset_url': asset_url, 'sha256': sha256, 'sig': sig_b64}
with open(manifest_path, 'w', encoding='utf-8') as f:
    json.dump(manifest, f, indent=2)
print('Wrote manifest:', manifest_path)

# Call check_update
from scripts import check_update
try:
    res = check_update.check_for_update('file://' + manifest_path.replace('\\', '/'), pub_path, '2.1', None)
    print('check_for_update result:')
    print(res)
except Exception as e:
    print('check_for_update raised:', e)
    raise
