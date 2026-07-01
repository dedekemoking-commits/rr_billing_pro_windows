import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import threading
import time
import socket
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import openpyxl.utils
from datetime import datetime, timedelta
import os
import shutil
import json
import hashlib
import bcrypt  # ← Password hashing with salt
import jwt  # ← JWT tokens
import sys
import re
import webbrowser
import smtplib
import ssl
import random
from email.message import EmailMessage
from PIL import Image, ImageTk  # ← tambah untuk logo
try:
    import fcntl  # ← FIX: File locking untuk thread-safe config save (Unix/Linux)
except ImportError:
    fcntl = None  # Windows tidak support fcntl

# ─── PASSWORD SECURITY HELPERS ──────────────────────────────────────────────
def hash_password(password: str) -> str:
    """Hash password dengan bcrypt (dengan salt). Format: bcrypt$<hash>"""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode(), salt)
    return "bcrypt$" + hashed.decode('utf-8')

def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against bcrypt hash (backward-compatible dengan SHA256)."""
    try:
        if not isinstance(password_hash, str) or not password_hash:
            return False
        # New bcrypt format
        if password_hash.startswith("bcrypt$"):
            hash_value = password_hash[7:].encode('utf-8')
            return bcrypt.checkpw(password.encode(), hash_value)
        # Legacy SHA256 format
        if re.fullmatch(r"[0-9a-f]{64}", password_hash):
            return hashlib.sha256(password.encode()).hexdigest() == password_hash
        # Legacy plaintext format (auto-upgrade after successful login)
        return password == password_hash
    except Exception as e:
        print(f"Password verification error: {e}")
        return False


WARNET_ADMIN_CODE_SECRET = "RR_WARNET_CFG_LOCK_V1"


def generate_warnet_admin_code(client_ip: str, day: datetime = None) -> str:
    """Generate kode akses pengaturan client berdasarkan IP + tanggal."""
    ip = (client_ip or "").strip()
    if not ip:
        return ""
    day = day or datetime.now()
    date_key = day.strftime("%Y%m%d")
    digest = hashlib.sha256(f"{ip}|{date_key}|{WARNET_ADMIN_CODE_SECRET}".encode("utf-8")).hexdigest().upper()
    return f"{digest[0:4]}-{digest[8:12]}-{digest[20:24]}"


# ─── WARNET SOCKET SERVER FOR CLIENT APPS ──────────────────────────────────────

class TokenManager:
    """JWT token manager untuk warnet client authentication."""
    SECRET_KEY = "rr_billing_warnet_secret_2024"
    ALGORITHM = "HS256"
    TOKEN_EXPIRY_DAYS = 180  # 6 months
    
    @classmethod
    def generate_token(cls, client_id: str) -> str:
        """Generate JWT token dengan 6-month expiry."""
        now = datetime.now()
        exp_time = now + timedelta(days=cls.TOKEN_EXPIRY_DAYS)
        
        payload = {
            "client_id": client_id,
            "iat": int(now.timestamp()),
            "exp": int(exp_time.timestamp())
        }
        return jwt.encode(payload, cls.SECRET_KEY, algorithm=cls.ALGORITHM)
    
    @classmethod
    def verify_token(cls, token: str) -> dict:
        """Verify token dan return payload, raise exception jika invalid."""
        try:
            payload = jwt.decode(token, cls.SECRET_KEY, algorithms=[cls.ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError as e:
            raise Exception(f"Token expired: {e}")
        except jwt.InvalidSignatureError as e:
            raise Exception(f"Invalid signature: {e}")
        except jwt.DecodeError as e:
            raise Exception(f"Decode error: {e}")
        except jwt.InvalidTokenError as e:
            raise Exception(f"Invalid token: {e}")
        except ValueError as e:
            # jwt.decode can raise ValueError for malformed tokens
            raise Exception(f"Malformed token: {e}")
        except Exception as e:
            raise Exception(f"Token verification error ({type(e).__name__}): {e}")
    
    @classmethod
    def is_token_valid(cls, token: str) -> bool:
        """Quick check if token is valid."""
        try:
            cls.verify_token(token)
            return True
        except:
            return False


class WarnetSocketServer:
    """Socket server untuk warnet client app connections."""
    
    def __init__(self, config_manager=None, listen_port=5000, app=None):
        self.config_manager = config_manager or ConfigManager
        self.listen_port = listen_port
        self.listen_address = "0.0.0.0"
        self.server_socket = None
        self.running = False
        self.sessions = {}  # {session_token: {client_id, last_heartbeat, address}}
        self.sessions_lock = threading.Lock()
        self.token_manager = TokenManager()
        self.app = app  # Reference to main app untuk query kursi/PC data
    
    def start(self):
        """Start socket server di background thread."""
        if self.running:
            return
        
        self.running = True
        server_thread = threading.Thread(target=self._accept_connections, daemon=True)
        server_thread.start()
        print(f"[WARNET SERVER] Started on {self.listen_address}:{self.listen_port}")
    
    def stop(self):
        """Stop socket server."""
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
    
    def _accept_connections(self):
        """Accept incoming client connections."""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.listen_address, self.listen_port))
            self.server_socket.listen(20)
            
            while self.running:
                try:
                    self.server_socket.settimeout(1)
                    client_socket, address = self.server_socket.accept()
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_socket, address),
                        daemon=True
                    )
                    client_thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"[WARNET SERVER] Accept error: {e}")
        
        except Exception as e:
            print(f"[WARNET SERVER] Server error: {e}")
        finally:
            self.running = False
    
    def _handle_client(self, client_socket, address):
        """Handle single client connection."""
        session_token = None
        try:
            while self.running:
                client_socket.settimeout(5)
                data = client_socket.recv(4096).decode('utf-8')
                
                if not data:
                    break
                
                message = json.loads(data)
                response = self._process_message(message)
                
                # Track session if AUTH successful
                if message.get("type") == "AUTH" and response.get("status") == "OK":
                    session_token = response.get("session_token")
                    with self.sessions_lock:
                        self.sessions[session_token] = {
                            "client_id": message.get("client_id"),
                            "last_heartbeat": time.time(),
                            "address": address
                        }
                
                # Update heartbeat
                if session_token and message.get("type") in ["COMMAND", "PING"]:
                    with self.sessions_lock:
                        if session_token in self.sessions:
                            self.sessions[session_token]["last_heartbeat"] = time.time()
                
                client_socket.sendall(json.dumps(response).encode('utf-8'))
        
        except socket.timeout:
            pass
        except json.JSONDecodeError:
            try:
                error_response = {"type": "ERROR", "message": "Invalid JSON"}
                client_socket.sendall(json.dumps(error_response).encode('utf-8'))
            except:
                pass
        except Exception as e:
            print(f"[WARNET SERVER] Client error ({address}): {e}")
        finally:
            try:
                client_socket.close()
            except:
                pass
            
            # Remove session on disconnect
            if session_token:
                with self.sessions_lock:
                    self.sessions.pop(session_token, None)
    
    def _process_message(self, message: dict) -> dict:
        """Process incoming message and return response."""
        msg_type = message.get("type")
        
        if msg_type == "AUTH":
            return self._handle_auth(message)
        elif msg_type == "COMMAND":
            return self._handle_command(message)
        elif msg_type == "PING":
            return self._handle_ping(message)
        elif msg_type == "GET_STATUS":
            return self._handle_get_status(message)
        else:
            return {"type": "ERROR", "message": f"Unknown message type: {msg_type}"}
    
    def _handle_auth(self, message: dict) -> dict:
        """Handle AUTH: verify client_id and password, return token."""
        client_id = message.get("client_id")
        password = message.get("password")
        
        cfg = self.config_manager.load()
        warnet_clients = cfg.get("warnet_clients", [])
        
        # Find client
        client_data = None
        for c in warnet_clients:
            if c.get("client_id") == client_id:
                client_data = c
                break
        
        if not client_data:
            return {
                "type": "AUTH_RESPONSE",
                "status": "FAIL",
                "message": f"Client {client_id} not found"
            }
        
        # Verify password
        password_hash = client_data.get("password_hash", "")
        if not verify_password(password, password_hash):
            return {
                "type": "AUTH_RESPONSE",
                "status": "FAIL",
                "message": "Invalid password"
            }
        
        # Generate token
        session_token = self.token_manager.generate_token(client_id)
        
        # Return token + PC list
        return {
            "type": "AUTH_RESPONSE",
            "status": "OK",
            "client_id": client_id,
            "session_token": session_token,
            "pcs": client_data.get("pcs", []),
            "timestamp": int(time.time())
        }
    
    def _handle_command(self, message: dict) -> dict:
        """Handle COMMAND: execute action on PC."""
        session_token = message.get("session_token")
        pc_id = message.get("pc_id")
        action = message.get("action")
        
        # Verify token is present
        if not session_token:
            return {
                "type": "COMMAND_RESPONSE",
                "status": "FAIL",
                "message": "Missing session_token"
            }
        
        # Debug: log token details
        # print(f"[WARNET SERVER] Token received: {session_token[:50]}...")
        
        # Verify token
        try:
            payload = self.token_manager.verify_token(session_token)
            client_id = payload.get("client_id")
        except Exception as e:
            # Debug error
            error_str = f"{type(e).__name__}: {str(e)}"
            print(f"[WARNET SERVER] Token verification failed: {error_str}")
            return {
                "type": "COMMAND_RESPONSE",
                "status": "FAIL",
                "message": f"Token error: {error_str}"
            }
        
        # Get client config
        cfg = self.config_manager.load()
        warnet_clients = cfg.get("warnet_clients", [])
        
        client_data = None
        for c in warnet_clients:
            if c.get("client_id") == client_id:
                client_data = c
                break
        
        if not client_data:
            return {
                "type": "COMMAND_RESPONSE",
                "status": "FAIL",
                "message": f"Client {client_id} not found"
            }
        
        # Verify PC ownership
        pc_data = None
        for pc in client_data.get("pcs", []):
            if pc.get("pc_id") == pc_id:
                pc_data = pc
                break
        
        if not pc_data:
            return {
                "type": "COMMAND_RESPONSE",
                "status": "FAIL",
                "message": f"PC {pc_id} not found for client {client_id}"
            }
        
        # Verify action is allowed
        allowed_actions = client_data.get("allowed_actions", ["ON", "OFF", "VOL+", "VOL-"])
        if action not in allowed_actions:
            return {
                "type": "COMMAND_RESPONSE",
                "status": "FAIL",
                "message": f"Action {action} not allowed"
            }
        
        # Execute command
        success = self._execute_pc_command(pc_data, action)
        
        # Log activity
        self._log_warnet_activity({
            "timestamp": datetime.now().isoformat(),
            "client_id": client_id,
            "pc_id": pc_id,
            "action": action,
            "success": success
        })
        
        return {
            "type": "COMMAND_RESPONSE",
            "status": "OK" if success else "FAIL",
            "message": f"{action} executed on {pc_id}",
            "timestamp": int(time.time())
        }
    
    def _handle_ping(self, message: dict) -> dict:
        """Handle PING: heartbeat."""
        return {
            "type": "PONG",
            "server_timestamp": int(time.time())
        }
    
    def _handle_get_status(self, message: dict) -> dict:
        """Handle GET_STATUS: return real billing status for a PC.
        Request: {"type": "GET_STATUS", "session_token": "...", "pc_id": "PC_1"}
        Response: {"type": "STATUS_RESPONSE", "status": "OK", "billing": {...}}
        """
        session_token = message.get("session_token")
        pc_id = message.get("pc_id")
        
        # Verify token
        try:
            payload = self.token_manager.verify_token(session_token)
            client_id = payload.get("client_id")
        except Exception as e:
            return {
                "type": "STATUS_RESPONSE",
                "status": "FAIL",
                "message": f"Token error: {str(e)}"
            }
        
        # Query real billing data from app state
        billing_status = {
            "pc_id": pc_id,
            "time_left": 0,
            "paket_aktif": "-",
            "total_biaya": 0,
            "is_playing": False,
            "timestamp": int(time.time())
        }
        
        # If app reference exists, query actual kursi data
        if self.app and hasattr(self.app, '_semua_kartu_tv'):
            # Search for kursi that matches pc_id (client_id in config)
            for kursi in self.app._semua_kartu_tv:
                # Try to match by label_tv or other identifier
                if hasattr(kursi, 'label_tv'):
                    # Update with real data from kursi
                    if kursi.paket_aktif:
                        billing_status["paket_aktif"] = kursi.paket_aktif
                    if kursi.sisa_waktu > 0:
                        billing_status["time_left"] = kursi.sisa_waktu
                    if kursi.paket_harga_tetap > 0 or kursi.biaya_pesanan > 0:
                        billing_status["total_biaya"] = kursi.paket_harga_tetap + kursi.biaya_pesanan
                    if kursi.paket_aktif and kursi.sisa_waktu > 0:
                        billing_status["is_playing"] = True
                    break
        
        return {
            "type": "STATUS_RESPONSE",
            "status": "OK",
            "billing": billing_status
        }
    
    def _execute_pc_command(self, pc_data: dict, action: str) -> bool:
        """Execute actual command on PC via ADB. Currently stub."""
        pc_ip = pc_data.get("ip")
        adb_port = pc_data.get("adb_port", 5555)
        
        # TODO: Real ADB integration
        # action mapping:
        # - ON: adb shell input power (turn on)
        # - OFF: adb shell input power (turn off)
        # - VOL+: adb shell input keyevent 24
        # - VOL-: adb shell input keyevent 25
        
        print(f"[WARNET SERVER] Would execute {action} on {pc_ip}:{adb_port}")
        return True  # Stub: always succeed for now
    
    def _log_warnet_activity(self, activity: dict):
        """Log warnet activity to config file."""
        try:
            cfg = self.config_manager.load()
            if "warnet_activity_log" not in cfg:
                cfg["warnet_activity_log"] = []
            
            cfg["warnet_activity_log"].append(activity)
            
            # Keep only last 1000 activities
            if len(cfg["warnet_activity_log"]) > 1000:
                cfg["warnet_activity_log"] = cfg["warnet_activity_log"][-1000:]
            
            self.config_manager.save(cfg)
        except Exception as e:
            print(f"[WARNET SERVER] Logging error: {e}")


def is_valid_username(username: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9_.]{4,20}", username))


def is_valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email))


def is_valid_phone(phone: str) -> bool:
    return bool(re.fullmatch(r"\+?[0-9]{7,15}", phone))


def is_valid_password(password: str) -> bool:
    return len(password) >= 8 and bool(re.search(r"[A-Za-z]", password)) and bool(re.search(r"[0-9]", password))

EMAIL_VERIFICATION_EXPIRY_MINUTES = 30
EMAIL_VERIFICATION_CODE_LENGTH = 6
EMAIL_VERIFICATION_CHARS = "0123456789"


def generate_verification_code(length: int = EMAIL_VERIFICATION_CODE_LENGTH) -> str:
    return "".join(random.choice(EMAIL_VERIFICATION_CHARS) for _ in range(length))


def sanitize_text(value: str) -> str:
    return value.strip()


def subprocess_no_window_kwargs() -> dict:
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

# ─── TEMA ───────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ─── PALET WARNA GAMING ──────────────────────────────────────────────────────
C_BG        = "#0A0A18"  # Very dark glass background
C_PANEL     = "#151530"  # Frosted glass panel
C_CARD      = "#1E1E3E"  # Glass card
C_ACCENT    = "#00FFCC"  # Neon cyan glass highlight
C_ACCENT2   = "#6C63FF"  # Soft purple accent
C_RED       = "#FF5252"
C_GREEN     = "#00E676"
C_YELLOW    = "#FFD740"
C_TEXT      = "#E8E8FF"
C_MUTED     = "#8888BB"
C_BTN       = "#181838"
C_BORDER    = "#3A3A6A"
C_ORANGE    = "#FF8C00"

FONT_TITLE  = ("Russo One",  18, "bold")
FONT_SUB    = ("Russo One",  12, "bold")
FONT_BODY   = ("Courier New", 12)
FONT_SMALL  = ("Courier New", 10)
FONT_LABEL  = ("Consolas",  11)

# ─── FILE KONFIGURASI ─────────────────────────────────────────────────────────
def get_app_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_BASE_DIR = get_app_base_dir()


def app_path(filename: str) -> str:
    return os.path.join(APP_BASE_DIR, filename)


CONFIG_FILE  = app_path("rr_billing_config.json")
LICENSE_FILE = app_path("rr_billing_license.json")

# ─── DATA HARGA (default) ─────────────────────────────────────────────────────
# Harga dikelompokkan per "Grup Tarif" (mis. PS3, PS4, Room VIP),
# karena tiap jenis device bisa punya harga sewa berbeda.
# Tiap grup punya paket sendiri {nama: {"harga":int, "menit":int}},
# dan "Main Bebas" di dalam grup itu otomatis dihitung dari paket acuan grup itu.
NAMA_GRUP_DEFAULT = "Reguler"

_PAKET_STANDAR = {
    "30 Menit":   {"harga": 5_000,  "menit": 30},
    "1 Jam":      {"harga": 10_000, "menit": 60},
    "2 Jam":      {"harga": 18_000, "menit": 120},
    "3 Jam":      {"harga": 25_000, "menit": 180},
    "5 Jam":      {"harga": 35_000, "menit": 300},
    "Overnight":  {"harga": 50_000, "menit": 540},
    "Main Bebas": {"harga": 0,      "menit": 0},
}

# Grup tarif bawaan saat aplikasi pertama kali dijalankan (belum ada config tersimpan).
# User bisa menambah/mengubah/menghapus grup ini secara bebas lewat tab Kontrol Harga.
DEFAULT_GRUP_TARIF = {
    "Reguler":   {k: dict(v) for k, v in _PAKET_STANDAR.items()},
    "PS3":       {k: dict(v) for k, v in _PAKET_STANDAR.items()},
    "PS4":       {k: dict(v) for k, v in _PAKET_STANDAR.items()},
    "Room VIP":  {k: dict(v) for k, v in _PAKET_STANDAR.items()},
}

# Grup yang tidak boleh dihapus user (minimal harus ada 1 grup default fallback).
GRUP_TERKUNCI = {"Reguler"}

# Nama paket acuan tarif per-menit untuk Main Bebas di tiap grup.
# Tarif/menit Main Bebas = harga paket ini ÷ menit paket ini (di dalam grup yang sama).
PAKET_ACUAN_BEBAS = "1 Jam"

DEFAULT_MENU_MAKANAN = {
    "Indomie Goreng":    8_000,
    "Indomie Kuah":      8_000,
    "Kentang Goreng":   12_000,
    "Burger":           20_000,
    "Roti Bakar":       10_000,
    "Nasi Goreng":      15_000,
    "Sosis Bakar":       7_000,
}

DEFAULT_MENU_MINUMAN = {
    "Air Mineral":        3_000,
    "Es Teh Manis":       5_000,
    "Es Jeruk":           6_000,
    "Kopi Hitam":         6_000,
    "Susu Coklat":        8_000,
    "Jus Mangga":        10_000,
    "Soda Gembira":      10_000,
    "Pocari Sweat":       8_000,
}

def fmt_rp(n):
    return f"Rp {n:,.0f}".replace(",", ".")


def fmt_durasi(menit):
    """Format menit jadi teks 'X jam Y menit' yang enak dibaca."""
    if menit <= 0:
        return "Bebas"
    jam, sisa = divmod(menit, 60)
    if jam and sisa:
        return f"{jam} jam {sisa} menit"
    if jam:
        return f"{jam} jam"
    return f"{sisa} menit"

DEFAULT_PORT = 5555
APP_VERSION = "2.3.1"


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPER LOGO
# ═══════════════════════════════════════════════════════════════════════════════
def _get_logo_path():
    """Cari logo.png di folder aplikasi; fallback ke folder bundle PyInstaller."""
    app_logo = app_path("logo.png")
    if os.path.exists(app_logo):
        return app_logo
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        bundled_logo = os.path.join(meipass, "logo.png")
        if os.path.exists(bundled_logo):
            return bundled_logo
    return app_logo


def load_ctk_image(size=(54, 54)):
    """
    Muat logo.png sebagai CTkImage untuk dipakai di CTkLabel.
    Kembalikan CTkImage jika berhasil, None jika gagal.
    """
    path = _get_logo_path()
    if not os.path.exists(path):
        return None
    try:
        img = Image.open(path).convert("RGBA").resize(size, Image.LANCZOS)
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)
    except Exception as e:
        print(f"[logo] Gagal muat CTkImage: {e}")
        return None


def set_window_icon(window):
    """
    Set logo.png sebagai ikon window (titlebar & taskbar).
    Bekerja di Windows dan Linux/macOS.
    """
    path = _get_logo_path()
    if not os.path.exists(path):
        return
    try:
        img = Image.open(path)
        # Buat beberapa ukuran supaya taskbar & titlebar sama-sama bagus
        sizes = [(16,16),(32,32),(48,48),(64,64),(128,128)]
        icons = []
        for s in sizes:
            resized = img.resize(s, Image.LANCZOS)
            icons.append(ImageTk.PhotoImage(resized))
        # Simpan referensi agar tidak di-garbage-collect
        window._icon_images = icons
        window.iconphoto(True, *icons[::-1])  # urutan besar → kecil
    except Exception as e:
        print(f"[logo] Gagal set window icon: {e}")


def center_window(win, master=None, width=None, height=None):
    """Center a toplevel window relative to master or screen."""
    win.update_idletasks()
    geom = win.geometry().split("+")[0]
    if width is None or height is None:
        parts = geom.split("x")
        if len(parts) == 2:
            width, height = int(parts[0]), int(parts[1])
    if master is not None:
        try:
            master.update_idletasks()
            mx = master.winfo_x()
            my = master.winfo_y()
            mw = master.winfo_width()
            mh = master.winfo_height()
            x = mx + max((mw - width) // 2, 0)
            y = my + max((mh - height) // 2, 0)
        except Exception:
            x = max((win.winfo_screenwidth() - width) // 2, 0)
            y = max((win.winfo_screenheight() - height) // 2, 0)
    else:
        x = max((win.winfo_screenwidth() - width) // 2, 0)
        y = max((win.winfo_screenheight() - height) // 2, 0)
    win.geometry(f"{width}x{height}+{x}+{y}")


# ═══════════════════════════════════════════════════════════════════════════════
#  KONFIGURASI MANAGER
# ═══════════════════════════════════════════════════════════════════════════════
class ConfigManager:
    """Simpan & load data harga, user, dan lisensi dengan file locking untuk thread-safety."""
    @staticmethod
    def load():
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    @staticmethod
    def save(data):
        """Simpan config dengan file locking untuk prevent race condition."""
        lock_file = CONFIG_FILE + ".lock"
        max_retry = 10
        retry_delay = 0.05
        
        for attempt in range(max_retry):
            try:
                # Buat lock file jika belum ada
                with open(lock_file, 'a') as lock:
                    if os.name == 'nt':  # Windows
                        # Windows: gunakan win32 file locking
                        import msvcrt
                        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                        try:
                            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                                json.dump(data, f, indent=2, ensure_ascii=False)
                        finally:
                            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:  # Unix/Linux/Mac
                        if fcntl is not None:
                            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                            try:
                                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                                    json.dump(data, f, indent=2, ensure_ascii=False)
                            finally:
                                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                        else:
                            # fcntl not available, write without lock
                            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                                json.dump(data, f, indent=2, ensure_ascii=False)
                return  # Success
            except (IOError, OSError) as e:
                if attempt < max_retry - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"Config save error after {max_retry} retries: {e}")
                    raise

    @staticmethod
    def get(key, default=None):
        d = ConfigManager.load()
        return d.get(key, default)

    @staticmethod
    def set(key, value):
        d = ConfigManager.load()
        d[key] = value
        ConfigManager.save(d)


def _get_email_settings():
    cfg = ConfigManager.load()
    return cfg.get("email_settings", {})


def _email_configured() -> bool:
    settings = _get_email_settings()
    required = ["smtp_server", "smtp_port", "smtp_username", "smtp_password", "from_address"]
    return all(settings.get(k) for k in required)


def _send_verification_email(to_email: str, username: str, code: str) -> tuple:
    settings = _get_email_settings()
    if not _email_configured():
        return False, "Email belum dikonfigurasi."

    msg = EmailMessage()
    msg["Subject"] = "RR Billing Pro - Email Verification Code"
    msg["From"] = settings.get("from_address")
    msg["To"] = to_email
    msg.set_content(
        f"Halo {username},\n\n"
        f"Kode verifikasi email Anda: {code}\n\n"
        f"Masukkan kode ini di aplikasi untuk menyelesaikan pendaftaran.\n"
        f"Kode berlaku selama {EMAIL_VERIFICATION_EXPIRY_MINUTES} menit.\n\n"
        "Terima kasih."
    )

    try:
        server = settings.get("smtp_server")
        port = int(settings.get("smtp_port", 587))
        username_smtp = settings.get("smtp_username")
        password_smtp = settings.get("smtp_password")
        use_tls = bool(settings.get("use_tls", True))

        if use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(server, port, timeout=10) as smtp:
                smtp.starttls(context=context)
                smtp.login(username_smtp, password_smtp)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(server, port, timeout=10) as smtp:
                smtp.login(username_smtp, password_smtp)
                smtp.send_message(msg)
        return True, "Email verifikasi telah dikirim."
    except Exception as e:
        return False, str(e)


# ─── AUDIT LOGGER ───────────────────────────────────────────────────────────
AUDIT_FILE = app_path("rr_billing_audit.jsonl")

class AuditLogger:
    @staticmethod
    def _append_line(line: str):
        lock_file = AUDIT_FILE + ".lock"
        max_retry = 10
        retry_delay = 0.05

        for attempt in range(max_retry):
            try:
                with open(lock_file, 'a') as lock:
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                        try:
                            with open(AUDIT_FILE, 'a', encoding='utf-8') as f:
                                f.write(line + '\n')
                        finally:
                            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        if fcntl is not None:
                            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                            try:
                                with open(AUDIT_FILE, 'a', encoding='utf-8') as f:
                                    f.write(line + '\n')
                            finally:
                                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                        else:
                            with open(AUDIT_FILE, 'a', encoding='utf-8') as f:
                                f.write(line + '\n')
                return
            except (IOError, OSError):
                if attempt < max_retry - 1:
                    time.sleep(retry_delay)
                    continue
                raise

    @staticmethod
    def log(action: str, username: str = "", status: str = "", details: dict = None):
        payload = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "username": username,
            "status": status,
            "details": details or {},
        }
        try:
            AuditLogger._append_line(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            print(f"Audit log error: {e}")


# Modul lisensi terpisah (rr_license.py). Kalau ada rr_keygen.py (binding per-
# username) ia akan dipakai otomatis oleh LicenseManager.aktivasi(); kalau
# tidak ada, LicenseManager sudah punya fallback aman di dalamnya sendiri.
from rr_license import LicenseManager, LicenseGenerator, get_machine_id


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPER ADB
# ═══════════════════════════════════════════════════════════════════════════════
class ADBHelper:
    ADB_PATH = shutil.which("adb") or "adb"

    @classmethod
    def adb_tersedia(cls):
        return shutil.which(cls.ADB_PATH) is not None or shutil.which("adb") is not None

    @classmethod
    def _run(cls, args, timeout=8):
        try:
            result = subprocess.run(
                [cls.ADB_PATH] + args,
                capture_output=True, text=True, timeout=timeout,
                **subprocess_no_window_kwargs()
            )
            ok = result.returncode == 0
            return ok, result.stdout.strip(), result.stderr.strip()
        except FileNotFoundError:
            return False, "", "adb tidak ditemukan."
        except subprocess.TimeoutExpired:
            return False, "", "Timeout."
        except Exception as e:
            return False, "", str(e)

    @classmethod
    def pair(cls, ip, pair_port, kode_pairing, timeout=15):
        target = f"{ip}:{pair_port}"
        try:
            result = subprocess.run(
                [cls.ADB_PATH, "pair", target],
                input=f"{kode_pairing}\n",
                capture_output=True, text=True, timeout=timeout,
                **subprocess_no_window_kwargs()
            )
            out  = result.stdout.strip()
            err  = result.stderr.strip()
            teks = (out + " " + err).lower()
            if "successfully paired" in teks or "paired to" in teks:
                return True, out or f"Berhasil paired ke {target}"
            if "failed" in teks or "error" in teks:
                return False, out or err or "Pairing gagal"
            if result.returncode == 0:
                return True, out or f"Paired ke {target}"
            return False, out or err or "Pairing gagal"
        except FileNotFoundError:
            return False, "adb tidak ditemukan di PATH."
        except subprocess.TimeoutExpired:
            return False, "Timeout."
        except Exception as e:
            return False, str(e)

    @classmethod
    def pair_dan_connect(cls, ip, pair_port, kode_pairing, timeout=15):
        sukses_pair, pesan_pair = cls.pair(ip, pair_port, kode_pairing, timeout)
        if not sukses_pair:
            return False, None, f"Pairing gagal: {pesan_pair}"
        kandidat_port = list(dict.fromkeys([5555, pair_port]))
        for port in kandidat_port:
            ok, pesan = cls.connect(ip, port)
            if ok:
                status, _ = cls.status_untuk_ip(ip, port)
                if status == "device":
                    return True, port, f"Paired & terhubung ke {ip}:{port}"
                elif status == "unauthorized":
                    return False, None, "Pair berhasil, tapi TV meminta otorisasi."
        return False, None, "Pair berhasil, tapi auto-connect gagal. Masukkan port manual."

    @classmethod
    def connect(cls, ip, port=DEFAULT_PORT):
        target = f"{ip}:{port}"
        ok, out, err = cls._run(["connect", target], timeout=8)
        teks = (out + " " + err).lower()
        if "connected to" in teks or "already connected" in teks:
            return True, out or f"connected to {target}"
        return False, out or err or "Gagal terhubung"

    @classmethod
    def disconnect(cls, ip, port=DEFAULT_PORT):
        target = f"{ip}:{port}"
        ok, out, err = cls._run(["disconnect", target], timeout=5)
        return ok, out or err

    @classmethod
    def list_devices(cls):
        ok, out, err = cls._run(["devices", "-l"], timeout=6)
        devices = {}
        if not ok:
            return devices, err
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                devices[parts[0]] = parts[1]
        return devices, ""

    @classmethod
    def status_untuk_ip(cls, ip, port=DEFAULT_PORT):
        target = f"{ip}:{port}"
        devices, err = cls.list_devices()
        if target in devices:
            return devices[target], err
        return "not_found", err

    @classmethod
    def shell(cls, ip, command_args, port=DEFAULT_PORT, timeout=6):
        target = f"{ip}:{port}"
        ok, out, err = cls._run(["-s", target, "shell"] + command_args, timeout=timeout)
        return ok, out, err

    @classmethod
    def power_toggle(cls, ip, port=DEFAULT_PORT):
        return cls.shell(ip, ["input", "keyevent", "26"], port=port)

    @classmethod
    def volume(cls, ip, naik=True, port=DEFAULT_PORT):
        return cls.shell(ip, ["input", "keyevent", "24" if naik else "25"], port=port)

    @classmethod
    def home(cls, ip, port=DEFAULT_PORT):
        return cls.shell(ip, ["input", "keyevent", "3"], port=port)

    @classmethod
    def cek_dan_reconnect(cls, ip, port=DEFAULT_PORT):
        if not cls.adb_tersedia():
            return False, "no_adb", "Binary 'adb' tidak ditemukan."
        status_awal, err = cls.status_untuk_ip(ip, port)
        if status_awal == "device":
            return True, status_awal, f"Sudah terhubung ({ip}:{port})."
        ok_connect, msg_connect = cls.connect(ip, port)
        status_akhir, _ = cls.status_untuk_ip(ip, port)
        if status_akhir == "device":
            return True, status_awal, f"Reconnect berhasil."
        elif status_akhir == "unauthorized":
            return False, status_awal, "Perlu otorisasi di TV."
        return False, status_awal, msg_connect or "Reconnect gagal."


class SocketHelper:
    @staticmethod
    def send(host, port, message, timeout=15):
        if not host or not port or not message:
            return False, "Socket host, port, dan perintah harus diisi."

        try:
            port = int(port)
        except Exception:
            return False, "Port socket tidak valid."

        try:
            with socket.create_connection((host, port), timeout=timeout) as sock:
                sock.settimeout(timeout)
                payload = message.strip()
                if not payload.endswith("\n"):
                    payload += "\n"
                sock.sendall(payload.encode("utf-8"))

                response_chunks = []
                while True:
                    try:
                        chunk = sock.recv(4096)
                    except socket.timeout:
                        break
                    if not chunk:
                        break
                    response_chunks.append(chunk)

                response = b"".join(response_chunks).decode("utf-8", errors="ignore").strip()
                return True, response or "Perintah socket berhasil dikirim."
        except socket.timeout:
            return False, "Socket connection timeout."
        except ConnectionRefusedError:
            return False, "Koneksi socket ditolak oleh host."
        except Exception as e:
            return False, str(e)


class DialogSocketConfig(ctk.CTkToplevel):
    def __init__(self, master, config=None, on_save=None, on_test=None):
        super().__init__(master)
        self.title("Konfigurasi Koneksi Client")
        self.geometry("620x380")
        self.configure(fg_color=C_BG)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.on_save = on_save
        self.on_test = on_test

        cfg = config or {}
        host = cfg.get("host", "")
        port = cfg.get("port", DEFAULT_PORT)
        self.start_cmd = cfg.get("on_start_command", "START {kursi}")
        self.finish_cmd = cfg.get("on_finish_command", "STOP {kursi}")

        ctk.CTkLabel(
            self,
            text="Konfigurasi Koneksi PC Client",
            font=FONT_TITLE,
            text_color=C_ACCENT,
        ).pack(pady=(18, 6))
        ctk.CTkLabel(
            self,
            text="Isi alamat server billing yang akan dipakai aplikasi client warnet.",
            font=FONT_BODY,
            text_color=C_MUTED,
        ).pack(pady=(0, 10))

        body = ctk.CTkFrame(
            self,
            fg_color=C_CARD,
            corner_radius=12,
            border_width=1,
            border_color=C_ACCENT2,
        )
        body.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0)

        self.host_var = tk.StringVar(value=host)
        self.port_var = tk.StringVar(value=str(port))

        ctk.CTkLabel(
            body,
            text="Host / IP Server",
            font=FONT_LABEL,
            text_color=C_MUTED,
        ).grid(row=0, column=0, padx=(18, 10), pady=(18, 6), sticky="w")
        ctk.CTkLabel(
            body,
            text="Port",
            font=FONT_LABEL,
            text_color=C_MUTED,
        ).grid(row=0, column=1, padx=(0, 18), pady=(18, 6), sticky="w")

        entry_host = ctk.CTkEntry(
            body,
            textvariable=self.host_var,
            fg_color=C_BTN,
            text_color=C_TEXT,
            border_color=C_ACCENT,
            font=("Consolas", 13, "bold"),
            height=38,
        )
        entry_host.grid(row=1, column=0, padx=(18, 10), pady=(0, 8), sticky="ew")

        entry_port = ctk.CTkEntry(
            body,
            textvariable=self.port_var,
            fg_color=C_BTN,
            text_color=C_TEXT,
            border_color=C_ACCENT,
            font=("Consolas", 13, "bold"),
            width=120,
            height=38,
        )
        entry_port.grid(row=1, column=1, padx=(0, 18), pady=(0, 8), sticky="ew")

        info_box = ctk.CTkFrame(body, fg_color=C_PANEL, corner_radius=10)
        info_box.grid(row=2, column=0, columnspan=2, padx=18, pady=(4, 10), sticky="ew")
        ctk.CTkLabel(
            info_box,
            text="Panduan cepat:",
            font=FONT_SUB,
            text_color=C_ACCENT,
        ).pack(anchor="w", padx=12, pady=(10, 4))
        self.info_label = ctk.CTkLabel(
            info_box,
            text=(
                "• Host/IP diisi alamat laptop/PC server billing.\n"
                "• Port harus sama dengan port server socket warnet.\n"
                "• Klik Tes Koneksi dulu, lalu Simpan jika sudah benar."
            ),
            font=FONT_SMALL,
            text_color=C_TEXT,
            justify="left",
        )
        self.info_label.pack(anchor="w", padx=12, pady=(0, 10))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(
            btn_frame,
            text="🔍 Tes Koneksi",
            width=150,
            height=38,
            fg_color=C_ACCENT2,
            hover_color="#5A0FCC",
            font=FONT_SUB,
            command=self._test_connection,
        ).pack(side="left")
        ctk.CTkButton(
            btn_frame,
            text="✖ Batal",
            width=120,
            height=38,
            fg_color=C_RED,
            hover_color="#7A1A1A",
            font=FONT_SUB,
            command=self.destroy,
        ).pack(side="right")
        ctk.CTkButton(
            btn_frame,
            text="✅ Simpan Config",
            width=170,
            height=38,
            fg_color=C_GREEN,
            hover_color="#2F7A2F",
            font=FONT_SUB,
            command=self._save,
        ).pack(side="right", padx=(0, 8))

        entry_host.focus_set()

    def _test_connection(self):
        if callable(self.on_test):
            self.on_test(self._collect_config())

    def _collect_config(self):
        try:
            port_value = int(self.port_var.get().strip() or DEFAULT_PORT)
        except ValueError:
            port_value = DEFAULT_PORT
        return {
            "host": self.host_var.get().strip(),
            "port": port_value,
            "on_start_command": self.start_cmd,
            "on_finish_command": self.finish_cmd,
        }

    def _save(self):
        cfg = self._collect_config()
        if not cfg["host"]:
            messagebox.showwarning("Lengkapi Konfigurasi", "Host/IP wajib diisi terlebih dahulu.", parent=self)
            return
        if callable(self.on_save):
            self.on_save(cfg)
        self.destroy()


class DialogWarnetAdminCode(ctk.CTkToplevel):
    """Dialog kecil untuk generate kode admin pengaturan client dari IP."""

    def __init__(self, master):
        super().__init__(master)
        self.title("Generator Kode Pengaturan Client")
        self.geometry("470x260")
        self.configure(fg_color=C_BG)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        ctk.CTkLabel(
            self,
            text="🔐 Generator Kode Pengaturan Client",
            font=FONT_TITLE,
            text_color=C_ACCENT,
        ).pack(pady=(14, 8))

        ctk.CTkLabel(
            self,
            text="Masukkan IP PC client, lalu generate kode untuk buka tombol ⚙ di app client.",
            font=FONT_SMALL,
            text_color=C_MUTED,
        ).pack(pady=(0, 10))

        form = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=10)
        form.pack(fill="x", padx=16, pady=6)
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="IP Client", font=FONT_LABEL, text_color=C_MUTED).grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.ip_var = tk.StringVar()
        self.entry_ip = ctk.CTkEntry(form, textvariable=self.ip_var)
        self.entry_ip.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        ctk.CTkLabel(form, text="Kode Hari Ini", font=FONT_LABEL, text_color=C_MUTED).grid(row=1, column=0, padx=10, pady=(0, 10), sticky="w")
        self.code_var = tk.StringVar(value="-")
        self.entry_code = ctk.CTkEntry(form, textvariable=self.code_var, state="readonly")
        self.entry_code.grid(row=1, column=1, padx=10, pady=(0, 10), sticky="ew")

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(8, 6))
        ctk.CTkButton(btns, text="Generate", fg_color=C_ACCENT2, hover_color="#5A0FCC", command=self._generate).pack(side="left")
        ctk.CTkButton(btns, text="Copy Kode", fg_color=C_GREEN, hover_color="#2F7A2F", command=self._copy_code).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="Tutup", fg_color=C_RED, hover_color="#7A1A1A", command=self.destroy).pack(side="right")

        self.info = ctk.CTkLabel(self, text="", font=FONT_SMALL, text_color=C_MUTED)
        self.info.pack(fill="x", padx=16, pady=(0, 8))
        self.entry_ip.focus_set()

    def _generate(self):
        ip = self.ip_var.get().strip()
        if not ip:
            messagebox.showwarning("IP Belum Diisi", "Masukkan IP client terlebih dahulu.", parent=self)
            return
        code = generate_warnet_admin_code(ip)
        if not code:
            messagebox.showwarning("Gagal Generate", "Kode gagal dibuat. Periksa IP.", parent=self)
            return
        self.code_var.set(code)
        self.info.configure(text=f"IP: {ip} | Tanggal: {datetime.now().strftime('%d-%m-%Y')}")

    def _copy_code(self):
        code = self.code_var.get().strip()
        if not code or code == "-":
            messagebox.showwarning("Belum Ada Kode", "Generate kode terlebih dahulu.", parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(code)
        self.update()
        messagebox.showinfo("Berhasil", "Kode berhasil disalin ke clipboard.", parent=self)


# ═══════════════════════════════════════════════════════════════════════════════
#  LOGIN PAGE
# ═══════════════════════════════════════════════════════════════════════════════
class LoginPage(ctk.CTkFrame):
    # Default passwords (hashed dengan bcrypt untuk keamanan)
    # Jika tidak ada users di config.json, gunakan ini sebagai fallback
    DEFAULT_USERS = {
        # Tidak ada default user - user harus register atau admin setup
    }

    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_LOCK_DURATION = timedelta(minutes=1)

    def __init__(self, master, on_login_success):
        super().__init__(master, fg_color=C_BG, corner_radius=0)
        self.on_login_success = on_login_success
        self._attempt         = 0
        self._locked_until    = None
        self._lp_username_verified = None  # username yg terverifikasi di lupa password

        # Satu container — isinya diganti saat pindah view
        # Dengan width minimum agar tidak shrink terlalu kecil
        self._view_container = ctk.CTkFrame(self, fg_color="transparent")
        self._view_container.pack(expand=True, fill="both", padx=20, pady=(14, 10), anchor="n")

        self._show_login_view()

    # ══════════════════════════════════════════════════════════════════════════
    #  VIEW 1 — LOGIN
    # ══════════════════════════════════════════════════════════════════════════
    def _show_login_view(self):
        for w in self._view_container.winfo_children():
            w.destroy()

        scroll = ctk.CTkScrollableFrame(self._view_container, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        outer = ctk.CTkFrame(scroll, fg_color=C_PANEL,
                              corner_radius=20, border_width=2,
                              border_color=C_ACCENT2)
        outer.pack(anchor="n", pady=(10, 10), padx=4, fill="x")

        # Logo
        logo_ico = ctk.CTkFrame(outer, fg_color=C_CARD, corner_radius=12,
                                  width=152, height=62)
        logo_ico.pack(pady=(28, 8))
        logo_ico.pack_propagate(False)
        ctk_img = load_ctk_image(size=(143, 55))
        if ctk_img:
            ctk.CTkLabel(logo_ico, text="", image=ctk_img).place(
                relx=0.5, rely=0.5, anchor="center")
        else:
            ctk.CTkLabel(logo_ico, text="🎮", font=("Arial", 32)).place(
                relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(outer, text="RR BILLING PRO",
                     font=("Russo One", 22, "bold"),
                     text_color=C_ACCENT).pack(pady=(4, 0))
        ctk.CTkLabel(outer, text="Sistem Billing Rental TV & PS",
                     font=("Courier New", 11), text_color=C_MUTED).pack(pady=(0, 16))

        self.lbl_lic = ctk.CTkLabel(outer, text="Silakan login untuk melanjutkan.",
                                     font=("Courier New", 10), text_color=C_MUTED)
        self.lbl_lic.pack(pady=(0, 10))

        ctk.CTkFrame(outer, height=1, fg_color=C_BORDER).pack(
            fill="x", padx=30, pady=(0, 18))

        # Input username
        ctk.CTkLabel(outer, text="Username", font=("Consolas", 11),
                     text_color=C_MUTED).pack(padx=40)
        self.entry_user = ctk.CTkEntry(
            outer, placeholder_text="Masukkan username",
            fg_color=C_BTN, text_color=C_ACCENT,
            border_color=C_BORDER, font=("Consolas", 14),
            height=40, width=320, justify="center")
        self.entry_user.pack(pady=(2, 10), padx=40)

        # Input password
        ctk.CTkLabel(outer, text="Password", font=("Consolas", 11),
                     text_color=C_MUTED).pack(padx=40)
        self.entry_pass = ctk.CTkEntry(
            outer, placeholder_text="Masukkan password",
            fg_color=C_BTN, text_color=C_ACCENT,
            border_color=C_BORDER, font=("Consolas", 14),
            height=40, width=320, show="●", justify="center")
        self.entry_pass.pack(pady=(2, 6), padx=40)
        self.entry_pass.bind("<Return>", lambda e: self._login())

        # Status error
        self.lbl_status = ctk.CTkLabel(outer, text="",
                                        font=("Consolas", 11), text_color=C_RED)
        self.lbl_status.pack(pady=(0, 8))

        # Tombol Masuk
        self.btn_login = ctk.CTkButton(
            outer, text="🔓  MASUK", width=280, height=44,
            fg_color=C_ACCENT2, hover_color=C_ACCENT,
            font=("Russo One", 13, "bold"), text_color="white",
            command=self._login)
        self.btn_login.pack(pady=(0, 4), padx=30)

        ctk.CTkLabel(outer,
                     text="Hubungi administrator untuk akses.",
                     font=("Courier New", 10), text_color=C_MUTED).pack(pady=(0, 4))

        # Tombol Daftar
        ctk.CTkLabel(outer, text="Rental baru? Belum punya akun?",
                     font=("Courier New", 10), text_color=C_MUTED).pack(pady=(8, 4))
        ctk.CTkButton(
            outer, text="📝  DAFTAR RENTAL BARU", width=280, height=36,
            fg_color="transparent", hover_color=C_BTN,
            border_width=1, border_color=C_ACCENT,
            font=("Russo One", 11, "bold"), text_color=C_ACCENT,
            command=self._show_daftar_view).pack(pady=(0, 6), padx=30)

        # Tombol Lupa Password
        ctk.CTkButton(
            outer, text="🔓  Lupa Password?", width=280, height=34,
            fg_color="transparent", hover_color=C_BTN,
            border_width=1, border_color=C_RED,
            font=("Russo One", 10, "bold"), text_color=C_RED,
            command=self._show_lupa_password_view).pack(pady=(0, 10), padx=30)

        # Version di login page
        ctk.CTkLabel(outer, text=f"v{APP_VERSION}",
                     font=("Courier New", 10), text_color=C_MUTED).pack(pady=(0, 6))

    # ══════════════════════════════════════════════════════════════════════════
    #  VIEW 2 — DAFTAR RENTAL BARU
    # ══════════════════════════════════════════════════════════════════════════
    def _show_daftar_view(self):
        for w in self._view_container.winfo_children():
            w.destroy()

        outer = ctk.CTkFrame(self._view_container, fg_color=C_PANEL,
                              corner_radius=20, border_width=2,
                              border_color=C_ACCENT2)
        outer.pack()

        hdr = ctk.CTkFrame(outer, fg_color=C_ACCENT2, corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="📝  DAFTAR RENTAL BARU",
                     font=("Russo One", 14, "bold"),
                     text_color="white").pack(pady=14)

        ctk.CTkLabel(outer,
                     text="Buat akun admin untuk rental Anda — trial otomatis aktif",
                     font=FONT_SMALL, text_color=C_MUTED).pack(pady=(10, 4))
        ctk.CTkLabel(outer,
                     text="Email wajib valid karena kami akan mengirim kode verifikasi.",
                     font=FONT_SMALL, text_color=C_MUTED).pack(pady=(0, 8))

        scroll = ctk.CTkScrollableFrame(outer, fg_color="transparent",
                                         width=440, height=460)
        scroll.pack(padx=20, pady=4)

        # Akun login
        akun_f = ctk.CTkFrame(scroll, fg_color=C_CARD, corner_radius=10)
        akun_f.pack(fill="x", pady=6)
        ctk.CTkLabel(akun_f, text="🔐  AKUN LOGIN", font=FONT_SUB,
                     text_color=C_ACCENT2).pack(anchor="w", padx=14, pady=(10, 6))
        self.d_username  = self._input_field(akun_f, "Username", "mis. rentalku01")
        self.d_password  = self._input_field(akun_f, "Password", "minimal 6 karakter", show="●")
        self.d_password2 = self._input_field(akun_f, "Konfirmasi Password", "ulangi password", show="●")

        # Profil rental
        profil_f = ctk.CTkFrame(scroll, fg_color=C_CARD, corner_radius=10)
        profil_f.pack(fill="x", pady=6)
        ctk.CTkLabel(profil_f, text="🏢  PROFIL RENTAL", font=FONT_SUB,
                     text_color=C_ACCENT2).pack(anchor="w", padx=14, pady=(10, 6))
        self.d_nama_pemilik = self._input_field(profil_f, "Nama Pemilik",  "mis. Budi Santoso")
        self.d_nama_rental  = self._input_field(profil_f, "Nama Rental PS","mis. RR Game Center")
        self.d_email        = self._input_field(profil_f, "Email / Gmail", "mis. nama@gmail.com")
        self.d_hp           = self._input_field(profil_f, "No HP / WhatsApp","mis. 0812xxxxxxx")

        ctk.CTkLabel(profil_f, text="Alamat", font=FONT_LABEL,
                     text_color=C_MUTED, anchor="w").pack(anchor="w", padx=14, pady=(4, 2))
        self.d_alamat = ctk.CTkTextbox(profil_f, height=56,
                                        fg_color=C_BTN, text_color=C_TEXT,
                                        border_color=C_BORDER, border_width=1,
                                        font=FONT_BODY)
        self.d_alamat.pack(fill="x", padx=14, pady=(0, 10))

        # Status & tombol
        self.lbl_daftar_status = ctk.CTkLabel(outer, text="",
                                               font=FONT_LABEL, text_color=C_RED,
                                               wraplength=420, justify="center")
        self.lbl_daftar_status.pack(pady=(6, 2))

        btn_row = ctk.CTkFrame(outer, fg_color="transparent")
        btn_row.pack(pady=(2, 20))
        ctk.CTkButton(btn_row, text="✅  DAFTAR SEKARANG", width=200, height=40,
                      fg_color=C_ACCENT2, hover_color="#5A0FCC",
                      font=("Russo One", 11, "bold"), text_color="white",
                      command=self._submit_daftar).pack(side="left", padx=8)
        ctk.CTkButton(btn_row, text="← KEMBALI LOGIN", width=160, height=40,
                      fg_color="transparent", hover_color=C_BTN,
                      border_width=1, border_color=C_MUTED,
                      font=("Russo One", 10, "bold"), text_color=C_MUTED,
                      command=self._show_login_view).pack(side="left", padx=8)

    def _input_field(self, parent, label, placeholder, show=None):
        ctk.CTkLabel(parent, text=label, font=FONT_LABEL,
                     text_color=C_MUTED, anchor="w").pack(anchor="w", padx=14, pady=(4, 2))
        kw = {"show": show} if show else {}
        e = ctk.CTkEntry(parent, placeholder_text=placeholder,
                          fg_color=C_BTN, text_color=C_TEXT,
                          border_color=C_BORDER, font=FONT_BODY, height=34, **kw)
        e.pack(fill="x", padx=14, pady=(0, 6))
        return e

    def _submit_daftar(self):
        username     = sanitize_text(self.d_username.get()).lower()
        password     = self.d_password.get().strip()
        password2    = self.d_password2.get().strip()
        nama_pemilik = sanitize_text(self.d_nama_pemilik.get())
        nama_rental  = sanitize_text(self.d_nama_rental.get())
        email        = sanitize_text(self.d_email.get()).lower()
        no_hp        = sanitize_text(self.d_hp.get())
        alamat       = sanitize_text(self.d_alamat.get("1.0", "end"))

        if not all([username, password, password2, nama_pemilik,
                    nama_rental, email, no_hp, alamat]):
            self.lbl_daftar_status.configure(
                text="⚠  Semua field wajib diisi.", text_color=C_YELLOW)
            return
        if not is_valid_username(username):
            self.lbl_daftar_status.configure(
                text="⚠  Username harus 4-20 karakter, huruf, angka, titik, atau garis bawah.",
                text_color=C_YELLOW)
            return
        if not is_valid_password(password):
            self.lbl_daftar_status.configure(
                text="⚠  Password harus minimal 8 karakter, dan berisi huruf serta angka.",
                text_color=C_YELLOW)
            return
        if password != password2:
            self.lbl_daftar_status.configure(
                text="⚠  Konfirmasi password tidak cocok.", text_color=C_YELLOW)
            return
        if not is_valid_email(email):
            self.lbl_daftar_status.configure(
                text="⚠  Format email tidak valid.", text_color=C_YELLOW)
            return
        if not is_valid_phone(no_hp):
            self.lbl_daftar_status.configure(
                text="⚠  Nomor HP tidak valid. Gunakan 7-15 digit, boleh diawali +.",
                text_color=C_YELLOW)
            return

        cfg   = ConfigManager.load()
        users = cfg.get("users", dict(LoginPage.DEFAULT_USERS))
        pending = cfg.get("pending_email_verifications", {})

        if username in users:
            self.lbl_daftar_status.configure(
                text=f"✖  Username '{username}' sudah dipakai.", text_color=C_RED)
            return
        if username in pending:
            self.lbl_daftar_status.configure(
                text=f"⚠  Username '{username}' sudah memiliki verifikasi tertunda.",
                text_color=C_YELLOW)
            return

        if not _email_configured():
            self.lbl_daftar_status.configure(
                text="⚠  Email verification belum tersedia karena SMTP belum dikonfigurasi.",
                text_color=C_YELLOW)
            return

        verification_code = generate_verification_code()
        verification_expires = datetime.now() + timedelta(minutes=EMAIL_VERIFICATION_EXPIRY_MINUTES)

        pending[username] = {
            "code": verification_code,
            "expires_at": verification_expires.isoformat(),
            "email": email,
            "data": {
                "password": hash_password(password),
                "role": "admin",
                "profil": {
                    "nama_pemilik":   nama_pemilik,
                    "nama_rental":    nama_rental,
                    "email":          email,
                    "no_hp":          no_hp,
                    "alamat":         alamat,
                    "tanggal_daftar": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
            },
        }
        cfg["pending_email_verifications"] = pending
        ConfigManager.save(cfg)

        sukses, pesan = _send_verification_email(email, username, verification_code)
        if not sukses:
            self.lbl_daftar_status.configure(
                text=f"✖  Gagal kirim kode verifikasi: {pesan}",
                text_color=C_RED)
            return

        AuditLogger.log(
            action="registration_pending",
            username=username,
            status="pending",
            details={"email": email}
        )

        self._show_verification_dialog(username)

    def _save_pending_verification(self, username: str, payload: dict):
        cfg = ConfigManager.load()
        pending = cfg.get("pending_email_verifications", {})
        pending[username] = payload
        cfg["pending_email_verifications"] = pending
        ConfigManager.save(cfg)

    def _load_pending_verification(self, username: str) -> dict:
        cfg = ConfigManager.load()
        return cfg.get("pending_email_verifications", {}).get(username, {})

    def _clear_pending_verification(self, username: str):
        cfg = ConfigManager.load()
        pending = cfg.get("pending_email_verifications", {})
        if username in pending:
            pending.pop(username)
            cfg["pending_email_verifications"] = pending
            ConfigManager.save(cfg)

    def _show_verification_dialog(self, username: str):
        pending = self._load_pending_verification(username)
        if not pending:
            messagebox.showerror("✖ Error", "Data verifikasi tidak ditemukan. Coba daftar ulang.")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("📧 Verifikasi Email")
        dialog.geometry("420x260")
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="Verifikasi Email", font=("Russo One", 16, "bold"),
                     text_color=C_ACCENT).pack(pady=(20, 10))
        ctk.CTkLabel(dialog,
                     text=f"Kode dikirim ke {pending.get('email')}. Masukkan kode di bawah.",
                     font=FONT_BODY, text_color=C_TEXT, wraplength=380).pack(pady=(0, 10))

        entry_code = ctk.CTkEntry(dialog, placeholder_text="Kode verifikasi 6 digit",
                                  fg_color=C_BTN, text_color=C_ACCENT,
                                  border_color=C_BORDER, font=FONT_BODY, height=40)
        entry_code.pack(fill="x", padx=30, pady=(0, 10))
        try:
            entry_code.focus()
        except Exception:
            pass

        status_label = ctk.CTkLabel(dialog, text="", font=FONT_LABEL, text_color=C_RED,
                                    wraplength=380, justify="center")
        status_label.pack(pady=(0, 10))

        def submit_code():
            code = sanitize_text(entry_code.get())
            if not code:
                status_label.configure(text="⚠  Masukkan kode verifikasi.", text_color=C_YELLOW)
                return
            success, msg = self._submit_verification_code(username, code)
            if success:
                dialog.destroy()
            else:
                status_label.configure(text=msg, text_color=C_RED)

        def resend_code():
            code = generate_verification_code()
            pending_data = self._load_pending_verification(username)
            if not pending_data:
                status_label.configure(text="✖  Data verifikasi hilang.", text_color=C_RED)
                return
            pending_data["code"] = code
            pending_data["expires_at"] = (datetime.now() + timedelta(minutes=EMAIL_VERIFICATION_EXPIRY_MINUTES)).isoformat()
            self._save_pending_verification(username, pending_data)
            sukses, pesan = _send_verification_email(pending_data.get("email", ""), username, code)
            if sukses:
                status_label.configure(text="✅  Kode baru telah dikirim.", text_color=C_GREEN)
                AuditLogger.log(
                    action="email_verification_resent",
                    username=username,
                    status="pending",
                    details={"email": pending_data.get("email", "")}
                )
            else:
                status_label.configure(text=f"✖  Gagal kirim ulang: {pesan}", text_color=C_RED)

        ctk.CTkButton(dialog, text="✅  Verifikasi", width=160, height=38,
                      fg_color=C_ACCENT2, hover_color="#5A0FCC",
                      font=("Russo One", 10, "bold"), text_color="white",
                      command=submit_code).pack(pady=(0, 6))
        ctk.CTkButton(dialog, text="🔁  Kirim Ulang Kode", width=160, height=34,
                      fg_color="transparent", hover_color=C_BTN,
                      border_width=1, border_color=C_ACCENT,
                      font=("Russo One", 10, "bold"), text_color=C_ACCENT,
                      command=resend_code).pack(pady=(0, 8))

    def _submit_verification_code(self, username: str, code: str) -> tuple:
        pending = self._load_pending_verification(username)
        if not pending:
            return False, "Data verifikasi tidak ditemukan. Coba daftar ulang."

        expires_at = pending.get("expires_at")
        if not expires_at:
            return False, "Data kadaluarsa tidak valid."

        try:
            expires = datetime.fromisoformat(expires_at)
        except Exception:
            return False, "Data kadaluarsa tidak valid."

        if datetime.now() > expires:
            self._clear_pending_verification(username)
            return False, "Kode verifikasi sudah kadaluarsa. Daftar ulang untuk mengirim kode baru."

        if code != pending.get("code"):
            AuditLogger.log(
                action="email_verification_failed",
                username=username,
                status="invalid_code",
                details={"attempt_code": code}
            )
            return False, "Kode verifikasi tidak cocok."

        data = pending.get("data", {})
        cfg = ConfigManager.load()
        users = cfg.get("users", dict(LoginPage.DEFAULT_USERS))
        if username in users:
            self._clear_pending_verification(username)
            return False, "Username sudah terdaftar."

        users[username] = {
            "password": data.get("password"),
            "role": data.get("role", "admin"),
        }
        cfg["users"] = users
        profil_semua = cfg.get("profil_rental", {})
        profil_semua[username] = data.get("profil", {})
        cfg["profil_rental"] = profil_semua
        self._clear_pending_verification(username)
        ConfigManager.save(cfg)

        AuditLogger.log(
            action="registration",
            username=username,
            status="verified",
            details={"email": pending.get("email")}
        )

        messagebox.showinfo("✅ Terverifikasi", "Email berhasil diverifikasi. Silakan login.")
        self._show_login_view()
        self.entry_user.delete(0, "end")
        self.entry_user.insert(0, username)
        try:
            self.entry_pass.focus()
        except Exception:
            pass
        return True, ""

    # ══════════════════════════════════════════════════════════════════════════
    #  VIEW 3 — LUPA PASSWORD
    # ══════════════════════════════════════════════════════════════════════════
    def _show_lupa_password_view(self):
        for w in self._view_container.winfo_children():
            w.destroy()
        self._lp_username_verified = None

        self.lp_outer = ctk.CTkFrame(self._view_container, fg_color=C_PANEL,
                                      corner_radius=20, border_width=2,
                                      border_color=C_RED)
        self.lp_outer.pack(fill="both", expand=True)

        # Header merah
        hdr = ctk.CTkFrame(self.lp_outer, fg_color=C_RED, corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="🔓  LUPA PASSWORD",
                     font=("Russo One", 14, "bold"),
                     text_color="white").pack(pady=14)

        ctk.CTkLabel(self.lp_outer,
                     text="Masukkan username dan email yang saat daftar.\n"
                          "Jika cocok, kamu bisa set password baru.",
                     font=FONT_SMALL, text_color=C_MUTED,
                     justify="center").pack(pady=(14, 4))

        # ── STEP 1: Verifikasi ────────────────────────────────────────────────
        step1 = ctk.CTkFrame(self.lp_outer, fg_color=C_CARD, corner_radius=12)
        step1.pack(fill="x", padx=28, pady=(6, 4))

        # Indikator step
        step_row = ctk.CTkFrame(step1, fg_color="transparent")
        step_row.pack(fill="x", padx=14, pady=(12, 8))
        for no, label, aktif in [("1", "Verifikasi Identitas", True),
                                   ("2", "Set Password Baru",   False)]:
            dot = ctk.CTkFrame(step_row, fg_color=C_ACCENT2 if aktif else C_BTN,
                                corner_radius=12, width=24, height=24)
            dot.pack(side="left", padx=(0, 4))
            dot.pack_propagate(False)
            ctk.CTkLabel(dot, text=no, font=("Russo One", 9, "bold"),
                          text_color="white").place(relx=0.5, rely=0.5, anchor="center")
            ctk.CTkLabel(step_row, text=label, font=FONT_LABEL,
                          text_color=C_ACCENT2 if aktif else C_MUTED).pack(side="left", padx=(0, 16))

        ctk.CTkFrame(step1, height=1, fg_color=C_BORDER).pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(step1, text="Username:", font=FONT_LABEL,
                     text_color=C_MUTED, anchor="w").pack(anchor="w", padx=14, pady=(0, 2))
        self.lp_entry_username = ctk.CTkEntry(
            step1, placeholder_text="Username akun Anda",
            fg_color=C_BTN, text_color=C_ACCENT,
            border_color=C_BORDER,
            font=("Consolas", 12, "bold"), height=36)
        self.lp_entry_username.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(step1, text="Email yang didaftarkan:", font=FONT_LABEL,
                     text_color=C_MUTED, anchor="w").pack(anchor="w", padx=14, pady=(0, 2))
        self.lp_entry_email = ctk.CTkEntry(
            step1, placeholder_text="mis. nama@gmail.com",
            fg_color=C_BTN, text_color=C_ACCENT,
            border_color=C_BORDER,
            font=("Consolas", 12, "bold"), height=36)
        self.lp_entry_email.pack(fill="x", padx=14, pady=(0, 10))
        self.lp_entry_email.bind("<Return>", lambda e: self._verifikasi_identitas())

        self.btn_verif = ctk.CTkButton(
            step1, text="✅  Verifikasi Identitas", height=38,
            fg_color=C_ACCENT2, hover_color="#4A20C8",
            font=("Russo One", 10, "bold"), text_color="white",
            command=self._verifikasi_identitas)
        self.btn_verif.pack(fill="x", padx=14, pady=(0, 14))

        # ── STEP 2: Set password baru (hidden, muncul setelah verifikasi) ─────
        self.lp_step2 = ctk.CTkFrame(self.lp_outer, fg_color=C_CARD, corner_radius=12)
        # Belum di-pack — ditampilkan setelah verifikasi sukses

        step2_hdr = ctk.CTkFrame(self.lp_step2, fg_color=C_GREEN, corner_radius=8)
        step2_hdr.pack(fill="x", padx=14, pady=(12, 8))
        ctk.CTkLabel(step2_hdr,
                     text="✅  Identitas Terverifikasi — Set Password Baru",
                     font=FONT_SUB, text_color=C_BG).pack(pady=8)

        ctk.CTkLabel(self.lp_step2, text="Password Baru:", font=FONT_LABEL,
                     text_color=C_MUTED, anchor="w").pack(anchor="w", padx=14, pady=(4, 2))
        self.lp_entry_pass1 = ctk.CTkEntry(
            self.lp_step2, placeholder_text="Minimal 6 karakter",
            fg_color=C_BTN, text_color=C_ACCENT,
            border_color=C_BORDER,
            font=("Consolas", 12, "bold"), height=36, show="●")
        self.lp_entry_pass1.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(self.lp_step2, text="Konfirmasi Password:", font=FONT_LABEL,
                     text_color=C_MUTED, anchor="w").pack(anchor="w", padx=14, pady=(0, 2))
        self.lp_entry_pass2 = ctk.CTkEntry(
            self.lp_step2, placeholder_text="Ulangi password baru",
            fg_color=C_BTN, text_color=C_ACCENT,
            border_color=C_BORDER,
            font=("Consolas", 12, "bold"), height=36, show="●")
        self.lp_entry_pass2.pack(fill="x", padx=14, pady=(0, 10))
        self.lp_entry_pass2.bind("<Return>", lambda e: self._submit_reset_password())

        ctk.CTkButton(
            self.lp_step2, text="🔒  Simpan Password Baru", height=40,
            fg_color=C_GREEN, hover_color="#20CC00",
            font=("Russo One", 11, "bold"), text_color=C_BG,
            command=self._submit_reset_password
        ).pack(fill="x", padx=14, pady=(0, 14))

        # Status
        self.lp_lbl_status = ctk.CTkLabel(self.lp_outer, text="",
                                            font=FONT_LABEL,
                                            text_color=C_RED,
                                            wraplength=380,
                                            justify="center")
        self.lp_lbl_status.pack(pady=(4, 6))

        # Kembali login
        ctk.CTkButton(self.lp_outer, text="← KEMBALI LOGIN", height=36,
                      fg_color="transparent", hover_color=C_BTN,
                      border_width=1, border_color=C_MUTED,
                      font=("Russo One", 9, "bold"), text_color=C_MUTED,
                      command=self._show_login_view
                      ).pack(padx=28, pady=(0, 22), fill="x")

    def _verifikasi_identitas(self):
        username = sanitize_text(self.lp_entry_username.get()).lower()
        email    = sanitize_text(self.lp_entry_email.get()).lower()

        if not username or not email:
            self.lp_lbl_status.configure(
                text="⚠  Username dan email wajib diisi.",
                text_color=C_YELLOW)
            return

        if not is_valid_username(username):
            self.lp_lbl_status.configure(
                text="⚠  Username tidak valid.",
                text_color=C_YELLOW)
            return

        if not is_valid_email(email):
            self.lp_lbl_status.configure(
                text="⚠  Format email tidak valid.",
                text_color=C_YELLOW)
            return

        cfg          = ConfigManager.load()
        users        = cfg.get("users", {})
        profil_semua = cfg.get("profil_rental", {})

        # Cek username terdaftar
        if username not in users:
            self.lp_lbl_status.configure(
                text="✖  Username tidak ditemukan.",
                text_color=C_RED)
            return

        # Cek email cocok
        profil = profil_semua.get(username, {})
        email_terdaftar = profil.get("email", "").strip().lower()

        if not email_terdaftar:
            self.lp_lbl_status.configure(
                text="✖  Akun ini tidak punya email terdaftar.\n"
                     "Hubungi admin/developer untuk reset password.",
                text_color=C_RED)
            return

        if email != email_terdaftar:
            self.lp_lbl_status.configure(
                text="✖  Email tidak cocok dengan data yang terdaftar.",
                text_color=C_RED)
            return

        # Generate verification code
        code = generate_verification_code()
        exp_time = (datetime.now() + timedelta(minutes=EMAIL_VERIFICATION_EXPIRY_MINUTES)).isoformat()
        
        # Store in pending verification
        pending_verif = cfg.get("pending_forgot_password_verifications", {})
        pending_verif[username] = {
            "code": code,
            "expires_at": exp_time,
            "email": email
        }
        cfg["pending_forgot_password_verifications"] = pending_verif
        ConfigManager.save(cfg)
        
        # Send email verification code
        self.lp_lbl_status.configure(
            text="📧  Mengirim kode verifikasi ke email...",
            text_color=C_MUTED)
        self.lp_lbl_status.update()
        
        threading.Thread(target=self._send_forgot_password_code, args=(username, email, code), daemon=True).start()

    def _send_forgot_password_code(self, username: str, email: str, code: str):
        """Send verification code via email."""
        smtp_settings = ConfigManager.get("email_settings", {})
        if not all([smtp_settings.get('smtp_server'), smtp_settings.get('smtp_username'), smtp_settings.get('smtp_password')]):
            self.after(0, lambda: self.lp_lbl_status.configure(
                text="⚠  Email SMTP belum dikonfigurasi.",
                text_color=C_YELLOW))
            return

        try:
            msg = EmailMessage()
            msg['Subject'] = "🔐 Kode Verifikasi Lupa Password - RR Billing PRO"
            msg['From'] = smtp_settings.get('from_address', smtp_settings.get('smtp_username'))
            msg['To'] = email

            html_body = f"""
