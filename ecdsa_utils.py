import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization

PUBLIC_KEY_B64 = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEtwmjVNVdjDQsMIl/oky9NxoAJ9pCZ7RqNUsQo9k1gzgvAOjlfDmxfXjoSMBu/T2llMjItylfC7fH680buJofuQ=="

# Private key yang SAMA dengan Android License Generator (PKCS#8 DER base64)
PRIVATE_KEY_B64 = "MEECAQAwEwYHKoZIzj0CAQYIKoZIzj0DAQcEJzAlAgEBBCD78iOiQrMsmei7ba0bqd6jTeiZPgiePwujiiQgd+g3ZQ=="

_public_key = None
_private_key = None


def _get_public_key():
    global _public_key
    if _public_key is not None:
        return _public_key
    der = base64.b64decode(PUBLIC_KEY_B64)
    _public_key = serialization.load_der_public_key(der)
    return _public_key


def _get_private_key():
    global _private_key
    if _private_key is not None:
        return _private_key
    der = base64.b64decode(PRIVATE_KEY_B64)
    _private_key = serialization.load_der_private_key(der, password=None)
    return _private_key


def verify(data: str, signature_b64: str) -> bool:
    try:
        pub = _get_public_key()
        sig_bytes = base64.b64decode(signature_b64)
        pub.verify(sig_bytes, data.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False


def sign(data: str) -> str:
    priv = _get_private_key()
    sig = priv.sign(data.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(sig).decode()
