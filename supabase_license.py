"""Supabase helpers untuk alur lisensi (invoice, notifikasi, license_status).

Digunakan desktop sebagai pengganti untuk koleksi Firestore:
invoices, notifications, licenses, settings/global, licenseStatus.
"""
import time
import threading
import requests
from typing import Optional

from supabase_sync import SUPABASE_URL, SUPABASE_KEY, _LOGGER

_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}


def _req(method: str, path: str, json_body=None, params=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    try:
        if method == "GET":
            resp = requests.get(url, headers=_HEADERS, params=params, timeout=15)
        elif method == "POST":
            resp = requests.post(url, headers=_HEADERS, json=json_body, params=params, timeout=15)
        elif method == "PATCH":
            resp = requests.patch(url, headers=_HEADERS, json=json_body, params=params, timeout=15)
        elif method == "DELETE":
            resp = requests.delete(url, headers=_HEADERS, params=params, timeout=15)
        else:
            return False, "METHOD?"
        if resp.status_code in (200, 201, 204):
            try:
                return True, resp.json() if resp.text else []
            except ValueError:
                return True, []
        _LOGGER.warning("Supabase %s %s HTTP %s: %s", method, path, resp.status_code, resp.text[:200])
        return False, resp.text[:200]
    except Exception as e:
        _LOGGER.warning("Supabase %s %s error: %s", method, path, e)
        return False, str(e)


def create_invoice(invoice_id: str, data: dict) -> tuple[bool, str]:
    row = dict(data)
    row["id"] = invoice_id
    ok, err = _req("POST", "invoices", json_body=row)
    if ok:
        return True, ""
    # Fallback: tabel dipisah per user belum ada -> simpan di user doc (seperti Firestore)
    return False, err


def create_notification(data: dict) -> bool:
    ok, _ = _req("POST", "notifications", json_body=data)
    return ok


def update_invoice(invoice_id: str, updates: dict) -> bool:
    ok, _ = _req("PATCH", f"invoices?id=eq.{invoice_id}", json_body=updates)
    return ok


def get_invoices_confirmed(username: str) -> list[dict]:
    ok, data = _req("GET", "invoices", params={
        "username": f"eq.{username}",
        "status": "eq.CONFIRMED",
        "order": "dibuat.desc",
        "limit": "10",
    })
    if ok and isinstance(data, list):
        return data
    return []


def upsert_license_status(username: str, data: dict) -> bool:
    row = {"id": username}
    row.update(data)
    headers = dict(_HEADERS)
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/license_status",
            headers=headers, json=row, timeout=15,
        )
        if resp.status_code in (200, 201, 204):
            return True
        _LOGGER.warning("upsert license_status HTTP %s: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        _LOGGER.warning("upsert license_status error: %s", e)
        return False


def get_license_status(username: str) -> Optional[dict]:
    ok, data = _req("GET", "license_status", params={
        "id": f"eq.{username}",
        "limit": "1",
    })
    if ok and isinstance(data, list) and data:
        row = data[0]
        return {
            "status": row.get("status", ""),
            "expiresAt": row.get("expiresAt", ""),
            "maxTv": row.get("maxTv", 0),
            "pesan": row.get("pesan", ""),
            "maxPc": row.get("maxTv", 0),
            "updatedAt": row.get("updatedAt", 0),
        }
    return None


def get_promo() -> Optional[dict]:
    ok, data = _req("GET", "promo", params={"id": "eq.global", "limit": "1"})
    if ok and isinstance(data, list) and data:
        row = data[0]
        return {
            "promoAktif": row.get("promoAktif", False),
            "diskonPerPaket": row.get("diskonPerPaket", {}) or {},
            "addTvOverride": row.get("addTvOverride", {}) or {},
            "updatedBy": row.get("updatedBy", ""),
            "updatedAt": row.get("updatedAt", 0),
            "newUserPromoActive": row.get("newUserPromoActive", False),
            "newUserDiscountPercent": row.get("newUserDiscountPercent", 30),
            "newUserPromoDurationHours": row.get("newUserPromoDurationHours", 96),
            "newUserDiskonPerPaket": row.get("newUserDiskonPerPaket", {}) or {},
            "promoStartedAt": row.get("promoStartedAt", 0),
            "promoDurationHours": row.get("promoDurationHours", 0),
        }
    return None


def upsert_promo(data: dict) -> bool:
    row = {"id": "global"}
    row.update(data)
    headers = dict(_HEADERS)
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/promo", headers=headers, json=row, timeout=15,
        )
        return resp.status_code in (200, 201, 204)
    except Exception as e:
        _LOGGER.warning("upsert promo error: %s", e)
        return False


def create_license(data: dict) -> bool:
    ok, _ = _req("POST", "licenses", json_body=data)
    return ok


def activate_license_row(license_id: str, expiry: str = "") -> bool:
    if not license_id:
        return False
    updates = {
        "activatedAt": int(time.time() * 1000),
        "activated_on": expiry,
    }
    ok, _ = _req("PATCH", f"licenses?id=eq.{license_id}", json_body=updates)
    return ok


def revoke_license(license_id: str, reason: str = "") -> bool:
    ok, _ = _req("PATCH", f"licenses?id=eq.{license_id}", json_body={
        "revoked": True, "revoke_reason": reason, "revokedAt": int(time.time() * 1000),
    })
    return ok


def get_licenses_by_user(generated_by: str) -> list[dict]:
    ok, data = _req("GET", "licenses", params={
        "generatedBy": f"eq.{generated_by}",
        "order": "generatedAt.desc",
        "limit": "50",
    })
    if ok and isinstance(data, list):
        return data
    return []


# ── License status poller ──────────────────────────────────────────────────

_LICENSE_POLL_INTERVAL = 60.0


def start_license_poller(username: str, on_change) -> threading.Thread:
    """Poll license_status per interval, panggil on_change(ls:dict) jika berubah."""

    stop_ev = threading.Event()
    state = {"last_json": ""}

    def _loop():
        import json as _json
        while not stop_ev.wait(_LICENSE_POLL_INTERVAL):
            try:
                ls = get_license_status(username)
                if ls is not None:
                    s = _json.dumps(ls, sort_keys=True)
                    if s != state["last_json"]:
                        state["last_json"] = s
                        try:
                            on_change(ls)
                        except Exception:
                            _LOGGER.warning("license poller callback error", exc_info=True)
            except Exception:
                _LOGGER.warning("license poller error", exc_info=True)

    t = threading.Thread(target=_loop, daemon=True, name="LicensePoller")
    t.start()
    t.stop_ev = stop_ev  # type: ignore[attr-defined]
    return t
