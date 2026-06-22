import os
import tempfile

from scripts import backup_utils


def test_encrypt_decrypt_roundtrip(tmp_path):
    data = b"this is a test blob\n" * 10
    in_file = tmp_path / 'blob.bin'
    in_file.write_bytes(data)
    out_file = tmp_path / 'blob.enc'
    passphrase = 's3cret-pass'
    backup_utils.encrypt_file_with_passphrase(str(in_file), str(out_file), passphrase)
    assert out_file.exists()
    recovered = backup_utils.decrypt_file_with_passphrase(str(out_file), passphrase)
    assert recovered == data
