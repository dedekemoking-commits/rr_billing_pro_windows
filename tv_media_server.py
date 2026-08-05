"""TvMediaServer — HTTP server mini untuk mengirim video/gambar promosi ke client TV.

Menjalankan ThreadingHTTPServer (bawaan Python, tanpa dependency) di port default 8082
dan menyajikan file dari folder media (media_promo/).

Endpoint:
  GET /media/<filename>   unduh media (video/gambar)
  HEAD /media/<filename>  header saja (wajib untuk MediaPlayer Android <11)
  GET /health             status server + media aktif

Desain kompatibilitas (agar video promo jalan di SEMUA TV Android — semua merk,
Android 4.x-14, STB Amlogic/Rockchip/Allwinner/HiSilicon dst.):

- HTTP/1.1 keep-alive + Content-Length selalu dikirim (tidak pernah chunked) —
  MediaPlayer lama butuh ukuran eksplisit.
- HEAD dijawab dengan header IDENTIK dengan GET (200/206) — Android <11 memakai
  HEAD untuk cek ukuran/tipe sebelum GET; tanpa ini ia berhenti (dulu 501).
- Dukungan HTTP Range / 206 Partial Content — MediaPlayer/VideoView melakukan
  seek dengan Range; tanpa 206 video gagal diputar di Android <11.
- Menghormati "Connection: close" — beberapa stack lama menunggu koneksi ditutup.
- Nama file di-unquote (mendukung spasi/karakter non-ASCII di nama file).
- Content-Type di-sniff dari magic bytes (bukan hanya ekstensi file).
- daemon_threads + socket timeout — koneksi setengah mati dari box murah tidak
  menumpuk thread / memblokir shutdown.

URL dipakai client Android TV via perintah WS SHOW_MEDIA:
  http://<ip-kasir>:8082/media/<filename>
"""
from __future__ import annotations

import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

