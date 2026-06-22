"""
rr_license.py — Sistem Aktivasi Aman untuk RR BILLING PRO
==========================================================

ARSITEKTUR KEAMANAN
-------------------
1. Kode lisensi = Base32 dari payload terenkripsi HMAC-SHA256
   Format internal (sebelum encode):
       <edition>:<machine_id>:<expiry_yyyymmdd>:<checksum_8hex>

2. Machine ID diturunkan dari hardware fingerprint (MAC address + hostname)
   sehingga kode lisensi HANYA valid di mesin yang didaftarkan.

3. SERVER_SECRET adalah kunci rahasia yang hanya diketahui developer.
   Di produksi, simpan di environment variable / server — JANGAN hardcode.

4. Format kode yang dilihat user:
       RR-XXXX-XXXX-XXXX-XXXX   (Base32, 20 char payload + dashes)

WORKFLOW
--------
  Developer (generate_license_code) → kirim kode → user (aktivasi di app)
  App verifikasi HMAC + machine_id + expiry → tulis license.json

CARA GENERATE KODE (sisi developer/admin)
-----------------------------------------
  from rr_license import LicenseGenerator
  kode = LicenseGenerator.generate("PRO", machine_id="AUTO", days=365)
  print(kode)   # → RR-ABCD-EFGH-IJKL-MNOP

  Atau jalankan langsung:
  $ python rr_license.py generate PRO 365 [machine_id]
"""

import os
import json
import uuid
import socket
import hashlib
import hmac
import base64
import struct
import time
try:
    import fcntl  # For Unix/Linux file locking
except ImportError:
    fcntl = None  # Windows tidak support fcntl
from datetime import datetime, timedelta, date

# ─── KUNCI RAHASIA ────────────────────────────────────────────────────────────
# Di produksi: ganti dengan os.environ["RR_LICENSE_SECRET"]
# Kunci ini HARUS sama antara generator (sisi developer) dan validator (sisi app).
_DEFAULT_SECRET = "RR-CCTV-2026-BILLING-PRO-SECRET-KEY-JANGAN-BOCOR"

def _get_secret() -> bytes:
    """Ambil secret dari environment variable, fallback ke default."""
    raw = os.environ.get("RR_LICENSE_SECRET", _DEFAULT_SECRET)
    return raw.encode("utf-8")


# ─── MACHINE FINGERPRINT ──────────────────────────────────────────────────────
def get_machine_id() -> str:
    """
    Buat fingerprint mesin dari MAC address + hostname.
    Hasilnya stabil selama NIC dan hostname tidak berubah.
    Disingkat jadi 12 karakter hex untuk kenyamanan.
    """
    try:
        mac = uuid.getnode()                        # integer MAC address
        host = socket.gethostname().lower()
        raw = f"{mac}:{host}".encode()
        digest = hashlib.sha256(raw).hexdigest()
        return digest[:12].upper()                  # 12 hex = 48-bit uniqueness
    except Exception:
        return "000000000000"


# ─── ENCODE / DECODE KODE LISENSI ─────────────────────────────────────────────
_CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # 32 simbol, tanpa I/O/0/1

def _to_b32(data: bytes) -> str:
    """Encode bytes ke custom Base32 string (tanpa padding '=')."""
    bits = int.from_bytes(data, "big")
    n = len(data) * 8
    chars = []
    while n >= 5:
        chars.append(_CHARSET[(bits >> (n - 5)) & 0x1F])
        n -= 5
    # Sisa bit < 5: pad ke kiri jadi 5 bit
    if n > 0:
        chars.append(_CHARSET[(bits & ((1 << n) - 1)) << (5 - n)])
    return "".join(chars)

