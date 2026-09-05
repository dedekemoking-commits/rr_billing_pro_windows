"""
Supabase Sync Module untuk RR Billing Pro
- Upload transaksi ke Supabase (PostgreSQL)
- Batch upload untuk hemat quota
- Exponential backoff saat error
- Fallback ke Firestore jika Supabase gagal
"""
import json
import logging
import time
import threading
from typing import Optional
from collections import OrderedDict

import requests

_LOGGER = logging.getLogger(__name__)

# ── Konfigurasi Supabase ──────────────────────────────────────────────────
SUPABASE_URL = "https://nqaucjpbnewckedqcezb.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5xYXVjanBibmV3Y2tlZHFjZXpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg1MjUyNzUsImV4cCI6MjEwNDEwMTI3NX0.xi-h-3E2Yww95HzXsNmmiOmdvMKi_TaFNw8Op7xryig"
SUPABASE_TABLE = "transaksi"

# ── Global State ───────────────────────────────────────────────────────────
_THROTTLED_UNTIL = 0.0
_THROTTLE_COUNT = 0
_THROTTLE_BASE = 60.0
_THROTTLE_MAX = 900.0
_BATCH_QUEUE: list[dict] = []
_BATCH_LOCK = threading.Lock()
_UPLOAD_LOCK = threading.Lock()

# ── Document Cache ─────────────────────────────────────────────────────────
_DOC_CACHE: OrderedDict[str, tuple[float, list]] = OrderedDict()
_DOC_CACHE_MAX = 50
_DOC_CACHE_TTL = 30.0


def _cache_get(key: str) -> Optional[list]:
    entry = _DOC_CACHE.get(key)
    if entry is None:
        return None
    ts, data = entry
    if time.time() - ts > _DOC_CACHE_TTL:
        _DOC_CACHE.pop(key, None)
        return None
    return data


def _cache_put(key: str, data: list) -> None:
    _DOC_CACHE[key] = (time.time(), data)
    while len(_DOC_CACHE) > _DOC_CACHE_MAX:
        _DOC_CACHE.popitem(last=False)


def _cache_invalidate(key: str) -> None:
    _DOC_CACHE.pop(key, None)


