"""TvWsHub — WebSocket push hub untuk Floating Overlay Timer & Lockscreen Android TV.

Protokol JSON (ws://<kasir-ip>:8080):

  Server -> Client TV:
    START_TIMER  {"action", "meja_id", "sisa_detik", "nama_rental", "total_tagihan"}
                 sisa_detik = -1 artinya mode "Main Bebas" (tanpa countdown).
    PAUSE_TIMER  {"action", "meja_id"}
    RESUME_TIMER {"action", "meja_id", "sisa_detik"}
    STOP_TIMER   {"action", "meja_id"}          -> sembunyikan overlay
    LOCK_SCREEN  {"action", "pesan", "detail_transaksi": {"meja","sewa","fnb","total"}}
    UNLOCK_SCREEN {"action", "meja_id"}         -> tutup lock screen
    PING         {"action", "timestamp"}        -> heartbeat tiap 5 detik

  Client TV -> Server:
    REGISTER      {"type": "REGISTER", "meja_id": "...", "device": "android_tv", "nama": "..."}
    PONG          {"type": "PONG"}
    SCREEN_STATE  {"type": "SCREEN_STATE", "meja_id": "...", "screen_on": true|false}
                  Dikirim TV saat layar nyala/mati & saat (re)connect — dipakai
                  dashboard untuk status HIDUP/MATI & auto-off TV tanpa paket.

Tidak menambah dependency: memakai library `websockets` yang sudah dipakai main.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
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


def fmt_rp_ws(nilai) -> str:
    try:
        return f"Rp {int(nilai):,}".replace(",", ".")
    except (TypeError, ValueError):
        return f"Rp {nilai}"


def _fmt_hms(detik: int) -> str:
    detik = max(0, int(detik))
    h, rem = divmod(detik, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


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
    ) -> None:
        self.app = app
        self.port = int(port)
        self.host = host
        self._get_nama_rental = get_nama_rental or (lambda: "RR Billing Pro")
        self._state_extra = state_extra

        self._loop_thread: Optional[_HubLoopThread] = None
        self._ws_server: Optional[websockets.WebSocketServer] = None
        self._running = False
        self._heartbeat_task: Optional[asyncio.Task] = None

        # meja_id -> {websocket, address, nama, device, last_seen, transport}
        self.clients: dict[str, dict] = {}
        self._clients_lock = threading.Lock()

        # State lock yang dipegang hub (bertahan walau client reconnect):
        # meja_id -> dict detail_transaksi untuk dikirim ulang saat reconnect.
        self._locked: dict[str, dict] = {}
        self._locked_lock = threading.Lock()

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

    def stop(self) -> None:
        self._running = False
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
                            "last_seen": time.time(),
                            "screen_on": None,
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
                    # akurat — tanpa perlu ADB port 5555).
                    screen_on = msg.get("screen_on")
                    with self._clients_lock:
                        if meja_id in self.clients:
                            self.clients[meja_id]["screen_on"] = (
                                True if screen_on is True else False
                                if screen_on is False else None)
                            self.clients[meja_id]["last_seen"] = time.time()
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
            "connected": True,
            "last_seen": c.get("last_seen", 0),
            "screen_on": c.get("screen_on"),
        }

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
                cmds.append(self._msg_start(meja_id, -1, nama_rental, total,
                                            lunas_total=lunas, tagihan_total=tagihan))
            elif getattr(kartu, "sisa_waktu", 0) > 0:
                cmds.append(self._msg_start(meja_id, int(kartu.sisa_waktu), nama_rental, total,
                                            lunas_total=lunas, tagihan_total=tagihan))
        elif locked is not None:
            cmds.append(self._msg_lock(meja_id, locked.get("pesan", "WAKTU SEWA HABIS"),
                                       locked.get("detail_transaksi", {})))
        else:
            cmds.append(self._msg_stop(meja_id))

        if self._state_extra is not None:
            try:
                extra = self._state_extra(meja_id)
                if extra:
                    cmds.extend(extra)
            except Exception:
                _LOGGER.exception("state_extra error")
        return cmds

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
                   total_tagihan: Any, lunas_total: Any = 0, tagihan_total: Any = 0) -> dict:
        mode, minutes = self._overlay_cfg()
        return {
            "action": "START_TIMER",
            "meja_id": meja_id,
            "sisa_detik": int(sisa_detik),
            "nama_rental": nama_rental,
            "total_tagihan": fmt_rp_ws(total_tagihan),
            "lunas_total": fmt_rp_ws(lunas_total),
            "tagihan_total": fmt_rp_ws(tagihan_total),
            "overlay_mode": mode,
            "overlay_last_minutes": minutes,
        }

    def send_start_timer(self, meja_id: str, sisa_detik: int,
                         total_tagihan: Any = 0, nama_rental: Optional[str] = None,
                         lunas_total: Any = 0, tagihan_total: Any = 0) -> bool:
        msg = self._msg_start(meja_id, sisa_detik,
                              nama_rental or self._get_nama_rental(), total_tagihan,
                              lunas_total, tagihan_total)
        with self._locked_lock:
            self._locked.pop(meja_id, None)
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
                        lunas_total: Any = 0, tagihan_total: Any = 0) -> bool:
        """Sinkronisasi sisa waktu + total tagihan kasir → TV (dikirim tiap detik)."""
        mode, minutes = self._overlay_cfg()
        return self._send_to(meja_id, {"action": "SYNC_TIMER", "meja_id": meja_id,
                                       "sisa_detik": int(sisa_detik),
                                       "total_tagihan": fmt_rp_ws(total_tagihan),
                                       "lunas_total": fmt_rp_ws(lunas_total),
                                       "tagihan_total": fmt_rp_ws(tagihan_total),
                                       "overlay_mode": mode,
                                       "overlay_last_minutes": minutes})

    def send_pause_timer(self, meja_id: str) -> bool:
        return self._send_to(meja_id, {"action": "PAUSE_TIMER", "meja_id": meja_id})

    def send_resume_timer(self, meja_id: str, sisa_detik: int) -> bool:
        return self._send_to(meja_id, {"action": "RESUME_TIMER", "meja_id": meja_id,
                                       "sisa_detik": int(sisa_detik)})

    def send_stop_timer(self, meja_id: str) -> bool:
        with self._locked_lock:
            self._locked.pop(meja_id, None)
        ok = self._send_to(meja_id, self._msg_stop(meja_id))
        print(f"[TV WS HUB] STOP_TIMER {meja_id}: {'terkirim' if ok else 'GAGAL (client tidak terhubung)'}")
        return ok

    def _msg_stop(self, meja_id: str) -> dict:
        return {"action": "STOP_TIMER", "meja_id": meja_id}

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
        ok = self._send_to(meja_id, self._msg_lock(meja_id, pesan, detail))
        print(f"[TV WS HUB] LOCK_SCREEN {meja_id}: {'terkirim' if ok else 'GAGAL (client tidak terhubung)'}")
        return ok

    def send_unlock_screen(self, meja_id: str) -> bool:
        with self._locked_lock:
            self._locked.pop(meja_id, None)
        ok = self._send_to(meja_id, {"action": "UNLOCK_SCREEN", "meja_id": meja_id})
        print(f"[TV WS HUB] UNLOCK_SCREEN {meja_id}: {'terkirim' if ok else 'GAGAL (client tidak terhubung)'}")
        return ok

    def send_show_media(self, meja_id: str, media_type: str, url: str) -> bool:
        return self._send_to(meja_id, {"action": "SHOW_MEDIA", "meja_id": meja_id,
                                       "type": media_type, "url": url})

    def send_hide_media(self, meja_id: str) -> bool:
        return self._send_to(meja_id, {"action": "HIDE_MEDIA", "meja_id": meja_id})

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

    def send_update_logo(self, meja_id: str, logo_url: str) -> bool:
        """Logo lock diganti kasir -> TV yang sedang terkunci refresh tampilannya."""
        return self._send_to(meja_id, {"action": "UPDATE_LOGO", "meja_id": meja_id,
                                       "logo_url": logo_url})

    def broadcast_update_logo(self, logo_url: str) -> int:
        """Kirim UPDATE_LOGO ke semua client terhubung; return jumlah terkirim."""
        sent = 0
        for mid in self.get_connected_ids():
            if self.send_update_logo(mid, logo_url):
                sent += 1
        return sent

    def send_update_rental(self, meja_id: str, nama_rental: str) -> bool:
        """Kirim UPDATE_RENTAL ke satu TV (ganti nama popup kanan atas)."""
        return self._send_to(meja_id, {"action": "UPDATE_RENTAL", "meja_id": meja_id,
                                       "nama_rental": nama_rental})

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
        if not self._running or not self._loop_thread:
            return False
        with self._clients_lock:
            target = self.clients.get(meja_id)
            if target is None:
                # Label kartu "1" vs meja client "TV 1" / "MEJA 1" / "MEJA_1":
                # fallback supaya perintah dari kasir tetap sampai ke client.
                for cand in (f"TV {meja_id}", f"MEJA {meja_id}", f"MEJA_{meja_id}"):
                    target = self.clients.get(cand)
                    if target is not None:
                        meja_id = cand
                        break
                if target is not None and "meja_id" in message:
                    # Sesuaikan label di pesan (popup PIN / overlay) dengan
                    # nama client yang sebenarnya ("TV 1"), bukan label kartu.
                    message["meja_id"] = meja_id
        if not target:
            return False
        # Jujur: client yang tak membalas PONG dianggap tidak terhubung,
        # walau entry-nya belum sempat dibersihkan sweep.
        if time.time() - target.get("last_seen", 0) > STALE_TIMEOUT:
            return False
        try:
            payload = json.dumps(message, ensure_ascii=False)
            asyncio.run_coroutine_threadsafe(
                target["websocket"].send(payload), self._loop_thread.loop)
            return True
        except Exception:
            return False

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

    def is_meja_connected(self, meja_id: str) -> bool:
        with self._clients_lock:
            return meja_id in self.clients

    def get_screen_state(self, meja_id: str) -> Optional[bool]:
        """Status layar TV dari APK: True=nyala, False=mati, None=tidak diketahui."""
        with self._clients_lock:
            c = self.clients.get(meja_id)
        if not c:
            return None
        return c.get("screen_on")

    def is_locked(self, meja_id: str) -> bool:
        with self._locked_lock:
            return meja_id in self._locked

    def locked_summary(self) -> dict:
        with self._locked_lock:
            return {mid: info.get("detail_transaksi", {})
                    for mid, info in self._locked.items()}

    def _get_nama_rental(self) -> str:
        try:
            return str(self._get_nama_rental()) or "RR Billing Pro"
        except Exception:
            return "RR Billing Pro"

    @staticmethod
    def format_hms(detik: int) -> str:
        return _fmt_hms(detik)