def _from_b32(s: str) -> bytes:
    """Decode custom Base32 string ke bytes. Raise ValueError jika invalid."""
    bits = 0
    count = 0
    for ch in s:
        idx = _CHARSET.find(ch.upper())
        if idx == -1:
            raise ValueError(f"Karakter tidak valid: '{ch}'")
        bits = (bits << 5) | idx
        count += 5
    # Potong bit berlebih (padding)
    extra = count % 8
    bits >>= extra
    count -= extra
    return bits.to_bytes(count // 8, "big")

def _format_kode(raw: str) -> str:
    """Tambahkan prefix RR- dan pisahkan tiap 4 karakter dengan dash."""
    # Pad ke kelipatan 4
    padded = raw + "A" * (-len(raw) % 4)
    groups = [padded[i:i+4] for i in range(0, len(padded), 4)]
    return "RR-" + "-".join(groups)

def _unformat_kode(kode: str) -> str:
    """Hapus prefix dan dash dari kode lisensi, kembalikan raw Base32."""
    clean = kode.upper().replace("-", "").replace(" ", "")
    if clean.startswith("RR"):
        clean = clean[2:]
    return clean


# ─── STRUKTUR PAYLOAD ─────────────────────────────────────────────────────────
# Payload (sebelum HMAC): 8 byte
#   [0]    edition  : 1 byte  (0x01=Bulanan, 0x03=3Bulan, 0x0C=Tahunan, 0xFF=Lifetime)
#   [1..4] expiry   : 4 byte  (unix timestamp hari, days since epoch)
#   [5..6] machine  : 2 byte  (folded CRC-32 dari machine_id/username, 0x0000 = semua mesin)
#                     ↳ Formula: (CRC-32 XOR (CRC-32 >> 16)) & 0xFFFF — reduce collision risk
#   [7]    reserved : 1 byte  (0x00)
# Signature: HMAC-SHA256(SECRET, payload)[0:4]  → 4 byte
# Total encode: 12 byte → 20 Base32 char → kode ~28 char dengan dash

EDITION_MAP = {
    "BULANAN":   0x01,
    "3BULAN":    0x03,
    "TAHUNAN":   0x0C,
    "LIFETIME":  0xFF,
}
EDITION_NAMA = {v: k for k, v in EDITION_MAP.items()}

EDITION_HARI = {
    0x01: 31,
    0x03: 92,
    0x0C: 365,
    0xFF: 36500,   # ~100 tahun
}


def _crc32(s: str) -> int:
    """
    CRC-32/IEEE dari string - lebih aman dari CRC-16.
    Return nilai 32-bit full range untuk internal use.
    Saat masukkan ke payload, akan di-mod dengan 0xFFFF untuk backward compat dengan 2-byte field.
    """
    crc = 0xFFFFFFFF
    poly = 0xEDB88320
    for b in s.encode():
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
    return crc ^ 0xFFFFFFFF


def _crc16_legacy(s: str) -> int:
    """CRC-16/CCITT dari string - dipakai untuk backward compatibility saja."""
    crc = 0xFFFF
    for b in s.encode():
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
        crc &= 0xFFFF
    return crc


def _crc16(s: str) -> int:
    """
    IMPROVED: Gunakan CRC-32 tapi mask ke 2-byte untuk backward compatibility dengan payload.
    Ini reduce collision risk signifikan dibanding pure CRC-16.
    Formula: (CRC-32 XOR (CRC-32 >> 16)) & 0xFFFF
    Ini spread bits lebih baik dari CRC-16 biasa.
    """
    crc32_val = _crc32(s)
    # Fold CRC-32 menjadi 2 byte untuk spread collision risk
    machine_crc = (crc32_val ^ (crc32_val >> 16)) & 0xFFFF
    return machine_crc


def _days_since_epoch(d: date) -> int:
    return (d - date(2000, 1, 1)).days   # epoch = 1 Jan 2000


def _epoch_to_date(n: int) -> date:
    return date(2000, 1, 1) + timedelta(days=n)


def _build_payload(edition_byte: int, expiry_days: int, machine_crc: int) -> bytes:
    return struct.pack(">BIHB", edition_byte, expiry_days, machine_crc, 0x00)
    # B=1 I=4 H=2 B=1 → total 8 byte


def _sign(payload: bytes) -> bytes:
    """Hitung HMAC-SHA256 dan ambil 4 byte pertama sebagai signature."""
    sig = hmac.new(_get_secret(), payload, hashlib.sha256).digest()
    return sig[:4]


# ─── GENERATOR (SISI DEVELOPER) ───────────────────────────────────────────────
class LicenseGenerator:
    """
    Dipakai oleh developer/admin untuk menerbitkan kode lisensi.
    Tidak perlu ada di binary yang didistribusikan ke user (bisa di server).
    """

    @staticmethod
    def generate(edition: str = "BULANAN",
                 machine_id: str = "AUTO",
                 days: int = None,
                 start_date: date = None) -> str:
        """
        Buat kode lisensi baru.

        Parameters
        ----------
        edition     : "BULANAN" | "3BULAN" | "TAHUNAN" | "LIFETIME"
        machine_id  : 12-char hex fingerprint mesin, atau "AUTO" (generate di mesin ini)
                      atau "ANY" (lisensi bisa dipakai di semua mesin — kurang aman)
        days        : override jumlah hari aktif (default dari edition)
        start_date  : tanggal mulai (default: hari ini)

        Returns
        -------
        str : kode lisensi berformat "RR-XXXX-XXXX-XXXX-XXXX-XXXX"
        """
        edition_upper = edition.upper().replace(" ", "").replace("-", "")
        if edition_upper not in EDITION_MAP:
            raise ValueError(f"Edition tidak dikenal: {edition}. Pilih: {list(EDITION_MAP)}")

        edition_byte = EDITION_MAP[edition_upper]
        hari         = days if days is not None else EDITION_HARI[edition_byte]
        mulai        = start_date or date.today()
        expiry       = mulai + timedelta(days=hari)
        expiry_days  = _days_since_epoch(expiry)

        if machine_id == "AUTO":
            mid = get_machine_id()
        elif machine_id.upper() in ("ANY", "ALL", "*"):
            mid = "000000000000"   # crc16("000000000000") → universal
        else:
            mid = machine_id.upper()[:12]

        machine_crc = _crc16(mid) if mid != "000000000000" else 0x0000

        payload   = _build_payload(edition_byte, expiry_days, machine_crc)
        signature = _sign(payload)
        encoded   = _to_b32(payload + signature)
        return _format_kode(encoded)

    @staticmethod
    def info(kode: str) -> dict:
        """Decode dan tampilkan info kode tanpa verifikasi machine_id (untuk admin)."""
        raw = _unformat_kode(kode)
        try:
            data = _from_b32(raw)
        except ValueError as e:
            return {"valid": False, "error": str(e)}

        if len(data) < 12:
            return {"valid": False, "error": f"Panjang data kurang ({len(data)} byte, butuh 12)"}

        payload   = data[:8]
        signature = data[8:12]
        expected  = _sign(payload)

        if not hmac.compare_digest(signature, expected):
            return {"valid": False, "error": "Signature tidak cocok"}

        edition_byte, expiry_days, machine_crc, _ = struct.unpack(">BIHB", payload)
        expiry_date = _epoch_to_date(expiry_days)

        return {
            "valid":        True,
            "edition":      EDITION_NAMA.get(edition_byte, f"0x{edition_byte:02X}"),
            "expiry":       expiry_date.isoformat(),
            "machine_crc":  f"{machine_crc:04X}",
            "universal":    machine_crc == 0x0000,
            "expired":      expiry_date < date.today(),
        }


# ─── VALIDATOR (SISI APP) ─────────────────────────────────────────────────────
class LicenseValidator:
    """
    Dipakai oleh aplikasi RR Billing untuk memverifikasi kode lisensi.
    """

    @staticmethod
    def verify(kode: str, machine_id: str = None) -> tuple:
        """
        Verifikasi kode lisensi.

        Returns
        -------
        (sukses: bool, pesan: str, info: dict)
        info berisi edition, expiry, dsb. jika sukses.
        """
        if not kode or not kode.strip():
            return False, "Kode tidak boleh kosong.", {}

        raw = _unformat_kode(kode)

        # 1. Decode Base32
        try:
            data = _from_b32(raw)
        except ValueError as e:
            return False, f"Format kode tidak valid: {e}", {}

        # 2. Cek panjang minimum
        if len(data) < 12:
            return False, "Kode terlalu pendek atau korup.", {}

        payload   = data[:8]
        signature = data[8:12]

        # 3. Verifikasi HMAC (pastikan kode diterbitkan oleh developer)
        expected = _sign(payload)
        if not hmac.compare_digest(signature, expected):
            return False, "Tanda tangan kode tidak valid. Pastikan kode diketik dengan benar.", {}

        # 4. Decode payload
        try:
            edition_byte, expiry_days, machine_crc, _ = struct.unpack(">BIHB", payload)
        except struct.error:
            return False, "Payload kode korup.", {}

        expiry_date = _epoch_to_date(expiry_days)
        edition_nm  = EDITION_NAMA.get(edition_byte, "UNKNOWN")

        # 5. Cek expiry
        if expiry_date < date.today():
            return (False,
                    f"Kode lisensi sudah kedaluwarsa sejak {expiry_date.strftime('%d %B %Y')}.",
                    {"edition": edition_nm, "expiry": expiry_date.isoformat()})

        # 6. Cek machine binding (jika machine_crc != 0x0000 = universal)
        if machine_crc != 0x0000:
            mid  = machine_id or get_machine_id()
            my_crc = _crc16(mid)
            if my_crc != machine_crc:
                return (False,
                        "Kode lisensi ini tidak terdaftar untuk perangkat ini.\n"
                        "Hubungi admin untuk mendapatkan kode baru.",
                        {})

        info = {
            "edition":    edition_nm,
            "expiry":     expiry_date.isoformat(),
            "universal":  machine_crc == 0x0000,
            "edition_byte": edition_byte,
        }
        sisa = (expiry_date - date.today()).days
        return (True,
                f"Lisensi {edition_nm} aktif hingga {expiry_date.strftime('%d %B %Y')} "
                f"(sisa {sisa} hari). 🎉",
                info)


# ─── LICENSE MANAGER (PENGGANTI KELAS LAMA) ───────────────────────────────────
LICENSE_FILE = "rr_billing_license.json"
TRIAL_DAYS   = 3     # masa trial gratis: 3 hari

class LicenseManager:
    """
    Drop-in replacement untuk LicenseManager lama.
    API publik tetap sama agar tidak perlu banyak ubah kode utama.
    """

    @staticmethod
    def load() -> dict:
        if os.path.exists(LICENSE_FILE):
            try:
                with open(LICENSE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    @staticmethod
    def save(data: dict):
        with open(LICENSE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def get_machine_id() -> str:
        return get_machine_id()

    @staticmethod
    def _today_str() -> str:
        return date.today().isoformat()   # "YYYY-MM-DD"

    @staticmethod
    def _check_clock_tamper(lic: dict) -> bool:
        """
        Deteksi apakah jam/tanggal sistem dimundurkan.
        Bandingkan hari ini dengan 'last_seen' yang tersimpan.
        Return True jika terdeteksi manipulasi (hari ini < last_seen).
        """
        last_seen = lic.get("last_seen", "")
        today_str = LicenseManager._today_str()
        if last_seen and today_str < last_seen:
            return True   # tanggal dimundurkan!
        return False

    @staticmethod
    def _update_last_seen(lic: dict) -> dict:
        """Perbarui last_seen ke hari ini jika hari ini lebih maju."""
        today_str = LicenseManager._today_str()
        if today_str > lic.get("last_seen", ""):
            lic["last_seen"] = today_str
        return lic

    @staticmethod
    def _get_trial_status_from_config(username: str) -> dict:
        """
        Cek trial status dari config (per-username).
        Ini prevent trial reset saat ganti PC dengan username yang sama.
        Direct file read (avoid circular imports).
        
        Returns: {"trial_start": "YYYY-MM-DD", "trial_days": N} atau empty dict jika tidak ada.
        """
        try:
            config_file = "rr_billing_config.json"
            if not os.path.exists(config_file):
                return {}
            
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            
            trial_users = cfg.get("trial_users", {})
            if username in trial_users:
                return trial_users[username]
        except Exception as e:
            print(f"Error reading trial status from config: {e}")
        
        return {}

    @staticmethod
    def _set_trial_status_in_config(username: str, trial_start: date, trial_days: int = TRIAL_DAYS):
        """
        Simpan trial status ke config (per-username).
        Direct file write dengan locking (avoid circular imports).
        """
        try:
            config_file = "rr_billing_config.json"
            lock_file = config_file + ".lock"
            
            # Load current config
            cfg = {}
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            
            # Update trial_users
            trial_users = cfg.get("trial_users", {})
            trial_users[username] = {
                "trial_start": trial_start.isoformat(),
                "trial_days": trial_days,
            }
            cfg["trial_users"] = trial_users
            
            # Save with locking (same as ConfigManager)
            max_retry = 10
            retry_delay = 0.05
            
            for attempt in range(max_retry):
                try:
                    with open(lock_file, 'a') as lock:
                        if os.name == 'nt':  # Windows
                            import msvcrt
                            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                            try:
                                with open(config_file, "w", encoding="utf-8") as f:
                                    json.dump(cfg, f, indent=2, ensure_ascii=False)
                            finally:
                                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                        else:  # Unix/Linux
                            if fcntl is not None:
                                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                                try:
                                    with open(config_file, "w", encoding="utf-8") as f:
                                        json.dump(cfg, f, indent=2, ensure_ascii=False)
                                finally:
                                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                            else:
                                # fcntl not available, write without lock
                                with open(config_file, "w", encoding="utf-8") as f:
                                    json.dump(cfg, f, indent=2, ensure_ascii=False)
                    return  # Success
                except (IOError, OSError):
                    if attempt < max_retry - 1:
                        time.sleep(retry_delay)
                        continue
                    else:
                        raise
        except Exception as e:
            print(f"Error saving trial status to config: {e}")

    @staticmethod
    def _get_user_trial_status(username: str) -> dict:
        """Return trial state for a given username, creating it if missing."""
        if not username:
            return {}
        trial_cfg = LicenseManager._get_trial_status_from_config(username)
        if not trial_cfg:
            LicenseManager._set_trial_status_in_config(username, date.today())
            trial_cfg = LicenseManager._get_trial_status_from_config(username)
        return trial_cfg or {}

    @staticmethod
    def get_status(current_user: str = "") -> dict:
        """
        Get license status. Support per-username trial binding.
        
        Parameters
        ----------
        current_user : str, optional
            Username saat ini login (untuk check per-user trial)
        """
        if not current_user:
            return {
                "status": "unknown",
                "sisa_hari": 0,
                "pesan": "Silakan login untuk melihat status lisensi.",
            }

        lic = LicenseManager.load()
 
        # ── Sudah aktif & terverifikasi sebelumnya ────────────────────────────
        if lic.get("aktif"):
            kode = lic.get("kode_aktivasi", "")

            # ── CEK BINDING MODE ──────────────────────────────────────────────
            # Saat aktivasi, kita simpan "binding_mode" di license.json.
            # Kalau "username" → verifikasi ulang pakai username yg tersimpan.
            # Kalau "universal" atau "machine" → verifikasi pakai machine_id biasa.
            binding_mode = lic.get("binding_mode", "machine")
            bound_username = lic.get("username", "")

            if binding_mode == "username" and bound_username:
                if not current_user:
                    return {
                        "status": "unknown",
                        "sisa_hari": 0,
                        "pesan": "Silakan login untuk melihat status lisensi.",
                    }
                if current_user != bound_username:
                    trial_cfg = LicenseManager._get_user_trial_status(current_user)
                    trial_start = trial_cfg.get("trial_start")
                    trial_days = int(trial_cfg.get("trial_days", TRIAL_DAYS))
                    if trial_start:
                        try:
                            start_date = date.fromisoformat(trial_start)
                            sisa = max(0, trial_days - (date.today() - start_date).days)
                        except Exception:
                            sisa = trial_days
                    else:
                        sisa = trial_days
                    return {
                        "status":    "trial" if sisa > 0 else "expired",
                        "sisa_hari": sisa,
                        "pesan":     f"Mode Trial — sisa {sisa} hari",
                    }

                verify_user = current_user
                try:
                    from rr_keygen import verify_for_username
                    sukses, _, info = verify_for_username(kode, verify_user)
                except ImportError:
                    # Fallback jika rr_keygen tidak tersedia
                    sukses, _, info = LicenseValidator.verify(kode, machine_id=verify_user)
            else:
                sukses, _, info = LicenseValidator.verify(kode)

            if sukses:
                expiry = info.get("expiry", "")
                sisa = (datetime.fromisoformat(expiry).date() - date.today()).days if expiry else 9999
                lic = LicenseManager._update_last_seen(lic)
                lic["status"] = "active"
                LicenseManager.save(lic)
                return {
                    "status":    "active",
                    "sisa_hari": sisa,
                    "pesan":     f"Lisensi {info.get('edition','PRO')} aktif ✅  (sisa {sisa} hari)",
                    "edition":   info.get("edition", ""),
                }
            else:
                # Kode tidak valid / expired → turunkan ke trial
                lic["aktif"] = False
                LicenseManager.save(lic)

        # ── Inisialisasi pertama kali (belum ada file) ────────────────────────
        if not lic:
            today_str = LicenseManager._today_str()
            lic = {
                "status":         "trial",
                "mulai":          datetime.now().isoformat(),
                "mulai_date":     today_str,
                "last_seen":      today_str,
                "aktif":          False,
                "kode_aktivasi":  "",
            }
            LicenseManager.save(lic)
            # Simpan trial user ke config jika ada current_user
            if current_user:
                LicenseManager._set_trial_status_in_config(current_user, date.today())
            return {
                "status":    "trial",
                "sisa_hari": TRIAL_DAYS,
                "pesan":     f"Mode Trial — sisa {TRIAL_DAYS} hari",
            }

        # ── Deteksi jam dimundurkan ────────────────────────────────────────────
        if LicenseManager._check_clock_tamper(lic):
            return {
                "status":    "expired",
                "sisa_hari": 0,
                "pesan":     "Trial tidak valid — jam sistem tidak sesuai. Aktifkan lisensi.",
            }

        # ── Hitung sisa trial dari local license.json ──────────────────────────
        mulai_str  = lic.get("mulai_date") or lic.get("mulai", LicenseManager._today_str())[:10]
        mulai_date = date.fromisoformat(mulai_str[:10])
        hari_terpakai = (date.today() - mulai_date).days
        sisa = TRIAL_DAYS - hari_terpakai

        # ── FALLBACK: Check trial dari config jika sisa < 0 (PC swap case) ────
        if sisa < 0 and current_user:
            trial_cfg = LicenseManager._get_trial_status_from_config(current_user)
            if trial_cfg:
                trial_start_str = trial_cfg.get("trial_start")
                trial_days = trial_cfg.get("trial_days", TRIAL_DAYS)
                try:
                    trial_start = date.fromisoformat(trial_start_str)
                    hari_terpakai_cfg = (date.today() - trial_start).days
                    sisa_cfg = trial_days - hari_terpakai_cfg
                    if sisa_cfg > sisa:  # Config punya trial lebih baru
                        sisa = sisa_cfg
                        # Update local license.json untuk keep in sync
                        lic["mulai_date"] = trial_start.isoformat()
                        LicenseManager.save(lic)
                except Exception:
                    pass

        lic = LicenseManager._update_last_seen(lic)
        LicenseManager.save(lic)

        if sisa > 0:
            return {"status": "trial", "sisa_hari": sisa,
                    "pesan": f"Mode Trial — sisa {sisa} hari"}
        return {"status": "expired", "sisa_hari": 0,
                "pesan": "Trial habis — Aktifkan lisensi"}

    @staticmethod
    def aktivasi(kode: str, username: str = "", binding_mode: str = "machine") -> tuple:
        """
        Verifikasi & simpan lisensi.

        Parameters
        ----------
        kode         : kode aktivasi format RR-XXXX-XXXX-XXXX
        username     : username yang login saat aktivasi (untuk binding username)
        binding_mode : "username" | "universal" | "machine"

        Returns (sukses: bool, pesan: str)
        """
        mid = get_machine_id()

        if binding_mode == "username" and username:
            try:
                from rr_keygen import verify_for_username
                sukses, pesan, info = verify_for_username(kode, username)
            except ImportError:
                sukses, pesan, info = LicenseValidator.verify(kode, machine_id=mid)
        else:
            sukses, pesan, info = LicenseValidator.verify(kode, machine_id=mid)

        # Fallback: coba universal jika gagal
        if not sukses:
            sukses_uni, pesan_uni, info_uni = LicenseValidator.verify(kode)
            if sukses_uni and info_uni.get("universal"):
                sukses, pesan, info = sukses_uni, pesan_uni, info_uni
                binding_mode = "universal"

        if not sukses:
            return False, pesan

        lic = LicenseManager.load()
        lic.update({
            "aktif":          True,
            "status":         "active",
            "kode_aktivasi":  kode.upper(),
            "tgl_aktivasi":   datetime.now().isoformat(),
            "edition":        info.get("edition", ""),
            "expiry":         info.get("expiry", ""),
            "machine_id":     mid,
            "username":       username,
            "binding_mode":   binding_mode,   # ← KUNCI SINKRONISASI
        })
        LicenseManager.save(lic)
        return True, pesan


# ─── CLI SEDERHANA UNTUK GENERATE KODE (sisi developer) ───────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "generate":
        edition_arg = sys.argv[2] if len(sys.argv) > 2 else "BULANAN"
        days_arg    = int(sys.argv[3]) if len(sys.argv) > 3 else None
        machine_arg = sys.argv[4] if len(sys.argv) > 4 else "AUTO"

        kode = LicenseGenerator.generate(edition_arg, machine_id=machine_arg, days=days_arg)
        print(f"Kode lisensi : {kode}")
        print(f"Machine ID   : {get_machine_id() if machine_arg == 'AUTO' else machine_arg}")
        info = LicenseGenerator.info(kode)
        print(f"Info         : {info}")
    elif len(sys.argv) >= 3 and sys.argv[1] == "verify":
        sukses, pesan, info = LicenseValidator.verify(sys.argv[2])
        print(f"Sukses : {sukses}")
        print(f"Pesan  : {pesan}")
        print(f"Info   : {info}")
    else:
        print("Pemakaian:")
        print("  python rr_license.py generate <EDITION> [days] [machine_id|AUTO|ANY]")
        print("  python rr_license.py verify <kode>")
        print(f"\nMachine ID mesin ini: {get_machine_id()}")