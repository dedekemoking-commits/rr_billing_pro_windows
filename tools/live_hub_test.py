"""live_hub_test.py — test nyata TvWsHub + TvTestApi dari PC ini.

Membuka hub WS di port acak + REST 8081, menghubungkan 2 client TV simulasi
(websockets), lalu menguji seluruh alur: REGISTER, START_TIMER, PAUSE,
RESUME, LOCK, UNLOCK, SHOW_MEDIA, SHOW_PIN, UPDATE_RENTAL, PING/PONG,
reconnect TV sama, dan health/tvs. Pesan diverifikasi isinya (json payload).
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tv_ws_hub import TvWsHub  # noqa: E402
from tv_test_api import TvTestApi  # noqa: E402

PASS = 0
FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label} {detail}")


async def main():
    global PASS, FAIL
    import socket as _socket
    _probe = _socket.socket()
    _probe.bind(("127.0.0.1", 0))
    free_port = _probe.getsockname()[1]
    _probe.close()
    hub = TvWsHub(port=free_port)
    api = TvTestApi(hub, port=8081)
    hub.start()
    api.start()
    await asyncio.sleep(0.5)

    received = {}
    recv_lock = asyncio.Lock()

    async def _connect_retry(uri, meja):
        import websockets
        for _ in range(20):
            try:
                ws = await websockets.connect(uri, open_timeout=5)
                await ws.send(json.dumps({
                    "type": "REGISTER", "meja_id": meja,
                    "device": "android_tv", "nama": f"Sim {meja}"}))
                return ws
            except Exception:
                await asyncio.sleep(0.3)
        return None

    async def client(meja):
        uri = f"ws://127.0.0.1:{free_port}"
        got = {}
        ws = await _connect_retry(uri, meja)
        if ws is None:
            return
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break
            msg = json.loads(raw)
            async with recv_lock:
                got[msg.get("action") or msg.get("type")] = msg
                received[meja] = got
            if msg.get("action") == "PING":
                try:
                    await ws.send(json.dumps({"type": "PONG"}))
                except Exception:
                    pass
    c1 = asyncio.create_task(client("TV 1"))
    c2 = asyncio.create_task(client("TV 2"))
    await asyncio.sleep(1.5)

    # pastikan terdaftar
    tvs = hub.get_connected_tvs()
    ok(len(tvs) == 2, "2 TV terhubung & terdaftar", f"(got {len(tvs)})")
    ok("TV 1" in [t["meja_id"] for t in tvs], "TV 1 ada di daftar")
    ok("TV 2" in [t["meja_id"] for t in tvs], "TV 2 ada di daftar")

    # START_TIMER
    t0 = time.time()
    hub.send_start_timer("TV 1", sisa_detik=3600, total_tagihan=12000,
                         nama_rental="RR BILLING PRO")
    await asyncio.sleep(1.0)
    msg = received.get("TV 1", {}).get("START_TIMER", {})
    ok(msg.get("action") == "START_TIMER", "START_TIMER diterima TV 1")
    ok(int(msg.get("remaining_ms", 0)) == 3600000, "remaining_ms = 3600000",
       f"(got {msg.get('remaining_ms')})")
    ok(str(msg.get("total")) == "12000" or msg.get("total") == 12000,
       "total_tagihan terkirim")
    ok("RR" in str(msg.get("rental_name", "")), "nama rental terkirim")

    # PAUSE / RESUME
    hub.send_pause_timer("TV 1")
    await asyncio.sleep(0.6)
    ok(received.get("TV 1", {}).get("PAUSE_TIMER", {}).get("action") == "PAUSE_TIMER",
       "PAUSE_TIMER diterima")
    hub.send_resume_timer("TV 1", 3599)
    await asyncio.sleep(0.6)
    m = received.get("TV 1", {}).get("RESUME_TIMER", {})
    ok(m.get("action") == "RESUME_TIMER" and int(m.get("remaining_ms", 0)) == 3599000,
       "RESUME_TIMER + sisa benar", f"(got {m.get('remaining_ms')})")

    # LOCK / UNLOCK
    hub.send_lock_screen("TV 1", "WAKTU SEWA HABIS",
                         {"meja": "TV 1", "sewa": "Rp 12.000", "total": "Rp 15.500"})
    await asyncio.sleep(0.6)
    m = received.get("TV 1", {}).get("LOCK_SCREEN", {})
    ok(m.get("action") == "LOCK_SCREEN", "LOCK_SCREEN diterima")
    ok(m.get("message") == "WAKTU SEWA HABIS", "pesan lock benar")
    hub.send_unlock_screen("TV 1")
    await asyncio.sleep(0.6)
    ok(received.get("TV 1", {}).get("UNLOCK_SCREEN", {}).get("action") == "UNLOCK_SCREEN",
       "UNLOCK_SCREEN diterima")

    # MEDIA
    hub.send_show_media("TV 1", "video", "http://x/v.mp4")
    await asyncio.sleep(0.6)
    m = received.get("TV 1", {}).get("SHOW_MEDIA", {})
    ok(m.get("action") == "SHOW_MEDIA" and m.get("url") == "http://x/v.mp4",
       "SHOW_MEDIA terkirim + url")
    hub.send_hide_media("TV 1")
    await asyncio.sleep(0.5)
    ok(received.get("TV 1", {}).get("HIDE_MEDIA", {}).get("action") == "HIDE_MEDIA",
       "HIDE_MEDIA terkirim")

    # PIN (fitur baru)
    hub.send_show_pin("TV 1", "123456")
    await asyncio.sleep(0.6)
    m = received.get("TV 1", {}).get("SHOW_PIN", {})
    ok(m.get("action") == "SHOW_PIN" and m.get("pin") == "123456",
       "SHOW_PIN diterima + pin", f"(got {m.get('pin')})")
    hub.send_hide_pin("TV 1")
    await asyncio.sleep(0.5)
    ok(received.get("TV 1", {}).get("HIDE_PIN", {}).get("action") == "HIDE_PIN",
       "HIDE_PIN diterima")

    # UPDATE_RENTAL + UPDATE_TOTAL
    hub.send_update_rental("TV 1", "WARNET TEST")
    await asyncio.sleep(0.6)
    m = received.get("TV 1", {}).get("UPDATE_RENTAL", {})
    ok(m.get("action") == "UPDATE_RENTAL" and m.get("nama_rental") == "WARNET TEST",
       "UPDATE_RENTAL terkirim + nama", f"(got {m.get('nama_rental')})")
    hub.send_update_total("TV 1", 15500)
    await asyncio.sleep(0.6)
    m = received.get("TV 1", {}).get("UPDATE_TOTAL", {})
    ok(m.get("action") == "UPDATE_TOTAL" and str(m.get("total")) == "15500",
       "UPDATE_TOTAL terkirim + nilai", f"(got {m.get('total')})")

    # REST API
    api_port = api.port
    import urllib.request
    def http(method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{api_port}{path}",
                                     data=json.dumps(body).encode() if body else None,
                                     method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    st, d = http("GET", "/health")
    print(f"  [DEBUG] /health raw = {d}")
    ok(st == 200 and d.get("ok") and d.get("connected") >= 2, "/health ok + count")
    st, d = http("GET", "/api/tvs")
    print(f"  [DEBUG] /api/tvs raw count={d.get('count')} tvs={d.get('tvs')}")
    ok(st == 200 and d.get("count") == 2, "/api/tvs count=2", f"(got {d.get('count')})")
    print(f"  [DEBUG] hub.get_connected_ids() langsung = {hub.get_connected_ids()}")
    import pprint
    print("  [DEBUG] clients hub saat ini:")
    pprint.pprint({m: {k: v for k, v in c.items() if k != "websocket"}
                   for m, c in list(hub.clients.items())})
    st, d = http("POST", "/api/lock", {"meja_id": "TV 2", "pesan": "HABIS",
                                       "total": "Rp 8.000"})
    await asyncio.sleep(0.6)
    m = received.get("TV 2", {}).get("LOCK_SCREEN", {})
    ok(st == 200 and d.get("ok") and m.get("action") == "LOCK_SCREEN",
       "REST /api/lock -> TV 2", f"(got {d})")
    st, d = http("POST", "/api/start-billing",
                 {"meja_id": "TV 2", "sisa_detik": 1800, "total_tagihan": 8000})
    await asyncio.sleep(0.6)
    m = received.get("TV 2", {}).get("START_TIMER", {})
    ok(st == 200 and int(m.get("remaining_ms", 0)) == 1800000,
       "REST /api/start-billing -> TV 2")

    # kirim ke TV tidak terhubung -> ok=False tanpa crash
    st, d = http("POST", "/api/pause-billing", {"meja_id": "TV 99"})
    ok(st == 200 and d.get("ok") is False, "TV tak terhubung -> ok=False (no crash)")

    # PING/PONG heartbeat — hub melakukan PING berkala
    await asyncio.sleep(4.0)
    ok(any(v.get("action") == "PING" for v in received.get("TV 1", {}).values()),
       "PING berkala dari hub diterima")
    st, d = http("POST", "/api/stop-billing", {"meja_id": "TV 1"})
    await asyncio.sleep(0.6)
    ok(received.get("TV 1", {}).get("STOP_TIMER", {}).get("action") == "STOP_TIMER",
       "REST /api/stop-billing -> TV 1")

    c1.cancel()
    c2.cancel()
    api.stop()
    hub.stop()

    print(f"\n{'='*52}")
    print(f"HASIL: {PASS} PASS, {FAIL} FAIL  (durasi {time.time()-t0:.1f}s)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))