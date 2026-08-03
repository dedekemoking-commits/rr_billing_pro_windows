"""tv_ws_test.py — Simulasi client Android TV untuk menguji TvWsHub (kasir).

Menghubungkan ke ws://<kasir-ip>:8080 sebagai sebuah meja, lalu mencetak
semua pesan yang dikirim server (START_TIMER, PAUSE, LOCK_SCREEN, PING, dst).

Cara pakai:
  python tools/tv_ws_test.py --host 192.168.1.100 --port 8080 --meja "TV 1"
  python tools/tv_ws_test.py --host 192.168.1.100 --meja "TV 1" --once
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import websockets

WS_URI = "ws://{host}:{port}"


def _print(msg: dict) -> None:
    action = msg.get("action") or msg.get("type", "?")
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {action:<14} {json.dumps(msg, ensure_ascii=False)}")


async def main() -> None:
    ap = argparse.ArgumentParser(description="Simulasi client TV (overlay + lockscreen)")
    ap.add_argument("--host", default="127.0.0.1", help="IP komputer kasir")
    ap.add_argument("--port", type=int, default=8080, help="Port WebSocket hub")
    ap.add_argument("--meja", default="TV 1", help="meja_id yang diregistrasikan")
    ap.add_argument("--nama", default="Simulasi TV", help="Nama device")
    ap.add_argument("--once", action="store_true",
                    help="Terima pesan satu kali (state awal) lalu keluar")
    args = ap.parse_args()

    uri = WS_URI.format(host=args.host, port=args.port)
    print(f"Menghubungkan ke {uri} sebagai '{args.meja}' ...")
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "type": "REGISTER",
            "meja_id": args.meja,
            "device": "android_tv",
            "nama": args.nama,
        }))
        print("Terhubung. Menunggu pesan dari server (Ctrl+C untuk keluar)...")
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
            except asyncio.TimeoutError:
                print("(tidak ada pesan dalam 30 detik — koneksi masih hidup)")
                continue
            msg = json.loads(raw)
            _print(msg)
            if args.once and (msg.get("type") == "REGISTERED"):
                break
            if msg.get("action") == "PING":
                await ws.send(json.dumps({"type": "PONG"}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nKeluar.")
        sys.exit(0)