# ── Supabase Client ────────────────────────────────────────────────────────
class SupabaseClient:
    """Client untuk berinteraksi dengan Supabase REST API."""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        })

    def _throttled(self) -> bool:
        return time.time() < _THROTTLED_UNTIL

    def _note_error(self, status: int, ctx: str) -> None:
        global _THROTTLED_UNTIL, _THROTTLE_COUNT
        if status == 429 or status >= 500:
            _THROTTLE_COUNT += 1
            delay = min(_THROTTLE_BASE * (2 ** (_THROTTLE_COUNT - 1)), _THROTTLE_MAX)
            _THROTTLED_UNTIL = time.time() + delay
            _LOGGER.warning("%s HTTP %d — jeda %ds", ctx, status, int(delay))
        elif status in (200, 201, 204):
            _THROTTLE_COUNT = 0

    # ── CRUD ───────────────────────────────────────────────────────────────

    def upsert(self, rows: list[dict]) -> bool:
        """Upsert beberapa baris ke tabel transaksi."""
        if not rows:
            return True
        if self._throttled():
            return False
        url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
        try:
            resp = self._session.post(
                url,
                json=rows,
                headers={"Prefer": "resolution=merge-duplicates"},
                timeout=30,
            )
            if resp.status_code in (200, 201):
                return True
            self._note_error(resp.status_code, "upsert")
            _LOGGER.warning("supabase upsert HTTP %d: %s", resp.status_code, resp.text[:300])
            return False
        except requests.RequestException as e:
            _LOGGER.warning("supabase upsert error: %s", e)
            return False

    def query(self, params: dict = None) -> list[dict]:
        """Query dari tabel transaksi."""
        if self._throttled():
            return []
        url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
        try:
            resp = self._session.get(url, params=params or {}, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            self._note_error(resp.status_code, "query")
            _LOGGER.warning("supabase query HTTP %d: %s", resp.status_code, resp.text[:200])
            return []
        except requests.RequestException as e:
            _LOGGER.warning("supabase query error: %s", e)
            return []

    def delete_by_username(self, username: str) -> bool:
        """Hapus semua transaksi untuk username tertentu."""
        if self._throttled():
            return False
        url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
        try:
            resp = self._session.delete(
                url,
                params={"username": f"eq.{username}"},
                timeout=15,
            )
            if resp.status_code in (200, 204):
                return True
            self._note_error(resp.status_code, "delete")
            return False
        except requests.RequestException as e:
            _LOGGER.warning("supabase delete error: %s", e)
            return False


# ── Batch Queue ────────────────────────────────────────────────────────────
def batch_add(username: str, tx: dict) -> None:
    """Tambah transaksi ke antrian batch."""
    with _BATCH_LOCK:
        tx["username"] = username
        _BATCH_QUEUE.append(tx)


def batch_flush() -> int:
    """Flush semua transaksi di antrian ke Supabase.
    Mengembalikan jumlah transaksi yang berhasil di-upload."""
    with _BATCH_LOCK:
        if not _BATCH_QUEUE:
            return 0
        pending = list(_BATCH_QUEUE)
        _BATCH_QUEUE.clear()

    if not pending:
        return 0

    with _UPLOAD_LOCK:
        client = SupabaseClient()
        ok = client.upsert(pending)
        if ok:
            _LOGGER.info("Supabase: %d transaksi di-upload", len(pending))
            return len(pending)
        else:
            _LOGGER.warning("Supabase: gagal upload %d transaksi", len(pending))
            return 0


# ── Direct Upload (tanpa batch) ────────────────────────────────────────────
def push_transaction(username: str, tx: dict) -> bool:
    """Upload 1 transaksi langsung ke Supabase."""
    with _UPLOAD_LOCK:
        client = SupabaseClient()
        tx["username"] = username
        return client.upsert([tx])


def push_transactions(username: str, txs: list[dict]) -> bool:
    """Upload beberapa transaksi langsung ke Supabase."""
    with _UPLOAD_LOCK:
        client = SupabaseClient()
        for tx in txs:
            tx["username"] = username
        return client.upsert(txs)


def fetch_transactions(username: str, limit: int = 1000) -> list[dict]:
    """Ambil transaksi dari Supabase untuk username tertentu."""
    cache_key = f"tx_{username}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    client = SupabaseClient()
    params = {
        "username": f"eq.{username}",
        "order": "waktu.desc",
        "limit": str(limit),
    }
    result = client.query(params)
    if result:
        _cache_put(cache_key, result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  BOOKING — CRUD via Supabase REST (menggantikan Firestore bookings)
# ══════════════════════════════════════════════════════════════════════════════

BOOKINGS_TABLE = "bookings"
CALL_META_TABLE = "call_meta"
CALLS_TABLE = "calls"
QR_SESSIONS_TABLE = "qr_sessions"


class SupabaseCalls:
    """Query + delete from calls table (Supabase)."""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        })

    def query_all(self, **filters) -> list:
        params = {}
        for k, v in filters.items():
            if v is not None:
                params[k] = f"eq.{v}"
        params["order"] = "ts.desc"
        url = f"{SUPABASE_URL}/rest/v1/{CALLS_TABLE}"
        try:
            resp = self._session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                rows = resp.json() or []
                for r in rows:
                    r["_id"] = r.get("id", "")
                return rows
        except Exception as e:
            _LOGGER.warning("SupabaseCalls.query_all error: %s", e)
        return []

    def delete(self, row_id: str) -> bool:
        url = f"{SUPABASE_URL}/rest/v1/{CALLS_TABLE}?id=eq.{row_id}"
        try:
            resp = self._session.delete(url, timeout=10)
            return resp.status_code in (200, 204)
        except Exception as e:
            _LOGGER.warning("SupabaseCalls.delete error: %s", e)
        return False


