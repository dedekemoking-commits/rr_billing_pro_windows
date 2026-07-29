import asyncio
import logging
import os
import sys
import threading
from typing import Optional

from androidtvremote2 import (
    AndroidTVRemote as _AndroidTVRemote,
    CannotConnect,
    ConnectionClosed,
    InvalidAuth,
)

_LOGGER = logging.getLogger(__name__)

CERT_DIR_NAME = "android_tv_certs"
CLIENT_NAME   = "RR Billing Pro"

KEY_MAP = {
    "POWER":              "KEYCODE_POWER",
    "HOME":               "KEYCODE_HOME",
    "BACK":               "KEYCODE_BACK",
    "DPAD_UP":            "KEYCODE_DPAD_UP",
    "DPAD_DOWN":          "KEYCODE_DPAD_DOWN",
    "DPAD_LEFT":          "KEYCODE_DPAD_LEFT",
    "DPAD_RIGHT":         "KEYCODE_DPAD_RIGHT",
    "DPAD_CENTER":        "KEYCODE_DPAD_CENTER",
    "VOLUME_UP":          "KEYCODE_VOLUME_UP",
    "VOLUME_DOWN":        "KEYCODE_VOLUME_DOWN",
    "MUTE":               "KEYCODE_MUTE",
    "MEDIA_PLAY_PAUSE":   "KEYCODE_MEDIA_PLAY_PAUSE",
    "MEDIA_STOP":         "KEYCODE_MEDIA_STOP",
    "SLEEP":              "KEYCODE_SLEEP",
    "WAKEUP":             "KEYCODE_WAKEUP",
    "SETTINGS":           "KEYCODE_SETTINGS",
    "TV_POWER":           "KEYCODE_TV_POWER",
    "TV_INPUT":           "KEYCODE_TV_INPUT",
    "HDMI_1":             "KEYCODE_TV_INPUT_HDMI_1",
    "HDMI_2":             "KEYCODE_TV_INPUT_HDMI_2",
    "HDMI_3":             "KEYCODE_TV_INPUT_HDMI_3",
    "HDMI_4":             "KEYCODE_TV_INPUT_HDMI_4",
    "ENTER":              "KEYCODE_ENTER",
    "MENU":               "KEYCODE_MENU",
    "INFO":               "KEYCODE_INFO",
}


def _get_app_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _get_cert_dir() -> str:
    d = os.path.join(_get_app_base_dir(), CERT_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def _cert_paths_for_ip(ip_address: str) -> tuple[str, str]:
    safe = ip_address.replace(".", "_")
    return (
        os.path.join(_get_cert_dir(), f"cert_{safe}.pem"),
        os.path.join(_get_cert_dir(), f"key_{safe}.pem"),
    )


async def pair_tv(ip_address: str, api_port: int = 6466, pair_port: int = 6467) -> dict:
    """Memulai pairing dengan Android TV.

    Mengembalikan dict dengan status 'pairing_started' dan objek remote
    yang harus digunakan untuk finish_pair() dengan PIN dari TV.
    """
    certfile, keyfile = _cert_paths_for_ip(ip_address)
    remote = _AndroidTVRemote(
        client_name=CLIENT_NAME,
        certfile=certfile,
        keyfile=keyfile,
        host=ip_address,
        api_port=api_port,
        pair_port=pair_port,
        enable_ime=False,
    )

    if await remote.async_generate_cert_if_missing():
        _LOGGER.info("Generated new cert for %s", ip_address)
    else:
        _LOGGER.info("Cert already exists for %s", ip_address)

    try:
        name_mac = await remote.async_get_name_and_mac()
    except Exception:
        name_mac = ("Unknown", "Unknown")

    await remote.async_start_pairing()
    _LOGGER.info("Pairing started for %s - enter PIN shown on TV", ip_address)

    return {
        "status": "pairing_started",
        "ip": ip_address,
        "device_name": name_mac[0] if name_mac else "Unknown",
        "device_mac": name_mac[1] if name_mac else "Unknown",
        "certfile": certfile,
        "keyfile": keyfile,
        "remote": remote,
    }


async def finish_pair(remote: _AndroidTVRemote, pin: str) -> dict:
    """Menyelesaikan pairing dengan PIN yang ditampilkan di TV."""
    try:
        await remote.async_finish_pairing(pin)
        _LOGGER.info("Pairing completed successfully")
        remote.disconnect()
        return {"status": "paired", "message": "Pairing berhasil"}
    except InvalidAuth as e:
        _LOGGER.error("Invalid PIN: %s", e)
        return {"status": "error", "message": f"PIN salah: {e}"}
    except ConnectionClosed as e:
        _LOGGER.error("Connection closed during pairing: %s", e)
        return {"status": "error", "message": f"Koneksi terputus: {e}"}
    except Exception as e:
        _LOGGER.exception("Pairing error")
        return {"status": "error", "message": str(e)}


def pair_tv_sync(ip_address: str, api_port: int = 6466, pair_port: int = 6467) -> dict:
    """Versi synchronous dari pair_tv untuk dipanggil dari thread."""
    loop_th = _get_global_loop()
    fut = loop_th.submit(pair_tv(ip_address, api_port, pair_port))
    return fut.result(timeout=30)


def finish_pair_sync(remote: _AndroidTVRemote, pin: str) -> dict:
    """Versi synchronous dari finish_pair."""
    loop_th = _get_global_loop()
    fut = loop_th.submit(finish_pair(remote, pin))
    return fut.result(timeout=30)


class _LoopThread(threading.Thread):
    """Thread daemon yang menjalankan asyncio event loop."""
    def __init__(self) -> None:
        super().__init__(name="androidtv-loop", daemon=True)
        self.loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()

    def run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)

    def submit(self, coro) -> asyncio.Task:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)


