"""Supabase Auth (Google OAuth + Email/Password) untuk aplikasi desktop.

Mirror interface dari firebase_auth.FirebaseAuth agar bisa ditukar dengan alias.
"""
import base64
import json
import logging
import os
import sys
import threading
import time
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

import requests

_LOGGER = logging.getLogger(__name__)

SUPABASE_URL = "https://nqaucjpbnewckedqcezb.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5xYXVjanBibmV3Y2tlZHFjZXpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg1MjUyNzUsImV4cCI6MjEwNDEwMTI3NX0.xi-h-3E2Yww95HzXsNmmiOmdvMKi_TaFNw8Op7xryig"
AUTH_FILE = "rr_billing_auth_supabase.json"
_INSTANCE: Optional["SupabaseAuth"] = None
_INSTANCE_LOCK = threading.Lock()


def _jwt_payload(token: str) -> dict:
    """Decode payload JWT (tanpa verifikasi) — dipakai ambil email/user_metadata
    dari accessToken Google. Return {} bila token bukan JWT valid."""
    try:
        parts = str(token or "").split(".")
        if len(parts) < 2:
            return {}
        seg = parts[1]
        seg += "=" * (-len(seg) % 4)
        return json.loads(base64.urlsafe_b64decode(seg.encode("ascii")).decode("utf-8", "replace"))
    except Exception:
        return {}


def _get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _auth_file_path() -> str:
    return os.path.join(_get_app_dir(), AUTH_FILE)