VIDEO_EXTS = {".mp4", ".webm", ".3gp", ".ts"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
MEDIA_EXTS = VIDEO_EXTS | IMAGE_EXTS

mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("video/3gpp", ".3gp")
mimetypes.add_type("video/mp2t", ".ts")


def klasifikasi_media(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in IMAGE_EXTS:
        return "image"
    return ""


def sniff_content_type(path: str, fallback: Optional[str]) -> str:
    """Deteksi Content-Type dari magic bytes file (lebih andal dari ekstensi)."""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
        if len(head) >= 8 and head[4:8] == b"ftyp":
            return "video/mp4"
        if head[:4] == b"\x1aE\xdf\xa3":
            return "video/webm"
        if head[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
        if head[:2] == b"BM":
            return "image/bmp"
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return "image/webp"
        if head[:4] == b"OggS":
            return "video/ogg"
    except Exception:
        pass
    return fallback or "application/octet-stream"


class _Handler(BaseHTTPRequestHandler):
    server_version = "TvMediaServer/1.0"
    # HTTP/1.1 → keep-alive aktif. MediaPlayer Android <11 membuka banyak
    # request berturut-turut (HEAD/GET + Range); koneksi berkelanjutan
    # menghindari koneksi baru per chunk.
    protocol_version = "HTTP/1.1"
    # Koneksi setengah mati dari box lama tidak menahan thread selamanya.
    timeout = 60

    def log_message(self, fmt: str, *args) -> None:
        if getattr(self.server, "debug_log", False):
            super().log_message(fmt, *args)

    def log_access(self, detail: str) -> None:
        """Access log: selalu dicatat — ke console (jika ada) DAN ke file
        media_promo/access.log (EXE di-build tanpa console, jadi file ini
        adalah satu-satunya tempat log terlihat di kasir).

        Berguna untuk diagnosa: apakah client TV benar-benar mengunduh file,
        dan berapa besar Range yang diminta (mis. macet di tengah-tengah).
        """
        try:
            line = "%s [TV MEDIA] %s %s %s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"),
                self.command or "?",
                self.client_address[0] if self.client_address else "?",
                detail,
            )
            print(line.rstrip("\n"), flush=True)
            media = getattr(self.server, "media", None)
            if media is not None:
                with media._access_lock:
                    try:
                        with open(os.path.join(media.media_dir, "access.log"),
                                  "a", encoding="utf-8") as f:
                            f.write(line)
                    except OSError:
                        pass
        except Exception:
            pass

    @property
    def media(self) -> Any:
        return self.server.media  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        self._serve(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802
        # Wajib: MediaPlayer Android <11 mengirim HEAD untuk cek ukuran/tipe
        # file sebelum GET. Tanpa ini server menjawab 501 → video gagal diputar.
        self._serve(head_only=True)

    def _serve(self, head_only: bool) -> None:
        from urllib.parse import unquote, urlparse

        # Hormati "Connection: close" dari client (beberapa player lama
        # menunggu koneksi ditutup untuk menyelesaikan transfer).
        if self.headers.get("Connection", "").lower().find("close") >= 0:
            self.close_connection = True

        path = urlparse(self.path).path
        if path == "/health":
            body = (
                '{"ok":true,"running":true,"media":"%s"}'
                % (self.media.current_file or "")
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
            return

        if path.startswith("/media/"):
            # unquote: nama file bisa mengandung spasi / karakter non-ASCII
            # (URL dikirim sudah di-encode oleh kasir).
            filename = os.path.basename(unquote(path[len("/media/"):]))
            full = os.path.join(self.media.media_dir, filename)
            if not filename or not os.path.isfile(full):
                self.log_access(f"404 {filename or self.path}")
                self.send_error(404, "File not found")
                return
            ctype, _ = mimetypes.guess_type(full)
            ctype = sniff_content_type(full, ctype)
            size = os.path.getsize(full)

            # Dukungan HTTP Range (wajib untuk MediaPlayer/VideoView Android —
            # tanpa 206 Partial Content, video gagal diputar di Android <11).
            range_header = self.headers.get("Range")
            start, end = 0, size - 1
            if range_header and range_header.startswith("bytes="):
                try:
                    spec = range_header[6:].split(",", 1)[0].strip()
                    if spec.startswith("-"):
                        # bytes=-N → N byte terakhir
                        n = int(spec[1:])
                        start = max(size - n, 0)
                    else:
                        if "-" in spec:
                            start_s, end_s = spec.split("-", 1)
                            start = int(start_s)
                            if end_s:
                                end = int(end_s)
                    if start >= size:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    if end >= size:
                        end = size - 1
                    if start > end:
                        start = end
                except Exception:
                    start, end = 0, size - 1

                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(length))
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.log_access(f"{filename} range {start}-{end}/{size}")
                if not head_only:
                    with open(full, "rb") as f:
                        f.seek(start)
                        remaining = length
                        while remaining > 0:
                            chunk = f.read(min(64 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                return

            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.log_access(f"{filename} full {size}")
            if not head_only:
                with open(full, "rb") as f:
                    while True:
                        chunk = f.read(64 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            return

        self.send_error(404, "Not found")


class TvMediaServer:
    """Server HTTP untuk media promosi client TV (port default 8082)."""

    def __init__(self, media_dir: str, port: int = 8082, host: str = "0.0.0.0",
                 debug_log: bool = False):
        self.media_dir = os.path.abspath(media_dir)
        os.makedirs(self.media_dir, exist_ok=True)
        self.port = int(port)
        self.host = host
        self.debug_log = debug_log
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.running = False

        # Media yang sedang ditampilkan: {"type": "video"/"image", "filename": str}
        self.current_media: dict = {}
        self._media_lock = threading.Lock()
        self._access_lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        self._httpd.media = self  # type: ignore[attr-defined]
        self._httpd.daemon_threads = True  # type: ignore[attr-defined]
        self._httpd.debug_log = self.debug_log  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True, name="tv-media-server")
        self._thread.start()
        print(f"[TV MEDIA SERVER] HTTP media on http://{self.host}:{self.port} "
              f"(folder: {self.media_dir})")
        print(f"[TV MEDIA SERVER] Access log -> {os.path.join(self.media_dir, 'access.log')}")

    def stop(self) -> None:
        self.running = False
        if self._httpd:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            self._httpd = None

    # ── State media aktif ─────────────────────────────────────────────────────
    @property
    def current_file(self) -> str:
        with self._media_lock:
            return self.current_media.get("filename", "")

    def set_current(self, media_type: str, filename: str) -> None:
        with self._media_lock:
            self.current_media = {"type": media_type, "filename": filename}

    def clear_current(self) -> None:
        with self._media_lock:
            self.current_media = {}

    def simpan_file(self, src_path: str) -> str:
        """Salin file media ke folder server. Return nama file yang disimpan."""
        filename = os.path.basename(src_path)
        dest = os.path.join(self.media_dir, filename)
        import shutil

        shutil.copyfile(src_path, dest)
        return filename
