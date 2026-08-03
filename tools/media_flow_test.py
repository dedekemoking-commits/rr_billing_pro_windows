"""media_flow_test — simulasi pola request MediaPlayer/VideoView Android lintas versi.

Menjalankan TvMediaServer di port acak lalu menguji semua pola permintaan yang
dikirim player Android (4.x-14, semua merk). Wajib LULUS sebelum rilis:

  - HEAD tanpa Range        -> 200 + Content-Length + Accept-Ranges (Android <11)
  - GET tanpa Range          -> 200
  - GET Range: bytes=0-      -> 206 + Content-Range penuh (progressive play)
  - GET Range: bytes=100-200 -> 206 (seek mid-file)
  - GET Range: bytes=-500    -> 206 (suffix)
  - GET Range di luar file   -> 416
  - HTTP/1.0                 -> tetap dilayani
  - Connection: close        -> koneksi ditutup setelah response
  - File ber-spasi / non-ASCII (URL-encoded) -> 200 (nama file di-unquote)
  - Content-Type dari magic bytes (file tanpa ekstensi MP4 -> video/mp4)
  - 404 untuk file hilang

Jalankan:  python tools/media_flow_test.py
"""
from __future__ import annotations

import os
import socket
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tv_media_server import TvMediaServer  # noqa: E402

PASS = 0
FAIL = 0


def ok(condition: bool, label: str, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label} {detail}")


def raw_request(port: int, method: str, path: str,
                headers: dict | None = None,
                http_ver: str = "HTTP/1.1",
                want_body: bool = True) -> tuple[int, dict, bytes]:
    """Kirim request mentah, return (status, headers_dict, body)."""
    s = socket.create_connection(("127.0.0.1", port), timeout=15)
    if method == "HEAD":
        want_body = False  # HEAD tidak pernah punya body
    try:
        lines = [f"{method} {path} {http_ver}"]
        for k, v in (headers or {}).items():
            lines.append(f"{k}: {v}")
        s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
            if b"\r\n\r\n" in data:
                head, _, body = data.partition(b"\r\n\r\n")
                clen = 0
                for line in head.split(b"\r\n")[1:]:
                    if line.lower().startswith(b"content-length:"):
                        clen = int(line.split(b":", 1)[1].strip() or 0)
                if not want_body or len(body) >= clen:
                    break
    finally:
        s.close()
    head, _, body = data.partition(b"\r\n\r\n")
    lines2 = head.split(b"\r\n")
    status = int(lines2[0].split(b" ")[1])
    hdrs = {}
    for line in lines2[1:]:
        if b":" in line:
            k, _, v = line.partition(b":")
            hdrs[k.strip().lower().decode("latin1")] = v.strip().decode("latin1")
    return status, hdrs, body


