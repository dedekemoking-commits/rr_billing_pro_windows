"""check_video - laporan kompatibilitas file video untuk semua Android TV.

Jalankan:
  python tools/check_video.py "path/video.mp4"

Menganalisis codec/resolusi/fps/audio/posisi moov lalu memberi verdict:
  AMAN       -> bisa dikirim langsung ke TV mana pun
  PERLU REMUX-> moov di belakang; aplikasi akan merapikan otomatis (cepat)
  PERLU TRANSCODE -> dikonversi otomatis saat dikirim via tombol VIDEO
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from media_prepare import (  # noqa: E402
    MAX_FPS, MAX_HEIGHT, MAX_WIDTH, analyze_video, decide_action, ffmpeg_path,
)

VERDICT = {
    "copy": "AMAN - format sudah didukung semua Android TV",
    "remux": "PERLU REMUX - moov di belakang (aplikasi merapikan otomatis, cepat)",
    "transcode": "PERLU TRANSCODE - dikonversi otomatis saat dikirim via tombol VIDEO",
}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f"File tidak ditemukan: {path}")
        return 1

    print(f"File      : {path}")
    print(f"Ukuran    : {os.path.getsize(path) / 1048576:.1f} MB")
    print(f"ffmpeg    : {ffmpeg_path() or 'TIDAK ADA (akan diunduh sekali oleh aplikasi)'}\n")

    info = analyze_video(path)
    v = info.get("video")
    if not v:
        print("Tidak dapat membaca stream video (bukan video yang valid?).")
        return 1

    audio = (info.get("audio") or "tanpa audio").upper()
    print("Video     : {codec} {profile} | {width}x{height} | {fps} fps | pix_fmt={pix_fmt}"
          .format(**v))
    print(f"Audio     : {audio}")
    print(f"faststart : {'YA (moov di depan)' if info.get('faststart') else 'TIDAK (moov di belakang)'}")
    batas = []
    if v["codec"] != "h264":
        batas.append(f"codec {v['codec'].upper()} -> butuh H.264")
    if v["width"] > MAX_WIDTH or v["height"] > MAX_HEIGHT:
        batas.append(f"resolusi {v['width']}x{v['height']} > {MAX_WIDTH}x{MAX_HEIGHT}")
    if v["fps"] > MAX_FPS:
        batas.append(f"fps {v['fps']} > {MAX_FPS}")
    if batas:
        print("Alasan    : " + "; ".join(batas))

    action = decide_action(info)
    print(f"\nVerdict   : {VERDICT[action]}")
    return 0 if action == "copy" else 1


if __name__ == "__main__":
    sys.exit(main())
