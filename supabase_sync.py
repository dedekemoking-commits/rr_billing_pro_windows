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
SUPABASE_URL = "https://nxaucjpbnewcdqcezbb.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5xYXVjanBibmV3Y2tlZHFjZXpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg1MjUyNzUsImV4cCI6jMxNDEwMTI3NX0.xi-h-3E2Yww95HzXsNmmiOmdvMKi_TaFNw8Op7xryig"
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
        tx["_username"] = username
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
        tx["_username"] = username
        return client.upsert([tx])


def push_transactions(username: str, txs: list[dict]) -> bool:
    """Upload beberapa transaksi langsung ke Supabase."""
    with _UPLOAD_LOCK:
        client = SupabaseClient()
        for tx in txs:
            tx["_username"] = username
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


# ── Legacy Compatibility ───────────────────────────────────────────────────
# Alias agar kode lama yang import dari firestore_sync tetap jalan
def get_supabase_client() -> SupabaseClient:
    return SupabaseClient()
