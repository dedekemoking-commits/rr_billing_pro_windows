import json
import logging
import time
import threading
from typing import Any, Callable, Optional

import requests

from firebase_auth import get_firebase_auth

_LOGGER = logging.getLogger(__name__)

FIRESTORE_BASE = "https://firestore.googleapis.com/v1/projects/rrbillingpro/databases/(default)/documents"

DEVICE_TYPE_DESKTOP = "desktop"
DEVICE_TYPE_ANDROID = "android"
VALID_DEVICE_TYPES = (DEVICE_TYPE_DESKTOP, DEVICE_TYPE_ANDROID)
MAX_ACTIVATIONS_DEFAULT = 2

# Throttle 429 (kuota Firestore) bersifat GLOBAL antar instans FirestoreClient
# agar semua jalur (poller, aktivasi, session, invoice, lisensi) berhenti
# bersama-sama saat kuota habis — bukan hanya per-objek.
_THROTTLED_UNTIL = 0.0
_TX_SAVE_LOCK = threading.Lock()


# ── Firestore Value Converters ────────────────────────────────────────────

def _to_fv(value):
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {k: _to_fv(v) for k, v in value.items()}}}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_to_fv(v) for v in value]}}
    return {"stringValue": str(value)}


def _from_fv(value):
    if "nullValue" in value:
        return None
    if "booleanValue" in value:
        return value["booleanValue"]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return value["doubleValue"]
    if "stringValue" in value:
        return value["stringValue"]
    if "mapValue" in value:
        fields = value["mapValue"].get("fields", {})
        return {k: _from_fv(v) for k, v in fields.items()}
    if "arrayValue" in value:
        arr = value["arrayValue"].get("values", [])
        return [_from_fv(v) for v in arr]
    return value


def _doc_to_dict(doc: dict) -> dict:
    fields = doc.get("fields", {})
    result = {k: _from_fv(v) for k, v in fields.items()}
    result["_id"] = doc.get("name", "").split("/")[-1]
    result["_path"] = doc.get("name", "")
    result["_createTime"] = doc.get("createTime", "")
    result["_updateTime"] = doc.get("updateTime", "")
    return result


def _dict_to_doc(data: dict) -> dict:
    return {"fields": {k: _to_fv(v) for k, v in data.items() if not k.startswith("_")}}


# ── Firestore Client ──────────────────────────────────────────────────────

