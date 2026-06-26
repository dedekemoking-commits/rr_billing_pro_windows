import json
import ipaddress
import re
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta
import hashlib
import customtkinter as ctk
try:
    import bcrypt
except ImportError:
    bcrypt = None


SESSION_FILE = "warnet_client_session.json"
PING_INTERVAL_SECONDS = 10
RECONNECT_INTERVAL_SECONDS = 5
CLIENT_IP_REFRESH_INTERVAL_SECONDS = 10
IPCONFIG_REFRESH_INTERVAL_SECONDS = 60
STATUS_POLL_INTERVAL_SECONDS = 2
MAIN_CONFIG_FILE = "rr_billing_config.json"
WARNET_ADMIN_CODE_SECRET = "RR_WARNET_CFG_LOCK_V1"


def generate_warnet_admin_code(client_ip: str, day: datetime = None) -> str:
    ip = (client_ip or "").strip()
    if not ip:
        return ""
    day = day or datetime.now()
    date_key = day.strftime("%Y%m%d")
    digest = hashlib.sha256(f"{ip}|{date_key}|{WARNET_ADMIN_CODE_SECRET}".encode("utf-8")).hexdigest().upper()
    return f"{digest[0:4]}-{digest[8:12]}-{digest[20:24]}"


class WarnetClientProtocol:
    def __init__(self):
        self.sock = None
        self.lock = threading.Lock()

    def connect(self, host: str, port: int):
        self.disconnect()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(6)
        self.sock.connect((host, port))

    def disconnect(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def request(self, message: dict) -> dict:
        if not self.sock:
            raise RuntimeError("Belum terhubung ke server.")
        payload = json.dumps(message).encode("utf-8")
        with self.lock:
            self.sock.sendall(payload)
            raw = self.sock.recv(4096)
        if not raw:
            raise RuntimeError("Koneksi terputus (empty response).")
        return json.loads(raw.decode("utf-8"))

    def auth(self, client_id: str, password: str) -> dict:
        return self.request(
            {
                "type": "AUTH",
                "client_id": client_id,
                "password": password,
                "timestamp": int(time.time()),
            }
        )

    def command(self, session_token: str, pc_id: str, action: str) -> dict:
        return self.request(
            {
                "type": "COMMAND",
                "session_token": session_token,
                "pc_id": pc_id,
                "action": action,
                "timestamp": int(time.time()),
            }
        )
    
    def get_status(self, session_token: str, pc_id: str) -> dict:
        return self.request(
            {
                "type": "GET_STATUS",
                "session_token": session_token,
                "pc_id": pc_id,
                "timestamp": int(time.time()),
            }
        )


class WarnetClientApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Warnet Mini Client")
        self.geometry("380x340")
        self.minsize(360, 320)
        self.attributes("-topmost", True)

        self.protocol_client = WarnetClientProtocol()
        self.reconnect_lock = threading.Lock()
        self.session_token = None
        self.pcs = []
        self.connected = False
        self.should_maintain_connection = False
        self.monitor_running = True
        self.config_panel_visible = False
        self.client_ip_refresh_job = None
        self.last_detected_client_ip = ""
        self.cached_ipv4_candidates = []
        self.cached_ipv4_candidates_at = 0.0
        self.billing_status_poll_job = None
        self.last_billing_status = {}

        self._build_ui()
        self._load_session()
        self._refresh_client_ip_info(self.ent_host.get().strip())
        self._schedule_client_ip_refresh()
        self._tick_clock()
        self._start_connection_monitor()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        shell = ctk.CTkFrame(self, corner_radius=16)
        shell.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(4, weight=1)

        top = ctk.CTkFrame(shell, fg_color=("#252a36", "#1f2430"))
        top.grid(row=0, column=0, padx=8, pady=(8, 6), sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        top.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(top, text="No.", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, padx=(8, 4), pady=(6, 0), sticky="w")
        self.lbl_pc_no = ctk.CTkLabel(top, text="00", font=ctk.CTkFont(size=13, weight="bold"))
        self.lbl_pc_no.grid(row=0, column=1, padx=(0, 6), pady=(6, 0), sticky="w")

        self.btn_disconnect = ctk.CTkButton(top, text="Logout", width=65, height=26, command=self._disconnect)
        self.btn_disconnect.grid(row=0, column=3, padx=(3, 8), pady=(5, 0), sticky="e")

        ctk.CTkLabel(top, text="💰 0", font=ctk.CTkFont(size=12)).grid(row=1, column=0, columnspan=2, padx=8, pady=(3, 8), sticky="w")
        self.lbl_clock = ctk.CTkLabel(top, text="⏳ 00:00:00", font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_clock.grid(row=1, column=2, columnspan=2, padx=8, pady=(3, 8), sticky="e")
        self.lbl_ip_badge = ctk.CTkLabel(top, text="IP: -", anchor="w", font=ctk.CTkFont(size=11))
        self.lbl_ip_badge.grid(row=2, column=0, columnspan=4, padx=8, pady=(0, 8), sticky="w")
        
        # ─── Billing Info Row (Real-time dari server) ───────────────────────
        billing_row = ctk.CTkFrame(top, fg_color=("gray20", "gray15"))
        billing_row.grid(row=3, column=0, columnspan=4, padx=8, pady=(0, 6), sticky="ew")
        billing_row.columnconfigure((0, 1, 2), weight=1)
        
        ctk.CTkLabel(billing_row, text="Paket:", font=ctk.CTkFont(size=10)).grid(row=0, column=0, padx=4, pady=4, sticky="w")
        self.lbl_billing_paket = ctk.CTkLabel(billing_row, text="-", font=ctk.CTkFont(size=10, weight="bold"), text_color="#00FF88")
        self.lbl_billing_paket.grid(row=0, column=0, padx=(50, 4), pady=4, sticky="e")
        
        ctk.CTkLabel(billing_row, text="Sisa:", font=ctk.CTkFont(size=10)).grid(row=0, column=1, padx=4, pady=4, sticky="w")
        self.lbl_billing_time = ctk.CTkLabel(billing_row, text="--:--", font=ctk.CTkFont(size=10, weight="bold"), text_color="#00FF88")
        self.lbl_billing_time.grid(row=0, column=1, padx=(35, 4), pady=4, sticky="e")
        
        ctk.CTkLabel(billing_row, text="Total:", font=ctk.CTkFont(size=10)).grid(row=0, column=2, padx=4, pady=4, sticky="w")
        self.lbl_billing_total = ctk.CTkLabel(billing_row, text="Rp0", font=ctk.CTkFont(size=10, weight="bold"), text_color="#FFD700")
        self.lbl_billing_total.grid(row=0, column=2, padx=(35, 4), pady=4, sticky="e")

        quick = ctk.CTkFrame(shell)
        quick.grid(row=1, column=0, padx=8, pady=6, sticky="ew")
        quick.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        ctk.CTkLabel(quick, text="PC", font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, padx=5, pady=6, sticky="e")
        self.cmb_pc = ctk.CTkComboBox(quick, values=["-"], state="readonly", width=95)
        self.cmb_pc.grid(row=0, column=1, padx=5, pady=6, sticky="w")
        self.cmb_pc.set("-")
        self.btn_on = ctk.CTkButton(quick, text="🟢 ON", width=58, command=lambda: self._send_command("ON"))
        self.btn_on.grid(row=0, column=2, padx=4, pady=6, sticky="ew")
        self.btn_off = ctk.CTkButton(quick, text="🔴 OFF", width=58, command=lambda: self._send_command("OFF"))
        self.btn_off.grid(row=0, column=3, padx=4, pady=6, sticky="ew")
        self.btn_cfg_toggle = ctk.CTkButton(quick, text="⚙", width=36, command=self._toggle_config_panel)
        self.btn_cfg_toggle.grid(row=0, column=4, padx=4, pady=6, sticky="e")

        controls = ctk.CTkFrame(shell)
        controls.grid(row=2, column=0, padx=8, pady=(0, 6), sticky="ew")
        controls.grid_columnconfigure((0, 1, 2), weight=1)
        self.btn_vol_up = ctk.CTkButton(controls, text="🔊 VOL+", command=lambda: self._send_command("VOL+"))
        self.btn_vol_up.grid(row=0, column=0, padx=4, pady=6, sticky="ew")
        self.btn_vol_down = ctk.CTkButton(controls, text="🔉 VOL-", command=lambda: self._send_command("VOL-"))
        self.btn_vol_down.grid(row=0, column=1, padx=4, pady=6, sticky="ew")
        self.sw_topmost = ctk.CTkSwitch(controls, text="Top", command=self._toggle_topmost)
        self.sw_topmost.grid(row=0, column=2, padx=8, pady=6, sticky="e")
        self.sw_topmost.select()

        self.config_panel = ctk.CTkFrame(shell)
        self.config_panel.grid(row=3, column=0, padx=8, pady=(0, 6), sticky="ew")
        self.config_panel.grid_columnconfigure(1, weight=1)
        self.config_panel.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(self.config_panel, text="Server").grid(row=0, column=0, padx=6, pady=5, sticky="w")
        self.ent_host = ctk.CTkEntry(self.config_panel)
        self.ent_host.grid(row=0, column=1, padx=6, pady=5, sticky="ew")
        self.ent_host.insert(0, "127.0.0.1")

        ctk.CTkLabel(self.config_panel, text="Port").grid(row=0, column=2, padx=6, pady=5, sticky="w")
        self.ent_port = ctk.CTkEntry(self.config_panel, width=70)
        self.ent_port.grid(row=0, column=3, padx=6, pady=5, sticky="ew")
        self.ent_port.insert(0, "5000")

        ctk.CTkLabel(self.config_panel, text="Client").grid(row=1, column=0, padx=6, pady=5, sticky="w")
        self.ent_client = ctk.CTkEntry(self.config_panel)
        self.ent_client.grid(row=1, column=1, padx=6, pady=5, sticky="ew")
        self.ent_client.insert(0, "WARNET_01")

        ctk.CTkLabel(self.config_panel, text="Password").grid(row=1, column=2, padx=6, pady=5, sticky="w")
        self.ent_password = ctk.CTkEntry(self.config_panel, show="*")
        self.ent_password.grid(row=1, column=3, padx=6, pady=5, sticky="ew")
        self.ent_password.insert(0, "test123")

        ctk.CTkLabel(self.config_panel, text="IP Nyata PC").grid(row=2, column=0, padx=6, pady=5, sticky="w")
        self.lbl_real_ip = ctk.CTkLabel(self.config_panel, text="-", anchor="w")
        self.lbl_real_ip.grid(row=2, column=1, padx=6, pady=5, sticky="ew")
        self.btn_connect_cfg = ctk.CTkButton(
            self.config_panel, text="Connect Server", height=28, command=self._connect_and_auth
        )
        self.btn_connect_cfg.grid(row=2, column=2, columnspan=2, padx=6, pady=5, sticky="ew")
        self.config_panel.grid_remove()

        log_frame = ctk.CTkFrame(shell)
        log_frame.grid(row=4, column=0, padx=8, pady=(0, 8), sticky="nsew")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        self.txt_log = ctk.CTkTextbox(log_frame, height=80)
        self.txt_log.grid(row=0, column=0, padx=6, pady=6, sticky="nsew")

        bottom = ctk.CTkFrame(shell)
        bottom.grid(row=5, column=0, padx=8, pady=(0, 8), sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=1)
        self.lbl_status = ctk.CTkLabel(bottom, text="Status: Offline", anchor="w")
        self.lbl_status.grid(row=0, column=0, padx=6, pady=4, sticky="w")
        self.lbl_auto_reconnect = ctk.CTkLabel(bottom, text="Auto reconnect: OFF", anchor="e")
        self.lbl_auto_reconnect.grid(row=0, column=1, padx=6, pady=4, sticky="e")
        self.lbl_client_ip = ctk.CTkLabel(bottom, text="IP Client: -", anchor="w")
        self.lbl_client_ip.grid(row=1, column=0, columnspan=2, padx=6, pady=(0, 4), sticky="w")

        self._set_controls_enabled(False)
        self._refresh_client_ip_info()

    def _toggle_config_panel(self):
        if self.config_panel_visible:
            self.config_panel_visible = False
            self.config_panel.grid_remove()
            self.btn_cfg_toggle.configure(text="⚙")
            return

        if not self._request_admin_password():
            return

        self.config_panel_visible = True
        self.config_panel.grid()
        self.btn_cfg_toggle.configure(text="✖")
        self._refresh_client_ip_info(self.ent_host.get().strip())

    def _request_admin_password(self) -> bool:
        dialog = ctk.CTkInputDialog(
            title="Akses Pengaturan",
            text="Masukkan password admin / kode dari server:",
        )
        admin_input = dialog.get_input()
        if admin_input is None:
            self._append_log("Akses pengaturan dibatalkan.")
            return False
        admin_input = admin_input.strip()
        if not admin_input:
            self._append_log("Password/kode admin tidak boleh kosong.")
            return False

        if self._verify_admin_password(admin_input):
            self._append_log("Akses pengaturan diizinkan.")
            return True

        self._append_log("Password/kode admin salah.")
        return False

    def _verify_admin_password(self, plain_password_or_code: str) -> bool:
        # Prioritas 1: cocok sebagai kode generate server berdasarkan IP client.
        if self._verify_generated_admin_code(plain_password_or_code):
            return True

        # Prioritas 2: fallback tetap dukung password admin lama dari config.
        try:
            with open(MAIN_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except FileNotFoundError:
            self._append_log(f"Config {MAIN_CONFIG_FILE} tidak ditemukan.")
            return False
        except json.JSONDecodeError:
            self._append_log(f"Config {MAIN_CONFIG_FILE} rusak.")
            return False
        except OSError as e:
            self._append_log(f"Gagal baca config: {e}")
            return False

        users = cfg.get("users", {})
        if not isinstance(users, dict):
            self._append_log("Format users di config tidak valid.")
            return False

        sha_candidate = hashlib.sha256(plain_password_or_code.encode("utf-8")).hexdigest()

        for _, user_data in users.items():
            if not isinstance(user_data, dict):
                continue
            if user_data.get("role") != "admin":
                continue
            stored = str(user_data.get("password", ""))
            if not stored:
                continue

            if stored.startswith("bcrypt$$"):
                if bcrypt is None:
                    self._append_log("bcrypt belum tersedia untuk verifikasi admin.")
                    continue
                try:
                    if bcrypt.checkpw(plain_password_or_code.encode("utf-8"), stored[7:].encode("utf-8")):
                        return True
                except ValueError:
                    continue
            else:
                if sha_candidate == stored:
                    return True

        return False

    def _get_local_ipv4_candidates(self):
        ips = set()
        try:
            hostname = socket.gethostname()
            for ip in socket.gethostbyname_ex(hostname)[2]:
                normalized = self._normalize_real_ipv4(ip)
                if normalized:
                    ips.add(normalized)
        except Exception:
            pass

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                normalized = self._normalize_real_ipv4(s.getsockname()[0])
                if normalized:
                    ips.add(normalized)
        except OSError:
            pass

        now = time.time()
        if now - self.cached_ipv4_candidates_at >= IPCONFIG_REFRESH_INTERVAL_SECONDS:
            self.cached_ipv4_candidates = self._get_ipv4_candidates_from_ipconfig()
            self.cached_ipv4_candidates_at = now

        for candidate in self.cached_ipv4_candidates:
            normalized = self._normalize_real_ipv4(candidate)
            if normalized:
                ips.add(normalized)

        if not ips:
            ips.add("127.0.0.1")
        return sorted(ips)

    def _get_ipv4_candidates_from_ipconfig(self):
        try:
            startupinfo = None
            creationflags = 0
            if hasattr(subprocess, "STARTUPINFO"):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            output = subprocess.check_output(
                ["ipconfig"],
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
            return re.findall(r"IPv4[^:]*:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", output)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError, ValueError):
            return []

    def _normalize_real_ipv4(self, candidate: str) -> str:
        value = (candidate or "").strip()
        if not value:
            return ""
        try:
            ip_obj = ipaddress.ip_address(value)
        except ValueError:
            return ""
        if ip_obj.version != 4 or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_unspecified:
            return ""
        return value

    def _choose_best_client_ip(self, candidates):
        preferred_private = []
        other_valid = []
        seen = set()

        for candidate in candidates:
            normalized = self._normalize_real_ipv4(candidate)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ip_obj = ipaddress.ip_address(normalized)
            if ip_obj.is_private:
                preferred_private.append(normalized)
            else:
                other_valid.append(normalized)

        if preferred_private:
            return preferred_private[0]
        if other_valid:
            return other_valid[0]

        for candidate in candidates:
            value = (candidate or "").strip()
            if value:
                return value
        return "-"

    def _get_entry_text(self, entry_widget) -> str:
        if not entry_widget:
            return ""
        try:
            if int(entry_widget.winfo_exists()) != 1:
                return ""
            return entry_widget.get().strip()
        except Exception:
            return ""

    def _update_displayed_client_ip(self, ip: str):
        value = (ip or "-").strip() or "-"
        self.lbl_client_ip.configure(text=f"IP Client: {value}")
        self.lbl_ip_badge.configure(text=f"IP: {value}")
        if hasattr(self, "lbl_real_ip"):
            self.lbl_real_ip.configure(text=value)
        if value != self.last_detected_client_ip:
            self.last_detected_client_ip = value
            if value != "-" and hasattr(self, "txt_log"):
                self._append_log(f"IP client terdeteksi: {value}")

    def _verify_generated_admin_code(self, input_code: str) -> bool:
        normalized_input = (input_code or "").strip().upper()
        if not normalized_input:
            return False

        local_ips = self._get_local_ipv4_candidates()
        days = [datetime.now(), datetime.now() - timedelta(days=1)]
        for ip in local_ips:
            for day in days:
                expected = generate_warnet_admin_code(ip, day=day).upper()
                if normalized_input == expected:
                    return True
        return False

    def _toggle_topmost(self):
        self.attributes("-topmost", bool(self.sw_topmost.get()))

    def _set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.btn_on.configure(state=state)
        self.btn_off.configure(state=state)
        self.btn_vol_up.configure(state=state)
        self.btn_vol_down.configure(state=state)
        self.cmb_pc.configure(state="readonly" if enabled else "disabled")

    def _append_log(self, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.txt_log.insert("end", f"[{ts}] {text}\n")
        self.txt_log.see("end")
        current = self.txt_log.get("1.0", "end-1c").splitlines()
        if len(current) > 80:
            self.txt_log.delete("1.0", "2.0")
    
    def _update_billing_display(self, billing_status: dict):
        """Update UI dengan data billing dari server."""
        if not billing_status:
            return
        paket = billing_status.get("paket_aktif", "-")
        time_left = billing_status.get("time_left", 0)
        total_biaya = billing_status.get("total_biaya", 0)
        
        # Format time_left (seconds to MM:SS)
        minutes = time_left // 60
        seconds = time_left % 60
        time_str = f"{minutes:02d}:{seconds:02d}" if time_left > 0 else "--:--"
        
        # Update labels
        try:
            self.lbl_billing_paket.configure(text=paket)
            self.lbl_billing_time.configure(text=time_str)
            self.lbl_billing_total.configure(text=f"Rp{total_biaya:,}".replace(",", "."))
        except Exception:
            pass
    
    def _schedule_billing_status_poll(self):
        """Polling status billing dari server setiap 2 detik."""
        if not self.monitor_running or not self.winfo_exists():
            self.billing_status_poll_job = None
            return
        
        if not self.connected or not self.session_token:
            self.billing_status_poll_job = self.after(STATUS_POLL_INTERVAL_SECONDS * 1000, self._schedule_billing_status_poll)
            return
        
        pc_id = self.cmb_pc.get()
        if not pc_id or pc_id == "-":
            self.billing_status_poll_job = self.after(STATUS_POLL_INTERVAL_SECONDS * 1000, self._schedule_billing_status_poll)
            return
        
        threading.Thread(target=self._fetch_billing_status_worker, args=(pc_id,), daemon=True).start()
        self.billing_status_poll_job = self.after(STATUS_POLL_INTERVAL_SECONDS * 1000, self._schedule_billing_status_poll)
    
    def _fetch_billing_status_worker(self, pc_id: str):
        """Worker thread untuk fetch status billing dari server."""
        try:
            response = self.protocol_client.get_status(self.session_token, pc_id)
            if response.get("status") == "OK":
                billing = response.get("billing", {})
                self.last_billing_status = billing
                self.after(0, lambda: self._update_billing_display(billing))
        except Exception as e:
            pass  # Silent fail, jangan spam log

    def _tick_clock(self):
        self.lbl_clock.configure(text="⏳ " + datetime.now().strftime("%H:%M:%S"))
        self.after(1000, self._tick_clock)

    def _connect_and_auth(self):
        threading.Thread(target=self._connect_and_auth_worker, daemon=True).start()

    def _connect_and_auth_worker(self):
        host = self.ent_host.get().strip()
        port_text = self.ent_port.get().strip()
        client_id = self.ent_client.get().strip()
        password = self.ent_password.get()

        if not host or not port_text or not client_id or not password:
            self.after(0, lambda: self._append_log("ERROR: Server/Port/Client ID/Password wajib diisi."))
            return

        try:
            port = int(port_text)
        except ValueError:
            self.after(0, lambda: self._append_log("ERROR: Port harus angka."))
            return

        try:
            self.protocol_client.connect(host, port)
            response = self.protocol_client.auth(client_id, password)
        except Exception as e:
            self.after(0, lambda: self._on_connect_failed(str(e)))
            return

        if response.get("status") != "OK":
            msg = response.get("message", "AUTH gagal.")
            self.after(0, lambda: self._on_connect_failed(msg))
            return

        token = response.get("session_token")
        pcs = response.get("pcs", [])
        pc_ids = [p.get("pc_id", "-") for p in pcs if isinstance(p, dict)]

        self.session_token = token
        self.pcs = pcs
        self.connected = True
        self.should_maintain_connection = True

        self.after(0, lambda: self._on_connected(pc_ids, host))

    def _on_connected(self, pc_ids, host=""):
        if not pc_ids:
            pc_ids = ["-"]
        self.cmb_pc.configure(values=pc_ids)
        self.cmb_pc.set(pc_ids[0])
        self.lbl_pc_no.configure(text=pc_ids[0].replace("PC_", "") if pc_ids[0].startswith("PC_") else pc_ids[0])
        self._set_controls_enabled(True)
        self._refresh_client_ip_info(host)
        self.lbl_status.configure(text="Status: Connected")
        self.lbl_auto_reconnect.configure(text="Auto reconnect: ON")
        self._append_log("AUTH sukses. Terhubung ke server.")
        self._save_session()
        # Start polling billing status
        if self.billing_status_poll_job:
            try:
                self.after_cancel(self.billing_status_poll_job)
            except Exception:
                pass
        self._schedule_billing_status_poll()

    def _on_connect_failed(self, message: str):
        self.connected = False
        self.session_token = None
        self.should_maintain_connection = False
        self._set_controls_enabled(False)
        self._refresh_client_ip_info()
        self.lbl_status.configure(text="Status: Gagal terhubung")
        self.lbl_auto_reconnect.configure(text="Auto reconnect: OFF")
        self._append_log(f"ERROR: {message}")
        self.protocol_client.disconnect()
        # Stop billing status polling
        if self.billing_status_poll_job:
            try:
                self.after_cancel(self.billing_status_poll_job)
            except Exception:
                pass
            self.billing_status_poll_job = None

    def _send_command(self, action: str):
        if not self.connected or not self.session_token:
            self._append_log("ERROR: Belum connected/auth.")
            return
        pc_id = self.cmb_pc.get()
        if not pc_id or pc_id == "-":
            self._append_log("ERROR: PC belum dipilih.")
            return
        threading.Thread(target=self._send_command_worker, args=(pc_id, action), daemon=True).start()

    def _send_command_worker(self, pc_id: str, action: str):
        try:
            response = self.protocol_client.command(self.session_token, pc_id, action)
        except Exception as e:
            self.after(0, lambda: self._append_log(f"ERROR send {action}: {e}"))
            reconnect_ok = self._reconnect_and_reauth()
            if not reconnect_ok:
                return
            try:
                response = self.protocol_client.command(self.session_token, pc_id, action)
                self.after(0, lambda: self._append_log(f"Retry {action}: berhasil setelah reconnect."))
            except Exception as retry_error:
                self.after(0, lambda: self._append_log(f"ERROR retry {action}: {retry_error}"))
                return

        status = response.get("status", "FAIL")
        msg = response.get("message", "-")
        self.after(0, lambda: self._append_log(f"{action} [{status}] {msg}"))

    def _reconnect_and_reauth(self) -> bool:
        with self.reconnect_lock:
            self.after(0, lambda: self.lbl_status.configure(text="Status: Reconnecting..."))

            host = self.ent_host.get().strip()
            port_text = self.ent_port.get().strip()
            client_id = self.ent_client.get().strip()
            password = self.ent_password.get()

            if not host or not port_text or not client_id or not password:
                self.after(0, lambda: self._append_log("ERROR reconnect: data koneksi/login belum lengkap."))
                return False

            try:
                port = int(port_text)
            except ValueError:
                self.after(0, lambda: self._append_log("ERROR reconnect: port tidak valid."))
                return False

            try:
                self.protocol_client.connect(host, port)
                response = self.protocol_client.auth(client_id, password)
            except Exception as reconnect_error:
                self.connected = False
                self.session_token = None
                self.after(0, lambda: self._set_controls_enabled(False))
                self.after(0, lambda: self.lbl_status.configure(text="Status: Disconnect"))
                self.after(0, lambda: self.lbl_auto_reconnect.configure(text="Auto reconnect: OFF"))
                self.after(0, lambda: self._append_log(f"Reconnect gagal: {reconnect_error}"))
                return False

            if response.get("status") != "OK":
                self.connected = False
                self.session_token = None
                self.after(0, lambda: self._set_controls_enabled(False))
                self.after(0, lambda: self.lbl_status.configure(text="Status: Disconnect"))
                self.after(0, lambda: self.lbl_auto_reconnect.configure(text="Auto reconnect: OFF"))
                self.after(0, lambda: self._append_log(f"Reconnect auth gagal: {response.get('message', 'AUTH gagal.')}"))
                return False

            self.session_token = response.get("session_token")
            self.pcs = response.get("pcs", [])
            self.connected = True
            self.should_maintain_connection = True

            pc_ids = [p.get("pc_id", "-") for p in self.pcs if isinstance(p, dict)]
            if not pc_ids:
                pc_ids = ["-"]

            def _apply_reconnect_state():
                self.cmb_pc.configure(values=pc_ids)
                if self.cmb_pc.get() not in pc_ids:
                    self.cmb_pc.set(pc_ids[0])
                self._set_controls_enabled(True)
                self._refresh_client_ip_info(host)
                self.lbl_status.configure(text="Status: Connected")
                self.lbl_auto_reconnect.configure(text="Auto reconnect: ON")
                self._append_log("Reconnect sukses.")

            self.after(0, _apply_reconnect_state)
            return True

    def _disconnect(self):
        self.connected = False
        self.session_token = None
        self.pcs = []
        self.should_maintain_connection = False
        self.protocol_client.disconnect()
        self.cmb_pc.configure(values=["-"])
        self.cmb_pc.set("-")
        self._set_controls_enabled(False)
        self._refresh_client_ip_info()
        self.lbl_status.configure(text="Status: Disconnect")
        self.lbl_auto_reconnect.configure(text="Auto reconnect: OFF")
        self._append_log("Disconnected.")
        # Stop billing status polling
        if self.billing_status_poll_job:
            try:
                self.after_cancel(self.billing_status_poll_job)
            except Exception:
                pass
            self.billing_status_poll_job = None

    def _refresh_client_ip_info(self, host: str = ""):
        candidates = []
        try:
            if self.protocol_client.sock:
                sock_ip = self.protocol_client.sock.getsockname()[0]
                if sock_ip:
                    candidates.append(sock_ip)
        except Exception:
            pass

        normalized_host = (host or "").strip().lower()
        if normalized_host and normalized_host not in ("127.0.0.1", "localhost", "0.0.0.0"):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.connect((host, 80))
                    route_ip = s.getsockname()[0]
                    if route_ip:
                        candidates.append(route_ip)
            except Exception:
                pass

        candidates.extend(self._get_local_ipv4_candidates())
        ip = self._choose_best_client_ip(candidates)
        self._update_displayed_client_ip(ip)

    def _schedule_client_ip_refresh(self):
        if not self.monitor_running or not self.winfo_exists():
            self.client_ip_refresh_job = None
            return
        host = self._get_entry_text(getattr(self, "ent_host", None))
        self._refresh_client_ip_info(host)
        self.client_ip_refresh_job = self.after(CLIENT_IP_REFRESH_INTERVAL_SECONDS * 1000, self._schedule_client_ip_refresh)

    def _start_connection_monitor(self):
        threading.Thread(target=self._connection_monitor_loop, daemon=True).start()

    def _connection_monitor_loop(self):
        last_ping_time = 0
        last_reconnect_time = 0

        while self.monitor_running:
            now = time.time()

            if self.connected and self.session_token:
                if now - last_ping_time >= PING_INTERVAL_SECONDS:
                    last_ping_time = now
                    try:
                        response = self.protocol_client.request(
                            {
                                "type": "PING",
                                "session_token": self.session_token,
                                "timestamp": int(now),
                            }
                        )
                        if response.get("type") != "PONG":
                            raise RuntimeError(f"PING gagal: {response}")
                    except Exception as ping_error:
                        self.connected = False
                        self.after(0, lambda: self.lbl_status.configure(text="Status: Reconnecting..."))
                        self.after(0, lambda: self._append_log(f"Koneksi putus: {ping_error}"))

            if self.should_maintain_connection and not self.connected:
                if now - last_reconnect_time >= RECONNECT_INTERVAL_SECONDS:
                    last_reconnect_time = now
                    reconnect_ok = self._reconnect_and_reauth()
                    if reconnect_ok:
                        last_ping_time = now

            time.sleep(1)

    def _save_session(self):
        try:
            data = {
                "host": self.ent_host.get().strip(),
                "port": self.ent_port.get().strip(),
                "client_id": self.ent_client.get().strip(),
                "topmost": bool(self.sw_topmost.get()),
            }
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _load_session(self):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            host = data.get("host", "")
            port = data.get("port", "")
            client_id = data.get("client_id", "")
            topmost = data.get("topmost", False)

            if host:
                self.ent_host.delete(0, "end")
                self.ent_host.insert(0, host)
            if port:
                self.ent_port.delete(0, "end")
                self.ent_port.insert(0, str(port))
            if client_id:
                self.ent_client.delete(0, "end")
                self.ent_client.insert(0, client_id)
            if topmost:
                self.sw_topmost.select()
                self.attributes("-topmost", True)
        except Exception:
            pass

    def _on_close(self):
        self.monitor_running = False
        self.should_maintain_connection = False
        if self.client_ip_refresh_job:
            try:
                self.after_cancel(self.client_ip_refresh_job)
            except Exception:
                pass
            self.client_ip_refresh_job = None
        if self.billing_status_poll_job:
            try:
                self.after_cancel(self.billing_status_poll_job)
            except Exception:
                pass
            self.billing_status_poll_job = None
        self._save_session()
        self.protocol_client.disconnect()
        self.destroy()


if __name__ == "__main__":
    app = WarnetClientApp()
    app.mainloop()
