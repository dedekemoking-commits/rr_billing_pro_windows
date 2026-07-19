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
    def __init__(self):
        self._auth = get_firebase_auth()
        self._session = requests.Session()

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
        url = f"{FIRESTORE_BASE}/{path}"
        try:
            resp = self._session.get(url, headers=self._headers(), timeout=15)
            if resp.status_code == 200:
                return _doc_to_dict(resp.json())
            if resp.status_code == 404:
                return None
            _LOGGER.warning("get_document(%s) HTTP %d: %s", path, resp.status_code, resp.text[:200])
            return None
        except requests.RequestException as e:
            _LOGGER.warning("get_document(%s) error: %s", path, e)
            return None

    def set_document(self, path: str, data: dict, merge: bool = True) -> bool:
        url = f"{FIRESTORE_BASE}/{path}"
        doc = _dict_to_doc(data)
        params = {}
        if merge:
            params["updateMask.fieldPaths"] = list(data.keys())
        try:
            resp = self._session.patch(url, params=params, json=doc, headers=self._headers(), timeout=15)
            if resp.status_code in (200, 201):
                return True
            _LOGGER.warning("set_document(%s) HTTP %d: %s", path, resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as e:
            _LOGGER.warning("set_document(%s) error: %s", path, e)
            return False

    def delete_document(self, path: str) -> bool:
        url = f"{FIRESTORE_BASE}/{path}"
        try:
            resp = self._session.delete(url, headers=self._headers(), timeout=15)
            return resp.status_code in (200, 204)
        except requests.RequestException as e:
            _LOGGER.warning("delete_document(%s) error: %s", path, e)
            return False

    # ── Query ─────────────────────────────────────────────────────────────

    def query_where_equal(self, collection: str, field: str, value: str) -> list[dict]:
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
            _LOGGER.warning("query(%s) HTTP %d: %s", collection, resp.status_code, resp.text[:200])
            return []
        except requests.RequestException as e:
            _LOGGER.warning("query(%s) error: %s", collection, e)
            return []

    # ── User Doc Helpers ─────────────────────────────────────────────────

    def get_user_doc(self, username: str) -> Optional[dict]:
        return self.get_document(f"billingps_users/{username}")

    def set_user_doc(self, username: str, data: dict, merge: bool = True) -> bool:
        return self.set_document(f"billingps_users/{username}", data, merge=merge)

    def push_transaction(self, username: str, tx: dict) -> bool:
        doc = self.get_user_doc(username)
        if doc is None:
            tx_list = [tx]
        else:
            tx_list = doc.get("transaksiList", [])
            tx_list.insert(0, tx)
        return self.set_user_doc(username, {"transaksiList": tx_list}, merge=True)

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
        results = self.query_where_equal("licenses", "kode", kode.upper())
        if not results:
            return None
        return results[0]

    def activate_license(self, doc_id: str, expiry: str = "",
                         device_id: str = "", device_type: str = DEVICE_TYPE_DESKTOP) -> bool:
        import time as _time
        now_ms = int(_time.time() * 1000)
        
        # Get existing doc to read current activatedDevices
        doc = self.get_document(f"licenses/{doc_id}")
        
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

    def write_license_status(self, username: str, ls: dict) -> bool:
        data = {
            "licenseStatus": {
                "status": ls.get("status", ""),
                "pesan": ls.get("pesan", ""),
                "expiresAt": ls.get("expiresAt", ""),
                "maxTv": ls.get("maxTv", 0),
                "maxPc": ls.get("maxPc", ls.get("maxTv", 0)),
                "cloud_restored": ls.get("cloud_restored", False),
            }
        }
        return self.set_user_doc(username, data, merge=True)

    def fetch_license_status_by_username(self, username: str) -> Optional[dict]:
        """
        Fetch licenseStatus from billingps_users/<username> doc.
        Jika tidak ditemukan, coba alternative username (dengan/tanpa prefix _user_).
        Returns the licenseStatus dict or None.
        """
        def _check(uname):
            if not uname:
                return None
            doc = self.get_user_doc(uname)
            if doc is None:
                return None
            ls = doc.get("licenseStatus")
            if ls and isinstance(ls, dict) and ls.get("status") == "active":
                return ls
            return None

        # Coba primary username
        result = _check(username)
        if result:
            return result

        # Coba alternative: strip atau tambah prefix _user_
        alt_usernames = []
        if username.startswith("_user_"):
            alt_usernames.append(username[6:])  # hilangin _user_
        else:
            alt_usernames.append(f"_user_{username}")

        # Juga cek field 'username' di doc primary (jika doc-nya ada)
        primary_doc = self.get_user_doc(username)
        if primary_doc and primary_doc.get("username"):
            field_username = primary_doc["username"]
            if field_username not in alt_usernames and field_username != username:
                alt_usernames.append(field_username)

        for alt in alt_usernames:
            result = _check(alt)
            if result:
                _LOGGER.info("fetch_license_status_by_username: found via alt username '%s'", alt)
                return result

        # Fallback: cari by email (untuk antisipasi Android nulis pake email sbg doc ID)
        email_to_try = None
        if primary_doc and primary_doc.get("email"):
            email_to_try = primary_doc["email"]
        else:
            for alt in alt_usernames:
                alt_doc = self.get_user_doc(alt)
                if alt_doc and alt_doc.get("email"):
                    email_to_try = alt_doc["email"]
                    break

        if email_to_try:
            email_results = self.query_where_equal("billingps_users", "email", email_to_try)
            for r in email_results:
                ls = r.get("licenseStatus")
                if ls and isinstance(ls, dict) and ls.get("status") == "active":
                    _LOGGER.info("fetch_license_status_by_username: found via email '%s'", email_to_try)
                    return ls

        return None

    # ── Invoice ────────────────────────────────────────────────────────────

    def query_invoices(self, status: str = None, limit: int = 50) -> list[dict]:
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
                        if status is None or d.get("status") == status:
                            results.append(d)
                return results
            _LOGGER.warning("query_invoices HTTP %d: %s", resp.status_code, resp.text[:200])
            return []
        except requests.RequestException as e:
            _LOGGER.warning("query_invoices error: %s", e)
            return []

    def query_all(self, collection: str, limit: int = 100) -> list[dict]:
        url = f"{FIRESTORE_BASE}:runQuery"
        body = {
            "structuredQuery": {
                "from": [{"collectionId": collection}],
                "limit": limit,
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

    def create_invoice(self, invoice_id: str, data: dict) -> bool:
        return self.set_document(f"invoices/{invoice_id}", data, merge=False)


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
        while not self._stop_event.is_set():
            try:
                ls = self._client.fetch_license_status_by_username(self._username)
                if self._callback:
                    self._callback(ls)
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