_global_loop: Optional[_LoopThread] = None
_global_loop_lock = threading.Lock()


def _get_global_loop() -> _LoopThread:
    global _global_loop
    if _global_loop is None or not _global_loop.is_alive():
        with _global_loop_lock:
            if _global_loop is None or not _global_loop.is_alive():
                _global_loop = _LoopThread()
                _global_loop.start()
    return _global_loop


class AndroidTVRemote:
    def __init__(self):
        self._remote: Optional[_AndroidTVRemote] = None
        self._lock = threading.Lock()
        self._ip: str = ""
        self._connection_method: str = "atpv2"

    def _submit_sync(self, coro, timeout: float = 10):
        loop_th = _get_global_loop()
        return loop_th.submit(coro).result(timeout=timeout)

    async def connect(self, ip_address: str, client_certificate: Optional[str] = None) -> dict:
        """Menghubungkan ke Android TV menggunakan sertifikat hasil pairing.

        Args:
            ip_address: IP Android TV.
            client_certificate: Path ke sertifikat (key file akan dideteksi otomatis).
                                Jika None, path otomatis dari _cert_paths_for_ip().

        Returns:
            dict dengan status 'connected' atau 'error'.
        """
        if client_certificate:
            certfile = os.path.abspath(client_certificate)
            base = os.path.splitext(certfile)[0]
            keyfile = base + ".key" if os.path.isfile(base + ".key") else None
            if not keyfile:
                return {"status": "error", "message": f"Key file tidak ditemukan untuk {certfile}"}
        else:
            certfile, keyfile = _cert_paths_for_ip(ip_address)

        if not os.path.isfile(certfile) or not os.path.isfile(keyfile):
            return {"status": "error", "message": "Sertifikat tidak ditemukan. Lakukan pairing terlebih dahulu."}

        remote = _AndroidTVRemote(
            client_name=CLIENT_NAME,
            certfile=certfile,
            keyfile=keyfile,
            host=ip_address,
            enable_ime=False,
        )

        try:
            await remote.async_connect()
        except InvalidAuth as e:
            return {"status": "error", "message": f"Autentikasi gagal, perlu pairing ulang: {e}"}
        except CannotConnect as e:
            return {"status": "error", "message": f"Tidak dapat terhubung ke {ip_address}: {e}"}
        except ConnectionClosed as e:
            return {"status": "error", "message": f"Koneksi ditutup: {e}"}
        except Exception as e:
            _LOGGER.exception("Connect error")
            return {"status": "error", "message": str(e)}

        remote.keep_reconnecting()
        with self._lock:
            self._remote = remote
            self._ip = ip_address
        _LOGGER.info("Connected to Android TV at %s", ip_address)
        return {"status": "connected", "message": f"Terhubung ke {ip_address}"}

    async def turn_off(self) -> dict:
        """Mematikan TV (mengirim KEYCODE_POWER)."""
        return await self._send_key_async("POWER")

    async def send_home(self) -> dict:
        """Mengirim tombol HOME."""
        return await self._send_key_async("HOME")

    async def send_key(self, key_name: str, direction: str = "SHORT") -> dict:
        """Mengirim key event ke TV."""
        return await self._send_key_async(key_name, direction)

    async def _send_key_async(self, key_name: str, direction: str = "SHORT") -> dict:
        key_code = KEY_MAP.get(key_name, key_name)
        with self._lock:
            if not self._remote:
                return {"status": "error", "message": "Tidak terhubung"}
            try:
                self._remote.send_key_command(key_code, direction)
                return {"status": "ok", "message": f"Key {key_name} sent"}
            except ConnectionClosed as e:
                return {"status": "error", "message": f"Koneksi terputus: {e}"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

    async def volume_up(self) -> dict:
        return await self._send_key_async("VOLUME_UP")

    async def volume_down(self) -> dict:
        return await self._send_key_async("VOLUME_DOWN")

    async def mute(self) -> dict:
        return await self._send_key_async("MUTE")

    async def sleep(self) -> dict:
        return await self._send_key_async("SLEEP")

    async def wakeup(self) -> dict:
        return await self._send_key_async("WAKEUP")

    def turn_off_blocking(self) -> dict:
        return self._submit_sync(self.turn_off())

    def send_home_blocking(self) -> dict:
        return self._submit_sync(self.send_home())

    def send_key_blocking(self, key_name: str, direction: str = "SHORT") -> dict:
        return self._submit_sync(self.send_key(key_name, direction))

    def volume_up_blocking(self) -> dict:
        return self._submit_sync(self.volume_up())

    def volume_down_blocking(self) -> dict:
        return self._submit_sync(self.volume_down())

    def mute_blocking(self) -> dict:
        return self._submit_sync(self.mute())

    def sleep_blocking(self) -> dict:
        return self._submit_sync(self.sleep())

    def wakeup_blocking(self) -> dict:
        return self._submit_sync(self.wakeup())

    def connect_blocking(self, ip_address: str, client_certificate: Optional[str] = None) -> dict:
        return self._submit_sync(self.connect(ip_address, client_certificate), timeout=15)

    def disconnect(self) -> None:
        with self._lock:
            if self._remote:
                try:
                    self._remote.disconnect()
                except Exception:
                    pass
                self._remote = None

    def is_connected(self) -> bool:
        if not self._remote:
            return False
        try:
            proto = getattr(self._remote, '_remote_message_protocol', None)
            if not proto:
                return False
            transport = getattr(proto, 'transport', None)
            if not transport or transport.is_closing():
                return False
            return True
        except Exception:
            return False

    async def check_connection(self) -> dict:
        if not self.is_connected():
            return {"status": "error", "message": "Tidak terhubung"}
        try:
            info = self._remote.device_info
            if info:
                return {"status": "ok", "device_info": str(info)}
            return {"status": "error", "message": "Device info tidak tersedia"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def check_connection_blocking(self) -> dict:
        return self._submit_sync(self.check_connection(), timeout=8)

    @property
    def device_info(self) -> Optional[dict]:
        if self._remote:
            return self._remote.device_info
        return None

    @property
    def is_on(self) -> Optional[bool]:
        if self._remote:
            return self._remote.is_on
        return None

    @property
    def volume_info(self) -> Optional[dict]:
        if self._remote:
            return self._remote.volume_info
        return None

    @property
    def current_app(self) -> Optional[str]:
        if self._remote:
            return self._remote.current_app
        return None


def certs_exist_for(ip_address: str) -> bool:
    cf, kf = _cert_paths_for_ip(ip_address)
    return os.path.isfile(cf) and os.path.isfile(kf)


def get_cert_storage_path() -> str:
    return _get_cert_dir()