<html>
<body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
    <div style="max-width: 600px; margin: 0 auto; background-color: white; border-radius: 10px; padding: 30px; box-shadow: 0 0 10px rgba(0,0,0,0.1);">
        <h2 style="color: #1e1e4a; text-align: center;">RR BILLING PRO</h2>
        <h3 style="color: #ff3366; text-align: center;">Permintaan Ubah Password</h3>
        
        <p style="color: #333; font-size: 14px;">Hai <strong>{username}</strong>,</p>
        <p style="color: #666; font-size: 14px;">Kami menerima permintaan untuk mengubah password akun Anda. Gunakan kode verifikasi di bawah ini:</p>
        
        <div style="background-color: #0d0d1a; border: 2px solid #7b2fff; border-radius: 8px; padding: 20px; text-align: center; margin: 20px 0;">
            <p style="font-size: 28px; font-weight: bold; color: #00ffcc; margin: 0; letter-spacing: 4px;">{code}</p>
            <p style="color: #6060a0; margin: 10px 0 0 0; font-size: 12px;">Kode berlaku selama 30 menit</p>
        </div>
        
        <p style="color: #666; font-size: 14px;">Langkah-langkah:</p>
        <ol style="color: #666; font-size: 14px;">
            <li>Masukkan kode verifikasi di aplikasi</li>
            <li>Set password baru Anda</li>
            <li>Login dengan password baru</li>
        </ol>
        
        <p style="color: #999; font-size: 12px; margin-top: 30px; border-top: 1px solid #eee; padding-top: 20px;">
            Jika Anda tidak membuat permintaan ini, abaikan email ini atau hubungi admin kami segera.
        </p>
    </div>
