# -*- coding: utf-8 -*-
"""Smart WiFi Plug untuk lampu LED per TV.

Mendukung dua jenis plug:
  - "tuya"   : Tuya / Bardi / Yanzi (butuh Local Key, kontrol via LAN pakai tinytuya)
  - "shelly" : Shelly (HTTP REST lokal, TIDAK butuh key — cukup IP, paling simpel & stabil)

Config per-TV (rr_billing_config.json -> daftar_tv[].plug):
  Tuya:   {"type":"tuya","device_id":"...","ip":"192.168.1.x",
            "local_key":"...","version":3.3}
  Shelly: {"type":"shelly","ip":"192.168.1.x",
            "auth":{"user":"","pass":""}}   # auth opsional (jika Shelly diproteksi)
"""

import threading
import logging

try:
    import requests
    _HAVE_REQ = True
except Exception:
    _HAVE_REQ = False

try:
    import tinytuya
    _HAVE_TUYA = True
except Exception:
    _HAVE_TUYA = False
    tinytuya = None

_LOGGER = logging.getLogger("rrbilling.plug")


class SmartPlugManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._devs = {}      # cache device Tuya (key = device_id)
        self._state = {}     # cache status terakhir (key = ip / device_id)

    # ── TUYA ───────────────────────────────────────────────────
    def _tuya_dev(self, cfg):
        dev_id = cfg.get("device_id") or cfg.get("id")
        ip = cfg.get("ip")
        key = cfg.get("local_key") or cfg.get("key")
        if not (dev_id and ip and key):
            return None
        with self._lock:
            if dev_id in self._devs:
                return self._devs[dev_id]
            if not _HAVE_TUYA:
                return None
            try:
                ver = float(cfg.get("version", 3.3) or 3.3)
                d = tinytuya.OutletDevice(dev_id, ip, key)
                d.set_version(ver)
                self._devs[dev_id] = d
                return d
            except Exception as e:
                _LOGGER.warning("Plug init gagal %s: %s", dev_id, e)
                return None

    # ── SHELLY ────────────────────────────────────────────────
    def _shelly_req(self, cfg, path, method="GET", data=None):
        ip = cfg.get("ip")
        if not ip:
            return None
        url = "http://%s/%s" % (ip, path.lstrip("/"))
        auth = None
        a = cfg.get("auth") or {}
        if a.get("user") or a.get("pass"):
            auth = (a.get("user", ""), a.get("pass", ""))
        try:
            if method == "POST":
                r = requests.post(url, json=data, auth=auth, timeout=5)
            else:
                r = requests.get(url, auth=auth, timeout=5)
            if r.status_code == 200:
                try:
                    return r.json()
                except Exception:
                    return {"raw": r.text}
            _LOGGER.warning("Shelly %s -> HTTP %s", url, r.status_code)
            return None
        except Exception as e:
            _LOGGER.warning("Shelly request gagal %s: %s", url, e)
            return None

    def _shelly_state(self, cfg):
        # Coba Gen2 (rpc) dulu, lalu Gen1 (/relay/0)
        j = self._shelly_req(cfg, "/rpc/Switch.Get?id=0")
        if isinstance(j, dict) and ("on" in j or "was_on" in j):
            return bool(j.get("on", j.get("was_on", False)))
        j = self._shelly_req(cfg, "/relay/0")
        if isinstance(j, dict) and "ison" in j:
            return bool(j.get("ison"))
        return None

    def _shelly_set(self, cfg, on):
        # Gen2
        j = self._shelly_req(cfg, "/rpc/Switch.Set", method="POST",
                             data={"id": 0, "on": bool(on)})
        if isinstance(j, dict) and ("was_on" in j or "on" in j):
            return True
        # Gen1
        j = self._shelly_req(cfg, "/relay/0?turn=" + ("on" if on else "off"))
        if isinstance(j, dict) and "ison" in j:
            return True
        return False

    # ── DISPATCH ──────────────────────────────────────────────
    def set_state(self, cfg, on):
        ptype = (cfg.get("type") or "tuya").lower()
        if ptype == "shelly":
            if not _HAVE_REQ:
                return False, "modul requests belum tersedia"
            try:
                ok = self._shelly_set(cfg, on)
            except Exception as e:
                return False, str(e)[:160]
            if ok:
                self._state[cfg.get("ip")] = bool(on)
                return True, "ok"
            return False, "gagal kontrol Shelly (cek IP/Auth/Model)"
        # default: tuya
        d = self._tuya_dev(cfg)
        if not d:
            return False, "plug tidak tersedia (cek device_id/ip/local_key/version)"
        try:
            if on:
                d.turn_on()
            else:
                d.turn_off()
            dev_id = cfg.get("device_id") or cfg.get("id")
            self._state[dev_id] = bool(on)
            return True, "ok"
        except Exception as e:
            return False, str(e)[:160]

    def get_state(self, cfg):
        ptype = (cfg.get("type") or "tuya").lower()
        if ptype == "shelly":
            if not _HAVE_REQ:
                return None
            try:
                return self._shelly_state(cfg)
            except Exception as e:
                _LOGGER.warning("Shelly status gagal: %s", e)
                return None
        d = self._tuya_dev(cfg)
        if not d:
            return None
        try:
            data = d.status()
            return bool((data.get("dps") or {}).get("1", False))
        except Exception as e:
            _LOGGER.warning("Plug status gagal: %s", e)
            return None


_MANAGER = None


def get_manager():
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = SmartPlugManager()
    return _MANAGER
