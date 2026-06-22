import os
import base64
import json
import tempfile
import importlib

import rr_crypto


def _set_env_key(tmp_key: bytes):
    b64 = base64.urlsafe_b64encode(tmp_key).decode('ascii').rstrip('=')
    os.environ['RR_BILLING_DATA_KEY'] = b64


def test_save_load_plain_and_encrypted(tmp_path, monkeypatch):
    # ensure deterministic key via env
    key = b"\x00" * 32
    _set_env_key(key)
    importlib.reload(rr_crypto)

    p = tmp_path / "cfg.json"
    data = {"a": 1}
    rr_crypto.save_json_file(str(p), data)
    assert p.exists()
    loaded = rr_crypto.load_json_file(str(p))
    assert loaded == data

    # Ensure backward compatibility: create legacy raw format (nonce + ct)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, json.dumps(data).encode('utf-8'), None)
    raw = nonce + ct
    legacy = tmp_path / "legacy.json.enc"
    legacy.write_bytes(raw)
    # reload module to ensure derive uses env key
    importlib.reload(rr_crypto)
    loaded2 = rr_crypto.load_json_file(str(legacy))
    assert loaded2 == data


def test_dpapi_failure_fallback(tmp_path, monkeypatch):
    # simulate DPAPI unavailable by forcing _load_master_key_dpapi to return None
    monkeypatch.setattr(rr_crypto, '_load_master_key_dpapi', lambda: None)
    # Provide secret but without salt to trigger RuntimeError in derive fallback
    monkeypatch.setenv('RR_LICENSE_SECRET', 'some-secret')
    monkeypatch.delenv('RR_BILLING_DATA_KEY', raising=False)
    importlib.reload(rr_crypto)
    # Now calling _derive_key should raise because salt missing
    raised = False
    try:
        rr_crypto._derive_key()
    except RuntimeError:
        raised = True
    assert raised
