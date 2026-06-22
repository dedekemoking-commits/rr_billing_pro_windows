#!/usr/bin/env python3
"""Generate new RSA key pair."""
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

# Generate new RSA key pair (2048 bits)
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)

# Get public key
public_key = private_key.public_key()

# Serialize private key to PEM
private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)

# Serialize public key to PEM
public_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
)

# Save private key
with open('keys/private_key_new.pem', 'wb') as f:
    f.write(private_pem)
print("✅ Private key saved: keys/private_key_new.pem")

# Save public key as update_pubkey.pem
with open('update_pubkey.pem', 'wb') as f:
    f.write(public_pem)
print("✅ Public key saved: update_pubkey.pem")