class FirestoreClient:
    # Jeda setelah HTTP 429 (kuota Firestore habis) — poller berhenti mem-bombardir
    # server, lalu otomatis coba lagi setelah jeda. Prevent spiral rate-limit.
    THROTTLE_429_SECONDS = 60.0

    def __init__(self):
        self._auth = get_firebase_auth()
        self._session = requests.Session()

    def _throttled(self) -> bool:
        global _THROTTLED_UNTIL
        return time.time() < _THROTTLED_UNTIL

    def _note_response(self, status: int, ctx: str) -> None:
        global _THROTTLED_UNTIL
        if status == 429:
            _THROTTLED_UNTIL = time.time() + self.THROTTLE_429_SECONDS
            _LOGGER.warning(
                "%s HTTP 429 (kuota Firestore habis) — jeda request %ds",
                ctx, int(self.THROTTLE_429_SECONDS))

    def _token(self) -> str:
        if not self._auth.get_id_token():
            self._auth.ensure_anonymous()
        return self._auth.get_id_token()

    def _headers(self):
        return {
            "Authorization": f"Bearer {self._token()}",
            "Content-Type": "application/json",
        }

    # ── Document CRUD ─────────────────────────────────────────────────────

    def get_document(self, path: str) -> Optional[dict]:
        if self._throttled():
            return None
        url = f"{FIRESTORE_BASE}/{path}"
        try:
            resp = self._session.get(url, headers=self._headers(), timeout=15)
            if resp.status_code == 200:
                return _doc_to_dict(resp.json())
            if resp.status_code == 404:
                return None
            self._note_response(resp.status_code, f"get_document({path})")
            _LOGGER.warning("get_document(%s) HTTP %d: %s", path, resp.status_code, resp.text[:200])
            return None
        except requests.RequestException as e:
            _LOGGER.warning("get_document(%s) error: %s", path, e)
            return None

    def set_document(self, path: str, data: dict, merge: bool = True) -> bool:
        ok, _ = self._set_document_detailed(path, data, merge)
        return ok

    def _set_document_detailed(self, path: str, data: dict, merge: bool = True) -> tuple[bool, str]:
        if self._throttled():
            return False, "Firestore di-throttle (kuota habis) — coba lagi nanti"
        url = f"{FIRESTORE_BASE}/{path}"
        doc = _dict_to_doc(data)
        params = {}
        if merge:
            params["updateMask.fieldPaths"] = list(data.keys())
        try:
            resp = self._session.patch(url, params=params, json=doc, headers=self._headers(), timeout=30)
            if resp.status_code in (200, 201):
                return True, ""
            self._note_response(resp.status_code, f"set_document({path})")
            err_msg = resp.text[:500] if resp.text else f"HTTP {resp.status_code}"
            _LOGGER.warning("set_document(%s) HTTP %d: %s", path, resp.status_code, err_msg)
            return False, err_msg
        except requests.RequestException as e:
            _LOGGER.warning("set_document(%s) error: %s", path, e)
            return False, str(e)

    def delete_document(self, path: str) -> bool:
        if self._throttled():
            return False
        url = f"{FIRESTORE_BASE}/{path}"
        try:
            resp = self._session.delete(url, headers=self._headers(), timeout=15)
            self._note_response(resp.status_code, f"delete_document({path})")
            return resp.status_code in (200, 204)
        except requests.RequestException as e:
            _LOGGER.warning("delete_document(%s) error: %s", path, e)
            return False

    # ── Query ─────────────────────────────────────────────────────────────

    def query_where_equal(self, collection: str, field: str, value: str) -> list[dict]:
        if self._throttled():
            return []
        url = f"{FIRESTORE_BASE}:runQuery"
        body = {
            "structuredQuery": {
                "from": [{"collectionId": collection}],
                "where": {
                    "fieldFilter": {
                        "field": {"fieldPath": field},
                        "op": "EQUAL",
                        "value": {"stringValue": value},
                    }
                },
                "limit": 20,
            }
        }
        try:
            resp = self._session.post(url, json=body, headers=self._headers(), timeout=15)
            if resp.status_code == 200:
                results = []
                for item in resp.json():
                    if "document" in item:
                        results.append(_doc_to_dict(item["document"]))
                return results
            self._note_response(resp.status_code, f"query({collection})")
            _LOGGER.warning("query(%s) HTTP %d: %s", collection, resp.status_code, resp.text[:200])
            return []
        except requests.RequestException as e:
            _LOGGER.warning("query(%s) error: %s", collection, e)
            return []

    # ── User Doc Helpers ─────────────────────────────────────────────────

    def get_user_doc(self, username: str) -> Optional[dict]:
        # Try direct path first (Android writes to {username} without prefix)
        doc = self.get_document(f"billingps_users/{username}")
        if doc is not None:
            return doc
        # Fallback: try _user_{username} prefix (legacy)
        return self.get_document(f"billingps_users/_user_{username}")

    def set_user_doc(self, username: str, data: dict, merge: bool = True) -> bool:
        # Always write to {username} without _user_ prefix, matching Android behavior
        return self.set_document(f"billingps_users/{username}", data, merge=merge)

    def push_transaction(self, username: str, tx: dict) -> bool:
        return self.push_transactions(username, [tx])

    def push_transactions(self, username: str, txs: list[dict]) -> bool:
        """Merge beberapa transaksi ke billingps_users/{username}.transaksiList.
        Idempoten: transaksi yang id-nya sudah ada di cloud TIDAK ditulis ulang,
        sehingga sinkronisasi desktop & Android tidak saling menimpa.
        """
        if not txs:
            return True
        with _TX_SAVE_LOCK:
            doc = self.get_user_doc(username)
            tx_list = doc.get("transaksiList", []) if doc else []
            if not isinstance(tx_list, list):
                tx_list = []
            existing_ids = {t.get("id") for t in tx_list if isinstance(t, dict) and t.get("id")}
            fresh = [t for t in txs if isinstance(t, dict) and t.get("id") not in existing_ids]
            if not fresh:
                return True
            merged = list(fresh) + list(tx_list)
            return self.set_user_doc(username, {"transaksiList": merged}, merge=True)

    def upsert_transactions(self, username: str, txs: list[dict]) -> bool:
        """Update (replace by id) transaksi yang sudah ada di cloud; tambahkan
        yang belum ada. Dipakai saat detail transaksi berubah di riwayat lokal
        (mis. pesanan makanan/minuman ditambahkan, status bayar berubah).
        """
        if not txs:
            return True
        with _TX_SAVE_LOCK:
            doc = self.get_user_doc(username)
            tx_list = doc.get("transaksiList", []) if doc else []
            if not isinstance(tx_list, list):
                tx_list = []
            by_id = {t.get("id"): t for t in tx_list if isinstance(t, dict) and t.get("id")}
            for t in txs:
                if isinstance(t, dict) and t.get("id"):
                    by_id[t["id"]] = t
            merged = list(by_id.values())
            return self.set_user_doc(username, {"transaksiList": merged}, merge=True)

    def fetch_transactions(self, username: str, max_days: int = 6) -> list[dict]:
        doc = self.get_user_doc(username)
        if doc is None:
            return []
        tx_list = doc.get("transaksiList", [])
        if not isinstance(tx_list, list):
            return []
        if max_days <= 0:
            return tx_list
        cutoff = time.time() - max_days * 86400
        result = []
        for tx in tx_list:
            if not isinstance(tx, dict):
                result.append(tx)
                continue
            tx_time = tx.get("timestamp", tx.get("waktu_epoch", None))
            if tx_time is None:
                # Format Android: "yyyy-MM-dd'T'HH:mm:ss'Z'" (waktu lokal, huruf Z literal)
                waktu = tx.get("waktu", "")
                if len(str(waktu)) >= 19:
                    try:
                        from datetime import datetime
                        dt = datetime.strptime(str(waktu)[:19], "%Y-%m-%dT%H:%M:%S")
                        tx_time = dt.timestamp()
                    except Exception:
                        tx_time = None
            else:
                try:
                    tx_time = float(tx_time)
                except Exception:
                    tx_time = None
            if tx_time is None or tx_time >= cutoff:
                result.append(tx)
        return result

    def sync_tv_list(self, username: str, tv_list: list[dict]) -> bool:
        return self.set_user_doc(username, {"tvList": tv_list}, merge=True)

    def find_username_by_email(self, email: str) -> Optional[str]:
        results = self.query_where_equal("billingps_users", "email", email)
        if results:
            return results[0].get("_id")
        results = self.query_where_equal("billingps_users", "username", email.split("@")[0])
        if results:
            return results[0].get("username") or results[0].get("_id")
        return None

    def get_license_status(self, username: str) -> Optional[dict]:
        doc = self.get_user_doc(username)
        if doc is None:
            return None
        return doc.get("licenseStatus")

    # ── Multi-Device License Helpers ─────────────────────────────────────

    @staticmethod
    def check_license_available(doc: dict, device_type: str) -> tuple[bool, str]:
        """
        Cek apakah license code masih bisa dipakai untuk device_type tertentu.
        
        Returns (ok: bool, message: str)
        """
        # Backward compat: old licenses without activatedDevices
        activated_devices = doc.get("activatedDevices", [])
        if not activated_devices:
            if doc.get("activatedAt", 0) > 0:
                # Already activated once - for backward compat, allow 1 more
                # (so old single-activation codes can be used on 2nd device)
                return True, ""
            return True, ""

        max_act = doc.get("maxActivations", MAX_ACTIVATIONS_DEFAULT)
        
        # Check if this device type is already registered
        for dev in activated_devices:
            if dev.get("deviceType") == device_type:
                return False, f"Kode ini sudah teraktivasi di perangkat {device_type.upper()}."
        
        # Check max activations
        if len(activated_devices) >= max_act:
            return False, f"Kode ini sudah mencapai batas aktivasi ({max_act} perangkat). Hubungi admin."
        
        return True, ""

    # ── License Code Activation ────────────────────────────────────────────

    def find_license_by_code(self, kode: str) -> Optional[dict]:
        results = self.query_where_equal("licenses", "kode", kode)
        if not results:
            return None
        return results[0]

    def activate_license(self, doc_id: str, expiry: str = "",
                         device_id: str = "", device_type: str = DEVICE_TYPE_DESKTOP) -> bool:
        import time as _time
        now_ms = int(_time.time() * 1000)
        
        # Get existing doc to read current activatedDevices
        doc = self.get_document(f"licenses/{doc_id}")

        # Revoked license tidak boleh diaktifkan kembali
        if doc and doc.get("revoked"):
            _LOGGER.warning("activate_license(%s) ditolak — lisensi sudah direvoke", doc_id)
            return False

        updates = {
            "activatedAt": now_ms,
            "activatedDeviceId": device_id,
        }
        
        # Handle activatedDevices array
        existing = (doc or {}).get("activatedDevices", [])
        if not isinstance(existing, list):
            existing = []
        
        # Check if this device type already exists
        device_exists = any(d.get("deviceType") == device_type for d in existing)
        if not device_exists:
            max_act = (doc or {}).get("maxActivations", MAX_ACTIVATIONS_DEFAULT)
            if len(existing) >= int(max_act):
                _LOGGER.warning(
                    "activate_license(%s) ditolak — kuota aktivasi tercapai (%d perangkat)",
                    doc_id, int(max_act))
                return False
            existing.append({
                "deviceType": device_type,
                "deviceId": device_id,
                "activatedAt": now_ms,
            })
        
        updates["activatedDevices"] = existing
        
        if expiry:
            updates["expiry"] = expiry
        
        ok = self.set_document(f"licenses/{doc_id}", updates, merge=True)
        
        # For old docs that already had activatedAt but no activatedDevices,
        # also ensure maxActivations is set
        if doc and "maxActivations" not in doc:
            self.set_document(f"licenses/{doc_id}", {"maxActivations": MAX_ACTIVATIONS_DEFAULT}, merge=True)
        
        return ok

    def revoke_license(self, doc_id: str, reason: str = "") -> bool:
        """Revoke a license in Firestore by setting revoked=True."""
        updates = {
            "revoked": True,
            "revokedAt": int(__import__("time").time() * 1000),
        }
        if reason:
            updates["revokeReason"] = reason
        return self.set_document(f"licenses/{doc_id}", updates, merge=True)

    def write_license_status(self, username: str, ls: dict) -> bool:
        # Hanya pertahankan promo lama dari cloud bila key TIDAK disediakan
        # (None); promoAddTv=0 artinya promo sengaja dimatikan.
        promo = ls.get("promoAddTv", None)
        if promo is None:
            existing = self.get_user_doc(username)
            if existing:
                promo = existing.get("licenseStatus", {}).get("promoAddTv", 0)
            else:
                promo = 0
        data = {
            "licenseStatus": {
                "status": ls.get("status", ""),
                "pesan": ls.get("pesan", ""),
                "expiresAt": ls.get("expiresAt", ""),
                "maxTv": ls.get("maxTv", 0),
                "maxPc": ls.get("maxPc", ls.get("maxTv", 0)),
                "promoAddTv": promo,
                "cloud_restored": ls.get("cloud_restored", False),
            }
        }
        return self.set_user_doc(username, data, merge=True)

    def fetch_license_status_by_username(self, username: str) -> Optional[dict]:
        """
        Fetch licenseStatus dari billingps_users/<username> doc.
        Dioptimasi: get_user_doc dipanggil maksimal 2x (bukan 8x) per
        pemanggilan — hemat kuota read Firestore (1 read per GET).
        """
        def _check(uname):
            if not uname:
                return None, None
            doc = self.get_user_doc(uname)
            if doc is None:
                return None, None
            ls = doc.get("licenseStatus")
            if ls and isinstance(ls, dict) and ls.get("status") == "active":
                return ls, doc
            return None, doc

        candidates = [username]
        if username.startswith("_user_"):
            candidates.append(username[6:])
        else:
            candidates.append(f"_user_{username}")

        primary_doc = None
        for c in candidates:
            ls, doc = _check(c)
            if ls:
                return ls
            if doc is not None and primary_doc is None:
                primary_doc = doc

        if primary_doc:
            field_username = primary_doc.get("username")
            if field_username and field_username not in candidates:
                ls, _ = _check(field_username)
                if ls:
                    _LOGGER.info("fetch_license_status_by_username: found via field username '%s'", field_username)
                    return ls
            email_to_try = primary_doc.get("email")
        else:
            email_to_try = username if "@" in username else None

        if email_to_try:
            email_results = self.query_where_equal("billingps_users", "email", email_to_try)
            for r in email_results:
                ls = r.get("licenseStatus")
                if ls and isinstance(ls, dict) and ls.get("status") == "active":
                    _LOGGER.info("fetch_license_status_by_username: found via email '%s'", email_to_try)
                    return ls
                # licenseStatus might be in the non-_user_ doc (Android writes to {username} directly)
                doc_id = r.get("_id", "")
                if doc_id.startswith("_user_"):
                    bare_user = doc_id[6:]
                    ls, _ = _check(bare_user)
                    if ls:
                        _LOGGER.info("fetch_license_status_by_username: found via email -> bare user '%s'", bare_user)
                        return ls

        return None

    # ── Invoice ────────────────────────────────────────────────────────────

    def query_invoices(self, status: str = None, limit: int = 50, username: str = "") -> list[dict]:
        if self._throttled():
            return []
        # Prioritas: map invoices di dalam doc user (billingps_users/{user}.invoices)
        if username:
            doc = self.get_user_doc(username)
            inv_map = (doc or {}).get("invoices", {})
            if isinstance(inv_map, dict) and inv_map:
                results = [d for d in inv_map.values() if isinstance(d, dict)]
                results.sort(key=lambda d: d.get("dibuat", 0) if isinstance(d.get("dibuat"), (int, float)) else 0,
                             reverse=True)
                if status:
                    results = [d for d in results if d.get("status") == status]
                return results[:limit]
        url = f"{FIRESTORE_BASE}:runQuery"
        body = {
            "structuredQuery": {
                "from": [{"collectionId": "invoices"}],
                "orderBy": [{"field": {"fieldPath": "dibuat"}, "direction": "DESCENDING"}],
                "limit": limit,
            }
        }
        try:
            resp = self._session.post(url, json=body, headers=self._headers(), timeout=15)
            if resp.status_code == 200:
                results = []
                for item in resp.json():
                    if "document" in item:
                        d = _doc_to_dict(item["document"])
                        if username and d.get("username") not in (None, "", username):
                            continue
                        if status is None or d.get("status") == status:
                            results.append(d)
                return results
            self._note_response(resp.status_code, "query_invoices")
            _LOGGER.warning("query_invoices HTTP %d: %s", resp.status_code, resp.text[:200])
            return []
        except requests.RequestException as e:
            _LOGGER.warning("query_invoices error: %s", e)
            return []

    def query_all(self, collection: str, limit: int = 100, order_field: str = "") -> list[dict]:
        if self._throttled():
            return []
        url = f"{FIRESTORE_BASE}:runQuery"
        query = {"from": [{"collectionId": collection}]}
        if order_field:
            # Dokumen TERBARU duluan — penting untuk poller QR: sesi/panggilan
            # baru selalu masuk window walau koleksi sudah menumpuk dokumen lama.
            query["orderBy"] = [{"field": {"fieldPath": order_field},
                                 "direction": "DESCENDING"}]
        query["limit"] = limit
        body = {"structuredQuery": query}
        try:
            resp = self._session.post(url, json=body, headers=self._headers(), timeout=15)
            if resp.status_code == 200:
                results = []
                for item in resp.json():
                    if "document" in item:
                        results.append(_doc_to_dict(item["document"]))
                return results
            self._note_response(resp.status_code, f"query_all({collection})")
            _LOGGER.warning("query_all(%s) HTTP %d: %s", collection, resp.status_code, resp.text[:200])
            return []
        except requests.RequestException as e:
            _LOGGER.warning("query_all(%s) error: %s", collection, e)
            return []

    def save_license_to_firestore(self, license_data: dict) -> Optional[str]:
        import time as _time
        doc_id = f"LIC_{int(_time.time() * 1000)}"
        ok = self.set_document(f"licenses/{doc_id}", license_data, merge=False)
        return doc_id if ok else None

    def update_invoice(self, invoice_id: str, updates: dict) -> bool:
        return self.set_document(f"invoices/{invoice_id}", updates, merge=True)

    def create_invoice(self, invoice_id: str, data: dict, username: str = "") -> tuple[bool, str]:
        # Save image locally, only upload metadata to cloud
        bukti_b64 = data.pop("buktiBase64", "")
        bukti_local = data.pop("bukti_local", "")
        # Upload lightweight metadata only (no base64 image) to avoid 1MB doc limit
        user = username or data.get("username", "")
        if user:
            ok, err = self._set_document_detailed(
                f"invoices/{invoice_id}", data, merge=False)
            if ok:
                return True, ""
            # Fallback: store in user doc as nested map
            doc = self.get_document(f"billingps_users/{user}")
            if doc is None:
                doc = {}
            invoices = doc.get("invoices", {})
            data["has_bukti"] = bool(bukti_b64 or bukti_local)
            invoices[invoice_id] = data
            return self._set_document_detailed(
                f"billingps_users/{user}", {"invoices": invoices}, merge=True)
        return False, "Tidak ada username"

    def fetch_promo_settings(self) -> Optional[dict]:
        doc = self.get_document("settings/global")
        if doc is None:
            return None
        return {
            "promoAktif": doc.get("promoAktif", False),
            "diskonPerPaket": doc.get("diskonPerPaket", {}),
            "addTvOverride": doc.get("addTvOverride", {}),
            "updatedBy": doc.get("updatedBy", ""),
            "updatedAt": doc.get("updatedAt", 0),
        }