def main() -> int:
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="media_flow_test_")
    # 1. file MP4 biasa (dengan spasi + non-ASCII di nama)
    mp4_path = os.path.join(tmp, "video promo 2026.mp4")
    with open(mp4_path, "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 2032)
    # 2. file MP4 TANPA ekstensi (uji sniff content-type)
    noext = os.path.join(tmp, "promo_android11")
    with open(noext, "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomiso2" + b"\x00" * 1000)
    # 3. file gambar PNG (uji sniff)
    png_path = os.path.join(tmp, "logo.png")
    with open(png_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 500)

    srv = TvMediaServer(tmp, port=0)  # port 0 -> pilih port acak
    srv.start()
    port = srv._httpd.server_address[1]
    time.sleep(0.3)
    size = os.path.getsize(mp4_path)
    print(f"Server media di port {port}, file uji: {os.path.basename(mp4_path)} "
          f"({size} bytes)\n")

    # ── HEAD (Android <11 memulai dengan HEAD) ──────────────────────────────
    print("HEAD tanpa Range (pola Android <11):")
    st, hd, body = raw_request(port, "HEAD", "/media/video%20promo%202026.mp4")
    ok(st == 200, "HEAD -> 200", f"(got {st})")
    ok(hd.get("content-length") == str(size), "HEAD Content-Length sesuai",
       f"(got {hd.get('content-length')})")
    ok(hd.get("accept-ranges") == "bytes", "HEAD Accept-Ranges: bytes")
    ok(body == b"", "HEAD tanpa body")

    print("\nHEAD dengan Range (beberapa build):")
    st, hd, _ = raw_request(port, "HEAD", "/media/video%20promo%202026.mp4",
                            {"Range": "bytes=0-"})
    ok(st == 206, "HEAD Range 0- -> 206", f"(got {st})")
    ok(hd.get("content-range") == f"bytes 0-{size-1}/{size}",
       "HEAD Content-Range penuh")

    # ── GET progressive ─────────────────────────────────────────────────────
    print("\nGET (progressive play):")
    st, hd, body = raw_request(port, "GET", "/media/video%20promo%202026.mp4")
    ok(st == 200, "GET -> 200", f"(got {st})")
    ok(len(body) == size, "GET body lengkap")
    ok(hd.get("content-type", "").startswith("video/mp4"), "GET Content-Type video/mp4")

    print("\nGET Range 0- (Android mulai main):")
    st, hd, body = raw_request(port, "GET", "/media/video%20promo%202026.mp4",
                               {"Range": "bytes=0-"})
    ok(st == 206, "GET Range 0- -> 206", f"(got {st})")
    ok(len(body) == size, "body = ukuran penuh")
    ok(hd.get("content-range") == f"bytes 0-{size-1}/{size}", "Content-Range penuh")

    print("\nGET Range tengah (seek 100-200):")
    st, hd, body = raw_request(port, "GET", "/media/video%20promo%202026.mp4",
                               {"Range": "bytes=100-200"})
    ok(st == 206, "Range 100-200 -> 206", f"(got {st})")
    ok(len(body) == 101, "panjang body = 101")
    ok(body == b"\x00" * 101, "isi body dari offset 100")

    print("\nGET Range suffix (-500):")
    st, hd, body = raw_request(port, "GET", "/media/video%20promo%202026.mp4",
                               {"Range": "bytes=-500"})
    ok(st == 206, "Range -500 -> 206", f"(got {st})")
    ok(len(body) == 500, "panjang body = 500")

    print("\nGET Range di luar file (416):")
    st, _, _ = raw_request(port, "GET", "/media/video%20promo%202026.mp4",
                           {"Range": f"bytes={size + 1000}-"})
    ok(st == 416, "Range out-of-bounds -> 416", f"(got {st})")

    # ── HTTP/1.0 & Connection close ─────────────────────────────────────────
    print("\nHTTP/1.0 (player tua):")
    st, hd, body = raw_request(port, "GET", "/media/video%20promo%202026.mp4",
                               http_ver="HTTP/1.0")
    ok(st == 200 and len(body) == size, "HTTP/1.0 -> 200 + body lengkap")

    print("\nConnection: close (harus ditutup server):")
    s = socket.create_connection(("127.0.0.1", port), timeout=15)
    s.sendall(b"GET /media/video%20promo%202026.mp4 HTTP/1.1\r\n"
              b"Connection: close\r\n\r\n")
    data = b""
    s.settimeout(10)
    try:
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    except socket.timeout:
        pass
    s.close()
    ok(b"200 OK" in data and len(data) >= size, "Connection: close diterima + body penuh")

    # ── Sniff content-type ──────────────────────────────────────────────────
    print("\nSniff Content-Type dari magic bytes:")
    st, hd, _ = raw_request(port, "HEAD", "/media/promo_android11")
    ok(st == 200 and hd.get("content-type", "").startswith("video/mp4"),
       "file tanpa ekstensi MP4 -> video/mp4")
    st, hd, _ = raw_request(port, "HEAD", "/media/logo.png")
    ok(st == 200 and hd.get("content-type", "").startswith("image/png"),
       "PNG -> image/png")

    # ── 404 ─────────────────────────────────────────────────────────────────
    print("\nFile tidak ada:")
    st, _, _ = raw_request(port, "GET", "/media/tidak-ada.mp4")
    ok(st == 404, "GET file hilang -> 404")

    # ── Health ──────────────────────────────────────────────────────────────
    st, _, _ = raw_request(port, "GET", "/health")
    ok(st == 200, "/health -> 200")

    srv.stop()

    print(f"\n{'='*50}")
    print(f"HASIL: {PASS} PASS, {FAIL} FAIL")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
