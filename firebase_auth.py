import json
import logging
import os
import sys
import threading
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

import requests

_LOGGER = logging.getLogger(__name__)

API_KEY = "AIzaSyAqOxWEBD9_AqaMiMtFwbyTvh-d_mdVofQ"
GOOGLE_CLIENT_ID = "291349089700-9ndql598pqktq5edspdtimfppv9erj4l.apps.googleusercontent.com"
FIREBASE_AUTH_BASE = "https://identitytoolkit.googleapis.com/v1"
FIREBASE_TOKEN_BASE = "https://securetoken.googleapis.com/v1"
AUTH_FILE = "rr_billing_auth.json"


def _get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _auth_file_path() -> str:
    return os.path.join(_get_app_dir(), AUTH_FILE)


class FirebaseAuth:
    def __init__(self):
        self._id_token: str = ""
        self._refresh_token: str = ""
        self._local_id: str = ""
        self._email: str = ""
        self._display_name: str = ""
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
                self._id_token = d.get("idToken", "")
                self._refresh_token = d.get("refreshToken", "")
                self._local_id = d.get("localId", "")
                self._email = d.get("email", "")
                self._display_name = d.get("displayName", "")
                self._loaded = True
            except Exception as e:
                _LOGGER.warning("Gagal load auth file: %s", e)

    def _save_to_file(self):
        path = _auth_file_path()
        try:
            with open(path, "w") as f:
                json.dump({
                    "idToken": self._id_token,
                    "refreshToken": self._refresh_token,
                    "localId": self._local_id,
                    "email": self._email,
                    "displayName": self._display_name,
                }, f, indent=2)
        except Exception as e:
            _LOGGER.warning("Gagal simpan auth file: %s", e)

    def clear(self):
        self._id_token = ""
        self._refresh_token = ""
        self._local_id = ""
        self._email = ""
        self._display_name = ""
        self._loaded = False
        path = _auth_file_path()
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    def is_logged_in(self) -> bool:
        if not self._id_token:
            return False
        try:
            user = self._get_user_info()
            return user is not None
        except Exception:
            return self._try_refresh()

    def ensure_anonymous(self) -> bool:
        """Sign in anonymously if no valid token exists. Thread-safe."""
        if self._id_token and not self._is_token_expired():
            return True
        with self._loading:
            if self._id_token and not self._is_token_expired():
                return True
            return self._sign_in_anonymous()

    def _sign_in_anonymous(self) -> bool:
        """Anonymous sign-in via Firebase Auth REST API. No email/password needed."""
        try:
            resp = requests.post(
                f"{FIREBASE_AUTH_BASE}/accounts:signUp?key={API_KEY}",
                json={"returnSecureToken": True},
                timeout=15,
            )
            data = resp.json()
            if "idToken" in data:
                self._set_tokens({
                    "idToken": data["idToken"],
                    "refreshToken": data.get("refreshToken", ""),
                    "localId": data.get("localId", ""),
                })
                _LOGGER.info("Anonymous Firebase sign-in success")
                return True
            _LOGGER.warning("Anonymous sign-in failed: %s", data.get("error", {}).get("message", "unknown"))
            return False
        except requests.RequestException as e:
            _LOGGER.warning("Anonymous sign-in error: %s", e)
            return False

    # ── Email/Password Auth ────────────────────────────────────────────────

    def sign_up(self, email: str, password: str) -> tuple[bool, str]:
        try:
            resp = requests.post(
                f"{FIREBASE_AUTH_BASE}/accounts:signUp?key={API_KEY}",
                json={"email": email, "password": password, "returnSecureToken": True},
                timeout=15,
            )
            data = resp.json()
            if "idToken" in data:
                self._set_tokens(data)
                return True, "Akun berhasil dibuat"
            msg = data.get("error", {}).get("message", "Gagal daftar")
            return False, msg
        except requests.RequestException as e:
            return False, f"Koneksi gagal: {e}"

    def login_with_email(self, email: str, password: str) -> tuple[bool, str]:
        try:
            resp = requests.post(
                f"{FIREBASE_AUTH_BASE}/accounts:signInWithPassword?key={API_KEY}",
                json={"email": email, "password": password, "returnSecureToken": True},
                timeout=15,
            )
            data = resp.json()
            if "idToken" in data:
                self._set_tokens(data)
                return True, "Login berhasil"
            msg = data.get("error", {}).get("message", "Email atau password salah")
            return False, msg
        except requests.RequestException as e:
            return False, f"Koneksi gagal: {e}"

    # ── Google Sign-In (GIS) ──────────────────────────────────────────────

    @staticmethod
    def _load_logo() -> str:
        paths = []
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            paths.append(os.path.join(meipass, "logo_billingpro.b64"))
        paths.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "logo_billingpro.b64"))
        paths.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo_billingpro.b64"))
        for p in paths:
            try:
                with open(p) as f:
                    return f.read().strip()
            except Exception:
                continue
        return ""

    @staticmethod
    def _google_html(port: int) -> str:
        logo_b64 = FirebaseAuth._load_logo()
        if not logo_b64:
            logo_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        return f"""<!DOCTYPE html>
<html lang="id">
<head><meta charset="utf-8"><title>Login Google</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body {{ font-family:sans-serif; text-align:center; padding-top:60px; background:#f5f5f5; }}
  h2 {{ color:#333; }}
  button {{ font-size:18px; padding:12px 32px; border-radius:6px; border:1px solid #ddd;
            background:white; cursor:pointer; margin-top:16px; }}
  button:hover {{ background:#f1f1f1; }}
  #status {{ margin-top:20px; color:#666; }}
</style>
</head>
<body>
  <div id="firebaseui-auth-container"></div>
  <img src="data:image/png;base64,{logo_b64}"
       style="max-width:320px;height:auto;display:block;margin:0 auto 8px">
  <h2>Masuk dengan RR Billing Pro</h2>
  <p>Gunakan akun Google yang terdaftar.</p>
  <button id="btnLogin" onclick="login()">Sign in with Google</button>
  <p id="status">Klik tombol di atas untuk memulai.</p>

  <script src="https://www.gstatic.com/firebasejs/11.4.0/firebase-app-compat.js"></script>
  <script src="https://www.gstatic.com/firebasejs/11.4.0/firebase-auth-compat.js"></script>
  <script>
    firebase.initializeApp({{
      apiKey: "{API_KEY}",
      authDomain: "rrbillingpro.firebaseapp.com",
      projectId: "rrbillingpro",
    }});

    async function login() {{
      const btn = document.getElementById('btnLogin');
      btn.disabled = true;
      btn.textContent = '⏳ Memproses...';
      document.getElementById('status').textContent = 'Membuka popup Google...';

      try {{
        const provider = new firebase.auth.GoogleAuthProvider();
        provider.addScope('email');
        provider.addScope('profile');
        const result = await firebase.auth().signInWithPopup(provider);
        const token = await result.user.getIdToken();
        const refreshToken = result.user.refreshToken;
        const email = result.user.email || '';
        const displayName = result.user.displayName || '';
        const localId = result.user.uid;

        document.getElementById('status').textContent = '⏳ Mengirim token...';
        const resp = await fetch('/token', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{
            idToken: token,
            refreshToken: refreshToken,
            email: email,
            displayName: displayName,
            localId: localId
          }})
        }});
        const data = await resp.json();
        if (data.success) {{
          document.body.innerHTML = '<h2 style="margin-top:80px">✅ Login berhasil!</h2><p>Silakan kembali ke aplikasi.</p>';
        }} else {{
          btn.disabled = false;
          btn.textContent = 'Sign in with Google';
          document.getElementById('status').textContent = '✖ Gagal: ' + (data.error || 'Unknown');
        }}
      }} catch (err) {{
        btn.disabled = false;
        btn.textContent = '🔵  Sign in with Google';
        document.getElementById('status').textContent = '✖ Error: ' + (err.message || err);
      }}
    }}
  </script>
</body></html>"""

    def login_with_google(self) -> tuple[bool, str]:
        import socket as _socket
        import webbrowser

        port = self._find_free_port(18080, 19000)
        if not port:
            return False, "Tidak bisa membuka server lokal"

        result = [None]

        class _GISHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(self.server._html.encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if self.path == "/token":
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length)
                    try:
                        data = json.loads(body)
                        id_token = data.get("idToken", "")
                        if not id_token:
                            self._reply(400, {"success": False, "error": "No idToken"})
                            return
                        result[0] = ("ok", {
                            "idToken": id_token,
                            "refreshToken": data.get("refreshToken", ""),
                            "localId": data.get("localId", ""),
                            "email": data.get("email", ""),
                            "displayName": data.get("displayName", ""),
                        })
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

            def log_message(self, fmt, *args):
                pass

            # Allow access from any origin for the GIS script
            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

        server = HTTPServer(("localhost", port), _GISHandler)
        server._html = self._google_html(port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        webbrowser.open(f"http://localhost:{port}/")

        thread.join(timeout=120)
        try:
            server.shutdown()
        except Exception:
            pass

        if result[0] is None:
            return False, "Timeout menunggu login Google"

        status, data = result[0]
        if status == "ok":
            self._set_tokens(data)
            self._display_name = data.get("displayName", "")
            return True, "Login Google berhasil"
        return False, "Gagal login Google"

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
                s.close()
                continue
        return None

    # ── Token Management ──────────────────────────────────────────────────

    def _set_tokens(self, data: dict):
        self._id_token = data.get("idToken", "")
        self._refresh_token = data.get("refreshToken", "")
        self._local_id = data.get("localId", "")
        self._email = data.get("email", "")
        self._display_name = data.get("displayName", data.get("email", ""))
        self._loaded = True
        self._save_to_file()

    def get_id_token(self) -> str:
        if self._id_token and not self._is_token_expired():
            return self._id_token
        self._try_refresh()
        return self._id_token

    def get_email(self) -> str:
        return self._email

    def get_display_name(self) -> str:
        return self._display_name

    def get_local_id(self) -> str:
        return self._local_id

    def _is_token_expired(self) -> bool:
        import base64
        if not self._id_token:
            return True
        try:
            parts = self._id_token.split(".")
            if len(parts) != 3:
                return True
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
            exp = payload.get("exp", 0)
            import time
            return time.time() > exp - 60
        except Exception:
            return True

    def _try_refresh(self) -> bool:
        if not self._refresh_token:
            return False
        try:
            resp = requests.post(
                f"{FIREBASE_TOKEN_BASE}/token?key={API_KEY}",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                timeout=15,
            )
            data = resp.json()
            if "id_token" in data:
                self._id_token = data["id_token"]
                self._refresh_token = data.get("refresh_token", self._refresh_token)
                self._save_to_file()
                return True
            return False
        except requests.RequestException:
            return False

    def _get_user_info(self) -> Optional[dict]:
        try:
            resp = requests.post(
                f"{FIREBASE_AUTH_BASE}/accounts:lookup?key={API_KEY}",
                json={"idToken": self._id_token},
                timeout=15,
            )
            data = resp.json()
            users = data.get("users", [])
            return users[0] if users else None
        except Exception:
            return None

_auth_instance: Optional[FirebaseAuth] = None
_auth_lock = threading.Lock()


def get_firebase_auth() -> FirebaseAuth:
    global _auth_instance
    if _auth_instance is None:
        with _auth_lock:
            if _auth_instance is None:
                _auth_instance = FirebaseAuth()
    return _auth_instance
