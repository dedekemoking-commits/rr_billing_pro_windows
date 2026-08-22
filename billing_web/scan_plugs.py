# -*- coding: utf-8 -*-
"""Scan smart plug Tuya di jaringan lokal (jalankan SEKALI, satu jaringan plug).

Cara pakai:
    pip install tinytuya
    python scan_plugs.py

Output berisi Device ID, IP, dan Local Key — salin ke rr_billing_config.json
pada bagian "smart_plugs" (key = label TV, mis. "TV 1").
"""

import tinytuya
import json


def main():
    print(">>> Memindai smart plug Tuya di jaringan (≈ 15 detik)...")
    devices = tinytuya.scan(24)  # tunggu hingga 24 detik
    if not devices:
        print("Tidak ada device Tuya ditemukan.")
        print("Pastikan: plug sudah menyala & terhubung WiFi, PC ini satu jaringan.")
        return
    print("\nDevice ditemukan:")
    print("%-18s | %-16s | %s" % ("ID", "IP", "Local Key"))
    print("-" * 60)
    out = {}
    for d in devices:
        did = d.get("gwId") or d.get("id") or d.get("devId")
        ip = d.get("ip")
        key = d.get("localKey") or d.get("key")
        print("%-18s | %-16s | %s" % (did, ip, key))
        if did:
            out[did] = {"ip": ip, "local_key": key, "version": 3.3}
    print("\n--- Salin ke rr_billing_config.json (sesuaikan label TV) ---")
    print(json.dumps({"smart_plugs": {"TV 1": out[list(out)[0]] if out else {}}},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