</body>
</html>
"""
            msg.set_content(f"Kode verifikasi: {code}")
            msg.add_alternative(html_body, subtype='html')

            context = ssl.create_default_context()
            with smtplib.SMTP(smtp_settings['smtp_server'], smtp_settings['smtp_port']) as smtp:
                smtp.starttls(context=context)
                smtp.login(smtp_settings['smtp_username'], smtp_settings['smtp_password'])
                smtp.send_message(msg)

            self.after(0, lambda: self._show_forgot_password_verify_code_view())
        except Exception as e:
            self.after(0, lambda: self.lp_lbl_status.configure(
                text=f"❌  Gagal kirim email: {str(e)[:50]}",
                text_color=C_RED))

    def _show_forgot_password_verify_code_view(self):
        """Show verification code input form."""
        username = sanitize_text(self.lp_entry_username.get()).lower()
        
        # Clear and redesign the view - destroy only step 1 form, keep status and step2
        if hasattr(self, 'lp_step1_verif') and self.lp_step1_verif.winfo_exists():
            self.lp_step1_verif.destroy()

        # Re-create step1 with verification code input
        self.lp_step1_verif = ctk.CTkFrame(self.lp_outer, fg_color=C_CARD, corner_radius=12)
        self.lp_step1_verif.pack(fill="x", padx=28, pady=(6, 4), before=self.lp_lbl_status)

        ctk.CTkLabel(self.lp_step1_verif, text="📧  Cek Email Anda",
                     font=("Russo One", 12, "bold"),
                     text_color=C_GREEN).pack(pady=(12, 4))

        ctk.CTkLabel(self.lp_step1_verif, text="Kami sudah mengirim kode verifikasi ke email Anda.\nMasukkan kode 6 digit di bawah.",
                     font=FONT_SMALL, text_color=C_MUTED,
                     justify="center").pack(pady=(0, 10))

        ctk.CTkLabel(self.lp_step1_verif, text="Kode Verifikasi (6 digit):", font=FONT_LABEL,
                     text_color=C_MUTED, anchor="w").pack(anchor="w", padx=14, pady=(0, 2))
        
        self.lp_entry_verif_code = ctk.CTkEntry(
            self.lp_step1_verif, placeholder_text="mis. 123456",
            fg_color=C_BTN, text_color=C_ACCENT,
            border_color=C_BORDER,
            font=("Consolas", 16, "bold"), height=40)
        self.lp_entry_verif_code.pack(fill="x", padx=14, pady=(0, 10))
        self.lp_entry_verif_code.bind("<Return>", lambda e: self._verify_forgot_password_code())
        try:
            self.lp_entry_verif_code.focus()
        except Exception:
            pass

        ctk.CTkButton(
            self.lp_step1_verif, text="✅  Verifikasi Kode", height=38,
            fg_color=C_ACCENT2, hover_color="#4A20C8",
            font=("Russo One", 10, "bold"), text_color="white",
            command=self._verify_forgot_password_code).pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkButton(
            self.lp_step1_verif, text="📧  Kirim Ulang Kode", height=36,
            fg_color=C_BTN, hover_color=C_BORDER,
            font=("Russo One", 9, "bold"), text_color=C_MUTED,
            command=lambda: self._verifikasi_identitas()).pack(fill="x", padx=14, pady=(0, 14))

    def _verify_forgot_password_code(self):
        """Verify the code sent via email."""
        username = sanitize_text(self.lp_entry_username.get()).lower()
        code_input = sanitize_text(self.lp_entry_verif_code.get()).strip()

        if not code_input:
            self.lp_lbl_status.configure(
                text="⚠  Kode verifikasi wajib diisi.",
                text_color=C_YELLOW)
            return

        cfg = ConfigManager.load()
        pending = cfg.get("pending_forgot_password_verifications", {})
        
        if username not in pending:
            self.lp_lbl_status.configure(
                text="⚠  Data verifikasi tidak ditemukan. Mulai ulang dari awal.",
                text_color=C_YELLOW)
            return

        pending_data = pending[username]
        exp_dt = datetime.fromisoformat(pending_data["expires_at"])
        
        if datetime.now() > exp_dt:
            del pending[username]
            cfg["pending_forgot_password_verifications"] = pending
            ConfigManager.save(cfg)
            self.lp_lbl_status.configure(
                text="⚠  Kode verifikasi sudah kadaluarsa (berlaku 30 menit).\nSilakan minta kode baru.",
                text_color=C_YELLOW)
            return

        if code_input != pending_data["code"]:
            self.lp_lbl_status.configure(
                text="✖  Kode verifikasi tidak cocok.",
                text_color=C_RED)
            return

        # Code verified!
        self._lp_username_verified = username
        del pending[username]
        cfg["pending_forgot_password_verifications"] = pending
        ConfigManager.save(cfg)

        self.lp_lbl_status.configure(
            text=f"✅  Kode terverifikasi! Set password baru di bawah.",
            text_color=C_GREEN)

        # Hide verification code input step
        if hasattr(self, 'lp_step1_verif'):
            self.lp_step1_verif.pack_forget()
        
        # Show password reset form
        self.lp_step2.pack(fill="x", padx=28, pady=(6, 4))
        try:
            self.lp_entry_pass1.focus()
        except Exception:
            pass

    def _submit_reset_password(self):
        if not self._lp_username_verified:
            self.lp_lbl_status.configure(
                text="⚠  Lakukan verifikasi identitas dulu (Langkah 1).",
                text_color=C_YELLOW)
            return

        pw1 = self.lp_entry_pass1.get().strip()
        pw2 = self.lp_entry_pass2.get().strip()

        if not is_valid_password(pw1):
            self.lp_lbl_status.configure(
                text="⚠  Password baru harus minimal 8 karakter dan berisi huruf serta angka.",
                text_color=C_YELLOW)
            return
        if pw1 != pw2:
            self.lp_lbl_status.configure(
                text="⚠  Konfirmasi password tidak cocok.",
                text_color=C_YELLOW)
            self.lp_entry_pass2.delete(0, "end")
            try:
                self.lp_entry_pass2.focus()
            except Exception:
                pass
            return

        cfg   = ConfigManager.load()
        users = cfg.get("users", {})
        if self._lp_username_verified not in users:
            self.lp_lbl_status.configure(
                text="✖  User tidak ditemukan. Coba lagi.",
                text_color=C_RED)
            return

        # Simpan password baru (dengan bcrypt)
        users[self._lp_username_verified]["password"] = hash_password(pw1)
        cfg["users"] = users
        ConfigManager.save(cfg)
        AuditLogger.log(
            action="password_reset",
            username=self._lp_username_verified,
            status="success",
            details={"method": "forgot_password"}
        )

        uname = self._lp_username_verified
        self._lp_username_verified = None

        # Kembali ke login dengan pesan sukses
        self._show_login_view()
        self.entry_user.delete(0, "end")
        self.entry_user.insert(0, uname)
        try:
            self.entry_pass.focus()
        except Exception:
            pass
        self.lbl_status.configure(
            text=f"✅  Password '{uname}' berhasil direset — silakan login.",
            text_color=C_GREEN)

    # ══════════════════════════════════════════════════════════════════════════
    #  HELPER BERSAMA
    # ══════════════════════════════════════════════════════════════════════════
    def _cek_status_lisensi(self):
        current_user = getattr(self, 'current_user', None) or ""
        if not current_user:
            self.lbl_lic.configure(text="Silakan login untuk melanjutkan.", text_color=C_MUTED)
            return
        status = LicenseManager.get_status(current_user=current_user)
        if status["status"] == "expired":
            self.lbl_lic.configure(
                text=f"⚠ {status['pesan']} — Login masih bisa, tapi fitur terbatas.",
                text_color=C_RED)
        elif status["status"] == "trial":
            self.lbl_lic.configure(
                text=f"🕐 {status['pesan']}", text_color=C_YELLOW)
        else:
            self.lbl_lic.configure(text="✅ Lisensi Aktif", text_color=C_GREEN)

    def _login(self):
        if self._locked_until and datetime.now() < self._locked_until:
            sisa = int((self._locked_until - datetime.now()).total_seconds())
            self.lbl_status.configure(text=f"⛔ Terkunci — coba lagi dalam {sisa}s")
            return

        username  = sanitize_text(self.entry_user.get().lower())
        password  = self.entry_pass.get().strip()

        if not username or not password:
            self.lbl_status.configure(
                text="⚠  Username dan password wajib diisi.", text_color=C_YELLOW)
            return

        if not is_valid_username(username):
            self.lbl_status.configure(
                text="⚠  Username harus 4-20 karakter alfanumerik, titik, atau garis bawah.",
                text_color=C_YELLOW)
            return

        users = ConfigManager.get("users", self.DEFAULT_USERS)
        if not isinstance(users, dict):
            users = {}
        user_data = users.get(username) if isinstance(users, dict) else None
        password_hash = user_data.get("password") if isinstance(user_data, dict) else ""

        # Gunakan verify_password() yang support bcrypt dan legacy SHA256
        if user_data and verify_password(password, password_hash):
            self._attempt = 0
            if not password_hash.startswith("bcrypt$"):
                users[username]["password"] = hash_password(password)
                cfg = ConfigManager.load()
                cfg_users = cfg.get("users", {})
                if isinstance(cfg_users, dict) and username in cfg_users:
                    cfg_users[username]["password"] = users[username]["password"]
                    cfg["users"] = cfg_users
                    ConfigManager.save(cfg)
            AuditLogger.log(
                action="login_success",
                username=username,
                status="success",
                details={"role": user_data.get("role", "kasir")}
            )
            self.on_login_success(username, user_data.get("role", "kasir"))
            return

        self._attempt += 1
        if self._attempt >= self.LOGIN_MAX_ATTEMPTS:
            self._locked_until = datetime.now() + self.LOGIN_LOCK_DURATION
            self.lbl_status.configure(
                text=f"⛔ {self.LOGIN_MAX_ATTEMPTS}x salah — terkunci {int(self.LOGIN_LOCK_DURATION.total_seconds()/60)} menit",
                text_color=C_RED)
            AuditLogger.log(
                action="login_failed",
                username=username,
                status="locked",
                details={"attempts": self._attempt}
            )
        else:
            self.lbl_status.configure(
                text=f"✖ Username/Password salah ({self._attempt}/{self.LOGIN_MAX_ATTEMPTS})",
                text_color=C_RED)
            AuditLogger.log(
                action="login_failed",
                username=username,
                status="failed",
                details={"attempts": self._attempt}
            )


# ═══════════════════════════════════════════════════════════════════════════════
#  DIALOG PAIRING
# ═══════════════════════════════════════════════════════════════════════════════
class DialogPairing(ctk.CTkToplevel):
    def __init__(self, master, ip_awal="", on_confirm=None, on_close_cb=None):
        super().__init__(master)
        self.title("📡  Pairing ADB — Android TV 11+")
        self.geometry("460x420")
        self.configure(fg_color=C_BG)
        self.transient(master)
        self.resizable(False, False)
        self.on_confirm  = on_confirm
        self.on_close_cb = on_close_cb
        self._confirmed  = False
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build(ip_awal)
        center_window(self, master, width=460, height=420)
        self.after(50, self.grab_set)

    def _build(self, ip_awal):
        ctk.CTkLabel(self, text="📡  Pairing ADB Wi-Fi",
                     font=FONT_TITLE, text_color=C_ACCENT).pack(pady=(20, 2))
        ctk.CTkLabel(self, text="Untuk Android TV 11+  —  kode pairing hanya sekali pakai",
                     font=FONT_SMALL, text_color=C_MUTED).pack(pady=(0, 14))
        panel = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=12,
                             border_width=1, border_color=C_ACCENT2)
        panel.pack(fill="x", padx=22, pady=6)
        hdr = ctk.CTkFrame(panel, fg_color=C_ACCENT2, corner_radius=8)
        hdr.pack(fill="x", padx=1, pady=(1, 0))
        ctk.CTkLabel(hdr, text="  Di TV: Pengaturan → Opsi Developer → Wireless Debugging",
                     font=FONT_SUB, text_color="white").pack(anchor="w", padx=10, pady=6)
        ctk.CTkLabel(panel, text="→ Tap 'Pair device with pairing code'  →  catat IP, Port & Kode PIN",
                     font=FONT_SMALL, text_color=C_MUTED).pack(anchor="w", padx=14, pady=(10, 6))
        for label, attr, ph, color in [
            ("IP Address :", "e_ip", "192.168.x.xxx", C_ACCENT),
            ("Port PAIRING :", "e_pair_port", "mis. 42135", C_YELLOW),
            ("Kode PIN :", "e_pin", "6 digit", C_GREEN),
        ]:
            r = ctk.CTkFrame(panel, fg_color="transparent")
            r.pack(fill="x", padx=14, pady=4)
            ctk.CTkLabel(r, text=label, font=FONT_LABEL, text_color=C_MUTED,
                         width=120, anchor="w").pack(side="left")
            e = ctk.CTkEntry(r, placeholder_text=ph, fg_color=C_BTN, text_color=color,
                              border_color=C_BORDER, font=("Consolas", 12, "bold"), height=34)
            e.pack(side="left", fill="x", expand=True)
            setattr(self, attr, e)
        if ip_awal:
            self.e_ip.insert(0, ip_awal)
        self.lbl_status = ctk.CTkLabel(self, text="⬤  Siap",
                                        font=FONT_BODY, text_color=C_MUTED)
        self.lbl_status.pack(pady=10)
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(pady=8)
        self.btn_pair = ctk.CTkButton(bot, text="🔑  Pair & Connect", width=200, height=38,
                                       fg_color="#1A3A1A", hover_color="#0A2A0A",
                                       border_width=1, border_color=C_GREEN,
                                       font=FONT_SUB, text_color=C_GREEN,
                                       command=self._lakukan_pair)
        self.btn_pair.pack(side="left", padx=8)
        ctk.CTkButton(bot, text="✖  Tutup", width=120, height=38,
                      fg_color=C_RED, hover_color="#CC0033",
                      font=FONT_SUB, text_color="white",
                      command=self._on_close).pack(side="left", padx=8)

    def _lakukan_pair(self):
        ip = self.e_ip.get().strip()
        pair_port = self.e_pair_port.get().strip()
        pin = self.e_pin.get().strip()
        if not ip or not pair_port.isdigit() or not pin:
            self.lbl_status.configure(text="⚠  Isi semua field", text_color=C_YELLOW)
            return
        self.btn_pair.configure(state="disabled", text="⏳...")
        threading.Thread(target=self._pair_thread, args=(ip, int(pair_port), pin), daemon=True).start()

    def _pair_thread(self, ip, pair_port, pin):
        sukses, port, pesan = ADBHelper.pair_dan_connect(ip, pair_port, pin)
        self.after(0, self._selesai, sukses, ip, port, pesan)

    def _selesai(self, sukses, ip, port, pesan):
        self.btn_pair.configure(state="normal", text="🔑  Pair & Connect")
        if sukses:
            self.lbl_status.configure(text=f"✅  BERHASIL — {ip}:{port}", text_color=C_GREEN)
            self._confirmed = True
            if self.on_confirm:
                self.on_confirm(ip, port)
            self.after(800, self.destroy)
        else:
            self.lbl_status.configure(text=f"✖  {pesan}", text_color=C_RED, wraplength=440)

    def _on_close(self):
        if not self._confirmed and self.on_close_cb:
            self.on_close_cb()
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
#  DIALOG GANTI PORT
# ═══════════════════════════════════════════════════════════════════════════════
class DialogGantiPort(ctk.CTkToplevel):
    def __init__(self, master, label_tv, ip, port_lama, on_confirm):
        super().__init__(master)
        self.title(f"Ganti Port — {label_tv}")
        self.geometry("380x320")
        self.configure(fg_color=C_BG)
        self.transient(master)
        self.resizable(False, False)
        self.label_tv = label_tv
        self.ip = ip
        self.port_lama = port_lama
        self.on_confirm = on_confirm
        self._connected = False
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text=f"📺  {self.label_tv}",
                     font=FONT_TITLE, text_color=C_ACCENT).pack(pady=(22, 4))
        ctk.CTkLabel(self, text="Masukkan port ADB baru lalu tes koneksi",
                     font=FONT_BODY, text_color=C_MUTED).pack(pady=(0, 14))
        port_f = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=10)
        port_f.pack(fill="x", padx=28, pady=4)
        ctk.CTkLabel(port_f, text=f"Port ADB Baru (lama: {self.port_lama})",
                     font=FONT_LABEL, text_color=C_MUTED).pack(anchor="w", padx=14, pady=(8, 2))
        port_row = ctk.CTkFrame(port_f, fg_color="transparent")
        port_row.pack(fill="x", padx=14, pady=(0, 10))
        self.entry_port = ctk.CTkEntry(port_row, placeholder_text="contoh: 37123",
                                        fg_color=C_BTN, text_color=C_ACCENT,
                                        border_color=C_BORDER, font=("Consolas", 13, "bold"), height=34)
        self.entry_port.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.btn_tes = ctk.CTkButton(port_row, text="🔗 Tes", width=72, height=34,
                                      fg_color=C_BTN, border_width=1, border_color=C_GREEN,
                                      font=FONT_LABEL, text_color=C_GREEN,
                                      command=self._tes_koneksi)
        self.btn_tes.pack(side="left")
        self.lbl_status = ctk.CTkLabel(self, text="⬤  Belum diuji",
                                        font=FONT_BODY, text_color=C_MUTED)
        self.lbl_status.pack(pady=8)
        btn_f = ctk.CTkFrame(self, fg_color="transparent")
        btn_f.pack(pady=6)
        self.btn_simpan = ctk.CTkButton(btn_f, text="✅  Simpan Port", width=150, height=36,
                                         fg_color=C_ACCENT2, font=FONT_SUB, text_color="white",
                                         state="disabled", command=self._konfirmasi)
        self.btn_simpan.pack(side="left", padx=8)
        ctk.CTkButton(btn_f, text="✖  Batal", width=100, height=36,
                      fg_color=C_RED, font=FONT_SUB, text_color="white",
                      command=self.destroy).pack(side="left", padx=8)

    def _tes_koneksi(self):
        port_str = self.entry_port.get().strip()
        if not port_str.isdigit():
            self.lbl_status.configure(text="⚠  Port harus angka", text_color=C_YELLOW)
            return
        port = int(port_str)
        self.btn_tes.configure(text="⏳...", state="disabled")
        threading.Thread(target=self._connect_thread, args=(port,), daemon=True).start()

    def _connect_thread(self, port):
        sukses, pesan = ADBHelper.connect(self.ip, port)
        if sukses:
            status, _ = ADBHelper.status_untuk_ip(self.ip, port)
            if status != "device":
                sukses = False
                pesan = "Unauthorized" if status == "unauthorized" else f"Status: {status}"
        self.after(0, self._update_status, sukses, port, pesan)

    def _update_status(self, sukses, port, pesan=""):
        self.btn_tes.configure(state="normal", text="🔗 Tes")
        if sukses:
            self._connected = True
            self._port_baru = port
            self.lbl_status.configure(text=f"● TERHUBUNG  {self.ip}:{port}", text_color=C_GREEN)
            self.btn_simpan.configure(state="normal")
        else:
            self.lbl_status.configure(text=f"● GAGAL  {pesan}", text_color=C_RED)
            self.btn_simpan.configure(state="disabled")

    def _konfirmasi(self):
        if self._connected:
            self.on_confirm(self._port_baru)
            self.destroy()


class DialogGantiIP(ctk.CTkToplevel):
    def __init__(self, master, label_tv, ip_lama, port_lama, on_confirm):
        super().__init__(master)
        self.title(f"Ganti IP & Port — {label_tv}")
        self.geometry("380x260")
        self.configure(fg_color=C_BG)
        self.transient(master)
        self.resizable(False, False)
        self.label_tv = label_tv
        self.ip_lama = ip_lama
        self.port_lama = port_lama
        self.on_confirm = on_confirm
        self._connected = False
        self._port_baru = None
        self._build()
        center_window(self, master, width=380, height=320)
        self.after(50, self.grab_set)

    def _build(self):
        ctk.CTkLabel(self, text=f"📺  {self.label_tv}", font=FONT_TITLE, text_color=C_ACCENT).pack(pady=(16, 4))
        ctk.CTkLabel(self, text="Masukkan IP & Port baru lalu tes koneksi ADB",
                     font=FONT_BODY, text_color=C_MUTED).pack(pady=(0, 10))

        row = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=10)
        row.pack(fill="x", padx=18, pady=4)

        ip_row = ctk.CTkFrame(row, fg_color="transparent")
        ip_row.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkLabel(ip_row, text="IP:", font=FONT_LABEL, text_color=C_MUTED, width=60).pack(side="left")
        self.entry_ip = ctk.CTkEntry(ip_row, fg_color=C_BTN, text_color=C_ACCENT,
                                     border_color=C_BORDER, font=("Consolas", 12, "bold"), height=34)
        self.entry_ip.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_ip.insert(0, self.ip_lama)

        port_row = ctk.CTkFrame(row, fg_color="transparent")
        port_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(port_row, text="Port:", font=FONT_LABEL, text_color=C_MUTED, width=60).pack(side="left")
        self.entry_port = ctk.CTkEntry(port_row, fg_color=C_BTN, text_color=C_YELLOW,
                                       border_color=C_BORDER, font=("Consolas", 12, "bold"), height=34,
                                       width=120)
        self.entry_port.pack(side="left", padx=(0, 8))
        self.entry_port.insert(0, str(self.port_lama or DEFAULT_PORT))

        self.btn_tes = ctk.CTkButton(self, text="🔗 Tes", width=120, height=34,
                                      fg_color=C_BTN, border_width=1, border_color=C_GREEN,
                                      font=FONT_LABEL, text_color=C_GREEN,
                                      command=self._tes_koneksi)
        self.btn_tes.pack(pady=(6, 4))

        self.lbl_status = ctk.CTkLabel(self, text="⬤  Belum diuji",
                                        font=FONT_BODY, text_color=C_MUTED)
        self.lbl_status.pack(pady=(0, 8))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=18, pady=(0, 14))
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        ctk.CTkButton(btn_frame, text="✖  Batal", fg_color=C_RED, command=self.destroy).grid(row=0, column=0, sticky="we", padx=(0, 6))
        ctk.CTkButton(btn_frame, text="✅  Simpan", fg_color=C_ACCENT2, command=self._konfirmasi).grid(row=0, column=1, sticky="we", padx=(6, 0))

        self.entry_ip.focus_set()

    def _tes_koneksi(self):
        ip = self.entry_ip.get().strip()
        port_s = self.entry_port.get().strip()
        if not ip or not port_s.isdigit():
            self.lbl_status.configure(text="⚠  IP atau port tidak valid", text_color=C_YELLOW)
            return
        port = int(port_s)
        self.btn_tes.configure(text="⏳...", state="disabled")
        threading.Thread(target=self._connect_thread, args=(ip, port), daemon=True).start()

    def _connect_thread(self, ip, port):
        try:
            sukses, status_awal, pesan = ADBHelper.cek_dan_reconnect(ip, port)
        except Exception as e:
            sukses, status_awal, pesan = False, 'error', str(e)
        self.after(0, self._update_status, sukses, ip, port, pesan)

    def _update_status(self, sukses, ip, port, pesan=""):
        self.btn_tes.configure(state="normal", text="🔗 Tes")
        if sukses:
            self._connected = True
            self._port_baru = port
            self.lbl_status.configure(text=f"✅ Terhubung — {ip}:{port}", text_color=C_GREEN)
        else:
            self._connected = False
            self.lbl_status.configure(text=f"✖ Gagal: {pesan}", text_color=C_RED)

    def _konfirmasi(self):
        new_ip = self.entry_ip.get().strip()
        port_s = self.entry_port.get().strip()
        if not new_ip or not port_s.isdigit():
            messagebox.showwarning("Input Salah", "IP/Port tidak valid.")
            return
        if not self._connected:
            self.lbl_status.configure(text="⚠  Silakan tes koneksi terlebih dahulu", text_color=C_YELLOW)
            return
        self.on_confirm(new_ip, int(port_s))
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
#  DIALOG TAMBAH TV
# ═══════════════════════════════════════════════════════════════════════════════
class DialogTambahTV(ctk.CTkToplevel):
    def __init__(self, master, nomor_tv, on_confirm, on_close_cb, daftar_grup=None):
        super().__init__(master)
        self.title(f"Tambah TV #{nomor_tv}")
        self.geometry("420x620")
        self.configure(fg_color=C_BG)
        self.transient(master)
        self.resizable(False, False)
        self.nomor_tv = nomor_tv
        self.on_confirm = on_confirm
        self.on_close_cb = on_close_cb
        self.connected = False
        self._confirmed = False
        self.mode_var = ctk.StringVar(value="Android TV 11+ (Pairing)")
        self.daftar_grup = daftar_grup or [NAMA_GRUP_DEFAULT]
        self.grup_var = ctk.StringVar(value=self.daftar_grup[0])
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()
        center_window(self, master, width=420, height=620)
        self.after(50, self.grab_set)

    def _build(self):
        ctk.CTkLabel(self, text=f"📺  Tambah TV #{self.nomor_tv}",
                     font=FONT_TITLE, text_color=C_ACCENT).pack(pady=(18, 2))
        ctk.CTkLabel(self, text="Masukkan IP & Port TV lalu tes koneksi ADB",
                     font=FONT_BODY, text_color=C_MUTED).pack(pady=(0, 4))

        ctk.CTkButton(self, text="❓  Cara cek versi Android di TV", height=26,
                      fg_color="transparent", hover_color=C_BTN,
                      border_width=1, border_color=C_MUTED,
                      font=FONT_SMALL, text_color=C_MUTED,
                      command=self._info_cek_versi).pack(pady=(0, 8))

        # ── PILIH JENIS ANDROID TV ────────────────────────────────────────────
        mode_f = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=10)
        mode_f.pack(fill="x", padx=24, pady=(0, 8))
        ctk.CTkLabel(mode_f, text="Pilih Versi Android TV", font=FONT_LABEL,
                     text_color=C_MUTED).pack(anchor="w", padx=14, pady=(10, 4))
        self.seg_mode = ctk.CTkSegmentedButton(
            mode_f,
            values=["Android TV 11+ (Pairing)", "Android TV 10 ↓ (Langsung)"],
            variable=self.mode_var,
            font=FONT_SMALL,
            selected_color=C_ACCENT2, selected_hover_color="#5A0FCC",
            unselected_color=C_BTN, unselected_hover_color=C_BORDER,
            command=lambda v: self._update_mode_ui())
        self.seg_mode.pack(fill="x", padx=14, pady=(0, 6))

        self.lbl_mode_info = ctk.CTkLabel(mode_f, text="", font=FONT_SMALL,
                                           text_color=C_MUTED, justify="left", wraplength=380)
        self.lbl_mode_info.pack(anchor="w", padx=14, pady=(0, 10))

        # ── PILIH GRUP TARIF (PS3/PS4/dll) ────────────────────────────────────
        grup_f = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=10)
        grup_f.pack(fill="x", padx=24, pady=(0, 8))
        ctk.CTkLabel(grup_f, text="🏷  Grup Tarif (menentukan harga & Main Bebas)",
                     font=FONT_LABEL, text_color=C_MUTED).pack(anchor="w", padx=14, pady=(10, 4))
        self.opt_grup = ctk.CTkOptionMenu(
            grup_f, values=self.daftar_grup, variable=self.grup_var,
            fg_color=C_BTN, button_color=C_ACCENT2, button_hover_color="#5A0FCC",
            text_color=C_TEXT, font=FONT_BODY, dropdown_font=FONT_BODY,
            dropdown_fg_color=C_CARD, dropdown_text_color=C_TEXT)
        self.opt_grup.pack(fill="x", padx=14, pady=(0, 10))

        nama_f = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=10)
        nama_f.pack(fill="x", padx=24, pady=4)
        ctk.CTkLabel(nama_f, text="Nama Kota / Label TV",
                     font=FONT_LABEL, text_color=C_MUTED).pack(anchor="w", padx=14, pady=(8, 2))
        self.entry_nama = ctk.CTkEntry(nama_f, placeholder_text=f"Contoh: KOTA {self.nomor_tv}",
                                        fg_color=C_BTN, text_color=C_TEXT,
                                        border_color=C_BORDER, font=FONT_BODY, height=34)
        self.entry_nama.pack(fill="x", padx=14, pady=(0, 10))
        ip_f = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=10)
        ip_f.pack(fill="x", padx=24, pady=4)
        ctk.CTkLabel(ip_f, text="IP Address  &  Port ADB",
                     font=FONT_LABEL, text_color=C_MUTED).pack(anchor="w", padx=14, pady=(8, 2))
        ip_row = ctk.CTkFrame(ip_f, fg_color="transparent")
        ip_row.pack(fill="x", padx=14, pady=(0, 10))
        self.entry_ip = ctk.CTkEntry(ip_row, placeholder_text="192.168.1.xxx",
                                      fg_color=C_BTN, text_color=C_ACCENT,
                                      border_color=C_BORDER, font=("Consolas", 13, "bold"), height=34)
        self.entry_ip.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkLabel(ip_row, text=":", font=("Consolas", 16, "bold"), text_color=C_MUTED).pack(side="left")
        self.entry_port = ctk.CTkEntry(ip_row, placeholder_text="Port",
                                        fg_color=C_BTN, text_color=C_YELLOW,
                                        border_color=C_BORDER, font=("Consolas", 13, "bold"),
                                        height=34, width=90)
        self.entry_port.pack(side="left", padx=(6, 8))
        self.entry_port.insert(0, str(DEFAULT_PORT))
        self.btn_tes = ctk.CTkButton(ip_row, text="🔗 Tes", width=72, height=34,
                                      fg_color=C_BTN, border_width=1, border_color=C_GREEN,
                                      font=FONT_LABEL, text_color=C_GREEN,
                                      command=self._tes_koneksi)
        self.btn_tes.pack(side="left")
        self.btn_pairing = ctk.CTkButton(
            self, text="📡  TV minta kode pairing? (Android TV 11+)", height=30,
            fg_color=C_BTN, border_width=1, border_color=C_ACCENT,
            font=FONT_SMALL, text_color=C_ACCENT,
            command=self._buka_pairing)
        self.btn_pairing.pack(fill="x", padx=24, pady=(8, 4))
        self.lbl_status = ctk.CTkLabel(self, text="⬤  Belum diuji",
                                        font=FONT_BODY, text_color=C_MUTED)
        self.lbl_status.pack(pady=6)
        btn_f = ctk.CTkFrame(self, fg_color="transparent")
        btn_f.pack(pady=6)
        self.btn_konfirmasi = ctk.CTkButton(btn_f, text="✅  Tambahkan TV", width=160, height=36,
                                             fg_color=C_ACCENT2, font=FONT_SUB, text_color="white",
                                             state="disabled", command=self._konfirmasi)
        self.btn_konfirmasi.pack(side="left", padx=8)
        ctk.CTkButton(btn_f, text="✖  Batal", width=100, height=36,
                      fg_color=C_RED, font=FONT_SUB, text_color="white",
                      command=self._on_close).pack(side="left", padx=8)

        self._update_mode_ui()

    def _info_cek_versi(self):
        messagebox.showinfo(
            "❓ Cara Cek Versi Android di TV",
            "1️⃣  Buka Pengaturan TV\n"
            "2️⃣  Pilih Preferensi Perangkat (Device Preferences) → Tentang (About)\n"
            "3️⃣  Lihat baris 'Versi Android' / 'Android TV OS version'\n\n"
            "📌  Android 11 ke atas  → pilih mode 'Android TV 11+ (Pairing)'\n"
            "     TV akan minta kode pairing 6 digit, lalu connect otomatis.\n\n"
            "📌  Android 10 ke bawah  → pilih mode 'Android TV 10 ↓ (Langsung)'\n"
            "     Tidak perlu pairing, cukup aktifkan Debugging Jaringan/USB lalu\n"
            "     langsung connect ke IP TV di port 5555.")

    def _update_mode_ui(self):
        mode = self.mode_var.get()
        if mode.startswith("Android TV 11"):
            self.lbl_mode_info.configure(
                text="🔐  Perlu PAIRING dulu (sekali saja). Di TV: Pengaturan → Opsi "
                     "Developer → Wireless Debugging → 'Pair device with pairing code'. "
                     "Klik tombol pairing di bawah, atau langsung Tes jika sudah pernah di-pair.",
                text_color=C_ACCENT)
            self.btn_pairing.pack(fill="x", padx=24, pady=(8, 4))
        else:
            self.lbl_mode_info.configure(
                text="🔌  LANGSUNG tanpa pairing. Di TV: Pengaturan → Preferensi Perangkat → "
                     "Tentang → tap 'Build' 7x untuk aktifkan Mode Pengembang → Opsi Pengembang "
                     "→ aktifkan 'ADB Debugging' / 'Network debugging'. Port default tetap 5555.",
                text_color=C_GREEN)
            self.btn_pairing.pack_forget()
            if self.entry_port.get().strip() in ("", str(DEFAULT_PORT)):
                self.entry_port.delete(0, "end")
                self.entry_port.insert(0, str(DEFAULT_PORT))

    def _buka_pairing(self):
        ip_awal = self.entry_ip.get().strip()
        def on_pair_done(ip, port):
            self.entry_ip.delete(0, "end"); self.entry_ip.insert(0, ip)
            self.entry_port.delete(0, "end"); self.entry_port.insert(0, str(port))
            self.connected = True; self._port_valid = port
            self.lbl_status.configure(text=f"● PAIRED & TERHUBUNG  {ip}:{port}", text_color=C_GREEN)
            self.btn_konfirmasi.configure(state="normal")
        DialogPairing(self.winfo_toplevel(), ip_awal=ip_awal, on_confirm=on_pair_done)

    def _get_port(self):
        raw = self.entry_port.get().strip()
        if raw.isdigit():
            p = int(raw)
            if 1 <= p <= 65535:
                return p
        return None

    def _tes_koneksi(self):
        ip = self.entry_ip.get().strip()
        port = self._get_port()
        if not ip or port is None:
            self.lbl_status.configure(text="⚠  Isi IP & Port dengan benar", text_color=C_YELLOW)
            return
        self.btn_tes.configure(text="⏳...", state="disabled")
        self.lbl_status.configure(text=f"⬤  Menghubungkan ke {ip}:{port}...", text_color=C_YELLOW)
        threading.Thread(target=self._connect_thread, args=(ip, port), daemon=True).start()

    def _connect_thread(self, ip, port):
        sukses, pesan = ADBHelper.connect(ip, port)
        if sukses:
            status, _ = ADBHelper.status_untuk_ip(ip, port)
            if status != "device":
                sukses = False
                pesan = "Unauthorized — terima dialog ADB di TV" if status == "unauthorized" else f"Status: {status}"
        self.after(0, self._update_status, sukses, ip, port, pesan)

    def _update_status(self, sukses, ip, port, pesan=""):
        self.btn_tes.configure(state="normal", text="🔗 Tes")
        if sukses:
            self.connected = True; self._port_valid = port
            self.lbl_status.configure(text=f"● TERHUBUNG  {ip}:{port}", text_color=C_GREEN)
            self.btn_konfirmasi.configure(state="normal")
        else:
            self.connected = False
            mode = self.mode_var.get()
            extra = ""
            if mode.startswith("Android TV 10"):
                extra = "\n(Pastikan 'ADB Debugging/Network debugging' sudah aktif di TV)"
            self.lbl_status.configure(text=f"● GAGAL  {pesan}{extra}", text_color=C_RED, wraplength=380)
            self.btn_konfirmasi.configure(state="disabled")

    def _konfirmasi(self):
        if not self.connected: return
        ip = self.entry_ip.get().strip()
        nama = self.entry_nama.get().strip() or f"KOTA {self.nomor_tv}"
        grup = self.grup_var.get() or NAMA_GRUP_DEFAULT
        self._confirmed = True
        self.on_confirm(ip, nama, self._port_valid, grup)
        self.destroy()

    def _on_close(self):
        if not self._confirmed: self.on_close_cb()
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
#  DIALOG TAMBAH PESANAN (MAKANAN/MINUMAN SAAT SESI BERJALAN)
# ═══════════════════════════════════════════════════════════════════════════════
class DialogTambahPesanan(ctk.CTkToplevel):
    """Dialog untuk tambah pesanan makanan/minuman saat sesi TV sedang berjalan."""
    def __init__(self, master, tv_label, on_confirm, makanan_data, minuman_data, pesanan_aktif=None):
        super().__init__(master)
        self.title(f"Tambah Pesanan — {tv_label}")
        self.geometry("380x460")
        self.configure(fg_color=C_BG)
        self.transient(master)
         
        self.tv_label = tv_label
        self.on_confirm = on_confirm
        self.makanan_data = makanan_data or {}
        self.minuman_data = minuman_data or {}
        self.pesanan_aktif = pesanan_aktif or {}
        self.order_qty = {}
         
        self._build()
        center_window(self, master, width=380, height=460)
        self.after(50, self.grab_set)
     
    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=12, pady=(12, 8))
        ctk.CTkLabel(hdr, text=f"🛒 Pesanan Tambahan — {self.tv_label}",
                     font=("Russo One", 13, "bold"), text_color=C_ACCENT).pack(anchor="w")
        ctk.CTkLabel(hdr, text="Pilih item untuk ditambahkan atau perbarui jumlah",
                     font=FONT_BODY, text_color=C_MUTED).pack(anchor="w")
        
        # Total display
        self.lbl_total = ctk.CTkLabel(self, text="Total Pesanan: Rp 0",
                                       font=("Russo One", 12, "bold"), text_color=C_YELLOW)
        self.lbl_total.pack(pady=(0, 8))
        
        # Scrollable content
        scroll = ctk.CTkScrollableFrame(self, fg_color=C_BG)
        scroll.pack(fill="both", expand=True, padx=12, pady=0)
        
        # Makanan section
        if self.makanan_data:
            self._build_menu_section(scroll, "🍔  MAKANAN", self.makanan_data)
        
        # Minuman section
        if self.minuman_data:
            self._build_menu_section(scroll, "🥤  MINUMAN", self.minuman_data)
        
        if not self.makanan_data and not self.minuman_data:
            ctk.CTkLabel(scroll, text="Tidak ada item tersedia",
                        font=FONT_BODY, text_color=C_MUTED).pack(pady=20)
        
        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=(8, 12))
        
        ctk.CTkButton(btn_frame, text="✅  TAMBAHKAN PESANAN",
                     fg_color=C_ACCENT2, hover_color=C_ACCENT,
                     font=("Russo One", 11, "bold"), height=44,
                     command=self._confirm).pack(fill="x", pady=(0, 6))
        ctk.CTkButton(btn_frame, text="✖  BATAL",
                     fg_color=C_RED, hover_color="#CC0033",
                     font=("Russo One", 10, "bold"), height=38,
                     command=self.destroy).pack(fill="x")
    
    def _build_menu_section(self, parent, title, menu_dict):
        """Build collapsible menu section."""
        section = ctk.CTkFrame(parent, fg_color="transparent")
        section.pack(fill="x", pady=6)
        
        # Header
        header = ctk.CTkFrame(section, fg_color=C_PANEL, corner_radius=8)
        header.pack(fill="x")
        ctk.CTkLabel(header, text=title,
                    font=("Russo One", 10, "bold"), text_color=C_ACCENT2).pack(anchor="w", padx=10, pady=8)
        
        # Content
        content = ctk.CTkFrame(section, fg_color=C_CARD, corner_radius=6)
        content.pack(fill="x", padx=4, pady=(0, 4))
        
        for nama, harga in menu_dict.items():
            row = ctk.CTkFrame(content, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=4)
            
            # Item name & price
            ctk.CTkLabel(row, text=f"{nama}  •  {fmt_rp(harga)}",
                        font=FONT_LABEL, text_color=C_TEXT, anchor="w").pack(side="left", fill="x", expand=True)
            
            # Qty control
            var = ctk.IntVar(value=self.pesanan_aktif.get(nama, 0))
            self.order_qty[nama] = var
            
            ctk.CTkButton(row, text="−", width=24, height=24, fg_color=C_BTN, hover_color=C_RED,
                         font=("Consolas", 11, "bold"),
                         command=lambda v=var: (v.set(max(0, v.get()-1)), self._update_total())
                         ).pack(side="left", padx=2)
            ctk.CTkLabel(row, textvariable=var, width=24,
                        font=FONT_LABEL, text_color=C_ACCENT).pack(side="left")
            ctk.CTkButton(row, text="+", width=24, height=24, fg_color=C_BTN, hover_color=C_GREEN,
                         font=("Consolas", 11, "bold"),
                         command=lambda v=var: (v.set(v.get()+1), self._update_total())
                         ).pack(side="left", padx=2)
    
    def _update_total(self):
        """Update total pesanan."""
        all_menu = {**self.makanan_data, **self.minuman_data}
        total = sum(all_menu.get(nm, 0) * v.get() for nm, v in self.order_qty.items())
        self.lbl_total.configure(text=f"Total Pesanan: {fmt_rp(total)}")
    
    def _confirm(self):
        """Confirm and return new order data."""
        pesanan_baru = {nm: v.get() for nm, v in self.order_qty.items() if v.get() > 0}
        self.on_confirm(pesanan_baru)
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
#  DIALOG PAKET + PESANAN
# ═══════════════════════════════════════════════════════════════════════════════
class DialogPaket(ctk.CTkToplevel):
    def __init__(self, master, tv_label, on_confirm, paket_data, makanan_data, minuman_data, nama_grup="Reguler", for_warnet=False):
        self.for_warnet = for_warnet
        super().__init__(master)
        self.title(f"Paket & Pesanan — {tv_label}")
        self.geometry("460x560")  # Lebih kecil & compact
        self.configure(fg_color=C_BG)
        self.transient(master)
         
        self.on_confirm   = on_confirm
        self.tv_label     = tv_label
        self.paket_data   = paket_data or {"Paket Default": {"harga": 50000, "menit": 60}}
        self.makanan_data = makanan_data or {}
        self.minuman_data = minuman_data or {}
        self.nama_grup    = nama_grup
        self.paket_var    = ctk.StringVar(value=list(self.paket_data.keys())[0])
        self.pesanan_qty  = {}
        
        # State untuk collapse/expand
        self.expanded_groups = {"paket": True, "makanan": False, "minuman": False}
        
        self._build()
        center_window(self, master, width=460, height=560)
        self.after(50, self.grab_set)
    
    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=12, pady=(12, 2))
        ctk.CTkLabel(hdr, text=f"📺  {self.tv_label}",
                     font=("Russo One", 14, "bold"), text_color=C_ACCENT).pack(anchor="w")
        ctk.CTkLabel(hdr, text=f"🏷 {self.nama_grup}  •  Total: ",
                     font=("Courier New", 9), text_color=C_MUTED).pack(anchor="w")
        
        # Total display inline
        self.lbl_total = ctk.CTkLabel(self, text="Rp 0",
                                       font=("Russo One", 13, "bold"), text_color=C_YELLOW)
        self.lbl_total.pack(pady=(0, 8))
        
        # Scrollable content - HANYA PAKET (makanan/minuman di tab TV)
        scroll = ctk.CTkScrollableFrame(self, fg_color=C_BG)
        scroll.pack(fill="both", expand=True, padx=12, pady=0)
        
        # Grup 1: PAKET SAJA
        paket_title = "⏱  PAKET WARNET" if getattr(self, 'for_warnet', False) else "⏱  PAKET RENTAL PS"
        self._build_collapsible_group(
            scroll, "paket", paket_title,
            self._build_paket_content
        )
        
        # BUTTONS — paling bawah
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=(8, 12))
        
        btn_mulai = ctk.CTkButton(btn_frame, text="✅  MULAI SESI",
                      fg_color=C_ACCENT2, hover_color=C_ACCENT,
                      font=("Russo One", 11, "bold"), height=44,
                      command=self._handle_mulai_sesi)
        btn_mulai.pack(fill="x", pady=(0, 6))
        
        ctk.CTkButton(btn_frame, text="✖  BATAL",
                      fg_color=C_RED, hover_color="#CC0033",
                      font=("Russo One", 10, "bold"), height=38,
                      command=self.destroy).pack(fill="x")
        
        self._update_total()
    
    def _build_collapsible_group(self, parent, group_id, title, content_builder):
        """Buat collapsible group dengan header dan content."""
        group_container = ctk.CTkFrame(parent, fg_color="transparent")
        group_container.pack(fill="x", pady=4)
        
        # Header dengan toggle
        header = ctk.CTkFrame(group_container, fg_color=C_PANEL, corner_radius=8)
        header.pack(fill="x")
        header.bind("<Button-1>", lambda e: self._toggle_group(group_id, content_frame, header_btn))
        
        header_btn = ctk.CTkButton(
            header, text=f"{'▼' if self.expanded_groups[group_id] else '▶'}  {title}",
            fg_color="transparent", hover_color=C_CARD,
            font=("Russo One", 10, "bold"), text_color=C_ACCENT2,
            anchor="w", width=450
        )
        header_btn.pack(fill="x", padx=10, pady=8)
        header_btn.bind("<Button-1>", lambda e: self._toggle_group(group_id, content_frame, header_btn))
        
        # Content frame
        content_frame = ctk.CTkFrame(group_container, fg_color="transparent")
        if self.expanded_groups[group_id]:
            content_frame.pack(fill="x", padx=2, pady=(0, 4))
            content_builder(content_frame)
        
        # Store reference untuk toggle
        group_container.content_frame = content_frame
        group_container.header_btn = header_btn
    
    def _toggle_group(self, group_id, content_frame, header_btn):
        """Toggle expand/collapse untuk group."""
        self.expanded_groups[group_id] = not self.expanded_groups[group_id]
        
        if self.expanded_groups[group_id]:
            # Expand
            content_frame.pack(fill="x", padx=2, pady=(0, 4))
            header_btn.configure(text=header_btn.cget("text").replace("▶", "▼"))
        else:
            # Collapse
            content_frame.pack_forget()
            btn_text = header_btn.cget("text").replace("▼", "▶")
            header_btn.configure(text=btn_text)
    
    def _build_paket_content(self, parent):
        """Build paket options inside collapsible group."""
        cf = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=6)
        cf.pack(fill="x", padx=8, pady=4)
        
        for nama, info in self.paket_data.items():
            harga = info.get("harga", 0)
            menit = info.get("menit", 0)
            
            row = ctk.CTkFrame(cf, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=3)
            
            color = C_GREEN if nama == "Main Bebas" else C_ORANGE if nama == "Reguler" else C_TEXT
            rb = ctk.CTkRadioButton(row, text=nama, variable=self.paket_var, value=nama,
                                     font=FONT_LABEL, text_color=color,
                                     fg_color=C_ACCENT, hover_color=C_ACCENT2,
                                     command=self._update_total)
            rb.pack(side="left")
            
            if nama == "Main Bebas":
                tarif_menit = hitung_tarif_per_menit(self.paket_data)
                harga_txt = f"≈ {fmt_rp(tarif_menit)}/menit"
                durasi_txt = "Bebas"
            else:
                harga_txt = "Sesuai Durasi" if harga == 0 and menit == 0 else fmt_rp(harga)
                durasi_txt = fmt_durasi(menit) if menit > 0 else "—"
            
            ctk.CTkLabel(row, text=f"{harga_txt} • {durasi_txt}", font=FONT_LABEL,
                        text_color=C_MUTED).pack(side="right")
    
    def _build_menu_content(self, parent, menu_dict):
        """Build menu items (makanan/minuman) inside collapsible group."""
        cf = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=6)
        cf.pack(fill="x", padx=8, pady=4)
        
        if not menu_dict:
            ctk.CTkLabel(cf, text="(Tidak ada item)", font=FONT_SMALL, text_color=C_MUTED).pack(pady=8)
            return
        
        for nama, harga in menu_dict.items():
            row = ctk.CTkFrame(cf, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=3)
            
            ctk.CTkLabel(row, text=f"{nama}  •  {fmt_rp(harga)}",
                        font=FONT_LABEL, text_color=C_TEXT, anchor="w").pack(side="left", fill="x", expand=True)
            
            var = ctk.IntVar(value=0)
            self.pesanan_qty[nama] = var
            
            ctk.CTkButton(row, text="−", width=24, height=24, fg_color=C_BTN, hover_color=C_RED,
                         font=("Consolas", 11, "bold"),
                         command=lambda v=var: (v.set(max(0, v.get()-1)), self._update_total())
                         ).pack(side="left", padx=2)
            ctk.CTkLabel(row, textvariable=var, width=24,
                        font=FONT_LABEL, text_color=C_ACCENT).pack(side="left")
            ctk.CTkButton(row, text="+", width=24, height=24, fg_color=C_BTN, hover_color=C_GREEN,
                         font=("Consolas", 11, "bold"),
                         command=lambda v=var: (v.set(v.get()+1), self._update_total())
                         ).pack(side="left", padx=2)

    def _update_total(self):
        """Update total calculation."""
        info = self.paket_data.get(self.paket_var.get(), {})
        harga_paket = info.get("harga", 0)
        menit_paket = info.get("menit", 0)
        all_menu = {**self.makanan_data, **self.minuman_data}
        total_pesanan = sum(all_menu.get(nm, 0) * v.get() for nm, v in self.pesanan_qty.items())
        
        nm = self.paket_var.get()
        if nm == "Main Bebas":
            tarif_menit = hitung_tarif_per_menit(self.paket_data)
            total_txt = f"≈ {fmt_rp(tarif_menit)}/menit"
            if total_pesanan > 0:
                total_txt += f" + {fmt_rp(total_pesanan)}"
        else:
            total = harga_paket + total_pesanan
            total_txt = fmt_rp(total)
        
        self.lbl_total.configure(text=total_txt)

    def _on_mulai_sesi(self):
        """Handle MULAI SESI button click - simplified."""
        print(f"[DEBUG] _on_mulai_sesi() called")
        try:
            paket_nm = self.paket_var.get()
            print(f"[DEBUG] Paket selected: {paket_nm}")
            info = self.paket_data.get(paket_nm, {})
            paket_harga = info.get("harga", 0)
            paket_menit = info.get("menit", 0)
            pesanan = {}  # Kosong - makanan/minuman di tab TV
            total = paket_harga
            
            print(f"[DEBUG] Calling on_confirm with: {paket_nm}, {paket_harga}, {paket_menit}")
            self.on_confirm(paket_nm, paket_harga, paket_menit, pesanan, total)
            print(f"[DEBUG] Destroying dialog")
            self.destroy()
        except Exception as e:
            print(f"[ERROR] Exception in _on_mulai_sesi: {e}")
            import traceback
            traceback.print_exc()
    
    def _handle_mulai_sesi(self):
        """Actual handler - called via button command."""
        if messagebox.askyesno("Konfirmasi", "Mulai sesi sekarang?", parent=self):
            self._confirm()
    
    def _confirm(self):
        """Confirm order."""
        try:
            paket_nm    = self.paket_var.get()
            info        = self.paket_data.get(paket_nm, {})
            paket_harga = info.get("harga", 0)
            paket_menit = info.get("menit", 0)
            all_menu    = {**self.makanan_data, **self.minuman_data}
            pesanan     = {nm: v.get() for nm, v in self.pesanan_qty.items() if v.get() > 0}
            
            # Hitung total pesanan dengan aman (hindari KeyError)
            total_pesanan = sum(all_menu.get(nm, 0) * qty for nm, qty in pesanan.items())
            
            if paket_nm == "Main Bebas":
                # Total biaya waktu belum diketahui sampai pemain selesai main.
                # Yang dikirim di sini hanya total pesanan tambahan (makanan/minuman).
                total = total_pesanan
            else:
                total = paket_harga + total_pesanan
            
            self.on_confirm(paket_nm, paket_harga, paket_menit, pesanan, total)
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Terjadi kesalahan: {str(e)}")


def hitung_tarif_per_menit(paket_data):
    """
    Tarif per menit untuk Main Bebas, diturunkan dari harga & durasi
    paket acuan (default: '1 Jam'). Kalau paket acuan tidak ada / durasinya 0,
    fallback ke paket non-Main Bebas / non-Reguler pertama yang punya durasi > 0.
    """
    acuan = paket_data.get(PAKET_ACUAN_BEBAS)
    if acuan and acuan.get("menit", 0) > 0:
        return acuan["harga"] / acuan["menit"]
    for nama, info in paket_data.items():
        if nama in ("Main Bebas",) :
            continue
        if info.get("menit", 0) > 0:
            return info["harga"] / info["menit"]
    return 0


# ═══════════════════════════════════════════════════════════════════════════════
#  DIALOG TAMBAH WARNET
# ═══════════════════════════════════════════════════════════════════════════════
class DialogTambahWarnet(ctk.CTkToplevel):
    def __init__(self, master, on_confirm, on_close_cb, daftar_grup=None, lock_group=False):
        super().__init__(master)
        self.title("Tambah Kursi Warnet")
        self.geometry("420x260")
        self.configure(fg_color=C_BG)
        self.transient(master)
        self.resizable(False, False)
        self.on_confirm = on_confirm
        self.on_close_cb = on_close_cb
        self.daftar_grup = daftar_grup or [NAMA_GRUP_DEFAULT]
        # lock_group: jika True, pengguna tidak dapat mengganti grup saat menambah kursi (dikunci ke grup warnet)
        self.lock_group = bool(lock_group)
        self.grup_var = ctk.StringVar(value=self.daftar_grup[0])
        self._confirmed = False
        self._build()
        center_window(self, master, width=420, height=260)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self.grab_set)

    def _build(self):
        ctk.CTkLabel(self, text="➕ Tambah Kursi Warnet", font=FONT_TITLE, text_color=C_ACCENT).pack(pady=(18, 8))
        ctk.CTkLabel(self, text="Masukkan nama kursi dan pilih grup tarif:", font=FONT_BODY, text_color=C_MUTED).pack(pady=(0, 8))

        row = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=10)
        row.pack(fill="x", padx=18, pady=(0, 8))
        ctk.CTkLabel(row, text="Nama:", width=90, anchor="w", font=FONT_LABEL, text_color=C_MUTED).pack(side="left", padx=(10, 0))
        self.entry_nama = ctk.CTkEntry(row, fg_color=C_BTN, text_color=C_ACCENT,
                                      border_color=C_BORDER, font=("Consolas", 12, "bold"), height=34)
        self.entry_nama.pack(side="left", fill="x", expand=True, padx=(6, 10))

        grp_row = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=10)
        grp_row.pack(fill="x", padx=18, pady=(0, 8))
        ctk.CTkLabel(grp_row, text="Grup:", width=90, anchor="w", font=FONT_LABEL, text_color=C_MUTED).pack(side="left", padx=(10, 0))
        self.opt_grup = ctk.CTkOptionMenu(
            grp_row,
            values=self.daftar_grup,
            variable=self.grup_var,
            fg_color=C_BTN,
            button_color=C_ACCENT2,
            button_hover_color="#5A0FCC",
            text_color=C_TEXT,
            font=FONT_BODY,
            dropdown_font=FONT_BODY,
            dropdown_fg_color=C_CARD,
            dropdown_text_color=C_TEXT,
        )
        self.opt_grup.pack(side="left", fill="x", expand=True, padx=(6, 10))
        # Jika dialog dipanggil untuk menambah warnet dan harus dikunci ke grup warnet,
        # matikan kemampuan mengganti grup di dialog ini (prevent accidental assignment ke grup lain)
        if getattr(self, 'lock_group', False):
            try:
                self.opt_grup.configure(state="disabled")
            except Exception:
                # CTkOptionMenu kadang tidak mendukung state config pada versi tertentu; sebagai fallback,
                # sembunyikan dropdown button sehingga user tidak bisa ubah pilihan.
                try:
                    self.opt_grup.pack_forget()
                    lbl = ctk.CTkLabel(grp_row, textvariable=self.grup_var, font=FONT_BODY, text_color=C_TEXT)
                    lbl.pack(side="left", fill="x", expand=True, padx=(6,10))
                except Exception:
                    pass

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=18, pady=(0, 14))
        ctk.CTkButton(btn_frame, text="✅ Tambah Kursi", fg_color=C_ACCENT2,
                      hover_color=C_ACCENT, font=FONT_SUB, text_color="white",
                      command=self._on_confirm).pack(side="left", fill="x", expand=True, padx=(0, 6), pady=0, ipady=6)
        ctk.CTkButton(btn_frame, text="✖ Batal", fg_color=C_RED,
                      hover_color="#FF5C5C", font=FONT_SUB, text_color="white",
                      command=self._on_close).pack(side="left", fill="x", expand=True, padx=(6, 0), pady=0, ipady=6)

    def _on_confirm(self):
        nama = self.entry_nama.get().strip()
        grup = self.grup_var.get().strip() if self.grup_var.get() else ""
        if not nama:
            messagebox.showwarning("Input Salah", "Nama kursi wajib diisi.", parent=self)
            return
        if not grup:
            messagebox.showwarning("Input Salah", "Pilih grup tarif untuk kursi warnet.", parent=self)
            return
        self._confirmed = True
        self.on_confirm(nama, grup)
        self.destroy()

    def _on_close(self):
        if not self._confirmed and self.on_close_cb:
            self.on_close_cb()
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
#  KARTU TV
# ═══════════════════════════════════════════════════════════════════════════════
class KartuTV(ctk.CTkFrame):
    def __init__(self, master, nomor, ip, port, label_tv, on_transaksi,
                 get_paket_data, get_makanan_data, get_minuman_data,
                 get_semua_kartu, nama_grup="Reguler", is_first=False,
                 get_daftar_grup=None, on_ganti_grup=None, on_hapus=None, **kwargs):
        super().__init__(master, fg_color=C_CARD, corner_radius=8,
                         border_width=1, border_color=C_BORDER, **kwargs)
        self.nomor        = nomor
        self.ip           = ip
        self.port         = port
        self.label_tv     = label_tv
        self.on_transaksi = on_transaksi
        self.nama_grup        = nama_grup   # grup tarif (PS3/PS4/dll) milik TV ini
        self.get_paket_data   = get_paket_data   # fungsi -> dict paket utk grup ini
        self.get_makanan_data = get_makanan_data
        self.get_minuman_data = get_minuman_data
        self.get_semua_kartu  = get_semua_kartu   # fungsi -> list semua KartuTV di app
        self.get_daftar_grup  = get_daftar_grup or (lambda: [nama_grup])  # fungsi -> list nama grup tersedia
        self.on_ganti_grup    = on_ganti_grup     # callback(kartu, grup_baru) saat user ganti grup TV ini
        self.on_hapus         = on_hapus          # callback(kartu) saat user ingin hapus TV
        self.is_first     = is_first
        self.is_on        = False
        self.connected    = True

        # ── Status sesi bermain ──────────────────────────────────────────────
        self.paket_aktif   = None     # nama paket yang sedang berjalan, None jika kosong
        self.sisa_waktu    = 0        # detik tersisa (untuk paket berwaktu)
        self.is_bebas      = False    # True jika sesi ini Main Bebas
        self.menit_dipakai_awal = 0   # offset menit (dipakai saat hasil pindah TV Main Bebas)
        self.waktu_mulai   = None     # datetime mulai sesi (acuan hitung Main Bebas)
        self.pesanan_aktif = {}       # pesanan tambahan (makanan/minuman) sesi berjalan
        self.biaya_pesanan = 0        # total biaya pesanan tambahan sesi berjalan
        self.paket_harga_tetap = 0    # harga tetap utk paket berwaktu non-bebas
        self._timer_job    = None
        self._last_transaction_item = None
        self._warning_blink_on = False

        self._build()
 
    def _build(self):
        # Header with TV label and IP block
        hdr = ctk.CTkFrame(self, fg_color=C_ACCENT2, corner_radius=10)
        hdr.pack(fill="x", padx=3, pady=(2, 1))
 
        display_label = self.label_tv
        if display_label.upper().startswith("KOTA "):
            display_label = display_label[5:]
 
        top_bar = ctk.CTkFrame(hdr, fg_color=C_ACCENT2)
        top_bar.pack(fill="x", padx=4, pady=(6, 4))
        self.lbl_tv_name = ctk.CTkLabel(top_bar, text=display_label,
                                         font=("Russo One", 11, "bold"), text_color="white")
        self.lbl_tv_name.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.btn_ganti_nama = ctk.CTkButton(top_bar, text="Nama", width=76, height=28,
                                            fg_color=C_BTN, hover_color=C_BORDER,
                                            border_width=1, border_color=C_ACCENT2,
                                            font=("Russo One", 8, "bold"), text_color=C_ACCENT2,
                                            command=self._buka_ganti_nama)
        self.btn_ganti_nama.pack(side="right", padx=(0, 4))
 
        self.btn_hapus = ctk.CTkButton(top_bar, text="✖", width=36, height=28,
                                       fg_color=C_RED, hover_color="#FF5C5C",
                                       border_width=1, border_color=C_RED,
                                       font=("Russo One", 8, "bold"), text_color="white",
                                       command=self._confirm_hapus)
        self.btn_hapus.pack(side="right", padx=(0, 8))
 
 
        # Status row: HIDEN/Reguler indicators
        st_row = ctk.CTkFrame(self, fg_color="transparent")
        st_row.pack(fill="x", padx=3, pady=(0, 4))
        self.lbl_power = ctk.CTkLabel(st_row, text="● HIDEN", font=("Courier New", 10, "bold"),
                                       text_color=C_GREEN)
        self.lbl_power.pack(side="left", padx=4)
        self.lbl_grup = ctk.CTkLabel(st_row, text="↻ Reguler", font=("Courier New", 10, "bold"),
                                      text_color=C_ACCENT2, cursor="hand2")
        self.lbl_grup.pack(side="left", padx=4)
        self.lbl_grup.bind("<Button-1>", lambda e: self._buka_ganti_grup())
        self.lbl_paket = ctk.CTkLabel(st_row, text="—", font=("Courier New", 8), text_color=C_MUTED)
        self.lbl_paket.pack(side="right", padx=4)
 
        # Timer display
        self.lbl_timer = ctk.CTkLabel(self, text="00:00:00",
                                       font=("Russo One", 20, "bold"), text_color=C_ACCENT2)
        self.lbl_timer.pack(pady=(2, 2))
 
        # Estimasi biaya berjalan (khusus Main Bebas)
        self.lbl_estimasi = ctk.CTkLabel(self, text="", font=("Courier New", 8), text_color=C_YELLOW)
        self.lbl_estimasi.pack()
 
        # Button row
        r1 = ctk.CTkFrame(self, fg_color="transparent")
        r1.pack(pady=4, fill="x", padx=3)
        for i in range(5):
           r1.columnconfigure(i, weight=1, uniform="btnrow")

        self.btn_power = ctk.CTkButton(r1, text="⚡ PWR", height=34,
                                       fg_color=C_RED, hover_color="#FF6666",
                                       border_width=2, border_color=C_RED,
                                       font=("Courier New", 9, "bold"), text_color="white",
                                       command=self._toggle_power)
        self.btn_power.grid(row=0, column=0, sticky="nsew", padx=(0, 2))
 
        for idx, (txt, color, cmd) in enumerate([
            ("VOL+", C_GREEN, lambda: self._adb_action(lambda: ADBHelper.volume(self.ip, naik=True, port=self.port))),
            ("VOL−", C_YELLOW, lambda: self._adb_action(lambda: ADBHelper.volume(self.ip, naik=False, port=self.port))),
            ("HOME", C_ACCENT, lambda: self._adb_action(lambda: ADBHelper.home(self.ip, port=self.port))),
        ], start=1):
            ctk.CTkButton(r1, text=txt, height=34, fg_color=color,
                         hover_color="white" if color == C_ACCENT else None,
                         font=("Courier New", 9, "bold"), text_color="black" if color == C_ACCENT else "white",
                         border_width=1, border_color=color,
                         command=cmd).grid(row=0, column=idx, sticky="nsew", padx=2)
 
        self.btn_status = ctk.CTkButton(r1, text="ON", height=34,
                                       fg_color=C_BTN, border_width=1, border_color=C_GREEN,
                                       font=("Russo One", 9, "bold"), text_color=C_GREEN,
                                       command=self._cek_koneksi_adb)
        self.btn_status.grid(row=0, column=4, sticky="nsew", padx=(2, 0))
 
        # Action row: stop, shop, add time, IP, pindah TV
        r2 = ctk.CTkFrame(self, fg_color="transparent")
        r2.pack(pady=2, fill="x", padx=3)
        for i in range(5):
            r2.columnconfigure(i, weight=1, uniform="btnrow")
 
        self.btn_selesai = ctk.CTkButton(r2, text="SELESAI", height=34,
                                         fg_color=C_BTN, hover_color="#3A0000",
                                         border_width=1, border_color=C_RED,
                                         font=("Russo One", 9, "bold"), text_color=C_RED,
                                         state="disabled",
                                         command=self._klik_selesai)
        self.btn_selesai.grid(row=0, column=0, sticky="nsew", padx=(0, 2))
 
        self.btn_tambah_pesanan = ctk.CTkButton(r2, text="SHOP", height=34,
                                               fg_color=C_BTN, hover_color=C_ACCENT2,
                                               border_width=1, border_color=C_ACCENT,
                                               font=("Russo One", 9, "bold"), text_color=C_ACCENT,
                                               state="disabled",
                                               command=self._buka_tambah_pesanan)
        self.btn_tambah_pesanan.grid(row=0, column=1, sticky="nsew", padx=2)
 
        self.btn_tambah_waktu = ctk.CTkButton(r2, text="PAKET", height=34,
                                              fg_color=C_BTN, hover_color=C_ACCENT2,
                                              border_width=1, border_color=C_ACCENT2,
                                              font=("Russo One", 9, "bold"), text_color=C_ACCENT2,
                                              command=self._pilih_paket)
        self.btn_tambah_waktu.grid(row=0, column=2, sticky="nsew", padx=2)
 
        self.btn_ip = ctk.CTkButton(r2, text="IP", height=34,
                                    fg_color=C_BTN, hover_color=C_ACCENT2,
                                    border_width=1, border_color=C_ACCENT2,
                                    font=("Russo One", 9, "bold"), text_color=C_ACCENT2,
                                    command=self._buka_ganti_ip)
        self.btn_ip.grid(row=0, column=3, sticky="nsew", padx=2)
 
        self.btn_pindah_tv = ctk.CTkButton(r2, text="Pindah TV", height=34,
                                           fg_color=C_BTN, border_width=1, border_color=C_ACCENT2,
                                           font=("Russo One", 9, "bold"), text_color=C_ACCENT2,
                                           command=self._klik_pindah)
        self.btn_pindah_tv.grid(row=0, column=4, sticky="nsew", padx=(2, 0))

    # ── Util status sesi ─────────────────────────────────────────────────────
    def sesi_kosong(self):
        return self.paket_aktif is None

    def _buka_ganti_port(self):
        DialogGantiPort(self.winfo_toplevel(), self.label_tv, self.ip, self.port,
                        on_confirm=self._terapkan_port_baru)

    def _buka_ganti_ip(self):
        def _on_confirm(new_ip, new_port):
            try:
                self._terapkan_ip_baru(new_ip, new_port)
            except Exception:
                pass
        DialogGantiIP(self.winfo_toplevel(), self.label_tv, self.ip, self.port,
                      on_confirm=_on_confirm)
 
    def _buka_ganti_nama(self):
        dlg = ctk.CTkInputDialog(text="Nama TV baru:", title=f"✏️ Ganti Nama TV — {self.label_tv}")
        nama_baru = dlg.get_input()
        if not nama_baru:
            return
        nama_baru = nama_baru.strip()
        if not nama_baru:
            return
        lama = self.label_tv
        self.label_tv = nama_baru
        display_label = nama_baru
        if display_label.upper().startswith("KOTA "):
            display_label = display_label[5:]
        self.lbl_tv_name.configure(text=display_label)
        if hasattr(self, 'lbl_ip_footer'):
            self.lbl_ip_footer.configure(text=self.ip)
        AuditLogger.log(action="rename_tv", username="", status="success", details={"old": lama, "new": nama_baru})
 
    def _confirm_hapus(self):
        if messagebox.askyesno("Hapus TV", f"Hapus {self.label_tv} dari dashboard?"):
            if callable(self.on_hapus):
                self.on_hapus(self)
 
    def _terapkan_ip_baru(self, new_ip, new_port):
        self.ip = new_ip
        self.port = new_port
        try:
            if hasattr(self, 'lbl_port_info'):
                self.lbl_port_info.configure(text=f"Port {self.port}")
        except Exception:
            pass
        if hasattr(self, 'btn_status'):
            self.btn_status.configure(text="● ON", fg_color=C_GREEN, border_color=C_GREEN)

    def _buka_ganti_grup(self):
        if not self.sesi_kosong():
            messagebox.showwarning("⚠ Sesi Sedang Berjalan",
                                    "Selesaikan sesi yang sedang berjalan dulu sebelum "
                                    "mengganti grup tarif TV ini.")
            return
        daftar = self.get_daftar_grup()
        if not daftar:
            return
        dlg = ctk.CTkToplevel(self.winfo_toplevel())
        dlg.title(f"Ganti Grup Tarif — {self.label_tv}")
        dlg.geometry("420x160")
        dlg.configure(fg_color=C_BG)
        dlg.grab_set()
        dlg.resizable(False, False)
        ctk.CTkLabel(dlg, text=f"🏷  Grup Tarif untuk {self.label_tv}",
                     font=("Russo One", 13, "bold"), text_color=C_ACCENT).pack(pady=(20, 12))
        var_grup = ctk.StringVar(value=self.nama_grup if self.nama_grup in daftar else daftar[0])
        opt = ctk.CTkOptionMenu(dlg, values=daftar, variable=var_grup,
                                 fg_color=C_BTN, button_color=C_ACCENT2,
                                 button_hover_color="#5A0FCC", text_color=C_TEXT,
                                 font=("Courier New", 12), dropdown_font=("Courier New", 11),
                                 dropdown_fg_color=C_CARD, dropdown_text_color=C_TEXT)
        opt.pack(padx=25, pady=8, fill="x")

        def terapkan():
            grup_baru = var_grup.get()
            self.nama_grup = grup_baru
            self.lbl_grup.configure(text=f"🏷 {grup_baru}")
            if self.on_ganti_grup:
                self.on_ganti_grup(self, grup_baru)
            dlg.destroy()

        ctk.CTkButton(dlg, text="✅  TERAPKAN GRUP", height=40,
                      fg_color=C_ACCENT2, hover_color=C_ACCENT,
                      font=("Russo One", 12, "bold"), text_color="white",
                      command=terapkan).pack(pady=16, padx=25, fill="x")

    def _terapkan_port_baru(self, port_baru):
        self.port = port_baru
        if hasattr(self, 'btn_status'):
            self.btn_status.configure(text="● ON", fg_color=C_GREEN, border_color=C_GREEN)

    def _cek_koneksi_adb(self):
        if getattr(self, "_cek_busy", False): return
        self._cek_busy = True
        if hasattr(self, 'btn_status'):
            self.btn_status.configure(text="⏳ Memeriksa...", state="disabled")
        threading.Thread(target=self._cek_koneksi_thread, daemon=True).start()

    def _cek_koneksi_thread(self):
        sukses, status_awal, pesan = ADBHelper.cek_dan_reconnect(self.ip, self.port)
        self.after(0, self._cek_koneksi_selesai, sukses, status_awal, pesan)

    def _cek_koneksi_selesai(self, sukses, status_awal, pesan):
        self._cek_busy = False
        if hasattr(self, 'btn_status'):
            self.btn_status.configure(state="normal")
        if sukses:
            self.connected = True
            if hasattr(self, 'btn_status'):
                self.btn_status.configure(text="● ON", fg_color=C_GREEN, border_color=C_GREEN)
            messagebox.showinfo("✅ Koneksi ADB", f"TV: {self.label_tv}\n{pesan}")
        else:
            self.connected = False
            if hasattr(self, 'btn_status'):
                self.btn_status.configure(text="● OFF", fg_color=C_RED, border_color=C_RED)
            if messagebox.askyesno("⚠ Koneksi Gagal",
                                    f"TV: {self.label_tv}\n{pesan}\n\nBuka dialog Ganti Port?"):
                self._buka_ganti_port()

    def _toggle_power(self):
        self.is_on = not self.is_on
        if self.is_on:
            self.lbl_power.configure(text="📺 HIDUP", text_color=C_GREEN)
            self.btn_power.configure(fg_color="#3A0000")
        else:
            self.lbl_power.configure(text="📵 MATI", text_color=C_MUTED)
            self.btn_power.configure(fg_color=C_BTN)
        self._adb_action(lambda: ADBHelper.power_toggle(self.ip, port=self.port))

    def _adb_action(self, fn):
        def runner():
            ok, out, err = fn()
            color = C_GREEN if ok else C_RED
            self.after(0, lambda: self.btn_status.configure(
                text="● ON" if ok else "● ERR", fg_color=color, border_color=color))
        threading.Thread(target=runner, daemon=True).start()

    def _pilih_paket(self):
        DialogPaket(self.winfo_toplevel(), self.label_tv, self._on_paket_confirm,
                    self.get_paket_data(), self.get_makanan_data(), self.get_minuman_data(),
                    nama_grup=self.nama_grup)

    def _buka_tambah_pesanan(self):
        """Buka dialog untuk tambah pesanan makanan/minuman saat sesi berjalan."""
        if not self.paket_aktif:
            messagebox.showwarning("Tidak Ada Sesi", "Mulai sesi terlebih dahulu untuk memesan.")
            return
        
        # Buka DialogTambahPesanan untuk add order
        DialogTambahPesanan(self.winfo_toplevel(), self.label_tv, 
                           self._on_tambah_pesanan_confirm,
                           self.get_makanan_data(), self.get_minuman_data(),
                           pesanan_aktif=self.pesanan_aktif.copy())

    def _on_tambah_pesanan_confirm(self, pesanan_baru):
        """Callback saat user confirm tambah pesanan."""
        # Merge pesanan baru ke pesanan_aktif
        all_menu = {**self.get_makanan_data(), **self.get_minuman_data()}
        total_baru = 0
        
        for nama, qty in pesanan_baru.items():
            self.pesanan_aktif[nama] = qty
        
        # Hitung ulang total berdasarkan semua pesanan aktif
        total_baru = sum(all_menu.get(nama, 0) * qty for nama, qty in self.pesanan_aktif.items())
        total_semua = self.paket_harga_tetap + total_baru if not self.is_bebas else total_baru
        self.biaya_pesanan = total_baru
        
        # Update display
        if self.is_bebas:
            self.lbl_paket.configure(text=f"Main Bebas 🕹️ +Pesanan {fmt_rp(total_baru)}")
        else:
            self.lbl_paket.configure(text=f"{self.paket_aktif} | {fmt_rp(total_semua)}")

        # Update recorded transaction row if this fixed package session already has one.
        if not self.is_bebas and getattr(self, '_last_transaction_item', None):
            app = self.winfo_toplevel()
            item_id = self._last_transaction_item
            pesanan_str = ", ".join(f"{nm}×{qty}" for nm, qty in self.pesanan_aktif.items()) or "—"
            total_str = fmt_rp(total_semua)
            if hasattr(app, 'tree') and hasattr(app, '_tree_item_to_index'):
                idx = app._tree_item_to_index.get(item_id)
                if idx is not None and idx < len(app.riwayat_transaksi):
                    waktu = app.tree.item(item_id, 'values')[0] if app.tree.item(item_id, 'values') else datetime.now().strftime("%Y-%m-%d %H:%M")
                    updated_row = (waktu, app.current_user, self.label_tv, self.paket_aktif, pesanan_str, total_str)
                    app.riwayat_transaksi[idx] = updated_row
                    app.tree.item(item_id, values=updated_row)
                    if hasattr(app, '_refresh_riwayat_summary'):
                        app._refresh_riwayat_summary()

        app = self.winfo_toplevel()
        if hasattr(app, '_refresh_dashboard_total_pesanan'):
            app._refresh_dashboard_total_pesanan()

    def _on_paket_confirm(self, paket_nm, paket_harga, paket_menit, pesanan, total_pesanan):
        previous_session = not self.sesi_kosong()
        self.pesanan_aktif  = pesanan
        self.biaya_pesanan  = total_pesanan
        self.menit_dipakai_awal = 0

        if paket_nm == "Main Bebas":
            self.is_bebas    = True
            self.sisa_waktu  = 0
            self.waktu_mulai = datetime.now()
            self.paket_harga_tetap = 0
            self.paket_aktif = paket_nm
            self.lbl_paket.configure(text="Main Bebas 🕹️ (berjalan)", text_color=C_GREEN)
            self.lbl_timer.configure(text_color=C_YELLOW)
            self.lbl_estimasi.configure(text=f"Total berjalan: {fmt_rp(self.biaya_pesanan)}", text_color=C_YELLOW)
        else:
            self.is_bebas    = False
            self.paket_aktif = paket_nm
            if previous_session and self.paket_harga_tetap:
                self.sisa_waktu += paket_menit * 60
                self.paket_harga_tetap += paket_harga
            else:
                self.sisa_waktu  = paket_menit * 60
                self.paket_harga_tetap = paket_harga
            self.waktu_mulai = datetime.now()
            self.lbl_paket.configure(text=f"{paket_nm} | {fmt_rp(self.paket_harga_tetap + self.biaya_pesanan)}",
                                      text_color=C_YELLOW)
            self.lbl_timer.configure(text_color=C_ACCENT)

        if self._timer_job:
            self.after_cancel(self._timer_job)

        self.btn_selesai.configure(state="normal")
        self.btn_tambah_pesanan.configure(state="normal")
        self.btn_tambah_pesanan.configure(text="SHOP", fg_color=C_BTN, border_width=1,
                                          border_color=C_ACCENT2, text_color=C_ACCENT2)
        self.configure(fg_color="white")
        self._warning_blink_on = False

        if not self.is_bebas and self.sisa_waktu > 0:
            h, rem = divmod(self.sisa_waktu, 3600)
            m, s = divmod(rem, 60)
            self.lbl_timer.configure(text=f"{h:02d}:{m:02d}:{s:02d}")

        if self.is_bebas:
            self._tick_bebas()
        elif self.sisa_waktu > 0:
            self._tick_waktu()
        else:
            self.lbl_timer.configure(text="∞ BEBAS", text_color=C_GREEN)

        if not self.is_bebas:
            if self._last_transaction_item and previous_session:
                app = self.winfo_toplevel()
                item_id = self._last_transaction_item
                pesanan_str = ", ".join(f"{nm}×{qty}" for nm, qty in self.pesanan_aktif.items()) or "—"
                total_str = fmt_rp(self.paket_harga_tetap + self.biaya_pesanan)
                if hasattr(app, 'tree') and hasattr(app, '_tree_item_to_index'):
                    idx = app._tree_item_to_index.get(item_id)
                    if idx is not None and idx < len(app.riwayat_transaksi):
                        waktu = app.tree.item(item_id, 'values')[0] if app.tree.item(item_id, 'values') else datetime.now().strftime("%Y-%m-%d %H:%M")
                        updated_row = (waktu, app.current_user, self.label_tv, self.paket_aktif, pesanan_str, total_str)
                        app.riwayat_transaksi[idx] = updated_row
                        app.tree.item(item_id, values=updated_row)
                        if hasattr(app, '_refresh_riwayat_summary'):
                            app._refresh_riwayat_summary()
            else:
                self._last_transaction_item = self.on_transaksi(
                    self.label_tv, paket_nm, pesanan, self.paket_harga_tetap + total_pesanan)
        else:
            self._last_transaction_item = None

        app = self.winfo_toplevel()
        if hasattr(app, '_refresh_dashboard_total_pesanan'):
            app._refresh_dashboard_total_pesanan()

    # ── Timer paket berwaktu (mundur) ───────────────────────────────────────
    def _tick_waktu(self):
        if self.sisa_waktu > 0:
            h, rem = divmod(self.sisa_waktu, 3600)
            m, s   = divmod(rem, 60)
            self.lbl_timer.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
            if self.sisa_waktu <= 120:
                self._warning_blink_on = not self._warning_blink_on
                if self._warning_blink_on:
                    self.configure(fg_color=C_RED)
                    self.lbl_timer.configure(text_color="white")
                else:
                    self.configure(fg_color="white")
                    self.lbl_timer.configure(text_color=C_ACCENT2)
            else:
                self.configure(fg_color="white")
                self.lbl_timer.configure(text_color=C_ACCENT2)
            self.sisa_waktu -= 1
            self._timer_job = self.after(1000, self._tick_waktu)
        else:
            # WAKTU HABIS — auto power off dan selesai sesi
            self.lbl_timer.configure(text="WAKTU HABIS ⏹", text_color=C_RED)
            total_akhir = self.paket_harga_tetap + self.biaya_pesanan
            pesanan_txt = ", ".join(f"{nm}×{qty}" for nm, qty in self.pesanan_aktif.items()) or "Tidak ada pesanan"
            paket_txt = f"{self.paket_aktif or '-'} ({fmt_rp(self.paket_harga_tetap)})"
            if getattr(self, '_last_transaction_item', None):
                app = self.winfo_toplevel()
                item_id = self._last_transaction_item
                pesanan_str = ", ".join(f"{nm}×{qty}" for nm, qty in self.pesanan_aktif.items()) or "—"
                total_str = fmt_rp(total_akhir)
                if hasattr(app, 'tree') and hasattr(app, '_tree_item_to_index'):
                    idx = app._tree_item_to_index.get(item_id)
                    if idx is not None and idx < len(app.riwayat_transaksi):
                        waktu = app.tree.item(item_id, 'values')[0] if app.tree.item(item_id, 'values') else datetime.now().strftime("%Y-%m-%d %H:%M")
                        updated_row = (waktu, app.current_user, self.label_tv, self.paket_aktif, pesanan_str, total_str)
                        app.riwayat_transaksi[idx] = updated_row
                        app.tree.item(item_id, values=updated_row)
                        # update meta if present
                        try:
                            app.riwayat_meta[idx]['pesanan_total'] = sum(
                                app.menu_makanan.get(nm, 0) * qty for nm, qty in self.pesanan_aktif.items())
                            app.riwayat_meta[idx]['total'] = total_akhir
                        except Exception:
                            pass
                        if hasattr(app, '_refresh_riwayat_summary'):
                            app._refresh_riwayat_summary()
            else:
                self.on_transaksi(self.label_tv, self.paket_aktif, self.pesanan_aktif, total_akhir)

            messagebox.showwarning(
                "⏰ Waktu TV Habis",
                f"TV: {self.label_tv}\n"
                f"Paket: {paket_txt}\n"
                f"Pesanan: {pesanan_txt} ({fmt_rp(self.biaya_pesanan)})\n"
                f"TOTAL: {fmt_rp(total_akhir)}",
                parent=self.winfo_toplevel(),
            )

            # Auto power off TV
            threading.Thread(target=lambda: self._adb_action(
                lambda: ADBHelper.power_toggle(self.ip, port=self.port)
            ), daemon=True).start()

            self._reset_sesi()

    # ── Timer Main Bebas (maju, hitung estimasi biaya berjalan) ─────────────
    def _tick_bebas(self):
        if not self.is_bebas or self.waktu_mulai is None:
            return
        total_detik = self.menit_dipakai_awal * 60 + int((datetime.now() - self.waktu_mulai).total_seconds())
        h, rem = divmod(total_detik, 3600)
        m, s   = divmod(rem, 60)
        self.lbl_timer.configure(text=f"{h:02d}:{m:02d}:{s:02d}", text_color=C_YELLOW)

        tarif_menit = hitung_tarif_per_menit(self.get_paket_data())
        menit_berjalan = total_detik / 60
        biaya_waktu_berjalan = tarif_menit * menit_berjalan
        total_berjalan = biaya_waktu_berjalan + self.biaya_pesanan
        self.lbl_estimasi.configure(
            text=f"Total berjalan: {fmt_rp(total_berjalan)}",
            text_color=C_YELLOW
        )

        self._timer_job = self.after(1000, self._tick_bebas)

    # ── Hitung total menit yang sudah dipakai sesi saat ini ─────────────────
    def _total_menit_terpakai(self):
        if self.is_bebas:
            if self.waktu_mulai is None:
                return self.menit_dipakai_awal
            detik_berjalan = (datetime.now() - self.waktu_mulai).total_seconds()
            return self.menit_dipakai_awal + detik_berjalan / 60
        return None  # tidak relevan untuk paket berwaktu

    # ── Tombol SELESAI ───────────────────────────────────────────────────────
    def _klik_selesai(self):
        if self.sesi_kosong():
            return
        if self.is_bebas:
            menit_total = self._total_menit_terpakai()
            tarif_menit = hitung_tarif_per_menit(self.get_paket_data())
            biaya_waktu = tarif_menit * menit_total
            total_akhir = biaya_waktu + self.biaya_pesanan
            pesanan_txt = ", ".join(f"{nm}×{qty}" for nm, qty in self.pesanan_aktif.items()) or "Tidak ada pesanan"
            konfirmasi = messagebox.askyesno(
                "⏹ Selesai — Main Bebas",
                f"TV: {self.label_tv}\n"
                f"Lama main: {fmt_durasi(round(menit_total))}\n"
                f"Biaya waktu: {fmt_rp(biaya_waktu)}\n"
                f"Biaya pesanan: {fmt_rp(self.biaya_pesanan)}\n"
                f"TOTAL: {fmt_rp(total_akhir)}\n\n"
                f"Rincian pesanan: {pesanan_txt}\n\n"
                f"Catat transaksi & akhiri sesi ini?")
            if not konfirmasi:
                return
            self.on_transaksi(self.label_tv, "Main Bebas", self.pesanan_aktif, total_akhir)
        else:
            total_akhir = self.paket_harga_tetap + self.biaya_pesanan
            pesanan_txt = ", ".join(f"{nm}×{qty}" for nm, qty in self.pesanan_aktif.items()) or "Tidak ada pesanan"
            paket_txt = f"{self.paket_aktif} ({fmt_rp(self.paket_harga_tetap)})"
            if not messagebox.askyesno(
                    "⏹ Selesai",
                    f"TV: {self.label_tv}\n"
                    f"Paket: {paket_txt}\n"
                    f"Pesanan: {pesanan_txt} ({fmt_rp(self.biaya_pesanan)})\n"
                    f"TOTAL: {fmt_rp(total_akhir)}\n\n"
                    f"Akhiri sesi ini?"):
                return
            # Transaksi paket berwaktu sudah dicatat saat konfirmasi awal,
            # jadi di sini tidak dicatat ulang — cukup tutup sesi.

        self.lbl_timer.configure(text="SELESAI ⏹", text_color=C_MUTED)
        self.lbl_estimasi.configure(text="")
        
        # AUTO POWER OFF TV
        threading.Thread(target=lambda: self._adb_action(
            lambda: ADBHelper.power_toggle(self.ip, port=self.port)
        ), daemon=True).start()
        
        self._reset_sesi()

    def _reset_sesi(self):
        if self._timer_job:
            self.after_cancel(self._timer_job)
            self._timer_job = None
        self.paket_aktif   = None
        self.sisa_waktu    = 0
        self.is_bebas      = False
        self.waktu_mulai   = None
        self.menit_dipakai_awal = 0
        self.pesanan_aktif = {}
        self.biaya_pesanan = 0
        self.paket_harga_tetap = 0
        self.lbl_paket.configure(text="—", text_color=C_MUTED)
        self.lbl_timer.configure(text="00:00:00", text_color=C_MUTED)
        self.configure(fg_color=C_CARD)
        self._warning_blink_on = False
        self.lbl_estimasi.configure(text="")
        self.btn_selesai.configure(state="disabled")
        self.btn_tambah_pesanan.configure(state="disabled")
        self.btn_tambah_pesanan.configure(text="SHOP", fg_color=C_BTN,
                                          border_width=1, border_color=C_ACCENT,
                                          text_color=C_ACCENT)
        app = self.winfo_toplevel()
        if hasattr(app, '_refresh_dashboard_total_pesanan'):
            app._refresh_dashboard_total_pesanan()

    # ── Tombol PINDAH TV ────────────────────────────────────────────────────
    def _klik_pindah(self):
        if self.sesi_kosong():
            return
        semua = self.get_semua_kartu()
        kandidat = [k for k in semua if k is not self and k.sesi_kosong()]
        if not kandidat:
            messagebox.showwarning("⚠ Tidak Ada TV Kosong",
                                    "Semua TV lain sedang dipakai.\n"
                                    "Selesaikan dulu salah satu sesi, atau tambah TV baru.")
            return
        self._buka_dialog_pilih_tujuan(kandidat)

    def _buka_dialog_pilih_tujuan(self, kandidat):
        dlg = ctk.CTkToplevel(self.winfo_toplevel())
        dlg.title("↔ Pindah TV")
        dlg.geometry("360x420")
        dlg.configure(fg_color=C_BG)
        dlg.grab_set()
        dlg.resizable(False, False)

        ctk.CTkLabel(dlg, text=f"↔  Pindah dari {self.label_tv}",
                     font=FONT_TITLE, text_color=C_ACCENT).pack(pady=(18, 4))
        ctk.CTkLabel(dlg, text="Pilih TV tujuan — sisa waktu & sesi akan dipindah",
                     font=FONT_BODY, text_color=C_MUTED, wraplength=320).pack(pady=(0, 12))

        scroll = ctk.CTkScrollableFrame(dlg, fg_color=C_BG, height=280)
        scroll.pack(fill="both", expand=True, padx=16)

        for k in kandidat:
            btn = ctk.CTkButton(
                scroll, text=f"📺  {k.label_tv}   ({k.ip}:{k.port})",
                height=40, fg_color=C_CARD, hover_color=C_ACCENT2,
                border_width=1, border_color=C_BORDER,
                font=FONT_BODY, text_color=C_TEXT, anchor="w",
                command=lambda target=k: self._konfirmasi_pindah(target, dlg))
            btn.pack(fill="x", pady=4, padx=4)

        ctk.CTkButton(dlg, text="✖  Batal", height=34, width=120,
                      fg_color=C_RED, font=FONT_SUB, text_color="white",
                      command=dlg.destroy).pack(pady=12)

    def _konfirmasi_pindah(self, target, dlg):
        if not messagebox.askyesno(
                "↔ Konfirmasi Pindah",
                f"Pindahkan sesi dari {self.label_tv} ke {target.label_tv}?\n\n"
                f"Sisa waktu / lama main akan dilanjutkan di {target.label_tv},\n"
                f"dan {self.label_tv} akan menjadi kosong."):
            return

        # ── Salin status sesi ke TV tujuan ───────────────────────────────────
        target.paket_aktif   = self.paket_aktif
        target.is_bebas      = self.is_bebas
        target.pesanan_aktif = dict(self.pesanan_aktif)
        target.biaya_pesanan = self.biaya_pesanan
        target.paket_harga_tetap = self.paket_harga_tetap

        if self.is_bebas:
            target.menit_dipakai_awal = self._total_menit_terpakai()
            target.sisa_waktu  = 0
            target.waktu_mulai = datetime.now()
            target.lbl_paket.configure(text="Main Bebas 🕹️ (berjalan)", text_color=C_GREEN)
            target.lbl_timer.configure(text_color=C_YELLOW)
            target.lbl_estimasi.configure(text=f"Total berjalan: {fmt_rp(target.biaya_pesanan)}", text_color=C_YELLOW)
        else:
            target.sisa_waktu  = self.sisa_waktu
            target.waktu_mulai = datetime.now()
            harga_tampil = self.paket_harga_tetap + self.biaya_pesanan
            target.lbl_paket.configure(text=f"{self.paket_aktif} | {fmt_rp(harga_tampil)}",
                                        text_color=C_YELLOW)
            target.lbl_timer.configure(text_color=C_ACCENT)

        if target._timer_job:
            target.after_cancel(target._timer_job)
        if target.is_bebas:
            target._tick_bebas()
        elif target.sisa_waktu > 0:
            target._tick_waktu()
        else:
            target.lbl_timer.configure(text="∞ BEBAS", text_color=C_GREEN)
        target.btn_selesai.configure(state="normal")
        target.btn_tambah_pesanan.configure(state="normal")
        target.btn_tambah_pesanan.configure(text="SHOP", fg_color=C_BTN, border_width=1,
                                            border_color=C_ACCENT2, text_color=C_ACCENT2)

        # ── Kosongkan TV asal ────────────────────────────────────────────────
        self._reset_sesi()

        dlg.destroy()
        messagebox.showinfo("✅ Berhasil Pindah",
                            f"Sesi telah dipindah ke {target.label_tv}.")


# ═══════════════════════════════════════════════════════════════════════════════
#  KARTU WARNET
# ═══════════════════════════════════════════════════════════════════════════════
class KartuWarnet(ctk.CTkFrame):
    def __init__(self, master, nomor, label_kursi, on_transaksi,
                 get_paket_data, get_makanan_data, get_minuman_data,
                get_semua_kartu=None, get_daftar_grup=None, on_ganti_grup=None,
                on_hapus=None, nama_grup=None, **kwargs):
        super().__init__(master, fg_color=C_CARD, corner_radius=8,
                         border_width=1, border_color=C_BORDER, **kwargs)
        self.nomor             = nomor
        self.label_kursi       = label_kursi
        self.on_transaksi      = on_transaksi
        self.nama_grup         = nama_grup or NAMA_GRUP_DEFAULT
        self.get_paket_data    = get_paket_data or (lambda: {})
        self.get_makanan_data  = get_makanan_data
        self.get_minuman_data  = get_minuman_data
        self.get_semua_kartu   = get_semua_kartu or (lambda: [])
        self.get_daftar_grup   = get_daftar_grup or (lambda: [self.nama_grup])
        self.on_ganti_grup     = on_ganti_grup
        self.on_hapus          = on_hapus

        self.paket_aktif       = None
        self.sisa_waktu        = 0
        self.is_bebas          = False
        self.menit_dipakai_awal= 0
        self.waktu_mulai       = None
        self.pesanan_aktif     = {}
        self.biaya_pesanan     = 0
        self.paket_harga_tetap = 0
        self._timer_job        = None
        self._last_transaction_item = None
        self.is_on            = False
        self._warning_blink_on = False

        self._build()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color=C_ACCENT2, corner_radius=10)
        hdr.pack(fill="x", padx=3, pady=(2, 1))

        self.lbl_kursi = ctk.CTkLabel(hdr, text=self.label_kursi,
                                     font=("Russo One", 11, "bold"), text_color="white")
        self.lbl_kursi.pack(side="left", fill="x", expand=True, padx=(8, 0))

        self.btn_ganti_nama = ctk.CTkButton(hdr, text="Nama", width=76, height=28,
                                            fg_color=C_BTN, hover_color=C_BORDER,
                                            border_width=1, border_color=C_ACCENT2,
                                            font=("Russo One", 8, "bold"), text_color=C_ACCENT2,
                                            command=self._buka_ganti_ip)
        self.btn_ganti_nama.pack(side="right", padx=(0, 4))

        self.btn_hapus = ctk.CTkButton(hdr, text="✖", width=36, height=28,
                                       fg_color=C_RED, hover_color="#FF5C5C",
                                       border_width=1, border_color=C_RED,
                                       font=("Russo One", 8, "bold"), text_color="white",
                                       command=self._confirm_hapus)
        self.btn_hapus.pack(side="right", padx=(0, 8))

        st_row = ctk.CTkFrame(self, fg_color="transparent")
        st_row.pack(fill="x", padx=3, pady=(0, 4))
        self.lbl_power = ctk.CTkLabel(st_row, text="● SIAP", font=("Courier New", 10, "bold"),
                                       text_color=C_GREEN)
        self.lbl_power.pack(side="left", padx=4)
        self.lbl_grup = ctk.CTkLabel(st_row, text=f"↻ {self.nama_grup}", font=("Courier New", 10, "bold"),
                                      text_color=C_ACCENT2, cursor="arrow")
        self.lbl_grup.pack(side="left", padx=4)
        # Warnet PCs dikunci ke grup warnet - tidak bisa diubah (hapus event binding)
        self.lbl_paket = ctk.CTkLabel(st_row, text="—", font=("Courier New", 8), text_color=C_MUTED)
        self.lbl_paket.pack(side="right", padx=4)

        self.lbl_timer = ctk.CTkLabel(self, text="00:00:00",
                                       font=("Russo One", 20, "bold"), text_color=C_ACCENT2)
        self.lbl_timer.pack(pady=(2, 2))

        self.lbl_estimasi = ctk.CTkLabel(self, text="", font=("Courier New", 8), text_color=C_YELLOW)
        self.lbl_estimasi.pack()

        r1 = ctk.CTkFrame(self, fg_color="transparent")
        r1.pack(pady=4, fill="x", padx=3)
        for i in range(5):
            r1.columnconfigure(i, weight=1, uniform="btnrow")

        self.btn_power = ctk.CTkButton(r1, text="⚡ PWR", height=34,
                                       fg_color=C_RED, hover_color="#FF6666",
                                       border_width=2, border_color=C_RED,
                                       font=("Courier New", 9, "bold"), text_color="white",
                                       command=self._toggle_power)
        self.btn_power.grid(row=0, column=0, sticky="nsew", padx=(0, 2))

        for idx, (txt, color, cmd) in enumerate([
            ("VOL+", C_GREEN, lambda: self._dummy_action("VOL+")),
            ("VOL−", C_YELLOW, lambda: self._dummy_action("VOL-")),
            ("HOME", C_ACCENT, lambda: self._dummy_action("HOME")),
        ], start=1):
            ctk.CTkButton(r1, text=txt, height=34, fg_color=color,
                         hover_color="white" if color == C_ACCENT else None,
                         font=("Courier New", 9, "bold"), text_color="black" if color == C_ACCENT else "white",
                         border_width=1, border_color=color,
                         command=cmd).grid(row=0, column=idx, sticky="nsew", padx=2)

        self.btn_status = ctk.CTkButton(r1, text="ON", height=34,
                                       fg_color=C_BTN, border_width=1, border_color=C_GREEN,
                                       font=("Russo One", 9, "bold"), text_color=C_GREEN,
                                       command=self._toggle_power)
        self.btn_status.grid(row=0, column=4, sticky="nsew", padx=(2, 0))

        r2 = ctk.CTkFrame(self, fg_color="transparent")
        r2.pack(pady=2, fill="x", padx=3)
        for i in range(5):
            r2.columnconfigure(i, weight=1, uniform="btnrow")

        self.btn_selesai = ctk.CTkButton(r2, text="SELESAI", height=34,
                                         fg_color=C_BTN, hover_color="#3A0000",
                                         border_width=1, border_color=C_RED,
                                         font=("Russo One", 9, "bold"), text_color=C_RED,
                                         state="disabled",
                                         command=self._klik_selesai)
        self.btn_selesai.grid(row=0, column=0, sticky="nsew", padx=(0, 2))

        self.btn_tambah_pesanan = ctk.CTkButton(r2, text="SHOP", height=34,
                                               fg_color=C_BTN, hover_color=C_ACCENT2,
                                               border_width=1, border_color=C_ACCENT,
                                               font=("Russo One", 9, "bold"), text_color=C_ACCENT,
                                               state="disabled",
                                               command=self._buka_tambah_pesanan)
        self.btn_tambah_pesanan.grid(row=0, column=1, sticky="nsew", padx=2)

        self.btn_tambah_waktu = ctk.CTkButton(r2, text="PAKET", height=34,
                                              fg_color=C_BTN, hover_color=C_ACCENT2,
                                              border_width=1, border_color=C_ACCENT2,
                                              font=("Russo One", 9, "bold"), text_color=C_ACCENT2,
                                              command=self._pilih_paket)
        self.btn_tambah_waktu.grid(row=0, column=2, sticky="nsew", padx=2)

        self.btn_ip = ctk.CTkButton(r2, text="IP", height=34,
                                    fg_color=C_BTN, hover_color=C_ACCENT2,
                                    border_width=1, border_color=C_ACCENT2,
                                    font=("Russo One", 9, "bold"), text_color=C_ACCENT2,
                                    command=self._buka_ganti_ip)
        self.btn_ip.grid(row=0, column=3, sticky="nsew", padx=2)

        self.btn_pindah_kursi = ctk.CTkButton(r2, text="Pindah PC", height=34,
                                             fg_color=C_BTN, border_width=1, border_color=C_ACCENT2,
                                             font=("Russo One", 9, "bold"), text_color=C_ACCENT2,
                                             command=self._klik_pindah)
        self.btn_pindah_kursi.grid(row=0, column=4, sticky="nsew", padx=(2, 0))

    def sesi_kosong(self):
        return self.paket_aktif is None

    def _buka_ganti_ip(self):
        dlg = ctk.CTkInputDialog(text="Nama kursi baru:", title=f"✏️ Ganti Nama Kursi — {self.label_kursi}")
        nama_baru = dlg.get_input()
        if not nama_baru:
            return
        self.label_kursi = nama_baru.strip()
        self.lbl_kursi.configure(text=self.label_kursi)

    def _buka_ganti_grup(self):
        daftar = self.get_daftar_grup() or []
        if not daftar:
            messagebox.showwarning("Grup Tarif", "Tidak ada grup tarif yang tersedia untuk dipilih.", parent=self)
            return

        dlg = ctk.CTkToplevel(self.winfo_toplevel())
        dlg.title("🏷 Ganti Grup Tarif Warnet")
        dlg.geometry("360x180")
        dlg.configure(fg_color=C_BG)
        dlg.resizable(False, False)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text=f"Kursi: {self.label_kursi}", font=FONT_SUB,
                     text_color=C_ACCENT).pack(pady=(16, 6))
        ctk.CTkLabel(dlg, text="Pilih grup tarif untuk kursi warnet ini:",
                     font=FONT_BODY, text_color=C_MUTED).pack(padx=16)

        var_grup = tk.StringVar(value=self.nama_grup)
        ctk.CTkOptionMenu(dlg, values=daftar, variable=var_grup,
                          fg_color=C_BTN, button_color=C_ACCENT2,
                          button_hover_color="#5A0FCC",
                          text_color=C_TEXT, font=FONT_BODY,
                          dropdown_font=FONT_BODY,
                          dropdown_fg_color=C_CARD,
                          dropdown_text_color=C_TEXT,
                          width=280).pack(pady=14)

        def terapkan():
            grup_baru = var_grup.get()
            if not grup_baru or grup_baru == self.nama_grup:
                dlg.destroy()
                return
            self.nama_grup = grup_baru
            self.lbl_grup.configure(text=f"↻ {grup_baru}")
            if callable(self.on_ganti_grup):
                self.on_ganti_grup(self, grup_baru)
            dlg.destroy()

        ctk.CTkButton(dlg, text="✅ Terapkan", width=120, height=36,
                      fg_color=C_ACCENT2, hover_color=C_ACCENT,
                      font=FONT_SMALL, text_color="white",
                      command=terapkan).pack(pady=(0, 10))

    def _confirm_hapus(self):
        if messagebox.askyesno("Hapus Kursi", f"Hapus {self.label_kursi} dari dashboard warnet?"):
            if callable(self.on_hapus):
                self.on_hapus(self)

    def _toggle_power(self):
        self.is_on = not self.is_on
        if self.is_on:
            self.lbl_power.configure(text="● ON", text_color=C_GREEN)
            self.btn_power.configure(fg_color="#3A0000")
            self.btn_status.configure(text="ON", fg_color=C_GREEN, border_color=C_GREEN, text_color=C_GREEN)
        else:
            self.lbl_power.configure(text="● OFF", text_color=C_MUTED)
            self.btn_power.configure(fg_color=C_BTN)
            self.btn_status.configure(text="OFF", fg_color=C_BTN, border_color=C_BORDER, text_color=C_MUTED)

    def _dummy_action(self, action):
        messagebox.showinfo("Info", f"{action} tidak tersedia untuk dashboard warnet.", parent=self)

    def _pilih_paket(self):
        # Mirror KartuTV behavior: call the kartu's get_paket_data() closure so it always
        # resolves paket data from the current grup setting (and respects for_warnet=True).
        try:
            paket_data = self.get_paket_data() if callable(self.get_paket_data) else {}
        except Exception as e:
            paket_data = {}

        DialogPaket(self.winfo_toplevel(), self.label_kursi, self._on_paket_confirm,
                    paket_data, self.get_makanan_data(), self.get_minuman_data(),
                    nama_grup=self.nama_grup, for_warnet=True)

    def _buka_tambah_pesanan(self):
        if not self.paket_aktif:
            messagebox.showwarning("Tidak Ada Sesi", "Mulai sesi terlebih dahulu untuk memesan.", parent=self)
            return
        DialogTambahPesanan(self.winfo_toplevel(), self.label_kursi,
                            self._on_tambah_pesanan_confirm,
                            self.get_makanan_data(), self.get_minuman_data(),
                            pesanan_aktif=self.pesanan_aktif.copy())

    def _on_tambah_pesanan_confirm(self, pesanan_baru):
        all_menu = {**self.get_makanan_data(), **self.get_minuman_data()}
        for nama, qty in pesanan_baru.items():
            self.pesanan_aktif[nama] = qty
        total_baru = sum(all_menu.get(nama, 0) * qty for nama, qty in self.pesanan_aktif.items())
        self.biaya_pesanan = total_baru

        if self.is_bebas:
            self.lbl_paket.configure(text=f"Main Bebas 🕹️ +Pesanan {fmt_rp(total_baru)}")
        else:
            self.lbl_paket.configure(text=f"{self.paket_aktif} | {fmt_rp(self.paket_harga_tetap + total_baru)}")

        if not self.is_bebas and getattr(self, '_last_transaction_item', None):
            app = self.winfo_toplevel()
            item_id = self._last_transaction_item
            pesanan_str = ", ".join(f"{nm}×{qty}" for nm, qty in self.pesanan_aktif.items()) or "—"
            total_str = fmt_rp(self.paket_harga_tetap + self.biaya_pesanan)
            if hasattr(app, 'tree') and hasattr(app, '_tree_item_to_index'):
                idx = app._tree_item_to_index.get(item_id)
                if idx is not None and idx < len(app.riwayat_transaksi):
                    waktu = app.tree.item(item_id, 'values')[0] if app.tree.item(item_id, 'values') else datetime.now().strftime("%Y-%m-%d %H:%M")
                    updated_row = (waktu, app.current_user, self.label_kursi, self.paket_aktif, pesanan_str, total_str)
                    app.riwayat_transaksi[idx] = updated_row
                    app.tree.item(item_id, values=updated_row)
                    try:
                        app.riwayat_meta[idx]['pesanan_total'] = sum(app.menu_makanan.get(nm, 0) * qty for nm, qty in self.pesanan_aktif.items())
                        app.riwayat_meta[idx]['total'] = self.paket_harga_tetap + self.biaya_pesanan
                    except Exception:
                        pass
                    if hasattr(app, '_refresh_riwayat_summary'):
                        app._refresh_riwayat_summary()
        app = self.winfo_toplevel()
        if hasattr(app, '_refresh_warnet_footer'):
            app._refresh_warnet_footer()

    def _on_paket_confirm(self, paket_nm, paket_harga, paket_menit, pesanan, total_pesanan):
        previous_session = not self.sesi_kosong()
        self.pesanan_aktif = pesanan
        self.biaya_pesanan = total_pesanan
        self.menit_dipakai_awal = 0

        if paket_nm == "Main Bebas":
            self.is_bebas = True
            self.sisa_waktu = 0
            self.waktu_mulai = datetime.now()
            self.paket_harga_tetap = 0
            self.paket_aktif = paket_nm
            self.lbl_paket.configure(text="Main Bebas 🕹️ (berjalan)", text_color=C_GREEN)
            self.lbl_timer.configure(text_color=C_YELLOW)
            self.lbl_estimasi.configure(text=f"Total berjalan: {fmt_rp(self.biaya_pesanan)}", text_color=C_YELLOW)
        else:
            self.is_bebas = False
            self.paket_aktif = paket_nm
            if previous_session and self.paket_harga_tetap:
                self.sisa_waktu += paket_menit * 60
                self.paket_harga_tetap += paket_harga
            else:
                self.sisa_waktu = paket_menit * 60
                self.paket_harga_tetap = paket_harga
            self.waktu_mulai = datetime.now()
            self.lbl_paket.configure(text=f"{paket_nm} | {fmt_rp(self.paket_harga_tetap + self.biaya_pesanan)}",
                                      text_color=C_YELLOW)
            self.lbl_timer.configure(text_color=C_ACCENT)

        if self._timer_job:
            self.after_cancel(self._timer_job)

        self.btn_selesai.configure(state="normal")
        self.btn_tambah_pesanan.configure(state="normal")
        self.btn_tambah_pesanan.configure(text="SHOP", fg_color=C_BTN, border_width=1,
                                          border_color=C_ACCENT2, text_color=C_ACCENT2)
        self.configure(fg_color="white")
        self._warning_blink_on = False

        if not self.is_bebas and self.sisa_waktu > 0:
            h, rem = divmod(self.sisa_waktu, 3600)
            m, s = divmod(rem, 60)
            self.lbl_timer.configure(text=f"{h:02d}:{m:02d}:{s:02d}")

        if self.is_bebas:
            self._tick_bebas()
        elif self.sisa_waktu > 0:
            self._tick_waktu()
        else:
            self.lbl_timer.configure(text="∞ BEBAS", text_color=C_GREEN)

        if not self.is_bebas:
            if self._last_transaction_item and previous_session:
                app = self.winfo_toplevel()
                item_id = self._last_transaction_item
                pesanan_str = ", ".join(f"{nm}×{qty}" for nm, qty in self.pesanan_aktif.items()) or "—"
                total_str = fmt_rp(self.paket_harga_tetap + self.biaya_pesanan)
                if hasattr(app, 'tree') and hasattr(app, '_tree_item_to_index'):
                    idx = app._tree_item_to_index.get(item_id)
                    if idx is not None and idx < len(app.riwayat_transaksi):
                        waktu = app.tree.item(item_id, 'values')[0] if app.tree.item(item_id, 'values') else datetime.now().strftime("%Y-%m-%d %H:%M")
                        updated_row = (waktu, app.current_user, self.label_kursi, self.paket_aktif, pesanan_str, total_str)
                        app.riwayat_transaksi[idx] = updated_row
                        app.tree.item(item_id, values=updated_row)
                        if hasattr(app, '_refresh_riwayat_summary'):
                            app._refresh_riwayat_summary()
            else:
                self._last_transaction_item = self.on_transaksi(
                    self.label_kursi, paket_nm, pesanan, self.paket_harga_tetap + total_pesanan, source='warnet')
        else:
            self._last_transaction_item = None
 
        app = self.winfo_toplevel()
        if hasattr(app, '_run_warnet_socket_command'):
            threading.Thread(
                target=lambda: app._run_warnet_socket_command(
                    app.socket_warnet_config.get('on_start_command', 'START {kursi}'),
                    self.label_kursi),
                daemon=True).start()
        if hasattr(app, '_refresh_warnet_footer'):
            app._refresh_warnet_footer()

    def _tick_waktu(self):
        if self.sisa_waktu > 0:
            h, rem = divmod(self.sisa_waktu, 3600)
            m, s = divmod(rem, 60)
            self.lbl_timer.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
            if self.sisa_waktu <= 120:
                self._warning_blink_on = not self._warning_blink_on
                if self._warning_blink_on:
                    self.configure(fg_color=C_RED)
                    self.lbl_timer.configure(text_color="white")
                else:
                    self.configure(fg_color="white")
                    self.lbl_timer.configure(text_color=C_ACCENT2)
            else:
                self.configure(fg_color="white")
                self.lbl_timer.configure(text_color=C_ACCENT2)
            self.sisa_waktu -= 1
            self._timer_job = self.after(1000, self._tick_waktu)
        else:
            self.lbl_timer.configure(text="WAKTU HABIS ⏹", text_color=C_RED)
            total_akhir = self.paket_harga_tetap + self.biaya_pesanan
            pesanan_txt = ", ".join(f"{nm}×{qty}" for nm, qty in self.pesanan_aktif.items()) or "Tidak ada pesanan"
            paket_txt = f"{self.paket_aktif or '-'} ({fmt_rp(self.paket_harga_tetap)})"
            messagebox.showwarning(
                "⏰ Waktu PC Habis",
                f"PC: {self.label_kursi}\n"
                f"Paket: {paket_txt}\n"
                f"Pesanan: {pesanan_txt} ({fmt_rp(self.biaya_pesanan)})\n"
                f"TOTAL: {fmt_rp(total_akhir)}",
                parent=self.winfo_toplevel(),
            )
            self._reset_sesi()

    def _tick_bebas(self):
        if not self.is_bebas or self.waktu_mulai is None:
            return
        total_detik = self.menit_dipakai_awal * 60 + int((datetime.now() - self.waktu_mulai).total_seconds())
        h, rem = divmod(total_detik, 3600)
        m, s = divmod(rem, 60)
        self.lbl_timer.configure(text=f"{h:02d}:{m:02d}:{s:02d}", text_color=C_YELLOW)
        tarif_menit = hitung_tarif_per_menit(self.get_paket_data())
        menit_berjalan = total_detik / 60
        biaya_waktu_berjalan = tarif_menit * menit_berjalan
        total_berjalan = biaya_waktu_berjalan + self.biaya_pesanan
        self.lbl_estimasi.configure(
            text=f"Total berjalan: {fmt_rp(total_berjalan)}",
            text_color=C_YELLOW
        )
        self._timer_job = self.after(1000, self._tick_bebas)

    def _total_menit_terpakai(self):
        if self.is_bebas:
            if self.waktu_mulai is None:
                return self.menit_dipakai_awal
            detik_berjalan = (datetime.now() - self.waktu_mulai).total_seconds()
            return self.menit_dipakai_awal + detik_berjalan / 60
        return None

    def _klik_selesai(self):
        if self.sesi_kosong():
            return
        if self.is_bebas:
            menit_total = self._total_menit_terpakai()
            tarif_menit = hitung_tarif_per_menit(self.get_paket_data())
            biaya_waktu = tarif_menit * menit_total
            total_akhir = biaya_waktu + self.biaya_pesanan
            pesanan_txt = ", ".join(f"{nm}×{qty}" for nm, qty in self.pesanan_aktif.items()) or "Tidak ada pesanan"
            if not messagebox.askyesno(
                    "⏹ Selesai — Main Bebas",
                    f"Kursi: {self.label_kursi}\n"
                    f"Lama main: {fmt_durasi(round(menit_total))}\n"
                    f"Biaya waktu: {fmt_rp(biaya_waktu)}\n"
                    f"Biaya pesanan: {fmt_rp(self.biaya_pesanan)}\n"
                    f"TOTAL: {fmt_rp(total_akhir)}\n\n"
                    f"Rincian pesanan: {pesanan_txt}\n\n"
                    f"Catat transaksi & akhiri sesi ini?"):
                return
            self.on_transaksi(self.label_kursi, "Main Bebas", self.pesanan_aktif, total_akhir, source='warnet')
        else:
            total_akhir = self.paket_harga_tetap + self.biaya_pesanan
            pesanan_txt = ", ".join(f"{nm}×{qty}" for nm, qty in self.pesanan_aktif.items()) or "Tidak ada pesanan"
            paket_txt = f"{self.paket_aktif} ({fmt_rp(self.paket_harga_tetap)})"
            if not messagebox.askyesno(
                    "⏹ Selesai",
                    f"Kursi: {self.label_kursi}\n"
                    f"Paket: {paket_txt}\n"
                    f"Pesanan: {pesanan_txt} ({fmt_rp(self.biaya_pesanan)})\n"
                    f"TOTAL: {fmt_rp(total_akhir)}\n\n"
                    f"Akhiri sesi ini?"):
                return
        self.lbl_timer.configure(text="SELESAI ⏹", text_color=C_MUTED)
        self.lbl_estimasi.configure(text="")
        app = self.winfo_toplevel()
        if hasattr(app, '_run_warnet_socket_command'):
            threading.Thread(
                target=lambda: app._run_warnet_socket_command(
                    app.socket_warnet_config.get('on_finish_command', 'STOP {kursi}'),
                    self.label_kursi),
                daemon=True).start()
        self._reset_sesi()

    def _reset_sesi(self):
        if self._timer_job:
            self.after_cancel(self._timer_job)
            self._timer_job = None
        self.paket_aktif = None
        self.sisa_waktu = 0
        self.is_bebas = False
        self.waktu_mulai = None
        self.menit_dipakai_awal = 0
        self.pesanan_aktif = {}
        self.biaya_pesanan = 0
        self.paket_harga_tetap = 0
        self.lbl_paket.configure(text="—", text_color=C_MUTED)
        self.lbl_timer.configure(text="00:00:00", text_color=C_MUTED)
        self.configure(fg_color=C_CARD)
        self._warning_blink_on = False
        self.lbl_estimasi.configure(text="")
        self.btn_selesai.configure(state="disabled")
        self.btn_tambah_pesanan.configure(state="disabled")
        self.btn_tambah_pesanan.configure(text="SHOP", fg_color=C_BTN,
                                          border_width=1, border_color=C_ACCENT,
                                          text_color=C_ACCENT)
        app = self.winfo_toplevel()
        if hasattr(app, '_refresh_warnet_footer'):
            app._refresh_warnet_footer()

    def _klik_pindah(self):
        if self.sesi_kosong():
            return
        semua = self.get_semua_kartu()
        kandidat = [k for k in semua if k is not self and k.sesi_kosong()]
        if not kandidat:
            messagebox.showwarning("⚠ Tidak Ada Kursi Kosong",
                                    "Semua kursi lain sedang dipakai.\n"
                                    "Selesaikan dulu salah satu sesi, atau tambah kursi baru.")
            return
        self._buka_dialog_pilih_tujuan(kandidat)

    def _buka_dialog_pilih_tujuan(self, kandidat):
        dlg = ctk.CTkToplevel(self.winfo_toplevel())
        dlg.title("↔ Pindah Kursi")
        dlg.geometry("360x420")
        dlg.configure(fg_color=C_BG)
        dlg.grab_set()
        dlg.resizable(False, False)

        ctk.CTkLabel(dlg, text=f"↔  Pindah dari {self.label_kursi}",
                     font=FONT_TITLE, text_color=C_ACCENT).pack(pady=(18, 4))
        ctk.CTkLabel(dlg, text="Pilih kursi tujuan — sisa waktu & sesi akan dipindah",
                     font=FONT_BODY, text_color=C_MUTED, wraplength=320).pack(pady=(0, 12))

        scroll = ctk.CTkScrollableFrame(dlg, fg_color=C_BG, height=280)
        scroll.pack(fill="both", expand=True, padx=16)

        for k in kandidat:
            btn = ctk.CTkButton(
                scroll, text=f"💻  {k.label_kursi}",
                height=40, fg_color=C_CARD, hover_color=C_ACCENT2,
                border_width=1, border_color=C_BORDER,
                font=FONT_BODY, text_color=C_TEXT, anchor="w",
                command=lambda target=k: self._konfirmasi_pindah(target, dlg))
            btn.pack(fill="x", pady=4, padx=4)

        ctk.CTkButton(dlg, text="✖  Batal", height=34, width=120,
                      fg_color=C_RED, font=FONT_SUB, text_color="white",
                      command=dlg.destroy).pack(pady=12)

    def _konfirmasi_pindah(self, target, dlg):
        if not messagebox.askyesno(
                "↔ Konfirmasi Pindah",
                f"Pindahkan sesi dari {self.label_kursi} ke {target.label_kursi}?\n\n"
                f"Sisa waktu / lama main akan dilanjutkan di {target.label_kursi},\n"
                f"dan {self.label_kursi} akan menjadi kosong."):
            return

        target.paket_aktif = self.paket_aktif
        target.is_bebas = self.is_bebas
        target.pesanan_aktif = dict(self.pesanan_aktif)
        target.biaya_pesanan = self.biaya_pesanan
        target.paket_harga_tetap = self.paket_harga_tetap
        target._last_transaction_item = self._last_transaction_item

        if self.is_bebas:
            target.menit_dipakai_awal = self._total_menit_terpakai()
            target.sisa_waktu = 0
            target.waktu_mulai = datetime.now()
            target.lbl_paket.configure(text="Main Bebas 🕹️ (berjalan)", text_color=C_GREEN)
            target.lbl_timer.configure(text_color=C_YELLOW)
            target.lbl_estimasi.configure(text=f"Total berjalan: {fmt_rp(target.biaya_pesanan)}", text_color=C_YELLOW)
        else:
            target.sisa_waktu = self.sisa_waktu
            target.waktu_mulai = datetime.now()
            target.lbl_paket.configure(text=f"{self.paket_aktif} | {fmt_rp(self.paket_harga_tetap + self.biaya_pesanan)}",
                                       text_color=C_YELLOW)
            target.lbl_timer.configure(text_color=C_ACCENT)

        target.btn_selesai.configure(state="normal")
        target.btn_tambah_pesanan.configure(state="normal")
        target.btn_tambah_pesanan.configure(text="SHOP", fg_color=C_BTN,
                                          border_width=1, border_color=C_ACCENT2,
                                          text_color=C_ACCENT2)

        self._reset_sesi()
        dlg.destroy()
        messagebox.showinfo("✅ Berhasil Pindah",
                            f"Sesi telah dipindah ke {target.label_kursi}.")


# ═══════════════════════════════════════════════════════════════════════════════
#  APLIKASI UTAMA
# ═══════════════════════════════════════════════════════════════════════════════
class AutoRentApp(ctk.CTk):
    pass

    def __init__(self):
        super().__init__()
        self.title("RR BILLING PRO — Billing TV System")
        self.geometry("560x760")
        self.resizable(False, False)
        self.configure(fg_color=C_BG)

        # ── Set ikon window dari logo.png ─────────────────────────────────────
        set_window_icon(self)

        self.current_user  = None
        self.current_role  = None
        self.jumlah_tv     = 0
        self.riwayat_transaksi = []
        self.riwayat_meta = []  # parallel metadata: dicts with keys: source('tv'|'warnet'), pesanan_total(int), total(int)
        self._tree_item_to_index = {}
        self._tambah_btn_enabled = True
        self._tambah_warnet_btn_enabled = True
        self._semua_kartu_tv  = []   # daftar semua KartuTV yang sedang ada di Dashboard
        self._semua_kartu_warnet = []  # daftar kartu warnet

        cfg = ConfigManager.load()
        self.grup_tarif   = self._migrasi_grup_tarif(cfg.get("grup_tarif"), cfg.get("paket_main"))
        self.menu_makanan = cfg.get("menu_makanan",  dict(DEFAULT_MENU_MAKANAN))
        self.menu_minuman = cfg.get("menu_minuman",  dict(DEFAULT_MENU_MINUMAN))
        self.socket_warnet_config = cfg.get("socket_warnet", {})
        self.current_tab  = None
        
        # ── Start Warnet Socket Server ──────────────────────────────────────────
        self.warnet_server = WarnetSocketServer(app=self)
        self.warnet_server.start()

        self._show_login()

    def _lakukan_aktivasi(self):
        kode = self.entry_kode.get().strip()
        if not kode:
            self.lbl_akt_status.configure(
                text="⚠  Masukkan kode aktivasi dulu.", text_color=C_YELLOW)
            return

        uname = self.current_user or ""

        # LicenseManager.aktivasi sudah otomatis mencoba binding username
        # (kalau rr_keygen.py tersedia) dengan fallback ke universal/machine.
        sukses, pesan = LicenseManager.aktivasi(
            kode,
            username=uname,
            binding_mode="username" if uname else "machine"
        )

        AuditLogger.log(
            action="activation_attempt",
            username=uname,
            status="success" if sukses else "failed",
            details={
                "binding_mode": "username" if uname else "machine",
                "message": pesan,
            }
        )
        if sukses:
            self.lbl_akt_status.configure(text=f"✅  {pesan}", text_color=C_GREEN)
            messagebox.showinfo("🎉 Aktivasi Berhasil", pesan)
            self._rebuild_sidebar_lic()
        else:
            self.lbl_akt_status.configure(text=f"✖  {pesan}", text_color=C_RED)

    @staticmethod
    def _migrasi_grup_tarif(data_grup, data_paket_lama):
        """
        Pastikan struktur self.grup_tarif selalu:
            {nama_grup: {nama_paket: {"harga":int, "menit":int}, ...}, ...}

        Tiga kemungkinan sumber data saat startup:
        1. Config baru sudah punya "grup_tarif"  -> dipakai langsung (dengan sanitasi).
        2. Config lama (sebelum fitur grup) cuma punya "paket_main" flat
           -> dijadikan grup tunggal "Reguler", grup PS3/PS4/Room VIP lain
              TIDAK otomatis dibuat (supaya tidak mengejutkan user lama yang
              sudah custom harga "Reguler"-nya).
        3. Belum ada config sama sekali -> pakai DEFAULT_GRUP_TARIF penuh
           (Reguler, PS3, PS4, Room VIP).
        """
        menit_lama = {
            "30 Menit": 30, "1 Jam": 60, "2 Jam": 120,
            "3 Jam": 180, "5 Jam": 300, "Overnight": 540,
            "Main Bebas": 0, "Reguler": 60,
        }

        def _bersihkan_satu_grup(paket_dict):
            hasil = {}
            for nama, val in paket_dict.items():
                if isinstance(val, dict):
                    hasil[nama] = {"harga": int(val.get("harga", 0)), "menit": int(val.get("menit", 0))}
                else:
                    hasil[nama] = {"harga": int(val), "menit": menit_lama.get(nama, 60)}
            if "Main Bebas" not in hasil:
                hasil["Main Bebas"] = {"harga": 0, "menit": 0}
            return hasil

        if data_grup:
            return {nama: _bersihkan_satu_grup(paket) for nama, paket in data_grup.items()}

        if data_paket_lama:
            return {NAMA_GRUP_DEFAULT: _bersihkan_satu_grup(data_paket_lama)}

        return {nama: {k: dict(v) for k, v in paket.items()} for nama, paket in DEFAULT_GRUP_TARIF.items()}

    def daftar_nama_grup(self, for_warnet=False):
        """Return list of group names.
        If for_warnet is False (default), exclude groups marked as warnet-only in config 'warnet_only_groups'.
        If for_warnet is True, include warnet-only groups and any groups defined specifically for warnet in
        config key 'grup_tarif_warnet'. "Warnet" group (if exists) is always first.
        """
        cfg = ConfigManager.load()
        warnet_only = set(cfg.get('warnet_only_groups', []))
        if for_warnet:
            names = list(self.grup_tarif.keys()) if getattr(self, 'grup_tarif', None) else []
            # Include any warnet-specific groups defined separately in config
            warnet_map = cfg.get('grup_tarif_warnet', {}) or {}
            for g in warnet_map.keys():
                if g not in names:
                    names.append(g)
            # Ensure "Warnet" group is first if it exists
            if 'Warnet' in names:
                names.remove('Warnet')
                names.insert(0, 'Warnet')
            return names or [NAMA_GRUP_DEFAULT]
        # Default (for PS/TV): exclude warnet-only groups
        names = [g for g in (self.grup_tarif.keys() if getattr(self, 'grup_tarif', None) else []) if g not in warnet_only]
        return names or [NAMA_GRUP_DEFAULT]

    def daftar_semua_grup(self):
        """Return list of ALL group names untuk Kontrol Harga (shared + warnet).
        User bisa edit harga untuk semua grup.
        """
        cfg = ConfigManager.load()
        names = list(self.grup_tarif.keys()) if getattr(self, 'grup_tarif', None) else []
        # Include warnet-specific groups
        warnet_map = cfg.get('grup_tarif_warnet', {}) or {}
        for g in warnet_map.keys():
            if g not in names:
                names.append(g)
        return names or [NAMA_GRUP_DEFAULT]

    # ── Login ──────────────────────────────────────────────────────────────────
    def _show_login(self):
        self.geometry("560x760")
        self.resizable(False, False)
        for w in self.winfo_children():
            w.destroy()
        login = LoginPage(self, on_login_success=self._on_login)
        login.pack(fill="both", expand=True)

    def _on_login(self, username, role):
        self.current_user = username
        self.current_role = role
        self.geometry("1280x800")
        self.resizable(True, True)
        self.state("zoomed")
        for w in self.winfo_children():
            w.destroy()
        self._build_layout()
        self._cek_adb_global_saat_start()
        self._cek_lisensi_saat_start()
        # Start background update checker (non-blocking)
        try:
            threading.Thread(target=self._start_update_checker, daemon=True).start()
        except Exception:
            pass

    def _cek_adb_global_saat_start(self):
        if not ADBHelper.adb_tersedia():
            self.after(500, lambda: messagebox.showwarning(
                "⚠ ADB Tidak Ditemukan",
                "Binary 'adb' tidak ditemukan di PATH sistem.\n"
                "Koneksi ke TV tidak akan berfungsi sampai adb terinstall."))

    def _cek_lisensi_saat_start(self):
        status = LicenseManager.get_status(current_user=self.current_user or "")
        if status["status"] == "expired":
            # Disable semua tab kecuali Aktivasi
            for tab_key, btn in self.nav_btns.items():
                if tab_key != "aktivasi":
                    btn.configure(state="disabled", text_color=C_MUTED)
            
            # Tampilkan warning
            self.after(600, lambda: messagebox.showwarning(
                "⚠ LISENSI HABIS — AKSES TERBATAS",
                f"{status['pesan']}\n\n"
                f"Semua fitur telah dikunci.\n"
                f"Silakan aktifkan lisensi untuk melanjutkan menggunakan aplikasi."))
            
            # Paksa show tab Aktivasi
            self.after(700, lambda: self._show_tab("aktivasi"))

    # ── Layout ─────────────────────────────────────────────────────────────────
    def _build_layout(self):
        self.sidebar = ctk.CTkFrame(self, width=185, fg_color=C_PANEL, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.content = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        self.content.pack(side="left", fill="both", expand=True)

        self._build_sidebar()

        self.frames = {}
        for name in ["dashboard", "warnet", "harga", "riwayat", "wifi", "aktivasi", "profil", "log_aplikasi", "users"]:
            f = ctk.CTkFrame(self.content, fg_color=C_BG, corner_radius=0)
            self.frames[name] = f

        self._setup_dashboard()
        self._setup_warnet()
        self._setup_harga()
        self._setup_riwayat()
        self._setup_wifi()
        self._setup_aktivasi()
        self._setup_profil()
        self._setup_log_aplikasi()
        # Admin-only users management tab - DISABLED
        # self._setup_users()
        self._show_tab("dashboard")

    def _build_sidebar(self):
        self._sidebar_text_widgets = []

        # Toggle button
        logo_f = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_f.pack(pady=(22, 6))

        # ── LOGO SIDEBAR: coba logo.png, fallback emoji ───────────────────────
        ico_bg = ctk.CTkFrame(logo_f, fg_color=C_PANEL, corner_radius=10,
                               width=128, height=54)
        ico_bg.pack()
        ico_bg.pack_propagate(False)

        ctk_img_sidebar = load_ctk_image(size=(120, 46))
        if ctk_img_sidebar:
            lbl_sb_logo = ctk.CTkLabel(ico_bg, text="", image=ctk_img_sidebar)
        else:
            lbl_sb_logo = ctk.CTkLabel(ico_bg, text="🎮", font=("Arial", 24))
        lbl_sb_logo.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(logo_f, text="RR BILLING",
                     font=("Russo One", 13, "bold"),
                     text_color=C_ACCENT, justify="center").pack(pady=(6, 0))
        ctk.CTkLabel(logo_f, text="PRO",
                     font=("Russo One", 11, "bold"),
                     text_color=C_ACCENT2).pack()

        status = LicenseManager.get_status(current_user=self.current_user or "")
        lic_color = C_GREEN if status["status"] == "active" else C_YELLOW if status["status"] == "trial" else C_RED
        self.lbl_sidebar_license_status = ctk.CTkLabel(self.sidebar, text=status["pesan"],
                                                       font=("Courier New", 10), text_color=lic_color,
                                                       wraplength=165)
        self.lbl_sidebar_license_status.pack(pady=(2, 10))

        ctk.CTkLabel(self.sidebar, text=f"👤 {self.current_user} [{self.current_role}]",
                     font=("Courier New", 10), text_color=C_MUTED).pack(pady=(0, 10))

        sep = ctk.CTkFrame(self.sidebar, height=1, fg_color=C_BORDER)
        sep.pack(fill="x", padx=10, pady=4)

        nav_items = [
            ("📺", "Dashboard TV",    "dashboard"),
            ("🖥️", "Dashboard Warnet", "warnet"),
            ("💰", "Kontrol Harga",   "harga"),
            ("📜", "Riwayat",         "riwayat"),
            ("📶", "Koneksi WiFi",    "wifi"),
            ("🔓", "Aktivasi",        "aktivasi"),
            ("👤", "Profil",          "profil"),
            ("📋", "Log Aplikasi",    "log_aplikasi"),
        ]
        self.nav_btns = {}
        for ico, label, key in nav_items:
            row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(row, text=ico, font=("Segoe UI Emoji", 14),
                         width=28, anchor="center").pack(side="left", padx=(2, 0))
            btn = ctk.CTkButton(
                row, text=f"  {label}", anchor="w", height=40,
                font=("Russo One", 12, "bold"),
                fg_color="transparent", hover_color="#1E1E4A",
                text_color=C_TEXT, corner_radius=8,
                command=lambda k=key: self._show_tab(k))
            btn.pack(side="left", fill="x", expand=True, padx=(0, 2))
            self.nav_btns[key] = btn

        sep2 = ctk.CTkFrame(self.sidebar, height=1, fg_color=C_BORDER)
        sep2.pack(fill="x", padx=10, pady=(10, 4))

        row_keluar = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        row_keluar.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(row_keluar, text="🚪", font=("Segoe UI Emoji", 14),
                     width=28, anchor="center").pack(side="left", padx=(2, 0))
        ctk.CTkButton(row_keluar, text="  Keluar", anchor="w", height=36,
                      font=("Russo One", 11, "bold"),
                      fg_color="transparent", hover_color="#3A0000",
                      text_color=C_RED, corner_radius=8,
                      command=self._logout).pack(side="left", fill="x", expand=True, padx=(0, 2))

        row_update = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        row_update.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(row_update, text="🔄", font=("Segoe UI Emoji", 14),
                     width=28, anchor="center").pack(side="left", padx=(2, 0))
        ctk.CTkButton(row_update, text="  Update via Git", anchor="w", height=36,
                      font=("Russo One", 11, "bold"),
                      fg_color="transparent", hover_color="#1A4A1A",
                      text_color="#00DD88", corner_radius=8,
                      command=self._on_git_update).pack(side="left", fill="x", expand=True, padx=(0, 2))

        ctk.CTkLabel(self.sidebar, text=f"v{APP_VERSION} — 2026",
                     font=("Courier New", 10), text_color=C_MUTED).pack(side="bottom", pady=12)

    def _logout(self):
        if messagebox.askyesno("Keluar", "Yakin ingin keluar / ganti akun?"):
            AuditLogger.log(
                action="logout",
                username=self.current_user or "",
                status="success",
                details={"role": self.current_role or ""}
            )
            self._show_login()

    def _on_check_update(self):
        """Triggered by UI button. Reads manifest URL from config and runs check in background."""
        manifest = ConfigManager.get('update_manifest_url')
        if not manifest or manifest.strip() == "":
            messagebox.showinfo("Cek Pembaruan", 
                "Fitur pembaruan belum dikonfigurasi.\n\n"
                "Untuk mengaktifkan:\n"
                "1. Upload manifest.json ke GitHub release\n"
                "2. Setel 'update_manifest_url' di config.json")
            return
        # Run in thread to avoid blocking UI
        threading.Thread(target=self._check_update_thread, args=(manifest,), daemon=True).start()

    def _check_update_thread(self, manifest_url: str):
        try:
            from scripts import check_update
            pubkey = ConfigManager.get('update_pubkey_path') or os.path.join(os.path.dirname(__file__), 'update_pubkey.pem')
            app_exe = os.path.abspath(__file__)
            res = check_update.check_for_update(manifest_url, pubkey, current_version=APP_VERSION, app_exe_path=app_exe)
            # res is a user-friendly message
            self.after(0, lambda: messagebox.showinfo("Cek Pembaruan", res))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Cek Pembaruan - Error", str(e)))
    
    def _on_git_update(self):
        """Check and update via Git, run in background thread."""
        threading.Thread(target=self._git_update_thread, daemon=True).start()
    
    def _git_update_thread(self):
        """Background thread untuk check dan update via Git."""
        try:
            from scripts.git_updater import GitUpdater
            
            repo_path = os.path.dirname(os.path.abspath(__file__))
            updater = GitUpdater(repo_path, remote="origin", branch="master")
            
            has_update, msg, info = updater.check_for_updates()
            
            if not has_update:
                self.after(0, lambda: messagebox.showinfo("📡 Update Git", msg))
                return
            
            commits_info = ""
            if info and info.get("commits_info"):
                commits_info = f"\n\nCommit:\n{info['commits_info'][:500]}"
            
            confirm_msg = (
                f"{msg}\n"
                f"Local: {info['local_commit']} → Remote: {info['remote_commit']}"
                f"{commits_info}\n\n"
                "Lanjutkan update dan restart aplikasi?"
            )
            
            # Tanya user via main thread
            import threading as _th
            ev = _th.Event()
            res = [False]
            def _ask():
                res[0] = messagebox.askyesno("📡 Update via Git", confirm_msg)
                ev.set()
            self.after(0, _ask)
            ev.wait()
            
            if not res[0]:
                self.after(0, lambda: messagebox.showinfo("Dibatalkan", "Update dibatalkan."))
                return
            
            # Pull updates
            self.after(0, lambda: messagebox.showinfo(
                "Sedang Update", "Sedang pull updates dari Git...\nSilakan tunggu..."))
            success, pull_msg = updater.pull_updates()
            
            if not success:
                self.after(0, lambda: messagebox.showerror("❌ Update Error", f"Update gagal:\n{pull_msg}"))
                return
            
            AuditLogger.log(
                action="system_update",
                username=self.current_user or "system",
                status="success",
                details={"type": "git", "message": pull_msg}
            )
            
            self.after(0, lambda: messagebox.showinfo(
                "✅ Update Berhasil",
                f"Update berhasil!\n\n{pull_msg}\n\nAplikasi akan restart sekarang..."))
            self.after(2000, lambda: self._do_restart())
            
        except ImportError as e:
            self.after(0, lambda: messagebox.showerror(
                "❌ Module Error",
                f"Git updater module tidak ditemukan:\n{e}\n\n"
                "Pastikan scripts/git_updater.py ada."
            ))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("❌ Error", f"Update error:\n{str(e)}"))

    def _show_tab(self, key):
        status = LicenseManager.get_status(current_user=self.current_user or "")
        if status["status"] == "expired" and key != "aktivasi":
            messagebox.showwarning(
                "⚠ AKSES TERBATAS",
                "Lisensi Anda telah habis. Silakan aktifkan lisensi untuk mengakses fitur lain.")
            self._show_tab("aktivasi")
            return
        
        self.current_tab = key
        for k, f in self.frames.items():
            f.pack_forget()
        self.frames[key].pack(fill="both", expand=True)
        for k, btn in self.nav_btns.items():
            btn.configure(fg_color=C_ACCENT2 if k == key else "transparent",
                          text_color="white" if k == key else C_TEXT)

    def get_paket_data(self, nama_grup=None, for_warnet=False):
        """Return paket dict for a group.
        If for_warnet=True, prefer warnet-specific groups stored under config key
        'grup_tarif_warnet'. Falls back to shared grup_tarif or standard paket.
        """
        cfg = ConfigManager.load()
        if for_warnet:
            warnet_map = cfg.get('grup_tarif_warnet', {}) or {}
            # Jika ada konfigurasi grup tarif khusus warnet, gunakan itu sepenuhnya
            if warnet_map:
                # support case-insensitive lookup: coba kecocokan exact, lalu lowercase-match
                k_found = None
                if nama_grup:
                    # exact match first
                    if nama_grup in warnet_map:
                        grp = warnet_map[nama_grup]
                        k_found = nama_grup
                    else:
                        # try case-insensitive match
                        lower_map = {k.lower(): k for k in warnet_map.keys()}
                        k_found = lower_map.get(nama_grup.lower()) if isinstance(nama_grup, str) else None
                        grp = warnet_map[k_found] if k_found else None
                    if grp is not None:
                        if isinstance(grp, dict):
                            result = {k: {"harga": int(v.get("harga", 0)), "menit": int(v.get("menit", 0))} for k, v in grp.items()}
                        else:
                            result = {k: {"harga": int(v), "menit": 60} for k, v in grp.items()}
                        return result
                # Jika nama_grup tidak diberikan atau tidak ditemukan, kembalikan grup pertama dari konfigurasi warnet
                first = next(iter(warnet_map.values()))
                if isinstance(first, dict):
                    return {k: {"harga": int(v.get("harga", 0)), "menit": int(v.get("menit", 0))} for k, v in first.items()}
                else:
                    return {k: {"harga": int(v), "menit": 60} for k, v in first.items()}
            # Jika tidak ada konfigurasi warnet sama sekali, jangan ambil dari grup PS — kembalikan kosong
            return {}
        
        # Default behavior: use shared grup_tarif, tapi juga cek warnet grup jika ada
        if nama_grup:
            # Check shared grup_tarif first
            if nama_grup in self.grup_tarif:
                return {k: dict(v) for k, v in self.grup_tarif[nama_grup].items()}
            # Check warnet-specific groups (untuk Kontrol Harga access)
            warnet_map = cfg.get('grup_tarif_warnet', {}) or {}
            if nama_grup in warnet_map:
                grp = warnet_map[nama_grup]
                if isinstance(grp, dict):
                    return {k: {"harga": int(v.get("harga", 0)), "menit": int(v.get("menit", 0))} for k, v in grp.items()}
                else:
                    return {k: {"harga": int(v), "menit": 60} for k, v in grp.items()}
        
        if NAMA_GRUP_DEFAULT in self.grup_tarif:
            return {k: dict(v) for k, v in self.grup_tarif[NAMA_GRUP_DEFAULT].items()}
        if self.grup_tarif:
            first = next(iter(self.grup_tarif.values()))
            return {k: dict(v) for k, v in first.items()}
        return {k: dict(v) for k, v in _PAKET_STANDAR.items()}

    def get_makanan_data(self): return dict(self.menu_makanan)
    def get_minuman_data(self): return dict(self.menu_minuman)
    def get_semua_kartu(self):  return list(self._semua_kartu_tv)

    def _refresh_dashboard_total_pesanan(self):
        total = sum(getattr(kartu, 'biaya_pesanan', 0) for kartu in self._semua_kartu_tv)
        if hasattr(self, 'lbl_dashboard_total_pesanan'):
            self.lbl_dashboard_total_pesanan.configure(text=f"Total Pesanan: {fmt_rp(total)}")

    def _refresh_riwayat_summary(self):
        # Compute totals split by source
        total_tv = sum(m['total'] for m in self.riwayat_meta if m.get('source') == 'tv')
        total_warnet = sum(m['total'] for m in self.riwayat_meta if m.get('source') == 'warnet')
        total_pesanan = sum(m.get('pesanan_total', 0) for m in self.riwayat_meta)
        total_all = total_tv + total_warnet
        summary_text = (
            f"Total TV: {fmt_rp(total_tv)}  |  Total Warnet: {fmt_rp(total_warnet)}  |  "
            f"Total Pesanan Makanan/Minuman: {fmt_rp(total_pesanan)}  |  TOTAL: {fmt_rp(total_all)}"
        )
        # Keep a short summary in the left label as before
        short_text = f"Total Transaksi: {len(self.riwayat_transaksi)}  |  Total Pendapatan: {fmt_rp(total_all)}"
        self.lbl_rekap.configure(text=short_text)
        if hasattr(self, 'lbl_rekap_footer'):
            # show full breakdown in footer
            self.lbl_rekap_footer.configure(text=summary_text)

    # ══════════════════════════════════════════════════════════════════════════
    #  TAB 1: Dashboard
    # ══════════════════════════════════════════════════════════════════════════
    def _setup_warnet(self):
        f = self.frames["warnet"]
        hdr = ctk.CTkFrame(f, fg_color=C_PANEL, height=54, corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="💻  DASHBOARD WARNET",
                     font=FONT_TITLE, text_color=C_ACCENT).pack(side="left", padx=18, pady=14)
        self.lbl_total_warnet = ctk.CTkLabel(hdr, text="Total Kursi: 0",
                                             font=FONT_BODY, text_color=C_MUTED)
        self.lbl_total_warnet.pack(side="left", padx=20)
        self.lbl_socket_warnet = ctk.CTkLabel(hdr, text="Client: Belum tersambung",
                                               font=FONT_BODY, text_color=C_MUTED)
        self.lbl_socket_warnet.pack(side="left", padx=12)
        self.btn_warnet_demo = ctk.CTkButton(hdr, text="🧪 Demo Warnet", width=140, height=34,
                                            fg_color=C_BTN, hover_color=C_ACCENT2,
                                            border_width=1, border_color=C_ACCENT2,
                                            font=("Russo One", 10, "bold"),
                                            text_color=C_ACCENT2,
                                            command=self._tambah_warnet_demo)
        self.btn_warnet_demo.pack(side="right", padx=10, pady=10)
        self.btn_tambah_warnet = ctk.CTkButton(hdr, text="➕  Tambah Kursi", width=150, height=34,
                                             fg_color=C_ACCENT2, hover_color="#5A0FCC",
                                             font=("Russo One", 10, "bold"),
                                             command=self._buka_dialog_tambah_warnet)
        self.btn_tambah_warnet.pack(side="right", padx=8, pady=10)
        self.btn_socket_warnet = ctk.CTkButton(hdr, text="⚙ Config Client", width=145, height=34,
                                               fg_color=C_BTN, hover_color=C_ACCENT2,
                                               border_width=1, border_color=C_ACCENT2,
                                               font=("Russo One", 10, "bold"),
                                               text_color=C_ACCENT2,
                                               command=self._open_socket_warnet_config)
        self.btn_socket_warnet.pack(side="right", padx=8, pady=10)
        self.btn_warnet_admin_code = ctk.CTkButton(
            hdr,
            text="🔐 Kode Client",
            width=130,
            height=34,
            fg_color=C_BTN,
            hover_color=C_ACCENT2,
            border_width=1,
            border_color=C_ACCENT2,
            font=("Russo One", 10, "bold"),
            text_color=C_ACCENT2,
            command=self._open_warnet_admin_code_generator,
        )
        self.btn_warnet_admin_code.pack(side="right", padx=8, pady=10)
        self._refresh_warnet_socket_status()
 
        self.scroll_warnet = ctk.CTkScrollableFrame(f, fg_color=C_BG)
        self.scroll_warnet.pack(fill="both", expand=True, padx=6, pady=6)
        cf = ctk.CTkFrame(self.scroll_warnet, fg_color="transparent")
        cf.pack(fill="both", expand=True)
        cf.columnconfigure(0, weight=1); cf.columnconfigure(1, weight=1); cf.columnconfigure(2, weight=1)
        self._grid_container_warnet = cf
        self._col_frames_warnet = []
        for i in range(3):
            col = ctk.CTkFrame(cf, fg_color="transparent")
            col.grid(row=0, column=i, sticky="nsew", padx=2)
            self._col_frames_warnet.append(col)

        footer = ctk.CTkFrame(f, fg_color=C_PANEL, height=40, corner_radius=0)
        footer.pack(fill="x", padx=6, pady=(0, 6))
        footer.pack_propagate(False)
        self.lbl_warnet_total_pendapatan = ctk.CTkLabel(footer,
                                                       text="Total Pendapatan Warnet: Rp 0",
                                                       font=FONT_BODY, text_color=C_YELLOW)
        self.lbl_warnet_total_pendapatan.pack(side="right", padx=18, pady=8)

    def _setup_dashboard(self):
        f = self.frames["dashboard"]
        hdr = ctk.CTkFrame(f, fg_color=C_PANEL, height=54, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="📺  DASHBOARD TV",
                     font=FONT_TITLE, text_color=C_ACCENT).pack(side="left", padx=18, pady=14)
        self.lbl_total_tv = ctk.CTkLabel(hdr, text="Total TV: 0",
                                          font=FONT_BODY, text_color=C_MUTED)
        self.lbl_total_tv.pack(side="left", padx=20)
        self.btn_demo = ctk.CTkButton(hdr, text="🧪 Demo TV", width=140, height=34,
                                      fg_color=C_BTN, hover_color=C_ACCENT2,
                                      border_width=1, border_color=C_ACCENT2,
                                      font=("Russo One", 10, "bold"),
                                      text_color=C_ACCENT2,
                                      command=self._tambah_tv_demo)
        self.btn_demo.pack(side="right", padx=10, pady=10)
        self.btn_tambah = ctk.CTkButton(hdr, text="➕  Tambah TV", width=150, height=34,
                                         fg_color=C_ACCENT2, hover_color="#5A0FCC",
                                         font=("Russo One", 10, "bold"),
                                         command=self._buka_dialog_tambah)
        self.btn_tambah.pack(side="right", padx=8, pady=10)
        self.scroll_dash = ctk.CTkScrollableFrame(f, fg_color=C_BG)
        self.scroll_dash.pack(fill="both", expand=True, padx=6, pady=6)
        cf = ctk.CTkFrame(self.scroll_dash, fg_color="transparent")
        cf.pack(fill="both", expand=True)
        cf.columnconfigure(0, weight=1); cf.columnconfigure(1, weight=1); cf.columnconfigure(2, weight=1)
        self._grid_container = cf
        self._col_frames = []
        for i in range(3):
            col = ctk.CTkFrame(cf, fg_color="transparent")
            col.grid(row=0, column=i, sticky="nsew", padx=2)
            self._col_frames.append(col)

        footer = ctk.CTkFrame(f, fg_color=C_PANEL, height=40, corner_radius=0)
        footer.pack(fill="x", padx=6, pady=(0, 6))
        footer.pack_propagate(False)
        self.lbl_dashboard_total_pesanan = ctk.CTkLabel(footer,
                                                       text="Total Pesanan: Rp 0",
                                                       font=FONT_BODY, text_color=C_YELLOW)
        self.lbl_dashboard_total_pesanan.pack(side="right", padx=18, pady=8)

    def _unlock_tambah(self):
        self._tambah_btn_enabled = True
        self.btn_tambah.configure(state="normal", text="➕  Tambah TV")

    def _unlock_tambah_warnet(self):
        self._tambah_warnet_btn_enabled = True
        self.btn_tambah_warnet.configure(state="normal", text="➕  Tambah Kursi")

    def _buka_dialog_tambah(self):
        if not self._tambah_btn_enabled: return
        self._tambah_btn_enabled = False
        self.btn_tambah.configure(state="disabled", text="⏳ Menunggu...")
        DialogTambahTV(self, self.jumlah_tv + 1,
                       on_confirm=self._on_tv_confirmed,
                       on_close_cb=self._unlock_tambah,
                       daftar_grup=self.daftar_nama_grup())
 
    def _tambah_tv_demo(self):
        demo_count = sum(1 for k in self._semua_kartu_tv if k.label_tv.startswith("Demo TV")) + 1
        demo_name = f"Demo TV {demo_count}"
        # Pastikan ada grup aktif; fallback ke default jika belum dipilih untuk menghindari AttributeError
        default_group = self._grup_aktif if hasattr(self, '_grup_aktif') else NAMA_GRUP_DEFAULT
        self._tambah_tv(ip="192.168.100.100", nama=demo_name, port=5555, nama_grup=default_group)
 
    def _on_tv_confirmed(self, ip, nama, port, nama_grup):
        self._unlock_tambah()
        self._tambah_tv(ip, nama, port, nama_grup)

    def _tambah_tv(self, ip, nama, port, nama_grup=None):
        nama_grup = nama_grup or NAMA_GRUP_DEFAULT
        self.jumlah_tv += 1
        kolom = (self.jumlah_tv - 1) % 3
        kartu = KartuTV(self._col_frames[kolom], self.jumlah_tv,
                        ip=ip, port=port, label_tv=nama,
                        on_transaksi=self._catat_transaksi,
                        get_paket_data=lambda g=nama_grup: self.get_paket_data(g),
                        get_makanan_data=self.get_makanan_data,
                        get_minuman_data=self.get_minuman_data,
                        get_semua_kartu=self.get_semua_kartu,
                        get_daftar_grup=self.daftar_nama_grup,
                        on_ganti_grup=self._on_kartu_ganti_grup,
                        on_hapus=self._hapus_tv,
                        nama_grup=nama_grup,
                        is_first=(self.jumlah_tv == 1))
        kartu.pack(fill="x", pady=2)
        self._semua_kartu_tv.append(kartu)
        self.lbl_total_tv.configure(text=f"Total TV: {self.jumlah_tv}")
        self._refresh_dashboard_total_pesanan()
  
    def _hapus_tv(self, kartu):
        if not messagebox.askyesno("Hapus TV", f"Yakin hapus '{kartu.label_tv}' dari dashboard?"):
            return
        if kartu in self._semua_kartu_tv:
            self._semua_kartu_tv.remove(kartu)
        try:
            kartu.destroy()
        except Exception:
            pass
        self.jumlah_tv = max(0, self.jumlah_tv - 1)
        self.lbl_total_tv.configure(text=f"Total TV: {self.jumlah_tv}")
        self._refresh_dashboard_total_pesanan()
 
    def _on_kartu_ganti_grup(self, kartu, grup_baru):
        """Saat user mengganti grup tarif sebuah TV: refresh closure get_paket_data
        kartu itu supaya menunjuk ke grup yang baru."""
        kartu.get_paket_data = lambda g=grup_baru: self.get_paket_data(g)

    # ══════════════════════════════════════════════════════════════════════════
    #  TAB 2: Kontrol Harga
    # ══════════════════════════════════════════════════════════════════════════
    def _buka_dialog_tambah_warnet(self):
        if not self._tambah_warnet_btn_enabled: return
        ok_client, msg_client = self._check_warnet_client_connection()
        if not ok_client:
            messagebox.showwarning(
                "Client Belum Siap",
                "Tambah Kursi hanya bisa dilakukan jika Config Client sudah benar\n"
                "dan PC client berhasil terhubung.\n\n"
                f"Detail: {msg_client}",
                parent=self
            )
            return

        self._tambah_warnet_btn_enabled = False
        self.btn_tambah_warnet.configure(state="disabled", text="⏳ Menunggu...")

        # Ambil daftar grup khusus warnet. Jika tidak ada, buat grup default 'Warnet' dari salinan grup aktif
        daftar_warnet = self.daftar_nama_grup(for_warnet=True)
        if not daftar_warnet:
            try:
                cfg = ConfigManager.load()
                shared = cfg.get('grup_tarif', {}) or {}
                # Ambil grup fallback dari grup_tarif jika tersedia, atau paket standar sebagai cadangan
                fallback_group = next(iter(shared.keys())) if shared else NAMA_GRUP_DEFAULT
                source_map = shared.get(fallback_group, _PAKET_STANDAR)
                warnet_map = cfg.get('grup_tarif_warnet', {}) or {}
                # Buat grup 'Warnet' sebagai salinan dari grup fallback
                warnet_map['Warnet'] = {k: dict(v) for k, v in source_map.items()} if isinstance(source_map, dict) else dict(source_map)
                cfg['grup_tarif_warnet'] = warnet_map
                ConfigManager.save(cfg)
                # refresh daftar setelah simpan
                daftar_warnet = self.daftar_nama_grup(for_warnet=True)
            except Exception as e:
                print(f"[WARN] Gagal membuat grup_warnet default: {e}", flush=True)
                daftar_warnet = [NAMA_GRUP_DEFAULT]

        # Buka dialog tambah warnet dengan grup yang hanya berisi grup warnet (dikunci)
        DialogTambahWarnet(self,
                            on_confirm=self._on_warnet_confirmed,
                            on_close_cb=self._unlock_tambah_warnet,
                            daftar_grup=daftar_warnet,
                            lock_group=True)

    def _on_warnet_confirmed(self, nama, nama_grup):
        self._unlock_tambah_warnet()
        self._tambah_warnet(nama=nama, nama_grup=nama_grup)

    def _tambah_warnet_demo(self):
        demo_count = sum(1 for k in getattr(self, '_semua_kartu_warnet', []) if k.label_kursi.startswith("Demo PC")) + 1
        demo_name = f"Demo PC {demo_count}"
        # Ensure warnet tab is visible so user can see the added demo card
        try:
            if hasattr(self, '_show_tab'):
                self._show_tab('warnet')
        except Exception:
            pass

        try:
            # Use first warnet group as demo default if available
            warnet_daftar = self.daftar_nama_grup(for_warnet=True)
            demo_group = warnet_daftar[0] if (warnet_daftar and len(warnet_daftar) > 0) else NAMA_GRUP_DEFAULT
            self._tambah_warnet(nama=demo_name, nama_grup=demo_group)
        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("❌ Demo Warnet Gagal", f"Gagal menambahkan Demo Warnet:\n{e}", parent=self)

    def _tambah_warnet(self, nama, nama_grup=None):
        # Ensure counters and containers exist
        self.jumlah_warnet = getattr(self, 'jumlah_warnet', 0) + 1
        kolom = (self.jumlah_warnet - 1) % 3
        # Default group for warnet: prefer the first warnet-specific group if present,
        # otherwise fall back to supplied nama_grup or current active grup.
        warnet_daftar = self.daftar_nama_grup(for_warnet=True)
        default_group = nama_grup or (warnet_daftar[0] if warnet_daftar else (self._grup_aktif if hasattr(self, '_grup_aktif') else NAMA_GRUP_DEFAULT))
        # Ensure the warnet cards list exists
        if not hasattr(self, '_semua_kartu_warnet'):
            self._semua_kartu_warnet = []
        # Defensive: ensure column frames exist
        if not hasattr(self, '_col_frames_warnet') or not self._col_frames_warnet:
            # Try to create a simple column container in the warnet scroll area if possible
            try:
                cf = ctk.CTkFrame(self.scroll_warnet, fg_color="transparent")
                cf.pack(fill="both", expand=True)
                cf.columnconfigure(0, weight=1)
                self._col_frames_warnet = [cf]
                kolom = 0
            except Exception:
                messagebox.showwarning("⚠ Dashboard Warnet Belum Siap",
                                       "Container untuk kartu Warnet belum dibuat dan tidak dapat dibuat otomatis.",
                                       parent=self)
                return

        kartu = KartuWarnet(self._col_frames_warnet[kolom], self.jumlah_warnet,
                            label_kursi=nama,
                            on_transaksi=self._catat_transaksi,
                            get_paket_data=lambda: self.get_paket_data("Warnet", for_warnet=True),
                            get_makanan_data=self.get_makanan_data,
                            get_minuman_data=self.get_minuman_data,
                            get_semua_kartu=lambda: self._semua_kartu_warnet,
                            get_daftar_grup=lambda: self.daftar_nama_grup(for_warnet=True),
                            on_ganti_grup=self._on_warnet_kartu_ganti_grup,
                            on_hapus=self._hapus_warnet,
                            nama_grup=default_group)
        kartu.pack(fill="x", pady=2)
        self._semua_kartu_warnet.append(kartu)
        try:
            self.lbl_total_warnet.configure(text=f"Total Kursi: {self.jumlah_warnet}")
        except Exception:
            pass
        if hasattr(self, '_refresh_warnet_footer'):
            self._refresh_warnet_footer()

    def _on_warnet_kartu_ganti_grup(self, kartu, grup_baru):
        # Warnet PC dikunci ke grup "Warnet", jadi selalu ambil paket dari "Warnet"
        kartu.get_paket_data = lambda: self.get_paket_data("Warnet", for_warnet=True)
        if not kartu.sesi_kosong() and not kartu.is_bebas:
            # If the kartu already has an active timed session, refresh the displayed total price
            total_pesanan = kartu.biaya_pesanan
            kartu.lbl_paket.configure(
                text=f"{fmt_durasi(int(kartu.sisa_waktu / 60))} | {fmt_rp(kartu.paket_harga_tetap + total_pesanan)}")

    def _hapus_warnet(self, kartu):
        """Hapus sebuah kartu Warnet dari dashboard.
        KartuWarnet._confirm_hapus sudah menanyakan konfirmasi, jadi di sini langsung lakukan penghapusan.
        """
        try:
            # Remove from list if present
            if hasattr(self, '_semua_kartu_warnet') and kartu in self._semua_kartu_warnet:
                try:
                    self._semua_kartu_warnet.remove(kartu)
                except ValueError:
                    pass
            # Destroy widget
            try:
                kartu.destroy()
            except Exception:
                pass
            # Update counters & footer
            self.jumlah_warnet = max(0, getattr(self, 'jumlah_warnet', 1) - 1)
            if hasattr(self, 'lbl_total_warnet'):
                try:
                    self.lbl_total_warnet.configure(text=f"Total Kursi: {self.jumlah_warnet}")
                except Exception:
                    pass
            if hasattr(self, '_refresh_warnet_footer'):
                try:
                    self._refresh_warnet_footer()
                except Exception:
                    pass
            AuditLogger.log(action="hapus_warnet", username=self.current_user or 'system', status='success', details={'label': getattr(kartu, 'label_kursi', 'unknown')})
        except Exception as e:
            AuditLogger.log(action="hapus_warnet", username=self.current_user or 'system', status='failed', details={'error': str(e)})
            try:
                messagebox.showerror("Error", f"Gagal menghapus kursi: {e}", parent=self)
            except Exception:
                pass

    def _refresh_warnet_footer(self):
        # Sum warnet totals from riwayat_meta
        total_warnet = sum(m['total'] for m in self.riwayat_meta if m.get('source') == 'warnet')
        if hasattr(self, 'lbl_warnet_total_pendapatan'):
            self.lbl_warnet_total_pendapatan.configure(text=f"Total Pendapatan Warnet: {fmt_rp(total_warnet)}")
 
    def _refresh_warnet_socket_status(self):
        cfg = self.socket_warnet_config or {}
        enabled = bool(cfg.get('host'))
        if hasattr(self, 'lbl_socket_warnet'):
            if not enabled:
                self.lbl_socket_warnet.configure(
                    text="Client: Belum dikonfigurasi",
                    text_color=C_MUTED
                )
                return

            ok_client, _ = self._check_warnet_client_connection(cfg=cfg, timeout=2)
            self.lbl_socket_warnet.configure(
                text=f"Client: {'Tersambung' if ok_client else 'Belum tersambung'}",
                text_color=C_GREEN if ok_client else C_YELLOW
            )

    def _check_warnet_client_connection(self, cfg=None, timeout=3):
        cfg = cfg or self.socket_warnet_config or {}
        host = (cfg.get('host') or '').strip()
        if not host:
            return False, "Host/IP client belum diisi di Config Client."

        server = getattr(self, 'warnet_server', None)
        if server is None or not getattr(server, 'running', False):
            return False, "Socket server billing belum aktif."

        with server.sessions_lock:
            active_sessions = list(server.sessions.values())

        if not active_sessions:
            return False, "Belum ada PC client yang AUTH/login ke server."

        return True, f"{len(active_sessions)} client aktif terhubung."

    def _open_socket_warnet_config(self):
        DialogSocketConfig(self, config=self.socket_warnet_config,
                           on_save=self._save_socket_warnet_config,
                           on_test=self._test_socket_warnet_config)

    def _open_warnet_admin_code_generator(self):
        DialogWarnetAdminCode(self)
 
    def _save_socket_warnet_config(self, cfg):
        ConfigManager.set('socket_warnet', cfg)
        self.socket_warnet_config = cfg
        self._refresh_warnet_socket_status()
        messagebox.showinfo("✅ Config Client Disimpan", "Konfigurasi koneksi client berhasil disimpan.", parent=self)

    def _test_socket_warnet_config(self, cfg):
        host = (cfg.get('host') or '').strip()
        if not host:
            messagebox.showerror("❌ Test Koneksi Gagal", "Host/IP client belum diisi.", parent=self)
            return

        try:
            port = int(cfg.get('port', DEFAULT_PORT) or DEFAULT_PORT)
        except Exception:
            messagebox.showerror("❌ Test Koneksi Gagal", "Port client tidak valid.", parent=self)
            return

        try:
            with socket.create_connection((host, port), timeout=3):
                pass
            ok, msg = True, f"Port {host}:{port} dapat diakses."
        except socket.timeout:
            ok, msg = False, f"Timeout ke {host}:{port}"
        except ConnectionRefusedError:
            ok, msg = False, f"Koneksi ditolak di {host}:{port}"
        except OSError as e:
            ok, msg = False, f"Gagal konek ke {host}:{port} ({e})"

        if ok:
            messagebox.showinfo("✅ Test Koneksi Berhasil", f"{msg}", parent=self)
        else:
            messagebox.showerror("❌ Test Koneksi Gagal", f"{msg}", parent=self)

    def _run_warnet_socket_command(self, cmd_template, kursi_label):
        cfg = self.socket_warnet_config or ConfigManager.get('socket_warnet', {})
        if not cfg.get('host'):
            return False, "Socket Warnet belum dikonfigurasi."

        if not cmd_template:
            return False, "Perintah Socket belum diatur."

        try:
            cmd = cmd_template.format(kursi=kursi_label, kursi_label=kursi_label, label=kursi_label)
        except Exception:
            cmd = cmd_template

        try:
            port = int(cfg.get('port', DEFAULT_PORT) or DEFAULT_PORT)
        except Exception:
            port = DEFAULT_PORT

        ok, msg = SocketHelper.send(
            cfg.get('host', ''), port, cmd)

        AuditLogger.log(
            action='socket_warnet_command',
            username=self.current_user or 'system',
            status='success' if ok else 'failed',
            details={'host': cfg.get('host'), 'kursi': kursi_label, 'command': cmd, 'result': msg})
        return ok, msg
 
    def _setup_harga(self):
        f = self.frames["harga"]
        hdr = ctk.CTkFrame(f, fg_color=C_PANEL, height=54, corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="⚙️  KONTROL HARGA",
                     font=FONT_TITLE, text_color=C_ACCENT).pack(side="left", padx=18, pady=14)
        ctk.CTkButton(hdr, text="💾 Simpan Semua", width=150, height=34,
                      fg_color="#1A4A1A", hover_color="#0A3A0A",
                      border_width=1, border_color=C_GREEN,
                      font=("Russo One", 10, "bold"), text_color=C_GREEN,
                      command=self._simpan_harga).pack(side="right", padx=18, pady=10)

        self.scroll_harga = ctk.CTkScrollableFrame(f, fg_color=C_BG)
        self.scroll_harga.pack(fill="both", expand=True, padx=14, pady=10)

        self._grup_aktif = self.daftar_nama_grup()[0]
        self._harga_entries = {}
        self._build_kotak_grup_dan_info()
        self._build_harga_section_editable("paket", f"⏱  Paket Waktu Main — Grup: {self._grup_aktif}",
                                            self.grup_tarif[self._grup_aktif])
        self._build_harga_section_editable("makanan", "🍔  Menu Makanan",     self.menu_makanan)
        self._build_harga_section_editable("minuman", "🥤  Menu Minuman",     self.menu_minuman)

    def _refresh_grup_info(self):
        jumlah_tv = sum(1 for k in self._semua_kartu_tv if k.nama_grup == self._grup_aktif)
        jumlah_warnet = sum(1 for k in getattr(self, '_semua_kartu_warnet', []) if k.nama_grup == self._grup_aktif)
        total_pengguna = jumlah_tv + jumlah_warnet
        label_sumber = "TV" if jumlah_warnet == 0 else "TV dan Warnet" if jumlah_tv and jumlah_warnet else "Warnet"
        self.lbl_grup_info.configure(
            text=f"Sedang mengedit harga untuk grup '{self._grup_aktif}'  ·  "
                 f"dipakai oleh {total_pengguna} {label_sumber} saat ini di Dashboard.")

    def _refresh_info_bebas(self):
        tarif_skrg = hitung_tarif_per_menit(self.grup_tarif[self._grup_aktif])
        self.lbl_info_bebas.configure(
            text=f"ℹ️  Tarif 'Main Bebas' grup '{self._grup_aktif}' dihitung otomatis dari paket "
                 f"'{PAKET_ACUAN_BEBAS}'  →  ≈ {fmt_rp(tarif_skrg)} / menit.\n"
                 f"    Ubah harga/durasi paket '{PAKET_ACUAN_BEBAS}' di bawah untuk mengubah tarif Main Bebas grup ini.")

    def _ganti_grup_aktif(self, grup_baru):
        self._simpan_paket_aktif_ke_memori()
        self._grup_aktif = grup_baru
        
        # Jika grup_baru tidak ada di self.grup_tarif (warnet group), muat dari config
        if self._grup_aktif not in self.grup_tarif:
            cfg = ConfigManager.load()
            warnet_map = cfg.get('grup_tarif_warnet', {}) or {}
            if self._grup_aktif in warnet_map:
                self.grup_tarif[self._grup_aktif] = warnet_map[self._grup_aktif]
        
        self._refresh_grup_info()
        self._refresh_info_bebas()
        self._rebuild_harga()

    def _tambah_grup_tarif(self):
        dlg = ctk.CTkInputDialog(text="Nama grup tarif baru (mis. PS5, Room VIP 2):",
                                  title="➕ Tambah Grup Tarif")
        nama_baru = dlg.get_input()
        if not nama_baru:
            return
        nama_baru = nama_baru.strip()
        if not nama_baru:
            return
        if nama_baru in self.grup_tarif:
            messagebox.showwarning("⚠ Sudah Ada", f"Grup '{nama_baru}' sudah ada.")
            return
        # Grup baru dimulai dari salinan paket grup yang sedang aktif, supaya
        # user tinggal sesuaikan harganya saja (tidak mulai dari kosong).
        self.grup_tarif[nama_baru] = {k: dict(v) for k, v in self.grup_tarif[self._grup_aktif].items()}
        self._simpan_paket_aktif_ke_memori()
        self._grup_aktif = nama_baru
        self._simpan_grup_tarif_ke_config()
        self._refresh_opt_grup_semua()
        self._refresh_grup_info()
        self._refresh_info_bebas()
        self._rebuild_harga()
        messagebox.showinfo("✅ Grup Ditambahkan",
                            f"Grup '{nama_baru}' dibuat (salinan harga dari '{self._grup_aktif}').\n"
                            f"Atur harganya lalu klik Simpan Semua.\n\n"
                            f"Grup baru ini langsung tersedia di Dashboard TV saat menambah/ganti TV.")

    def _rename_grup_tarif(self):
        grup_lama = self._grup_aktif
        dlg = ctk.CTkInputDialog(text=f"Nama baru untuk grup '{grup_lama}':",
                                  title="✏️ Ganti Nama Grup")
        nama_baru = dlg.get_input()
        if not nama_baru:
            return
        nama_baru = nama_baru.strip()
        if not nama_baru or nama_baru == grup_lama:
            return
        if nama_baru in self.grup_tarif:
            messagebox.showwarning("⚠ Sudah Ada", f"Grup '{nama_baru}' sudah ada.")
            return
        self._simpan_paket_aktif_ke_memori()
        self.grup_tarif[nama_baru] = self.grup_tarif.pop(grup_lama)
        # TV yang sebelumnya memakai grup lama ikut di-update namanya
        for kartu in self._semua_kartu_tv:
            if kartu.nama_grup == grup_lama:
                kartu.nama_grup = nama_baru
                kartu.lbl_grup.configure(text=f"🏷 {nama_baru}")
                kartu.get_paket_data = lambda g=nama_baru: self.get_paket_data(g)
        self._grup_aktif = nama_baru
        self._simpan_grup_tarif_ke_config()
        self._refresh_opt_grup_semua()
        self._refresh_grup_info()
        self._refresh_info_bebas()
        self._rebuild_harga()

    def _hapus_grup_tarif(self):
        grup = self._grup_aktif
        if grup in GRUP_TERKUNCI or len(self.grup_tarif) <= 1:
            messagebox.showwarning("⚠ Tidak Bisa Dihapus",
                                    f"Grup '{grup}' tidak bisa dihapus "
                                    f"(minimal harus ada 1 grup tersisa).")
            return
        jumlah_tv = sum(1 for k in self._semua_kartu_tv if k.nama_grup == grup)
        pesan = f"Hapus grup tarif '{grup}'?"
        if jumlah_tv:
            pesan += (f"\n\n⚠ {jumlah_tv} TV di Dashboard saat ini memakai grup ini.\n"
                      f"TV tersebut akan otomatis dipindah ke grup '{NAMA_GRUP_DEFAULT}'.")
        if not messagebox.askyesno("🗑 Hapus Grup Tarif", pesan):
            return
        del self.grup_tarif[grup]
        fallback = NAMA_GRUP_DEFAULT if NAMA_GRUP_DEFAULT in self.grup_tarif else next(iter(self.grup_tarif))
        for kartu in self._semua_kartu_tv:
            if kartu.nama_grup == grup:
                kartu.nama_grup = fallback
                kartu.lbl_grup.configure(text=f"🏷 {fallback}")
                kartu.get_paket_data = lambda g=fallback: self.get_paket_data(g)
        for kartu in getattr(self, '_semua_kartu_warnet', []):
            if kartu.nama_grup == grup:
                kartu.nama_grup = fallback
                kartu.lbl_grup.configure(text=f"↻ {fallback}")
                kartu.get_paket_data = lambda g=fallback: self.get_paket_data(g)
        self._grup_aktif = fallback
        self._simpan_grup_tarif_ke_config()
        self._refresh_opt_grup_semua()
        self._refresh_grup_info()
        self._refresh_info_bebas()
        self._rebuild_harga()

    def _refresh_opt_grup_semua(self):
        """Refresh dropdown grup di tab Kontrol Harga setelah daftar grup berubah."""
        daftar = self.daftar_nama_grup()
        self.opt_grup_aktif.configure(values=daftar)
        self.var_grup_aktif.set(self._grup_aktif)

    def _simpan_grup_tarif_ke_config(self):
        cfg = ConfigManager.load()
        cfg["grup_tarif"] = self.grup_tarif
        ConfigManager.save(cfg)

    def _simpan_paket_aktif_ke_memori(self):
        """Tulis perubahan yang sedang diketik user (belum ditekan Simpan Semua)
        kembali ke self.grup_tarif[grup_aktif] sebelum pindah grup/rebuild,
        supaya perubahan yang belum disimpan permanen tidak hilang begitu saja
        saat sekadar berpindah tampilan antar grup."""
        if not hasattr(self, "_harga_entries"):
            return
        hasil = {}
        for (kategori, nama_asli), entry in self._harga_entries.items():
            if kategori != "paket":
                continue
            nama_baru = entry["var_nama"].get().strip() or nama_asli
            if nama_asli == "Main Bebas":
                hasil["Main Bebas"] = {"harga": 0, "menit": 0}
                continue
            try:
                harga_baru = int(entry["var_harga"].get().strip() or 0)
            except ValueError:
                harga_baru = 0
            try:
                jam_baru = int(entry["var_jam"].get().strip() or 0)
            except ValueError:
                jam_baru = 0
            try:
                menit_baru = int(entry["var_menit"].get().strip() or 0)
            except ValueError:
                menit_baru = 0
            hasil[nama_baru] = {"harga": harga_baru, "menit": max(0, jam_baru) * 60 + max(0, menit_baru)}
        if "Main Bebas" not in hasil:
            hasil["Main Bebas"] = {"harga": 0, "menit": 0}
        if hasil and self._grup_aktif in self.grup_tarif:
            self.grup_tarif[self._grup_aktif] = hasil

    def _build_harga_section_editable(self, kategori, judul, menu_dict):
        sec = ctk.CTkFrame(self.scroll_harga, fg_color=C_PANEL, corner_radius=12)
        sec.pack(fill="x", pady=8)
        if kategori == "paket":
            self._frame_paket_section = sec

        hdr_row = ctk.CTkFrame(sec, fg_color="transparent")
        hdr_row.pack(fill="x", padx=16, pady=(10, 6))
        ctk.CTkLabel(hdr_row, text=judul, font=FONT_SUB, text_color=C_ACCENT2).pack(side="left")
        ctk.CTkButton(hdr_row, text="➕ Tambah Item", width=120, height=28,
                      fg_color=C_BTN, border_width=1, border_color=C_GREEN,
                      font=FONT_SMALL, text_color=C_GREEN,
                      command=lambda k=kategori, s=sec: self._tambah_item_harga(k, s)
                      ).pack(side="right")

        # Header kolom khusus untuk paket waktu (ada kolom Jam & Menit)
        if kategori == "paket":
            kol_row = ctk.CTkFrame(sec, fg_color="transparent")
            kol_row.pack(fill="x", padx=16, pady=(0, 2))
            ctk.CTkLabel(kol_row, text="Nama Paket", font=FONT_SMALL, text_color=C_MUTED,
                         width=180, anchor="w").pack(side="left", padx=(0, 8))
            ctk.CTkLabel(kol_row, text="Harga (Rp)", font=FONT_SMALL, text_color=C_MUTED,
                         width=110, anchor="w").pack(side="left", padx=(0, 12))
            ctk.CTkLabel(kol_row, text="Jam", font=FONT_SMALL, text_color=C_MUTED,
                         width=54, anchor="w").pack(side="left", padx=(0, 4))
            ctk.CTkLabel(kol_row, text="Menit", font=FONT_SMALL, text_color=C_MUTED,
                         width=54, anchor="w").pack(side="left", padx=(0, 4))

        container = ctk.CTkFrame(sec, fg_color="transparent")
        container.pack(fill="x", padx=0, pady=(0, 8))
        container.columnconfigure(0, weight=1)

        for nama, val in menu_dict.items():
            self._tambah_row_harga(container, kategori, nama, val, menu_dict)

        if not hasattr(self, '_harga_containers'):
            self._harga_containers = {}
        self._harga_containers[kategori] = (container, menu_dict)

    def _tambah_row_harga(self, container, kategori, nama, val, menu_dict):
        row = ctk.CTkFrame(container, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=3)

        var_nama = ctk.StringVar(value=nama)
        e_nama = ctk.CTkEntry(row, textvariable=var_nama, width=180,
                               fg_color=C_BTN, text_color=C_TEXT,
                               border_color=C_BORDER, font=FONT_BODY)
        e_nama.pack(side="left", padx=(0, 8))

        if kategori == "paket":
            harga = val.get("harga", 0)
            menit_total = val.get("menit", 0)
            jam, menit = divmod(menit_total, 60)
        else:
            harga = val

        var_harga = ctk.StringVar(value=str(harga))
        e_harga = ctk.CTkEntry(row, textvariable=var_harga, width=110,
                                fg_color=C_BTN, text_color=C_ACCENT,
                                border_color=C_BORDER, font=FONT_BODY)
        e_harga.pack(side="left", padx=(0, 4))

        var_jam = None
        var_menit = None
        if kategori == "paket":
            ctk.CTkLabel(row, text="Rp", font=FONT_SMALL, text_color=C_MUTED).pack(side="left", padx=(0, 12))

            is_bebas_row = (nama == "Main Bebas")

            var_jam = ctk.StringVar(value=str(jam))
            e_jam = ctk.CTkEntry(row, textvariable=var_jam, width=54,
                                  fg_color=C_BTN, text_color=C_YELLOW,
                                  border_color=C_BORDER, font=FONT_BODY,
                                  state="disabled" if is_bebas_row else "normal")
            e_jam.pack(side="left", padx=(0, 4))
            ctk.CTkLabel(row, text="jam", font=FONT_SMALL, text_color=C_MUTED).pack(side="left", padx=(0, 10))

            var_menit = ctk.StringVar(value=str(menit))
            e_menit = ctk.CTkEntry(row, textvariable=var_menit, width=54,
                                    fg_color=C_BTN, text_color=C_YELLOW,
                                    border_color=C_BORDER, font=FONT_BODY,
                                    state="disabled" if is_bebas_row else "normal")
            e_menit.pack(side="left", padx=(0, 4))
            ctk.CTkLabel(row, text="menit", font=FONT_SMALL, text_color=C_MUTED).pack(side="left", padx=(0, 12))

            if is_bebas_row:
                e_harga.configure(state="disabled")
                ctk.CTkLabel(row, text="(otomatis dari acuan)", font=FONT_SMALL,
                             text_color=C_GREEN).pack(side="left", padx=(0, 8))
        else:
            ctk.CTkLabel(row, text="Rp", font=FONT_SMALL, text_color=C_MUTED).pack(side="left", padx=(0, 12))

        # Hanya boleh hapus item yang bukan "Main Bebas" (paket inti sistem)
        if not (kategori == "paket" and nama == "Main Bebas"):
            ctk.CTkButton(row, text="🗑", width=32, height=28,
                          fg_color=C_BTN, hover_color=C_RED,
                          font=FONT_SMALL, text_color=C_RED,
                          command=lambda r=row, k=kategori, n=nama, md=menu_dict:
                                  self._hapus_item_harga(r, k, n, md)
                          ).pack(side="left")

        key = (kategori, nama)
        self._harga_entries[key] = {
            "var_nama": var_nama, "var_harga": var_harga,
            "var_jam": var_jam, "var_menit": var_menit, "nama_asli": nama,
        }

    def _tambah_item_harga(self, kategori, sec_frame):
        if kategori == "paket":
            paket_grup = self.grup_tarif[self._grup_aktif]
            nama_baru = f"Paket Baru {len(paket_grup) + 1}"
            paket_grup[nama_baru] = {"harga": 0, "menit": 60}
        elif kategori == "makanan":
            nama_baru = f"Item Baru {len(self._harga_entries)}"
            self.menu_makanan[nama_baru] = 0
        else:
            nama_baru = f"Item Baru {len(self._harga_entries)}"
            self.menu_minuman[nama_baru] = 0

        self._rebuild_harga()
        messagebox.showinfo("✅ Tambah Item",
                            f"Item '{nama_baru}' ditambahkan.\nEdit nama, harga"
                            + (", jam & menit" if kategori == "paket" else "")
                            + " lalu klik Simpan Semua.")

    def _hapus_item_harga(self, row_widget, kategori, nama_asli, menu_dict):
        if kategori == "paket" and nama_asli == "Main Bebas":
            messagebox.showwarning("⚠ Tidak Bisa Dihapus",
                                    "Paket 'Main Bebas' adalah paket inti sistem dan tidak bisa dihapus.")
            return
        if messagebox.askyesno("Hapus Item", f"Hapus '{nama_asli}'?"):
            if kategori == "paket":
                paket_grup = self.grup_tarif[self._grup_aktif]
                if nama_asli in paket_grup:
                    del paket_grup[nama_asli]
            elif kategori == "makanan" and nama_asli in self.menu_makanan:
                del self.menu_makanan[nama_asli]
            elif kategori == "minuman" and nama_asli in self.menu_minuman:
                del self.menu_minuman[nama_asli]
            self._rebuild_harga()

    def _rebuild_harga(self):
        for w in self.scroll_harga.winfo_children():
            w.destroy()
        self._harga_entries = {}
        # Kotak grup tarif & info Main Bebas dibangun ulang juga supaya konsisten
        self._build_kotak_grup_dan_info()
        self._build_harga_section_editable("paket", f"⏱  Paket Waktu Main — Grup: {self._grup_aktif}",
                                            self.grup_tarif[self._grup_aktif])
        self._build_harga_section_editable("makanan", "🍔  Menu Makanan",     self.menu_makanan)
        self._build_harga_section_editable("minuman", "🥤  Menu Minuman",     self.menu_minuman)

    def _build_kotak_grup_dan_info(self):
        grup_box = ctk.CTkFrame(self.scroll_harga, fg_color=C_PANEL, corner_radius=12,
                                 border_width=1, border_color=C_ACCENT2)
        grup_box.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(grup_box, text="🏷  GRUP TARIF (mis. PS3, PS4, Room VIP — masing-masing harga sendiri)",
                     font=FONT_SUB, text_color=C_ACCENT2).pack(anchor="w", padx=16, pady=(12, 6))

        grup_row = ctk.CTkFrame(grup_box, fg_color="transparent")
        grup_row.pack(fill="x", padx=16, pady=(0, 6))
        self.var_grup_aktif = ctk.StringVar(value=self._grup_aktif)
        self.opt_grup_aktif = ctk.CTkOptionMenu(
            grup_row, values=self.daftar_semua_grup(), variable=self.var_grup_aktif,
            fg_color=C_BTN, button_color=C_ACCENT2, button_hover_color="#5A0FCC",
            text_color=C_TEXT, font=("Consolas", 11, "bold"), dropdown_font=FONT_BODY,
            dropdown_fg_color=C_CARD, dropdown_text_color=C_TEXT, width=220,
            command=self._ganti_grup_aktif)
        self.opt_grup_aktif.pack(side="left", padx=(0, 8))

        ctk.CTkButton(grup_row, text="➕ Grup Baru", width=110, height=30,
                      fg_color=C_BTN, border_width=1, border_color=C_GREEN,
                      font=FONT_SMALL, text_color=C_GREEN,
                      command=self._tambah_grup_tarif).pack(side="left", padx=4)
        ctk.CTkButton(grup_row, text="✏️ Ganti Nama", width=110, height=30,
                      fg_color=C_BTN, border_width=1, border_color=C_YELLOW,
                      font=FONT_SMALL, text_color=C_YELLOW,
                      command=self._rename_grup_tarif).pack(side="left", padx=4)
        ctk.CTkButton(grup_row, text="🗑 Hapus Grup", width=110, height=30,
                      fg_color=C_BTN, border_width=1, border_color=C_RED,
                      font=FONT_SMALL, text_color=C_RED,
                      command=self._hapus_grup_tarif).pack(side="left", padx=4)

        self.lbl_grup_info = ctk.CTkLabel(
            grup_box, text="", font=FONT_SMALL, text_color=C_MUTED, justify="left")
        self.lbl_grup_info.pack(anchor="w", padx=16, pady=(0, 12))
        self._refresh_grup_info()

        info_bebas = ctk.CTkFrame(self.scroll_harga, fg_color=C_PANEL, corner_radius=10,
                                   border_width=1, border_color=C_GREEN)
        info_bebas.pack(fill="x", pady=(0, 10))
        self.lbl_info_bebas = ctk.CTkLabel(
            info_bebas, text="", font=FONT_SMALL, text_color=C_GREEN, justify="left")
        self.lbl_info_bebas.pack(anchor="w", padx=14, pady=10)
        self._refresh_info_bebas()

    def _simpan_harga(self):
        new_makanan = {}
        new_minuman = {}
        new_paket_grup_aktif = {}

        for (kategori, nama_asli), entry in self._harga_entries.items():
            nama_baru  = entry["var_nama"].get().strip()
            harga_str  = entry["var_harga"].get().strip()
            if not nama_baru:
                continue

            # "Main Bebas" namanya dikunci, harga & durasi dihitung otomatis (bukan dari input)
            if kategori == "paket" and nama_asli == "Main Bebas":
                new_paket_grup_aktif["Main Bebas"] = {"harga": 0, "menit": 0}
                continue

            try:
                harga_baru = int(harga_str)
            except ValueError:
                harga_baru = 0

            if kategori == "paket":
                try:
                    jam_baru = int(entry["var_jam"].get().strip() or 0)
                except ValueError:
                    jam_baru = 0
                try:
                    menit_baru = int(entry["var_menit"].get().strip() or 0)
                except ValueError:
                    menit_baru = 0
                total_menit = max(0, jam_baru) * 60 + max(0, menit_baru)
                new_paket_grup_aktif[nama_baru] = {"harga": harga_baru, "menit": total_menit}
            elif kategori == "makanan":
                new_makanan[nama_baru] = harga_baru
            elif kategori == "minuman":
                new_minuman[nama_baru] = harga_baru

        # Jaga-jaga: pastikan "Main Bebas" selalu ada walau entry-nya hilang
        if "Main Bebas" not in new_paket_grup_aktif:
            new_paket_grup_aktif["Main Bebas"] = {"harga": 0, "menit": 0}

        if new_paket_grup_aktif:
            self.grup_tarif[self._grup_aktif] = new_paket_grup_aktif
        self.menu_makanan = new_makanan if new_makanan else self.menu_makanan
        self.menu_minuman = new_minuman if new_minuman else self.menu_minuman

        cfg = ConfigManager.load()
        cfg["grup_tarif"]   = self.grup_tarif
        cfg["menu_makanan"] = self.menu_makanan
        cfg["menu_minuman"] = self.menu_minuman
        
        # Sinkronkan grup warnet: jika grup yang diedit juga ada di grup_tarif_warnet, update sana juga
        if 'grup_tarif_warnet' not in cfg:
            cfg['grup_tarif_warnet'] = {}
        warnet_map = cfg['grup_tarif_warnet']
        if self._grup_aktif in warnet_map and new_paket_grup_aktif:
            warnet_map[self._grup_aktif] = new_paket_grup_aktif
        
        ConfigManager.save(cfg)

        # Sinkronkan tampilan Dashboard TV: semua KartuTV yang sedang memakai
        # grup yang baru saja diedit otomatis pakai data harga terbaru
        # (karena get_paket_data closure-nya membaca self.grup_tarif langsung).

        messagebox.showinfo("✅ Tersimpan",
                            f"Harga & durasi untuk grup '{self._grup_aktif}' berhasil disimpan!\n"
                            f"Tarif Main Bebas grup ini sekarang: "
                            f"≈ {fmt_rp(hitung_tarif_per_menit(self.grup_tarif[self._grup_aktif]))}/menit")
        self._refresh_grup_info()
        self._refresh_info_bebas()
        self._rebuild_harga()


    # ══════════════════════════════════════════════════════════════════════════
    #  TAB 3: Riwayat
    # ══════════════════════════════════════════════════════════════════════════
    def _setup_riwayat(self):
        # (riwayat unchanged UI)
        f = self.frames["riwayat"]
        hdr = ctk.CTkFrame(f, fg_color=C_PANEL, height=54, corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="📊  RIWAYAT TRANSAKSI",
                     font=FONT_TITLE, text_color=C_ACCENT).pack(side="left", padx=18, pady=14)

        btn_row = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_row.pack(side="right", padx=18, pady=10)
        ctk.CTkButton(btn_row, text="Export Excel", width=200, height=36,
                      fg_color="#1A4A1A", hover_color="#0A3A0A",
                      border_width=1, border_color=C_GREEN,
                      font=("Russo One", 10, "bold"), text_color=C_GREEN,
                      command=self._export_excel).pack(side="left", padx=4)

        rekap_f = ctk.CTkFrame(f, fg_color=C_PANEL, height=44, corner_radius=0)
        rekap_f.pack(fill="x")
        rekap_f.pack_propagate(False)
        self.lbl_rekap = ctk.CTkLabel(rekap_f, text="Total Transaksi: 0  |  Total Pendapatan: Rp 0",
                                       font=FONT_SUB, text_color=C_YELLOW)
        self.lbl_rekap.pack(side="left", padx=18, pady=10)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Game.Treeview",
                        background=C_CARD, fieldbackground=C_CARD,
                        foreground=C_TEXT, rowheight=28,
                        font=("Consolas", 10))
        style.configure("Game.Treeview.Heading",
                        background=C_PANEL, foreground=C_ACCENT,
                        font=("Russo One", 9, "bold"), relief="flat")
        style.map("Game.Treeview", background=[("selected", C_ACCENT2)])

        cols = ("Waktu", "Kasir", "Kota", "Paket", "Pesanan", "Total")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", style="Game.Treeview")
        widths = [140, 80, 100, 100, 280, 110]
        for col, w in zip(cols, widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor="center" if w < 150 else "w")
        self.tree.pack(fill="both", expand=True, padx=14, pady=(10, 4))
        # Right-click: admin-only action menu (Hapus transaksi)
        self.tree.bind("<Button-3>", self._on_riwayat_right_click)

        footer_f = ctk.CTkFrame(f, fg_color=C_PANEL, height=40, corner_radius=0)
        footer_f.pack(fill="x", padx=14, pady=(0, 12))
        footer_f.pack_propagate(False)
        self.lbl_rekap_footer = ctk.CTkLabel(footer_f,
                                            text="Total Transaksi: 0  |  Total Pendapatan: Rp 0",
                                            font=FONT_SUB, text_color=C_YELLOW)
        self.lbl_rekap_footer.pack(side="left", padx=18, pady=8)

    def _catat_transaksi(self, kota, paket, pesanan, total, source='tv'):
        """Catat transaksi ke riwayat.
        pesanan: dict nama->qty
        kota: string label kursi atau nama TV
        source: 'tv' atau 'warnet'
        total: int (total rupiah)
        """
        waktu       = datetime.now().strftime("%Y-%m-%d %H:%M")
        pesanan = pesanan or {}
        pesanan_str = ", ".join(f"{nm}×{qty}" for nm, qty in pesanan.items()) or "—"

        src = source if source in ('tv', 'warnet') else 'tv'

        # compute pesanan total (money) using menu prices
        all_menu = {**self.menu_makanan, **self.menu_minuman}
        pesanan_total = sum(all_menu.get(nm, 0) * qty for nm, qty in (pesanan.items() if isinstance(pesanan, dict) else []))

        # ensure total is int
        try:
            total_int = int(total)
        except Exception:
            # try to extract from formatted string
            try:
                total_int = int(str(total).replace('Rp ', '').replace('.', '').strip())
            except Exception:
                total_int = pesanan_total

        row = (waktu, self.current_user, kota, paket, pesanan_str, fmt_rp(total_int))
        self.riwayat_transaksi.append(row)
        # maintain parallel meta
        self.riwayat_meta.append({'source': src, 'pesanan_total': pesanan_total, 'total': total_int})

        item_id = self.tree.insert("", 0, values=row)
        self._tree_item_to_index[item_id] = len(self.riwayat_transaksi) - 1

        # refresh summaries
        if hasattr(self, '_refresh_riwayat_summary'):
            self._refresh_riwayat_summary()
        if hasattr(self, '_refresh_warnet_footer'):
            self._refresh_warnet_footer()
        if hasattr(self, '_refresh_dashboard_total_pesanan'):
            self._refresh_dashboard_total_pesanan()

        return item_id

    def _bersihkan_riwayat(self):
        # Hanya admin yang boleh membersihkan seluruh riwayat
        if self.current_role != "admin":
            messagebox.showwarning("Akses Ditolak", "Hanya admin yang boleh membersihkan riwayat.")
            return
        if messagebox.askyesno("Bersihkan Riwayat", "Hapus semua data riwayat dari tampilan?"):
            self.riwayat_transaksi.clear()
            for item in self.tree.get_children():
                self.tree.delete(item)
            summary_text = "Total Transaksi: 0  |  Total Pendapatan: Rp 0"
            self.lbl_rekap.configure(text=summary_text)
            if hasattr(self, 'lbl_rekap_footer'):
                self.lbl_rekap_footer.configure(text=summary_text)

    def _on_riwayat_right_click(self, event):
        # Dapatkan item di bawah kursor
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        values = self.tree.item(iid, "values")
        # Hanya tampilkan opsi hapus jika user adalah admin
        menu = tk.Menu(self.tree, tearoff=0)
        if self.current_role == "admin":
            menu.add_command(label="🗑 Hapus Transaksi (Admin)", command=lambda i=iid: self._ask_admin_and_delete(i))
        else:
            menu.add_command(label="🔒 Akses terbatas", command=lambda: messagebox.showinfo("Akses", "Hanya admin yang dapat menghapus transaksi."))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _rebuild_tree_item_index(self):
        # Rebuild mapping item_id -> riwayat_transaksi index (best-effort by matching row values)
        self._tree_item_to_index.clear()
        items = list(self.tree.get_children())
        for item_id in items:
            vals = tuple(self.tree.item(item_id, 'values'))
            # find matching index in riwayat_transaksi
            idx = None
            for i, r in enumerate(self.riwayat_transaksi):
                if tuple(r) == vals:
                    idx = i
                    break
            if idx is None:
                # fallback: use position-based mapping (assume newest at 0)
                idx = max(0, len(self.riwayat_transaksi) - 1 - items.index(item_id))
            self._tree_item_to_index[item_id] = idx

    def _ask_admin_and_delete(self, iid):
        # Dialog kecil untuk meminta username + password admin untuk otorisasi
        dlg = ctk.CTkToplevel(self)
        dlg.title("Otorisasi Admin")
        dlg.geometry("520x320")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        ctk.CTkLabel(dlg, text="Masukkan akun admin untuk menghapus transaksi", font=FONT_BODY, text_color=C_MUTED).pack(pady=(16,12), padx=16)
        entry_user = ctk.CTkEntry(dlg, placeholder_text="username admin", fg_color=C_BTN, text_color=C_TEXT)
        entry_user.pack(padx=24, pady=(4,10), fill="x")
        entry_pass = ctk.CTkEntry(dlg, placeholder_text="password admin", show="●", fg_color=C_BTN, text_color=C_TEXT)
        entry_pass.pack(padx=24, pady=(0,12), fill="x")
        status = ctk.CTkLabel(dlg, text="", text_color=C_RED)
        status.pack(padx=16, pady=(0,10))

        def submit():
            uname = entry_user.get().strip()
            pwd = entry_pass.get().strip()
            users = ConfigManager.get("users", LoginPage.DEFAULT_USERS)
            u = users.get(uname)
            if not u or u.get("role") != "admin":
                status.configure(text="✖ Akun tidak ditemukan atau bukan admin.")
                AuditLogger.log(action="authorize_delete_failed", username=uname, status="not_admin")
                return
            if not verify_password(pwd, u.get("password","")):
                status.configure(text="✖ Password salah.")
                AuditLogger.log(action="authorize_delete_failed", username=uname, status="bad_password")
                return
            # authorized
            row_values = tuple(self.tree.item(iid, "values"))
            # find index in riwayat_transaksi
            idx = None
            for i, r in enumerate(self.riwayat_transaksi):
                if tuple(r) == row_values:
                    idx = i
                    break
            if idx is not None:
                try:
                    self.riwayat_transaksi.pop(idx)
                except Exception:
                    pass
                try:
                    self.riwayat_meta.pop(idx)
                except Exception:
                    pass
            else:
                # fallback: try to remove by value
                try:
                    self.riwayat_transaksi.remove(list(row_values))
                except Exception:
                    pass
            self.tree.delete(iid)
            AuditLogger.log(action="transaction_deleted", username=uname, status="success", details={"row": row_values})
            dlg.destroy()
            # rebuild index mapping and refresh rekap
            self._rebuild_tree_item_index()
            if hasattr(self, '_refresh_riwayat_summary'):
                self._refresh_riwayat_summary()
            if hasattr(self, 'lbl_rekap_footer'):
                self.lbl_rekap_footer.configure(text=self.lbl_rekap.cget('text'))

        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(8, 16))
        ctk.CTkButton(btn_frame, text="✖ Batal", width=120, height=36,
                      fg_color=C_RED, hover_color="#7A1A1A", command=dlg.destroy).pack(side="left")
        ctk.CTkButton(btn_frame, text="🔒 Authorize & Hapus", width=180, height=36,
                      fg_color=C_ACCENT2, hover_color="#5A0FCC", command=submit).pack(side="right")


    def _export_excel(self):
        if not self.riwayat_transaksi:
            messagebox.showwarning("⚠ Kosong", "Belum ada data transaksi untuk diekspor.", parent=self)
            return

        wb  = openpyxl.Workbook()
        ws  = wb.active
        ws.title = "Riwayat Transaksi"

        header_fill = PatternFill("solid", fgColor="1A1A3A")
        header_font = Font(name="Consolas", bold=True, color="00FFCC", size=11)
        accent_fill = PatternFill("solid", fgColor="12122A")
        normal_font = Font(name="Consolas", size=10)
        center      = Alignment(horizontal="center", vertical="center")
        border      = Border(
            left=Side(style="thin", color="2A2A5A"),
            right=Side(style="thin", color="2A2A5A"),
            top=Side(style="thin", color="2A2A5A"),
            bottom=Side(style="thin", color="2A2A5A"),
        )

        ws.merge_cells("A1:F1")
        ws["A1"] = "LAPORAN TRANSAKSI — RR BILLING PRO"
        ws["A1"].font      = Font(name="Consolas", bold=True, color="00FFCC", size=14)
        ws["A1"].fill      = PatternFill("solid", fgColor="0D0D1A")
        ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 32

        ws.merge_cells("A2:F2")
        ws["A2"] = f"Dicetak: {datetime.now().strftime('%d %B %Y %H:%M')}  |  Kasir: {self.current_user}"
        ws["A2"].font      = Font(name="Consolas", color="6060A0", size=9)
        ws["A2"].fill      = PatternFill("solid", fgColor="0D0D1A")
        ws["A2"].alignment = Alignment(horizontal="center")
        ws.row_dimensions[2].height = 18

        headers = ["Waktu", "Kasir", "Kota/TV", "Paket", "Pesanan Tambahan", "Total"]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=3, column=col, value=h)
            cell.font      = header_font
            cell.fill      = header_fill
            cell.alignment = center
            cell.border    = border
        ws.row_dimensions[3].height = 24

        for r_idx, row in enumerate(self.riwayat_transaksi, 4):
            fill = accent_fill if r_idx % 2 == 0 else PatternFill("solid", fgColor="161628")
            for c_idx, val in enumerate(row, 1):
                cell = ws.cell(row=r_idx, column=c_idx, value=val)
                cell.font      = normal_font
                cell.fill      = fill
                cell.border    = border
                cell.alignment = center if c_idx in (1, 2, 3, 4, 6) else Alignment(vertical="center")

        col_widths = [20, 12, 14, 14, 40, 16]
        for i, w in enumerate(col_widths, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

        last_row = len(self.riwayat_transaksi) + 4
        ws.merge_cells(f"A{last_row}:E{last_row}")
        ws[f"A{last_row}"] = "TOTAL PENDAPATAN"
        ws[f"A{last_row}"].font      = Font(name="Consolas", bold=True, color="FFD700", size=11)
        ws[f"A{last_row}"].fill      = PatternFill("solid", fgColor="1A1A3A")
        ws[f"A{last_row}"].alignment = Alignment(horizontal="right")
        total_tv = sum(m['total'] for m in self.riwayat_meta if m.get('source') == 'tv')
        total_warnet = sum(m['total'] for m in self.riwayat_meta if m.get('source') == 'warnet')
        total_pesanan = sum(m.get('pesanan_total', 0) for m in self.riwayat_meta)
        total_all = total_tv + total_warnet
        ws[f"F{last_row}"] = fmt_rp(total_all)
        ws[f"F{last_row}"].font      = Font(name="Consolas", bold=True, color="FFD700", size=11)
        ws[f"F{last_row}"].fill      = PatternFill("solid", fgColor="1A1A3A")
        ws[f"F{last_row}"].alignment = center

        summary_row = last_row + 1
        for label, amount in [
            ("TOTAL TV", total_tv),
            ("TOTAL WARnet", total_warnet),
            ("TOTAL PESANAN", total_pesanan),
            ("TOTAL KESELURUHAN", total_all),
        ]:
            ws.merge_cells(f"A{summary_row}:E{summary_row}")
            ws[f"A{summary_row}"] = label
            ws[f"A{summary_row}"].font      = Font(name="Consolas", bold=True, color="00FFCC" if label != "TOTAL KESELURUHAN" else "FFD700", size=10)
            ws[f"A{summary_row}"].fill      = PatternFill("solid", fgColor="12122A")
            ws[f"A{summary_row}"].alignment = Alignment(horizontal="right")
            ws[f"F{summary_row}"] = fmt_rp(amount)
            ws[f"F{summary_row}"].font      = Font(name="Consolas", bold=True, color="00FFCC" if label != "TOTAL KESELURUHAN" else "FFD700", size=10)
            ws[f"F{summary_row}"].fill      = PatternFill("solid", fgColor="12122A")
            ws[f"F{summary_row}"].alignment = center
            summary_row += 1

        tgl = datetime.now().strftime("%d-%m-%Y_%H-%M")
        default_name = f"laporan_rr_billing_{tgl}.xlsx"
        docs_dir = os.path.join(os.path.expanduser("~"), "Documents")
        initial_dir = docs_dir if os.path.isdir(docs_dir) else os.path.expanduser("~")

        save_path = filedialog.asksaveasfilename(
            parent=self,
            title="Simpan Laporan Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook", "*.xlsx")],
            initialfile=default_name,
            initialdir=initial_dir
        )

        if not save_path:
            return

        try:
            wb.save(save_path)
        except Exception as e:
            messagebox.showerror("❌ Export Gagal",
                                 f"Gagal menyimpan file Excel:\n{str(e)}",
                                 parent=self)
            return

        messagebox.showinfo("✅ Export Berhasil",
                            f"File berhasil disimpan:\n{save_path}",
                            parent=self)

    # ══════════════════════════════════════════════════════════════════════════
    #  TAB 4: WiFi
    # ══════════════════════════════════════════════════════════════════════════
    def _setup_wifi(self):
        f = self.frames["wifi"]
        hdr = ctk.CTkFrame(f, fg_color=C_PANEL, height=54, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="📡  KONEKSI ADB via Wi-Fi",
                     font=FONT_TITLE, text_color=C_ACCENT).pack(side="left", padx=18, pady=14)
        self.btn_scan = ctk.CTkButton(hdr, text="🔍  Scan Devices", width=150, height=34,
                                       fg_color="#1A3A1A", hover_color="#0A2A0A",
                                       border_width=1, border_color=C_GREEN,
                                       font=("Russo One", 10, "bold"), text_color=C_GREEN,
                                       command=self._wifi_scan_devices)
        self.btn_scan.pack(side="right", padx=18, pady=10)

        scroll = ctk.CTkScrollableFrame(f, fg_color=C_BG)
        scroll.pack(fill="both", expand=True, padx=14, pady=10)

        panduan_f = ctk.CTkFrame(scroll, fg_color=C_PANEL, corner_radius=12)
        panduan_f.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(panduan_f, text="📋  CARA AKTIFKAN ADB Wi-Fi DI ANDROID TV",
                     font=FONT_SUB, text_color=C_ACCENT2).pack(anchor="w", padx=16, pady=(14, 8))

        tabs_panduan = ctk.CTkSegmentedButton(panduan_f, values=["Android TV 11+", "Android TV 10 ↓"],
                                               font=FONT_SMALL,
                                               selected_color=C_ACCENT2, selected_hover_color="#5A0FCC",
                                               unselected_color=C_BTN, unselected_hover_color=C_BORDER,
                                               command=lambda v: self._tampilkan_panduan_wifi(v))
        tabs_panduan.set("Android TV 11+")
        tabs_panduan.pack(fill="x", padx=16, pady=(0, 8))

        self.frame_panduan_11 = ctk.CTkFrame(panduan_f, fg_color="transparent")
        self.frame_panduan_10 = ctk.CTkFrame(panduan_f, fg_color="transparent")

        langkah_11 = [
            ("1", "Pengaturan → Preferensi Perangkat → Tentang", "Klik 'Build' 7x sampai mode developer aktif"),
            ("2", "Pengaturan → Opsi Developer", "Aktifkan 'ADB via Jaringan' / 'Wireless Debugging'"),
            ("3", "Tap 'Pair device with pairing code'", "Catat IP, Port Pairing & Kode PIN"),
            ("4", "Klik tombol 📡 Pairing di bawah", "Isi form → Pair & Connect — selesai otomatis!"),
        ]
        langkah_10 = [
            ("1", "Pengaturan → Preferensi Perangkat → Tentang", "Klik 'Build' 7x sampai mode developer aktif"),
            ("2", "Pengaturan → Opsi Developer", "Aktifkan 'USB debugging' & 'ADB Debugging/Network debugging'"),
            ("3", "Cek IP TV", "Pengaturan → Jaringan & Internet → lihat alamat IP"),
            ("4", "Connect langsung, TANPA pairing", "Isi IP & Port 5555 di form Tambah TV → klik Tes Koneksi"),
        ]
        for parent, langkah in [(self.frame_panduan_11, langkah_11), (self.frame_panduan_10, langkah_10)]:
            for no, judul, sub in langkah:
                row = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=8)
                row.pack(fill="x", padx=14, pady=4)
                ctk.CTkLabel(row, text=no, font=("Russo One", 12, "bold"),
                             text_color=C_BG, fg_color=C_ACCENT2, corner_radius=14,
                             width=28, height=28).pack(side="left", padx=(10, 12), pady=10)
                txt_f = ctk.CTkFrame(row, fg_color="transparent")
                txt_f.pack(side="left", fill="x", expand=True, pady=8)
                ctk.CTkLabel(txt_f, text=judul, font=("Consolas", 10, "bold"),
                             text_color=C_TEXT, anchor="w").pack(anchor="w")
                ctk.CTkLabel(txt_f, text=sub, font=FONT_SMALL,
                             text_color=C_MUTED, anchor="w").pack(anchor="w")
        self.frame_panduan_11.pack(fill="x")
        ctk.CTkFrame(panduan_f, fg_color="transparent", height=8).pack()

        conn_f = ctk.CTkFrame(scroll, fg_color=C_PANEL, corner_radius=12)
        conn_f.pack(fill="x", pady=8)
        ctk.CTkLabel(conn_f, text="🔌  CONNECT MANUAL",
                     font=FONT_SUB, text_color=C_ACCENT2).pack(anchor="w", padx=16, pady=(14, 6))
        input_row = ctk.CTkFrame(conn_f, fg_color="transparent")
        input_row.pack(fill="x", padx=14, pady=(0, 8))
        ctk.CTkLabel(input_row, text="IP :", font=FONT_LABEL, text_color=C_MUTED).pack(side="left", padx=(0, 4))
        self.wifi_entry_ip = ctk.CTkEntry(input_row, placeholder_text="192.168.1.xxx",
                                           fg_color=C_BTN, text_color=C_ACCENT,
                                           border_color=C_BORDER, font=("Consolas", 12, "bold"),
                                           height=34, width=170)
        self.wifi_entry_ip.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(input_row, text="Port :", font=FONT_LABEL, text_color=C_MUTED).pack(side="left", padx=(0, 4))
        self.wifi_entry_port = ctk.CTkEntry(input_row, placeholder_text="5555 / acak",
                                             fg_color=C_BTN, text_color=C_YELLOW,
                                             border_color=C_BORDER, font=("Consolas", 12, "bold"),
                                             height=34, width=100)
        self.wifi_entry_port.pack(side="left", padx=(0, 12))
        self.wifi_entry_port.insert(0, "5555")
        for txt, cmd, color in [
            ("⚡ Connect",    self._wifi_connect,        C_GREEN),
            ("✖ Disconnect", self._wifi_disconnect,     C_RED),
            ("📡 Pairing",   self._wifi_buka_pairing,   C_ACCENT),
        ]:
            ctk.CTkButton(input_row, text=txt, width=100, height=34,
                          fg_color=C_BTN, border_width=1, border_color=color,
                          font=FONT_LABEL, text_color=color,
                          command=cmd).pack(side="left", padx=4)
        ctk.CTkLabel(conn_f, text="Log Output:", font=FONT_LABEL, text_color=C_MUTED).pack(anchor="w", padx=16, pady=(4, 2))
        self.wifi_log = ctk.CTkTextbox(conn_f, height=80, fg_color=C_BTN, text_color=C_GREEN,
                                        font=("Consolas", 10), border_color=C_BORDER, border_width=1)
        self.wifi_log.pack(fill="x", padx=14, pady=(0, 12))
        self.wifi_log.configure(state="disabled")

        scan_f = ctk.CTkFrame(scroll, fg_color=C_PANEL, corner_radius=12)
        scan_f.pack(fill="x", pady=8)
        ctk.CTkLabel(scan_f, text="📟  DEVICES TERDETEKSI",
                     font=FONT_SUB, text_color=C_ACCENT2).pack(anchor="w", padx=14, pady=(12, 6))

        style2 = ttk.Style()
        style2.configure("Wifi.Treeview", background=C_CARD, fieldbackground=C_CARD,
                         foreground=C_TEXT, rowheight=26, font=("Consolas", 10))
        style2.configure("Wifi.Treeview.Heading", background=C_PANEL, foreground=C_ACCENT,
                         font=("Russo One", 9, "bold"), relief="flat")
        cols2 = ("Serial / IP:Port", "Status", "Keterangan")
        self.wifi_tree = ttk.Treeview(scan_f, columns=cols2, show="headings",
                                       style="Wifi.Treeview", height=5)
        for col, w in zip(cols2, [240, 120, 300]):
            self.wifi_tree.heading(col, text=col)
            self.wifi_tree.column(col, width=w, anchor="center" if w < 200 else "w")
        self.wifi_tree.pack(fill="x", padx=14, pady=(0, 14))
        self.wifi_tree.tag_configure("device",       foreground=C_GREEN)
        self.wifi_tree.tag_configure("offline",      foreground=C_RED)
        self.wifi_tree.tag_configure("unauthorized", foreground=C_YELLOW)
        self.wifi_tree.tag_configure("empty",        foreground=C_MUTED)

    def _tampilkan_panduan_wifi(self, pilihan):
        if pilihan == "Android TV 11+":
            self.frame_panduan_10.pack_forget()
            self.frame_panduan_11.pack(fill="x")
        else:
            self.frame_panduan_11.pack_forget()
            self.frame_panduan_10.pack(fill="x")

    def _wifi_buka_pairing(self):
        ip_awal = self.wifi_entry_ip.get().strip()
        def on_pair_done(ip, port):
            self.wifi_entry_ip.delete(0, "end"); self.wifi_entry_ip.insert(0, ip)
            self.wifi_entry_port.delete(0, "end"); self.wifi_entry_port.insert(0, str(port))
            self._wifi_log_tulis(f"✅  Paired & Connected — {ip}:{port}")
            self._wifi_scan_devices()
        DialogPairing(self, ip_awal=ip_awal, on_confirm=on_pair_done)

    def _wifi_log_tulis(self, teks):
        self.wifi_log.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self.wifi_log.insert("end", f"[{ts}]  {teks}\n")
        self.wifi_log.see("end")
        self.wifi_log.configure(state="disabled")

    def _wifi_get_ip_port(self):
        ip  = self.wifi_entry_ip.get().strip()
        raw = self.wifi_entry_port.get().strip()
        port = int(raw) if raw.isdigit() and 1 <= int(raw) <= 65535 else None
        return ip, port

    def _wifi_connect(self):
        ip, port = self._wifi_get_ip_port()
        if not ip or port is None:
            self._wifi_log_tulis("⚠  IP/Port tidak valid.")
            return
        if not ADBHelper.adb_tersedia():
            self._wifi_log_tulis("✖  'adb' tidak ditemukan.")
            return
        self._wifi_log_tulis(f"→  Menghubungkan ke {ip}:{port}...")
        threading.Thread(target=lambda: self.after(0, self._wifi_connect_selesai,
            *ADBHelper.connect(ip, port), ip, port), daemon=True).start()

    def _wifi_connect_selesai(self, sukses, pesan, ip, port):
        if sukses:
            self._wifi_log_tulis(f"✅  Terhubung ke {ip}:{port}")
        else:
            self._wifi_log_tulis(f"✖  Gagal: {pesan}")
        self._wifi_scan_devices()

    def _wifi_disconnect(self):
        ip, port = self._wifi_get_ip_port()
        if not ip: return
        port = port or DEFAULT_PORT
        self._wifi_log_tulis(f"→  Memutus {ip}:{port}...")
        threading.Thread(target=lambda: self.after(0, self._wifi_disconnect_selesai,
            *ADBHelper.disconnect(ip, port), ip, port), daemon=True).start()

    def _wifi_disconnect_selesai(self, ok, pesan, ip, port):
        self._wifi_log_tulis(f"{'✅' if ok else '✖'}  {pesan or f'Disconnected {ip}:{port}'}")
        self._wifi_scan_devices()

    def _wifi_scan_devices(self):
        self.btn_scan.configure(state="disabled", text="⏳ Scanning...")
        threading.Thread(target=self._wifi_scan_thread, daemon=True).start()

    def _wifi_scan_thread(self):
        if not ADBHelper.adb_tersedia():
            self.after(0, self._wifi_scan_selesai, {}, "adb tidak ditemukan")
            return
        devices, err = ADBHelper.list_devices()
        self.after(0, self._wifi_scan_selesai, devices, err)

    def _wifi_scan_selesai(self, devices, err):
        self.btn_scan.configure(state="normal", text="🔍  Scan Devices")
        for item in self.wifi_tree.get_children():
            self.wifi_tree.delete(item)
        if not devices:
            self.wifi_tree.insert("", "end", values=("—", "Tidak ada", "Jalankan Connect dulu"), tags=("empty",))
            return
        ket_map = {
            "device":       "Terhubung & siap",
            "offline":      "Tidak merespon",
            "unauthorized": "Perlu otorisasi di TV",
        }
        for serial, status in devices.items():
            ket = ket_map.get(status, f"Status: {status}")
            tag = status if status in ket_map else "empty"
            self.wifi_tree.insert("", "end", values=(serial, status.upper(), ket), tags=(tag,))
        self._wifi_log_tulis(f"↺  Scan selesai — {len(devices)} device.")

    # ══════════════════════════════════════════════════════════════════════════
    #  TAB 5: AKTIVASI
    # ══════════════════════════════════════════════════════════════════════════
    def _setup_aktivasi(self):
        f = self.frames["aktivasi"]
        hdr = ctk.CTkFrame(f, fg_color=C_PANEL, height=54, corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="🔑  AKTIVASI & BERLANGGANAN",
                     font=FONT_TITLE, text_color=C_ACCENT).pack(side="left", padx=18, pady=14)

        scroll = ctk.CTkScrollableFrame(f, fg_color=C_BG)
        scroll.pack(fill="both", expand=True, padx=20, pady=16)

        status_lic = LicenseManager.get_status(current_user=self.current_user or "")
        status_card = ctk.CTkFrame(scroll, fg_color=C_PANEL, corner_radius=14,
                                    border_width=2,
                                    border_color=C_GREEN if status_lic["status"] == "active"
                                                 else C_YELLOW if status_lic["status"] == "trial"
                                                 else C_RED)
        status_card.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(status_card, text="📋  STATUS LISENSI SAAT INI",
                     font=FONT_SUB, text_color=C_ACCENT2).pack(anchor="w", padx=20, pady=(16, 8))

        ico_status = "✅" if status_lic["status"] == "active" else "🕐" if status_lic["status"] == "trial" else "⛔"
        color_status = C_GREEN if status_lic["status"] == "active" else C_YELLOW if status_lic["status"] == "trial" else C_RED
        ctk.CTkLabel(status_card, text=f"{ico_status}  {status_lic['pesan']}",
                     font=("Russo One", 14, "bold"), text_color=color_status).pack(padx=20, pady=8)

        if status_lic["status"] == "active":
            lic = LicenseManager.load()
            ctk.CTkLabel(status_card, text=f"Kode: {lic.get('kode_aktivasi', '')}  |  Aktif sejak: {lic.get('tgl_aktivasi', '—')[:10]}",
                         font=FONT_SMALL, text_color=C_MUTED).pack(padx=20, pady=(0, 16))
        else:
            ctk.CTkLabel(status_card,
                         text="Aktifkan lisensi untuk menghilangkan batasan trial dan menggunakan semua fitur.",
                         font=FONT_BODY, text_color=C_MUTED, wraplength=700).pack(padx=20, pady=(0, 16))

        akt_card = ctk.CTkFrame(scroll, fg_color=C_PANEL, corner_radius=14)
        akt_card.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(akt_card, text="🔐  MASUKKAN KODE AKTIVASI",
                     font=FONT_SUB, text_color=C_ACCENT2).pack(anchor="w", padx=20, pady=(16, 6))
        ctk.CTkLabel(akt_card, text="Format kode:  RR-XXXX-XXXX-XXXX  (diperoleh setelah pembayaran)",
                     font=FONT_SMALL, text_color=C_MUTED).pack(anchor="w", padx=20, pady=(0, 10))
        akt_row = ctk.CTkFrame(akt_card, fg_color="transparent")
        akt_row.pack(fill="x", padx=20, pady=(0, 12))
        self.entry_kode = ctk.CTkEntry(akt_row, placeholder_text="RR-XXXX-XXXX-XXXX",
                                        fg_color=C_BTN, text_color=C_ACCENT,
                                        border_color=C_BORDER, font=("Consolas", 14, "bold"),
                                        height=42, width=340)
        self.entry_kode.pack(side="left", padx=(0, 12))
        ctk.CTkButton(akt_row, text="🔓  Aktifkan", width=140, height=42,
                      fg_color=C_ACCENT2, hover_color="#5A0FCC",
                      font=("Russo One", 11, "bold"), text_color="white",
                      command=self._lakukan_aktivasi).pack(side="left")
        self.lbl_akt_status = ctk.CTkLabel(akt_card, text="",
                                            font=FONT_BODY, text_color=C_MUTED)
        self.lbl_akt_status.pack(pady=(0, 16))

        bayar_card = ctk.CTkFrame(scroll, fg_color=C_PANEL, corner_radius=14)
        bayar_card.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(bayar_card, text="💰  PAKET BERLANGGANAN",
                     font=FONT_SUB, text_color=C_ACCENT2).pack(anchor="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(bayar_card, text="Klik 'Bayar Sekarang' untuk langsung diarahkan ke WhatsApp Admin",
                     font=("Courier New", 12), text_color=C_MUTED).pack(anchor="w", padx=20, pady=(0, 8))

        paket_langganan = [
            ("Bulanan",   "Rp 99.000 / bulan",  "Semua fitur, 1 lokasi", C_ACCENT,  "💎"),
            ("3 Bulan",   "Rp 249.000",          "Hemat 16% vs bulanan",  C_GREEN,   "🚀"),
            ("Tahunan",   "Rp 799.000 / tahun",  "Hemat 33% — Terbaik!", C_YELLOW,  "👑"),
        ]

        paket_row = ctk.CTkFrame(bayar_card, fg_color="transparent")
        paket_row.pack(fill="x", padx=20, pady=(0, 16))

        for nama, harga, deskripsi, color, ico in paket_langganan:
            card_p = ctk.CTkFrame(paket_row, fg_color=C_CARD, corner_radius=12,
                                   border_width=1, border_color=color)
            card_p.pack(side="left", fill="both", expand=True, padx=8)
            ctk.CTkLabel(card_p, text=ico, font=("Arial", 28)).pack(pady=(16, 4))
            ctk.CTkLabel(card_p, text=nama, font=("Russo One", 13, "bold"),
                         text_color=color).pack()
            ctk.CTkLabel(card_p, text=harga, font=("Consolas", 12, "bold"),
                         text_color=C_TEXT).pack(pady=4)
            ctk.CTkLabel(card_p, text=deskripsi, font=("Courier New", 12),
                         text_color=C_MUTED, wraplength=150).pack(pady=(0, 8))
            ctk.CTkButton(card_p, text="💳 Bayar Sekarang", width=130, height=32,
                          fg_color=color, hover_color=C_ACCENT2,
                          font=FONT_SUB, text_color=C_BG if color in (C_ACCENT, C_GREEN, C_YELLOW) else "white",
                          command=lambda n=nama, h=harga: self._pilih_paket_bayar(n, h)
                          ).pack(pady=(0, 16))

        pay_card = ctk.CTkFrame(scroll, fg_color=C_PANEL, corner_radius=14)
        pay_card.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(pay_card, text="💳  METODE PEMBAYARAN",
                     font=FONT_SUB, text_color=C_ACCENT2).pack(anchor="w", padx=20, pady=(16, 8))

        metode = [
            ("🏦 Transfer Bank BCA",      "6145375553  a/n Rahmadani"),
            ("🏦 Transfer Bank BRI",      "0256 0109 2349 500  a/n Rahmadani"),
            ("💚 GoPay / OVO / Dana",     "0812-7064-7744 a/n Rahmadani (scan QR di bawah)"),
            ("🟦 QRIS",                   "Tersedia di kantor / hubungi admin"),
        ]
        for metode_nm, detail in metode:
            row_m = ctk.CTkFrame(pay_card, fg_color=C_CARD, corner_radius=8)
            row_m.pack(fill="x", padx=20, pady=4)
            ctk.CTkLabel(row_m, text=metode_nm, font=("Consolas", 12, "bold"),
                         text_color=C_TEXT, width=220, anchor="w").pack(side="left", padx=14, pady=10)
            ctk.CTkLabel(row_m, text=detail, font=("Courier New", 12),
                         text_color=C_MUTED).pack(side="left", padx=8)

        ctk.CTkLabel(pay_card,
                     text="💬  Setelah pembayaran, WhatsApp bukti transfer ke 0812-7064-7744\n"
                          "    Admin akan mengirim kode aktivasi dalam 1×24 jam.",
                     font=FONT_SMALL, text_color=C_MUTED, justify="left").pack(
                         anchor="w", padx=20, pady=(8, 4))

        ctk.CTkButton(pay_card, text="📲  Hubungi Admin via WhatsApp", height=36,
                      fg_color="#1A3A1A", hover_color="#0A2A0A",
                      border_width=1, border_color=C_GREEN,
                      font=FONT_SUB, text_color=C_GREEN,
                      command=lambda: webbrowser.open("https://wa.me/6281270647744")
                      ).pack(fill="x", padx=20, pady=(4, 16))

        ctk.CTkLabel(scroll,
                     text="⚠  Aplikasi akan TERKUNCI otomatis setelah masa trial habis.\n"
                          "    Aktifkan lisensi untuk terus menggunakan semua fitur tanpa batasan.",
                     font=FONT_BODY, text_color=C_YELLOW,
                     justify="center").pack(pady=10)

    def _pilih_paket_bayar(self, nama, harga):
        import urllib.parse
        pesan = (
            f"Halo Admin RR Billing Pro 👋\n\n"
            f"Saya ingin berlangganan:\n"
            f"📦 Paket: {nama}\n"
            f"💰 Harga: {harga}\n\n"
            f"Mohon info rekening/QRIS pembayaran. Terima kasih!"
        )
        url = "https://wa.me/6281270647744?text=" + urllib.parse.quote(pesan)
        webbrowser.open(url)

    def _start_update_checker(self, interval_hours: int = 6):
        """Background loop: cek update via manifest URL atau Git setiap interval_hours."""
        manifest = ConfigManager.get('update_manifest_url')
        pubkey = ConfigManager.get('update_pubkey_path') or os.path.join(os.path.dirname(__file__), 'update_pubkey.pem')
        app_exe = os.path.abspath(__file__)
        # Delay awal agar UI tidak kena spam saat startup
        time.sleep(5)
        while True:
            try:
                if manifest and manifest.strip():
                    # Cek via manifest URL
                    try:
                        from scripts import check_update
                        msg = check_update.check_for_update(manifest, pubkey, APP_VERSION, app_exe)
                        if msg and "Versi terbaru terpasang" not in msg:
                            self.after(0, lambda m=msg: messagebox.showinfo("Pembaruan Tersedia", m))
                    except Exception:
                        pass
                else:
                    # Fallback: cek via Git
                    try:
                        from scripts.git_updater import GitUpdater
                        repo_path = os.path.dirname(os.path.abspath(__file__))
                        updater = GitUpdater(repo_path, remote="origin", branch="master")
                        has_update, msg, info = updater.check_for_updates()
                        if has_update:
                            self.after(0, lambda m=msg: messagebox.showinfo(
                                "📡 Update Tersedia",
                                f"{m}\n\nKlik 'Update via Git' di sidebar untuk mengupdate."))
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                time.sleep(interval_hours * 3600)
            except Exception:
                break

    def _do_restart(self):
        """Restart aplikasi dengan benar."""
        try:
            if sys.platform == "win32":
                if getattr(sys, "frozen", False):
                    restart_cmd = [sys.executable]
                else:
                    restart_cmd = [sys.executable, os.path.abspath(__file__)]
                subprocess.Popen(restart_cmd, close_fds=True, **subprocess_no_window_kwargs())
            else:
                # Unix/Linux/Mac
                python_exe = sys.executable
                script_path = os.path.abspath(__file__)
                subprocess.Popen([python_exe, script_path], close_fds=True)
        except Exception as e:
            AuditLogger.log(
                action="restart_error",
                username=self.current_user or "system",
                status="error",
                details={"error": str(e)}
            )
        finally:
            # Keluar dari aplikasi lama
            time.sleep(0.5)
            self.quit()

    def _rebuild_sidebar_lic(self):
        self._refresh_license_ui()

    def _refresh_license_ui(self):
        """Refresh license status labels after activation."""
        status = LicenseManager.get_status(current_user=self.current_user or "")
        lic_color = C_GREEN if status["status"] == "active" else C_YELLOW if status["status"] == "trial" else C_RED
        if getattr(self, "lbl_sidebar_license_status", None) is not None:
            self.lbl_sidebar_license_status.configure(text=status["pesan"], text_color=lic_color)

        # Re-enable semua tab jika lisensi aktif/trial
        if status["status"] in ["active", "trial"]:
            for tab_key, btn in self.nav_btns.items():
                btn.configure(state="normal", text_color=C_TEXT if tab_key != self.current_tab else "white")
        
        if self.frames.get("aktivasi"):
            for child in self.frames["aktivasi"].winfo_children():
                child.destroy()
            self._setup_aktivasi()
            self._show_tab("aktivasi")

    # ══════════════════════════════════════════════════════════════════════════
    #  TAB 6: Profil
    # ══════════════════════════════════════════════════════════════════════════
    def _setup_profil(self):
        f = self.frames["profil"]
        hdr = ctk.CTkFrame(f, fg_color=C_PANEL, height=54, corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="👤  PROFIL & MANAJEMEN USER",
                     font=FONT_TITLE, text_color=C_ACCENT).pack(side="left", padx=18, pady=14)

        scroll = ctk.CTkScrollableFrame(f, fg_color=C_BG)
        scroll.pack(fill="both", expand=True, padx=20, pady=16)

        card = ctk.CTkFrame(scroll, fg_color=C_CARD, corner_radius=16)
        card.pack(fill="x", pady=(0, 16))

        # ── Logo profil: coba logo.png, fallback teks ─────────────────────────
        ctk_img_profil = load_ctk_image(size=(180, 68))
        if ctk_img_profil:
            logo_container = ctk.CTkFrame(card, fg_color=C_CARD, corner_radius=12,
                                           width=190, height=76)
            logo_container.pack(pady=(24, 8))
            logo_container.pack_propagate(False)
            ctk.CTkLabel(logo_container, text="", image=ctk_img_profil).place(
                relx=0.5, rely=0.5, anchor="center")
        else:
            ctk.CTkLabel(card, text="🎮  RR BILLING PRO",
                         font=("Russo One", 18, "bold"), text_color=C_ACCENT).pack(pady=(24, 4))

        ctk.CTkLabel(card, text="RR BILLING PRO" if ctk_img_profil else "",
                     font=("Russo One", 16, "bold"), text_color=C_ACCENT).pack(pady=(4 if ctk_img_profil else 0, 0))
        ctk.CTkLabel(card, text="Sistem Billing Rental PlayStation & TV",
                     font=FONT_BODY, text_color=C_MUTED).pack()
        sep = ctk.CTkFrame(card, height=1, fg_color=C_BORDER)
        sep.pack(fill="x", padx=30, pady=16)
        for label, val in [
            ("Versi",      APP_VERSION),
            ("Developer",  "RR CCTV"),
            ("Kontak",     "0812-7064-7744"),
            ("User Aktif", f"{self.current_user} [{self.current_role}]"),
            ("Lisensi",    LicenseManager.get_status(current_user=self.current_user or "")["pesan"]),
        ]:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=30, pady=3)
            ctk.CTkLabel(row, text=f"{label}:", font=FONT_SUB,
                         text_color=C_MUTED, width=120, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=val, font=FONT_BODY, text_color=C_TEXT).pack(side="left")
        ctk.CTkLabel(card, text="© 2026 RR CCTV — All Rights Reserved",
                     font=FONT_SMALL, text_color=C_MUTED).pack(pady=(16, 24))

        # ── PROFIL RENTAL USER ───────────────────────────────────────────
        rental_card = ctk.CTkFrame(scroll, fg_color=C_PANEL, corner_radius=14)
        rental_card.pack(fill="x", pady=(0, 16))
        
        ctk.CTkLabel(rental_card, text="🏢  PROFIL RENTAL ANDA",
                     font=("Russo One", 12, "bold"), text_color=C_ACCENT).pack(anchor="w", padx=20, pady=(16, 12))
        
        # Get rental profile data
        cfg = ConfigManager.load()
        profil_semua = cfg.get("profil_rental", {})
        profil_user = profil_semua.get(self.current_user, {})
        
        # Display rental profile info
        rental_info = [
            ("🏪 Nama Rental",      profil_user.get("nama_rental", "-")),
            ("👤 Nama Pemilik",     profil_user.get("nama_pemilik", "-")),
            ("📱 No HP / WhatsApp",  profil_user.get("hp", "-")),
            ("📧 Email / Gmail",    profil_user.get("email", "-")),
            ("📍 Alamat Tempat",    profil_user.get("alamat", "-")),
        ]
        
        for label, val in rental_info:
            row = ctk.CTkFrame(rental_card, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=4)
            ctk.CTkLabel(row, text=f"{label}:", font=FONT_LABEL,
                        text_color=C_MUTED, width=140, anchor="w").pack(side="left")
            # Handle long text wrapping
            lbl_val = ctk.CTkLabel(row, text=val, font=FONT_BODY, 
                                   text_color=C_TEXT, wraplength=300, justify="left")
            lbl_val.pack(side="left", anchor="nw", fill="x", expand=True)
        
        ctk.CTkLabel(rental_card, text="",).pack(pady=4)

        if self.current_role == "admin":
            user_card = ctk.CTkFrame(scroll, fg_color=C_PANEL, corner_radius=14)
            user_card.pack(fill="x", pady=(0, 16))

            ctk.CTkLabel(user_card, text="Ganti Password Akun Saya:",
                         font=FONT_LABEL, text_color=C_MUTED).pack(anchor="w", padx=20, pady=(16, 4))
            self.entry_new_pass = ctk.CTkEntry(user_card, placeholder_text="Password baru",
                                                fg_color=C_BTN, text_color=C_ACCENT,
                                                border_color=C_BORDER, font=FONT_BODY,
                                                height=34, show="●", width=240)
            self.entry_new_pass.pack(anchor="w", padx=20, pady=(0, 8))
            ctk.CTkButton(user_card, text="🔒 Simpan Password Baru", width=200, height=34,
                          fg_color=C_ACCENT2, font=FONT_SUB, text_color="white",
                          command=self._ganti_password).pack(anchor="w", padx=20, pady=(0, 16))

    def _ganti_password(self):
        new_pass = self.entry_new_pass.get().strip()
        if len(new_pass) < 6:
            messagebox.showwarning("⚠ Terlalu Pendek", "Password minimal 6 karakter.")
            return
        users = ConfigManager.get("users", LoginPage.DEFAULT_USERS)
        if self.current_user in users:
            users[self.current_user]["password"] = hash_password(new_pass)
            ConfigManager.set("users", users)
            AuditLogger.log(
                action="password_change",
                username=self.current_user,
                status="success",
                details={"initiated_by": "self"}
            )
            messagebox.showinfo("✅ Berhasil", "Password berhasil diubah!")
        else:
            AuditLogger.log(
                action="password_change",
                username=self.current_user or "",
                status="failed",
                details={"reason": "user_not_found"}
            )
            messagebox.showerror("✖ Error", "User tidak ditemukan di config.")

    # ══════════════════════════════════════════════════════════════════════════
    #  TAB: LOG APLIKASI — Viewer lengkap untuk audit log
    # ══════════════════════════════════════════════════════════════════════════
    def _setup_log_aplikasi(self):
        f = self.frames.get("log_aplikasi")
        if not f:
            return
        for w in f.winfo_children():
            w.destroy()
        
        # Header
        hdr = ctk.CTkFrame(f, fg_color=C_PANEL, height=54, corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="📋  LOG APLIKASI LENGKAP", 
                     font=FONT_TITLE, text_color=C_ACCENT).pack(side="left", padx=18, pady=14)
        
        # Filter bar
        filter_frame = ctk.CTkFrame(f, fg_color=C_PANEL, height=44)
        filter_frame.pack(fill="x", padx=0, pady=0)
        filter_frame.pack_propagate(False)
        
        ctk.CTkLabel(filter_frame, text="Filter:", font=FONT_LABEL, 
                     text_color=C_MUTED).pack(side="left", padx=16)
        
        self.log_filter_var = ctk.StringVar(value="all")
        for val, lbl in [("all", "Semua"), ("login", "Login"), ("transaction", "Transaksi"), 
                         ("rental", "Rental"), ("update", "Update"), ("error", "Error")]:
            ctk.CTkRadioButton(filter_frame, text=lbl, variable=self.log_filter_var, 
                              value=val, font=FONT_LABEL, text_color=C_TEXT,
                              command=self._refresh_log_view).pack(side="left", padx=8)
        
        # Main log viewer
        self.log_textbox = ctk.CTkTextbox(f, fg_color=C_BTN, text_color=C_TEXT,
                                          border_color=C_BORDER, border_width=1,
                                          font=("Courier New", 13))
        self.log_textbox.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_textbox.configure(state="disabled")
        
        # Load logs
        self._refresh_log_view()
    
    def _refresh_log_view(self):
        """Refresh dan tampilkan logs berdasarkan filter."""
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        
        try:
            # Baca audit log
            audit_file = "rr_billing_audit.jsonl"
            if not os.path.exists(audit_file):
                self.log_textbox.insert("end", "❌ File audit log tidak ditemukan.\n")
                self.log_textbox.configure(state="disabled")
                return
            
            logs = []
            filter_type = self.log_filter_var.get()
            
            with open(audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        # Filter berdasarkan action
                        if filter_type == "all":
                            logs.append(entry)
                        elif filter_type == "login" and "login" in entry.get("action", ""):
                            logs.append(entry)
                        elif filter_type == "transaction" and "transaksi" in entry.get("action", ""):
                            logs.append(entry)
                        elif filter_type == "rental" and "rental" in entry.get("action", ""):
                            logs.append(entry)
                        elif filter_type == "update" and "update" in entry.get("action", ""):
                            logs.append(entry)
                        elif filter_type == "error" and entry.get("status") == "failed":
                            logs.append(entry)
                    except json.JSONDecodeError:
                        continue
            
            # Sort by timestamp (terbaru di atas)
            logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            
            # Display logs
            if not logs:
                self.log_textbox.insert("end", f"✓ Tidak ada log untuk filter '{filter_type}'.\n")
            else:
                self.log_textbox.insert("end", f"📊 Total: {len(logs)} entri\n" + "="*80 + "\n\n")
                
                for entry in logs:
                    timestamp = entry.get("timestamp", "N/A")
                    action = entry.get("action", "unknown")
                    username = entry.get("username", "system")
                    status = entry.get("status", "unknown")
                    details = entry.get("details", {})
                    
                    # Color based on status
                    if status == "success":
                        status_icon = "✅"
                        status_color = C_GREEN
                    elif status == "failed":
                        status_icon = "❌"
                        status_color = C_RED
                    else:
                        status_icon = "⚠️ "
                        status_color = C_YELLOW
                    
                    log_line = f"{status_icon} [{timestamp}] {action.upper()}\n"
                    log_line += f"   User: {username} | Status: {status}\n"
                    
                    if details:
                        log_line += f"   Details: {json.dumps(details, ensure_ascii=False)[:120]}\n"
                    
                    log_line += "\n"
                    
                    self.log_textbox.insert("end", log_line)
            
            # Footer
            self.log_textbox.insert("end", "\n" + "="*80 + "\n")
            self.log_textbox.insert("end", f"✓ Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            
        except Exception as e:
            self.log_textbox.insert("end", f"❌ Error loading logs: {str(e)}\n")
        
        finally:
            self.log_textbox.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════════════════
    #  TAB: USERS (Admin-only) — CRUD untuk akun kasir/admin
    # ══════════════════════════════════════════════════════════════════════════
    def _setup_users(self):
        f = self.frames.get("users")
        if not f:
            return
        for w in f.winfo_children():
            w.destroy()
        hdr = ctk.CTkFrame(f, fg_color=C_PANEL, height=54, corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="👥  USER MANAGEMENT (Admin)", font=FONT_TITLE, text_color=C_ACCENT).pack(side="left", padx=18, pady=14)

        content = ctk.CTkScrollableFrame(f, fg_color=C_BG)
        content.pack(fill="both", expand=True, padx=16, pady=12)

        form = ctk.CTkFrame(content, fg_color=C_CARD, corner_radius=12)
        form.pack(fill="x", pady=(0,12))
        ctk.CTkLabel(form, text="Buat Akun Baru", font=FONT_SUB, text_color=C_ACCENT2).pack(anchor="w", padx=12, pady=(12,6))
        self.u_username = ctk.CTkEntry(form, placeholder_text="username (a-z0-9_.)", fg_color=C_BTN, text_color=C_TEXT)
        self.u_username.pack(fill="x", padx=12, pady=(0,6))
        self.u_password = ctk.CTkEntry(form, placeholder_text="password (min 8)", show="●", fg_color=C_BTN, text_color=C_TEXT)
        self.u_password.pack(fill="x", padx=12, pady=(0,6))
        self.u_role = ctk.CTkOptionMenu(form, values=["kasir", "admin"], variable=ctk.StringVar(value="kasir"), fg_color=C_BTN, button_color=C_ACCENT2)
        self.u_role.pack(anchor="w", padx=12, pady=(0,12))
        ctk.CTkButton(form, text="➕ Buat Akun", fg_color=C_ACCENT2, command=self._create_user).pack(padx=12, pady=(0,12))

        list_card = ctk.CTkFrame(content, fg_color=C_PANEL, corner_radius=12)
        list_card.pack(fill="both", expand=True)
        ctk.CTkLabel(list_card, text="Daftar User", font=FONT_SUB, text_color=C_ACCENT2).pack(anchor="w", padx=12, pady=(12,6))

        self.user_list_box = ctk.CTkScrollableFrame(list_card, fg_color="transparent")
        self.user_list_box.pack(fill="both", expand=True, padx=12, pady=(0,12))

        self._refresh_user_list()

    def _refresh_user_list(self):
        for w in self.user_list_box.winfo_children():
            w.destroy()
        users = ConfigManager.get("users", LoginPage.DEFAULT_USERS)
        for uname, u in users.items():
            row = ctk.CTkFrame(self.user_list_box, fg_color=C_CARD, corner_radius=8)
            row.pack(fill="x", pady=6)
            ctk.CTkLabel(row, text=f"{uname}", font=FONT_BODY, text_color=C_TEXT).pack(side="left", padx=12)
            ctk.CTkLabel(row, text=f"{u.get('role','kasir')}", font=FONT_SMALL, text_color=C_MUTED).pack(side="left", padx=8)
            if uname != self.current_user:
                ctk.CTkButton(row, text="🗑 Hapus", fg_color=C_RED, command=lambda n=uname: self._delete_user(n)).pack(side="right", padx=8)
                ctk.CTkButton(row, text="🔁 Reset PW", fg_color=C_BTN, command=lambda n=uname: self._reset_user_pw(n)).pack(side="right", padx=8)

    def _create_user(self):
        username = self.u_username.get().strip().lower()
        password = self.u_password.get().strip()
        role = self.u_role.get() if hasattr(self.u_role, 'get') else "kasir"
        if not is_valid_username(username):
            messagebox.showwarning("⚠ Username tidak valid", "Gunakan 4-20 karakter: huruf kecil, angka, ., _")
            return
        if not is_valid_password(password):
            messagebox.showwarning("⚠ Password tidak valid", "Password minimal 8 karakter, berisi huruf dan angka")
            return
        cfg = ConfigManager.load()
        users = cfg.get("users", dict(LoginPage.DEFAULT_USERS))
        if username in users:
            messagebox.showwarning("⚠ Sudah ada", "Username sudah dipakai")
            return
        users[username] = {"password": hash_password(password), "role": role}
        cfg["users"] = users
        ConfigManager.save(cfg)
        AuditLogger.log(action="user_created", username=username, status="success", details={"created_by": self.current_user})
        messagebox.showinfo("✅ Berhasil", f"User '{username}' dibuat sebagai role '{role}'")
        self.u_username.delete(0, 'end')
        self.u_password.delete(0, 'end')
        self._refresh_user_list()

    def _delete_user(self, username):
        if not messagebox.askyesno("Hapus User", f"Hapus user '{username}'? Ini tidak bisa dibatalkan."):
            return
        cfg = ConfigManager.load()
        users = cfg.get("users", {})
        if username in users:
            users.pop(username)
            cfg["users"] = users
            ConfigManager.save(cfg)
            AuditLogger.log(action="user_deleted", username=username, status="success", details={"deleted_by": self.current_user})
            self._refresh_user_list()

    def _reset_user_pw(self, username):
        # Set default temporary password 'changeme123' — admin harus memberi tahu user
        cfg = ConfigManager.load()
        users = cfg.get("users", {})
        if username in users:
            users[username]["password"] = hash_password("changeme123")
            cfg["users"] = users
            ConfigManager.save(cfg)
            AuditLogger.log(action="user_pw_reset", username=username, status="success", details={"reset_by": self.current_user})
            messagebox.showinfo("✅ Reset Pw", f"Password akun '{username}' telah di-reset ke 'changeme123' (mohon ganti segera)")


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = AutoRentApp()
    app.mainloop()
