"""Generate QR panggil kasir untuk N TV (default 30) — untuk mencetak kartu QR.

Kode unik tiap TV disimpan di config qr_call sehingga aplikasi kasir mengenali
QR-nya (matching toleran via kode). Halaman QR di-host Firebase Hosting
(https://rrbillingpro.web.app/call.html) — bisa diakses dari jaringan mana pun;
override host via config qr_page_url bila perlu.

Pemakaian:
  python scripts/generate_qr_batch.py                  # TV 1..TV 30
  python scripts/generate_qr_batch.py --count 40 --prefix "Meja "
  python scripts/generate_qr_batch.py --owner kasir1   # isi param o= (menu web)
"""
import argparse
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import APP_BASE_DIR, ConfigManager  # noqa: E402

QR_PAGE_BASE = "https://rrbillingpro.web.app/call.html"


def _kode_baru():
    return secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:8].upper()


def _aman(nama):
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in nama).strip() or "TV"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=30, help="jumlah QR (default 30)")
    ap.add_argument("--start", type=int, default=1, help="nomor awal (default 1)")
    ap.add_argument("--prefix", default="TV ", help="awalan nama TV (default 'TV ')")
    ap.add_argument("--owner", default="", help="kasir/admin untuk param o= (menu web)")
    args = ap.parse_args()

    cfg = ConfigManager.load()
    peta = cfg.get("qr_call", {})
    if not isinstance(peta, dict):
        peta = {}
    base = str(cfg.get("qr_page_url", "") or "").strip() or QR_PAGE_BASE
    folder = os.path.join(APP_BASE_DIR, "qr_panggilan")
    os.makedirs(folder, exist_ok=True)

    from urllib.parse import quote
    import qrcode

    dibuat = 0
    for i in range(args.start, args.start + args.count):
        nama = f"{args.prefix}{i}"
        pi = peta.get(nama)
        kode = ""
        ip_lama = ""
        if isinstance(pi, dict):
            kode = str(pi.get("kode", "") or "")
            ip_lama = str(pi.get("ip", "") or "")
        if not kode:
            kode = _kode_baru()
            peta[nama] = {"kode": kode, "ip": ip_lama}
        url = f"{base}?tv={quote(nama)}&k={kode}"
        if args.owner:
            url += f"&o={quote(args.owner)}"
        path = os.path.join(folder, f"{_aman(nama)}.png")
        qrcode.make(url).save(path)
        print(f"{path}  kode={kode}")
        dibuat += 1

    cfg["qr_call"] = peta
    if not cfg.get("qr_page_url"):
        cfg["qr_page_url"] = base
    ConfigManager.save(cfg)
    print(f"\n{dibuat} QR dibuat di {folder}")
    print(f"halaman: {base}")


if __name__ == "__main__":
    main()