class SupabaseQrSession:
    """Query + update qr_sessions table (Supabase)."""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        })

    def query_all(self, **filters) -> list:
        params = {}
        for k, v in filters.items():
            if v is not None:
                params[k] = f"eq.{v}"
        params["order"] = "created.desc"
        url = f"{SUPABASE_URL}/rest/v1/{QR_SESSIONS_TABLE}"
        try:
            resp = self._session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                rows = resp.json() or []
                for r in rows:
                    r["_id"] = r.get("id", "")
                return rows
        except Exception as e:
            _LOGGER.warning("SupabaseQrSession.query_all error: %s", e)
        return []

    def get_by_id(self, row_id: str) -> dict:
        params = {"id": f"eq.{row_id}", "limit": "1"}
        url = f"{SUPABASE_URL}/rest/v1/{QR_SESSIONS_TABLE}"
        try:
            resp = self._session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                rows = resp.json()
                if rows:
                    rows[0]["_id"] = rows[0].get("id", "")
                    return rows[0]
        except Exception as e:
            _LOGGER.warning("SupabaseQrSession.get_by_id error: %s", e)
        return {}

    def update(self, row_id: str, data: dict) -> bool:
        url = f"{SUPABASE_URL}/rest/v1/{QR_SESSIONS_TABLE}?id=eq.{row_id}"
        try:
            resp = self._session.patch(url, json=data, timeout=10)
            return resp.status_code in (200, 204)
        except Exception as e:
            _LOGGER.warning("SupabaseQrSession.update error: %s", e)
        return False

    def delete(self, row_id: str) -> bool:
        url = f"{SUPABASE_URL}/rest/v1/{QR_SESSIONS_TABLE}?id=eq.{row_id}"
        try:
            resp = self._session.delete(url, timeout=10)
            return resp.status_code in (200, 204)
        except Exception as e:
            _LOGGER.warning("SupabaseQrSession.delete error: %s", e)
        return False


