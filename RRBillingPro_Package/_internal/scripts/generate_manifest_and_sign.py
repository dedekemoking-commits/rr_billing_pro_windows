"""Generate manifest.json and signature for release.
Usage:
  python scripts/generate_manifest_and_sign.py --version VERSION --asset_url URL --sha256 SHA256 --signing_key "<PEM>" --out manifest.json
The signing_key argument should be the PEM private key text (can be read from GitHub Secret).
"""
import argparse
import json
import base64
import os
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--version', required=True)
    p.add_argument('--asset_url', required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--signing_key', required=True)
    p.add_argument('--out', required=True)
    args = p.parse_args()

    message = (args.version + "\n" + args.asset_url + "\n" + args.sha256).encode('utf-8')

    # Load private key
    key_pem = args.signing_key.encode('utf-8')
    priv = load_pem_private_key(key_pem, password=None)
    sig = priv.sign(message, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.b64encode(sig).decode('ascii')

    manifest = {
        'version': args.version,
        'asset_url': args.asset_url,
        'sha256': args.sha256,
        'sig': sig_b64,
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    print('Wrote', args.out)

if __name__ == '__main__':
    main()
