"""
tv_controller_system.py — Hybrid TV Controller untuk RR Billing Pro

OOP Controller untuk Android TV (ADB/atpv2) dan LG webOS 22 (WOL + bscpylgtv).
Termasuk:
  - TVController (base), AndroidTVController, WebOSTVController
  - Factory: create_tv_controller(tv_id, config)
  - BillingSession: async scheduler toast + auto-off

Bug fix:
  - webOS screensaver: kirim WOL senggolan sebelum perintah untuk
    membangunkan NIC yang tertidur, lalu reconnect WebSocket.

Usage:
    python tv_controller_system.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from wakeonlan import send_magic_packet as _wol_send

try:
    from bscpylgtv import WebOsClient
except ImportError:
    WebOsClient = None

_LOGGER = logging.getLogger("tv_ctrl")
if not _LOGGER.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s", "%H:%M:%S"))
    _LOGGER.addHandler(_h)
    _LOGGER.setLevel(logging.INFO)


# ===============================================================================
#  DATA CLASSES
# ===============================================================================

@dataclass
class TVConfig:
    """Konfigurasi satu unit TV dari tvs_config.json."""
    tv_id: str
    ip_address: str
    mac_address: str
    os_type: str  # "android" | "webos"
    port: int = 5555
    label: str = ""

    def __post_init__(self):
        if not self.label:
            self.label = self.tv_id.upper()


@dataclass
class ToastMilestone:
    """Satu titik waktu untuk mengirim toast peringatan."""
    sisa_menit: int
    pesan: str


# ===============================================================================
#  BASE CONTROLLER
# ===============================================================================

class TVController(ABC):
    """Abstract base class untuk semua jenis TV."""

    def __init__(self, config: TVConfig):
        self.config = config
        self.ip = config.ip_address
        self.mac = config.mac_address
        self.label = config.label

    @abstractmethod
    async def turn_on(self) -> bool:
        """Nyalakan TV. Return True jika berhasil."""

    @abstractmethod
    async def turn_off(self) -> bool:
        """Matikan TV (standby). Return True jika berhasil."""

    @abstractmethod
    async def show_toast(self, message: str) -> bool:
        """Tampilkan toast message di layar TV."""

    @abstractmethod
    async def is_powered_on(self) -> Optional[bool]:
        """Cek status power. True=HIDUP, False=MATI, None=tidak diketahui."""

    async def reconnect(self) -> bool:
        """Reconnect opsional. Default: no-op, return True."""
        return True

    async def safe_turn_on(self) -> bool:
        """turn_on dibungkus try-except, tidak pernah crash."""
        try:
            return await self.turn_on()
        except Exception as e:
            _LOGGER.error("[%s] turn_on error: %s", self.label, e)
            return False

    async def safe_turn_off(self) -> bool:
        """turn_off dibungkus try-except, tidak pernah crash."""
        try:
            return await self.turn_off()
        except Exception as e:
            _LOGGER.error("[%s] turn_off error: %s", self.label, e)
            return False

    async def safe_show_toast(self, message: str) -> bool:
        """show_toast dibungkus try-except, tidak pernah crash."""
        try:
            return await self.show_toast(message)
        except Exception as e:
            _LOGGER.error("[%s] show_toast error: %s", self.label, e)
            return False

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.label} {self.ip}>"


# ===============================================================================
#  ANDROID TV CONTROLLER
# ===============================================================================

class AndroidTVController(TVController):
    """Kontrol Android TV via ADBHelper (atpv2 / ADB shell).

    TIDAK mengubah logika ADBHelper yang sudah ada — hanya membungkus
    dalam API async agar konsisten dengan BillingSession.
    """

    def __init__(self, config: TVConfig):
        super().__init__(config)
        self._adb = None  # lazy import ADBHelper dari main

    def _get_adb_helper(self):
        """Lazy import ADBHelper dari main.py (hindari circular import)."""
        if self._adb is not None:
            return self._adb
        try:
            # Import dari main modul (sudah terinstal di runtime)
            import importlib
            main_mod = importlib.import_module("main")
            self._adb = main_mod.ADBHelper
            return self._adb
        except Exception as e:
            _LOGGER.warning("[%s] Cannot import ADBHelper: %s", self.label, e)
            return None

    async def turn_on(self) -> bool:
        """Android TV: tidak ada WOL standar. Coba reconnect + keyevent."""
        adb = self._get_adb_helper()
        if not adb:
            _LOGGER.error("[%s] ADBHelper tidak tersedia", self.label)
            return False

        loop = asyncio.get_event_loop()

        # Coba reconnect dulu
        try:
            ok, _, msg = await loop.run_in_executor(
                None, lambda: adb.cek_dan_reconnect(self.ip, self.config.port))
            _LOGGER.info("[%s] Reconnect: %s — %s", self.label, ok, msg)
        except Exception as e:
            _LOGGER.warning("[%s] Reconnect error: %s", self.label, e)

        # Kirim KEYCODE_WAKEUP untuk membangunkan layar
        try:
            ok, out = await loop.run_in_executor(
                None, lambda: adb.adb_shell(
                    self.ip, "input keyevent KEYCODE_WAKEUP",
                    timeout=8, port=self.config.port))
            _LOGGER.info("[%s] KEYCODE_WAKEUP: %s — %s", self.label, ok, out)
            return ok
        except Exception as e:
            _LOGGER.error("[%s] turn_on error: %s", self.label, e)
            return False

    async def turn_off(self) -> bool:
        """Android TV: power_toggle via atpv2 / ADB."""
        adb = self._get_adb_helper()
        if not adb:
            return False

        loop = asyncio.get_event_loop()
        try:
            ok, out, err = await loop.run_in_executor(
                None, lambda: adb.power_toggle(self.ip, port=self.config.port))
            _LOGGER.info("[%s] power_toggle: %s — %s", self.label, ok, out)
            if ok:
                return True

            # Fallback: KEYCODE_POWER via ADB shell
            for key in ("KEYCODE_POWER", "KEYCODE_SLEEP", "223"):
                ok_adb, out_adb = await loop.run_in_executor(
                    None, lambda k=key: adb.adb_shell(
                        self.ip, f"input keyevent {k}",
                        timeout=8, port=self.config.port))
                if ok_adb:
                    _LOGGER.info("[%s] fallback %s: OK", self.label, key)
                    return True
            return False
        except Exception as e:
            _LOGGER.error("[%s] turn_off error: %s", self.label, e)
            return False

    async def show_toast(self, message: str) -> bool:
        """Android TV: kirim toast via ADB (tidak ada bscpylgtv)."""
        adb = self._get_adb_helper()
        if not adb:
            return False

        loop = asyncio.get_event_loop()
        try:
            # Gunakan ADB broadcast untuk toast
            cmd = (
                f'am broadcast -a android.intent.action.MAIN '
                f'-e msg "{message}" '
                f'-n com.rrbillingpro.tvclient/.ToastReceiver'
            )
            ok, out = await loop.run_in_executor(
                None, lambda: adb.adb_shell(self.ip, cmd, timeout=8,
                                            port=self.config.port))
            if ok:
                _LOGGER.info("[%s] toast terkirim: %s", self.label, message[:40])
                return True

            # Fallback: gunama service call notification
            ok2, out2 = await loop.run_in_executor(
                None, lambda: adb.adb_shell(
                    self.ip,
                    f"am startservice -a com.rrbillingpro.SHOW_TOAST "
                    f"--es toast_text '{message}'",
                    timeout=8, port=self.config.port))
            return ok2
        except Exception as e:
            _LOGGER.error("[%s] show_toast error: %s", self.label, e)
            return False

    async def is_powered_on(self) -> Optional[bool]:
        """Android TV: cek power state via ADB dumpsys."""
        adb = self._get_adb_helper()
        if not adb:
            return None

        loop = asyncio.get_event_loop()
        try:
            state = await loop.run_in_executor(
                None, lambda: adb.tv_power_state(self.ip, self.config.port))
            return state  # True / False / None
        except Exception as e:
            _LOGGER.error("[%s] is_powered_on error: %s", self.label, e)
            return None


# ===============================================================================
#  LG webOS CONTROLLER
# ===============================================================================

class WebOSTVController(TVController):
    """Kontrol LG Smart TV webOS via Wake-on-LAN + bscpylgtv WebSocket.

    Bug fix — Screensaver Issue:
      Kartu jaringan webOS sering tertidur saat screensaver, menyebabkan
      WebSocket terputus. Solusi:
      1. Sebelum show_toast / turn_off, kirim WOL senggolan dulu
      2. Reconnect WebSocket via await client.connect()
      3. Baru eksekusi perintah aslinya
    """

    # Timeout & retry untuk WebSocket
    WS_TIMEOUT = 8
    WS_RETRY = 2

    def __init__(
        self,
        config: TVConfig,
        key_file_path: Optional[str] = None,
        manifest_file_path: Optional[str] = None,
    ):
        super().__init__(config)

        # Pairing key: cari di APP_BASE_DIR -> _MEIPASS -> lg_tv_controller/
        self._key_file_path = key_file_path or self._find_file(
            ".aiopylgtv.sqlite",
            [os.path.join(os.getcwd(), ".aiopylgtv.sqlite")]
        )

        # Manifest pairing: cari di beberapa lokasi
        self._manifest_file_path = manifest_file_path or self._find_file(
            "manifest_rrbillingpro.json",
            [
                os.path.join(os.getcwd(), "manifest_rrbillingpro.json"),
                os.path.join(os.getcwd(), "lg_tv_controller",
                             "manifest_rrbillingpro.json"),
            ]
        )

        _LOGGER.info(
            "[%s] webOS init — key: %s, manifest: %s",
            self.label,
            os.path.basename(self._key_file_path) if self._key_file_path else "NONE",
            os.path.basename(self._manifest_file_path)
            if self._manifest_file_path else "default",
        )

    @staticmethod
    def _find_file(name: str, extra_paths: list = None) -> Optional[str]:
        """Cari file di berbagai lokasi: extra_paths, APP_BASE_DIR, _MEIPASS."""
        candidates = list(extra_paths or [])
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            candidates.append(os.path.join(exe_dir, name))
            meipass = getattr(sys, "_MEIPASS", "")
            if meipass:
                candidates.append(os.path.join(meipass, name))
        else:
            candidates.append(os.path.join(
                os.path.dirname(os.path.abspath(__file__)), name))
        for p in candidates:
            if os.path.isfile(p):
                return p
        return None

    # -- WOL senggolan (screensaver fix) -----------------------------------

    def _send_wol_nudge(self):
        """Kirim WOL Magic Packet sebagai 'senggolan' untuk membangunkan NIC."""
        try:
            mac_clean = (self.mac.replace(":", "").replace("-", "")
                         .replace(".", ""))
            if len(mac_clean) != 12:
                _LOGGER.warning("[%s] MAC tidak valid untuk WOL: %s",
                               self.label, self.mac)
                return
            mac_fmt = ":".join(mac_clean[i:i+2] for i in range(0, 12, 2))
            _wol_send(mac_fmt)
            _LOGGER.info("[%s] WOL senggolan terkirim ke %s", self.label, mac_fmt)
        except Exception as e:
            _LOGGER.warning("[%s] WOL senggolan gagal: %s", self.label, e)

    # -- WebSocket lifecycle ------------------------------------------------

    async def _create_client(self) -> Any:
        """Buat WebOsClient baru dengan konfigurasi yang benar."""
        if WebOsClient is None:
            raise ImportError("bscpylgtv tidak terinstal")
        return await WebOsClient.create(
            self.ip,
            ping_interval=None,
            states=[],
            key_file_path=self._key_file_path or "",
            timeout_connect=self.WS_TIMEOUT,
            manifest_file_path=self._manifest_file_path or "",
        )

    async def _connect_with_wol_nudge(self) -> Any:
        """Connect dengan screensaver fix:
        1. Kirim WOL senggolan
        2. Tunggu sebentar (NIC bangun)
        3. Connect WebSocket
        """
        # Step 1: WOL senggolan
        self._send_wol_nudge()

        # Step 2: Tunggu NIC bangun
        await asyncio.sleep(2)

        # Step 3: Connect WebSocket
        client = await self._create_client()
        await client.connect()
        return client

    async def _safe_operation(self, operation: str, fn) -> bool:
        """Jalankan operasi WebSocket dengan reconnect logic.

        Screensaver fix:
        1. Coba jalankan operasi langsung
        2. Jika gagal, kirim WOL senggolan, reconnect, coba lagi
        """
        last_error = None

        # Percobaan pertama: langsung connect
        for attempt in range(1, self.WS_RETRY + 1):
            client = None
            try:
                if attempt == 1:
                    # Pertama: connect biasa
                    client = await self._create_client()
                    await client.connect()
                else:
                    # Retry: WOL senggolan + reconnect
                    _LOGGER.info(
                        "[%s] Retry %d/%d — WOL senggolan + reconnect",
                        self.label, attempt, self.WS_RETRY)
                    client = await self._connect_with_wol_nudge()

                # Eksekusi operasi
                result = await fn(client)
                _LOGGER.info("[%s] %s: OK", self.label, operation)
                return result

            except Exception as e:
                last_error = e
                _LOGGER.warning(
                    "[%s] %s attempt %d gagal: %s",
                    self.label, operation, attempt, e)
            finally:
                if client:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass

        _LOGGER.error(
            "[%s] %s: GAGAL setelah %d percobaan. Error terakhir: %s",
            self.label, operation, self.WS_RETRY, last_error)
        return False

    # -- Public API ---------------------------------------------------------

    async def turn_on(self) -> bool:
        """Nyalakan TV via Wake-on-LAN."""
        try:
            mac_clean = (self.mac.replace(":", "").replace("-", "")
                         .replace(".", ""))
            if len(mac_clean) != 12:
                _LOGGER.error("[%s] MAC tidak valid: %s", self.label, self.mac)
                return False
            mac_fmt = ":".join(mac_clean[i:i+2] for i in range(0, 12, 2))
            _wol_send(mac_fmt)
            _LOGGER.info("[%s] WOL terkirim ke %s", self.label, mac_fmt)
            return True
        except Exception as e:
            _LOGGER.error("[%s] turn_on WOL error: %s", self.label, e)
            return False

    async def turn_off(self) -> bool:
        """Matikan TV via WebSocket power_off (dengan screensaver fix)."""
        async def _do_power_off(client):
            state = await client.get_power_state()
            _LOGGER.info("[%s] Power state: %s", self.label, state)
            await client.power_off()
            return True

        return await self._safe_operation("power_off", _do_power_off)

    async def show_toast(self, message: str) -> bool:
        """Tampilkan toast message (dengan screensaver fix)."""
        if not message or not message.strip():
            return False

        async def _do_toast(client):
            await client.send_message(message.strip())
            return True

        return await self._safe_operation("toast", _do_toast)

    async def is_powered_on(self) -> Optional[bool]:
        """Cek status power TV."""
        async def _do_check(client):
            state = await client.get_power_state()
            state_str = state.get("state", "Unknown") if state else "Unknown"
            is_active = state_str.lower() in ("active", "on", "unknown")
            return is_active

        try:
            return await self._safe_operation("power_check", _do_check)
        except Exception as e:
            _LOGGER.error("[%s] is_powered_on error: %s", self.label, e)
            return None

    async def reconnect(self) -> bool:
        """Reconnect dengan WOL senggolan."""
        try:
            client = await self._connect_with_wol_nudge()
            await client.disconnect()
            _LOGGER.info("[%s] Reconnect sukses", self.label)
            return True
        except Exception as e:
            _LOGGER.error("[%s] Reconnect gagal: %s", self.label, e)
            return False


# ===============================================================================
#  FACTORY / ROUTER
# ===============================================================================

def create_tv_controller(
    tv_id: str,
    config: Dict[str, Any],
    key_file_path: Optional[str] = None,
    manifest_file_path: Optional[str] = None,
) -> TVController:
    """Factory: buat instance controller berdasarkan os_type dari config.

    Args:
        tv_id: ID unik TV (mis. "tv_01")
        config: Dict dari JSON — harus punya ip_address, mac_address, os_type
        key_file_path: Lokasi .aiopylgtv.sqlite (webOS only)
        manifest_file_path: Lokasi manifest_rrbillingpro.json (webOS only)

    Returns:
        AndroidTVController atau WebOSTVController

    Raises:
        ValueError: os_type tidak dikenali
    """
    tv_config = TVConfig(
        tv_id=tv_id,
        ip_address=config["ip_address"],
        mac_address=config["mac_address"],
        os_type=config["os_type"],
        port=config.get("port", 5555),
        label=config.get("label", ""),
    )

    os_type = config["os_type"].lower().strip()

    if os_type == "android":
        return AndroidTVController(tv_config)
    elif os_type == "webos":
        return WebOSTVController(
            tv_config,
            key_file_path=key_file_path,
            manifest_file_path=manifest_file_path,
        )
    else:
        raise ValueError(
            f"os_type tidak dikenali: '{os_type}' untuk TV '{tv_id}'. "
            f"Harus 'android' atau 'webos'.")


def load_tv_config(config_path: str) -> Dict[str, TVController]:
    """Load tvs_config.json dan buat semua controller.

    Return dict: {tv_id: TVController_instance}
    """
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Config file tidak ditemukan: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    controllers = {}
    for tv_id, tv_cfg in data.items():
        try:
            ctrl = create_tv_controller(tv_id, tv_cfg)
            controllers[tv_id] = ctrl
            _LOGGER.info("Loaded TV: %s -> %s", tv_id, repr(ctrl))
        except Exception as e:
            _LOGGER.error("Gagal load TV '%s': %s", tv_id, e)

    return controllers


# ===============================================================================
#  BILLING SESSION (ASYNC SCHEDULER)
# ===============================================================================

class BillingSession:
    """Async scheduler untuk sesi billing satu TV.

    Alur:
      1. start() — nyalakan TV, tunggu 8 detik, kirim toast mulai
      2. Timer berjalan di background, kirim toast pada milestone
      3. finish() — matikan TV, batalkan timer

    Semua operasi jaringan dibungkus try-except, tidak pernah crash.
    """

    # Default milestones (sisa menit -> pesan)
    DEFAULT_MILESTONES = [
        ToastMilestone(5, "Peringatan: Waktu Anda tersisa 5 menit lagi!"),
        ToastMilestone(3, "Peringatan: Waktu Anda tersisa 3 menit lagi!"),
        ToastMilestone(1, "PERHATIAN: Waktu Anda tersisa 1 menit lagi!"),
    ]

    def __init__(
        self,
        controller: TVController,
        nama_paket: str = "Basic",
        duration_detik: int = 3600,
        milestones: Optional[list] = None,
        on_finish: Optional[Callable] = None,
    ):
        self.controller = controller
        self.nama_paket = nama_paket
        self.duration_detik = duration_detik
        self.milestones = milestones or self.DEFAULT_MILESTONES
        self.on_finish = on_finish  # callback setelah sesi selesai

        self._start_time: Optional[float] = None
        self._timer_task: Optional[asyncio.Task] = None
        self._sent_milestones: set = set()  # track yang sudah dikirim
        self._active = False

    @property
    def sisa_waktu(self) -> int:
        """Sisa waktu dalam detik."""
        if not self._start_time:
            return 0
        elapsed = time.time() - self._start_time
        remaining = self.duration_detik - elapsed
        return max(0, int(remaining))

    @property
    def sisa_menit(self) -> int:
        """Sisa waktu dalam menit (dibulatkan ke bawah)."""
        return self.sisa_waktu // 60

    @property
    def is_active(self) -> bool:
        return self._active

    async def start(self):
        """Mulai sesi billing.

        1. Nyalakan TV
        2. Tunggu 8 detik (TV boot + NIC ready)
        3. Kirim toast "Sesi Dimulai"
        4. Mulai background timer
        """
        _LOGGER.info(
            "=== SESI MULAI: %s | %s | %d detik ===",
            self.controller.label, self.nama_paket, self.duration_detik)

        # 1. Nyalakan TV
        on_ok = await self.controller.safe_turn_on()
        _LOGGER.info("Turn on: %s -> %s", self.controller.label, on_ok)

        # 2. Tunggu 8 detik
        await asyncio.sleep(8)

        # 3. Kirim toast mulai
        toast_mulai = f"Sesi Paket {self.nama_paket} Telah Dimulai."
        toast_ok = await self.controller.safe_show_toast(toast_mulai)
        _LOGGER.info("Toast mulai: %s -> %s", self.controller.label, toast_ok)

        # 4. Mulai timer
        self._start_time = time.time()
        self._active = True
        self._sent_milestones.clear()
        self._timer_task = asyncio.create_task(self._timer_loop())

    async def finish(self):
        """Akhiri sesi billing.

        1. Batalkan timer
        2. Matikan TV
        3. Jalankan callback on_finish
        """
        _LOGGER.info("=== SESI SELESAI: %s ===", self.controller.label)

        self._active = False
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            try:
                await self._timer_task
            except asyncio.CancelledError:
                pass

        # Matikan TV
        off_ok = await self.controller.safe_turn_off()
        _LOGGER.info("Turn off: %s -> %s", self.controller.label, off_ok)

        # Callback
        if self.on_finish:
            try:
                self.on_finish()
            except Exception as e:
                _LOGGER.error("on_finish callback error: %s", e)

    async def cancel(self):
        """Batalkan sesi tanpa matikan TV (misal operator override)."""
        _LOGGER.info("=== SESI DIBATALKAN: %s ===", self.controller.label)
        self._active = False
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()

    async def _timer_loop(self):
        """Background timer: cek sisa waktu setiap detik, kirim toast."""
        try:
            while self._active:
                await asyncio.sleep(1)

                sisa = self.sisa_waktu
                sisa_menit = sisa // 60

                if sisa <= 0:
                    _LOGGER.info("WAKTU HABIS: %s", self.controller.label)
                    await self.finish()
                    return

                # Cek milestones
                for milestone in self.milestones:
                    key = milestone.sisa_menit
                    if (sisa_menit == key
                            and key not in self._sent_milestones
                            and sisa % 60 == 0):
                        self._sent_milestones.add(key)
                        _LOGGER.info(
                            "TOAST [%s] sisa %d menit: %s",
                            self.controller.label, key, milestone.pesan)
                        await self.controller.safe_show_toast(milestone.pesan)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("Timer error: %s", e)


# ===============================================================================
#  CONTOH / SIMULASI
# ===============================================================================

async def simulasi_lengkap():
    """Simulasi lengkap: load config -> mulai sesi -> timer -> selesai."""

    # -- 1. Buat config file contoh ----------------------------------------
    config_data = {
        "tv_01": {
            "ip_address": "192.168.1.10",
            "mac_address": "AA:BB:CC:DD:EE:01",
            "os_type": "android",
            "port": 5555,
            "label": "PC-01 Android"
        },
        "tv_02": {
            "ip_address": "192.168.1.50",
            "mac_address": "AA:BB:CC:DD:EE:02",
            "os_type": "webos",
            "label": "TV-02 LG webOS"
        }
    }

    config_path = "tvs_config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)
    print(f"[SIMULASI] Config ditulis ke {config_path}\n")

    # -- 2. Load semua TV controller ----------------------------------------
    controllers = load_tv_config(config_path)
    print(f"[SIMULASI] Loaded {len(controllers)} TV:\n")
    for tv_id, ctrl in controllers.items():
        print(f"  {tv_id}: {ctrl}")
    print()

    # -- 3. Pilih TV untuk sesi billing -------------------------------------
    # Misal operator pilih tv_02 (webOS)
    tv_pilih = "tv_02"
    ctrl = controllers[tv_pilih]
    print(f"[SIMULASI] TV dipilih: {tv_pilih} -> {ctrl}\n")

    # -- 4. Mulai sesi billing (durasi 30 detik untuk simulasi) -------------
    session = BillingSession(
        controller=ctrl,
        nama_paket="GOLD 1 Jam",
        duration_detik=30,  # 30 detik untuk demo
    )

    print("[SIMULASI] Memulai sesi...")
    await session.start()

    # Tunggu sesi selesai (timer otomatis finish)
    # Dalam aplikasi nyata, ini berjalan di background selama billing
    while session.is_active:
        sisa = session.sisa_waktu
        menit = sisa // 60
        detik = sisa % 60
        print(f"  [TIMER] Sisa: {menit:02d}:{detik:02d}", end="\r")
        await asyncio.sleep(1)

    print("\n[SIMULASI] Sesi selesai!")
    print(f"[SIMULASI] Status akhir: is_active={session.is_active}")

    # -- 5. Cleanup ---------------------------------------------------------
    if os.path.exists(config_path):
        os.remove(config_path)


async def simulasi_manual():
    """Simulasi manual: operator kontrol satu per satu."""

    # Buat controller langsung tanpa config file
    webos_config = TVConfig(
        tv_id="tv_demo",
        ip_address="192.168.1.50",
        mac_address="AA:BB:CC:DD:EE:FF",
        os_type="webos",
        label="Demo LG webOS",
    )

    ctrl = WebOSTVController(webos_config)
    print(f"[MANUAL] Controller: {repr(ctrl)}\n")

    # Turn on
    print("[MANUAL] Menyalakan TV...")
    ok = await ctrl.safe_turn_on()
    print(f"[MANUAL] Turn on: {ok}\n")

    # Tunggu
    await asyncio.sleep(3)

    # Toast
    print("[MANUAL] Mengirim toast...")
    ok = await ctrl.safe_show_toast("Halo! Ini pesan dari RR Billing Pro.")
    print(f"[MANUAL] Toast: {ok}\n")

    # Cek power
    print("[MANUAL] Cek power state...")
    state = await ctrl.is_powered_on()
    print(f"[MANUAL] Power state: {state}\n")

    # Turn off
    print("[MANUAL] Mematikan TV...")
    ok = await ctrl.safe_turn_off()
    print(f"[MANUAL] Turn off: {ok}\n")

    print("[MANUAL] Selesai!")


# ===============================================================================
#  MAIN
# ===============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  RR BILLING PRO — TV Controller System Test")
    print("=" * 60)
    print()

    pilihan = input("Pilih simulasi:\n"
                     "  1. Simulasi Lengkap (config + session)\n"
                     "  2. Simulasi Manual (satu TV webOS)\n"
                     "Pilihan (1/2): ").strip()

    if pilihan == "2":
        asyncio.run(simulasi_manual())
    else:
        asyncio.run(simulasi_lengkap())