class SupabaseAuth:
    def __init__(self):
        self._access_token: str = ""
        self._refresh_token: str = ""
        self._expires_at: int = 0
        self._email: str = ""
        self._display_name: str = ""
        self._user_id: str = ""
        self._loaded = False
        self._loading = threading.Lock()
        self._load_from_file()

    # ── Persistence ────────────────────────────────────────────────────────

    def _load_from_file(self):
        path = _auth_file_path()
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    d = json.load(f)
                self._access_token = d.get("accessToken", "")
                self._refresh_token = d.get("refreshToken", "")
                self._expires_at = int(d.get("expiresAt", 0) or 0)
                self._email = d.get("email", "")
                self._display_name = d.get("displayName", "")
                self._user_id = d.get("userId", "")
                self._loaded = True
            except Exception as e:
                _LOGGER.warning("Gagal load auth file: %s", e)

    def _save_to_file(self):
        path = _auth_file_path()
        try:
            with open(path, "w") as f:
                json.dump({
                    "accessToken": self._access_token,
                    "refreshToken": self._refresh_token,
                    "expiresAt": self._expires_at,
                    "email": self._email,
                    "displayName": self._display_name,
                    "userId": self._user_id,
                }, f, indent=2)
        except Exception as e:
            _LOGGER.warning("Gagal simpan auth file: %s", e)

    def clear(self):
        self._access_token = ""
        self._refresh_token = ""
        self._expires_at = 0
        self._email = ""
        self._display_name = ""
        self._user_id = ""
        self._loaded = False
        try:
            os.remove(_auth_file_path())
        except Exception:
            pass

    # ── Helpers ────────────────────────────────────────────────────────────

    def get_email(self) -> str:
        return self._email

    def get_display_name(self) -> str:
        return self._display_name

    def is_logged_in(self) -> bool:
        if not self._access_token:
            return False
        if self._is_expired():
            return bool(self._try_refresh())
        user = self._get_user_info()
        return user is not None

    def _is_expired(self) -> bool:
        if not self._expires_at:
            return False
        return (int(time.time()) + 30) >= self._expires_at

    def _get_user_info(self) -> Optional[dict]:
        try:
            resp = requests.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {self._access_token}",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
            _LOGGER.info("get_user_info HTTP %s", resp.status_code)
            return None
        except Exception as e:
            _LOGGER.warning("get_user_info error: %s", e)
            return None

    def _try_refresh(self) -> bool:
        if not self._refresh_token:
            return False
        try:
            resp = requests.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
                headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"},
                json={"refresh_token": self._refresh_token},
                timeout=15,
            )
            data = resp.json()
            if "access_token" in data:
                self._set_session(data)
                return True
        except Exception as e:
            _LOGGER.warning("refresh token error: %s", e)
        return False

    def _set_session(self, data: dict):
        self._access_token = data.get("access_token", "")
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        expires_in = int(data.get("expires_in", 3600) or 3600)
        self._expires_at = int(time.time()) + expires_in
        user = data.get("user") or {}
        if not isinstance(user, dict):
            user = {}
        # ── Login Google via browser HANYA mengirim access_token (tanpa 'user'),
        #    sehingga email sebelumnya kosong → akun jadi tak dikenal (username
        #    acak seperti '_3') & lisensi tidak ketemu. Ambil profil dari token
        #    atau dari endpoint /auth/v1/user. ──
        if not (user.get("email") or "").strip():
            user = self._profil_dari_token() or user
        self._user_id = user.get("id") or user.get("sub") or self._user_id
        email = str(user.get("email") or self._email or "").strip()
        if email:
            self._email = email
        meta = (user.get("user_metadata") or {}) if isinstance(user, dict) else {}
        self._display_name = (meta.get("full_name") or meta.get("name")
                              or str(user.get("name") or "") or self._email or "")
        if not self._email:
            _LOGGER.warning("Login berhasil tetapi email kosong — akun tidak bisa dicocokkan")
        else:
            _LOGGER.info("Auth session: email=%s display=%s", self._email, self._display_name)
        self._save_to_file()

    def _profil_dari_token(self) -> dict:
        """Ambil profil user dari access token: coba decode JWT, lalu GET /auth/v1/user."""
        claims = _jwt_payload(self._access_token)
        profil = {}
        email = str(claims.get("email") or "").strip()
        meta = claims.get("user_metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        if email or meta:
            profil = {
                "id": claims.get("sub") or "",
                "email": email,
                "user_metadata": meta,
            }
        if email:
            return profil
        # Fallback: tanya Supabase (JWT bisa di-blacklist / tidak punya claim email)
        try:
            info = self._get_user_info()
            if isinstance(info, dict) and (info.get("email") or info.get("user_metadata")):
                return info
        except Exception as e:
            _LOGGER.debug("profil dari /auth/v1/user gagal: %s", e)
        return profil

    def ensure_anonymous(self) -> bool:
        """Supabase tidak butuh anonymous token untuk anon-key; selalu True."""
        return True

    # ── Email/Password Auth ────────────────────────────────────────────────

    def sign_up(self, email: str, password: str) -> tuple[bool, str]:
        try:
            resp = requests.post(
                f"{SUPABASE_URL}/auth/v1/signup",
                headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"},
                json={"email": email, "password": password},
                timeout=15,
            )
            data = resp.json()
            if resp.status_code in (200, 201) and ("access_token" in data or data.get("user")):
                if "access_token" in data:
                    self._set_session(data)
                return True, "Sukses"
            return False, str(data.get("error_description") or data.get("message") or "Gagal daftar")
        except Exception as e:
            return False, str(e)

    def login_with_email(self, email: str, password: str) -> tuple[bool, str]:
        try:
            resp = requests.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"},
                json={"email": email, "password": password},
                timeout=15,
            )
            data = resp.json()
            if "access_token" in data:
                self._set_session(data)
                return True, "OK"
            return False, str(data.get("error_description") or data.get("msg") or "Gagal login")
        except Exception as e:
            return False, str(e)

    # ── Google OAuth ───────────────────────────────────────────────────────

    def login_with_google(self) -> tuple[bool, str]:
        import socket as _socket
        import webbrowser

        port = self._find_free_port(18080, 19000)
        if not port:
            return False, "Tidak bisa membuka server lokal"

        result = [None]
        parent_html = self._provider_redirect_html()

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/" or self.path == "/index.html":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(parent_html.encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if self.path == "/token":
                    try:
                        length = int(self.headers.get("Content-Length", 0))
                        body = self.rfile.read(length)
                        data = json.loads(body)
                        access_token = data.get("accessToken", "")
                        refresh_token = data.get("refreshToken", "")
                        expires_in = int(data.get("expiresIn", 3600) or 3600)
                        if not access_token:
                            self._reply(400, {"success": False, "error": "No accessToken"})
                            return
                        match = self.server._set_session({
                            "access_token": access_token,
                            "refresh_token": refresh_token,
                            "expires_in": expires_in,
                            "user": data.get("user") or {},
                        })
                        result[0] = True
                        self._reply(200, {"success": True})
                        threading.Thread(target=self.server.shutdown, daemon=True).start()
                    except Exception as e:
                        self._reply(500, {"success": False, "error": str(e)})
                else:
                    self.send_response(404)
                    self.end_headers()

            def _reply(self, code, obj):
                body = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def log_message(self, fmt, *args):
                pass

        server = HTTPServer(("localhost", port), _Handler)
        server._set_session = lambda data: self._set_session(data) or True  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        authorize_url = (
            f"{SUPABASE_URL}/auth/v1/authorize?provider=google"
            f"&redirect_to={urllib.parse.quote(f'http://localhost:{port}/')}"
            f"&apikey={SUPABASE_KEY}"
        )
        try:
            webbrowser.open(authorize_url)
        except Exception as e:
            return False, f"Gagal membuka browser: {e}"

        thread.join(timeout=300)
        try:
            server.shutdown()
        except Exception:
            pass

        if result[0]:
            return True, "Login Google berhasil"
        return False, "Login Google gagal / dibatalkan"

    def _provider_redirect_html(self) -> str:
        return f"""<!DOCTYPE html>
<html lang="id">
<head><meta charset="utf-8"><title>Login Google</title>
<style>body{{font-family:sans-serif;text-align:center;padding-top:60px;background:#f5f5f5;}}</style>
</head>
<body>
  <h2>Masuk dengan RR Billing Pro</h2>
  <p id="status">Menunggu login Google...</p>
<script>
var hash = window.location.hash.substring(1);
var params = new URLSearchParams(hash);
var accessToken = params.get("access_token") || "";
var refreshToken = params.get("refresh_token") || "";
var expiresIn = parseInt(params.get("expires_in") || "3600");
async function kirim() {{
  if (accessToken) {{
    document.getElementById("status").textContent = "Mengirim token...";
    try {{
      var resp = await fetch("/token", {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{ accessToken: accessToken, refreshToken: refreshToken, expiresIn: expiresIn }})
      }});
      var data = await resp.json();
      if (data.success) {{
        document.body.innerHTML = "<h2>Login berhasil! Silakan kembali ke aplikasi.</h2>";
      }} else {{
        document.getElementById("status").textContent = "Gagal: " + (data.error || "unknown");
      }}
    }} catch (e) {{
      document.getElementById("status").textContent = "Error: " + e.message;
    }}
  }} else {{
    var errorDesc = params.get("error_description") || params.get("error") || "";
    document.getElementById("status").textContent = "Belum login / gagal: " + errorDesc;
  }}
}}
kirim();
</script>
</body></html>"""

    @staticmethod
    def _find_free_port(start: int, end: int) -> Optional[int]:
        import socket
        for port in range(start, end):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(("localhost", port))
                s.close()
                return port
            except OSError:
                continue
        return None


def get_supabase_auth() -> SupabaseAuth:
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = SupabaseAuth()
        return _INSTANCE
