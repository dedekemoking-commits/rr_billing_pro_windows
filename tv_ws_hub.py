"""TvWsHub — WebSocket push hub untuk Floating Overlay Timer & Lockscreen Android TV.

Protokol JSON (ws://<kasir-ip>:8080):

  Server -> Client TV:
    START_TIMER  {"action", "meja_id", "sisa_detik", "nama_rental", "total_tagihan"}
                 sisa_detik = -1 artinya mode "Main Bebas" (tanpa countdown).
    PAUSE_TIMER  {"action", "meja_id"}
    RESUME_TIMER {"action", "meja_id", "sisa_detik"}
     STOP_TIMER   {"action", "meja_id"}          -> sembunyikan overlay
     SLEEP_TV     {"action", "meja_id", "countdown"}
                  -> TV client mengunci layar & tidur setelah `countdown` detik
                  (client yang tidak mengenali action ini diabaikan).
     LOCK_SCREEN  {"action", "pesan", "detail_transaksi": {"meja","sewa","fnb","total"}}
    UNLOCK_SCREEN {"action", "meja_id"}         -> tutup lock screen
    PING         {"action", "timestamp"}        -> heartbeat tiap 5 detik
    PAIRING_MODE {"action", "ip", "pairing"}    -> true = kasir sedang pairing
                  TV dengan IP itu; TV freeze promo/power key/lockscreen
                  supaya dialog kode pairing sistem tidak hilang.

  Client TV -> Server:
    REGISTER      {"type": "REGISTER", "meja_id": "...", "device": "android_tv", "nama": "...", "ip": "..."}
    PONG          {"type": "PONG"}
    SCREEN_STATE  {"type": "SCREEN_STATE", "meja_id": "...", "screen_on": true|false,
                   "input_label": "HDMI1", "ui_mode": "promo|lock|input|unknown"}
                  Dikirim TV saat layar nyala/mati & saat (re)connect — dipakai
                  dashboard untuk status HIDUP/MATI, port input (Home/HDMI),
                  mode tampilan, & auto-off TV tanpa paket.
    CLIENT_EVENT  {"type": "CLIENT_EVENT", "meja_id": "...", "event": "tv_lockscreen",
                   "ok": true|false, "message": "..."}
                  Laporan kejadian client (popup timer, lockscreen, promo,
                  QR/PIN, wake/tidur, WS putus). Semua masuk Log Aplikasi kasir,
                  termasuk status GAGAL.

Tidak menambah dependency: memakai library `websockets` yang sudah dipakai main.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import sys
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional

import websockets

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 8080
PING_INTERVAL = 5   # detik — heartbeat sesuai spesifikasi
PING_TIMEOUT = 10
STALE_TIMEOUT = 20  # detik — client dianggap putus jika tak ada PONG

# ── Auto-discovery hub (v4.14) ───────────────────────────────────────────────
# Kasir memancarkan alamat hub-nya via UDP broadcast tiap beberapa detik.
# App TV mendengarkan di port ini: begitu alamat hub berubah (IP PC diganti,
# IP DHCP berubah, dsb.) TV otomatis pindah & reconnect — tanpa setelan
# manual di TV. Payload JSON:
#   {"app": "rrbillingpro", "type": "hub_advert", "host": "192.168.1.x", "port": 8080}
ADVERT_PORT = 8095
ADVERT_INTERVAL = 2.5  # detik


def fmt_rp_ws(nilai) -> str:
    try:
        return f"Rp {int(nilai):,}".replace(",", ".")
    except (TypeError, ValueError):
        return f"Rp {nilai}"


def _clamp_int(nilai, lo: int, hi: int, default: int) -> int:
    """Ambil nilai integer dalam rentang; apa pun yang rusak -> default."""
    try:
        return max(lo, min(hi, int(nilai)))
    except (TypeError, ValueError):
        return default


def _clr_hex(nilai, default: str) -> str:
    """Normalisasi '#RRGGBB' atau 'RRGGBB'; nilai rusak -> default."""
    s = str(nilai or "").strip().lstrip("#").upper()
    if len(s) == 6 and all(c in "0123456789ABCDEF" for c in s):
        return "#" + s
    return default


def _fmt_hms(detik: int) -> str:
    detik = max(0, int(detik))
    h, rem = divmod(detik, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _elapsed_bebas(kartu) -> int:
    """Waktu berjalan (detik) untuk sesi Main Bebas."""
    awal = int(getattr(kartu, "menit_dipakai_awal", 0) or 0) * 60
    mulai = getattr(kartu, "waktu_mulai", None)
    if mulai is None:
        return max(0, awal)
    try:
        import datetime as _dt
        delta = (_dt.datetime.now() - mulai).total_seconds()
        return max(0, int(awal + delta))
    except Exception:
        return max(0, awal)


# Field yang ditampilkan di jejak log "apa yang dikirim ke TV". Field lain
# (nama_member, pin, logo_url, dll.) sengaja tidak ikut supaya baris log
# tetap ringkas dan tidak membocorkan isi QR/PIN ke file log.
_FIELD_LOG = (
    "sisa_detik", "elapsed_detik", "total_tagihan", "lunas_total",
    "tagihan_total", "nama_rental", "overlay_mode", "overlay_last_minutes",
    "bebas_interval", "bebas_durasi", "meja_id", "type", "pesan", "grup",
    "pairing", "on", "force_start", "mode", "alpha", "accent", "scale",
    "timer_size", "pos_y", "radius",
)


def _ringkas_pesan(message: dict) -> str:
    """Ringkas isi pesan WebSocket jadi satu baris yang enak dibaca log."""
    bagian = []
    for key in _FIELD_LOG:
        if key not in message:
            continue
        nilai = message[key]
        if nilai in ("", None):
            continue
        bagian.append(f"{key}={nilai}")
    return " ".join(bagian)[:220]


class _HubLoopThread(threading.Thread):
    """Daemon thread yang menjalankan asyncio event loop milik hub."""

    def __init__(self) -> None:
        super().__init__(name="tv-ws-hub-loop", daemon=True)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        self.loop.run_forever()

    def submit(self, coro) -> "asyncio.Future":
        return asyncio.run_coroutine_threadsafe(coro, self.loop)


class TvWsHub:
    """WebSocket push server untuk aplikasi client Android TV.

    Thread-safe: semua method public boleh dipanggil dari thread UI Tkinter.
    """

    def __init__(
        self,
        app: Any = None,
        port: int = DEFAULT_PORT,
        host: str = "0.0.0.0",
        get_nama_rental: Optional[Callable[[], str]] = None,
        state_extra: Optional[Callable[[str], list[dict]]] = None,
        advertise: bool = True,
        on_locked_changed: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.app = app
        self.port = int(port)
        self.host = host
        self._get_nama_rental = get_nama_rental or (lambda: "RR Billing Pro")
        self._state_extra = state_extra
        self._on_locked_changed = on_locked_changed
        # Auto-discovery UDP: hub uji/harness WAJIB advertise=False supaya
        # tidak menyerobot TV asli ke port hub tiruan (v4.14).
        self._advertise_enabled = bool(advertise)

        self._loop_thread: Optional[_HubLoopThread] = None
        self._ws_server: Optional[websockets.WebSocketServer] = None
        self._running = False
        self._heartbeat_task: Optional[asyncio.Task] = None

        # meja_id -> {websocket, address, nama, device, last_seen, transport}
        self.clients: dict[str, dict] = {}
        self._clients_lock = threading.RLock()

        # State lock yang dipegang hub (bertahan walau client reconnect):
        # meja_id -> dict detail_transaksi untuk dikirim ulang saat reconnect.
        self._locked: dict[str, dict] = {}
        self._locked_lock = threading.Lock()

        # START_TIMER yang ditunda karena TV tujuan sedang tidur (mis. sesi
        # dipindah ke TV yang layarnya mati). Dikirim begitu TV melapor
        # SCREEN_STATE nyala — mencegah wake lock membangunkan TV saat pindah.
        self._pending_start: dict[str, dict] = {}
        self._pending_start_lock = threading.Lock()

        # R4: meja yang SUDAH pernah dikirimi video promosi bawaan (sekali per
        # run server) — mencegah replay SHOW_MEDIA saat reconnect blip jaringan.
        self._media_sent_once: set[str] = set()

        # Penghitung pesan frekuensi-tinggi (SYNC/UPDATE_TOTAL) untuk log
        # ringkas — lihat _log_kirim.
        self._log_kirim_state: dict[str, dict] = {}

        # Overlay QR sesi member yang masih aktif per meja — dikirim ulang
        # saat client TV reconnect, supaya QR tidak hilang saat Wi-Fi blip.
        self._qr_aktif: dict[str, dict] = {}

        # Folder log debug R4 — diisi main.py (app_log_dir) supaya konsisten
        # dengan app.log; None = fallback (folder exe / folder file ini).
        self._r4_log_dir: Optional[str] = None

        # ── Auto-discovery hub (v4.14) ────────────────────────────────────────
        self._advert_stop: Optional[threading.Event] = None
        self._advert_thread: Optional[threading.Thread] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop_thread = _HubLoopThread()
        self._loop_thread.start()
        self._loop_thread._ready.wait(timeout=5)
        loop = self._loop_thread.loop
        loop.call_soon_threadsafe(self._start_heartbeat)
        loop.call_soon_threadsafe(asyncio.ensure_future, self._serve())
        print(f"[TV WS HUB] WebSocket server on ws://{self.host}:{self.port}")
        self._start_advert()

    def stop(self) -> None:
        self._running = False
        if self._advert_stop is not None:
            self._advert_stop.set()
            self._advert_stop = None
        if not self._loop_thread:
            return
        loop = self._loop_thread.loop
        try:
            fut = asyncio.run_coroutine_threadsafe(self._shutdown(), loop)
            fut.result(timeout=5)
        except Exception:
            pass
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
        self._loop_thread = None

    # ── Auto-discovery hub (UDP broadcast, v4.14) ────────────────────────────
    def _start_advert(self) -> None:
        """Pancarkan alamat hub via UDP broadcast (thread daemon).

        Dikirim dari TIAP alamat IPv4 lokal (bind per-interface) supaya TV di
        LAN mana pun menerima alamat yang benar; plus satu siaran global
        255.255.255.255. App TV (HubAdvertListener) mendengarkan di
        ADVERT_PORT lalu pindah alamat & reconnect otomatis.
        """
        if self._advert_thread is not None:
            return
        if not self._advertise_enabled:
            self._advert_thread = None
            return
        self._advert_stop = threading.Event()
        th = threading.Thread(target=self._advertise_loop,
                              args=(self._advert_stop,), daemon=True)
        self._advert_thread = th
        th.start()

    @staticmethod
    def _ip_lokal() -> list[str]:
        """Daftar IPv4 lokal non-loopback yang layak dipancarkan."""
        hasil: list[str] = []
        try:
            host = socket.gethostname()
            for info in socket.getaddrinfo(host, None, socket.AF_INET):
                ip = info[4][0]
                if ip and not ip.startswith("127.") and \
                        not ip.startswith("169.254.") and ip not in hasil:
                    hasil.append(ip)
        except Exception:
            pass
        if not hasil:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                hasil.append(s.getsockname()[0])
                s.close()
            except Exception:
                pass
        return hasil

    def _advertise_loop(self, stop_ev: threading.Event) -> None:
        payload_base = {"app": "rrbillingpro", "type": "hub_advert",
                        "port": int(self.port)}
        logged = False
        while not stop_ev.is_set() and self._running:
            for ip in self._ip_lokal():
                try:
                    pesan = json.dumps({**payload_base, "host": ip,
                                        "ts": time.time()}).encode("utf-8")
                    # Siaran /24 (subnet umum warnet) + global, dari interface
                    # yang memiliki IP tersebut (bind).
                    bcast24 = ".".join(ip.split(".")[:3]) + ".255"
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    try:
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                        s.bind((ip, 0))
                        s.sendto(pesan, (bcast24, ADVERT_PORT))
                        s.sendto(pesan, ("255.255.255.255", ADVERT_PORT))
                    finally:
                        s.close()
                    if not logged:
                        print(f"[HUB ADV] alamat hub dipancarkan via UDP "
                              f"{ip} -> :{ADVERT_PORT} (host={ip}:{self.port})",
                              flush=True)
                        logged = True
                except Exception:
                    continue
            stop_ev.wait(ADVERT_INTERVAL)

    def _start_heartbeat(self) -> None:
        if self._running:
            self._heartbeat_task = asyncio.ensure_future(self._heartbeat_loop())

    async def _shutdown(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._ws_server:
            self._ws_server.close()
            try:
                await self._ws_server.wait_closed()
            except Exception:
                pass
            self._ws_server = None
        with self._clients_lock:
            pending_close = [c.get("websocket")
                             for c in self.clients.values()
                             if c.get("websocket") is not None]
            self.clients.clear()
        for ws_obj in pending_close:
            try:
                await asyncio.wait_for(ws_obj.close(), timeout=5)
            except Exception:
                pass

    # ── Server coroutine ──────────────────────────────────────────────────────
    async def _serve(self) -> None:
        try:
            self._ws_server = await websockets.serve(
                self._handle_client,
                self.host,
                self.port,
                ping_interval=PING_INTERVAL,
                ping_timeout=PING_TIMEOUT,
                max_size=64 * 1024,
            )
        except Exception as e:
            print(f"[TV WS HUB] Server error: {e}")
            _LOGGER.exception("TvWsHub serve error")

    async def _heartbeat_loop(self) -> None:
        while self._running:
            await asyncio.sleep(PING_INTERVAL)
            await self._broadcast({"action": "PING", "timestamp": int(time.time())})
            await self._sweep_stale()

    async def _sweep_stale(self) -> None:
        """Hapus client yang tidak membalas PONG (last_seen usang).

        Mencegah entry 'hantu' — client yang koneksinya mati (mis. AP isolation,
        Wi-Fi STB tidur) tetap dianggap terhubung sehingga perintah START_TIMER
        dkk dianggap terkirim padahal tidak sampai.
        """
        now = time.time()
        stale: list[tuple[str, Any]] = []
        with self._clients_lock:
            for mid, c in list(self.clients.items()):
                if now - c.get("last_seen", 0) > STALE_TIMEOUT:
                    stale.append((mid, c.get("websocket")))
                    self.clients.pop(mid, None)
        for mid, ws_obj in stale:
            print(f"[TV WS HUB] Client stale dihapus: {mid}")
            if ws_obj is not None:
                try:
                    await ws_obj.close()
                except Exception:
                    pass

    async def _broadcast(self, message: dict) -> None:
        if not self.clients:
            return
        payload = json.dumps(message, ensure_ascii=False)
        with self._clients_lock:
            targets = list(self.clients.values())
        for c in targets:
            try:
                await c["websocket"].send(payload)
            except Exception:
                pass

    # ── Per-connection handler ────────────────────────────────────────────────
    async def _handle_client(self, websocket, path: Optional[str] = None) -> None:
        meja_id: Optional[str] = None
        address = None
        try:
            address = getattr(websocket, "remote_address", None)
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        "type": "ERROR", "message": "Invalid JSON"}))
                    continue

                msg_type = msg.get("type")
                if msg_type == "REGISTER":
                    meja_id = str(msg.get("meja_id", "")).strip()
                    if not meja_id:
                        await websocket.send(json.dumps({
                            "type": "ERROR", "message": "meja_id wajib diisi"}))
                        continue
                    with self._clients_lock:
                        old = self.clients.get(meja_id)
                        old_ws = (old.get("websocket") if old is not None
                                  and old.get("websocket") is not websocket else None)
                        self.clients[meja_id] = {
                            "websocket": websocket,
                            "address": address,
                            "nama": msg.get("nama", meja_id),
                            "device": msg.get("device", "android"),
                            "ip": str(msg.get("ip", "") or "").strip(),
                            "last_seen": time.time(),
                            "screen_on": None,
                            "input_label": "",
                            "ui_mode": "",
                            "adb_ui_mode": "",
                            "adb_input_label": "",
                            "adb_at": 0.0,
                            "izin": {},
                            "izin_belum": [],
                            "izin_at": 0.0,
                            "last_state_at": 0.0,
                        }
                    # Tutup koneksi lama DI LUAR lock — koneksi macet tidak boleh
                    # membekukan event loop / thread UI (deadlock fix).
                    if old_ws is not None:
                        try:
                            await asyncio.wait_for(old_ws.close(), timeout=5)
                        except Exception:
                            pass
                    state = self._build_state_snapshot(meja_id)
                    await websocket.send(json.dumps({
                        "type": "REGISTERED",
                        "status": "OK",
                        "meja_id": meja_id,
                        "state": state,
                    }, ensure_ascii=False))
                    if state:
                        for cmd in state:
                            await websocket.send(json.dumps(cmd, ensure_ascii=False))
                    # Overlay QR sesi member yang masih aktif: kirim ulang supaya
                    # pelanggan tetap bisa scan setelah reconnect / TV bangun.
                    qr_cmd = getattr(self, "_qr_aktif", {}).get(meja_id)
                    if qr_cmd:
                        try:
                            await websocket.send(json.dumps(qr_cmd, ensure_ascii=False))
                        except Exception:
                            pass
                    print(f"[TV WS HUB] Client terhubung: {meja_id} ({msg.get('nama')}) "
                          f"@{address} — {self.count_connected()} TV aktif")
                    continue

                if msg_type == "PONG":
                    with self._clients_lock:
                        if meja_id in self.clients:
                            self.clients[meja_id]["last_seen"] = time.time()
                    continue

                if msg_type == "SCREEN_STATE":
                    # Status layar dari APK TV (sumber status HIDUP/MATI paling
                    # akurat — tanpa perlu ADB port 5555). Sekalian menerima
                    # port input (HDMI1/2/... atau HOME) & mode tampilan
                    # (promo/lock/input) supaya kasir bisa menampilkan status
                    # nyata tiap TV dan memberi peringatan bila TV keluar jalur.
                    screen_on = msg.get("screen_on")
                    input_label = str(msg.get("input_label", "") or "").strip()
                    ui_mode = str(msg.get("ui_mode", "") or "").strip()
                    pending_msg = None
                    with self._clients_lock:
                        if meja_id in self.clients:
                            c = self.clients[meja_id]
                            baru_nyala = (screen_on is True and c.get("screen_on") is not True)
                            baru_mati = (screen_on is False and c.get("screen_on") is not False)
                            if input_label:
                                baru_nyala = baru_nyala or (c.get("input_label") != input_label)
                            if ui_mode:
                                baru_nyala = baru_nyala or (c.get("ui_mode") != ui_mode)
                            c["screen_on"] = (
                                True if screen_on is True else False
                                if screen_on is False else None)
                            if input_label:
                                c["input_label"] = input_label
                            if ui_mode:
                                c["ui_mode"] = ui_mode
                            c["last_state_at"] = time.time()
                            c["last_seen"] = time.time()
                            if baru_nyala or baru_mati:
                                print(f"[TV WS HUB] {meja_id} layar "
                                      f"{'NYALA' if baru_nyala else 'MATI'} "
                                      f"(input={c.get('input_label') or '?'} "
                                      f"mode={c.get('ui_mode') or '?'})")
                            # Status layar masuk Log Aplikasi, tapi HANYA saat
                            # berubah — TV lapor SCREEN_STATE tiap 15 detik,
                            # mencatat semuanya akan jadi spam.
                            log_event = getattr(self.app, "log_event", None)
                            if (baru_nyala or baru_mati) and callable(log_event):
                                log_event(
                                    "layar",
                                    "layar_nyala" if baru_nyala else "layar_mati",
                                    "info",
                                    {"tv": meja_id,
                                     "input": c.get("input_label") or "?",
                                     "mode": c.get("ui_mode") or "?"},
                                )
                            # Kirim START_TIMER yang ditunda karena TV tidur.
                            if screen_on is True:
                                with self._pending_start_lock:
                                    key = self._resolve_meja_id(meja_id) or meja_id
                                    pending_msg = self._pending_start.pop(key, None)
                                    if pending_msg is None:
                                        pending_msg = self._pending_start.pop(meja_id, None)
                    if pending_msg is not None:
                        try:
                            await websocket.send(json.dumps(pending_msg, ensure_ascii=False))
                            print(f"[TV WS HUB] START_TIMER tertunda {meja_id}: terkirim (TV nyala)")
                        except Exception as e:
                            print(f"[TV WS HUB] START_TIMER tertunda {meja_id}: GAGAL {e}")
                    continue

                if msg_type == "CLIENT_EVENT":
                    # Laporan kejadian dari client TV (popup timer, lockscreen,
                    # promo, QR/PIN, wake/tidur, WebSocket putus, kelengkapan
                    # izin). Semua ditulis ke Log Aplikasi kasir — termasuk GAGAL.
                    meja = str(msg.get("meja_id", "") or meja_id or "").strip()
                    event = str(msg.get("event", "") or "").strip() or "client_event"
                    ok = msg.get("ok") is True
                    message = str(msg.get("message", "") or "")
                    print(f"[TV WS HUB] {meja} CLIENT_EVENT {event}: "
                          f"{'OK' if ok else 'GAGAL'} {message}")
                    # Kelengkapan izin disimpan supaya badge kartu TV bisa
                    # menampilkan "izin lengkap / belum lengkap".
                    if event == "tv_izin_client":
                        mid = self._resolve_meja_id(meja) or meja
                        rincian = {}
                        for bagian in message.split(","):
                            bagian = bagian.strip()
                            if "=" in bagian:
                                kunci, _, nilai = bagian.partition("=")
                                rincian[kunci.strip()] = nilai.strip().upper()
                        belum = [k for k, v in rincian.items() if v != "OK"]
                        with self._clients_lock:
                            c = self.clients.get(mid)
                            if c is not None:
                                c["izin"] = rincian
                                c["izin_belum"] = belum
                                c["izin_at"] = time.time()
                    try:
                        # AuditLogger ada di main.py — impor lokal agar tidak
                        # circular import (main mengimpor modul ini).
                        from main import AuditLogger  # lazy import
                        AuditLogger.log(
                            event,
                            getattr(self.app, "current_user", "") or "",
                            "success" if ok else "failed",
                            {"label_tv": meja, "pesan": message})
                    except Exception:
                        _LOGGER.exception("CLIENT_EVENT audit gagal")
                    # Kasir boleh bereaksi real-time (mis. auto-pulih input HDMI
                    # 5 detik setelah promo selesai). Method ini opsional:
                    # aplikasi lama / mode lain tidak punya method tersebut.
                    try:
                        hook = getattr(self.app, "_tv_client_event", None)
                        if callable(hook):
                            hook(meja, event, ok, message)
                    except Exception:
                        _LOGGER.exception("hook _tv_client_event gagal")
                    continue

                if msg_type == "GET_TVS":
                    await websocket.send(json.dumps({
                        "type": "TVS_RESPONSE",
                        "tvs": [self._client_info(mid) for mid in self.get_connected_ids()],
                    }, ensure_ascii=False))
                    continue

                await websocket.send(json.dumps({
                    "type": "ERROR", "message": f"Unknown type: {msg_type}"}))
        except websockets.ConnectionClosed:
            pass
        except Exception as e:
            print(f"[TV WS HUB] Client error ({address}): {e}")
            _LOGGER.exception("TvWsHub client error")
        finally:
            if meja_id:
                with self._clients_lock:
                    cur = self.clients.get(meja_id)
                    # Hanya hapus jika entry masih milik koneksi ini — mencegah
                    # koneksi lama menghapus registrasi baru setelah reconnect.
                    if cur is not None and cur.get("websocket") is websocket:
                        self.clients.pop(meja_id, None)
                print(f"[TV WS HUB] Client putus: {meja_id} ({address})")

    def _client_info(self, meja_id: str) -> dict:
        with self._clients_lock:
            c = self.clients.get(meja_id)
        if not c:
            return {"meja_id": meja_id, "connected": False}
        return {
            "meja_id": meja_id,
            "nama": c.get("nama", meja_id),
            "device": c.get("device", ""),
            "address": str(c.get("address", "")),
            "ip": self._client_ip(meja_id, c),
            "connected": True,
            "last_seen": c.get("last_seen", 0),
            "screen_on": c.get("screen_on"),
            "input_label": c.get("input_label", ""),
            "ui_mode": c.get("ui_mode", ""),
            "adb_ui_mode": c.get("adb_ui_mode", ""),
            "adb_input_label": c.get("adb_input_label", ""),
            "adb_at": c.get("adb_at", 0),
            "izin": c.get("izin", {}),
            "izin_belum": c.get("izin_belum", []),
            "last_state_at": c.get("last_state_at", 0),
        }

    # ── Status lengkap satu TV (untuk badge kartu & peringatan kasir) ─────────
    def set_status_adb(self, meja_id: str, ui_mode: str, input_label: str) -> None:
        """Simpan hasil verifikasi ADB (dumpsys) untuk satu meja TV.

        Ini yang dipakai sebagai sumber kebenaran status tampilan/port TV,
        karena laporan client (SCREEN_STATE) bisa basi: Prefs "last input"
        di TV tidak berubah saat pelanggan memindahkan HDMI sendiri.
        """
        mid = self._resolve_meja_id(meja_id)
        if not mid:
            return
        with self._clients_lock:
            c = self.clients.get(mid)
            if c is None:
                return
            c["adb_ui_mode"] = str(ui_mode or "")
            c["adb_input_label"] = str(input_label or "")
            c["adb_at"] = time.time()

    def get_client_status(self, meja_id: str) -> dict:
        """Ringkasan status real-time satu meja TV untuk ditampilkan di kasir."""
        mid = self._resolve_meja_id(meja_id) or meja_id
        base = {"meja_id": mid, "connected": False, "screen_on": None,
                "input_label": "", "ui_mode": "", "locked": self.is_locked(mid)}
        with self._clients_lock:
            c = self.clients.get(mid)
            if not c:
                return base
            # Prioritas: verifikasi ADB (15 detik) > laporan client TV.
            adb_mode = c.get("adb_ui_mode") or ""
            adb_input = c.get("adb_input_label") or ""
            mode = adb_mode or (c.get("ui_mode") or "")
            # Saat ADB yakin TV di Home/promo/lock, port HDMI tidak relevan.
            input_label = "" if mode in ("home", "promo", "lock") else (
                adb_input or c.get("input_label") or "")
            base.update({
                "connected": True,
                "screen_on": c.get("screen_on"),
                "input_label": input_label,
                "ui_mode": mode,
                "last_state_at": c.get("last_state_at", 0),
                "last_seen": c.get("last_seen", 0),
                "adb_at": c.get("adb_at", 0),
                "izin": c.get("izin", {}),
                "izin_belum": c.get("izin_belum", []),
                "izin_at": c.get("izin_at", 0),
            })
        return base

    @staticmethod
    def _client_ip(meja_id: str, client: dict | None = None) -> str:
        """IP TV dari payload REGISTER, fallback ke address socket WebSocket."""
        if client is None:
            return ""
        ip = str(client.get("ip", "") or "").strip()
        if ip:
            return ip
        addr = str(client.get("address", "") or "")
        return addr.rsplit(":", 1)[0] if ":" in addr else ""

    def find_meja_by_ip(self, ip: str) -> str:
        """meja_id TV dengan IP tersebut, atau string kosong bila tidak ada."""
        ip = (ip or "").strip()
        if not ip:
            return ""
        with self._clients_lock:
            items = list(self.clients.items())
        for mid, c in items:
            if self._client_ip(mid, c) == ip:
                return mid
        return ""

    # ── State snapshot untuk resync saat client reconnect ─────────────────────
    def _build_state_snapshot(self, meja_id: str) -> list[dict]:
        cmds: list[dict] = []
        with self._locked_lock:
            locked = self._locked.get(meja_id)

        kartu = self._find_kartu(meja_id)
        if kartu is not None and not kartu.sesi_kosong():
            nama_rental = self._get_nama_rental()
            try:
                total = kartu._total_setelah_diskon()
            except Exception:
                total = getattr(kartu, "paket_harga_tetap", 0) + getattr(kartu, "biaya_pesanan", 0)
            lunas, tagihan = 0, 0
            if hasattr(kartu, "_split_payment"):
                try:
                    lunas, tagihan = kartu._split_payment()
                except Exception:
                    lunas, tagihan = 0, 0
            if getattr(kartu, "is_bebas", False):
                elapsed = _elapsed_bebas(kartu)
                cmds.append(self._msg_start(meja_id, -1, nama_rental, total,
                                            lunas_total=lunas, tagihan_total=tagihan,
                                            elapsed_detik=elapsed))
            elif getattr(kartu, "sisa_waktu", 0) > 0:
                cmds.append(self._msg_start(meja_id, int(kartu.sisa_waktu), nama_rental, total,
                                            lunas_total=lunas, tagihan_total=tagihan,
                                            is_last_time=bool(getattr(
                                                kartu, "is_last_time", False))))
        elif locked is not None:
            cmds.append(self._msg_lock(meja_id, locked.get("pesan", "WAKTU SEWA HABIS"),
                                       locked.get("detail_transaksi", {})))
        else:
            cmds.append(self._msg_stop(meja_id))
            # R4: video promosi bawaan (user NON-LIFETIME: trial/bulanan/tahunan)
            # — kirim SEKALI saat TV pertama terhubung dalam keadaan idle supaya
            # video sampai ke TV tanpa aksi kasir. Tidak replay pada reconnect
            # (flag _media_sent_once); replay hanya saat TV bangun dari tidur
            # (perilaku APK R3: MediaActivity.putar saat ACTION_SCREEN_ON).
            try:
                app = getattr(self, "app", None)
                if app is None:
                    self._r4_log(meja_id, "app=None")
                elif app._lisensi_lifetime():
                    self._r4_log(meja_id, "lifetime=True (skip)")
                else:
                    url = app._promo_default_media_url()
                    self._r4_log(meja_id, "url=%r sent_once=%s" % (url, meja_id in self._media_sent_once))
                    if url and meja_id not in self._media_sent_once:
                        self._media_sent_once.add(meja_id)
                        cmds.append({"action": "SHOW_MEDIA", "meja_id": meja_id,
                                     "type": "video", "url": url})
            except Exception as e:
                self._r4_log(meja_id, "EXC %r" % (e,))

        if self._state_extra is not None:
            try:
                extra = self._state_extra(meja_id)
                if extra:
                    cmds.extend(extra)
            except Exception:
                _LOGGER.exception("state_extra error")
        return cmds

    def _r4_log(self, meja_id: str, pesan: str) -> None:
        """Log debug R4 (SHOW_MEDIA bawaan) ke tv_ws_hub_debug.log di folder
        aplikasi — membantu diagnosa tanpa console (EXE tanpa window).
        Folder: _r4_log_dir (diisi main.py) → exe/folder file → LOCALAPPDATA."""
        try:
            import os
            base = self._r4_log_dir
            if not base:
                if getattr(sys, "frozen", False):
                    base = os.path.dirname(os.path.abspath(sys.executable))
                else:
                    base = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(base, "tv_ws_hub_debug.log")
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write("[R4] %s %s: %s\n"
                            % (meja_id, time.strftime("%H:%M:%S"), pesan))
            except OSError:
                fallback = os.path.join(
                    os.environ.get("LOCALAPPDATA", ""), "RRBillingPro")
                os.makedirs(fallback, exist_ok=True)
                with open(os.path.join(fallback, "tv_ws_hub_debug.log"),
                          "a", encoding="utf-8") as f:
                    f.write("[R4] %s %s: %s\n"
                            % (meja_id, time.strftime("%H:%M:%S"), pesan))
        except Exception:
            pass

    def _find_kartu(self, meja_id: str):
        app = self.app
        if app is None or not hasattr(app, "_semua_kartu_tv"):
            return None
        for kartu in app._semua_kartu_tv:
            label = getattr(kartu, "label_tv", "") or ""
            if label == meja_id:
                return kartu
            nomor = getattr(kartu, "nomor", "")
            if meja_id in (f"TV {nomor}", f"MEJA {nomor}", f"MEJA_{nomor}") or meja_id == str(nomor):
                return kartu
        return None

    # ── Pengaturan overlay (mode tampil countdown) ──────────────────────────
    def _overlay_cfg(self) -> tuple[str, int]:
        """Return (overlay_mode, overlay_last_minutes).

        Mode: "always" | "last_minutes" | "hidden".
        Dibaca dari atribut app (dipasang main.py dari config); fallback ke
        nilai default ("always", 5) bila belum diatur.
        """
        mode = "always"
        minutes = 5
        try:
            if self.app is not None:
                mode = str(getattr(self.app, "tv_overlay_mode", "") or mode)
                minutes = int(getattr(self.app, "tv_overlay_last_minutes", 0) or minutes)
        except Exception:
            pass
        if mode not in ("always", "last_minutes", "hidden"):
            mode = "always"
        if minutes < 1:
            minutes = 5
        return mode, minutes

    # ── Public API (thread-safe, dipanggil dari thread UI) ───────────────────
    def _msg_start(self, meja_id: str, sisa_detik: int, nama_rental: str,
                   total_tagihan: Any, lunas_total: Any = 0, tagihan_total: Any = 0,
                   nama_member: Optional[str] = None,
                   elapsed_detik: int = -1,
                   hdmi_port: Optional[int] = None,
                   hdmi_input_hint: str = "",
                   no_wake: bool = False,
                   is_last_time: bool = False) -> dict:
        mode, minutes = self._overlay_cfg()
        bebas = self._bebas_cfg()
        msg = {
            "action": "START_TIMER",
            "meja_id": meja_id,
            "sisa_detik": int(sisa_detik),
            "nama_rental": nama_rental,
            "total_tagihan": fmt_rp_ws(total_tagihan),
            "lunas_total": fmt_rp_ws(lunas_total),
            "tagihan_total": fmt_rp_ws(tagihan_total),
            "overlay_mode": mode,
            "overlay_last_minutes": minutes,
            "nama_member": str(nama_member or ""),
            # Main Bebas: waktu berjalan supaya TV tidak perlu menghitung
            # sendiri (keputusan "popup muncul" tetap di sisi TV).
            "elapsed_detik": int(elapsed_detik),
            "bebas_interval": bebas[0],
            "bebas_durasi": bebas[1],
        }
        # v4.13: port HDMI pilihan kasir untuk TV ini. None = jangan kirim
        # (client v4.12 ke bawah hanya mengabaikan; client v4.13 tidak
        # mengubah Prefs-nya). -1 = "Jangan pakai", 0 = belum diisi, 1..4.
        if hdmi_port is not None:
            msg["hdmi_port"] = int(hdmi_port)
            if hdmi_input_hint:
                msg["hdmi_input_hint"] = str(hdmi_input_hint)
        if no_wake:
            # Client v4.15+: jangan acquire SCREEN_BRIGHT_WAKE_LOCK saat START.
            msg["no_wake"] = True
        if is_last_time:
            # Client menampilkan label Last Time (APK baru) dan tetap
            # menjalankan countdown yang sama seperti sesi biasa.
            msg["is_last_time"] = True
        return msg

    def _bebas_cfg(self) -> tuple[int, int]:
        """(interval menit, durasi detik) untuk popup berkala di Main Bebas."""
        iv, dur = 60, 30
        try:
            if self.app is not None:
                iv = int(getattr(self.app, "tv_bebas_popup_interval", iv) or iv)
                dur = int(getattr(self.app, "tv_bebas_popup_durasi", dur) or dur)
        except Exception:
            pass
        return max(1, min(600, iv)), max(1, min(600, dur))

    def send_start_timer(self, meja_id: str, sisa_detik: int,
                         total_tagihan: Any = 0, nama_rental: Optional[str] = None,
                         lunas_total: Any = 0, tagihan_total: Any = 0,
                         nama_member: Optional[str] = None,
                         hdmi_port: Optional[int] = None,
                         hdmi_input_hint: str = "",
                         defer_if_asleep: bool = False,
                         no_wake: bool = False,
                         is_last_time: bool = False) -> bool:
        msg = self._msg_start(meja_id, sisa_detik,
                              nama_rental or self._get_nama_rental(), total_tagihan,
                              lunas_total, tagihan_total, nama_member,
                              hdmi_port=hdmi_port, hdmi_input_hint=hdmi_input_hint,
                              no_wake=no_wake, is_last_time=is_last_time)
        self._clear_locked(meja_id)
        with self._clients_lock:
            resolved = self._resolve_meja_id(meja_id) or meja_id
        # Pindah sesi ke TV yang sedang tidur: jangan kirim START sekarang
        # (START memicu wake lock di APK lama). Simpan dan kirim saat TV
        # melapor layar nyala.
        _defer = False
        if defer_if_asleep:
            try:
                _defer = (self.get_screen_state(meja_id) is False)
            except Exception:
                _defer = False
        if _defer:
            with self._pending_start_lock:
                self._pending_start[resolved] = msg
            print(f"[TV WS HUB] START_TIMER {meja_id}: ditunda (TV tidur)")
            return True
        with self._pending_start_lock:
            self._pending_start.pop(resolved, None)
        ok = self._send_to(meja_id, msg)
        print(f"[TV WS HUB] START_TIMER {meja_id} ({sisa_detik}dtk): "
              f"{'terkirim' if ok else 'GAGAL (client tidak terhubung)'}")
        return ok

    def send_update_total(self, meja_id: str, total_tagihan: Any = 0,
                          lunas_total: Any = 0, tagihan_total: Any = 0) -> bool:
        """Update tagihan berjalan (Main Bebas) — total dikirim tiap detik."""
        return self._send_to(meja_id, {"action": "UPDATE_TOTAL", "meja_id": meja_id,
                                       "total_tagihan": fmt_rp_ws(total_tagihan),
                                       "lunas_total": fmt_rp_ws(lunas_total),
                                       "tagihan_total": fmt_rp_ws(tagihan_total)})

    def send_sync_timer(self, meja_id: str, sisa_detik: int,
                        total_tagihan: Any = 0,
                        lunas_total: Any = 0, tagihan_total: Any = 0,
                        nama_member: Optional[str] = None,
                        elapsed_detik: int = -1,
                        hdmi_port: Optional[int] = None,
                        hdmi_input_hint: str = "",
                        is_last_time: bool = False) -> bool:
        """Sinkronisasi sisa waktu + total tagihan kasir → TV (dikirim tiap detik)."""
        # Jangan kirim SYNC ke TV yang layarnya mati. APK lama memanggil
        # setSessionScreenOn(true) pada SYNC_TIMER sehingga TV yang baru
        # menerima sesi pindahan ikut bangun dari tidur.
        try:
            if self.get_screen_state(meja_id) is False:
                return False
        except Exception:
            pass
        mode, minutes = self._overlay_cfg()
        bebas_iv, bebas_dur = self._bebas_cfg()
        msg = {"action": "SYNC_TIMER", "meja_id": meja_id,
               "sisa_detik": int(sisa_detik),
               "total_tagihan": fmt_rp_ws(total_tagihan),
               "lunas_total": fmt_rp_ws(lunas_total),
               "tagihan_total": fmt_rp_ws(tagihan_total),
               "overlay_mode": mode,
               "overlay_last_minutes": minutes,
               "nama_member": str(nama_member or ""),
               "elapsed_detik": int(elapsed_detik),
               "bebas_interval": bebas_iv,
               "bebas_durasi": bebas_dur}
        # v4.13: bawa juga konfigurasi HDMI kartu (client menyimpan hanya saat
        # berubah) — jadi mengubah port di kartu langsung tersinkron ke TV.
        if hdmi_port is not None:
            msg["hdmi_port"] = int(hdmi_port)
            if hdmi_input_hint:
                msg["hdmi_input_hint"] = str(hdmi_input_hint)
        if is_last_time:
            msg["is_last_time"] = True
        return self._send_to(meja_id, msg)

    def send_pause_timer(self, meja_id: str) -> bool:
        return self._send_to(meja_id, {"action": "PAUSE_TIMER", "meja_id": meja_id})

    def send_resume_timer(self, meja_id: str, sisa_detik: int) -> bool:
        return self._send_to(meja_id, {"action": "RESUME_TIMER", "meja_id": meja_id,
                                       "sisa_detik": int(sisa_detik)})

    def send_stop_timer(self, meja_id: str) -> bool:
        self._clear_locked(meja_id)
        with self._clients_lock:
            resolved = self._resolve_meja_id(meja_id) or meja_id
        with self._pending_start_lock:
            self._pending_start.pop(resolved, None)
        ok = self._send_to(meja_id, self._msg_stop(meja_id))
        print(f"[TV WS HUB] STOP_TIMER {meja_id}: {'terkirim' if ok else 'GAGAL (client tidak terhubung)'}")
        return ok

    def _msg_stop(self, meja_id: str) -> dict:
        return {"action": "STOP_TIMER", "meja_id": meja_id}

    def send_sleep_tv(self, meja_id: str, countdown: int = 2) -> bool:
        """Minta TV client mengunci layar lalu tidur (action SLEEP_TV).

        `countdown` = detik penundaan sebelum TV tidur, supaya kasir masih
        sempat melihat layar sebelum mati. Client TV RRBillingPro (v4.x+)
        sudah mendukung action ini; client lama/TV non-RR mengabaikannya
        (kasir tetap memakai fallback ADB/webOS).
        """
        try:
            detik = max(0, min(300, int(countdown or 0)))
        except (TypeError, ValueError):
            detik = 0
        ok = self._send_to(meja_id, {"action": "SLEEP_TV", "meja_id": meja_id,
                                     "countdown": detik})
        print(f"[TV WS HUB] SLEEP_TV {meja_id} ({detik}dtk): "
              f"{'terkirim' if ok else 'GAGAL (client tidak terhubung)'}")
        return ok

    def _msg_lock(self, meja_id: str, pesan: str, detail: Optional[dict]) -> dict:
        return {
            "action": "LOCK_SCREEN",
            "pesan": pesan,
            "detail_transaksi": detail or {
                "meja": meja_id, "sewa": "-", "fnb": "Rp 0", "total": "Rp 0"},
        }

    def send_lock_screen(self, meja_id: str, pesan: str = "WAKTU SEWA HABIS",
                         detail: Optional[dict] = None) -> bool:
        detail = detail or {}
        with self._locked_lock:
            self._locked[meja_id] = {"pesan": pesan, "detail_transaksi": detail}
        self._notify_locked_changed()
        with self._clients_lock:
            resolved = self._resolve_meja_id(meja_id) or meja_id
        with self._pending_start_lock:
            self._pending_start.pop(resolved, None)
        ok = self._send_to(meja_id, self._msg_lock(meja_id, pesan, detail))
        print(f"[TV WS HUB] LOCK_SCREEN {meja_id}: {'terkirim' if ok else 'GAGAL (client tidak terhubung)'}")
        return ok

    def send_unlock_screen(self, meja_id: str) -> bool:
        self._clear_locked(meja_id)
        ok = self._send_to(meja_id, {"action": "UNLOCK_SCREEN", "meja_id": meja_id})
        print(f"[TV WS HUB] UNLOCK_SCREEN {meja_id}: {'terkirim' if ok else 'GAGAL (client tidak terhubung)'}")
        return ok

    def send_show_media(self, meja_id: str, media_type: str, url: str,
                        local: str = "") -> bool:
        """Putar promo di TV. `local` = nama file aset hasil adb push (v4.13);
        client memakai file lokal dulu, `url` hanya cadangan streaming."""
        payload = {"action": "SHOW_MEDIA", "meja_id": meja_id,
                   "type": media_type, "url": url}
        if local:
            payload["local"] = local
        return self._send_to(meja_id, payload)

    def send_hide_media(self, meja_id: str) -> bool:
        return self._send_to(meja_id, {"action": "HIDE_MEDIA", "meja_id": meja_id})

    def send_message(self, meja_id: str, pesan: str, durasi: int = 5) -> bool:
        """Tampilkan banner pesan singkat di TV (mis. "Mohon Jangan Ribut").

        Banner = overlay atas transparan (APK v4.17) yang tampil `durasi`
        detik lalu hilang sendiri; game/HDMI di belakangnya tetap jalan.
        Client melaporkan CLIENT_EVENT `tv_pesan` supaya kasir tahu sudah
        tampil. TV tidur/offline TIDAK dibangunkan di sini — pemanggil
        (kasir) yang memutuskan perlu/tidaknya memberi tahu operator.
        """
        teks = str(pesan or "").strip()[:300]
        if not teks:
            return False
        payload = {"action": "SHOW_MESSAGE", "meja_id": meja_id,
                   "pesan": teks,
                   "durasi": max(3, min(int(durasi or 5), 300))}
        ok = self._send_to(meja_id, payload)
        print(f"[TV WS HUB] SHOW_MESSAGE {meja_id}: "
              f"{'terkirim' if ok else 'GAGAL (client tidak terhubung)'}")
        return ok

    # ── Mode pairing (dialog kode Android TV tidak boleh terputus) ────────────
    def send_pairing_mode(self, ip: str, on: bool) -> int:
        """Nyalakan/matikan mode pairing untuk TV dengan IP tertentu.

        Selama mode pairing aktif, client TV tidak boleh mengirim power key,
        memutar promo, membuka lockscreen, atau menaruh overlay apa pun — semua
        itu menutupi dialog kode pairing sistem sehingga kasir tidak sempat
        memasukkan PIN ("Connection has been lost").

        Dikirim ke semua client (bukan cuma meja yang terdaftar) karena saat
        pairing TV sering belum punya kartu di kasir; tiap client menyaring
        sendiri lewat field `ip`. Return jumlah client yang menerimanya.
        """
        payload = {"action": "PAIRING_MODE", "ip": (ip or "").strip(),
                   "pairing": bool(on)}
        ids = self.get_connected_ids()
        targets = []
        for mid in ids:
            with self._clients_lock:
                client = self.clients.get(mid)
            # ip kosong (matikan semua) = semua client; selain itu hanya TV itu.
            if payload["ip"] and self._client_ip(mid, client) != payload["ip"]:
                continue
            targets.append(mid)
        # TV yang sedang di-pair kadang belum pernah REGISTER dengan IP (APK lama
        # atau IP belum tercatat) — kalau tidak ada yang cocok, lebih baik kirim
        # ke semua daripada pairing gagal terus.
        if on and not targets and ids:
            targets = list(ids)
            payload["ip"] = ""
            print("[TV WS HUB] PAIRING_MODE ON: IP tidak cocok, kirim ke semua TV")
        sent = 0
        for mid in targets:
            if self._send_to(mid, payload):
                sent += 1
        print(f"[TV WS HUB] PAIRING_MODE {'ON' if on else 'OFF'} "
              f"ip={payload['ip'] or '(semua)'}: {sent} client")
        return sent

    def broadcast_show_media(self, media_type: str, url: str, local: str = "") -> int:
        """Kirim SHOW_MEDIA ke semua client terhubung; return jumlah terkirim."""
        sent = 0
        for mid in self.get_connected_ids():
            if self.send_show_media(mid, media_type, url, local):
                sent += 1
        return sent

    def broadcast_hide_media(self) -> int:
        """Kirim HIDE_MEDIA ke semua client terhubung; return jumlah terkirim."""
        sent = 0
        for mid in self.get_connected_ids():
            if self.send_hide_media(mid):
                sent += 1
        return sent

    def send_show_pin(self, meja_id: str, pin: str) -> bool:
        """Tampilkan PIN panggil operator/kasir di pojok KIRI atas layar TV."""
        ok = self._send_to(meja_id, {"action": "SHOW_PIN", "meja_id": meja_id, "pin": pin})
        print(f"[TV WS HUB] SHOW_PIN {meja_id}: {'terkirim' if ok else 'GAGAL (client tidak terhubung)'}")
        return ok

    def send_hide_pin(self, meja_id: str) -> bool:
        """Sembunyikan PIN di layar TV (sesi selesai / PIN terpakai / user masuk web)."""
        ok = self._send_to(meja_id, {"action": "HIDE_PIN", "meja_id": meja_id})
        print(f"[TV WS HUB] HIDE_PIN {meja_id}: {'terkirim' if ok else 'GAGAL (client tidak terhubung)'}")
        return ok

    def send_show_qr(self, meja_id: str, url: str, grup: str = "", sisa_detik: int = 0) -> bool:
        """Tampilkan overlay QR sesi member di TV (kiri 1/4 QR, kanan info rental).
        `url` = URL PNG QR yang dilayani media server kasir (port 8082/qr/...)."""
        payload = {"action": "SHOW_QR", "meja_id": meja_id, "url": url,
                   "grup": grup or "", "sisa_detik": int(sisa_detik or 0)}
        ok = self._send_to(meja_id, payload)
        if ok:
            self._qr_aktif[meja_id] = payload
        print(f"[TV WS HUB] SHOW_QR {meja_id}: {'terkirim' if ok else 'GAGAL (client tidak terhubung)'}")
        return ok

    def send_hide_qr(self, meja_id: str) -> bool:
        """Sembunyikan overlay QR sesi member (sukses / batal / kedaluwarsa)."""
        self._qr_aktif.pop(meja_id, None)
        ok = self._send_to(meja_id, {"action": "HIDE_QR", "meja_id": meja_id})
        print(f"[TV WS HUB] HIDE_QR {meja_id}: {'terkirim' if ok else 'GAGAL (client tidak terhubung)'}")
        return ok

    def qr_aktif(self, meja_id: str) -> bool:
        """True bila sedang ada overlay QR member aktif untuk TV ini."""
        return meja_id in getattr(self, "_qr_aktif", {})

    def send_update_lock_bg(self, meja_id: str, bg_url: str,
                            local: str = "") -> bool:
        """Background lockscreen (MP4 loop) diganti kasir -> TV terapkan.
        `local` = nama file aset hasil adb push (lockscreen.mp4, v4.13)."""
        payload = {"action": "UPDATE_LOCK_BG", "meja_id": meja_id,
                   "bg_url": bg_url}
        if local:
            payload["local"] = local
        return self._send_to(meja_id, payload)

    def broadcast_update_lock_bg(self, bg_url: str, local: str = "") -> int:
        """Kirim UPDATE_LOCK_BG ke semua client terhubung; return jumlah terkirim."""
        sent = 0
        for mid in self.get_connected_ids():
            if self.send_update_lock_bg(mid, bg_url, local):
                sent += 1
        return sent

    def send_update_logo(self, meja_id: str, logo_url: str,
                         local: str = "") -> bool:
        """Logo lock diganti kasir -> TV yang sedang terkunci refresh tampilannya.
        `local` = nama file aset hasil adb push (logo.png, v4.13)."""
        payload = {"action": "UPDATE_LOGO", "meja_id": meja_id,
                   "logo_url": logo_url}
        if local:
            payload["local"] = local
        return self._send_to(meja_id, payload)


    def broadcast_update_logo(self, logo_url: str, local: str = "") -> int:
        """Kirim UPDATE_LOGO ke semua client terhubung; return jumlah terkirim."""
        sent = 0
        for mid in self.get_connected_ids():
            if self.send_update_logo(mid, logo_url, local):
                sent += 1
        return sent

    def send_update_rental(self, meja_id: str, nama_rental: str) -> bool:
        """Nama rental berubah (mis. ganti logo/toko) -> overlay di-refresh."""
        return self._send_to(meja_id, {"action": "UPDATE_RENTAL", "meja_id": meja_id,
                                       "nama_rental": nama_rental})

    # ── Tampilan popup (transparansi, warna, ukuran font, radius, skala) ─────
    # Nilai diambil dari app (dibaca dari config). Client memakai nilai
    # bawaannya bila field tidak dikirim, jadi TV versi lama aman.

    def _style_cfg(self) -> dict:
        st = getattr(self.app, "tv_overlay_style", None) if self.app else None
        if not isinstance(st, dict):
            st = {}
        return {
            "bg_alpha": _clamp_int(st.get("bg_alpha"), 0, 100, 80),
            "accent": _clr_hex(st.get("accent"), "#00E5FF"),
            "radius": _clamp_int(st.get("radius"), 0, 40, 14),
            "timer_size": _clamp_int(st.get("timer_size"), 12, 48, 22),
            "scale": _clamp_int(st.get("scale"), 50, 130, 70),
            "pos_y": _clamp_int(st.get("pos_y"), 0, 60, 20),
        }

    def send_overlay_style(self, meja_id: str, bg_alpha=None, accent=None,
                           radius=None, timer_size=None, scale=None,
                           pos_y=None) -> bool:
        """Kirim gaya popup ke satu TV (live, tanpa restart sesi)."""
        cfg = self._style_cfg()
        if bg_alpha is not None:
            cfg["bg_alpha"] = _clamp_int(bg_alpha, 0, 100, cfg["bg_alpha"])
        if accent is not None:
            cfg["accent"] = _clr_hex(accent, cfg["accent"])
        for key, val, lo, hi in (("radius", radius, 0, 40),
                                 ("timer_size", timer_size, 12, 48),
                                 ("scale", scale, 50, 130),
                                 ("pos_y", pos_y, 0, 60)):
            if val is not None:
                cfg[key] = _clamp_int(val, lo, hi, cfg[key])
        payload = {"action": "OVERLAY_STYLE", "meja_id": meja_id}
        payload.update(cfg)
        ok = self._send_to(meja_id, payload)
        print(f"[TV WS HUB] OVERLAY_STYLE {meja_id}: "
              f"{'terkirim' if ok else 'GAGAL (TV tidak terhubung)'} {cfg}")
        return ok

    def broadcast_overlay_style(self, bg_alpha=None, accent=None, radius=None,
                                timer_size=None, scale=None, pos_y=None) -> int:
        """Kirim gaya popup ke semua client; return jumlah terkirim."""
        sent = 0
        for mid in self.get_connected_ids():
            if self.send_overlay_style(mid, bg_alpha, accent, radius,
                                       timer_size, scale, pos_y):
                sent += 1
        return sent

    def broadcast_update_rental(self, nama_rental: str) -> int:
        """Kirim UPDATE_RENTAL ke semua client terhubung; return jumlah terkirim."""
        sent = 0
        for mid in self.get_connected_ids():
            if self.send_update_rental(mid, nama_rental):
                sent += 1
        return sent

    def push_current_state(self, meja_id: str) -> int:
        """Kirim ulang snapshot state (START_TIMER / LOCK / STOP) ke satu TV.

        Dipakai saat server restart: kalau TV telah reconnect lebih dulu sebelum
        kasir login ulang, snapshot lama (saat kartu belom terbangun) berisi
        STOP_TIMER. Setelah sesi direstore, hub mengirim ulang snapshot terbaru
        supaya popup & countdown TV hidup kembali.
        """
        if not self._running:
            return 0
        try:
            cmds = self._build_state_snapshot(meja_id)
        except Exception as e:
            _LOGGER.exception("push_current_state error: %s", e)
            return 0
        sent = 0
        for cmd in cmds:
            if self._send_to(meja_id, cmd):
                sent += 1
        return sent

    def _send_to(self, meja_id: str, message: dict) -> bool:
        action = str(message.get("action", "?"))
        if not self._running or not self._loop_thread:
            self._log_kirim(meja_id, action, False, "hub tidak jalan")
            return False
        with self._clients_lock:
            resolved = self._resolve_meja_id(meja_id)
            target = self.clients.get(resolved) if resolved else None
            if target is not None and resolved != meja_id:
                # Label kartu "TV1" vs meja client "TV 1": sesuaikan label di
                # pesan (popup PIN / overlay) dengan nama client sebenarnya.
                meja_id = resolved
                if "meja_id" in message:
                    message["meja_id"] = meja_id
        if not target:
            self._log_kirim(meja_id, action, False, "client tidak terhubung")
            return False
        # Jujur: client yang tak membalas PONG dianggap tidak terhubung,
        # walau entry-nya belum sempat dibersihkan sweep.
        if time.time() - target.get("last_seen", 0) > STALE_TIMEOUT:
            self._log_kirim(meja_id, action, False, "client stale (tanpa PONG)")
            return False
        try:
            payload = json.dumps(message, ensure_ascii=False)
            asyncio.run_coroutine_threadsafe(
                target["websocket"].send(payload), self._loop_thread.loop)
            self._log_kirim(meja_id, action, True, _ringkas_pesan(message))
            return True
        except Exception as e:
            self._log_kirim(meja_id, action, False, f"{type(e).__name__}: {e}")
            return False

    # ── Jejak "apa yang dikirim ke TV" ─────────────────────────────────────────
    # SYNC_TIMER dikirim tiap detik per TV — kalau semuanya dicatat apa adanya,
    # app.log (rotasi 2 MB x 3) habis dalam hitungan jam dan log yang penting
    # ikut ter-overwrite. Jadi pesan frekuensi-tinggi diringkas: yang pertama,
    # lalu tiap JEDA_LOG_WS detik, plus rekap jumlah saat berhenti.
    JEDA_LOG_WS = 30.0
    # Kegagalan berulang ke meja yang sama dicatat maksimal 1x per ini (detik).
    # SYNC_TIMER/PING jalan tiap detik; tanpa batas, satu TV offline cukup
    # untuk menambah ratusan baris per menit ke app.log.
    JEDA_LOG_GAGAL = 60.0

    def _log_kirim(self, meja_id: str, action: str, ok: bool, info: str = ""):
        """Catat tiap pengiriman ke TV + session start/finish ke Log Aplikasi."""
        app = self.app
        log_event = getattr(app, "log_event", None) if app is not None else None

        if action in ("SYNC_TIMER", "UPDATE_TOTAL", "PING"):
            with self._clients_lock:
                state = self._log_kirim_state.setdefault(
                    meja_id, {"n": 0, "terakhir": 0.0,
                             "gagal_n": 0, "gagal_log": 0.0})
                state["n"] += 1
                n = state["n"]
                sekarang = time.time()
                celah = sekarang - state["terakhir"]
                state["terakhir"] = sekarang

                # Kegagalan beruntun (TV client ikut disconnect) ditulis
                # maksimal 1x per JEDA_LOG_GAGAL per meja. SYNC_TIMER jalan
                # tiap detik, jadi tanpa throttle ini satu TV yang offline
                # memenuhi app.log dengan baris yang sama berulang.
                if not ok:
                    state["gagal_n"] += 1
                    if (state["gagal_n"] > 1
                            and sekarang - state["gagal_log"] < self.JEDA_LOG_GAGAL):
                        return
                    state["gagal_log"] = sekarang
                    if state["gagal_n"] > 1:
                        info = (f"{info} ({state['gagal_n']}x berturut-turut, "
                                f"laporan diperlambat)")
                else:
                    state["gagal_n"] = 0

                if n > 1 and celah < self.JEDA_LOG_WS:
                    # Cukup di app.log; tidak perlu membanjiri audit log.
                    print(f"[TV WS HUB] ⇄ {meja_id} {action} (#{n}) "
                          f"{info} {'terkirim' if ok else 'GAGAL: ' + info}",
                          flush=True)
                    return
                info = f"{info} (total {n}x sejak start)"
            status = "success" if ok else "failed"
            if callable(log_event):
                log_event("ws", action.lower(), status,
                          {"tv": meja_id, "n": n, "info": info})
            print(f"[TV WS HUB] ⇄ {meja_id} {action} (#{n}) "
                  f"{info} {'terkirim' if ok else 'GAGAL: ' + info}", flush=True)
            return

        status = "success" if ok else "failed"
        if callable(log_event):
            log_event("ws", action.lower(), status,
                      {"tv": meja_id, "info": info})
        print(f"[TV WS HUB] → {meja_id} {action} "
              f"{info} {'terkirim' if ok else 'GAGAL: ' + info}", flush=True)

    # ── Info ──────────────────────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return self._running

    def count_connected(self) -> int:
        with self._clients_lock:
            return len(self.clients)

    def get_connected_ids(self) -> list[str]:
        with self._clients_lock:
            return list(self.clients.keys())

    def get_connected_tvs(self) -> list[dict]:
        return [self._client_info(mid) for mid in self.get_connected_ids()]

    def _resolve_meja_id(self, meja_id: str):
        """Cari key client sungguhan: exact, lalu "TV X" / "MEJA X" / "MEJA_X"
        (kartu kasir pakai "TV1" tapi client APK daftarkan "TV 1").
        Terakhir: normalisasi longgar (buang spasi/underscore + lowercase)
        agar "TV1", "tv 1", "TV_1" semuanya cocok."""
        with self._clients_lock:
            if meja_id in self.clients:
                return meja_id
            for cand in (f"TV {meja_id}", f"MEJA {meja_id}", f"MEJA_{meja_id}"):
                if cand in self.clients:
                    return cand

            def norm(s: str) -> str:
                return "".join(str(s).split()).lower().replace("_", "")

            target = norm(meja_id)
            if target:
                for mid in list(self.clients.keys()):
                    if norm(mid) == target:
                        return mid
        return None

    def is_meja_connected(self, meja_id: str) -> bool:
        with self._clients_lock:
            return self._resolve_meja_id(meja_id) is not None

    def get_screen_state(self, meja_id: str) -> Optional[bool]:
        """Status layar TV dari APK: True=nyala, False=mati, None=tidak diketahui."""
        with self._clients_lock:
            key = self._resolve_meja_id(meja_id)
            c = self.clients.get(key) if key else None
        if not c:
            return None
        return c.get("screen_on")

    def get_client_ui_mode(self, meja_id: str) -> str:
        """Mode yang DILAPORKAN client TV (bukan hasil probe ADB).

        Penting untuk v2.4.25: saat TV baru bangun dari standby, client
        mengirim SCREEN_STATE dengan `ui_mode=promo` (promo sudah diputar
        lokal) tanpa mengirim ulang event `tv_promo`. Kasir memakai ini untuk
        tahu layar sudah siap tanpa harus menunggu event yang tak akan pernah
        datang.
        """
        with self._clients_lock:
            key = self._resolve_meja_id(meja_id)
            c = self.clients.get(key) if key else None
        if not c:
            return ""
        return str(c.get("ui_mode") or "")

    def get_client_state_age(self, meja_id: str) -> float:
        """Umur data status terakhir (detik). 0 = belum pernah lapor."""
        with self._clients_lock:
            key = self._resolve_meja_id(meja_id)
            c = self.clients.get(key) if key else None
        if not c:
            return 0.0
        ts = float(c.get("last_state_at") or 0.0)
        return (time.time() - ts) if ts > 0 else 0.0

    def is_locked(self, meja_id: str) -> bool:
        with self._locked_lock:
            return meja_id in self._locked

    def locked_summary(self) -> dict:
        with self._locked_lock:
            return {mid: info.get("detail_transaksi", {})
                    for mid, info in self._locked.items()}

    def locked_state(self) -> dict:
        """Snapshot lengkap state lock untuk dipersistensi ke config."""
        with self._locked_lock:
            return {
                str(mid): {
                    "pesan": str(info.get("pesan", "WAKTU SEWA HABIS")
                                or "WAKTU SEWA HABIS"),
                    "detail_transaksi": dict(info.get("detail_transaksi", {}) or {}),
                }
                for mid, info in self._locked.items()
            }

    def restore_locked_state(self, state: dict) -> None:
        """Pulihkan state lock dari config (mis. Last Time habis saat app tutup).

        Client yang reconnect akan langsung menerima LOCK_SCREEN yang sama,
        termasuk judul "LAST TIME HABIS" dan URL gambar khususnya.
        """
        if not isinstance(state, dict) or not state:
            return
        restored = {}
        for mid, info in state.items():
            if not isinstance(info, dict):
                continue
            detail = info.get("detail_transaksi", info)
            if not isinstance(detail, dict):
                detail = {}
            pesan = str(info.get("pesan", "WAKTU SEWA HABIS")
                        or "WAKTU SEWA HABIS")
            restored[str(mid)] = {
                "pesan": pesan,
                "detail_transaksi": dict(detail),
            }
        if not restored:
            return
        with self._locked_lock:
            self._locked.update(restored)
        print(f"[TV WS HUB] Restored {len(restored)} lock state")

    def remove_locked_state(self, meja_id: str) -> None:
        """Hapus state lock satu meja (mis. sesi aktif dipulihkan)."""
        self._clear_locked(meja_id)

    def _clear_locked(self, meja_id: str) -> None:
        with self._locked_lock:
            removed = self._locked.pop(meja_id, None)
        if removed is not None:
            self._notify_locked_changed()

    def _notify_locked_changed(self) -> None:
        cb = self._on_locked_changed
        if cb is None:
            return
        try:
            cb(self.locked_state())
        except Exception as e:
            print(f"[TV WS HUB] simpan state lock gagal: {e}")

    def _get_nama_rental(self) -> str:
        try:
            return str(self._get_nama_rental()) or "RR Billing Pro"
        except Exception:
            return "RR Billing Pro"

    @staticmethod
    def format_hms(detik: int) -> str:
        return _fmt_hms(detik)
