import base64
import json
import logging
import os
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Environment names
DATA_KEY_ENV = "RR_BILLING_DATA_KEY"
DATA_SALT_ENV = "RR_BILLING_DATA_SALT"

# DPAPI-protected key file (per-user)
_APP_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "RRBilling")
_DPAPI_KEY_PATH = os.path.join(_APP_DIR, "data_key.bin")

# Logging
logger = logging.getLogger("rr_crypto")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(os.environ.get("RR_CRYPTO_LOG_LEVEL", "WARNING"))


# DPAPI helpers: prefer pywin32's win32crypt, fall back to informative error
try:
    import win32crypt  # type: ignore

    def _dpapi_protect(data: bytes) -> bytes:
        blob = win32crypt.CryptProtectData(data, "RRBilling Data Key", None, None, None, 0)
        return blob

    def _dpapi_unprotect(blob: bytes) -> bytes:
        tup = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
        # win32crypt returns (decrypted, description) on many installs
        if isinstance(tup, tuple):
            return tup[1] if len(tup) > 1 and tup[1] is not None and isinstance(tup[1], bytes) else tup[0]
        return tup

except Exception:
    win32crypt = None

    def _dpapi_protect(data: bytes) -> bytes:
        raise RuntimeError("pywin32 is required for DPAPI support. Install pywin32.")

    def _dpapi_unprotect(blob: bytes) -> bytes:
        raise RuntimeError("pywin32 is required for DPAPI support. Install pywin32.")


def _ensure_app_dir():
    try:
        os.makedirs(_APP_DIR, exist_ok=True)
    except Exception as e:
        logger.warning("Could not create app dir %s: %s", _APP_DIR, e)


def _save_master_key_dpapi(key: bytes):
    _ensure_app_dir()
    try:
        enc = _dpapi_protect(key)
        with open(_DPAPI_KEY_PATH, "wb") as f:
            f.write(enc)
        logger.info("Saved master key to DPAPI file %s", _DPAPI_KEY_PATH)
    except Exception as e:
        logger.exception("Failed saving master key to DPAPI: %s", e)
        raise


def _load_master_key_dpapi() -> Optional[bytes]:
    if not os.path.exists(_DPAPI_KEY_PATH):
        return None
    try:
        blob = open(_DPAPI_KEY_PATH, "rb").read()
        key = _dpapi_unprotect(blob)
        if isinstance(key, str):
            key = key.encode("utf-8")
        if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
            logger.warning("DPAPI file present but content not valid key length")
            return None
        return bytes(key)
    except Exception as e:
        logger.exception("Failed loading master key from DPAPI: %s", e)
        return None


def _derive_key() -> bytes:
    # 1) If user provided explicit base64 or raw key via env, use it
    env_key = os.environ.get(DATA_KEY_ENV, "")
    if env_key:
        try:
            # try urlsafe_b64 first
            decoded = base64.urlsafe_b64decode(env_key + "=" * (-len(env_key) % 4))
            if len(decoded) == 32:
                logger.info("Using key from %s (base64)", DATA_KEY_ENV)
                return decoded
        except Exception:
            raw = env_key.encode("utf-8")
            if len(raw) == 32:
                logger.info("Using key from %s (raw bytes)", DATA_KEY_ENV)
                return raw

    # 2) Try DPAPI-protected key file
    try:
        dpapi_key = _load_master_key_dpapi()
        if dpapi_key:
            logger.info("Using key loaded from DPAPI file")
            return dpapi_key
    except Exception:
        logger.exception("Error while loading DPAPI key")

    # 3) If RR_LICENSE_SECRET env provided, derive key (deprecated fallback)
    secret = os.environ.get("RR_LICENSE_SECRET")
    if secret:
        # If a salt is provided via env, use it; otherwise fail to avoid deterministic constant
        salt = os.environ.get(DATA_SALT_ENV)
        if not salt:
            raise RuntimeError("RR_LICENSE_SECRET present but no %s salt provided; set %s or provide DPAPI key" % (DATA_SALT_ENV, DATA_KEY_ENV))
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt.encode("utf-8"), iterations=390000)
        derived = kdf.derive(secret.encode("utf-8"))
        logger.warning("Derived key from RR_LICENSE_SECRET (fallback path)")
        return derived

    # 4) No key found: generate a new random key, persist via DPAPI if available
    new_key = os.urandom(32)
    try:
        _save_master_key_dpapi(new_key)
        logger.info("Generated new master key and saved to DPAPI")
    except Exception:
        logger.warning("Could not persist new master key to DPAPI; key will be ephemeral for this run")
    return new_key


def encrypt_bytes(payload: bytes) -> bytes:
    key = _derive_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, payload, None)
    # store as JSON wrapper with base64 fields so salt/nonce can be extended later
    wrapper = {
        "v": 1,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "data": base64.b64encode(ct).decode("ascii"),
    }
    return json.dumps(wrapper).encode("utf-8")


def decrypt_bytes(ciphertext: bytes) -> bytes:
    # Support two formats:
    # 1) new JSON wrapper: {v, nonce, data}
    # 2) old raw: nonce(12) + ciphertext
    try:
        obj = json.loads(ciphertext.decode("utf-8"))
        if isinstance(obj, dict) and obj.get("v") == 1 and "nonce" in obj and "data" in obj:
            nonce = base64.b64decode(obj["nonce"])
            ct = base64.b64decode(obj["data"])
            key = _derive_key()
            aesgcm = AESGCM(key)
            return aesgcm.decrypt(nonce, ct, None)
    except Exception:
        # not JSON wrapper; try old raw format
        pass

    if len(ciphertext) < 13:
        raise ValueError("Ciphertext too short")
    key = _derive_key()
    aesgcm = AESGCM(key)
    nonce = ciphertext[:12]
    data = ciphertext[12:]
    return aesgcm.decrypt(nonce, data, None)


def load_json_file(path: str, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        raw = open(path, "rb").read()
        if not raw:
            return default if default is not None else {}

        # First, try to detect new wrapper (JSON) and decrypt
        try:
            obj = json.loads(raw.decode("utf-8"))
            if isinstance(obj, dict) and obj.get("v") == 1 and "nonce" in obj and "data" in obj:
                try:
                    decrypted = decrypt_bytes(raw)
                    return json.loads(decrypted.decode("utf-8"))
                except InvalidTag:
                    logger.warning("Decryption failed: invalid tag for file %s", path)
                    return default if default is not None else {}
        except Exception:
            # not wrapper JSON; continue
            pass

        # Try old encrypted raw format
        try:
            decrypted = decrypt_bytes(raw)
            return json.loads(decrypted.decode("utf-8"))
        except InvalidTag:
            # If decryption fails with InvalidTag, try plaintext fallback
            logger.warning("Invalid authentication tag when decrypting %s; attempting plaintext parse", path)
        except Exception as e:
            logger.debug("Decrypt attempt failed: %s", e)

        # Fallback to plaintext JSON
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            logger.exception("Failed to parse JSON (encrypted or plaintext) for %s", path)
            return default if default is not None else {}
    except Exception:
        logger.exception("Unexpected error reading %s", path)
        return default if default is not None else {}


def save_json_file(path: str, payload):
    raw = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    encrypted = encrypt_bytes(raw)
    with open(path, "wb") as f:
        f.write(encrypted)