# ── License Poller ────────────────────────────────────────────────────────

class LicensePoller:
    def __init__(self, username: str, interval: float = 30.0):
        self._username = username
        self._interval = interval
        self._callback: Optional[Callable[[Optional[dict]], None]] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._client = FirestoreClient()

    def start(self, callback: Callable[[Optional[dict]], None]):
        self._callback = callback
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):
        last_fetch = 0.0
        cached_ls = None
        while not self._stop_event.is_set():
            try:
                if time.time() - last_fetch >= self._interval:
                    ls = self._client.fetch_license_status_by_username(self._username)
                    last_fetch = time.time()
                    cached_ls = ls
                    if self._callback:
                        self._callback(ls)
                elif self._callback:
                    self._callback(cached_ls)
            except Exception as e:
                _LOGGER.warning("LicensePoller error: %s", e)
            self._stop_event.wait(self._interval)

    def poll_now(self):
        try:
            ls = self._client.fetch_license_status_by_username(self._username)
            if self._callback:
                self._callback(ls)
        except Exception as e:
            _LOGGER.warning("LicensePoller.poll_now error: %s", e)


class CallPoller:
    """Polling panggilan QR dari halaman web pelanggan (collection 'calls').

    Meniru pola LicensePoller: thread + interval. Setiap dokumen baru diteruskan
    ke callback (dict hasil _doc_to_dict + '_id'). Validasi kode TV & rate-limit
    dilakukan di sisi kasir (main.py)."""

    def __init__(self, collection: str = "calls", interval: float = 3.0, limit: int = 20,
                 order_field: str = ""):
        self._collection = collection
        self._interval = float(interval)
        self._limit = max(5, int(limit))
        self._order_field = order_field or ""
        self._callback = None
        self._stop_event = threading.Event()
        self._thread = None
        self._client = FirestoreClient()

    def start(self, callback):
        self._callback = callback
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):
        while not self._stop_event.is_set():
            try:
                docs = self._client.query_all(self._collection, limit=self._limit,
                                              order_field=self._order_field)
                if docs and self._callback:
                    docs.sort(key=lambda d: str(d.get("_createTime", "")))
                    for d in docs:
                        try:
                            self._callback(d)
                        except Exception:
                            pass
            except Exception as e:
                _LOGGER.warning("CallPoller error: %s", e)
            self._stop_event.wait(self._interval)

    def poll_now(self):
        try:
            docs = self._client.query_all(self._collection, limit=self._limit,
                                          order_field=self._order_field)
            if docs and self._callback:
                docs.sort(key=lambda d: str(d.get("_createTime", "")))
                for d in docs:
                    try:
                        self._callback(d)
                    except Exception:
                        pass
        except Exception as e:
            _LOGGER.warning("CallPoller.poll_now error: %s", e)


# ── Singleton ─────────────────────────────────────────────────────────────

_client_instance: Optional[FirestoreClient] = None
_client_lock = threading.Lock()


def get_firestore_client() -> FirestoreClient:
    global _client_instance
    if _client_instance is None:
        with _client_lock:
            if _client_instance is None:
                _client_instance = FirestoreClient()
    return _client_instance
