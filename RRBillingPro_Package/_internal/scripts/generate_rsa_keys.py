"""Generate RSA key pair for signing updates.
Usage:
  python scripts/generate_rsa_keys.py --out-dir keys

This writes two files in the out-dir:
  - private_key.pem (PKCS#8 PEM)  <-- keep secret, add to GitHub secret SIGNING_PRIVATE_KEY
  - public_key.pem  (SubjectPublicKeyInfo PEM)  <-- commit to repo as update_pubkey.pem or ship with app
"""
import argparse
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out-dir', default='keys')
    args = p.parse_args()

    out_dir = args.out_dir
    import os
    os.makedirs(out_dir, exist_ok=True)

    # Generate 2048-bit RSA key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )

    public_key = key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    priv_path = os.path.join(out_dir, 'private_key.pem')
    pub_path = os.path.join(out_dir, 'public_key.pem')

    with open(priv_path, 'wb') as f:
        f.write(private_pem)
    with open(pub_path, 'wb') as f:
        f.write(public_pem)

    print('Wrote private key to', priv_path)
    print('Wrote public key to', pub_path)
    print('\nNext steps:')
    print('1) Copy private_key.pem contents into GitHub repo secret SIGNING_PRIVATE_KEY')
    print('   (Repository -> Settings -> Secrets -> Actions)')
    print("2) Commit public_key.pem as 'update_pubkey.pem' in the repository so clients can verify manifests.")

if __name__ == '__main__':
    main()