class SupabaseBooking:
    """Helper untuk operasi booking di Supabase.
    Semua method mengembalikan dict dengan key '_id' (= Supabase 'id')
    agar kompatibel dengan kode existing yang memakai `_id`."""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        })

    @staticmethod
    def _map_id(rows: list) -> list:
        """Map 'id' -> '_id' agar kode existing tetap jalan."""
        for r in rows:
            if "id" in r and "_id" not in r:
                r["_id"] = r["id"]
        return rows

    @staticmethod
    def _map_one(row: dict) -> dict:
        if row and "id" in row and "_id" not in row:
            row["_id"] = row["id"]
        return row

    # ── Query ───────────────────────────────────────────────────────────────
    def query_all(self, owner: str = "", status: str = "", limit: int = 100) -> list:
        """Query bookings, optional filter owner/status."""
        url = f"{SUPABASE_URL}/rest/v1/{BOOKINGS_TABLE}"
        params = {"order": "createdAt.desc", "limit": str(limit)}
        if owner:
            params["owner"] = f"eq.{owner}"
        if status:
            params["status"] = f"eq.{status}"
        try:
            resp = self._session.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                return self._map_id(resp.json())
        except Exception as e:
            _LOGGER.warning("SupabaseBooking.query_all error: %s", e)
        return []

    def get_by_id(self, did: str) -> dict:
        """Ambil 1 booking by ID."""
        url = f"{SUPABASE_URL}/rest/v1/{BOOKINGS_TABLE}"
        params = {"id": f"eq.{did}", "limit": "1"}
        try:
            resp = self._session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                rows = resp.json()
                return self._map_one(rows[0]) if rows else {}
        except Exception as e:
            _LOGGER.warning("SupabaseBooking.get_by_id error: %s", e)
        return {}

    def query_valid_for_card(self, owner: str, perangkat: str) -> list:
        """Query booking 'dikonfirmasi' untuk kartu tertentu, belum sesiDimulai."""
        url = f"{SUPABASE_URL}/rest/v1/{BOOKINGS_TABLE}"
        params = {
            "owner": f"eq.{owner}",
            "status": f"eq.dikonfirmasi",
            "perangkat": f"eq.{perangkat}",
            "sesiDimulai": "eq.false",
            "order": "jam.asc",
            "limit": "50",
        }
        try:
            resp = self._session.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                return self._map_id(resp.json())
        except Exception as e:
            _LOGGER.warning("SupabaseBooking.query_valid_for_card error: %s", e)
        return []

    # ── Write ───────────────────────────────────────────────────────────────
    def update_status(self, did: str, status: str, kasir: str = "",
                      alasan: str = "") -> bool:
        """Update status booking (dikonfirmasi / ditolak)."""
        url = f"{SUPABASE_URL}/rest/v1/{BOOKINGS_TABLE}?id=eq.{did}"
        patch = {
            "status": status,
            "kasir": kasir,
            "alasan": alasan,
            "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            resp = self._session.patch(url, json=patch, timeout=10)
            return resp.status_code in (200, 204)
        except Exception as e:
            _LOGGER.warning("SupabaseBooking.update_status error: %s", e)
            return False

    def mark_sesi_dimulai(self, did: str) -> bool:
        """Tandai booking sudah dimulai sesinya."""
        url = f"{SUPABASE_URL}/rest/v1/{BOOKINGS_TABLE}?id=eq.{did}"
        patch = {
            "sesiDimulai": True,
            "sesiDimulaiAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            resp = self._session.patch(url, json=patch, timeout=10)
            return resp.status_code in (200, 204)
        except Exception as e:
            _LOGGER.warning("SupabaseBooking.mark_sesi_dimulai error: %s", e)
            return False

    def lunas_sisa(self, did: str, total: int, sisa: int, kasir: str = "") -> bool:
        """Tandai sisa DP sebagai LUNAS."""
        url = f"{SUPABASE_URL}/rest/v1/{BOOKINGS_TABLE}?id=eq.{did}"
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        patch = {
            "statusBayar": "lunas_transfer",
            "nominalTransfer": total,
            "pelunasanSisa": sisa,
            "lunasAt": now,
            "updatedAt": now,
            "kasir": kasir,
        }
        try:
            resp = self._session.patch(url, json=patch, timeout=10)
            return resp.status_code in (200, 204)
        except Exception as e:
            _LOGGER.warning("SupabaseBooking.lunas_sisa error: %s", e)
            return False

    def insert(self, data: dict) -> dict:
        """Insert booking baru, return row dengan _id."""
        url = f"{SUPABASE_URL}/rest/v1/{BOOKINGS_TABLE}"
        try:
            resp = self._session.post(url, json=data, timeout=15)
            if resp.status_code in (200, 201):
                rows = resp.json()
                return self._map_one(rows[0]) if rows else {}
        except Exception as e:
            _LOGGER.warning("SupabaseBooking.insert error: %s", e)
        return {}


# ── call_meta helper ──────────────────────────────────────────────────────
class SupabaseCallMeta:
    """Push device status, no_hp, paket_grup ke call_meta Supabase."""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        })

    def upsert(self, owner: str, data: dict) -> bool:
        """Upsert call_meta/{owner}."""
        url = f"{SUPABASE_URL}/rest/v1/{CALL_META_TABLE}"
        row = {"id": owner, "owner": owner}
        row.update(data)
        try:
            resp = self._session.post(url, json=[row], timeout=15)
            return resp.status_code in (200, 201, 204)
        except Exception as e:
            _LOGGER.warning("SupabaseCallMeta.upsert error: %s", e)
            return False

    def get(self, owner: str) -> dict:
        """Ambil call_meta/{owner}."""
        url = f"{SUPABASE_URL}/rest/v1/{CALL_META_TABLE}"
        params = {"id": f"eq.{owner}", "limit": "1"}
        try:
            resp = self._session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                rows = resp.json()
                return rows[0] if rows else {}
        except Exception as e:
            _LOGGER.warning("SupabaseCallMeta.get error: %s", e)
        return {}


# ── Singleton instances ───────────────────────────────────────────────────
_booking_client = None
_callmeta_client = None
_calls_client = None
_qrsession_client = None


def get_booking_client() -> SupabaseBooking:
    global _booking_client
    if _booking_client is None:
        _booking_client = SupabaseBooking()
    return _booking_client


def get_callmeta_client() -> SupabaseCallMeta:
    global _callmeta_client
    if _callmeta_client is None:
        _callmeta_client = SupabaseCallMeta()
    return _callmeta_client


def get_calls_client() -> SupabaseCalls:
    global _calls_client
    if _calls_client is None:
        _calls_client = SupabaseCalls()
    return _calls_client


def get_qrsession_client() -> SupabaseQrSession:
    global _qrsession_client
    if _qrsession_client is None:
        _qrsession_client = SupabaseQrSession()
    return _qrsession_client


# ── Legacy Compatibility ───────────────────────────────────────────────────
def get_supabase_client() -> SupabaseClient:
    return SupabaseClient()
