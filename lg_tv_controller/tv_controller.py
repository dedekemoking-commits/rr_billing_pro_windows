"""
tv_controller.py — Kontrol LG Smart TV (webOS 22) via LAN/Wi-Fi.
Library: wakeonlan (Wake-on-LAN), bscpylgtv (WebSocket control)

Digunakan untuk:
- Menyalakan TV via WOL saat sesi billing dimulai
- Mematikan TV via WebSocket saat waktu billing habis
- Menampilkan toast/popup peringatan di layar TV

Contoh pemakaian:
    controller = TVController()
    controller.turn_on_tv("AA:BB:CC:DD:EE:FF")
    asyncio.run(controller.show_toast_message("192.168.1.100", "Sisa 5 menit!"))
    asyncio.run(controller.turn_off_tv("192.168.1.100"))
"""

import asyncio
import logging
import os
from typing import Optional

from wakeonlan import send_magic_packet
from bscpylgtv import WebOsClient


class TVController:
    """Kontrol LG Smart TV (webOS) via LAN/Wi-Fi.

    Attributes:
        key_file_path: Lokasi file SQLite untuk pairing key WebOS.
            Default: .aiopylgtv.sqlite di working directory.
        timeout: Timeout koneksi ke TV (detik).
        retry_attempts: Jumlah percobaan ulang koneksi.
    """

    def __init__(
        self,
        key_file_path: Optional[str] = None,
        manifest_file_path: Optional[str] = None,
        timeout: int = 5,
        retry_attempts: int = 2,
    ):
        """Inisialisasi TVController.

        Args:
            key_file_path: Path file SQLite untuk pairing key.
                Jika None, gunakan default .aiopylgtv.sqlite
            manifest_file_path: Path file JSON manifest untuk pairing.
                Jika None, gunakan default (akan tampilkan "RR BILLING PRO").
            timeout: Timeout koneksi WebSocket (detik).
            retry_attempts: Jumlah retry jika koneksi gagal.
        """
        self._logger = logging.getLogger("TVController")
        self._timeout = timeout
        self._retry_attempts = max(1, retry_attempts)

        # Path default untuk pairing key storage
        if key_file_path is None:
            self._key_file_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                ".aiopylgtv.sqlite"
            )
        else:
            self._key_file_path = key_file_path

        # Path default untuk manifest (tampilkan "RR BILLING PRO" di TV)
        if manifest_file_path is None:
            default_manifest = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "manifest_rrbillingpro.json"
            )
            if os.path.exists(default_manifest):
                self._manifest_file_path = default_manifest
            else:
                self._manifest_file_path = None
        else:
            self._manifest_file_path = manifest_file_path

        self._logger.info(
            f"TVController init — key: {os.path.basename(self._key_file_path)}, "
            f"manifest: {os.path.basename(self._manifest_file_path) if self._manifest_file_path else 'default'}"
        )

    def turn_on_tv(self, mac_address: str) -> bool:
        """Nyalakan TV via Wake-on-LAN Magic Packet.

        Kirim paket WOL ke MAC address TV. TV harus sudah
        di-setting enabling WoL di menu pengaturan webOS.

        Args:
            mac_address: MAC address TV dalam format:
                "AA:BB:CC:DD:EE:FF" atau "AA-BB-CC-DD-EE-FF" atau "AABBCCDDEEFF"

        Returns:
            True jika paket berhasil dikirim, False jika gagal.
        """
        try:
            # Normalisasi MAC address: hapus separator, pastikan 12 karakter hex
            mac_clean = mac_address.replace(":", "").replace("-", "").replace(".", "")
            if len(mac_clean) != 12:
                self._logger.error(
                    f"MAC address tidak valid: {mac_address} "
                    f"(harus 12 karakter hex, dapat {len(mac_clean)})"
                )
                return False

            # Validasi karakter hex (0-9, A-F)
            if not all(c in "0123456789ABCDEFabcdef" for c in mac_clean):
                invalid = [c for c in mac_clean if c not in "0123456789ABCDEFabcdef"]
                self._logger.error(
                    f"MAC address mengandung karakter tidak valid: {mac_address} "
                    f"( karakter non-hex: {''.join(set(invalid))}) — "
                    f"periksa apakah 'O' (huruf) seharusnya '0' (angka nol)"
                )
                return False

            # Format ulang ke XX:XX:XX:XX:XX:XX untuk wakeonlan
            mac_formatted = ":".join(mac_clean[i:i+2] for i in range(0, 12, 2))

            # Kirim Magic Packet ke broadcast (255.255.255.255:9)
            send_magic_packet(mac_formatted)
            self._logger.info(f"WOL Magic Packet terkirim ke {mac_formatted}")
            return True

        except Exception as e:
            self._logger.error(f"Gagal kirim WOL ke {mac_address}: {e}")
            return False

    async def turn_off_tv(self, ip_address: str) -> bool:
        """Matikan TV via WebSocket (standby mode).

        Koneksi ke TV via bscpylgtv, kirim perintah power_off,
        lalu disconnect. TV akan masuk standby mode.

        Args:
            ip_address: IP address TV di jaringan lokal.

        Returns:
            True jika TV berhasil dimatikan, False jika gagal.
        """
        client = None
        for attempt in range(1, self._retry_attempts + 1):
            try:
                # Buat client baru untuk setiap percobaan
                client = await WebOsClient.create(
                    ip_address,
                    ping_interval=None,
                    states=[],
                    key_file_path=self._key_file_path,
                    timeout_connect=self._timeout,
                    manifest_file_path=self._manifest_file_path,
                )

                # Koneksi ke TV
                self._logger.info(
                    f"Menyambungkan ke TV {ip_address} "
                    f"(percobaan {attempt}/{self._retry_attempts})..."
                )
                await client.connect()

                # Cek apakah TV sudah menyala sebelum kirim power_off
                power_state = await client.get_power_state()
                current_state = power_state.get("state", "Unknown")
                self._logger.info(f"Power state TV {ip_address}: {current_state}")

                # Kirim perintah power_off
                await client.power_off()
                self._logger.info(f"TV {ip_address} berhasil dimatikan (standby)")
                return True

            except ConnectionRefusedError:
                self._logger.warning(
                    f"Koneksi ditolak ke TV {ip_address} "
                    f"(TV mungkin sudah mati atau IP berubah)"
                )
                return False

            except asyncio.TimeoutError:
                self._logger.warning(
                    f"Timeout koneksi ke TV {ip_address} "
                    f"(percobaan {attempt}/{self._retry_attempts})"
                )
                if attempt == self._retry_attempts:
                    self._logger.error(
                        f"Gagal matikan TV {ip_address}: "
                        f"timeout setelah {self._retry_attempts} percobaan"
                    )
                    return False

            except OSError as e:
                # Error jaringan: DNS gagal, unreachable, dll
                self._logger.error(
                    f"Error jaringan saat matikan TV {ip_address}: {e}"
                )
                return False

            except Exception as e:
                self._logger.error(
                    f"Gagal matikan TV {ip_address}: {type(e).__name__}: {e}"
                )
                return False

            finally:
                # Selalu tutup koneksi
                if client:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass  # Abaikan error saat disconnect
                    client = None

        return False

    async def show_toast_message(self, ip_address: str, message: str) -> bool:
        """Tampilkan popup/toast message di layar TV.

        Menampilkan pesan overlay di layar TV. Berguna untuk
        peringatan billing seperti "Waktu tersisa 5 menit".

        Args:
            ip_address: IP address TV di jaringan lokal.
            message: Teks pesan yang ditampilkan (maks ~500 karakter).

        Returns:
            True jika pesan berhasil ditampilkan, False jika gagal.
        """
        if not message or not message.strip():
            self._logger.warning("Pesan kosong, skip toast message")
            return False

        client = None
        for attempt in range(1, self._retry_attempts + 1):
            try:
                # Buat client baru
                client = await WebOsClient.create(
                    ip_address,
                    ping_interval=None,
                    states=[],
                    key_file_path=self._key_file_path,
                    timeout_connect=self._timeout,
                    manifest_file_path=self._manifest_file_path,
                )

                # Koneksi ke TV
                self._logger.info(
                    f"Menyambungkan ke TV {ip_address} untuk toast "
                    f"(percobaan {attempt}/{self._retry_attempts})..."
                )
                await client.connect()

                # Kirim toast message
                await client.send_message(message.strip())
                self._logger.info(
                    f"Toast terkirim ke {ip_address}: {message.strip()[:50]}..."
                )
                return True

            except ConnectionRefusedError:
                self._logger.warning(
                    f"Koneksi ditolak ke TV {ip_address} "
                    f"(TV mungkin mati atau IP berubah)"
                )
                return False

            except asyncio.TimeoutError:
                self._logger.warning(
                    f"Timeout koneksi ke TV {ip_address} untuk toast "
                    f"(percobaan {attempt}/{self._retry_attempts})"
                )
                if attempt == self._retry_attempts:
                    self._logger.error(
                        f"Gagal kirim toast ke {ip_address}: "
                        f"timeout setelah {self._retry_attempts} percobaan"
                    )
                    return False

            except OSError as e:
                self._logger.error(
                    f"Error jaringan saat kirim toast ke {ip_address}: {e}"
                )
                return False

            except Exception as e:
                self._logger.error(
                    f"Gagal kirim toast ke {ip_address}: {type(e).__name__}: {e}"
                )
                return False

            finally:
                # Selalu tutup koneksi
                if client:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                    client = None

        return False

    async def get_power_state(self, ip_address: str) -> Optional[dict]:
        """Cek status power TV.

        Args:
            ip_address: IP address TV di jaringan lokal.

        Returns:
            Dict berisi info power state, contoh:
                {"state": "Active"} — TV menyala
                {"state": "Off"} — TV mati/standby
            Return None jika gagal mengambil status.
        """
        client = None
        try:
            client = await WebOsClient.create(
                ip_address,
                ping_interval=None,
                states=[],
                key_file_path=self._key_file_path,
                timeout_connect=self._timeout,
                manifest_file_path=self._manifest_file_path,
            )
            await client.connect()

            power_state = await client.get_power_state()
            self._logger.debug(f"Power state {ip_address}: {power_state}")
            return power_state

        except Exception as e:
            self._logger.error(
                f"Gagal cek power state {ip_address}: {type(e).__name__}: {e}"
            )
            return None

        finally:
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def is_tv_on(self, ip_address: str) -> bool:
        """Cek apakah TV menyala.

        Args:
            ip_address: IP address TV di jaringan lokal.

        Returns:
            True jika TV menyala, False jika mati atau gagal dicek.
        """
        try:
            state = await self.get_power_state(ip_address)
            if state:
                # bscpylgtv mengembalikan "state" sebagai string
                # "Active" = menyala, lainnya = mati
                is_active = state.get("state", "").lower() in ("active", "on", "unknown")
                self._logger.debug(
                    f"TV {ip_address} {'menyala' if is_active else 'mati'} "
                    f"(state: {state.get('state', 'Unknown')})"
                )
                return is_active
            return False
        except Exception as e:
            self._logger.error(f"Gagal cek status TV {ip_address}: {e}")
            return False


