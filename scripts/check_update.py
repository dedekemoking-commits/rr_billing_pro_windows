"""Simple updater client:
- Fetch manifest.json from a URL (HTTPS/file)
- Manifest JSON fields: version, asset_url, sha256, sig (base64 of signature over 'version\nasset_url\nsha256')
- Verify signature with provided RSA public key (PEM)
- Download asset to temp, verify sha256
- Launch updater to replace binary (batch on Windows EXE, python helper in source mode)

Usage: call check_for_update(manifest_url, public_key_path, current_version, app_exe_path)
or use the two-step flow: fetch_manifest + verify_manifest, then
download_asset + launch_updater (so the UI can confirm before downloading).
"""
from __future__ import annotations
import json
import os
import re
import sys
import subprocess
import urllib.request
import urllib.error
import hashlib
import base64
import tempfile
from typing import Callable, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key


def _subprocess_no_window_kwargs() -> dict:
    if os.name != "nt":
        return {}
    kwargs = {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags
    startup_cls = getattr(subprocess, "STARTUPINFO", None)
    if startup_cls is not None:
        startupinfo = startup_cls()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    return kwargs


def resolve_pubkey(pubkey_path: Optional[str] = None) -> Optional[str]:
    """Temukan update_pubkey.pem di lokasi yang benar (EXE frozen / source)."""
    candidates: list[str] = []
    if pubkey_path:
        candidates.append(pubkey_path)
    # Frozen (PyInstaller): pubkey di samping exe, lalu di _internal
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(exe_dir, "update_pubkey.pem"))
        candidates.append(os.path.join(exe_dir, "_internal", "update_pubkey.pem"))
    # Source: samping script ini
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "update_pubkey.pem"))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "update_pubkey.pem"))
    for c in candidates:
        try:
            if os.path.isfile(c):
                return c
        except Exception:
            continue
    return None


def _download_url(url: str, out_path: str, progress_cb: Optional[Callable[[int, int], None]] = None):
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            total = int(r.headers.get('content-length', 0))
            downloaded = 0
            with open(out_path, 'wb') as f:
                while True:
                    chunk = r.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError(
                f"Download GAGAL: file tidak ditemukan di server (HTTP 404).\n\n"
                f"URL: {url}\n\n"
                "File ini belum di-upload ke release terbaru. Laporkan ke admin "
                "agar asset (mis. RRBillingPro-TV.apk) di-upload ke GitHub release.")
        raise ValueError(f"HTTP Error {e.code} saat mengakses {url}")
    except urllib.error.URLError as e:
        raise ValueError(f"Tidak dapat mengakses URL: {e.reason}")
    except Exception as e:
        raise ValueError(f"Gagal download dari {url}: {str(e)}")


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


def fetch_manifest(manifest_url: str) -> dict:
    """Ambil + parse manifest.json dari URL. Raise ValueError jika gagal."""
    try:
        with urllib.request.urlopen(manifest_url, timeout=30) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise ValueError(f"Gagal membuka manifest (HTTP {e.code}): {manifest_url}\n\nPastikan URL tersedia dan file manifest.json ada di release.")
    except urllib.error.URLError as e:
        raise ValueError(f"Tidak dapat mengakses manifest: {e.reason}")
    except json.JSONDecodeError:
        raise ValueError("Manifest bukan JSON valid")
    except Exception as e:
        raise ValueError(f"Gagal fetch manifest: {str(e)}")


def verify_manifest(manifest: dict, pubkey_path: Optional[str]) -> bool:
    """Verifikasi tanda tangan RSA manifest. False jika key tidak ditemukan / sig salah."""
    pk = resolve_pubkey(pubkey_path)
    if not pk:
        raise ValueError("update_pubkey.pem tidak ditemukan — verifikasi pembaruan tidak bisa dilakukan.")
    version = manifest.get('version')
    asset_url = manifest.get('asset_url')
    sha256 = manifest.get('sha256')
    sig = manifest.get('sig')
    if not all([version, asset_url, sha256, sig]):
        raise ValueError('Manifest missing required fields')
    msg = (version + "\n" + asset_url + "\n" + sha256).encode('utf-8')
    return _verify_signature(pk, msg, sig)


