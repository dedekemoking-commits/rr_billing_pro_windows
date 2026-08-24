# -*- coding: utf-8 -*-
"""
Warnet Socket Server (TCP :5000) — protokol JSON identik dengan
WarnetSocketServer di main.py, dijalankan dari server web.

Alur (pull model):
  AUTH        -> AUTH_RESPONSE (session_token JWT + daftar pcs)
  GET_STATUS  -> STATUS_RESPONSE {billing:{..., pending_commands}} (client poll 3-5 dtk)
  PING        -> PONG
  COMMAND     -> client minta server menjalankan aksi ADB di PC/TV

Client C# (BillingClientService / warnet_client_app.exe) memakai protokol yang
sama — PC warnet yang sudah terpasang client bisa langsung dikontrol.
"""

import json
import logging
import os
import socket
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import main as M  # TokenManager, verify_password, ADBHelper, ConfigManager

_LOGGER = logging.getLogger("rrbilling.web.warnet")

WARNET_ADMIN_CODE_SECRET = "RR_WARNET_CFG_LOCK_V1"


class WarnetServerWeb:
    """Server pull-based: server TIDAK push perintah langsung; LOCK/UNLOCK
    dimasukkan ke antrian `pending_commands[pc_id]` yang dipop client pada
    GET_STATUS berikutnya (sekali pop)."""

    def __init__(self, store, listen_port=5000, max_conn=30):
        self.store = store
        self.listen_port = int(listen_port)
        self.max_conn = max_conn
        self.sessions = {}                 # session_token -> {client_id, last_heartbeat, address}
        self.sessions_lock = threading.Lock()
        self.pending_commands = {}         # pc_id -> [list cmd]
        self.pending_commands_lock = threading.Lock()
        self._server = None
        self._running = False
        self._lock_requeue = {}            # pc_id -> last re-queue (debounce 10 dtk)
        self._pc_last_seen = {}            # pc_id -> ts GET_STATUS terakhir
        self._pc_last_seen_lock = threading.Lock()

    # ── koneksi ──────────────────────────────────────────────────────────
    def start(self):
        if self._running:
            return
        try:
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server.bind(("0.0.0.0", self.listen_port))
            self._server.listen(self.max_conn)
            self._running = True
            threading.Thread(target=self._accept_loop, daemon=True, name="WarnetTCP").start()
            _LOGGER.info("Warnet Socket Server aktif di :%d", self.listen_port)
        except OSError as e:
            _LOGGER.warning("Warnet TCP :%d gagal bind (%s)", self.listen_port, e)
            self._running = False
            self._server = None
            raise

    def stop(self):
        self._running = False
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass
            self._server = None

    def _accept_loop(self):
        while self._running:
            try:
                conn, addr = self._server.accept()
            except Exception:
                time.sleep(0.2)
                continue
            conn.settimeout(600)
            threading.Thread(target=self._client_loop, args=(conn, addr), daemon=True).start()

    def _client_loop(self, conn, addr):
        token = [None]
        try:
            f = conn.makefile("r", encoding="utf-8", errors="replace")
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            return
        try:
            while True:
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                mtype = msg.get("type", "")
                if mtype == "AUTH":
                    token[0] = self._handle_auth(conn, msg, addr)
                elif mtype == "GET_STATUS":
                    self._handle_get_status(conn, msg)
                elif mtype == "PING":
                    self._handle_ping(conn, msg)
                elif mtype == "COMMAND":
                    self._handle_command(conn, msg, token[0])
                elif mtype == "REQUEST":
                    self._handle_request(conn, msg, token[0])
                else:
                    self.send(conn, {"type": "ERROR", "message": "Unknown type: %s" % mtype})
        except OSError:
            pass
        finally:
            try:
                f.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def send(self, conn, obj):
        try:
            data = json.dumps(obj, ensure_ascii=False)
            conn.sendall(data.encode("utf-8") + b"\n")
        except Exception:
            pass

    # ── antrian perintah ────────────────────────────────────────────────
    def queue_pending_command(self, pc_id, cmd, **params):
        with self.pending_commands_lock:
            d = {"cmd": cmd, "timestamp": int(time.time())}
            d.update(params)
            self.pending_commands.setdefault(str(pc_id), []).append(d)

    def pop_pending_commands(self, pc_id):
        with self.pending_commands_lock:
            return self.pending_commands.pop(str(pc_id), [])

    # ── helper config ───────────────────────────────────────────────────
    def _warnet_clients(self):
        return M.ConfigManager.get("warnet_clients", []) or []

    def _find_client(self, client_id):
        for c in self._warnet_clients():
            if isinstance(c, dict) and c.get("client_id") == client_id:
                return c
        return None

    def _find_pc(self, client_id, pc_id):
        c = self._find_client(client_id) or {}
        for p in (c.get("pcs") or []):
            if isinstance(p, dict) and str(p.get("pc_id")) == str(pc_id):
                return p
        return {}

    def _pc_data(self, pc_id):
        for client in self._warnet_clients():
            for p in (client.get("pcs") or []):
                if isinstance(p, dict) and str(p.get("pc_id")) == str(pc_id):
                    return p
        return {}

    def _is_pc_locked(self, pc_id):
        try:
            for c in M.ConfigManager.get("daftar_warnet", []) or []:
                if c.get("pc_id") == pc_id:
                    return bool(c.get("pc_locked", False))
        except Exception:
            pass
        return False

    def _lock_info(self, pc_id):
        try:
            for c in M.ConfigManager.get("daftar_warnet", []) or []:
                if c.get("pc_id") == pc_id:
                    return (c.get("pc_lock_reason", "") or "",
                            c.get("pc_lock_message", "Waktu PC telah habis."))
        except Exception:
            pass
        return "", "Waktu PC telah habis."

    # ── dispatch ────────────────────────────────────────────────────────
    def _handle_auth(self, conn, msg, addr):
        client_id = str(msg.get("client_id", ""))
        password = str(msg.get("password", ""))
        c = self._find_client(client_id)
        if not c:
            self.send(conn, {"type": "AUTH_RESPONSE", "status": "FAIL",
                             "message": "Client %s not found" % client_id})
            return None
        pw_hash = c.get("password_hash") or c.get("password_enc") or ""
        ok = bool(pw_hash) and M.verify_password(password, pw_hash)
        if not ok:
            self.send(conn, {"type": "AUTH_RESPONSE", "status": "FAIL",
                             "message": "Client %s: invalid password" % client_id})
            return None
        pcs = [dict(p) for p in (c.get("pcs") or [])]
        token = M.TokenManager.generate_token(client_id)
        with self.sessions_lock:
            self.sessions[token] = {"client_id": client_id, "last_heartbeat": time.time(),
                                    "address": str(addr[0]) if addr else ""}
        self.send(conn, {"type": "AUTH_RESPONSE", "status": "OK", "client_id": client_id,
                         "session_token": token, "pcs": pcs, "timestamp": int(time.time()),
                         "admin_code_secret": WARNET_ADMIN_CODE_SECRET})
        return token

    def _client_by_token(self, token):
        if not token:
            return None
        with self.sessions_lock:
            session = self.sessions.get(token)
            if not session:
                return None
            session["last_heartbeat"] = time.time()
            return session.get("client_id")

    def _handle_ping(self, conn, msg):
        self.send(conn, {"type": "PONG", "server_timestamp": int(time.time())})

    def _handle_get_status(self, conn, msg):
        token = msg.get("session_token", "")
        client_id = self._client_by_token(token)
        if not client_id:
            self.send(conn, {"type": "ERROR", "message": "invalid token"})
            return
        pc_id = str(msg.get("pc_id", ""))
        self._mark_pc_seen(pc_id)
        pending = self.pop_pending_commands(pc_id)
        sesi = self.store.sesi_warnet.get(pc_id)
        is_locked = self._is_pc_locked(pc_id)
        if sesi and sesi.paket_aktif:
            snap = sesi.snapshot()
            pay = {
                "pc_id": pc_id,
                "time_left": -1 if sesi.is_bebas else sesi.sisa_waktu,
                "paket_aktif": sesi.paket_aktif or "",
                "total_biaya": snap.get("total", 0),
                "is_playing": True,
                "timestamp": int(time.time()),
                "is_locked": False,
                "pending_commands": pending,
            }
        else:
            pay = {
                "pc_id": pc_id,
                "time_left": 0,
                "paket_aktif": "SELESAI" if is_locked else "IDLE",
                "total_biaya": 0,
                "is_playing": False,
                "timestamp": int(time.time()),
                "is_locked": bool(is_locked),
                "pending_commands": pending,
            }
            self._requeue_lock_if_needed(pc_id, is_locked)
        self.send(conn, {"type": "STATUS_RESPONSE", "status": "OK", "billing": pay})

    def _requeue_lock_if_needed(self, pc_id, is_locked):
        """LOCK di-queue ulang tiap >=10 dtk agar tahan client reconnect."""
        if not is_locked:
            return
        now = time.time()
        if now - self._lock_requeue.get(str(pc_id), 0) >= 10:
            self._lock_requeue[str(pc_id)] = now
            reason, message = self._lock_info(pc_id)
            self.queue_pending_command(pc_id, "LOCK", reason=reason or "selesai_manual",
                                       time_left=0, message=message)

    def _handle_command(self, conn, msg, token):
        client_id = self._client_by_token(token)
        if not client_id:
            self.send(conn, {"type": "ERROR", "message": "invalid token"})
            return
        pc_id = str(msg.get("pc_id", ""))
        action = str(msg.get("action", ""))
        c = self._find_client(client_id)
        pc = self._find_pc(client_id, pc_id)
        if not pc:
            self.send(conn, {"type": "COMMAND_RESPONSE", "status": "FAIL",
                             "message": "pc not owned by client"})
            return
        allowed = (c or {}).get("allowed_actions") or ["ON", "OFF", "VOL+", "VOL-"]
        if action not in allowed:
            self.send(conn, {"type": "COMMAND_RESPONSE", "status": "FAIL",
                             "message": "action not allowed"})
            return
        ip = pc.get("ip", "")
        ok, msg_out, _ = self._invoke_adb(ip, action)
        self.send(conn, {"type": "COMMAND_RESPONSE", "status": "OK" if ok else "FAIL",
                         "message": msg_out, "timestamp": int(time.time())})

    @staticmethod
    def _invoke_adb(ip, action):
        from main import ADBHelper
        try:
            if action in ("ON", "OFF"):
                res = ADBHelper.power_toggle(ip)
                return (res[0] if isinstance(res, tuple) else bool(res)), "OK", ""
            if action == "VOL+":
                res = ADBHelper.volume(ip, naik=True)
                return (res[0] if isinstance(res, tuple) else bool(res)), "OK", ""
            if action == "VOL-":
                res = ADBHelper.volume(ip, naik=False)
                return (res[0] if isinstance(res, tuple) else bool(res)), "OK", ""
            if action == "HOME":
                res = ADBHelper.home(ip)
                return (res[0] if isinstance(res, tuple) else bool(res)), "OK", ""
            return False, "Aksi tidak dikenal: %s" % action, ""
        except Exception as e:
            return False, str(e), ""

    def _handle_request(self, conn, msg, token):
        client_id = self._client_by_token(token)
        if not client_id:
            self.send(conn, {"type": "ERROR", "message": "invalid token"})
            return
        req = str(msg.get("request_type", ""))
        if req == "add_time":
            data = msg.get("data") or {}
            pc_id = str(data.get("pc_id", ""))
            paket_nm = str(data.get("package", ""))
            sesi = self.store.sesi_warnet.get(pc_id)
            if sesi and paket_nm:
                info = sesi.paket_data().get(paket_nm)
                if info:
                    sesi.start_paket(paket_nm, int(info.get("harga", 0)),
                                     int(info.get("menit", 0)), {}, 0)
                    self.send(conn, {"type": "REQUEST_RESPONSE", "status": "OK"})
                    return
            self.send(conn, {"type": "REQUEST_RESPONSE", "status": "FAIL",
                             "message": "paket tidak ditemukan"})
            return
        self.send(conn, {"type": "REQUEST_RESPONSE", "status": "OK", "message": "ignored"})

    # ── util untuk UI admin ─────────────────────────────────────────────
    def _mark_pc_seen(self, pc_id):
        if not pc_id:
            return
        with self._pc_last_seen_lock:
            self._pc_last_seen[str(pc_id)] = time.time()

    def is_pc_online(self, pc_id):
        with self._pc_last_seen_lock:
            ts = self._pc_last_seen.get(str(pc_id), 0)
        return (time.time() - ts) < 20

    def get_clients_online(self):
        """[{client_id, online_pcs:[{pc_id,name}], last_heartbeat}]"""
        with self.sessions_lock:
            now = time.time()
            clients = {}
            for token, s in self.sessions.items():
                cid = s.get("client_id")
                if not cid:
                    continue
                seen = clients.setdefault(cid, {"client_id": cid, "online_pcs": [], "last_heartbeat": 0})
                seen["last_heartbeat"] = max(seen["last_heartbeat"], s.get("last_heartbeat", 0))
        # pcs yang online = semua pc milik client yang sessionnya baru saja ngepoll
        online_ids = {}
        with self.sessions_lock:
            for s in self.sessions.values():
                cid = s.get("client_id")
                online_ids.setdefault(cid, True)
        out = []
        for client in self._warnet_clients():
            cid = client.get("client_id")
            if cid not in clients and cid not in online_ids:
                continue
            pcs = []
            for p in (client.get("pcs") or []):
                pcs.append({"pc_id": p.get("pc_id"), "name": p.get("name")})
            out.append({
                "client_id": cid,
                "online": bool(online_ids.get(cid)),
                "pcs": pcs,
                "last_heartbeat": clients.get(cid, {}).get("last_heartbeat", 0),
            })
        return out
