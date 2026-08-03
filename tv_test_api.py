"""TvTestApi — REST API sederhana (tanpa dependency) untuk menguji kirim sinyal ke TV.

Server HTTP mini di port 8081 (ThreadingHTTPServer bawaan Python).

Endpoint:
  POST /api/start-billing   {"meja_id","sisa_detik","total_tagihan","nama_rental"}
  POST /api/stop-billing    {"meja_id"}
  POST /api/pause-billing   {"meja_id"}
  POST /api/resume-billing  {"meja_id","sisa_detik"}
  POST /api/lock            {"meja_id","pesan","detail_transaksi":{...}}
  POST /api/unlock          {"meja_id"}
  GET  /api/tvs             daftar TV yang terhubung
  GET  /health              status hub

Contoh:
  curl -X POST http://127.0.0.1:8081/api/start-billing -H "Content-Type: application/json" -d "{\"meja_id\":\"TV 1\",\"sisa_detik\":3600,\"total_tagihan\":6000}"
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import urlparse


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    try:
        length = int(handler.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = handler.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class _Handler(BaseHTTPRequestHandler):
    server_version = "TvTestApi/1.0"

    def log_message(self, fmt: str, *args) -> None:  # ramah di konsol kasir
        return

    # ── Helpers ───────────────────────────────────────────────────────────────
    @property
    def hub(self) -> Any:
        return self.server.hub  # type: ignore[attr-defined]

    def _respond(self, status: int, ok: bool, message: str, **extra) -> None:
        _send_json(self, status, {"ok": ok, "message": message, **extra})

    def _meja(self) -> tuple[str, dict]:
        data = _read_json(self)
        meja_id = str(data.get("meja_id", "")).strip()
        return meja_id, data

    # ── Routes ────────────────────────────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802 (nama method bawaan http.server)
        path = urlparse(self.path).path
        if path == "/api/tvs":
            tvs = self.hub.get_connected_tvs()
            _send_json(self, 200, {"ok": True, "tvs": tvs,
                                   "count": len(tvs),
                                   "locked": self.hub.locked_summary()})
        elif path == "/health":
            _send_json(self, 200, {
                "ok": True,
                "running": self.hub.running,
                "connected": self.hub.count_connected(),
                "port": self.hub.port,
            })
        else:
            self._respond(404, False, f"Not found: {path}")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        meja_id, data = self._meja()
        if not meja_id:
            self._respond(400, False, "meja_id wajib diisi")
            return

        if path == "/api/start-billing":
            sisa = int(data.get("sisa_detik", 3600))
            ok = self.hub.send_start_timer(
                meja_id,
                sisa_detik=sisa,
                total_tagihan=data.get("total_tagihan", 0),
                nama_rental=data.get("nama_rental"),
            )
            self._respond(200, ok, "START_TIMER terkirim" if ok else "TV tidak terhubung",
                          action="START_TIMER", meja_id=meja_id, sisa_detik=sisa)

        elif path == "/api/stop-billing":
            ok = self.hub.send_stop_timer(meja_id)
            self._respond(200, ok, "STOP_TIMER terkirim" if ok else "TV tidak terhubung",
                          action="STOP_TIMER", meja_id=meja_id)

        elif path == "/api/pause-billing":
            ok = self.hub.send_pause_timer(meja_id)
            self._respond(200, ok, "PAUSE_TIMER terkirim" if ok else "TV tidak terhubung",
                          action="PAUSE_TIMER", meja_id=meja_id)

        elif path == "/api/resume-billing":
            sisa = int(data.get("sisa_detik", 3600))
            ok = self.hub.send_resume_timer(meja_id, sisa)
            self._respond(200, ok, "RESUME_TIMER terkirim" if ok else "TV tidak terhubung",
                          action="RESUME_TIMER", meja_id=meja_id, sisa_detik=sisa)

        elif path == "/api/lock":
            detail = data.get("detail_transaksi") or {}
            if not isinstance(detail, dict):
                detail = {}
            detail.setdefault("meja", data.get("meja") or meja_id)
            detail.setdefault("sewa", data.get("sewa", "-"))
            detail.setdefault("fnb", data.get("fnb", "Rp 0"))
            detail.setdefault("total", data.get("total", "Rp 0"))
            ok = self.hub.send_lock_screen(meja_id, data.get("pesan", "WAKTU SEWA HABIS"),
                                           detail)
            self._respond(200, ok, "LOCK_SCREEN terkirim" if ok else "TV tidak terhubung",
                          action="LOCK_SCREEN", meja_id=meja_id)

        elif path == "/api/unlock":
            ok = self.hub.send_unlock_screen(meja_id)
            self._respond(200, ok, "UNLOCK_SCREEN terkirim" if ok else "TV tidak terhubung",
                          action="UNLOCK_SCREEN", meja_id=meja_id)

        else:
            self._respond(404, False, f"Not found: {path}")


class TvTestApi:
    """REST test server yang membungkus TvWsHub (port default 8081)."""

    def __init__(self, hub, port: int = 8081, host: str = "0.0.0.0"):
        self.hub = hub
        self.port = int(port)
        self.host = host
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        self._httpd.hub = self.hub  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True, name="tv-test-api")
        self._thread.start()
        print(f"[TV TEST API] REST API on http://{self.host}:{self.port}")

    def stop(self) -> None:
        self.running = False
        if self._httpd:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            self._httpd = None