def find_latest_apk_url(repo_url: str) -> Optional[str]:
    """Cari asset .apk terbaru dari release GitHub 'latest' via API publik.

    repo_url boleh URL repo penuh (mis. update_manifest_url); pasangan
    owner/repo di-parse dari pola github.com/<owner>/<repo>. Preferensi asset
    .apk dengan nama mengandung 'tv', dipilih yang paling baru (updated_at).
    Return browser_download_url, atau None bila repo bukan GitHub /
    API gagal / tidak ada asset .apk di release terbaru.
    """
    if not repo_url:
        return None
    m = re.search(r"github\.com/([^/]+)/([^/]+)", repo_url)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    api = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    try:
        with urllib.request.urlopen(api, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    apk_assets = [
        a for a in data.get("assets", [])
        if str(a.get("name") or "").lower().endswith(".apk")
    ]
    if not apk_assets:
        return None
    apk_assets.sort(
        key=lambda a: str(a.get("updated_at") or a.get("created_at") or ""),
        reverse=True)
    for a in apk_assets:
        if "tv" in str(a.get("name") or "").lower():
            return str(a.get("browser_download_url") or "")
    return str(apk_assets[0].get("browser_download_url") or "")


def find_aapt() -> Optional[str]:
    """Lokasi aapt.exe (Android build-tools): PATH → ANDROID_HOME → LOCALAPPDATA.
    Return path aapt.exe atau None bila tidak tersedia."""
    import shutil
    p = shutil.which("aapt")
    if p:
        return p
    roots = []
    if os.environ.get("ANDROID_HOME"):
        roots.append(os.environ["ANDROID_HOME"])
    if os.environ.get("LOCALAPPDATA"):
        roots.append(os.path.join(os.environ["LOCALAPPDATA"], "Android", "Sdk"))
    for root in roots:
        bts = os.path.join(root, "build-tools")
        try:
            if not os.path.isdir(bts):
                continue
            for ver in sorted(os.listdir(bts), reverse=True):
                cand = os.path.join(bts, ver, "aapt.exe")
                if os.path.isfile(cand):
                    return cand
        except Exception:
            continue
    return None


def read_apk_version(apk_path: str):
    """Baca versionCode & versionName dari APK via aapt.

    Return tuple (version_code: int|None, version_name: str|None).
    None bila aapt tidak tersedia / APK tidak bisa dibaca.
    """
    aapt = find_aapt()
    if not aapt or not apk_path or not os.path.isfile(apk_path):
        return None, None
    try:
        out = subprocess.run(
            [aapt, "dump", "badging", apk_path],
            capture_output=True, text=True, timeout=60,
            **_subprocess_no_window_kwargs()).stdout or ""
    except Exception:
        return None, None
    m1 = re.search(r"versionCode='(\d+)'", out)
    m2 = re.search(r"versionName='([^']*)'", out)
    code = int(m1.group(1)) if m1 else None
    name = m2.group(1) if m2 else None
    return code, name


def download_asset(asset_url: str, out_path: str, expected_sha256: Optional[str] = None,
                   progress_cb: Optional[Callable[[int, int], None]] = None) -> str:
    """Unduh aset ke out_path, verifikasi sha256 bila diberikan. Return sha256 file."""
    _download_url(asset_url, out_path, progress_cb)
    got = _sha256_of_file(out_path)
    if expected_sha256 and got.lower() != expected_sha256.lower():
        raise ValueError('Checksum tidak cocok')
    return got


def launch_updater(app_exe_path: str, new_file: str) -> str:
    """Ganti app_exe_path dengan new_file, lalu restart.

    - EXE (PyInstaller frozen): tulis apply_update.bat di samping exe, jalankan
      lewat cmd.exe (detached) — batch menunggu proses mati, replace, restart.
    - Source: pakai updater_helper.py via interpreter python.
    """
    if not app_exe_path or not os.path.exists(app_exe_path):
        raise ValueError("Path executable aplikasi tidak valid.")

    frozen = getattr(sys, "frozen", False) or app_exe_path.lower().endswith(".exe")
    if not frozen:
        updater = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'updater_helper.py')
        proc = subprocess.Popen(
            [sys.executable, updater, app_exe_path, new_file],
            close_fds=True,
            **_subprocess_no_window_kwargs()
        )
        return f"Proses updater dimulai (PID {proc.pid}). Aplikasi akan dimulai ulang otomatis."

    # Frozen Windows: batch mandiri yang menunggu exe tidak terkunci lalu replace + restart
    app_dir = os.path.dirname(os.path.abspath(app_exe_path))
    exe_name = os.path.basename(app_exe_path)
    staged = os.path.join(app_dir, "update_staged.exe")
    try:
        os.replace(new_file, staged)
    except Exception:
        staged = new_file  # fallback: pakai path asli

    bat_path = os.path.join(app_dir, "apply_update.bat")
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "timeout /t 3 /nobreak >nul",
        f'move /y "{exe_name}" "{exe_name}.old" >nul 2>&1',
        f'move /y "update_staged.exe" "{exe_name}" >nul 2>&1',
        f'if exist "{exe_name}.old" del /q "{exe_name}.old"',
        f'start "" "{exe_name}"',
        'del "%~f0"',
    ]
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines))

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(["cmd.exe", "/c", bat_path], cwd=app_dir, close_fds=True,
                     creationflags=flags)
    return "Update diterapkan. Aplikasi akan menutup lalu restart otomatis dengan versi baru."


def check_for_update(manifest_url: str, public_key_path: Optional[str], current_version: str,
                     app_exe_path: Optional[str] = None,
                     progress_cb: Optional[Callable[[int, int], None]] = None) -> str:
    """Alur lengkap satu tahap: fetch manifest → verifikasi → unduh → terapkan.

    Return pesan untuk user. Raise ValueError untuk error fatal.
    """
    manifest = fetch_manifest(manifest_url)
    version = manifest.get('version')
    asset_url = manifest.get('asset_url')
    sha256 = manifest.get('sha256')
    if not all([version, asset_url, sha256]):
        raise ValueError('Manifest missing required fields')

    if version == current_version:
        return f"Versi terbaru terpasang ({current_version})."

    if not verify_manifest(manifest, public_key_path):
        raise ValueError('Signature manifest tidak valid')

    tmp = tempfile.mkdtemp(prefix='rr_update_')
    asset_path = os.path.join(tmp, os.path.basename(asset_url) or "update.exe")
    download_asset(asset_url, asset_path, sha256, progress_cb)

    if not app_exe_path:
        return f"Update tersedia: {version}. File diunduh ke {asset_path}."

    return launch_updater(app_exe_path, asset_path)
