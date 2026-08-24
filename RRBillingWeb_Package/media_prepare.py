"""media_prepare — normalisasi video promo agar kompatibel dengan SEMUA Android TV.

Masalah: setiap merk TV Android & versi Android punya decoder berbeda. Format yang
hampir pasti didukung SEMUA (Android 4.x-14, Sony/TCL/Xiaomi/Sharp/Philips/Hisense/
Dahua/STB Amlogic-Rockchip-Allwinner-HiSilicon): MP4 H.264 Main Profile L4.0,
yuv420p, <=1080p30, audio AAC/MP3, moov di depan (faststart).

Alur:
1. Analisis file (ffmpeg -i + cek posisi box moov).
2. Sudah kompatibel + faststart        -> "copy"      (file dipakai apa adanya)
3. Kompatibel tapi moov di belakang    -> "remux"     (ffmpeg -c copy +faststart, cepat)
4. Codec/profile High/resolusi/fps/audio beda / tanpa audio -> "transcode" (encode ulang penuh)
5. Error                                -> raise      (caller fallback ke file asli)

ffmpeg diambil dari imageio-ffmpeg (dibundle saat build EXE); jika tidak ada,
caller bisa mengunduhnya sekali (lihat FFMPEG_URL) lalu retry.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from typing import Callable, Optional

# Format target: cukup rendah untuk semua SoC Android TV (termasuk STB murah),
# cukup bagus untuk iklan promosi di layar TV.
MAX_WIDTH = 1920
MAX_HEIGHT = 1080
MAX_FPS = 31.0
TARGET_FPS = 30
AUDIO_OK = {"aac", "mp3", "mp4a", "mp4a.40.2", "mp4a.40.5"}
PIX_OK = {"yuv420p"}

FFMPEG_URL = ("https://github.com/dedekemoking-commits/rr_billing_pro_windows/"
              "releases/latest/download/ffmpeg.exe")

_VIDEO_RE = re.compile(
    r"Stream #\d+:\d+.*?: Video: (\S+?)((?: \([^)]*\))*), "
    r"([a-z0-9_]+)(?:\([^)]*\))?, (\d+)x(\d+).*?, (\d+(?:\.\d+)?) fps")
_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?: Audio: (\S+)")
_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def ffmpeg_path() -> Optional[str]:
    """Lokasi ffmpeg.exe saat ini (paket EXE / imageio-ffmpeg / folder dev)."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass
    meipass = getattr(sys, "_MEIPASS", "")
    for cand in (
        os.path.join(meipass, "ffmpeg", "ffmpeg.exe"),
        os.path.join(meipass, "imageio_ffmpeg", "binaries", "ffmpeg-win-x86_64-v7.1.exe"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", "ffmpeg.exe"),
        "ffmpeg.exe",
    ):
        if cand and os.path.isfile(cand):
            return cand
    return None


def ffmpeg_target_path() -> str:
    """Lokasi yang seharusnya untuk menyimpan ffmpeg yang diunduh."""
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        return os.path.join(meipass, "ffmpeg", "ffmpeg.exe")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", "ffmpeg.exe")


def _moov_before_mdat(path: str) -> Optional[bool]:
    """True jika box 'moov' muncul SEBELUM 'mdat' (faststart) di level 1 MP4."""
    try:
        with open(path, "rb") as f:
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    return None
                size = int.from_bytes(hdr[:4], "big")
                typ = hdr[4:8]
                if size == 1:
                    ext = f.read(8)
                    if len(ext) < 8:
                        return None
                    size = int.from_bytes(ext, "big")
                elif size == 0:
                    return None
                if typ == b"moov":
                    return True
                if typ == b"mdat":
                    return False
                if size < 8:
                    return None
                if f.seek(size - 8, 1) < 0:
                    return None
    except Exception:
        pass
    return None


def analyze_video(path: str) -> dict:
    """Analisis codec/resolusi/fps/audio/faststart via ffmpeg -i."""
    exe = ffmpeg_path()
    info: dict = {"video": None, "audio": None, "faststart": None, "ffmpeg": exe}
    if not exe:
        return info
    try:
        p = subprocess.run(
            [exe, "-hide_banner", "-i", path],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=90)
        stderr = p.stderr or ""
        m = _VIDEO_RE.search(stderr)
        if m:
            codec = m.group(1).split("/")[0].strip().lower()
            profile = m.group(2).strip()
            pix = m.group(3)
            w = int(m.group(4))
            h = int(m.group(5))
            fps = float(m.group(6))
            info["video"] = {"codec": codec, "profile": profile, "pix_fmt": pix,
                             "width": w, "height": h, "fps": fps}
        a = _AUDIO_RE.search(stderr)
        if a:
            info["audio"] = a.group(1).split("(")[0].strip().lower()
    except Exception:
        pass
    if info["video"]:
        info["faststart"] = _moov_before_mdat(path)
    return info


def decide_action(info: dict) -> str:
    """'copy' | 'remux' | 'transcode' berdasarkan hasil analisis."""
    v = info.get("video")
    if not v:
        return "transcode"
    if v.get("codec") != "h264":
        return "transcode"
    # H.264 profile: hanya Main/Baseline yang didukung decoder SEMUA box
    # (beberapa STB Android 11 gagal decode High profile: layar hitam + spinner).
    pm = re.search(r"\(([^)]*)\)", v.get("profile") or "")
    profile = pm.group(1).strip().lower() if pm else ""
    if profile and profile not in ("main", "baseline"):
        return "transcode"
    if v.get("width", 0) > MAX_WIDTH or v.get("height", 0) > MAX_HEIGHT:
        return "transcode"
    if v.get("fps", 0) > MAX_FPS:
        return "transcode"
    if v.get("pix_fmt") not in PIX_OK:
        return "transcode"
    audio = (info.get("audio") or "").lower()
    if audio and audio not in AUDIO_OK:
        return "transcode"
    # Video tanpa audio: tambahkan track audio senyap (beberapa box hang
    # memutar video-only karena wait pakai pts audio). => transcode.
    if not audio:
        return "transcode"
    if info.get("faststart"):
        return "copy"
    return "remux"


def _parse_progress(line: str) -> Optional[float]:
    m = _TIME_RE.search(line)
    if not m:
        return None
    try:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        return None


def prepare_video(src: str, dest: str,
                  progress_cb: Optional[Callable[[float], None]] = None,
                  cancel: Optional[Callable[[], bool]] = None) -> str:
    """Siapkan src menjadi MP4 kompatibel semua TV di dest.

    Return 'copy' | 'remux' | 'transcode'. Raise RuntimeError bila gagal.
    progress_cb(float detik video terproses); cancel() -> True untuk batal.
    """
    exe = ffmpeg_path()
    if not exe:
        raise RuntimeError("ffmpeg tidak tersedia")
    info = analyze_video(src)
    action = decide_action(info)
    if action == "copy":
        shutil.copyfile(src, dest)
        return "copy"

    if action == "remux":
        args = [exe, "-y", "-hide_banner", "-loglevel", "error",
                "-i", src, "-c", "copy", "-movflags", "+faststart",
                "-map_metadata", "-1", dest]
    else:
        vf = f"scale='min({MAX_WIDTH},iw)':-2"
        if info.get("audio"):
            args = [exe, "-y", "-hide_banner", "-loglevel", "info",
                    "-i", src,
                    "-vf", vf, "-r", str(TARGET_FPS),
                    "-c:v", "libx264", "-profile:v", "main", "-level", "4.0",
                    "-pix_fmt", "yuv420p", "-crf", "23", "-preset", "veryfast",
                    "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000",
                    "-movflags", "+faststart", "-map_metadata", "-1", dest]
        else:
            # Sumber tanpa audio: suntik track audio senyap (AAC stereo).
            # Beberapa box Android 11 hang memutar video-only; tanpa audio,
            # sinkronisasi (wait pada pts audio) tidak pernah jalan.
            args = [exe, "-y", "-hide_banner", "-loglevel", "info",
                    "-i", src,
                    "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                    "-map", "0:v:0", "-map", "1:a:0", "-shortest",
                    "-vf", vf, "-r", str(TARGET_FPS),
                    "-c:v", "libx264", "-profile:v", "main", "-level", "4.0",
                    "-pix_fmt", "yuv420p", "-crf", "23", "-preset", "veryfast",
                    "-c:a", "aac", "-b:a", "64k", "-ac", "2", "-ar", "48000",
                    "-movflags", "+faststart", "-map_metadata", "-1", dest]

    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        raise RuntimeError(f"Gagal menjalankan ffmpeg: {e}") from e

    assert proc.stderr is not None
    for line in proc.stderr:
        if cancel and cancel():
            proc.terminate()
            raise RuntimeError("Dibatalkan")
        if progress_cb:
            t = _parse_progress(line)
            if t is not None:
                progress_cb(t)
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"Konversi video gagal (ffmpeg rc={rc})")
    if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
        raise RuntimeError("Hasil konversi kosong")
    return action