# ═══════════════════════════════════════════════════════════════════════════════
#  CONTOH PEMAKAIAN
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # ══════════════════════════════════════════════════════════════════════════
    #  KONFIGURASI — Ganti dengan data TV Anda
    # ══════════════════════════════════════════════════════════════════════════
    TV_MAC = "AA:BB:CC:DD:EE:FF"    # MAC address LG TV
    TV_IP = "192.168.1.100"         # IP address LG TV

    controller = TVController()

    # ══════════════════════════════════════════════════════════════════════════
    #  1. NYALAKAN TV VIA WAKE-ON-LAN
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*50}")
    print(f"1. Menyalakan TV {TV_MAC} via WOL...")
    print(f"{'='*50}")
    ok = controller.turn_on_tv(TV_MAC)
    print(f"   Hasil: {'Berhasil' if ok else 'Gagal'}")

    # ══════════════════════════════════════════════════════════════════════════
    #  2. CEK STATUS POWER TV
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*50}")
    print(f"2. Mengecek status power TV {TV_IP}...")
    print(f"{'='*50}")

    async def check_power():
        state = await controller.get_power_state(TV_IP)
        if state:
            print(f"   Status: {state.get('state', 'Unknown')}")
        else:
            print(f"   Status: Tidak diketahui (TV offline atau belum terpairing)")

        is_on = await controller.is_tv_on(TV_IP)
        print(f"   TV menyala: {is_on}")
        return is_on

    tv_is_on = asyncio.run(check_power())

    # ══════════════════════════════════════════════════════════════════════════
    #  3. TAMPILKAN TOAST MESSAGE (hanya jika TV menyala)
    # ══════════════════════════════════════════════════════════════════════════
    if tv_is_on:
        print(f"\n{'='*50}")
        print(f"3. Mengirim toast message ke TV {TV_IP}...")
        print(f"{'='*50}")

        async def send_toast():
            pesan = "Waktu tersisa 5 menit! Silakan perpanjang sesi."
            ok = await controller.show_toast_message(TV_IP, pesan)
            print(f"   Pesan: {pesan}")
            print(f"   Hasil: {'Berhasil' if ok else 'Gagal'}")
            return ok

        asyncio.run(send_toast())
    else:
        print(f"\n   [SKIP] Toast message dilewati (TV tidak menyala)")

    # ══════════════════════════════════════════════════════════════════════════
    #  4. MATIKAN TV (uncomment untuk testing)
    # ══════════════════════════════════════════════════════════════════════════
    # print(f"\n{'='*50}")
    # print(f"4. Mematikan TV {TV_IP}...")
    # print(f"{'='*50}")
    #
    # async def turn_off():
    #     ok = await controller.turn_off_tv(TV_IP)
    #     print(f"   Hasil: {'Berhasil' if ok else 'Gagal'}")
    #
    # asyncio.run(turn_off())

    print(f"\n{'='*50}")
    print("Selesai!")
    print(f"{'='*50}\n")
