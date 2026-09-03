# -*- coding: utf-8 -*-
"""
RR Billing Pro — Web Kasir (localhost)
======================================
Backend Flask yang mengupas logika billing dari main.py (tanpa GUI tkinter).
Berbagi file data yang sama dengan aplikasi desktop:
  - rr_billing_config.json   (users, tarif, menu, daftar TV/warnet, printer)
  - rr_billing_riwayat.json  (riwayat transaksi)
  - Firestore cloud          (billingps_users/{admin_utama}.transaksiList)

JANGAN menjalankan aplikasi desktop (main.py) bersamaan dengan server ini:
keduanya punya state sesi in-memory sendiri & menulis file yang sama.
"""

import os
import sys
import re
import json
import time
import math
import random
import string
import shutil
import socket
import subprocess
import tempfile
import ipaddress
import threading
import datetime
import logging
from urllib.parse import quote

try:
    from PIL import Image as _PILImage
except Exception:
    _PILImage = None

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import mimetypes
mimetypes.add_type("font/woff2", ".woff2")

import main as M  # noqa: E402  (ConfigManager, fmt_rp, hitung_tarif_per_menit, verify_password, ...)
from rr_license import LicenseManager  # noqa: E402
WEB_APP_VERSION = "2.4.15"   # versi aplikasi Web Kasir (billing_web)
from firestore_sync import FirestoreClient  # noqa: E402
from firebase_auth import API_KEY as FIREBASE_API_KEY  # noqa: E402
from tv_ws_hub import TvWsHub  # noqa: E402 — hub WebSocket untuk Android TV (port 8080)
from tv_media_server import TvMediaServer  # noqa: E402 — server media promosi (port 8082)
from warnet_server import WarnetServerWeb  # noqa: E402 — socket server warnet (port 5000)
import tv_mesin  # noqa: E402 — pairing & remote Android TV (androidtvremote2)
import media_prepare  # noqa: E402 — normalisasi video promo (ffmpeg) agar jalan di semua TV
import smart_plug  # noqa: E402 — smart WiFi plug (Tuya/Bardi/Yanzi) untuk lampu LED per TV

logging.basicConfig(level=logging.INFO, format="%(asctime)s [WEB] %(message)s")
_LOGGER = logging.getLogger("rrbilling.web")

# Pastikan stdout/stderr pakai UTF-8 (errors=replace) agar karakter seperti
# ❌/✖ di pesan error tidak memicu UnicodeEncodeError di console Windows (cp1252)
# yang bisa mematikan worker request.
try:
    for _s in (sys.stdout, sys.stderr):
        if _s is not None and getattr(_s, "reconfigure", None) is not None:
            try:
                _s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
except Exception:
    pass

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")
HOST = "127.0.0.1"
PORT = 8000

_APPLOG_PATH = os.path.join(APP_DIR, "web_app.log")
_APPLOG_LOCK = threading.Lock()


def applog(msg):
    """Log aplikasi lengkap: timestamp -> web_app.log (append) + stderr."""
    try:
        line = time.strftime("%Y-%m-%d %H:%M:%S") + "  " + str(msg)
        with _APPLOG_LOCK:
            with open(_APPLOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass
    try:
        _LOGGER.info("%s", msg)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────
#  SESI (state machine TV / warnet) — port dari KartuTV/KartuWarnet (main.py)
# ─────────────────────────────────────────────────────────────────────────
class Sesi:
    def __init__(self, store, kind, nomor, label, nama_grup, ip=None, pc_id=None):
        self.store = store
        self.kind = kind            # 'tv' | 'warnet'
        self.nomor = nomor
        self.label = label
        self.nama_grup = nama_grup
        self.ip = ip
        self.pc_id = pc_id
        self.plug = None            # config smart plug per-TV: {device_id, ip, local_key, version}

        self.paket_aktif = None
        self.sisa_waktu = 0
        self.is_bebas = False
        self.menit_dipakai_awal = 0
        self.waktu_mulai = None
        self.pesanan_aktif = {}
        self.biaya_pesanan = 0
        self.paket_harga_tetap = 0
        self.daftar_paket_sesi = []
        # Status pembayaran PER ITEM (port main.py KartuTV): lunas_paket[i]
        # sejajar daftar_paket_sesi[i], harga_paket_sesi[i] = harga paket ke-i,
        # lunas_pesanan[nm] = status item pesanan makanan/minuman.
        self.lunas_paket = []
        self.harga_paket_sesi = []
        self.lunas_pesanan = {}
        self.diskoni = 0
        self.diskoni_mode = "nominal"
        self._last_transaction_item = None   # index ke riwayat_transaksi
        self.paid = True
        self._timer_paused = False
        self._paused_total = None

        # Mode member (saldo waktu): sesi berjalan memotong saldo member,
        # potongan saldo dilakukan saat sesi berakhir (aman crash).
        self.mode_member = False
        self.member_hp = None
        self.member_nama = None
        self.member_detik_pakai = 0   # akumulasi detik terpakai (pause-safe)

        # Pelacak auto cut-off TV (idle tanpa sesi)
        self.idle_on_seconds = 0
        self.idle_escalated = False
        self._tv_status_last = None

    # ── katalog ─────────────────────────────────────────────────────────
    def paket_data(self):
        return self.store.paket_data(self.nama_grup, for_warnet=(self.kind == "warnet"))

    def all_menu(self):
        return {**self.store.menu_makanan, **self.store.menu_minuman}

    def sesi_kosong(self):
        return not self.paket_aktif and not self.is_bebas

    def timer_key(self):
        return str(self.pc_id) if (self.kind == "warnet" and self.pc_id) else str(self.nomor)

    # ── total & diskon (port _total_setelah_diskon) ─────────────────────
    def total_setelah_diskon(self, subtotal=None):
        if subtotal is None:
            subtotal = self.paket_harga_tetap + self.biaya_pesanan
        if self.diskoni <= 0:
            return subtotal
        if self.diskoni_mode == "persen":
            diskon = subtotal * self.diskoni // 100
        else:
            diskon = self.diskoni
        return max(0, subtotal - diskon)

    def total_menit_terpakai(self):
        if self.is_bebas:
            if self.waktu_mulai is None:
                return self.menit_dipakai_awal
            detik = (datetime.datetime.now() - self.waktu_mulai).total_seconds()
            return self.menit_dipakai_awal + detik / 60
        return None

    def split_lunas_tagihan(self):
        """Split tagihan sesi jadi (lunas_total, tagihan_total) PER ITEM —
        port main.py KartuTV._split_payment: status dihitung granular per paket
        (sejajar daftar_paket_sesi, dengan harga per segmen) dan per item
        pesanan (lunas_pesanan). Diskon dialokasikan proporsional."""
        try:
            total = self.total_setelah_diskon()
        except Exception:
            total = getattr(self, "paket_harga_tetap", 0) + getattr(self, "biaya_pesanan", 0)
        if self.sesi_kosong():
            return 0, 0
        if getattr(self, "is_bebas", False):
            return total, 0
        try:
            subtotal = self.paket_harga_tetap + self.biaya_pesanan
        except Exception:
            subtotal = 0
        if subtotal <= 0:
            if getattr(self, "paid", True):
                return total, 0
            return 0, total

        # ── subtotal LUNAS per item ──
        lunas_sub = 0
        harga_paket = getattr(self, "harga_paket_sesi", None) or []
        lunas_paket = getattr(self, "lunas_paket", None) or []
        if harga_paket:
            for i, h in enumerate(harga_paket):
                paid_i = lunas_paket[i] if i < len(lunas_paket) else getattr(self, "paid", True)
                if paid_i:
                    lunas_sub += h
        else:
            # fallback sesi lama (tanpa data per item): pakai paid keseluruhan
            if getattr(self, "paid", True):
                lunas_sub += self.paket_harga_tetap

        all_menu = self.all_menu()
        lunas_pesanan = getattr(self, "lunas_pesanan", None) or {}
        for nm, qty in (self.pesanan_aktif or {}).items():
            paid_i = lunas_pesanan.get(nm, getattr(self, "paid", True))
            if paid_i:
                lunas_sub += all_menu.get(nm, 0) * qty

        lunas_sub = min(lunas_sub, subtotal)
        if lunas_sub >= subtotal:
            lunas_res = total
        elif lunas_sub <= 0:
            lunas_res = 0
        else:
            # diskon proporsional terhadap subtotal lunas
            lunas_res = round(total * lunas_sub / subtotal)
        lunas_res = min(lunas_res, total)
        tagihan_res = max(0, total - lunas_res)
        return lunas_res, tagihan_res

    def biaya_bebas_berjalan(self):
        """Biaya Main Bebas berjalan (waktu + pesanan), persis seperti _tick_bebas."""
        total_detik = self.menit_dipakai_awal * 60 + (
            int((datetime.datetime.now() - self.waktu_mulai).total_seconds())
            if self.waktu_mulai else 0)
        tarif = M.hitung_tarif_per_menit(self.paket_data())
        biaya_waktu = tarif * (total_detik / 60)
        return self.total_setelah_diskon(biaya_waktu + self.biaya_pesanan)

    # ── mulai paket (port _on_paket_confirm, tanpa UI) ──────────────────
    def start_paket(self, paket_nm, paket_harga, paket_menit, pesanan, total_pesanan,
                    diskoni=0, diskoni_mode="nominal", paid=None):
        # Validasi & delta stok makanan/minuman
        delta = {}
        for nm, qty in (pesanan or {}).items():
            d = int(qty or 0) - int(self.pesanan_aktif.get(nm, 0) or 0)
            if d > 0:
                delta[nm] = d
        if delta:
            self.store._stok_validate(delta)
        previous_session = not self.sesi_kosong()
        self.menit_dipakai_awal = 0
        self.diskoni = diskoni
        self.diskoni_mode = diskoni_mode
        all_menu = self.all_menu()

        if not previous_session:
            self.daftar_paket_sesi = [paket_nm]
            self.harga_paket_sesi = [paket_harga]
            self.lunas_paket = [True if paid is None else bool(paid)]
            self.pesanan_aktif = dict(pesanan or {})
            self.lunas_pesanan = {nm: (True if paid is None else bool(paid))
                                  for nm in (pesanan or {})}
            self.biaya_pesanan = sum(all_menu.get(nm, 0) * qty for nm, qty in self.pesanan_aktif.items())
        else:
            self.daftar_paket_sesi.append(paket_nm)
            self.harga_paket_sesi.append(paket_harga)
            self.lunas_paket.append(True if paid is None else bool(paid))
            for nm, qty in (pesanan or {}).items():
                self.pesanan_aktif[nm] = qty
                self.lunas_pesanan[nm] = True if paid is None else bool(paid)
            if pesanan:
                self.biaya_pesanan += sum(all_menu.get(nm, 0) * qty for nm, qty in pesanan.items())

        if paket_nm == "Main Bebas":
            self.is_bebas = True
            self.sisa_waktu = 0
            self.waktu_mulai = datetime.datetime.now()
            self.paket_harga_tetap = 0
            self.paket_aktif = paket_nm
        else:
            self.is_bebas = False
            self.paket_aktif = paket_nm
            if previous_session and self.paket_harga_tetap:
                self.sisa_waktu += paket_menit * 60
                self.paket_harga_tetap += paket_harga
            else:
                self.sisa_waktu = paket_menit * 60
                self.paket_harga_tetap = paket_harga
            self.waktu_mulai = datetime.datetime.now()

        self._timer_paused = False
        self._paused_total = None

        if not self.is_bebas:
            if self._last_transaction_item is not None and previous_session:
                self.store.update_row_meta(self, self.total_setelah_diskon())
            else:
                total_int_baru = self.total_setelah_diskon(self.paket_harga_tetap + total_pesanan)
                self._last_transaction_item = self.store.catat(
                    self.label, paket_nm, self.pesanan_aktif, total_int_baru,
                    source=self.kind, diskoni=diskoni, diskoni_mode=diskoni_mode,
                    paid=paid, sesi=self)
        else:
            self._last_transaction_item = None

        if self.is_bebas:
            # Hormati pilihan kasir (LUNAS/TAGIHAN); total berjalan dicatat
            # ulang saat sesi berakhir (klik_selesai).
            self.paid = True if paid is None else bool(paid)
            self.lunas_paket = [self.paid] * (len(self.daftar_paket_sesi or []) or 1)
            self.lunas_pesanan = {nm: self.paid for nm in self.pesanan_aktif}
        else:
            if not previous_session:
                self.paid = True if paid is None else bool(paid)
                self.lunas_paket = [self.paid] * (len(self.daftar_paket_sesi or []) or 1)
                self.lunas_pesanan = {nm: self.paid for nm in self.pesanan_aktif}

        if self._hub_ok():
            total = self.total_setelah_diskon()
            lunas_now, tagihan_now = self.split_lunas_tagihan()
            nama_member = self.member_nama if getattr(self, "mode_member", False) else None
            if self.is_bebas:
                self.store.hub.send_start_timer(self.label, -1, total,
                                                lunas_total=lunas_now, tagihan_total=tagihan_now,
                                                nama_member=nama_member)
            else:
                self.store.hub.send_start_timer(self.label, self.sisa_waktu, total,
                                                lunas_total=lunas_now, tagihan_total=tagihan_now,
                                                nama_member=nama_member)
        self._warnet_queue("UNLOCK", "sesi_baru", f"Sesi baru dimulai untuk {self.label}")

        self.store._stok_terapkan(delta)
        self.store.notify("paket", self.snapshot())

        applog(f"[SESI MULAI] {self.label} | grup={self.nama_grup} | paket={paket_nm} | "
               f"pesanan={list((pesanan or {}).items())} | harga_paket={paket_harga} | "
               f"diskoni={diskoni}({diskoni_mode}) | total={self.total_setelah_diskon()}")
        self.store._sync_timer_state()

    # ── tambah pesanan SHOP (port _on_tambah_pesanan_confirm) ───────────
    def tambah_pesanan(self, pesanan_baru, paid=None):
        # Validasi & delta stok (qty baru - qty lama) sebelum diterapkan
        delta = {}
        for nama, qty in (pesanan_baru or {}).items():
            if qty is None:
                qty = 0
            try:
                qty = int(qty)
            except Exception:
                qty = 0
            new_q = qty if qty > 0 else 0
            d = new_q - int(self.pesanan_aktif.get(nama, 0) or 0)
            if d > 0:
                delta[nama] = d
        if delta:
            self.store._stok_validate(delta)
        all_menu = self.all_menu()
        paid_flag = True if paid is None else bool(paid)
        for nama, qty in (pesanan_baru or {}).items():
            if qty is None:
                qty = 0
            try:
                qty = int(qty)
            except Exception:
                qty = 0
            if qty <= 0:
                self.pesanan_aktif.pop(nama, None)
                self.lunas_pesanan.pop(nama, None)
            else:
                self.pesanan_aktif[nama] = qty
                self.lunas_pesanan[nama] = paid_flag

        total_baru = sum(all_menu.get(nm, 0) * qty for nm, qty in self.pesanan_aktif.items())
        self.biaya_pesanan = total_baru
        if not self.is_bebas:
            total_semua = self.total_setelah_diskon(self.paket_harga_tetap + total_baru)
            if self._last_transaction_item is not None:
                self.store.update_row_meta(self, total_semua)
        if self._hub_ok() and self.paket_aktif:
            lunas_now, tagihan_now = self.split_lunas_tagihan()
            self.store.hub.send_update_total(self.label, self.total_setelah_diskon(),
                                             lunas_total=lunas_now, tagihan_total=tagihan_now)
        self.store._stok_terapkan(delta)
        self.store.notify("shop", self.snapshot())
        self.store._sync_timer_state()

    def set_paid(self, paid):
        self.paid = bool(paid)
        # Semua item ikut memilih tombol (port main.py KartuTV.set_paid)
        self.lunas_paket = [bool(paid)] * (len(self.daftar_paket_sesi or []) or 1)
        if self.pesanan_aktif:
            self.lunas_pesanan = {nm: bool(paid) for nm in self.pesanan_aktif}
        self._sync_paid_state()

    def _recalc_paid(self):
        """paid keseluruhan = SEMUA segmen paket & SEMUA pesanan LUNAS
        (per-item tracking; ada item TAGIHAN → paid False)."""
        paid = getattr(self, "paid", True)
        pk = all(self.lunas_paket[i] if i < len(self.lunas_paket) else paid
                 for i in range(len(self.daftar_paket_sesi or []) or 1))
        ps = all(bool(self.lunas_pesanan.get(nm, paid))
                 for nm in (self.pesanan_aktif or {}))
        return pk and ps

    def _sync_paid_state(self):
        """Sinkron status bayar ke riwayat (meta+row), badge & split ke hub
        (popup TV), notify. Dipakai set_paid & alur QR per-item."""
        if self._last_transaction_item is not None and not self.is_bebas:
            try:
                lunas_r, tagihan_r = self.split_lunas_tagihan()
                meta = self.store.riwayat_meta[self._last_transaction_item]
                meta['paid'] = self.paid
                meta['lunas_total'] = lunas_r
                meta['tagihan_total'] = tagihan_r
                self.store._refresh_paid_row(self._last_transaction_item)
                self.store._save_riwayat()
            except Exception:
                pass
        # Sinkron badge LUNAS/TAGIHAN ke popup & lock screen APK TV (sama seperti
        # desktop KartuTV._ws_send_total saat status pembayaran berubah).
        if self._hub_ok() and self.paket_aktif and not self.is_bebas:
            try:
                lunas_now, tagihan_now = self.split_lunas_tagihan()
                self.store.hub.send_update_total(
                    self.label, self.total_setelah_diskon(),
                    lunas_total=lunas_now, tagihan_total=tagihan_now)
            except Exception:
                pass
        self.store.notify("paid", self.snapshot())
        try:
            self.store._sync_timer_state()
        except Exception:
            pass

    # ── timer tick (dipanggil TimerService/thread) ──────────────────────
    def tick(self):
        if self.paket_aktif and self.sisa_waktu > 0 and not self._timer_paused:
            self.sisa_waktu = max(0, self.sisa_waktu - 1)
            if getattr(self, "mode_member", False):
                self.member_detik_pakai += 1
            if self.sisa_waktu <= 0:
                self.timer_habis()
                return "habis"
        return None

    # ── potongan saldo member di akhir sesi ─────────────────────────────
    def _auto_print_struk(self):
        """Cetak struk OTOMATIS ke printer terhubung saat sesi berakhir.
        Lewatkan bila tidak ada printer (type='file') atau baris transaksi
        tidak ditemukan. Status cetak dilaporkan ke UI via event 'print'."""
        try:
            cfg = M.ConfigManager.get("printer_settings", {}) or {}
            if cfg.get("type") not in ("bluetooth", "usb", "network"):
                return
            idx = getattr(self, "_last_transaction_item", None)
            if idx is None or not (0 <= idx < len(self.store.riwayat_meta)):
                return
            row = self.store.riwayat_transaksi[idx]
            meta = self.store.riwayat_meta[idx] or {}
            text = build_struk_text(
                row[2], meta.get("paket_raw", ""), meta.get("paket_harga", 0), None,
                meta.get("pesanan", {}) or {}, meta.get("pesanan_total", 0),
                meta.get("diskoni", 0), meta.get("diskoni_mode", "nominal"),
                meta.get("total", 0), row[1],
                self.store.menu_makanan, self.store.menu_minuman)
            _print_async(text)
            applog(f"[AUTO PRINT] {self.label} | {meta.get('paket_raw', '')} | "
                   f"total={meta.get('total', 0)}")
        except Exception as e:
            _LOGGER.warning("Auto print %s gagal: %s", self.label, e)

    def _member_potong_akhir(self):
        """Potong saldo waktu member sebesar menit terpakai (dibulatkan ke atas).
        Dipanggil sekali tepat sebelum sesi di-reset."""
        if not getattr(self, "mode_member", False) or not self.member_hp:
            return
        menit = -(-int(self.member_detik_pakai or 0) // 60)   # ceil
        if menit <= 0:
            return
        try:
            saldo_baru = self.store.potong_saldo_member(self.member_hp, menit)
            applog(f"[MEMBER POTONG] {self.label} | {self.member_nama} "
                   f"({self.member_hp}) -{menit} mnt | sisa saldo={saldo_baru} mnt")
        except Exception as e:
            _LOGGER.warning("Potong saldo member %s gagal: %s", self.member_hp, e)

    # ── waktu habis (port _timer_habis, tanpa dialog & kontrol TV) ──────
    def timer_habis(self):
        if self.sesi_kosong():
            return
        total_akhir = self.total_setelah_diskon()
        lunas_now, tagihan_now = self.split_lunas_tagihan()
        nm_paket = self.paket_aktif or "-"
        if self._last_transaction_item is not None:
            self.store.update_row_meta(self, total_akhir)
        else:
            self._last_transaction_item = self.store.catat(
                self.label, self.paket_aktif, self.pesanan_aktif, total_akhir,
                source=self.kind, diskoni=self.diskoni, diskoni_mode=self.diskoni_mode,
                paid=self.paid, sesi=self)
        if self._hub_ok():
            try:
                self.store.hub.send_lock_screen(self.label, "WAKTU SEWA HABIS",
                                                self._lock_detail(total_akhir))
            except Exception:
                pass
        self._warnet_queue("LOCK", "waktu_habis",
                           f"Waktu PC {self.label} telah habis.", time_left=0)
        snap = self.snapshot()
        member_ev = None
        if getattr(self, "mode_member", False):
            member_ev = {"hp": self.member_hp, "nama": self.member_nama}
            self._member_potong_akhir()
        self._auto_print_struk()
        self.store.notify("habis", snap,
                          paid=self.paid, paket=nm_paket,
                          lunas=lunas_now, tagihan=tagihan_now,
                          key=self.timer_key(), kind=self.kind,
                          member=member_ev)
        paid_log = self.paid
        self.reset()
        applog(f"[WAKTU HABIS] {self.label} | total={total_akhir} | paid={paid_log} | "
               f"paket={nm_paket} | kasir={self.store.user}")

    def pause(self):
        if not self._timer_paused:
            self._timer_paused = True
            if self.is_bebas:
                self._paused_total = self.biaya_bebas_berjalan()
            if self._hub_ok() and self.paket_aktif:
                self.store.hub.send_pause_timer(self.label)
            self.store.notify("pause", self.snapshot())
            self.store._sync_timer_state()

    def resume(self):
        self._timer_paused = False
        self._paused_total = None
        if self._hub_ok() and self.paket_aktif:
            self.store.hub.send_resume_timer(self.label, self.sisa_waktu)
        self.store.notify("resume", self.snapshot())
        self.store._sync_timer_state()

    # ── selesai (port _klik_selesai, tanpa dialog konfirmasi) ───────────
    def klik_selesai(self):
        if self.sesi_kosong():
            return None
        if self.is_bebas:
            menit_total = self.total_menit_terpakai()
            tarif = M.hitung_tarif_per_menit(self.paket_data())
            biaya_waktu = tarif * menit_total
            total_akhir = self.total_setelah_diskon(biaya_waktu + self.biaya_pesanan)
            self._last_transaction_item = self.store.catat(
                self.label, "Main Bebas", self.pesanan_aktif, total_akhir,
                source=self.kind, diskoni=self.diskoni, diskoni_mode=self.diskoni_mode,
                paid=self.paid, sesi=self)
        snap = self.snapshot()
        if self._hub_ok():
            try:
                self.store.hub.send_stop_timer(self.label)
                # TV dikunci saat kasir konfirmasi pembayaran selesai
                # Bug Fix 2: Gunakan _lock_detail_tv untuk singkron status bayar/tagihan dengan aplikasi
                self.store.hub.send_lock_screen(self.label, "SELESAI BAYAR", _lock_detail_tv(snap))
            except Exception:
                pass
        # ─ Bug Fix 1: TV sleep setelah klik selesai (delay 1 detik agar lock screen terlihat dulu) ─
        if self.ip:
            try:
                port = int(getattr(self, "port", 0) or 0)
                alasan = f"Sesi {self.label} selesai - dibayar admin"
                threading.Thread(
                    target=_tv_sleep_runner,
                    args=(self.ip, port, self.label, self.timer_key()),
                    kwargs={"alasan": alasan, "delay": 1},
                    daemon=True, name=f"SleepOnSelesai-{self.label}").start()
            except Exception as e:
                applog(f"[ERROR] TV sleep fail {self.label}: {e}")
        self._warnet_queue("LOCK", "selesai_manual",
                           f"Sesi {self.label} dihentikan admin.")
        # TIDAK auto cetak struk - cetak hanya ketika kasir klik print manual
        self._member_potong_akhir()
        self.reset()
        self.store.notify("selesai", snap)
        applog(f"[SESI SELESAI] {self.label} | total={snap.get('total')} | "
               f"paid={snap.get('paid')} | kasir={self.store.user}")
        return snap

    def reset(self):
        self.paket_aktif = None
        self.sisa_waktu = 0
        self.is_bebas = False
        self.waktu_mulai = None
        self.menit_dipakai_awal = 0
        self.pesanan_aktif = {}
        self.biaya_pesanan = 0
        self.paket_harga_tetap = 0
        self.daftar_paket_sesi = []
        self.lunas_paket = []
        self.harga_paket_sesi = []
        self.lunas_pesanan = {}
        self.diskoni = 0
        self.diskoni_mode = "nominal"
        self._timer_paused = False
        self._paused_total = None
        self.paid = True
        self.mode_member = False
        self.member_hp = None
        self.member_nama = None
        self.member_detik_pakai = 0
        self._last_transaction_item = None
        try:
            self.store._sync_timer_state()
        except Exception:
            pass

    # ── snapshot untuk API ──────────────────────────────────────────────
    def snapshot(self):
        if self.is_bebas:
            if self._timer_paused and self._paused_total is not None:
                total = self._paused_total
            else:
                total = self.biaya_bebas_berjalan()
            total_detik = self.menit_dipakai_awal * 60 + (
                int((datetime.datetime.now() - self.waktu_mulai).total_seconds())
                if self.waktu_mulai else 0)
            menit_terpakai = round(total_detik / 60, 1)
            durasi = total_detik
        else:
            total = self.total_setelah_diskon()
            menit_terpakai = None
            durasi = self.sisa_waktu
        try:
            lunas_res, tagihan_res = self.split_lunas_tagihan()
        except Exception:
            lunas_res, tagihan_res = 0, 0
        return {
            "kind": self.kind,
            "nomor": self.nomor,
            "key": self.timer_key(),
            "label": self.label,
            "group": self.nama_grup,
            "paket": self.paket_data(),
            "paket_aktif": self.paket_aktif,
            "sisa_waktu": self.sisa_waktu,
            "durasi": durasi,
            "is_bebas": self.is_bebas,
            "menit_terpakai": menit_terpakai,
            "waktu_mulai": self.waktu_mulai.isoformat() if self.waktu_mulai else None,
            "pesanan_aktif": dict(self.pesanan_aktif),
            "biaya_pesanan": self.biaya_pesanan,
            "paket_harga_tetap": self.paket_harga_tetap,
            "daftar_paket_sesi": list(self.daftar_paket_sesi),
            "diskoni": self.diskoni,
            "diskoni_mode": self.diskoni_mode,
            "paid": self.paid,
            "lunas_total": int(round(lunas_res)),
            "tagihan_total": int(round(tagihan_res)),
            "all_paid": bool(lunas_res > 0 and tagihan_res == 0),  # Flag untuk disable tombol TAGIHAN jika semua LUNAS
            "paused": self._timer_paused,
            "total": int(round(total)),
            "mode_member": bool(getattr(self, "mode_member", False)),
            "member_hp": getattr(self, "member_hp", None),
            "member_nama": getattr(self, "member_nama", None),
            "member_menit_pakai": (round((getattr(self, "member_detik_pakai", 0) or 0) / 60)
                                   if getattr(self, "mode_member", False) else None),
            "aktif": not self.sesi_kosong(),
        }

    # ── kontrol device (hub TV & socket warnet) ──────────────────────────
    def _hub_ok(self):
        return self.kind == "tv" and self.store.hub is not None and self.store.hub.running

    def _warnet_queue(self, cmd, reason, message, **extra):
        if self.kind != "warnet" or not self.store.warnet or not self.pc_id:
            return
        payload = {"reason": reason, "message": message}
        payload.update(extra)
        self.store.warnet.queue_pending_command(self.pc_id, cmd, **payload)
        self.store.set_pc_locked(self, cmd == "LOCK", reason, message)

    def _lock_detail(self, total):
        semua = {**self.store.menu_makanan, **self.store.menu_minuman}
        lunas_pesanan = getattr(self, "lunas_pesanan", None) or {}
        mak = [{"item": f"{qty}x {nm}", "harga": M.fmt_rp(semua.get(nm, 0) * qty),
                "lunas": bool(lunas_pesanan.get(nm, getattr(self, "paid", True)))}
               for nm, qty in self.pesanan_aktif.items() if nm in self.store.menu_makanan]
        minu = [{"item": f"{qty}x {nm}", "harga": M.fmt_rp(semua.get(nm, 0) * qty),
                 "lunas": bool(lunas_pesanan.get(nm, getattr(self, "paid", True)))}
                for nm, qty in self.pesanan_aktif.items() if nm in self.store.menu_minuman]
        lunas_now, tagihan_now = self.split_lunas_tagihan()
        sewa_lunas = all(
            (self.lunas_paket[i] if i < len(self.lunas_paket) else True)
            for i in range(len(self.daftar_paket_sesi or []) or 1))
        return {
            "meja": self.label,
            "sewa": " + ".join(self.daftar_paket_sesi) or (self.paket_aktif or "-"),
            "sewa_harga": M.fmt_rp(self.paket_harga_tetap),
            "sewa_lunas": bool(sewa_lunas),
            "lunas_total": M.fmt_rp(lunas_now),
            "tagihan_total": M.fmt_rp(tagihan_now),
            "makanan": mak,
            "minuman": minu,
            "fnb": M.fmt_rp(self.biaya_pesanan),
            "total": M.fmt_rp(self.total_setelah_diskon()),
        }


# ─────────────────────────────────────────────────────────────────────────
#  STORE — katalog, riwayat, cloud sync, timer (port AutoRentApp, tanpa tk)
# ─────────────────────────────────────────────────────────────────────────
class Store:
    def __init__(self):
        self._lock = threading.RLock()
        self.user = None
        self.role = None
        self.sesi_tv = {}      # nomor -> Sesi
        self.sesi_warnet = {}  # key -> Sesi
        self.riwayat_transaksi = []
        self.riwayat_meta = []
        self._pending_tx_uploads = []
        self.events = []               # event singkat untuk UI (habis, dll)
        self._version = 0
        self._tick_n = 0
        self._ticker = None
        self._fail_attempts = {}
        self._locked_until = {}
        self._member_fails = {}          # identifier member -> jumlah PIN salah
        self._member_locked_until = {}   # identifier member -> datetime lockout
        self._lic_cache = {"t": 0.0, "status": None}   # cache status lisensi (TTL 5 dtk)
        self._lic_restore_last = 0.0   # throttle adopsi lisensi cloud (1x/menit)
        self.hub = None                # TvWsHub (TV Android), diisi start_servers()
        self.warnet = None             # WarnetServerWeb (PC warnet), diisi start_servers()
        self.media = None              # TvMediaServer (media promosi TV), diisi start_servers()

    # ── katalog dari config (baca langsung tiap kali, seperti desktop) ───
    @property
    def menu_makanan(self):
        return M.ConfigManager.get("menu_makanan", {}) or {}

    @property
    def menu_minuman(self):
        return M.ConfigManager.get("menu_minuman", {}) or {}

    @property
    def stok(self):
        v = M.ConfigManager.get("stok", {}) or {}
        return v if isinstance(v, dict) else {}

    @property
    def stok_min(self):
        v = M.ConfigManager.get("stok_min", {}) or {}
        return v if isinstance(v, dict) else {}

    # ── stok: helper (paralel dgn main.py) ───────────────────────────────
    def _stok_map(self, nama):
        if nama in self.menu_makanan:
            return "makanan"
        if nama in self.menu_minuman:
            return "minuman"
        return None

    def _stok_get(self, nama):
        kat = self._stok_map(nama)
        if kat is None:
            return None
        m = (self.stok.get(kat) or {}) if isinstance(self.stok, dict) else {}
        if nama not in m or m[nama] is None:
            return None
        try:
            return max(0, int(m[nama]))
        except Exception:
            return None

    def _stok_validate(self, pesanan):
        """Blokir kalau qty pesanan melebihi stok tersisa (raise ValueError)."""
        for nama, qty in (pesanan or {}).items():
            sisa = self._stok_get(nama)
            if sisa is None:
                continue
            if int(qty or 0) > sisa:
                raise ValueError(
                    f"Stok '{nama}' tidak mencukupi: tersedia {sisa}, diminta {int(qty or 0)}.")

    def _stok_terapkan(self, delta):
        """Kurangi/kembalikan stok (delta > 0 = kurangi). Item tanpa entri diabaikan."""
        if not delta:
            return
        try:
            def _mut(cfg):
                stok = cfg.get("stok", {}) or {}
                if not isinstance(stok, dict):
                    stok = {}
                for nama, d in delta.items():
                    d = int(d or 0)
                    if d == 0:
                        continue
                    kat = self._stok_map(nama)
                    if kat is None:
                        continue
                    if not isinstance(stok.get(kat), dict):
                        stok[kat] = {}
                    if nama not in stok[kat]:
                        continue
                    try:
                        cur = max(0, int(stok[kat].get(nama, 0)))
                    except Exception:
                        cur = 0
                    stok[kat][nama] = max(0, cur - d)
                cfg["stok"] = stok
                return cfg
            M.ConfigManager.update(_mut)
        except Exception:
            pass

    def _warnet_group_names(self):
        return set((M.ConfigManager.get("grup_tarif_warnet", {}) or {}).keys())

    def paket_data(self, nama_grup, for_warnet=False):
        """Port main.py AutoRentApp.get_paket_data."""
        cfg = M.ConfigManager.load()
        grup_tarif = cfg.get("grup_tarif", {}) or {}
        warnet_map = cfg.get("grup_tarif_warnet", {}) or {}

        def _norm(grp):
            if isinstance(grp, dict):
                return {k: {"harga": int(v.get("harga", 0)), "menit": int(v.get("menit", 0))}
                        for k, v in grp.items()}
            return {}

        if for_warnet:
            if nama_grup:
                k_found = None
                if nama_grup in warnet_map:
                    k_found = nama_grup
                else:
                    lower_map = {k.lower(): k for k in warnet_map.keys()}
                    if isinstance(nama_grup, str):
                        k_found = lower_map.get(nama_grup.lower())
                if k_found is not None:
                    return _norm(warnet_map[k_found])
                if nama_grup in grup_tarif and nama_grup not in self._warnet_group_names():
                    return _norm(grup_tarif[nama_grup])
            if "Warnet" in warnet_map:
                return _norm(warnet_map["Warnet"])
            if warnet_map:
                return _norm(next(iter(warnet_map.values())))
            return {}
        warnet_only = self._warnet_group_names()
        if nama_grup and nama_grup in grup_tarif and nama_grup not in warnet_only:
            return _norm(grup_tarif[nama_grup])
        if M.NAMA_GRUP_DEFAULT in grup_tarif:
            return _norm(grup_tarif[M.NAMA_GRUP_DEFAULT])
        if grup_tarif:
            return _norm(next(iter(grup_tarif.values())))
        return _norm(M._PAKET_STANDAR)

    def daftar_grup_tv(self):
        cfg = M.ConfigManager.load()
        warnet_only = set((cfg.get("grup_tarif_warnet", {}) or {}).keys())
        return [g for g in (cfg.get("grup_tarif", {}) or {}).keys() if g not in warnet_only] or [M.NAMA_GRUP_DEFAULT]

    def daftar_grup_warnet(self):
        cfg = M.ConfigManager.load()
        warnet_map = cfg.get("grup_tarif_warnet", {}) or {}
        return list(warnet_map.keys()) or [M.NAMA_GRUP_DEFAULT]

    # ── kartu dari config ───────────────────────────────────────────────
    def load_kartu(self):
        with self._lock:
            cfg = M.ConfigManager.load()
            self.sesi_tv = {}
            self.sesi_warnet = {}
            for i, item in enumerate((cfg.get("daftar_tv", []) or []), start=1):
                try:
                    ip = str(item.get("ip", "")).strip()
                    nama = str(item.get("nama", "")).strip() or f"TV {i}"
                    nama_grup = str(item.get("nama_grup", "")).strip() or M.NAMA_GRUP_DEFAULT
                    if not ip:
                        continue
                    self.sesi_tv[i] = Sesi(self, "tv", i, nama, nama_grup, ip=ip)
                    self.sesi_tv[i].plug = item.get("plug") or None
                except Exception as e:
                    _LOGGER.warning("Gagal muat TV %s: %s", item, e)
            for i, item in enumerate((cfg.get("daftar_warnet", []) or []), start=1):
                try:
                    nama = str(item.get("nama", "")).strip() or f"PC {i}"
                    nama_grup = str(item.get("nama_grup", "")).strip() or M.NAMA_GRUP_DEFAULT
                    pc_id = item.get("pc_id")
                    key = str(pc_id) if pc_id else str(i)
                    self.sesi_warnet[key] = Sesi(self, "warnet", i, nama, nama_grup,
                                                 ip=item.get("pc_ip"), pc_id=pc_id)
                except Exception as e:
                    _LOGGER.warning("Gagal muat warnet %s: %s", item, e)

    def all_sesi(self):
        return list(self.sesi_tv.values()) + list(self.sesi_warnet.values())

    def get_sesi(self, kind, key):
        if kind == "warnet":
            return self.sesi_warnet.get(str(key))
        return self.sesi_tv.get(int(key))

    # ── riwayat (port _save_riwayat / _load_riwayat / _backfill_cloud_ids) ─
    def _format_riwayat_row(self, waktu, tv_label, paket_nama, pesanan_dict, total_int,
                            pesanan_total=None, diskoni=0, diskoni_mode="nominal",
                            paid=True, kasir=None, lunas_total=None, tagihan_total=None):
        if pesanan_total is None:
            all_menu = {**self.menu_makanan, **self.menu_minuman}
            pesanan_total = sum(all_menu.get(nm, 0) * qty
                                for nm, qty in (pesanan_dict.items() if isinstance(pesanan_dict, dict) else []))
        paket_harga = total_int - pesanan_total
        if paket_harga < 0:
            paket_harga = 0
        paket_tampil = f"{paket_nama} ({M.fmt_rp(paket_harga)})" if paket_harga > 0 else paket_nama
        pesanan_str = ", ".join(f"{nm}×{qty}" for nm, qty in
                                (pesanan_dict.items() if isinstance(pesanan_dict, dict) else [])) or "—"
        pesanan_tampil = f"{pesanan_str} ({M.fmt_rp(pesanan_total)})" if pesanan_str != "—" else "—"
        if diskoni > 0:
            diskon_tampil = f"{diskoni}%" if diskoni_mode == "persen" else M.fmt_rp(diskoni)
        else:
            diskon_tampil = "—"
        if lunas_total is not None and tagihan_total is not None \
                and int(lunas_total or 0) > 0 and int(tagihan_total or 0) > 0:
            status_str = (f"🔀 Lunas {M.fmt_rp(lunas_total)} · "
                          f"Tagihan {M.fmt_rp(tagihan_total)}")
        else:
            status_str = "✅ Lunas" if paid else "⏳ Belum Lunas"
        return (waktu, kasir or self.user, tv_label, paket_tampil, pesanan_tampil,
                diskon_tampil, M.fmt_rp(total_int), status_str)

    def save_riwayat(self):
        try:
            data = {
                "riwayat_transaksi": [list(r) for r in self.riwayat_transaksi],
                "riwayat_meta": self.riwayat_meta,
            }
            with open(M.RIWAYAT_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _LOGGER.warning("Gagal simpan riwayat: %s", e)

    def load_riwayat(self):
        self.riwayat_transaksi = []
        self.riwayat_meta = []
        if not os.path.exists(M.RIWAYAT_FILE):
            return
        try:
            with open(M.RIWAYAT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            rows = data.get("riwayat_transaksi", [])
            metas = data.get("riwayat_meta", [])
            padded = []
            for idx, r in enumerate(rows):
                rlist = list(r)
                while len(rlist) < 7:
                    rlist.append("—")
                paid = metas[idx].get('paid', True) if idx < len(metas) else True
                lt = metas[idx].get('lunas_total') if idx < len(metas) else None
                tg = metas[idx].get('tagihan_total') if idx < len(metas) else None
                if lt is not None and tg is not None \
                        and int(lt or 0) > 0 and int(tg or 0) > 0:
                    status_str = (f"🔀 Lunas {M.fmt_rp(lt)} · "
                                  f"Tagihan {M.fmt_rp(tg)}")
                else:
                    status_str = "✅ Lunas" if paid else "⏳ Belum Lunas"
                while len(rlist) < 8:
                    rlist.append("—")
                rlist[7] = status_str
                padded.append(tuple(rlist))
            self.riwayat_transaksi = padded
            self.riwayat_meta = metas
            self._backfill_cloud_ids()
        except Exception as e:
            _LOGGER.warning("Gagal muat riwayat: %s", e)

    def _backfill_cloud_ids(self):
        import hashlib
        changed = False
        for i, meta in enumerate(self.riwayat_meta):
            if not isinstance(meta, dict):
                continue
            if meta.get("cloud_id"):
                continue
            try:
                row = self.riwayat_transaksi[i]
                stable = hashlib.md5(f"{tuple(row)}".encode("utf-8")).hexdigest()[:12]
                meta["cloud_id"] = f"tx_{stable}"
                meta.setdefault("paket_raw", "")
                meta.setdefault("pesanan", {})
                changed = True
            except Exception:
                continue
        if changed:
            self.save_riwayat()

    # ── catat transaksi (port _catat_transaksi tanpa tkinter) ───────────
    def catat(self, tv_label, paket, pesanan, total, source='tv', diskoni=0, diskoni_mode="nominal",
              paid=None, sesi=None):
        waktu = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        pesanan = pesanan or {}
        src = source if source in ('tv', 'warnet') else 'tv'
        if paid is not None:
            paid_bool = bool(paid)
        elif hasattr(self, 'paid'):
            paid_bool = bool(self.paid)
        else:
            paid_bool = True

        all_menu = {**self.menu_makanan, **self.menu_minuman}
        pesanan_total = sum(all_menu.get(nm, 0) * qty
                            for nm, qty in (pesanan.items() if isinstance(pesanan, dict) else []))
        try:
            total_int = int(total)
        except Exception:
            total_int = pesanan_total
        paket_harga = total_int - pesanan_total
        if paket_harga < 0:
            paket_harga = 0

        lunas_res = tagihan_res = None
        if sesi is not None:
            try:
                lunas_res, tagihan_res = sesi.split_lunas_tagihan()
            except Exception:
                pass

        row = self._format_riwayat_row(waktu, tv_label, paket, pesanan, total_int,
                                       pesanan_total, diskoni, diskoni_mode, paid=paid_bool,
                                       lunas_total=lunas_res, tagihan_total=tagihan_res)
        with self._lock:
            self.riwayat_transaksi.append(row)
            cloud_id = f"tx_{int(time.time() * 1000)}"
            self.riwayat_meta.append({
                'source': src, 'paket_harga': paket_harga, 'pesanan_total': pesanan_total,
                'total': total_int, 'diskoni': diskoni, 'diskoni_mode': diskoni_mode,
                'paid': paid_bool, 'cloud_id': cloud_id, 'paket_raw': str(paket or ""),
                'lunas_total': lunas_res, 'tagihan_total': tagihan_res,
                'pesanan': {str(k): int(v) for k, v in
                            (pesanan.items() if isinstance(pesanan, dict) else [])},
            })
            idx = len(self.riwayat_transaksi) - 1

            try:
                tx_cloud = self._build_tx_cloud(row, self.riwayat_meta[idx])
                if tx_cloud:
                    self._pending_tx_uploads.append(tx_cloud)
                    threading.Thread(target=self._flush_cloud_uploads, daemon=True).start()
            except Exception as e:
                _LOGGER.warning("Gagal siapkan upload: %s", e)
            self.save_riwayat()
        return idx

    def _refresh_paid_row(self, idx):
        try:
            row = list(self.riwayat_transaksi[idx])
            meta = self.riwayat_meta[idx] if idx < len(self.riwayat_meta) else {}
            lt = meta.get('lunas_total')
            tg = meta.get('tagihan_total')
            if lt is not None and tg is not None \
                    and int(lt or 0) > 0 and int(tg or 0) > 0:
                status = (f"🔀 Lunas {M.fmt_rp(lt)} · "
                          f"Tagihan {M.fmt_rp(tg)}")
            else:
                status = ("✅ Lunas" if meta.get('paid', True)
                          else "⏳ Belum Lunas")
            row[7] = status
            self.riwayat_transaksi[idx] = tuple(row)
        except Exception:
            pass

    def update_row_meta(self, sesi, total_int):
        """Update baris riwayat + meta + re-upload cloud setelah detail berubah
        (tambah pesanan, tambah paket, timer habis). Port dari blok update di main.py."""
        with self._lock:
            idx = sesi._last_transaction_item
            if idx is None or not (0 <= idx < len(self.riwayat_transaksi)):
                return
            if idx >= len(self.riwayat_meta):
                return
            waktu = self.riwayat_transaksi[idx][0]
            try:
                lunas_res, tagihan_res = sesi.split_lunas_tagihan()
            except Exception:
                lunas_res, tagihan_res = None, None
            updated_row = self._format_riwayat_row(waktu, sesi.label, sesi.paket_aktif,
                                                   sesi.pesanan_aktif, total_int,
                                                   paid=sesi.paid, kasir=self.user,
                                                   lunas_total=lunas_res,
                                                   tagihan_total=tagihan_res)
            self.riwayat_transaksi[idx] = updated_row
            meta = self.riwayat_meta[idx]
            all_menu = {**self.menu_makanan, **self.menu_minuman}
            pesanan_total_baru = sum(all_menu.get(nm, 0) * qty for nm, qty in sesi.pesanan_aktif.items())
            paket_harga_baru = total_int - pesanan_total_baru
            if paket_harga_baru < 0:
                paket_harga_baru = 0
            meta['paket_harga'] = paket_harga_baru
            meta['pesanan_total'] = pesanan_total_baru
            meta['total'] = total_int
            meta['diskoni'] = sesi.diskoni
            meta['diskoni_mode'] = sesi.diskoni_mode
            meta['pesanan'] = {str(k): int(v) for k, v in sesi.pesanan_aktif.items()}
            meta['lunas_total'] = lunas_res
            meta['tagihan_total'] = tagihan_res
            threading.Thread(target=self._upsert_tx_cloud_from_index, args=(idx,), daemon=True).start()
            self.save_riwayat()

    # ── cloud (port _build_tx_cloud / _flush_cloud_uploads / _upsert) ────
    def _resolve_license_user(self):
        if (self.role or "") != "kasir":
            return self.user or ""
        try:
            users = M.ConfigManager.get("users", {}) or {}
            u = users.get(self.user) or {}
            if isinstance(u, dict):
                return u.get("admin_utama") or self.user or ""
            return self.user or ""
        except Exception:
            return self.user or ""

    def _build_tx_cloud(self, row, meta):
        try:
            if not isinstance(meta, dict):
                return None
            cloud_id = meta.get("cloud_id") or ""
            if not cloud_id:
                return None
            waktu_str = str(row[0] if len(row) > 0 else "") or ""
            if len(waktu_str) >= 16:
                waktu_iso = waktu_str[:16].replace(" ", "T") + ":00Z"
            else:
                waktu_iso = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
            total = int(meta.get("total", 0))
            paket_harga = int(meta.get("paket_harga", 0) or 0)
            if paket_harga <= 0:
                paket_harga = max(0, total - int(meta.get("pesanan_total", 0) or 0))
            pesanan_raw = meta.get("pesanan") or {}
            pesanan = {}
            if isinstance(pesanan_raw, dict):
                for k, v in pesanan_raw.items():
                    try:
                        pesanan[str(k)] = int(v)
                    except Exception:
                        pesanan[str(k)] = 0
            all_menu = {**self.menu_makanan, **self.menu_minuman}
            pesananHarga = {}
            for nm, qty in pesanan.items():
                try:
                    pesananHarga[nm] = int(all_menu.get(nm, 0)) * qty
                except Exception:
                    pesananHarga[nm] = 0
            return {
                "id": cloud_id,
                "waktu": waktu_iso,
                "kasir": str(row[1] if len(row) > 1 else "") or (self.user or ""),
                "kota": str(row[2] if len(row) > 2 else "") or "",
                "paket": str(meta.get("paket_raw") or ""),
                "total": total,
                "pesanan": pesanan,
                "paketHarga": paket_harga,
                "pesananHarga": pesananHarga,
                "tvJenisPs": "TV" if meta.get("source") == "tv" else "PC",
            }
        except Exception:
            return None

    def _flush_cloud_uploads(self):
        try:
            if not self._pending_tx_uploads:
                return
            target = self._resolve_license_user()
            if not target:
                self._pending_tx_uploads.clear()
                return
            pending = list(self._pending_tx_uploads)
            fc = FirestoreClient()
            ok = fc.push_transactions(target, pending)
            if ok:
                sent_ids = {t.get("id") for t in pending}
                self._pending_tx_uploads = [
                    t for t in self._pending_tx_uploads if t.get("id") not in sent_ids]
        except Exception as e:
            _LOGGER.warning("Gagal upload transaksi ke cloud: %s", e)

    def _upsert_tx_cloud_from_index(self, idx):
        try:
            if idx is None or not (0 <= idx < len(self.riwayat_transaksi)):
                return
            if idx >= len(self.riwayat_meta):
                return
            row = self.riwayat_transaksi[idx]
            meta = self.riwayat_meta[idx]
            tx = self._build_tx_cloud(row, meta)
            if not tx:
                return
            target = self._resolve_license_user()
            if not target:
                return
            fc = FirestoreClient()
            ok = fc.upsert_transactions(target, [tx])
            if ok:
                _LOGGER.info("Transaksi %s di-update di cloud", tx.get("id"))
        except Exception as e:
            _LOGGER.warning("Gagal update transaksi cloud: %s", e)

    def _cloud_retry_tick(self):
        while True:
            time.sleep(30)
            try:
                if self._pending_tx_uploads:
                    threading.Thread(target=self._flush_cloud_uploads, daemon=True).start()
            except Exception:
                pass

    # ── timer service (port TimerService) ───────────────────────────────
    def start_ticker(self):
        self._running = True
        self._ticker = threading.Thread(target=self._tick_loop, daemon=True, name="WebTimer")
        self._ticker.start()
        threading.Thread(target=self._cloud_retry_tick, daemon=True, name="WebCloudRetry").start()

    def _tick_loop(self):
        while True:
            time.sleep(1.0)
            try:
                self._tick()
            except Exception as e:
                _LOGGER.warning("Tick error: %s", e)

    def _tick(self):
        with self._lock:
            self._tick_n += 1
            for s in self.all_sesi():
                try:
                    s.tick()
                except Exception:
                    pass
            hub = self.hub
            if hub and hub.running:
                for s in self.sesi_tv.values():
                    if s.paket_aktif and not s._timer_paused:
                        try:
                            total = s.snapshot().get("total", 0)
                            lunas_now, tagihan_now = s.split_lunas_tagihan()
                            nama_member = s.member_nama if getattr(s, "mode_member", False) else None
                            if s.is_bebas:
                                hub.send_update_total(s.label, total,
                                                      lunas_total=lunas_now, tagihan_total=tagihan_now)
                            else:
                                hub.send_sync_timer(s.label, s.sisa_waktu, total,
                                                    lunas_total=lunas_now, tagihan_total=tagihan_now,
                                                    nama_member=nama_member)
                        except Exception:
                            pass
            if self._tick_n % 30 == 0:
                self._sync_timer_state()
                self._tv_status_and_idle_check()

    def _plug_set(self, target, on):
        """Nyalakan/matikan smart plug lampu LED mengikuti status TV.

        Prioritas: plug per-TV (field 'plug' di daftar_tv) -> lalu map
        'smart_plugs' keyed by label TV. Setiap TV boleh punya plug &
        IP berbeda. target boleh objek Sesi (.label/.plug) atau string label.
        """
        try:
            label = target.label if hasattr(target, "label") else str(target)
            plug = None
            if hasattr(target, "plug") and target.plug:
                plug = target.plug
            if not plug:
                cfg_map = M.ConfigManager.get("smart_plugs", {}) or {}
                plug = cfg_map.get(label)
            if not plug:
                return
            mgr = smart_plug.get_manager()
            ok, msg = mgr.set_state(plug, on)
            applog(f"[PLUG] {label} -> {'NYALA' if on else 'MATI'} : {msg}")
        except Exception as e:
            _LOGGER.warning("Plug control error: %s", e)

    def _tv_status_and_idle_check(self):
        """Port _tv_idle_check (main.py:7401): log status TV + auto cut-off 10 menit.
        Setiap 30 dtk: TV nyala tanpa sesi aktif dihitung (idle_on_seconds);
        lewat ambang (first 600s, lalu eskalasi 300s) -> tidurkan lewat _tv_sleep_runner.

        Smart plug (lampu LED) dipantau DI SINI agar mengikuti status TV walau
        fitur auto-off dimatikan: saat layar berubah ON -> plug NYALA,
        saat berubah OFF -> plug MATI.
        """
        try:
            cfg = M.ConfigManager.get("tv_auto_off", {}) or {}
            enabled = cfg.get("enabled", True)
            first_sec = int(cfg.get("first_idle_sec", 600) or 600)
            escalated_sec = int(cfg.get("escalated_idle_sec", 300) or 300)
        except Exception:
            enabled, first_sec, escalated_sec = True, 600, 300
        hub = self.hub
        for s in list(self.sesi_tv.values()):
            try:
                st = hub.get_screen_state(s.label) if (hub and hub.running) else None
                cur = {True: "ONLINE", False: "OFFLINE"}.get(st, "TIDAK DIKETAHUI")
                if cur != s._tv_status_last:
                    s._tv_status_last = cur
                    applog(f"[TV STATUS] {s.label} | {cur}")
                    # --- SMART PLUG: ikuti status TV (ON -> NYALA, OFF -> MATI) ---
                    if st is True:
                        self._plug_set(s, True)
                    elif st is False:
                        self._plug_set(s, False)
                if st is None:
                    continue
                if not enabled:
                    continue
                if not st:
                    s.idle_on_seconds = 0
                    s.idle_escalated = False
                    continue
                if not s.sesi_kosong():
                    s.idle_on_seconds = 0
                    s.idle_escalated = False
                    continue
                s.idle_on_seconds += 30
                threshold = escalated_sec if s.idle_escalated else first_sec
                if s.idle_on_seconds >= threshold:
                    s.idle_on_seconds = 0
                    s.idle_escalated = True
                    alasan = f"auto off setelah {threshold // 60} menit hidup tanpa sesi"
                    applog(f"[AUTO OFF] {s.label} | {alasan}")
                    if s.ip:
                        port = int(getattr(s, "port", 0) or 0)
                        threading.Thread(
                            target=_tv_sleep_runner,
                            args=(s.ip, port, s.label, s.timer_key()),
                            kwargs={"alasan": alasan, "delay": 0},
                            daemon=True, name=f"AutoOff-{s.label}").start()
            except Exception as e:
                _LOGGER.warning("TV idle check %s error: %s", s.label, e)

    def _sync_timer_state(self):
        try:
            state = {"tv": {}, "warnet": {}}
            for s in self.sesi_tv.values():
                if s.paket_aktif and s.sisa_waktu > 0:
                    state["tv"][s.timer_key()] = self._sesi_state_dict(s)
            for s in self.sesi_warnet.values():
                if s.paket_aktif and s.sisa_waktu > 0:
                    state["warnet"][s.timer_key()] = self._sesi_state_dict(s)
            M.ConfigManager.update(lambda cfg: (
                cfg.__setitem__("timer_state", state) or
                cfg.__setitem__("timer_state_updated", datetime.datetime.now().isoformat()) or cfg))
        except Exception as e:
            _LOGGER.warning("Sync timer state error: %s", e)

    @staticmethod
    def _sesi_state_dict(s):
        return {
            "label": s.label,
            "paket": s.paket_aktif,
            "sisa_waktu": s.sisa_waktu,
            "is_bebas": s.is_bebas,
            "waktu_mulai": s.waktu_mulai.isoformat() if s.waktu_mulai else None,
            "biaya_pesanan": s.biaya_pesanan,
            "paket_harga_tetap": s.paket_harga_tetap,
            "pesanan_aktif": dict(s.pesanan_aktif),
            "daftar_paket_sesi": list(s.daftar_paket_sesi),
            "menit_dipakai_awal": s.menit_dipakai_awal,
            "diskoni": s.diskoni,
            "diskoni_mode": s.diskoni_mode,
            "paid": s.paid,
            "mode_member": bool(getattr(s, "mode_member", False)),
            "member_hp": getattr(s, "member_hp", None),
            "member_nama": getattr(s, "member_nama", None),
            "member_detik_pakai": int(getattr(s, "member_detik_pakai", 0) or 0),
        }

    def restore_timer_state(self):
        """Port TimerService.restore_timer_state: pulihkan sesi aktif dari config.
        Baris riwayat yang masih terbuka dicocokkan agar tidak duplikat."""
        try:
            cfg = M.ConfigManager.load()
            state = cfg.get("timer_state", {}) or {}
            tv_state = state.get("tv", {}) or {}
            warnet_state = state.get("warnet", {}) or {}
            for s in self.sesi_tv.values():
                d = tv_state.get(s.timer_key())
                if d and d.get("paket") and d.get("sisa_waktu", 0) > 0:
                    self._apply_restore(s, d)
            for s in self.sesi_warnet.values():
                d = warnet_state.get(s.timer_key())
                if d and d.get("paket") and d.get("sisa_waktu", 0) > 0:
                    self._apply_restore(s, d)
        except Exception as e:
            _LOGGER.warning("Restore timer state error: %s", e)

    def _apply_restore(self, s, d):
        s.paket_aktif = d["paket"]
        s.sisa_waktu = d.get("sisa_waktu", 0)
        s.is_bebas = d.get("is_bebas", False)
        s.biaya_pesanan = d.get("biaya_pesanan", 0)
        s.paket_harga_tetap = d.get("paket_harga_tetap", 0)
        s.pesanan_aktif = dict(d.get("pesanan_aktif", {}))
        s.daftar_paket_sesi = list(d.get("daftar_paket_sesi", []))
        s.menit_dipakai_awal = d.get("menit_dipakai_awal", 0)
        s.diskoni = d.get("diskoni", 0)
        s.diskoni_mode = d.get("diskoni_mode", "nominal")
        s.paid = d.get("paid", True)
        s.mode_member = bool(d.get("mode_member", False))
        s.member_hp = d.get("member_hp")
        s.member_nama = d.get("member_nama")
        s.member_detik_pakai = int(d.get("member_detik_pakai", 0) or 0)
        if d.get("waktu_mulai"):
            try:
                s.waktu_mulai = datetime.datetime.fromisoformat(d["waktu_mulai"])
            except Exception:
                s.waktu_mulai = datetime.datetime.now()
        s._last_transaction_item = self._find_open_row(s)

    def _find_open_row(self, s):
        """Cari baris riwayat hari ini yang masih 'terbuka' untuk sesi ini
        (label & paket sama) supaya update berikutnya tidak mencatat ulang."""
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        paket_raw = s.paket_aktif if not s.is_bebas else "Main Bebas"
        src = s.kind
        found = None
        for i in range(len(self.riwayat_meta)):
            try:
                m = self.riwayat_meta[i]
                row = self.riwayat_transaksi[i]
                if m.get("source") != src:
                    continue
                if not str(row[0] or "").startswith(today):
                    continue
                if m.get("paket_raw") != paket_raw:
                    continue
                if row[2] != s.label:
                    continue
                found = i
            except Exception:
                continue
        return found

    def notify(self, evtype, snap=None, **extra):
        if isinstance(snap, dict):
            label = snap.get("label", "")
            total = snap.get("total", 0)
        else:
            label = snap or ""
            total = 0
        ev = {"t": time.time(), "type": evtype, "label": label, "total": total}
        ev.update(extra)
        self.events.append(ev)
        self._version += 1
        if len(self.events) > 50:
            self.events = self.events[-50:]

    # ── auth ────────────────────────────────────────────────────────────
    def check_login(self, username, password):
        username = str(username or "").strip().lower()
        if not username or not password:
            return None, "Username dan password wajib diisi."
        locked_until = self._locked_until.get(username)
        if locked_until and datetime.datetime.now() < locked_until:
            sisa = int((locked_until - datetime.datetime.now()).total_seconds())
            return None, f"⛔ Terkunci — coba lagi dalam {sisa}s"
        users = M.ConfigManager.get("users", {}) or {}
        if not isinstance(users, dict):
            users = {}
        u = users.get(username)
        pw_hash = ""
        if isinstance(u, dict):
            pw_hash = u.get("password_enc") or u.get("password", "") or ""
        if isinstance(u, dict) and u and M.verify_password(password, pw_hash):
            self._fail_attempts.pop(username, None)
            self.user = username
            self.role = u.get("role", "kasir")
            self._sync_timer_state()
            self.load_kartu()
            self.load_riwayat()
            self.restore_timer_state()
            return {"username": username, "role": self.role,
                    "admin_utama": u.get("admin_utama", "")}, None
        self._fail_attempts[username] = self._fail_attempts.get(username, 0) + 1
        if self._fail_attempts[username] >= 5:
            self._locked_until[username] = datetime.datetime.now() + datetime.timedelta(minutes=1)
            self._fail_attempts[username] = 0
            return None, "⛔ 5x salah — terkunci 1 menit"
        return None, f"✖ Username/Password salah ({self._fail_attempts[username]}/5)"

    def google_login(self, id_token):
        """Masuk via akun Google (token dari Firebase Auth SDK di browser).
        Verifikasi token (accounts:lookup) lalu petakan email -> username
        Firestore — persis seperti _login_google di aplikasi desktop."""
        import requests as _requests
        try:
            resp = _requests.post(
                f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={FIREBASE_API_KEY}",
                json={"idToken": id_token}, timeout=15)
            data = resp.json()
        except Exception as e:
            return None, f"Gagal verifikasi token Google: {e}"
        users_arr = data.get("users", []) if isinstance(data, dict) else []
        if not users_arr:
            return None, "Token Google tidak valid atau sudah kedaluwarsa."
        email = users_arr[0].get("email", "")
        if not email:
            return None, "Akun Google tidak memiliki email."
        uname = self._resolve_username_from_email(email)
        if not uname:
            return None, (f"Email {email} belum terdaftar di RR Billing Pro. "
                          "Aktivasi akun dulu lewat aplikasi Android / hubungi admin.")
        self._fail_attempts.pop(uname, None)
        self.user = uname
        self.role = "admin"
        self._sync_timer_state()
        self.load_kartu()
        self.load_riwayat()
        self.restore_timer_state()
        return {"username": uname, "role": "admin", "admin_utama": ""}, None

    def _resolve_username_from_email(self, email):
        """Port _login_google (main.py): cari billingps_users by email,
        dukung prefix _user_ + licenseStatus aktif, lalu fallback."""
        try:
            fc = FirestoreClient()
            fb_results = fc.query_where_equal("billingps_users", "email", email)
            for r in fb_results or []:
                fb_uname = r.get("_id", "")
                if str(fb_uname).startswith("_user_"):
                    bare = fb_uname[6:]
                    bare_doc = fc.get_user_doc(bare)
                    if bare_doc and bare_doc.get("licenseStatus", {}).get("status") == "active":
                        return bare
                elif (r.get("licenseStatus") or {}).get("status") == "active":
                    return fb_uname
        except Exception as e:
            _LOGGER.warning("Google: cari email di Firestore gagal: %s", e)
        try:
            fc = FirestoreClient()
            return fc.find_username_by_email(email)
        except Exception as e:
            _LOGGER.warning("Google: find_username_by_email gagal: %s", e)
            return None

    def register(self, username, password, role="admin"):
        username = str(username or "").strip().lower()
        if not username or not M.is_valid_username(username):
            return None, "Username harus 4-20 karakter alfanumerik, titik, atau garis bawah."
        if len(password) < 6:
            return None, "Password minimal 6 karakter."
        users = M.ConfigManager.get("users", {}) or {}
        if not isinstance(users, dict):
            users = {}
        if username in users:
            return None, "Username sudah terdaftar."
        users[username] = {
            "password_enc": M.hash_password(password),
            "role": role,
            "admin_utama": "" if role == "admin" else (users and next(iter(users))),
        }
        cfg = M.ConfigManager.load()
        cfg["users"] = users
        M.ConfigManager.save(cfg)
        return {"username": username, "role": role}, None

    def create_kasir(self, username, password, admin_utama):
        username = str(username or "").strip().lower()
        admin_utama = str(admin_utama or "").strip().lower()
        if not username or not M.is_valid_username(username):
            return None, "Username kasir tidak valid."
        if len(password) < 6:
            return None, "Password minimal 6 karakter."
        users = M.ConfigManager.get("users", {}) or {}
        if not isinstance(users, dict):
            users = {}
        if username in users:
            return None, "Username sudah terdaftar."
        users[username] = {
            "password_enc": M.hash_password(password),
            "role": "kasir",
            "admin_utama": admin_utama or next(iter(users), ""),
        }
        cfg = M.ConfigManager.load()
        cfg["users"] = users
        M.ConfigManager.save(cfg)
        return {"username": username, "role": "kasir"}, None

    def list_users(self):
        users = M.ConfigManager.get("users", {}) or {}
        return [{"username": u, "role": x.get("role", "kasir") if isinstance(x, dict) else "kasir",
                 "admin_utama": x.get("admin_utama", "") if isinstance(x, dict) else ""}
                for u, x in users.items()] if isinstance(users, dict) else []

    # ── member (saldo waktu) ────────────────────────────────────────────
    _JENIS_MEMBER = ("VIP", "PS3", "PS4")
    _DEFAULT_TOPUP = [
        {"nama": "1 Jam", "menit": 60, "harga": 5000},
        {"nama": "2 Jam", "menit": 120, "harga": 9000},
        {"nama": "5 Jam", "menit": 300, "harga": 20000},
    ]

    def _members_dict(self):
        m = M.ConfigManager.get("members", {})
        return m if isinstance(m, dict) else {}

    def list_members(self, q=""):
        q = (q or "").strip().lower()
        out = []
        for hp, m in self._members_dict().items():
            if not isinstance(m, dict):
                continue
            if q and q not in hp.lower() and q not in str(m.get("nama", "")).lower():
                continue
            out.append({
                "hp": hp,
                "nama": str(m.get("nama", "")),
                "jenis": str(m.get("jenis", "VIP") or "VIP").strip().upper(),
                "saldo_menit": int(m.get("saldo_menit", 0) or 0),
                "dibuat": m.get("dibuat", ""),
                "terakhir_aktif": m.get("terakhir_aktif", ""),
                "jumlah_isi": len(m.get("riwayat_isi", []) or []),
            })
        out.sort(key=lambda x: x["nama"].lower())
        return out

    def create_member(self, nama, hp, pin, jenis="VIP"):
        nama = str(nama or "").strip()
        hp = str(hp or "").strip()
        pin = str(pin or "").strip()
        jenis = str(jenis or "VIP").strip().upper()
        if not nama:
            return None, "Nama member wajib diisi."
        if not hp.isdigit() or not (8 <= len(hp) <= 15):
            return None, "No HP/WA tidak valid (8–15 digit angka)."
        if not (pin.isdigit() and 4 <= len(pin) <= 6):
            return None, "PIN harus 4–6 digit angka."
        if jenis not in self._JENIS_MEMBER:
            return None, "Jenis member harus salah satu dari: " + ", ".join(self._JENIS_MEMBER) + "."
        members = self._members_dict()
        if hp in members:
            return None, f"No HP {hp} sudah terdaftar."
        members[hp] = {
            "nama": nama,
            "jenis": jenis,
            "pin_enc": M.hash_password(pin),
            "saldo_menit": 0,
            "dibuat": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "terakhir_aktif": "",
            "riwayat_isi": [],
        }

        def _mut(cfg):
            cfg["members"] = members
            return cfg

        M.ConfigManager.update(_mut)
        applog(f"[MEMBER DAFTAR] {nama} ({hp}) | jenis={jenis} | kasir={self.user}")
        return {"hp": hp, "nama": nama, "jenis": jenis}, None

    def update_member(self, hp, nama=None, pin=None, jenis=None):
        hp = str(hp or "").strip()
        members = self._members_dict()
        m = members.get(hp)
        if not isinstance(m, dict):
            return None, "Member tidak ditemukan."
        changed = []
        if nama is not None and str(nama).strip() and str(nama).strip() != m.get("nama"):
            m["nama"] = str(nama).strip()
            changed.append(f"nama->{m['nama']}")
        if jenis is not None and str(jenis).strip():
            jenis = str(jenis).strip().upper()
            if jenis not in self._JENIS_MEMBER:
                return None, "Jenis member harus salah satu dari: " + ", ".join(self._JENIS_MEMBER) + "."
            if jenis != m.get("jenis"):
                m["jenis"] = jenis
                changed.append(f"jenis->{jenis}")
        if pin:
            pin = str(pin).strip()
            if not (pin.isdigit() and 4 <= len(pin) <= 6):
                return None, "PIN harus 4–6 digit angka."
            m["pin_enc"] = M.hash_password(pin)
            changed.append("pin-reset")

        def _mut(cfg):
            cfg["members"] = members
            return cfg

        M.ConfigManager.update(_mut)
        if changed:
            applog(f"[MEMBER EDIT] {hp} | {', '.join(changed)} | admin={self.user}")
        return {"hp": hp, "nama": m.get("nama")}, None

    def delete_member(self, hp):
        hp = str(hp or "").strip()
        members = self._members_dict()

        def _mut(cfg):
            members.pop(hp, None)
            cfg["members"] = members
            return cfg

        if hp not in members:
            return None, "Member tidak ditemukan."
        M.ConfigManager.update(_mut)
        applog(f"[MEMBER HAPUS] {hp} | admin={self.user}")
        return {"ok": True}, None

    def verify_member(self, identifier, pin):
        """Verifikasi member by No HP atau Nama + PIN. Rate-limit 5x salah →
        kunci 1 menit (pola sama dengan login kasir)."""
        identifier = str(identifier or "").strip()
        pin = str(pin or "").strip()
        if not identifier or not pin:
            return None, "Nama/No HP dan PIN wajib diisi."
        locked_until = self._member_locked_until.get(identifier)
        if locked_until and datetime.datetime.now() < locked_until:
            sisa = int((locked_until - datetime.datetime.now()).total_seconds())
            return None, f"⛔ Terkunci — coba lagi dalam {sisa}s"
        members = self._members_dict()
        m = None
        hp = None
        if identifier in members and isinstance(members[identifier], dict):
            hp, m = identifier, members[identifier]
        else:
            ident_l = identifier.lower()
            matches = [(k, v) for k, v in members.items()
                       if isinstance(v, dict) and str(v.get("nama", "")).lower() == ident_l]
            if len(matches) == 1:
                hp, m = matches[0]
            elif len(matches) > 1:
                return None, "Ada beberapa member dengan nama sama — gunakan No HP."
        if not m:
            return None, "Member tidak ditemukan. Cek nama/No HP atau daftarkan dulu."
        if not M.verify_password(pin, m.get("pin_enc") or ""):
            self._member_fails[identifier] = self._member_fails.get(identifier, 0) + 1
            n = self._member_fails[identifier]
            if n >= 5:
                self._member_locked_until[identifier] = \
                    datetime.datetime.now() + datetime.timedelta(minutes=1)
                self._member_fails[identifier] = 0
                return None, "⛔ 5x PIN salah — terkunci 1 menit"
            return None, f"✖ PIN salah ({n}/5)"
        self._member_fails.pop(identifier, None)
        return {"hp": hp, "nama": str(m.get("nama", "")),
                "saldo_menit": int(m.get("saldo_menit", 0) or 0)}, None

    def topup_semua_jenis(self):
        """Daftar paket isi ulang per jenis member {VIP:[...], PS3:[...], PS4:[...]}.
        Migrasi otomatis: jenis yang belum diatur mewarisi `member_topup` lama
        (atau default) supaya tidak ada jenis tanpa harga."""
        cfg_jenis = M.ConfigManager.get("member_topup_jenis", None)
        if not isinstance(cfg_jenis, dict):
            cfg_jenis = {}
        legacy = M.ConfigManager.get("member_topup", None)
        base = ([dict(p) for p in legacy]
                if isinstance(legacy, list) and legacy
                else [dict(p) for p in self._DEFAULT_TOPUP])
        out = {}
        for j in self._JENIS_MEMBER:
            lst = cfg_jenis.get(j)
            out[j] = ([dict(p) for p in lst]
                      if isinstance(lst, list) and lst else [dict(p) for p in base])
        return out

    def topup_paket_list(self, jenis=""):
        jenis = str(jenis or "").strip().upper() or "VIP"
        if jenis not in self._JENIS_MEMBER:
            jenis = "VIP"
        return self.topup_semua_jenis()[jenis]

    def save_topup_paket(self, paket_list, jenis="VIP"):
        jenis = str(jenis or "VIP").strip().upper() or "VIP"
        if jenis not in self._JENIS_MEMBER:
            return None, "Jenis harus salah satu dari: " + ", ".join(self._JENIS_MEMBER) + "."
        norm = []
        for p in paket_list or []:
            try:
                nm = str(p.get("nama", "")).strip()
                menit = int(p.get("menit", 0))
                harga = int(p.get("harga", 0))
            except Exception:
                return None, "Paket isi ulang tidak valid."
            if not nm or menit <= 0 or harga < 0:
                return None, f"Paket '{nm or '?'}': nama & menit wajib (>0), harga >= 0."
            norm.append({"nama": nm, "menit": menit, "harga": harga})

        def _mut(cfg):
            semua = cfg.get("member_topup_jenis")
            if not isinstance(semua, dict):
                semua = {}
                cfg["member_topup_jenis"] = semua
            semua[jenis] = norm
            return cfg

        M.ConfigManager.update(_mut)
        applog(f"[TOPUP PAKET] jenis={jenis} | {len(norm)} paket disimpan | admin={self.user}")
        return norm, None

    def topup_member(self, hp, paket_nama):
        """Isi ulang saldo waktu member: tambah menit + catat transaksi.
        Paket dicari dari daftar harga sesuai JENIS member."""
        hp = str(hp or "").strip()
        members = self._members_dict()
        m = members.get(hp)
        if not isinstance(m, dict):
            return None, "Member tidak ditemukan."
        jenis = str(m.get("jenis", "VIP") or "VIP").strip().upper() or "VIP"
        if jenis not in self._JENIS_MEMBER:
            jenis = "VIP"
        pkt = next((p for p in self.topup_paket_list(jenis) if p.get("nama") == paket_nama), None)
        if not pkt:
            return None, f"Paket isi ulang '{paket_nama}' tidak ada."
        menit = int(pkt.get("menit", 0))
        harga = int(pkt.get("harga", 0))
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        m["saldo_menit"] = int(m.get("saldo_menit", 0) or 0) + menit
        m["terakhir_aktif"] = now_str
        riw = m.setdefault("riwayat_isi", [])
        riw.append({"tgl": now_str, "paket": pkt["nama"], "menit": menit,
                    "harga": harga, "kasir": self.user})
        if len(riw) > 100:
            del riw[:-100]

        def _mut(cfg):
            cfg["members"] = members
            return cfg

        M.ConfigManager.update(_mut)
        # Catat sebagai transaksi riwayat agar masuk omzet & cloud
        label = f"MEMBER · {m.get('nama', '')}"
        idx = self.catat(label, f"ISI ULANG {pkt['nama']} (+{menit} mnt)", {}, harga,
                         source="tv", paid=True)
        try:
            meta = self.riwayat_meta[idx]
            meta["member_hp"] = hp
            meta["member_nama"] = m.get("nama", "")
            meta["topup"] = {"paket": pkt["nama"], "menit": menit, "harga": harga}
            self.save_riwayat()
        except Exception:
            pass
        applog(f"[MEMBER TOPUP] {m.get('nama')} ({hp}) jenis={jenis} | {pkt['nama']} "
               f"+{menit} mnt {M.fmt_rp(harga)} | saldo={m['saldo_menit']} mnt | kasir={self.user}")
        return {"hp": hp, "nama": m.get("nama"), "jenis": jenis,
                "saldo_menit": m["saldo_menit"],
                "topup": {"paket": pkt["nama"], "menit": menit, "harga": harga}}, None

    def potong_saldo_member(self, hp, menit):
        """Potong saldo member (menit>0), clamp minimal 0. Kembalikan saldo baru."""
        hp = str(hp or "").strip()
        menit = max(0, int(menit or 0))
        members = self._members_dict()
        m = members.get(hp)
        if not isinstance(m, dict):
            raise ValueError("member tidak ditemukan")
        m["saldo_menit"] = max(0, int(m.get("saldo_menit", 0) or 0) - menit)

        def _mut(cfg):
            cfg["members"] = members
            return cfg

        M.ConfigManager.update(_mut)
        return m["saldo_menit"]

    def mulai_sesi_member(self, sesi, member_hp, member_pin):
        """Mulai sesi dari saldo waktu member (tanpa paket reguler).
        Verifikasi PIN di sini supaya aman; saldo TIDAK dipotong dulu —
        potongan terjadi saat sesi berakhir (_member_potong_akhir)."""
        res, err = self.verify_member(member_hp, member_pin)
        if err:
            return err
        # ── Cegah member yang sama aktif di dua tempat sekaligus ──
        for other in self.all_sesi():
            if other is sesi:
                continue
            if (getattr(other, "mode_member", False)
                    and getattr(other, "member_hp", None) == res["hp"]
                    and not other.sesi_kosong()):
                return (f"Member {res['nama']} sedang aktif bermain di {other.label}. "
                        "Selesaikan sesi tersebut dulu sebelum dipakai di sini.")
        sesi_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        members = self._members_dict()
        m = members.get(res["hp"])
        saldo_menit = int(m.get("saldo_menit", 0) or 0)
        if saldo_menit <= 0:
            return f"Saldo member {res['nama']} habis — isi ulang dulu."
        sesi.mode_member = True
        sesi.member_hp = res["hp"]
        sesi.member_nama = res["nama"]
        sesi.member_detik_pakai = 0
        sesi.is_bebas = False
        sesi.paket_aktif = f"MEMBER · {res['nama']}"
        sesi.sisa_waktu = saldo_menit * 60
        sesi.waktu_mulai = datetime.datetime.now()
        sesi.paket_harga_tetap = 0
        sesi.daftar_paket_sesi = [sesi.paket_aktif]
        sesi.harga_paket_sesi = [0]
        sesi.lunas_paket = [True]
        sesi.pesanan_aktif = {}
        sesi.lunas_pesanan = {}
        sesi.biaya_pesanan = 0
        sesi.diskoni = 0
        sesi.diskoni_mode = "nominal"
        sesi.paid = True
        sesi.menit_dipakai_awal = 0
        sesi._timer_paused = False
        sesi._paused_total = None
        sesi._last_transaction_item = None
        # tandai aktivitas member di config
        m["terakhir_aktif"] = sesi_now

        def _mut(cfg):
            cfg["members"] = members
            return cfg

        M.ConfigManager.update(_mut)
        if sesi._hub_ok():
            lunas_now, tagihan_now = sesi.split_lunas_tagihan()
            try:
                sesi.store.hub.send_start_timer(sesi.label, sesi.sisa_waktu, 0,
                                                lunas_total=lunas_now, tagihan_total=tagihan_now,
                                                nama_member=sesi.member_nama)
            except Exception:
                pass
        sesi._warnet_queue("UNLOCK", "sesi_member",
                           f"Sesi member {res['nama']} dimulai di {sesi.label}")
        sesi.store.notify("paket", sesi.snapshot())
        applog(f"[SESI MEMBER MULAI] {sesi.label} | {res['nama']} ({res['hp']}) | "
               f"saldo_awal={saldo_menit} mnt | kasir={self.user}")
        sesi.store._sync_timer_state()
        return None

    def set_pc_locked(self, sesi, locked, reason="", message=""):
        """Simpan status pc_locked ke config daftar_warnet (dibaca client
        lewat GET_STATUS & dipakai untuk re-queue LOCK)."""
        if not sesi or sesi.kind != "warnet" or not sesi.pc_id:
            return
        try:
            cfg = M.ConfigManager.load()
            daftar = cfg.get("daftar_warnet", []) or []
            for c in daftar:
                if c.get("pc_id") == sesi.pc_id:
                    c["pc_locked"] = bool(locked)
                    if locked:
                        c["pc_lock_reason"] = reason
                        c["pc_lock_message"] = message
                    else:
                        c.pop("pc_lock_reason", None)
                        c.pop("pc_lock_message", None)
                    break
            cfg["daftar_warnet"] = daftar
            M.ConfigManager.save(cfg)
        except Exception as e:
            _LOGGER.warning("Set pc_locked error: %s", e)

    def omzet(self, days=0, from_ts=None, to_ts=None):
        """Ringkasan laporan dari riwayat_meta (port fungsi omzet desktop).
        days: 0 = hari ini (dari tengah malam), >0 = N hari terakhir,
        <0 = seluruh waktu."""
        from datetime import datetime as _dt
        if from_ts is None:
            now = time.time()
            if days > 0:
                from_ts = now - days * 86400
            elif days == 0:
                from_ts = _dt.combine(_dt.now().date(), _dt.min.time()).timestamp()
            else:
                from_ts = 0
            to_ts = now + 1
        total = 0
        count = 0
        diskon = 0
        belum = 0
        per_kasir = {}
        per_paket = {}
        per_meja = {}
        per_hari = {}
        per_source = {"tv": 0, "warnet": 0}
        for i in range(min(len(self.riwayat_transaksi), len(self.riwayat_meta))):
            row = self.riwayat_transaksi[i]
            meta = self.riwayat_meta[i]
            try:
                ts = _dt.strptime(str(row[0])[:16], "%Y-%m-%d %H:%M").timestamp()
            except Exception:
                continue
            if ts < from_ts or ts > to_ts:
                continue
            t = int(meta.get("total", 0) or 0)
            total += t
            count += 1
            diskon += int(meta.get("diskoni", 0) or 0)
            if not meta.get("paid", True):
                belum += 1
            kasir = str(row[1] or "-")
            label = str(row[2] or "-")
            paket = str(meta.get("paket_raw", "") or "-")
            src = "warnet" if meta.get("source") == "warnet" else "tv"
            per_kasir[kasir] = per_kasir.get(kasir, 0) + t
            per_paket[paket] = per_paket.get(paket, 0) + t
            per_meja[label] = per_meja.get(label, 0) + t
            per_source[src] = per_source.get(src, 0) + t
            day = str(row[0])[:10]
            per_hari[day] = per_hari.get(day, 0) + t

        def _top(d):
            return [{"name": k, "total": v} for k, v in sorted(d.items(), key=lambda x: -x[1])[:12]]

        return {
            "total": total,
            "count": count,
            "diskon": diskon,
            "belum_lunas": belum,
            "per_kasir": _top(per_kasir),
            "per_paket": _top(per_paket),
            "per_meja": _top(per_meja),
            "per_source": per_source,
            "per_hari": [{"hari": k, "total": v} for k, v in sorted(per_hari.items())],
        }

    def state(self):
        tvs = [s.snapshot() for s in self.sesi_tv.values()]
        if self.hub and self.hub.running:
            for snap in tvs:
                snap["ws_online"] = bool(self.hub.is_meja_connected(snap.get("label", "")))
        warnet = []
        for s in self.sesi_warnet.values():
            snap = s.snapshot()
            snap["client_online"] = self._pc_online(s)
            warnet.append(snap)
        return {
            "user": self.user,
            "role": self.role,
            "has_password": self._has_password(),
            "lic_status": str((self._lic_check() or {}).get("status", "unknown")),
            "lic_pesan": str((self._lic_cache.get("status") or {}).get("pesan", "")),
            "lic_sisa_hari": int((self._lic_cache.get("status") or {}).get("sisa_hari", 0) or 0),
            "menu_makanan": self.menu_makanan,
            "menu_minuman": self.menu_minuman,
            "stok": self.stok,
            "stok_min": self.stok_min,
            "groups_tv": self.daftar_grup_tv(),
            "groups_warnet": self.daftar_grup_warnet(),
            "member_topup": self.topup_paket_list("VIP"),
            "member_topup_jenis": self.topup_semua_jenis(),
            "tv": tvs,
            "warnet": warnet,
            "events": list(self.events),
            "version": self._version,
        }

    def _pc_online(self, sesi):
        try:
            if not self.warnet or not sesi.pc_id:
                return False
            return self.warnet.is_pc_online(sesi.pc_id)
        except Exception:
            return False

    def _has_password(self):
        """True bila akun yang sedang login punya password lokal (bukan
        akun Google tanpa password) — dipakai UI untuk mode Buat Password."""
        try:
            u = (M.ConfigManager.get("users", {}) or {}).get(self.user)
            if not isinstance(u, dict):
                return False
            return bool(u.get("password_enc") or u.get("password"))
        except Exception:
            return True

    # ── lisensi real-time ──────────────────────────────────────────────
    _LIC_TTL = 5.0   # detik — polling state tiap 1 dtk tetap ringan

    def _lic_check(self):
        """Status lisensi dengan cache TTL pendek supaya UI bisa memantau
        real-time tanpa membaca config/verifikasi berat di setiap request.
        Bila status lokal bukan 'active', coba adopsi lisensi cloud dulu
        (aktivasi lewat rrbillingpro.exe / Android) — maksimal 1x per menit."""
        now = time.time()
        c = self._lic_cache
        if c.get("status") is not None and now - c.get("t", 0.0) < self._LIC_TTL:
            return c["status"]
        try:
            st = LicenseManager.get_status(current_user=self._resolve_license_user())
        except Exception as e:
            st = {"status": "unknown", "sisa_hari": 0, "pesan": f"Error: {e}"}
        if str(st.get("status", "")) != "active":
            if now - getattr(self, "_lic_restore_last", 0.0) >= self._LIC_RESTORE_EVERY:
                self._lic_restore_last = now
                try:
                    if self._lic_cloud_restore():
                        st = LicenseManager.get_status(
                            current_user=self._resolve_license_user())
                except Exception as e:
                    _LOGGER.warning("Cloud license restore error: %s", e)
        self._lic_cache = {"t": now, "status": st}
        return st

    def _lic_invalidate(self):
        """Buang cache status lisensi (dipanggil setelah aktivasi/revoke)."""
        self._lic_cache = {"t": 0.0, "status": None}

    def _lic_ok(self):
        """False bila trial/lisensi habis — blokir transaksi baru saja;
        sesi yang sudah berjalan dibiarkan sampai selesai."""
        st = self._lic_check()
        ok = str(st.get("status", "")) in ("active", "trial")
        return ok, st

    # ── adopsi lisensi dari cloud (port 'Cloud license restore' main.py) ──
    _EDITION_RANK = {"BULANAN": 0, "3BULAN": 1, "TAHUNAN": 2, "LIFETIME": 3}
    _LIC_RESTORE_EVERY = 60.0   # detik minimal antar percobaan restore cloud

    def _lic_edition_from_max_tv(self, lic, max_tv):
        """maxTv tidak valid (<=0) → jangan ubah edition; LIFETIME jangan
        diturunkan. Pola sama dengan _save_edition_from_max_tv di main.py."""
        if max_tv >= 999999:
            new = "LIFETIME"
        elif max_tv >= 15:
            new = "TAHUNAN"
        elif max_tv >= 10:
            new = "3BULAN"
        elif max_tv > 0:
            new = "BULANAN"
        else:
            return
        old = str(lic.get("edition", "")).strip().upper() if "edition" in lic else ""
        if old and self._EDITION_RANK.get(old, -1) >= self._EDITION_RANK.get(new, -1):
            return
        lic["edition"] = new

    def _lic_write_cloud(self, expires_at, kode_aktivasi="", max_tv=0, promo_add_tv=0):
        """Tulis lisensi hasil adopsi cloud ke file lisensi lokal web."""
        import datetime as _dt
        try:
            fmt = lambda x: x if "T" in x else x + "T00:00:00"
            expires = _dt.datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=_dt.timezone.utc)
            if expires <= _dt.datetime.now(_dt.timezone.utc):
                return False
        except Exception:
            return False
        lic = LicenseManager.load() or {}
        resolved = (self._resolve_license_user() or "").strip()
        existing_user = str(lic.get("username", ""))
        # Lisensi milik user lain TIDAK ditimpa, kecuali yang login sekarang
        # adalah admin_utama pemilik data mesin ini (pola main.py).
        if lic.get("aktif") and existing_user and existing_user != resolved:
            admin_utama = ""
            try:
                for _u in (M.ConfigManager.get("users", {}) or {}).values():
                    if isinstance(_u, dict) and _u.get("admin_utama"):
                        admin_utama = _u.get("admin_utama")
            except Exception:
                pass
            if not (admin_utama and resolved == admin_utama):
                return False
        lic["aktif"] = True
        old_exp_raw = str(lic.get("expiry", "") or "")
        try:
            if not old_exp_raw:
                lic["expiry"] = expires_at
            else:
                old_exp = _dt.datetime.fromisoformat(fmt(old_exp_raw).replace("Z", "+00:00"))
                new_exp = _dt.datetime.fromisoformat(fmt(expires_at).replace("Z", "+00:00"))
                if new_exp > old_exp:
                    lic["expiry"] = expires_at
        except Exception:
            lic["expiry"] = expires_at
        lic["firebase_sync"] = True
        lic["binding_mode"] = "username"
        lic["username"] = resolved
        self._lic_edition_from_max_tv(lic, int(max_tv or 0))
        if kode_aktivasi:
            lic["kode_aktivasi"] = str(kode_aktivasi)
        lic["promo_add_tv"] = int(promo_add_tv or 0) or int(lic.get("promo_add_tv", 0) or 0)
        lic["promo_add_warnet"] = lic.get("promo_add_tv", 0)
        LicenseManager.save(lic)
        applog(f"[LISENSI] Adopsi lisensi CLOUD untuk {resolved} "
               f"(s/d {expires_at}, sumber: desktop/Android)")
        return True

    def _lic_cloud_restore(self):
        """Cek Firestore: bila akun ini sudah punya lisensi aktif yang
        diaktifkan lewat aplikasi desktop (rrbillingpro.exe) / Android,
        adopsi ke file lisensi lokal web supaya status sinkron real-time."""
        user = (self._resolve_license_user() or "").strip()
        if not user:
            return False
        try:
            fc = FirestoreClient()
        except Exception as e:
            _LOGGER.warning("Cloud license restore dilewati (Firestore): %s", e)
            return False
        try:
            ls = fc.fetch_license_status_by_username(user)
            if ls and ls.get("status") == "active" and ls.get("expiresAt"):
                return self._lic_write_cloud(
                    ls["expiresAt"], max_tv=ls.get("maxTv") or 0,
                    promo_add_tv=ls.get("promoAddTv") or 0)
        except Exception as e:
            _LOGGER.warning("Cloud license restore (licenseStatus) gagal: %s", e)
        try:
            ld = fc.get_document(f"licenses/{user}")
            if ld and ld.get("expiry") and not ld.get("revoked"):
                if self._lic_write_cloud(ld["expiry"],
                                         kode_aktivasi=str(ld.get("kode", "") or ""),
                                         max_tv=int(ld.get("maxTv") or 0)):
                    return True
        except Exception as e:
            _LOGGER.warning("Cloud license restore (licenses/) gagal: %s", e)
        try:
            invs = fc.query_where_equal("invoices", "username", user)
            for iv in invs or []:
                if iv.get("revoked"):
                    continue
                if (str(iv.get("status", "")).upper() == "CONFIRMED"
                        and iv.get("expiry")):
                    if self._lic_write_cloud(iv["expiry"],
                                             kode_aktivasi=str(iv.get("kodeLisensi", "") or "")):
                        return True
        except Exception as e:
            _LOGGER.warning("Cloud license restore (invoices/) gagal: %s", e)
        return False

    def riwayat(self, q=None, limit=500, tgl=None, mode=None, kasir=None):
        q = (q or "").strip().lower()
        kasir_f = (kasir or "").strip()
        lo_ts = hi_ts = None
        if tgl:
            try:
                lo_dt = datetime.datetime.strptime(str(tgl)[:10], "%Y-%m-%d")
                lo_ts = lo_dt.timestamp()
                hi_ts = lo_dt.replace(hour=23, minute=59, second=59).timestamp()
            except Exception:
                lo_ts = hi_ts = None
        elif mode and mode != "all":
            now = datetime.datetime.now()
            if mode == "0":
                lo_ts = datetime.datetime.combine(now.date(), datetime.datetime.min.time()).timestamp()
                hi_ts = now.timestamp() + 1
            elif mode == "1":
                kem = now - datetime.timedelta(days=1)
                lo_ts = datetime.datetime.combine(kem.date(), datetime.datetime.min.time()).timestamp()
                hi_ts = datetime.datetime.combine(kem.date(), datetime.datetime.max.time()).timestamp()
            elif mode == "7":
                lo_ts = datetime.datetime.combine(
                    (now - datetime.timedelta(days=6)).date(), datetime.datetime.min.time()).timestamp()
                hi_ts = now.timestamp() + 1
            elif mode == "bulan":
                lo_ts = datetime.datetime.combine(now.replace(day=1).date(), datetime.datetime.min.time()).timestamp()
                hi_ts = now.timestamp() + 1
        out = []
        for i in range(min(len(self.riwayat_transaksi), len(self.riwayat_meta))):
            row = self.riwayat_transaksi[i]
            meta = self.riwayat_meta[i]
            if lo_ts is not None:
                try:
                    ts = datetime.datetime.strptime(str(row[0])[:16], "%Y-%m-%d %H:%M").timestamp()
                except Exception:
                    continue
                if ts < lo_ts or ts > hi_ts:
                    continue
            if kasir_f and kasir_f != "SEMUA":
                if str(row[1]) != kasir_f:
                    continue
            if q:
                hay = " ".join(str(x) for x in row) + " " + json.dumps(meta)
                if q not in hay.lower():
                    continue
            out.append({
                "index": i,
                "waktu": row[0],
                "kasir": row[1],
                "label": row[2],
                "paket": row[3],
                "pesanan": row[4],
                "diskon": row[5],
                "total": row[6],
                "status": row[7],
                "meta": {k: meta.get(k) for k in
                         ("source", "paket_harga", "pesanan_total", "total", "diskoni",
                          "diskoni_mode", "paid", "cloud_id", "paket_raw", "pesanan",
                          "tagihan_nama", "tagihan_hp", "tagihan_at", "lunas_at")},
            })
            if len(out) >= limit:
                break
        return out


STORE = Store()


# ─────────────────────────────────────────────────────────────────────────
#  QR PANGILAN OPERATOR (port main.py _qr_*) — pelanggan scan QR di TV,
#  halaman qr_page/call.html menulis Firestore calls/, poller di sini
#  memproses: validasi kode vs qr_call, simpan riwayat qr_pesanan_log.json,
#  hapus dokumen, rate-limit, lalu push event ke browser.
# ─────────────────────────────────────────────────────────────────────────
QR_PAGE_BASE = "https://rrbillingpro.web.app/call.html"
QR_RATE_LIMIT = 90          # detik antar panggilan per TV (sama dengan desktop)
QR_PIN_TTL = 240            # detik PIN panggil operator berlaku sejak ditulis (sama dengan desktop)
_QR_SEEN = set()            # id dokumen calls yang sudah diproses
_QR_SEEN_LOCK = threading.Lock()
_QR_LAST_CALL = {}          # tv -> ts panggilan terakhir
_QR_LOG_LOCK = threading.Lock()


def _qr_log(msg):
    try:
        applog(f"[QR] {msg}")
    except Exception:
        pass


def _qr_token_baru():
    import secrets
    return secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:8].upper()


def _qr_host_web():
    try:
        return str(M.ConfigManager.get("qr_page_url", "") or "").strip() or QR_PAGE_BASE
    except Exception:
        return QR_PAGE_BASE


def _qr_owner():
    try:
        return STORE._resolve_license_user() or ""
    except Exception:
        return ""


def _qr_url(nama_tv, kode, nama_grup=""):
    owner = _qr_owner()
    url = (f"{_qr_host_web()}?tv={quote(nama_tv)}&k={kode}&o={quote(owner)}")
    if nama_grup:
        url += f"&g={quote(nama_grup)}"
    return url


def _qr_ip_tv(nama_tv):
    try:
        for item in (M.ConfigManager.load().get("daftar_tv", []) or []):
            if str(item.get("nama", "")) == nama_tv:
                return str(item.get("ip", "")).strip()
    except Exception:
        pass
    return ""


def _qr_grup_tv(nama_tv):
    try:
        for item in (M.ConfigManager.load().get("daftar_tv", []) or []):
            if str(item.get("nama", "")) == nama_tv:
                return str(item.get("nama_grup", "") or "").strip()
    except Exception:
        pass
    return ""


def _qr_simpan_png(nama_tv, url):
    """Simpan QR PNG ke folder qr_panggilan/<TV>.png. Return path ('' gagal)."""
    try:
        import qrcode
        folder = os.path.join(BASE_DIR, "qr_panggilan")
        os.makedirs(folder, exist_ok=True)
        aman = "".join(c if c.isalnum() or c in " -_" else "_" for c in nama_tv).strip()
        path = os.path.join(folder, f"{aman or 'TV'}.png")
        qrcode.make(url).save(path)
        return path
    except Exception as e:
        _qr_log(f"simpan png gagal: {e}")
        return ""


def _qr_png_data_uri(nama_tv):
    """Baca QR PNG jadi data URI base64 (tampil di <img> tanpa header auth).
    Return '' jika file tidak ada / gagal baca."""
    try:
        folder = os.path.join(BASE_DIR, "qr_panggilan")
        aman = "".join(c if c.isalnum() or c in " -_" else "_" for c in nama_tv).strip() or "TV"
        path = os.path.join(folder, f"{aman}.png")
        if not os.path.isfile(path):
            _qr_simpan_png(nama_tv, _qr_url(nama_tv, _qr_generate_untuk(nama_tv), _qr_grup_tv(nama_tv)))
            if not os.path.isfile(path):
                return ""
        import base64
        with open(path, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        _qr_log(f"png data uri gagal: {e}")
        return ""


def _qr_generate_untuk(nama_tv):
    """Port _qr_generate_untuk (main.py): ambil kode unik TV; jika belum ada
    ATAU IP TV berubah -> kode BARU (QR lama tidak berlaku lagi)."""
    try:
        cfg = M.ConfigManager.load()
        peta = cfg.get("qr_call", {}) or {}
        if not isinstance(peta, dict):
            peta = {}
        lama = peta.get(nama_tv) or {}
        if isinstance(lama, dict):
            kode_lama = str(lama.get("kode", ""))
            ip_lama = str(lama.get("ip", ""))
        else:
            kode_lama, ip_lama = "", ""
        ip_kini = _qr_ip_tv(nama_tv)
        if kode_lama and (not ip_kini or ip_kini == ip_lama):
            _qr_simpan_png(nama_tv, _qr_url(nama_tv, kode_lama, _qr_grup_tv(nama_tv)))
            return kode_lama
        kode = _qr_token_baru()
        peta[nama_tv] = {"kode": kode, "ip": ip_kini}
        cfg["qr_call"] = peta
        M.ConfigManager.save(cfg)
        _qr_simpan_png(nama_tv, _qr_url(nama_tv, kode, _qr_grup_tv(nama_tv)))
        _qr_log(f"{nama_tv}: kode baru ({ip_kini})")
        return kode
    except Exception as e:
        _qr_log(f"generate gagal: {e}")
        return ""


def _qr_cari_tv_oleh_kode(kode):
    """Cari nama TV di config qr_call yang kodenya cocok (QR lama yang nama
    TV-nya berubah). Return (tv, pi) atau (None, None)."""
    try:
        peta = (M.ConfigManager.load().get("qr_call", {}) or {})
        for tv, pi in peta.items():
            if isinstance(pi, dict) and str(pi.get("kode", "") or "") == str(kode):
                return tv, pi
    except Exception:
        pass
    return None, None


def _qr_parse_items(doc):
    """Port _qr_parse_items (main.py): kumpulkan item terstruktur dari dokumen
    calls (format BARU 'items'; format LAMA 'item' string sebagai fallback)."""
    out = []
    raw = doc.get("items")
    if isinstance(raw, list) and raw:
        for x in raw:
            try:
                if isinstance(x, dict):
                    tipe = str(x.get("t") or x.get("tipe") or "makanan")
                    if tipe not in ("paket", "makanan", "minuman"):
                        tipe = "makanan"
                    out.append({
                        "tipe": tipe,
                        "nama": str(x.get("n") or x.get("nama") or "?"),
                        "qty": int(x.get("q") or x.get("qty") or 1),
                        "harga": int(x.get("h") or x.get("harga") or 0),
                        "menit": int(x.get("men") or x.get("menit") or 0),
                        "status": "baru",
                    })
                else:
                    out.append({"tipe": "pesanan", "nama": str(x), "qty": 1,
                                "harga": 0, "menit": 0, "status": "baru"})
            except Exception:
                continue
        return out
    item_str = doc.get("item")
    if isinstance(item_str, list) and item_str:
        return [{"tipe": "pesanan", "nama": str(x), "qty": 1, "harga": 0,
                 "menit": 0, "status": "baru"} for x in item_str]
    return []


def _qr_log_load():
    try:
        with _QR_LOG_LOCK:
            if os.path.exists(M.QR_PESAN_LOG):
                with open(M.QR_PESAN_LOG, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, list) else []
    except Exception as e:
        _qr_log(f"gagal baca riwayat pesanan: {e}")
    return []


def _qr_log_save(rows):
    try:
        with _QR_LOG_LOCK:
            with open(M.QR_PESAN_LOG, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=1)
    except Exception as e:
        _qr_log(f"gagal simpan riwayat pesanan: {e}")


def _qr_log_append(order):
    rows = [r for r in _qr_log_load() if r.get("id") != order.get("id")]
    rows.append(order)
    _qr_log_save(rows)


def _qr_panggilan_masuk(doc):
    """Dipanggil thread CallPoller — port _qr_panggilan_masuk (main.py):
    validasi kode, simpan riwayat (SEBELUM dokumen dihapus), push event."""
    global _QR_SEEN
    try:
        did = str(doc.get("_id", ""))
        if not did:
            return
        with _QR_SEEN_LOCK:
            if did in _QR_SEEN:
                return
        kode = str(doc.get("kode", ""))
        tv = str(doc.get("tv", ""))
        if not tv or not kode:
            return
        peta = (M.ConfigManager.load().get("qr_call", {}) or {})
        pi = peta.get(tv) if isinstance(peta, dict) else None
        if not isinstance(pi, dict) or kode != str(pi.get("kode", "")):
            tv2, pi2 = _qr_cari_tv_oleh_kode(kode)
            if tv2 is not None and isinstance(pi2, dict):
                tv, pi = tv2, pi2
            else:
                _qr_log(f"panggilan {did} diabaikan: tv={tv!r} kode={kode!r} tak dikenal")
                with _QR_SEEN_LOCK:
                    _QR_SEEN.add(did)
                return
            with _QR_SEEN_LOCK:
                _QR_SEEN.add(did)
        with _QR_SEEN_LOCK:
            _QR_SEEN.add(did)
            if len(_QR_SEEN) > 5000:
                _QR_SEEN = set(list(_QR_SEEN)[-2500:])
        now = time.time()
        rate_ok = now - _QR_LAST_CALL.get(tv, 0) >= QR_RATE_LIMIT
        if rate_ok:
            _QR_LAST_CALL[tv] = now
        jenis = str(doc.get("jenis", "keluhan"))
        items = _qr_parse_items(doc)
        item_text = doc.get("item") or []
        catatan = str(doc.get("catatan", ""))
        order = {
            "id": did,
            "waktu": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "tv": tv,
            "jenis": jenis,
            "item": [str(x) for x in item_text],
            "items": items,
            "catatan": catatan,
            "status": "baru",
        }
        _qr_log_append(order)
        try:
            from firestore_sync import get_firestore_client
            get_firestore_client().delete_document(f"calls/{did}")
        except Exception as e:
            _qr_log(f"gagal hapus panggilan {did}: {e}")
        if not rate_ok:
            _qr_log(f"panggilan {did} masuk jendela rate-limit — dicatat di riwayat")
            return
        _qr_log(f"panggilan masuk: tv={tv} did={did} jenis={jenis} item={len(items)}")
        try:
            STORE.notify("panggilan", {"label": tv, "total": 1})
        except Exception:
            pass
    except Exception as e:
        _qr_log(f"panggilan masuk error: {e}")


def _booking_poll_loop():
    """Polling Firestore 'bookings' — booking status BARU (belum dikonfirmasi)
    diberitahukan ke kasir via event 'booking_baru' (toast + beep di UI)."""
    seen = set()
    while True:
        try:
            owner = (STORE._resolve_license_user() or "").strip().lower()
            if owner:
                docs = FirestoreClient().query_all("bookings", limit=50,
                                                   order_field="createdAt") or []
                ids_baru = set()
                for d in docs:
                    if str(d.get("owner", "")).strip().lower() != owner:
                        continue
                    did = str(d.get("_id", ""))
                    if str(d.get("status", "")) != "baru":
                        continue
                    ids_baru.add(did)
                    if did in seen:
                        continue
                    seen.add(did)
                    try:
                        STORE.notify("booking_baru", {"label": str(d.get("namaPelanggan", "") or "")},
                                     did=did, nama=str(d.get("namaPelanggan", "") or ""),
                                     perangkat=str(d.get("perangkat", "") or ""),
                                     tanggal=str(d.get("tanggal", "") or ""),
                                     jam=str(d.get("jam", ""))[:5])
                        applog(f"[BOOKING BARU] {did[:8].upper()} | "
                               f"{d.get('namaPelanggan', '')} | {d.get('perangkat', '')} "
                               f"{d.get('tanggal', '')} {d.get('jam', '')}")
                    except Exception:
                        pass
                seen &= ids_baru   # buang id yang sudah diproses/ditolak
                # Prune event booking_baru basi (sudah dikonfirmasi/ditolak)
                # agar tidak diputar ulang ke UI setelah login/restart.
                try:
                    with STORE._lock:
                        alive = [ev for ev in STORE.events
                                 if ev.get("type") != "booking_baru"
                                 or ev.get("did") in ids_baru]
                        if len(alive) != len(STORE.events):
                            STORE.events = alive
                            STORE._version += 1
                except Exception:
                    pass
        except Exception as e:
            _LOGGER.warning("Booking poll error: %s", e)
        time.sleep(20)


def _start_booking_poller():
    threading.Thread(target=_booking_poll_loop, daemon=True,
                     name="BookingPoller").start()
    applog("[BOOKING] Poller dimulai (bookings, status baru)")


def _start_call_poller():
    try:
        from firestore_sync import CallPoller
        p = CallPoller(interval=6.0, limit=5, order_field="ts")
        p.start(_qr_panggilan_masuk)
        STORE._call_poller = p
        _qr_log("CallPoller dimulai (calls, order ts DESC)")
    except Exception as e:
        _qr_log(f"CallPoller gagal start: {e}")
    _start_pin_poller()


def _start_pin_poller():
    """PIN sesi QR (qr_sessions) — verifikasi kehadiran pelanggan di depan TV.
    Port _qr_pin_proses (main.py): tanpanya PIN panggil operator tidak pernah
    dikirim ke TV (SHOW_PIN) padahal hub WS (tv_ws_hub) sudah siap."""
    try:
        from firestore_sync import CallPoller
        _PIN_ACTIF.clear()
        _PIN_HIDE_LAST.clear()
        _PIN_LOOP_STOP.clear()
        p = CallPoller(collection="qr_sessions", interval=4.0, limit=10,
                       order_field="created")
        p.start(_qr_pin_proses)
        STORE._pin_poller = p
        t = threading.Thread(target=_qr_pin_loop, daemon=True)
        t.start()
        STORE._pin_loop_thread = t
        _qr_log("PinPoller dimulai (qr_sessions, order created DESC)")
    except Exception as e:
        _qr_log(f"PinPoller gagal start: {e}")


# ── PIN Sesi QR (panggil operator) — port main.py ───────────────────────────
_PIN_HURUF = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_PIN_ANGKA = "23456789"
_PIN_ACTIF = {}        # tv -> {'sid','pin','t0','owner'}
_PIN_HIDE_LAST = {}    # tv -> ts HIDE_PIN terakhir (kooldown)
_PIN_LOOP_STOP = threading.Event()


def _qr_pin_baru() -> str:
    """PIN 5 karakter alfanumerik: 2 huruf + 3 angka (tanpa 0/O/1/I).
    Selalu BERUBAH setiap kali QR discan (satu PIN per sesi)."""
    h = [random.choice(_PIN_HURUF) for _ in range(2)]
    a = [random.choice(_PIN_ANGKA) for _ in range(3)]
    pin = list(h + a)
    random.shuffle(pin)
    return "".join(pin)


def _set_pin_doc(did: str, data: dict):
    try:
        from firestore_sync import get_firestore_client
        get_firestore_client().set_document(f"qr_sessions/{did}", data, merge=True)
    except Exception as e:
        _qr_log(f"update sesi {did} gagal: {e}")


def _qr_pin_set_tv(owner: str, tv: str, pin: str):
    """Tampilkan PIN di layar TV (kiri atas) via WebSocket hub (app RR Billing TV)."""
    try:
        hub = getattr(STORE, "hub", None)
        if hub is not None and hub.running:
            ok = hub.send_show_pin(tv, pin)
            if not ok:
                _qr_log(f"tampil PIN TV {tv} gagal: client APK tidak terhubung")
        else:
            _qr_log(f"tampil PIN TV {tv} gagal: hub WS tidak aktif")
    except Exception as e:
        _qr_log(f"tampil PIN TV {tv} gagal: {e}")


def _qr_pin_clear_tv(owner: str, tv: str):
    """Sembunyikan PIN di TV — idempotent dengan kooldown 10 dtk supaya
    HIDE_PIN yang gagal (WS putus sesaat) tertolong kiriman berikutnya."""
    if not tv:
        return
    try:
        last = _PIN_HIDE_LAST.get(tv, 0)
        if time.time() - last < 10:
            return
        _PIN_HIDE_LAST[tv] = time.time()
        hub = getattr(STORE, "hub", None)
        if hub is not None and hub.running:
            hub.send_hide_pin(tv)
        else:
            _qr_log(f"sembunyi PIN TV {tv} gagal (hub WS tidak aktif)")
    except Exception as e:
        _qr_log(f"sembunyi PIN TV {tv} gagal: {e}")


def _qr_pin_selesai(tv: str, sid: str, reason: str = "", hapus_doc: bool = True):
    """Akhiri sesi PIN: sembunyikan overlay TV, hapus dokumen sesi
    (kecuali status verified yang butuh dibaca web)."""
    akt = _PIN_ACTIF.get(tv)
    if akt and (not sid or akt.get("sid") == sid):
        _PIN_ACTIF.pop(tv, None)
    if reason:
        _qr_log(f"sesi PIN {tv}: {reason}")
        _qr_pin_clear_tv("", tv)
    if hapus_doc and sid:
        try:
            from firestore_sync import get_firestore_client
            get_firestore_client().delete_document(f"qr_sessions/{sid}")
        except Exception as e:
            _qr_log(f"hapus sesi {sid} gagal: {e}")


def _qr_pin_proses(doc: dict):
    """Thread PinPoller: state machine sesi PIN (dipanggil di thread).

    TIDAK memakai guard _QR_SEEN — dokumen yang sama wajib diproses berulang
    setiap poll, karena alur verifikasi PIN (pin_user dari web) hanya bisa
    dilihat pada poll berikutnya setelah web menulis pin_user."""
    try:
        did = str(doc.get("_id", ""))
        if not did:
            return
        tv = str(doc.get("tv", ""))
        kode = str(doc.get("kode", ""))
        if not tv or not kode:
            return
        peta = (M.ConfigManager.load().get("qr_call", {}) or {})
        pi = peta.get(tv) if isinstance(peta, dict) else None
        if not isinstance(pi, dict) or kode != str(pi.get("kode", "")):
            # QR lama / nama TV berubah: coba cocokkan lewat kode dulu.
            tv2, pi2 = _qr_cari_tv_oleh_kode(kode)
            if tv2 is not None and isinstance(pi2, dict):
                tv, pi = tv2, pi2
                _qr_log(f"PIN: sesi {did} tv={doc.get('tv')!r} dipetakan ke {tv!r} via kode")
            else:
                _qr_log(f"PIN tolak: tv={tv!r} kode={kode!r} tidak dikenal di qr_call")
                return
        now = time.time()
        status = str(doc.get("status", "awaiting"))
        owner = str(doc.get("owner", "")).strip()
        aktif = _PIN_ACTIF.get(tv)
        sid_sekarang = (aktif or {}).get("sid")

        if status == "awaiting":
            pin = str(doc.get("pin", "") or "")
            if not pin:
                # PIN sudah di memori untuk sesi yang sama (write Firestore
                # tertunda) -> pakai ulang, jangan generate PIN baru.
                if aktif and sid_sekarang == did and (aktif or {}).get("pin"):
                    pin = (aktif or {}).get("pin")
                    _set_pin_doc(did, {"pin": pin, "pin_set_at": int(now * 1000)})
                    _qr_pin_set_tv(owner, tv, pin)
                    return
                # Satu sesi aktif per TV: sesi lama hangus diganti yang baru
                if aktif and sid_sekarang and sid_sekarang != did:
                    _qr_pin_selesai(tv, sid_sekarang, reason="diganti")
                pin = _qr_pin_baru()
                _set_pin_doc(did, {"pin": pin, "pin_set_at": int(now * 1000)})
                _PIN_ACTIF[tv] = {"sid": did, "pin": pin, "t0": now, "owner": owner}
                _qr_pin_set_tv(owner, tv, pin)
                return
            # PIN sudah terpasang (sinkronisasi lintas-restart)
            _PIN_ACTIF[tv] = {"sid": did, "pin": pin, "t0": now, "owner": owner}
            pin_set_at = float(doc.get("pin_set_at", 0) or 0) / 1000.0
            if pin_set_at and now - pin_set_at > QR_PIN_TTL:
                _set_pin_doc(did, {"status": "expired", "reason": "ttl"})
                _qr_pin_selesai(tv, did, reason="expired")
                return
            pin_user = str(doc.get("pin_user", "") or "").strip().upper()
            if pin_user:
                if pin_user == str(pin).strip().upper():
                    _set_pin_doc(did, {"status": "verified", "pin_user": ""})
                    _qr_pin_selesai(tv, did, reason="ok", hapus_doc=False)
                    try:
                        STORE.notify("panggilan", {"label": tv, "total": 1, "kehadiran": True})
                    except Exception:
                        pass
                else:
                    tries = int(doc.get("tries", 0) or 0) + 1
                    if tries >= 3:
                        _set_pin_doc(did, {"status": "blocked", "pin_user": "", "tries": tries})
                        _qr_pin_selesai(tv, did, reason="blocked")
                    else:
                        _set_pin_doc(did, {"tries": tries, "pin_user": ""})
        elif status in ("blocked", "expired"):
            _qr_pin_selesai(tv, did, reason=status)
        elif status == "verified":
            _qr_pin_selesai(tv, did, reason="ok", hapus_doc=False)
            created_ms = float(doc.get("created", 0) or 0)
            if created_ms and now - created_ms / 1000.0 > 300:
                try:
                    from firestore_sync import get_firestore_client
                    get_firestore_client().delete_document(f"qr_sessions/{did}")
                except Exception:
                    pass
    except Exception as e:
        _qr_log(f"pin proses error: {e}")


def _qr_pin_loop():
    """Re-trigger overlay PIN di TV tiap ~6 detik selama sesi aktif,
    karena overlay app TV auto-hilang 8 detik. Sesi lewat TTL dihanguskan."""
    while True:
        if _PIN_LOOP_STOP.is_set():
            break
        now = time.time()
        for tv, akt in list(_PIN_ACTIF.items()):
            try:
                sid = akt.get("sid")
                # Dokumen sesi sudah hilang (dihapus lewat jalur lain / sesi web
                # dibatalkan) → 2 kali berturut-turut hilang = hangus.
                if sid and (akt.get("doc_none") or 0) < 2:
                    try:
                        from firestore_sync import get_firestore_client
                        d = get_firestore_client().get_document(f"qr_sessions/{sid}")
                        if d is None:
                            akt["doc_none"] = (akt.get("doc_none") or 0) + 1
                            if akt["doc_none"] >= 2:
                                _qr_pin_selesai(tv, sid, reason="hilang", hapus_doc=False)
                                continue
                        else:
                            akt["doc_none"] = 0
                    except Exception:
                        pass
                if now - (akt.get("t0") or now) > QR_PIN_TTL:
                    _set_pin_doc(sid, {"status": "expired", "reason": "ttl"})
                    _qr_pin_selesai(tv, sid, reason="expired")
                    continue
                _qr_pin_set_tv(akt.get("owner", ""), tv, akt.get("pin", ""))
                # Sesi bisa berakhir TEPAT saat SHOW ini dikirim — balas HIDE
                # kalau entry sesi sudah tidak aktif lagi.
                if (_PIN_ACTIF.get(tv) or {}).get("sid") != akt.get("sid"):
                    _qr_pin_clear_tv("", tv)
            except Exception as e:
                _qr_log(f"pin loop {tv}: {e}")
        time.sleep(6)


# ─────────────────────────────────────────────────────────────────────────
#  KONTROL DEVICE — hub TV (WebSocket 8080) & socket warnet (TCP 5000)
# ─────────────────────────────────────────────────────────────────────────
class _HubTVAdapter:
    """Adapter minimal yang dibaca TvWsHub._find_kartu untuk snapshot reconnect."""
    def __init__(self, sesi):
        self._s = sesi
        self.label_tv = sesi.label
        self.nomor = sesi.nomor

    def sesi_kosong(self):
        return self._s.sesi_kosong()

    @property
    def is_bebas(self):
        return self._s.is_bebas

    @property
    def sisa_waktu(self):
        return self._s.sisa_waktu

    def _total_setelah_diskon(self):
        return self._s.total_setelah_diskon()


class _HubAppAdapter:
    @property
    def _semua_kartu_tv(self):
        return [_HubTVAdapter(s) for s in STORE.sesi_tv.values()]

    # ─ Bug Fix: jembatan overlay_setting (config web) ke TvWsHub._overlay_cfg() ─
    # TvWsHub baca self.app.tv_overlay_mode / tv_overlay_last_minutes; tanpa ini
    # overlay_setting yang disimpan lewat /api/settings/overlay TIDAK PERNAH
    # dibaca (selalu fallback default). Value web ("hide"/"remaining") di-mapping
    # ke istilah TvWsHub/desktop ("hidden"/"last_minutes").
    @property
    def tv_overlay_mode(self):
        try:
            cfg = M.ConfigManager.get("overlay_setting", {}) or {}
            mode = str(cfg.get("mode", "always"))
        except Exception:
            mode = "always"
        return {"hide": "hidden", "remaining": "last_minutes"}.get(mode, mode)

    @property
    def tv_overlay_last_minutes(self):
        try:
            cfg = M.ConfigManager.get("overlay_setting", {}) or {}
            return int(cfg.get("remaining_minutes", 5))
        except Exception:
            return 5


def _get_nama_rental():
    try:
        cfg = M.ConfigManager.get("profil_rental", {}) or {}
        if isinstance(cfg, dict):
            for uname, p in cfg.items():
                if isinstance(p, dict) and p.get("nama_rental"):
                    return str(p["nama_rental"])
    except Exception:
        pass
    return "RR Billing Pro"


def start_servers():
    """Nyalakan kontrol device: hub TV (WebSocket :8080), server media promosi
    (:8082) & socket warnet (TCP :5000)."""
    try:
        if M.ConfigManager.get("tv_ws_enabled", True):
            port = int(M.ConfigManager.get("warnet_tv_ws_port", 8080) or 8080)
            hub = TvWsHub(app=_HubAppAdapter(), port=port, get_nama_rental=_get_nama_rental)
            hub.start()
            STORE.hub = hub
    except Exception as e:
        _LOGGER.warning("Hub TV tidak menyala: %s", e)
    try:
        if M.ConfigManager.get("tv_ws_enabled", True):
            mport = int(M.ConfigManager.get("warnet_media_port", 8082) or 8082)
            media = TvMediaServer(
                media_dir=M.app_path("media_promo"),
                port=mport,
            )
            media.start()
            STORE.media = media
    except Exception as e:
        _LOGGER.warning("Server media tidak menyala: %s", e)
    try:
        wport = int(M.ConfigManager.get("warnet_port", 5000) or 5000)
        STORE.warnet = WarnetServerWeb(STORE, listen_port=wport)
        STORE.warnet.start()
    except Exception as e:
        _LOGGER.warning("Socket warnet tidak menyala: %s", e)
    try:
        _start_call_poller()
    except Exception as e:
        _qr_log(f"CallPoller gagal: {e}")
    try:
        _start_booking_poller()
    except Exception as e:
        _LOGGER.warning("Booking poller gagal: %s", e)


# ─────────────────────────────────────────────────────────────────────────
#  STRUK (port _print_receipt / _print_via_escpos / _print_to_file)
# ─────────────────────────────────────────────────────────────────────────
def build_struk_text(label, paket_nama, paket_harga, durasi_menit, pesanan_aktif,
                     biaya_pesanan, diskoni, diskoni_mode, total, kasir, menu_makanan, menu_minuman):
    L = []
    L.append("       RR BILLING PRO")
    L.append("      STRUK TRANSAKSI")
    L.append(f"Tanggal : {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}")
    L.append(f"Kasir   : {kasir or '-'}")
    L.append(f"Meja    : {label}")
    L.append("-" * 32)
    L.append(f"Paket   : {paket_nama or '-'}")
    if durasi_menit:
        L.append(f"Durasi  : {durasi_menit} menit")
    if paket_harga > 0:
        L.append(f"Biaya   : {M.fmt_rp(paket_harga)}")
    if pesanan_aktif:
        L.append("-" * 32)
        L.append("PESANAN:")
        mak = sum(menu_makanan.get(nm, 0) * q for nm, q in pesanan_aktif.items())
        minu = sum(menu_minuman.get(nm, 0) * q for nm, q in pesanan_aktif.items())
        for nm, q in pesanan_aktif.items():
            h = menu_makanan.get(nm, menu_minuman.get(nm, 0))
            L.append(f" {q}x {nm:<20} {M.fmt_rp(h * q)}")
        L.append(f" Makanan : {M.fmt_rp(mak)}")
        L.append(f" Minuman : {M.fmt_rp(minu)}")
    if diskoni > 0:
        L.append(f"Diskon  : {diskoni}%" if diskoni_mode == "persen" else f"Diskon  : {M.fmt_rp(diskoni)}")
    L.append("-" * 32)
    L.append(f"TOTAL   : {M.fmt_rp(total)}")
    L.append("")
    L.append("      TERIMA KASIH")
    L.append("   Silakan datang kembali")
    return "\n".join(L)


# ─── Printer Bluetooth BLE (RPP02N dkk — ISSC Transparent UART) ──────────────
BLE_PRINT_RX_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"
_BLE_PRINTER_HINTS = ("RPP", "POS58", "58MM", "MTP", "THERMAL", "PRINTER", "TSC")

def _ble_escpos_bytes(text):
    data = bytearray()
    data += b"\x1b\x40"
    for line in str(text).split("\n"):
        data += line.encode("cp437", errors="replace") + b"\n"
    data += b"\x1b\x64\x05"
    data += b"\x1d\x56\x42"
    return bytes(data)

def _ble_write_printer(addr, data):
    import asyncio
    from bleak import BleakClient

    RX = BLE_PRINT_RX_UUID

    async def _write_once():
        async with BleakClient(addr, timeout=20) as client:
            if not client.is_connected:
                raise RuntimeError("BLE tidak terhubung")
            await asyncio.sleep(0.5)
            mtu = client.mtu_size
            chunk = max(20, min(500, mtu - 3))
            for i in range(0, len(data), chunk):
                await client.write_gatt_char(RX, data[i:i + chunk], response=False)
                await asyncio.sleep(0.03)

    async def _repair_pair():
        """Unpair + pair ulang di level Windows (menyembuhkan sesi GATT yang
        macet/E_ABORT pada RPP02N dkk), lalu koneksi berikutnya sehat."""
        try:
            from winrt.windows.devices.bluetooth import BluetoothLEDevice
            addr_int = int(str(addr).replace(":", ""), 16)
            dev = await BluetoothLEDevice.from_bluetooth_address_async(addr_int)
            if dev is None:
                return
            p = dev.device_information.pairing
            if p.is_paired:
                try:
                    await p.unpair_async()
                except Exception:
                    pass
                await asyncio.sleep(1.5)
            try:
                await p.pair_async()
            except Exception:
                pass
            await asyncio.sleep(1.5)
        except Exception as e:
            applog(f"[PRINT] proses pair ulang gagal: {e}")

    async def _run():
        try:
            await _write_once()
        except Exception as e1:
            applog(f"[PRINT] kirim pertama gagal ({str(e1)[:60]}) — coba pair ulang…")
            await _repair_pair()
            try:
                await _write_once()
            except Exception as e2:
                raise RuntimeError(f"gagal setelah pair ulang: {e2}")

    asyncio.run(_run())


def print_text(text):
    """Cetak struk ke printer terhubung (ESC/POS). Return (ok, msg).
    BLE/network/usb gagal → fallback simpan ke folder receipts."""
    try:
        cfg = M.ConfigManager.get("printer_settings", {}) or {}
        ptype = cfg.get("type", "file")
        address = cfg.get("address", "")
        if ptype in ("bluetooth", "usb", "network"):
            try:
                _print_escpos(text, ptype, address)
                msg = f"tercetak ke printer {ptype} ({address or '-'})"
                applog(f"[PRINT] OK | {msg}")
                return True, msg
            except Exception as e:
                fpath = _print_to_file(text)
                msg = (f"GAGAL cetak ke printer {ptype} ({str(e)[:80]}) — "
                       f"struk disimpan: {os.path.basename(fpath) if fpath else 'receipts/'}")
                applog(f"[PRINT] GAGAL | {msg}")
                return False, msg
        fpath = _print_to_file(text)
        msg = (f"type='{ptype}' (bukan printer) — struk disimpan: "
               f"{os.path.basename(fpath) if fpath else 'receipts/'}")
        applog(f"[PRINT] FILE | {msg}")
        return False, msg
    except Exception as e:
        _LOGGER.warning("Print error: %s", e)
        _print_to_file(text)
        return False, str(e)


def _print_async(text):
    """Cetak di background thread; kirim statusnya ke UI lewat event 'print'."""
    def _run():
        ok, msg = print_text(text)
        try:
            STORE.events.append({"t": time.time(), "type": "print",
                                 "ok": ok, "msg": msg})
            while len(STORE.events) > 60:
                STORE.events.pop(0)
            STORE._version += 1
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True, name="PrintJob").start()


def _print_escpos(text, ptype, address):
    try:
        if ptype == "bluetooth":
            _ble_write_printer(address, _ble_escpos_bytes(text))
            return
        elif ptype == "network":
            from escpos.printer import Network
            p = Network(address)
        elif ptype == "usb":
            from escpos.printer import Usb
            parts = address.split(":")
            if len(parts) == 2:
                p = Usb(int(parts[0], 16), int(parts[1], 16))
            else:
                p = Usb(0x0416, 0x5011)
        else:
            return
        p.text(text + "\n\n")
        p.cut()
    except Exception as e:
        _LOGGER.warning("ESC/POS print error: %s", e)
        _print_to_file(text)


def _print_to_file(text):
    try:
        receipt_dir = M.app_path("receipts")
        os.makedirs(receipt_dir, exist_ok=True)
        fname = f"struk_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        fpath = os.path.join(receipt_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(text)
        _LOGGER.info("Struk disimpan: %s", fpath)
        return fpath
    except Exception as e:
        _LOGGER.error("Print to file error: %s", e)
        return None


# ─────────────────────────────────────────────────────────────────────────
#  FLASK APP
# ─────────────────────────────────────────────────────────────────────────
try:
    from flask import Flask, request, jsonify, send_from_directory, Response, redirect, send_file
except ImportError:
    print("Flask belum terpasang. Jalankan: python -m pip install flask")
    sys.exit(1)

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
TOKENS = {}   # token -> username
PAIRING_JOBS = {}       # job_id -> {"ip","state","remote","device_name","device_mac","message","ts"}
PAIRING_JOBS_LOCK = threading.Lock()
PAIRING_TTL = 600       # detik sebelum job pairing kedaluwarsa


def _pairing_cleanup():
    now = time.time()
    with PAIRING_JOBS_LOCK:
        for jid in [j for j, v in PAIRING_JOBS.items() if now - v.get("ts", 0) > PAIRING_TTL]:
            PAIRING_JOBS.pop(jid, None)


def make_token():
    return "".join(random.choices(string.ascii_letters + string.digits, k=32))


def require_auth(fn):
    def wrapper(*args, **kwargs):
        tok = request.headers.get("X-Auth-Token", "")
        if not tok or TOKENS.get(tok) != STORE.user or not STORE.user:
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/logo.png")
def logo():
    return send_from_directory(STATIC_DIR, "logo.png")


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    res, err = STORE.check_login(data.get("username", ""), data.get("password", ""))
    if err:
        return jsonify({"error": err}), 401
    token = make_token()
    TOKENS.clear()
    TOKENS[token] = res["username"]
    STORE.notify("login", {"label": res["username"]})
    return jsonify({"token": token, **res})


@app.route("/api/register", methods=["POST"])
def api_register():
    """Daftarkan akun ADMIN pertama (hanya berlaku saat belum ada user)."""
    data = request.get_json(silent=True) or {}
    users = M.ConfigManager.get("users", {}) or {}
    if users:
        return jsonify({"error": "Akun admin sudah ada. Gunakan fitur Akun (admin)."}), 403
    res, err = STORE.register(data.get("username", ""), data.get("password", ""), role="admin")
    if err:
        return jsonify({"error": err}), 400
    return jsonify(res)


@app.route("/api/google_login", methods=["POST"])
def api_google_login():
    """Masuk dengan akun Google: idToken dari Firebase Auth SDK (popup).
    Mengembalikan token sesi yang sama seperti /api/login."""
    data = request.get_json(silent=True) or {}
    id_token = data.get("idToken", "")
    if not id_token:
        return jsonify({"error": "idToken wajib diisi"}), 400
    res, err = STORE.google_login(id_token)
    if err:
        return jsonify({"error": err}), 401
    token = make_token()
    TOKENS.clear()
    TOKENS[token] = res["username"]
    STORE.notify("login", {"label": res["username"]})
    return jsonify({"token": token, **res})


@app.route("/api/logout", methods=["POST"])
@require_auth
def api_logout():
    TOKENS.clear()
    STORE.user = None
    STORE.role = None
    return jsonify({"ok": True})


@app.route("/api/state")
@require_auth
def api_state():
    return jsonify(STORE.state())


@app.route("/api/events")
@require_auth
def api_events():
    def gen():
        last = STORE._version
        while True:
            if STORE._version != last:
                last = STORE._version
                ev = STORE.events[-1] if STORE.events else {}
                yield f"data: {json.dumps({'version': last, 'event': ev})}\n\n"
            time.sleep(0.5)
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _tv_sleep_runner(ip, port, label, key, alasan="", delay=2):
    """Port desktop _tv_sleep_now (main.py:7425): matikan TV berlapis lalu verifikasi.
    1) atpv2 POWER retry 3x (selang 2 dtk)  2) atpv2 SLEEP
    3) fallback ADB keyevent yang tersedia    4) verifikasi layar ±9 dtk.
    Bug Fix: jika verifikasi pertama masih nyala, retry 1x lagi dengan
    keyevent SLEEP eksplisit sebelum menyerah (TV kadang butuh 2 percobaan
    karena wakelock media/notifikasi async androidtvremote2 telat update).
    Push event tv_sleep + log aplikasi lengkap."""
    if alasan is None:
        alasan = "TV dimatikan"
    try:
        if delay:
            time.sleep(delay)
    except Exception:
        pass
    tgt = (port if port else None)

    def _kirim_sleep():
        """Satu putaran usaha matikan TV. Return (hasil, pesan)."""
        hasil, pesan = False, ""
        # 1) atpv2 POWER retry 3x (sama seperti desktop _tv_sleep_now)
        for _ in range(3):
            try:
                ok, out, _ = M.ADBHelper.power_toggle(ip, port=tgt or 0)
                if ok:
                    hasil, pesan = True, "atpv2 POWER terkirim"
                    break
                pesan = str(out)[:120]
            except Exception as e:
                pesan = str(e)
            time.sleep(2)
        # 2) atpv2 SLEEP
        if not hasil:
            try:
                rem = M.ADBHelper._get_remote(ip)
                res = rem.sleep_blocking()
                if res.get("status") == "ok":
                    hasil, pesan = True, "atpv2 SLEEP terkirim"
            except Exception as e:
                pesan = str(e)[:120]
        # 3) fallback ADB keyevent
        if not hasil:
            for kunci in ("KEYCODE_POWER", "KEYCODE_SLEEP", "223"):
                try:
                    ok_adb, out_adb = M.ADBHelper.adb_shell(
                        ip, f"input keyevent {kunci}", timeout=8,
                        port=(tgt or 5555))
                    if ok_adb:
                        hasil, pesan = True, f"fallback ADB keyevent {kunci}: {out_adb[:80]}"
                        break
                except Exception as e:
                    pesan = str(e)[:120]
        return hasil, pesan

    def _cek_layar():
        """Verifikasi status layar (sama seperti desktop), ±9 dtk."""
        state = None
        for _ in range(3):
            time.sleep(3)
            try:
                state = M.ADBHelper.tv_power_state(ip, port=(tgt or 5555))
            except Exception:
                state = None
            if state is False:
                break
            if state is None:
                break
        return state

    hasil, pesan = _kirim_sleep()
    state = None
    if hasil:
        state = _cek_layar()
        if state is False:
            pesan = pesan + " — terverifikasi MATI"
        elif state is True:
            # ─ Bug Fix: retry sekali lagi (paksa keyevent SLEEP eksplisit)
            # sebelum menyerah — TV kadang butuh 2 percobaan (wakelock media
            # / notifikasi androidtvremote2 telat update saat percobaan 1).
            try:
                M.ADBHelper.adb_shell(ip, "input keyevent 223", timeout=8,
                                       port=(tgt or 5555))
            except Exception:
                pass
            time.sleep(2)
            hasil2, pesan2 = _kirim_sleep()
            state2 = _cek_layar() if hasil2 else None
            if state2 is False:
                hasil, pesan = True, pesan2 + " (percobaan ke-2) — terverifikasi MATI"
            elif state2 is None:
                hasil, pesan = True, pesan2 + " (percobaan ke-2) — tanpa verifikasi (tak terdeteksi)"
            else:
                hasil, pesan = False, ("perintah terkirim 2x tapi layar masih nyala "
                                       "(kemungkinan Stay Awake/wakelock media aktif di TV)")
        else:
            pesan = pesan + " — tanpa verifikasi (tak terdeteksi)"
    try:
        STORE.events.append({"type": "tv_sleep", "label": label, "key": key,
                             "kind": "tv", "ok": hasil, "msg": pesan})
        while len(STORE.events) > 60:
            STORE.events.pop(0)
    except Exception:
        pass
    applog(f"[TV SLEEP] {label} ({ip}) | alasan={alasan} | "
           f"{'OK' if hasil else 'GAGAL'} — {pesan}")
    _LOGGER.warning("[TV SLEEP] %s: %s — %s", label,
                    "OK" if hasil else "GAGAL", pesan)
    # --- SMART PLUG: lampu ikut mati saat TV tidur ---
    try:
        STORE._plug_set(label, False)
    except Exception as e:
        _LOGGER.warning("Plug off (sleep) error: %s", e)


@app.route("/api/sesi/<kind>/<key>", methods=["POST"])
@require_auth
def api_sesi(kind, key):
    s = STORE.get_sesi(kind, key)
    if not s:
        return jsonify({"error": "sesi tidak ditemukan"}), 404
    data = request.get_json(silent=True) or {}
    act = data.get("action")
    # ── Lisensi: blokir transaksi BARU bila trial/lisensi habis.
    #    Sesi yang sudah berjalan (pause/resume/selesai/bayar) tetap boleh.
    if act in ("paket", "booking", "member_mulai", "shop"):
        ok_lic, st = STORE._lic_ok()
        if not ok_lic:
            return jsonify({"error": "⛔ Trial habis — Aktifkan lisensi di tab Aktivasi "
                                     "untuk melanjutkan transaksi baru."}), 403
    with STORE._lock:
        if act == "paket":
            paket_nm = data.get("paket", "")
            if not paket_nm:
                return jsonify({"error": "paket wajib diisi"}), 400
            pd = s.paket_data()
            info = pd.get(paket_nm)
            if not info:
                return jsonify({"error": f"paket '{paket_nm}' tidak ada di grup {s.nama_grup}"}), 400
            paket_harga = int(info.get("harga", 0))
            paket_menit = int(info.get("menit", 0))
            pesanan = {str(k): int(v) for k, v in (data.get("pesanan", {}) or {}).items()}
            all_menu = s.all_menu()
            total_pesanan = sum(all_menu.get(nm, 0) * qty for nm, qty in pesanan.items())
            diskoni = int(data.get("diskon", 0) or 0)
            diskoni_mode = data.get("diskon_mode", "nominal")
            try:
                s.start_paket(paket_nm, paket_harga, paket_menit, pesanan, total_pesanan,
                              diskoni=diskoni, diskoni_mode=diskoni_mode,
                              paid=data.get("paid"))
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            if data.get("paid") is not None:
                s.set_paid(bool(data.get("paid")))
            applog(f"[SESI MULAI] {s.label} | total={s.snapshot().get('total')} | "
                   f"paid={s.snapshot().get('paid')} | kasir={STORE.user}")
            return jsonify({"ok": True, "sesi": s.snapshot()})
        if act == "booking":
            # Mulai sesi dari booking online (port _mulai_booking, main.py)
            if s.kind != "tv":
                return jsonify({"error": "Booking hanya untuk kartu TV."}), 400
            if not s.sesi_kosong():
                return jsonify({"error": f"{s.label} masih ada sesi aktif."}), 400
            did = str(data.get("did", "") or "").strip()
            if not did:
                return jsonify({"error": "id booking wajib diisi"}), 400
            try:
                b = FirestoreClient().get_document(f"bookings/{did}") or {}
            except Exception as e:
                return jsonify({"error": f"Gagal ambil booking: {e}"}), 500
            if not b or not str(b.get("status", "")):
                return jsonify({"error": "Booking tidak ditemukan."}), 404
            owner = (STORE._resolve_license_user() or "").strip().lower()
            if str(b.get("owner", "")).strip().lower() != owner:
                return jsonify({"error": "Booking bukan milik akun ini."}), 403
            if str(b.get("status", "")) != "dikonfirmasi":
                return jsonify({"error": "Booking belum dikonfirmasi / ditolak."}), 400
            if str(b.get("perangkat", "") or "").strip() != s.label:
                return jsonify({"error": f"Booking untuk {b.get('perangkat')}, bukan {s.label}."}), 400
            if b.get("sesiDimulai"):
                return jsonify({"error": "Sesi booking sudah pernah dimulai."}), 400
            paket_nm = str(b.get("paket", "") or "")
            pd = s.paket_data()
            info = pd.get(paket_nm)
            if not info:
                return jsonify({"error": f"Paket '{paket_nm}' tidak ada di grup {s.nama_grup}. "
                                         f"Perbarui tarif atau tolak booking."}), 400
            paket_harga = int(info.get("harga", 0))
            paket_menit = int(info.get("menit", 0))
            try:
                pesanan = {str(k): int(v) for k, v in (b.get("pesanan", {}) or {}).items()}
            except Exception:
                pesanan = {}
            all_menu = s.all_menu()
            total_pesanan = sum(all_menu.get(nm, 0) * qty for nm, qty in pesanan.items())
            metode = str(b.get("metode", "") or "")
            sb = str(b.get("statusBayar", "") or "")
            paid = bool(metode == "lunas" or sb == "lunas_transfer")
            try:
                s.start_paket(paket_nm, paket_harga, paket_menit, pesanan, total_pesanan,
                              diskoni=0, diskoni_mode="nominal", paid=paid)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            s.set_paid(paid)
            # Tandai riwayat dengan 📅 + id booking (port _format_riwayat_row booking)
            idx = getattr(s, "_last_transaction_item", None)
            if idx is not None and 0 <= idx < len(STORE.riwayat_transaksi):
                try:
                    row = list(STORE.riwayat_transaksi[idx])
                    row[3] = f"📅 {row[3]}"
                    STORE.riwayat_transaksi[idx] = tuple(row)
                    meta = STORE.riwayat_meta[idx]
                    meta["booking_id"] = did
                    meta["booking_nama"] = str(b.get("namaPelanggan", "") or "")
                    meta["booking_dp"] = int(b.get("nominalDp", 0) or 0)
                    STORE.save_riwayat()
                    threading.Thread(target=STORE._upsert_tx_cloud_from_index,
                                     args=(idx,), daemon=True).start()
                except Exception as e:
                    _LOGGER.warning("Tandai booking di riwayat gagal: %s", e)
            # Tandai booking sudah dimulai (Firestore)
            try:
                FirestoreClient().set_document(
                    f"bookings/{did}",
                    {"sesiDimulai": True, "sesiLabel": s.label,
                     "kasir": STORE.user or "",
                     "updatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                    merge=True)
            except Exception as e:
                _LOGGER.warning("Tandai sesiDimulai gagal: %s", e)
            applog(f"[SESI BOOKING MULAI] {s.label} | {b.get('namaPelanggan', '')} | "
                   f"paket={paket_nm} | total={s.total_setelah_diskon()} | "
                   f"paid={paid} | kasir={STORE.user}")
            return jsonify({"ok": True, "sesi": s.snapshot()})
        if act == "member_mulai":            # Mulai sesi dari saldo waktu member (tanpa paket reguler)
            if not s.sesi_kosong():
                return jsonify({"error": f"{s.label} masih ada sesi aktif."}), 400
            err = STORE.mulai_sesi_member(s, str(data.get("member_hp", "") or ""),
                                          str(data.get("member_pin", "") or ""))
            if err:
                return jsonify({"error": err}), 400
            applog(f"[SESI MULAI] {s.label} | MEMBER {s.member_nama} | "
                   f"sisa={s.sisa_waktu}s | kasir={STORE.user}")
            return jsonify({"ok": True, "sesi": s.snapshot()})
        if act == "member_extend":
            # Tambah waktu sesi member yang berjalan dengan saldo member saat ini
            if not getattr(s, "mode_member", False) or not s.paket_aktif:
                return jsonify({"error": "Bukan sesi member yang aktif."}), 400
            res, err = STORE.verify_member(str(data.get("member_hp", "") or ""),
                                           str(data.get("member_pin", "") or ""))
            if err:
                return jsonify({"error": err}), 401
            if res["hp"] != s.member_hp:
                return jsonify({"error": "PIN bukan milik member sesi ini."}), 403
            saldo = res.get("saldo_menit", 0)
            if saldo <= 0:
                return jsonify({"error": "Saldo member kosong — proses isi ulang dulu."}), 400
            s.sisa_waktu += saldo * 60
            if s._hub_ok():
                try:
                    lunas_now, tagihan_now = s.split_lunas_tagihan()
                    STORE.hub.send_start_timer(s.label, s.sisa_waktu,
                                               s.total_setelah_diskon(),
                                               lunas_total=lunas_now, tagihan_total=tagihan_now,
                                               nama_member=s.member_nama)
                except Exception:
                    pass
            s.store.notify("paket", s.snapshot())
            applog(f"[MEMBER EXTEND] {s.label} | {res['nama']} +{saldo} mnt "
                   f"(saldo belum dipotong; potongan di akhir sesi) | kasir={STORE.user}")
            s.store._sync_timer_state()
            return jsonify({"ok": True, "sesi": s.snapshot()})
        if act == "shop":
            try:
                # Bug Fix 5: pass paid langsung ke tambah_pesanan (per-item),
                # JANGAN panggil set_paid() terpisah — itu override SEMUA item
                # (termasuk paket yang sudah LUNAS ikut ter-flip jadi TAGIHAN).
                s.tambah_pesanan(data.get("pesanan", {}) or {}, paid=data.get("paid"))
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            if data.get("paid") is not None:
                s.paid = s._recalc_paid()
                s._sync_paid_state()
            applog(f"[PESANAN TAMBAH] {s.label} | "
                   f"items={list((data.get('pesanan') or {}).items())} | "
                   f"total={s.snapshot().get('total')} | paid={s.paid} | kasir={STORE.user}")
            return jsonify({"ok": True, "sesi": s.snapshot()})
        if act == "pause":
            s.pause()
            return jsonify({"ok": True, "sesi": s.snapshot()})
        if act == "resume":
            s.resume()
            return jsonify({"ok": True, "sesi": s.snapshot()})
        if act == "selesai":
            # Pilihan kasir di popup Selesaikan Sesi: LUNAS (true) / TAGIHAN (false)
            if data.get("lunas") is not None:
                s.set_paid(bool(data.get("lunas")))
            snap = s.klik_selesai()
            return jsonify({"ok": True, "sesi": snap})
        if act == "paid":
            s.set_paid(bool(data.get("paid", True)))
            return jsonify({"ok": True, "sesi": s.snapshot()})
        if act in ("lock", "unlock"):
            if s.kind != "warnet":
                return jsonify({"error": "hanya untuk sesi warnet"}), 400
            locked = act == "lock"
            if locked:
                s._warnet_queue("LOCK", "manual_off", f"Sesi {s.label} dikunci admin.")
            else:
                s._warnet_queue("UNLOCK", "manual_on", f"Sesi {s.label} dibuka admin.")
            return jsonify({"ok": True, "sesi": s.snapshot()})
        if act == "konfirmasi_habis":
            # Hapus event "habis" yang sudah dikonfirmasi dari antrean UI agar
            # tidak muncul lagi setelah kasir logout → login ulang.
            try:
                STORE.events = [e for e in STORE.events if not (
                    e.get("type") == "habis" and e.get("label") == s.label)]
            except Exception:
                pass
            if s.kind != "tv":
                return jsonify({"ok": True})
            if s._hub_ok():
                try:
                    STORE.hub.send_stop_timer(s.label)
                    STORE.hub.send_unlock_screen(s.label)
                except Exception:
                    pass
            ip = s.ip
            port = int(getattr(s, "port", 0) or 0)
            label = s.label
            key = s.timer_key()
            applog(f"[KONFIRMASI HABIS] {label} | TV dibiarkan menyala "
                   f"(tidur hanya via auto-off {s.ip}:{port} key={key})")
            return jsonify({"ok": True})
        if act == "pindah":
            if s.kind != "tv":
                return jsonify({"error": "Pindah hanya untuk sesi TV"}), 400
            if s.sesi_kosong():
                return jsonify({"error": "Sesi kosong — tidak ada yang bisa dipindah."}), 400
            target = STORE.get_sesi(s.kind, data.get("target", "") or "")
            if not target:
                return jsonify({"error": "TV tujuan tidak ditemukan."}), 404
            if not target.sesi_kosong():
                return jsonify({"error": f"TV {target.label} sedang dipakai."}), 400
            kopas = ["paket_aktif", "is_bebas", "pesanan_aktif", "biaya_pesanan",
                     "paket_harga_tetap", "diskoni", "diskoni_mode", "paid",
                     "menit_dipakai_awal", "sisa_waktu", "waktu_mulai",
                     "_timer_paused", "_paused_total", "daftar_paket_sesi",
                     "lunas_paket", "harga_paket_sesi", "lunas_pesanan",
                     "_last_transaction_item",
                     "mode_member", "member_hp", "member_nama", "member_detik_pakai"]
            for f in kopas:
                setattr(target, f, getattr(s, f, None))
            target._last_transaction_item = s._last_transaction_item
            if s._hub_ok():
                try:
                    STORE.hub.send_stop_timer(s.label)
                    STORE.hub.send_unlock_screen(s.label)
                except Exception:
                    pass
                if not target.is_bebas and target.paket_aktif:
                    try:
                        lunas_now, tagihan_now = target.split_lunas_tagihan()
                        STORE.hub.send_start_timer(target.label, target.sisa_waktu,
                                                   target.total_setelah_diskon(),
                                                   lunas_total=lunas_now, tagihan_total=tagihan_now,
                                                   nama_member=target.member_nama)
                    except Exception:
                        pass
            s.reset()
            STORE.notify("pindah", {"label": s.label})
            return jsonify({"ok": True, "sesi": s.snapshot(),
                            "target": target.snapshot()})
    return jsonify({"error": "aksi tidak dikenal"}), 400


@app.route("/api/struk", methods=["POST"])
@require_auth
def api_struk():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "sesi")
    if mode == "transaksi":
        idx = int(data.get("index", -1))
        if not (0 <= idx < len(STORE.riwayat_transaksi)):
            return jsonify({"error": "index tidak valid"}), 404
        row = STORE.riwayat_transaksi[idx]
        meta = STORE.riwayat_meta[idx]
        pesanan = meta.get("pesanan", {}) or {}
        text = build_struk_text(
            row[2], meta.get("paket_raw", ""), meta.get("paket_harga", 0), None,
            pesanan, meta.get("pesanan_total", 0), meta.get("diskoni", 0),
            meta.get("diskoni_mode", "nominal"), meta.get("total", 0), row[1],
            STORE.menu_makanan, STORE.menu_minuman)
    elif mode == "label":
        label = str(data.get("label", "") or "").strip()
        idx = -1
        for i in range(len(STORE.riwayat_transaksi) - 1, -1, -1):
            try:
                if STORE.riwayat_transaksi[i][2] == label:
                    idx = i
                    break
            except Exception:
                continue
        if idx < 0:
            return jsonify({"error": f"Tidak ada transaksi terakhir untuk {label}."}), 404
        row = STORE.riwayat_transaksi[idx]
        meta = STORE.riwayat_meta[idx] if idx < len(STORE.riwayat_meta) else {}
        pesanan = meta.get("pesanan", {}) or {}
        text = build_struk_text(
            row[2], meta.get("paket_raw", ""), meta.get("paket_harga", 0), None,
            pesanan, meta.get("pesanan_total", 0), meta.get("diskoni", 0),
            meta.get("diskoni_mode", "nominal"), meta.get("total", 0), row[1],
            STORE.menu_makanan, STORE.menu_minuman)
    else:
        kind = data.get("kind")
        key = data.get("key")
        s = STORE.get_sesi(kind, key)
        if not s or s.sesi_kosong():
            return jsonify({"error": "tidak ada sesi aktif"}), 404
        durasi_menit = round((s.sisa_waktu + 59) // 60) if not s.is_bebas else None
        text = build_struk_text(
            s.label, s.paket_aktif, s.paket_harga_tetap, durasi_menit,
            s.pesanan_aktif, s.biaya_pesanan, s.diskoni, s.diskoni_mode,
            s.snapshot()["total"], STORE.user, STORE.menu_makanan, STORE.menu_minuman)
    fpath = None
    if data.get("print", True):
        # Cetak async: BLE bisa butuh beberapa detik — jangan blokir request
        _print_async(text)
        try:
            _lbl = {"label": str(label), "transaksi": str(data.get("index", "?")),
                    "sesi": s.label}[mode]
        except Exception:
            _lbl = "?"
        applog(f"[CETAK STRUK] mode={mode} | {_lbl} | print=True | kasir={STORE.user}")
        return jsonify({"ok": True, "text": text,
                        "msg": "Mengirim struk ke printer…"})
    if mode == "label":
        struk_lbl, struk_total = label, str(meta.get("total", 0))
    elif mode == "transaksi":
        struk_lbl, struk_total = str(row[2]), str(meta.get("total", 0))
    else:
        struk_lbl, struk_total = s.label, str(s.snapshot()["total"])
    applog(f"[CETAK STRUK] mode={mode} | {struk_lbl} | total={struk_total} | "
           f"print={data.get('print', True)} | kasir={STORE.user}")
    return jsonify({"ok": True, "text": text, "file": fpath})


@app.route("/api/tagihan", methods=["POST"])
@require_auth
def api_tagihan():
    data = request.get_json(silent=True) or {}
    label = str(data.get("label", "") or "").strip()
    nama = str(data.get("nama", "") or "").strip()
    hp = str(data.get("hp", "") or "").strip()
    idx_raw = data.get("index")
    if idx_raw is not None:
        try:
            idx = int(idx_raw)
        except Exception:
            return jsonify({"error": "Indeks tidak valid."}), 400
        with STORE._lock:
            if not (0 <= idx < len(STORE.riwayat_meta) and idx < len(STORE.riwayat_transaksi)):
                return jsonify({"error": "Baris tidak ditemukan."}), 404
            meta = STORE.riwayat_meta[idx]
            if meta.get("paid") is not False:
                return jsonify({"error": "Transaksi ini sudah lunas."}), 404
            meta["paid"] = True
            meta["lunas_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            if nama:
                meta["tagihan_nama"] = nama
            if hp:
                meta["tagihan_hp"] = hp
            row = STORE.riwayat_transaksi[idx]
            STORE._refresh_paid_row(idx)
            threading.Thread(target=STORE._upsert_tx_cloud_from_index,
                             args=(idx,), daemon=True).start()
            STORE.save_riwayat()
            applog(f"[TAGIHAN LUNAS] #{idx} | label={row[2]} | kasir={STORE.user}")
            return jsonify({"ok": True, "index": idx, "lunas": True})
    if not label:
        return jsonify({"error": "Label wajib diisi."}), 400
    if data.get("lunas"):
        with STORE._lock:
            for i in range(len(STORE.riwayat_meta) - 1, -1, -1):
                try:
                    meta = STORE.riwayat_meta[i]
                    row = STORE.riwayat_transaksi[i]
                except Exception:
                    continue
                if meta.get("paid") is False and str(row[2]) == label:
                    meta["paid"] = True
                    meta["lunas_at"] = datetime.datetime.now().isoformat(timespec="seconds")
                    STORE._refresh_paid_row(i)
                    threading.Thread(target=STORE._upsert_tx_cloud_from_index,
                                     args=(i,), daemon=True).start()
                    STORE.save_riwayat()
                    applog(f"[TAGIHAN LUNAS] {label} | nama={nama} | hp={hp} | "
                           f"kasir={STORE.user}")
                    return jsonify({"ok": True, "label": label, "lunas": True})
        return jsonify({"error": f"Tidak ada tagihan belum lunas untuk {label}."}), 404
    if not nama or not hp:
        return jsonify({"error": "Nama dan No HP wajib diisi."}), 400
    if not hp.isdigit() or not (8 <= len(hp) <= 15):
        return jsonify({"error": "No HP/WA tidak valid (8–15 digit angka)."}), 400
    with STORE._lock:
        for i in range(len(STORE.riwayat_meta) - 1, -1, -1):
            try:
                meta = STORE.riwayat_meta[i]
                row = STORE.riwayat_transaksi[i]
            except Exception:
                continue
            if meta.get("paid") is False and str(row[2]) == label:
                meta["tagihan_nama"] = nama
                meta["tagihan_hp"] = hp
                meta["tagihan_at"] = datetime.datetime.now().isoformat(timespec="seconds")
                STORE.save_riwayat()
                applog(f"[TAGIHAN BUAT] {label} | nama={nama} | hp={hp} | kasir={STORE.user}")
                return jsonify({"ok": True, "label": label})
        return jsonify({"error": f"Tidak ada tagihan belum lunas untuk {label}."}), 404


@app.route("/api/riwayat")
@require_auth
def api_riwayat():
    kasir = request.args.get("k") or ""
    # Kasir hanya melihat transaksinya sendiri (konsisten dengan desktop).
    if STORE.role != "admin":
        kasir = STORE.user or ""
    return jsonify({"rows": STORE.riwayat(
        request.args.get("q") or "",
        tgl=request.args.get("tgl") or None,
        mode=request.args.get("d") or "0",
        kasir=kasir,
    )})


@app.route("/api/riwayat/kasir")
@require_auth
def api_riwayat_kasir():
    if STORE.role != "admin":
        return jsonify({"kasir": [STORE.user or ""]})
    kasir = set()
    for i in range(min(len(STORE.riwayat_transaksi), len(STORE.riwayat_meta))):
        k = str(STORE.riwayat_transaksi[i][1] or "-")
        if k != "-":
            kasir.add(k)
    return jsonify({"kasir": sorted(kasir)})


@app.route("/api/users", methods=["GET", "POST"])
@require_auth
def api_users():
    if STORE.role != "admin":
        return jsonify({"error": "hanya admin"}), 403
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        res, err = STORE.create_kasir(data.get("username", ""), data.get("password", ""),
                                      data.get("admin_utama", ""))
        if err:
            return jsonify({"error": err}), 400
        return jsonify(res)
    return jsonify({"users": STORE.list_users()})


# ─────────────────────────────────────────────────────────────────────────
#  MEMBER — saldo waktu, isi ulang custom (harga diatur admin)
# ─────────────────────────────────────────────────────────────────────────
@app.route("/api/member", methods=["GET", "POST"])
@require_auth
def api_member():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        res, err = STORE.create_member(data.get("nama", ""), data.get("hp", ""),
                                       data.get("pin", ""), data.get("jenis", "VIP"))
        if err:
            return jsonify({"error": err}), 400
        return jsonify(res)
    return jsonify({"members": STORE.list_members(request.args.get("q", ""))})


@app.route("/api/member/<hp>", methods=["PUT", "DELETE"])
@require_auth
def api_member_edit(hp):
    if STORE.role != "admin":
        return jsonify({"error": "hanya admin"}), 403
    if request.method == "DELETE":
        res, err = STORE.delete_member(hp)
        if err:
            return jsonify({"error": err}), 400
        return jsonify(res)
    data = request.get_json(silent=True) or {}
    res, err = STORE.update_member(hp, nama=data.get("nama"), pin=data.get("pin"),
                                   jenis=data.get("jenis"))
    if err:
        return jsonify({"error": err}), 400
    return jsonify(res)


@app.route("/api/member/verify", methods=["POST"])
@require_auth
def api_member_verify():
    """Cek Nama/No HP + PIN member (untuk mulai sesi & isi ulang)."""
    data = request.get_json(silent=True) or {}
    res, err = STORE.verify_member(data.get("identifier", ""), data.get("pin", ""))
    if err:
        return jsonify({"error": err}), 401
    return jsonify(res)


@app.route("/api/member/topup", methods=["GET", "POST"])
@require_auth
def api_member_topup():
    if request.method == "POST":
        if STORE.role != "admin":
            return jsonify({"error": "hanya admin"}), 403
        data = request.get_json(silent=True) or {}
        res, err = STORE.save_topup_paket(data.get("paket", []),
                                          data.get("jenis", "VIP"))
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"ok": True, "jenis": data.get("jenis", "VIP"), "paket": res})
    return jsonify({"semua": STORE.topup_semua_jenis(),
                    "paket": STORE.topup_paket_list(request.args.get("jenis", "VIP"))})


@app.route("/api/member/topup/beli", methods=["POST"])
@require_auth
def api_member_topup_beli():
    """Kasir memproses pembelian paket isi ulang untuk member."""
    ok_lic, _st = STORE._lic_ok()
    if not ok_lic:
        return jsonify({"error": "⛔ Trial habis — Aktifkan lisensi di tab Aktivasi "
                                 "untuk melanjutkan transaksi baru."}), 403
    data = request.get_json(silent=True) or {}
    res, err = STORE.topup_member(data.get("hp", ""), data.get("paket", ""))
    if err:
        return jsonify({"error": err}), 400
    return jsonify(res)


# ─────────────────────────────────────────────────────────────────────────
#  ADMIN — kelola master data (menu, tarif, TV, warnet, printer), laporan
# ─────────────────────────────────────────────────────────────────────────
def require_admin(fn):
    def wrapper(*args, **kwargs):
        if STORE.role != "admin":
            return jsonify({"error": "hanya admin"}), 403
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper


def _safe(val, default):
    return val if val is not None else default


def _adbres(res, fallback="OK"):
    if isinstance(res, (tuple, list)):
        ok = bool(res[0]) if res else False
        msg = res[1] if len(res) > 1 and res[1] else fallback
        return ok, msg
    return bool(res), fallback


@app.route("/api/settings")
@require_admin
@require_auth
def api_settings_get():
    cfg = M.ConfigManager.load()
    clients = []
    for c in (cfg.get("warnet_clients") or []):
        if isinstance(c, dict):
            cc = dict(c)
            cc.pop("password_hash", None)
            cc.pop("password_enc", None)
            clients.append(cc)
    overlay_setting = _safe(cfg.get("overlay_setting"), {})
    if not overlay_setting or not isinstance(overlay_setting, dict):
        overlay_setting = {"mode": "always", "remaining_minutes": 5}
    return jsonify({
        "menu_makan": _safe(cfg.get("menu_makanan"), {}),
        "menu_minum": _safe(cfg.get("menu_minuman"), {}),
        "stok": _safe(cfg.get("stok"), {}),
        "stok_min": _safe(cfg.get("stok_min"), {}),
        "grup_tarif": _safe(cfg.get("grup_tarif"), {}),
        "grup_tarif_warnet": _safe(cfg.get("grup_tarif_warnet"), {}),
        "daftar_tv": _safe(cfg.get("daftar_tv"), []),
        "daftar_warnet": _safe(cfg.get("daftar_warnet"), []),
        "warnet_clients": clients,
        "printer_settings": _safe(cfg.get("printer_settings"), {}),
        "overlay_setting": overlay_setting,
    })


@app.route("/api/settings/menu", methods=["POST"])
@require_admin
@require_auth
def api_settings_menu():
    data = request.get_json(silent=True) or {}
    cat = data.get("category", "")
    items = data.get("items", {})
    if cat in ("makan", "makanan"):
        key = "menu_makanan"
    elif cat in ("minum", "minuman"):
        key = "menu_minuman"
    else:
        return jsonify({"error": "category harus makan/minum"}), 400
    new_menu = {}
    if isinstance(items, dict):
        for k, v in items.items():
            try:
                new_menu[str(k).strip()] = int(v)
            except Exception:
                return jsonify({"error": f"Harga '{k}' harus angka"}), 400
    cfg = M.ConfigManager.load()
    cfg[key] = new_menu
    M.ConfigManager.save(cfg)
    return jsonify({"ok": True, "menu": new_menu})


@app.route("/api/settings/stok", methods=["POST"])
@require_admin
@require_auth
def api_settings_stok():
    """Simpan stok & stok-minim per kategori: {"makanan": {nama: qty}, "minuman": {...}}.
    items kosong per item = hapus pelacakan (tidak dilacak)."""
    data = request.get_json(silent=True) or {}
    kategori = data.get("category", "")
    if kategori not in ("makanan", "minuman"):
        return jsonify({"error": "category harus makanan/minuman"}), 400
    stok_items = data.get("stok", {}) or {}
    min_items = data.get("stok_min", {}) or {}

    def _norm(raw):
        out = {}
        if not isinstance(raw, dict):
            return out
        for k, v in raw.items():
            nm = str(k).strip()
            if not nm:
                continue
            try:
                out[nm] = max(0, int(v))
            except Exception:
                continue  # kosong/tidak valid = tidak dilacak
        return out

    stok_new = _norm(stok_items)
    min_new = _norm(min_items)

    def _mut(cfg):
        stok = cfg.get("stok", {}) or {}
        if not isinstance(stok, dict):
            stok = {}
        stok[kategori] = stok_new
        cfg["stok"] = stok
        stok_min = cfg.get("stok_min", {}) or {}
        if not isinstance(stok_min, dict):
            stok_min = {}
        stok_min[kategori] = min_new
        cfg["stok_min"] = stok_min
        return cfg

    M.ConfigManager.update(_mut)
    return jsonify({"ok": True, "stok": stok_new, "stok_min": min_new})


@app.route("/api/settings/tarif", methods=["POST"])
@require_admin
@require_auth
def api_settings_tarif():
    data = request.get_json(silent=True) or {}
    grup = str(data.get("grup", "")).strip()
    paket = str(data.get("paket", "")).strip()
    if not grup or not paket:
        return jsonify({"error": "grup & paket wajib diisi"}), 400
    key = "grup_tarif_warnet" if data.get("for_warnet") else "grup_tarif"
    cfg = M.ConfigManager.load()
    groups = dict(cfg.get(key) or {})
    grp = groups.get(grup)
    if not isinstance(grp, dict):
        grp = {}
    if data.get("hapus"):
        grp.pop(paket, None)
        groups[grup] = grp
        cfg[key] = groups
        M.ConfigManager.save(cfg)
        return jsonify({"ok": True})
    try:
        harga = int(data.get("harga", 0))
        menit = int(data.get("menit", 0))
    except Exception:
        return jsonify({"error": "harga & menit harus angka"}), 400
    grp[paket] = {"harga": harga, "menit": menit}
    groups[grup] = grp
    cfg[key] = groups
    M.ConfigManager.save(cfg)
    return jsonify({"ok": True})


@app.route("/api/settings/grup", methods=["POST"])
@require_admin
@require_auth
def api_settings_grup():
    data = request.get_json(silent=True) or {}
    action = data.get("action", "")
    nama = str(data.get("nama", "")).strip()
    if not nama:
        return jsonify({"error": "nama grup wajib"}), 400
    key = "grup_tarif_warnet" if data.get("for_warnet") else "grup_tarif"
    cfg = M.ConfigManager.load()
    groups = dict(cfg.get(key) or {})
    if action == "tambah":
        groups.setdefault(nama, {})
    elif action == "hapus":
        groups.pop(nama, None)
    else:
        return jsonify({"error": "action tambah/hapus"}), 400
    cfg[key] = groups
    M.ConfigManager.save(cfg)
    return jsonify({"ok": True})


@app.route("/api/settings/tv", methods=["POST"])
@require_admin
@require_auth
def api_settings_tv():
    data = request.get_json(silent=True) or {}
    action = data.get("action", "tambah")
    cfg = M.ConfigManager.load()
    daftar = [dict(d) for d in (cfg.get("daftar_tv") or []) if isinstance(d, dict)]
    if action == "hapus":
        ip = str(data.get("ip", "")).strip()
        nama = str(data.get("nama", "")).strip()
        daftar = [d for d in daftar if d.get("ip") != ip or d.get("nama") != nama]
    elif action == "edit":
        ip = str(data.get("ip", "")).strip()
        for d in daftar:
            if d.get("ip") == ip:
                if data.get("nama"):
                    d["nama"] = str(data["nama"]).strip()
                if data.get("nama_grup"):
                    d["nama_grup"] = str(data["nama_grup"]).strip()
                if data.get("port") is not None:
                    try:
                        d["port"] = int(data["port"])
                    except Exception:
                        pass
                if "plug" in data:
                    d["plug"] = data.get("plug") or None
                break
    else:
        ip = str(data.get("ip", "")).strip()
        if not ip or "." not in ip:
            return jsonify({"error": "IP TV wajib diisi & valid"}), 400
        nama = str(data.get("nama", "")).strip() or f"TV {len(daftar) + 1}"
        nama_grup = str(data.get("nama_grup", "")).strip() or M.NAMA_GRUP_DEFAULT
        try:
            port = int(data.get("port", 0) or 0)
        except Exception:
            port = 0
        plug = data.get("plug") or None
        daftar.append({"ip": ip, "nama": nama, "port": port,
                       "nama_grup": nama_grup, "plug": plug})
    cfg["daftar_tv"] = daftar
    M.ConfigManager.save(cfg)
    STORE.load_kartu()
    return jsonify({"ok": True, "daftar_tv": daftar})


# ── PLUG SCAN JOBS (async, mirip PAIRING_JOBS) ────────────────────────────
SCAN_JOBS_LOCK = threading.Lock()
SCAN_JOBS = {}
SCAN_JOBS_TTL = 300  # detik sebelum job scan kedaluwarsa


def _scan_cleanup():
    now = time.time()
    with SCAN_JOBS_LOCK:
        for jid in [j for j, v in SCAN_JOBS.items()
                    if now - v.get("ts", 0) > SCAN_JOBS_TTL]:
            SCAN_JOBS.pop(jid, None)


@app.route("/api/plug/scan", methods=["POST"])
@require_admin
@require_auth
def api_plug_scan():
    """Mulai scan smart plug Tuya di background (async, tidak block Flask).
    Return {ok, job_id}; frontend poll /api/plug/scan/status?id=xxx."""
    try:
        import tinytuya
    except Exception as e:
        return jsonify({"ok": False,
                        "error": "tinytuya belum tersedia: %s" % e}), 500
    _scan_cleanup()
    jid = make_token()
    with SCAN_JOBS_LOCK:
        SCAN_JOBS[jid] = {"status": "running", "devices": [],
                          "error": None, "ts": time.time()}

    def _run():
        try:
            devs = tinytuya.scan(15)  # ≤15 dtk: cukup untuk plug yang merespons lambat
            out = []
            if devs:
                out = [{"device_id": (d.get("gwId") or d.get("id")),
                        "ip": d.get("ip"),
                        "local_key": (d.get("localKey") or d.get("key")),
                        "version": d.get("version")}
                       for d in devs]
            else:
                # tinytuya.scan() return None bila device tidak kirim Local Key
                # (firmware Tuya baru). Baca snapshot.json yang tinytuya tulis
                # agar device tetap terdeteksi (user isi key manual nanti).
                try:
                    snap = os.path.join(APP_DIR, "snapshot.json")
                    if os.path.exists(snap):
                        with open(snap, "r", encoding="utf-8") as f:
                            sj = json.load(f)
                        for d in (sj.get("devices") or []):
                            did = d.get("id") or d.get("gwId")
                            ip = d.get("ip")
                            if did and ip:
                                out.append({
                                    "device_id": did,
                                    "ip": ip,
                                    "local_key": d.get("key") or d.get("localKey") or "",
                                    "version": d.get("ver") or d.get("version"),
                                })
                        try:
                            os.remove(snap)
                        except Exception:
                            pass
                except Exception:
                    pass
            if not out:
                out = []
            with SCAN_JOBS_LOCK:
                SCAN_JOBS[jid] = {"status": "done", "devices": out,
                                  "error": None, "ts": time.time()}
        except Exception as e:
            with SCAN_JOBS_LOCK:
                SCAN_JOBS[jid] = {"status": "error", "devices": [],
                                  "error": str(e), "ts": time.time()}

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "job_id": jid})


@app.route("/api/plug/scan/status", methods=["GET"])
@require_admin
@require_auth
def api_plug_scan_status():
    jid = request.args.get("id", "")
    with SCAN_JOBS_LOCK:
        job = SCAN_JOBS.get(jid)
    if not job:
        return jsonify({"ok": False, "error": "job tidak ditemukan"}), 404
    return jsonify({"ok": True, "status": job["status"],
                    "devices": job["devices"], "error": job["error"]})


@app.route("/api/plug/test", methods=["POST"])
@require_admin
@require_auth
def api_plug_test():
    """Test koneksi smart plug (Tuya butuh key, Shelly cukup IP)."""
    data = request.get_json(silent=True) or {}
    ptype = str(data.get("type") or "tuya").lower()
    ip = str(data.get("ip") or "").strip()
    if not ip:
        return jsonify({"ok": False, "error": "ip wajib diisi"}), 400
    if ptype == "shelly":
        try:
            import requests
        except Exception as e:
            return jsonify({"ok": False,
                            "error": "requests belum tersedia: %s" % e}), 500
        try:
            auth = None
            a = data.get("auth") or {}
            if a.get("user") or a.get("pass"):
                auth = (a.get("user", ""), a.get("pass", ""))
            # coba Gen2 lalu Gen1
            st = None
            try:
                r = requests.get("http://%s/rpc/Switch.Get?id=0" % ip,
                                 auth=auth, timeout=5)
                if r.status_code == 200:
                    j = r.json()
                    if isinstance(j, dict) and ("on" in j or "was_on" in j):
                        st = bool(j.get("on", j.get("was_on", False)))
            except Exception:
                pass
            if st is None:
                r = requests.get("http://%s/relay/0" % ip, auth=auth, timeout=5)
                if r.status_code == 200:
                    j = r.json()
                    st = bool(j.get("ison", False)) if isinstance(j, dict) else None
            if st is None:
                return jsonify({"ok": False,
                                "error": "Shelly tidak merespons (cek IP/Auth/Model)"}), 500
            return jsonify({"ok": True, "state": st, "type": "shelly"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:200]}), 500
    # default: tuya
    dev_id = str(data.get("device_id") or "").strip()
    key = str(data.get("local_key") or "").strip()
    ver = data.get("version") or 3.3
    if not (dev_id and key):
        return jsonify({"ok": False,
                        "error": "device_id & local_key wajib (untuk Tuya)"}), 400
    try:
        import tinytuya
    except Exception as e:
        return jsonify({"ok": False,
                        "error": "tinytuya belum tersedia: %s" % e}), 500
    try:
        d = tinytuya.OutletDevice(dev_id, ip, key)
        d.set_version(float(ver) or 3.3)
        st = d.status()
        on = bool((st.get("dps") or {}).get("1", False))
        return jsonify({"ok": True, "state": on, "type": "tuya"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/api/settings/warnet", methods=["POST"])
@require_admin
@require_auth
def api_settings_warnet():
    data = request.get_json(silent=True) or {}
    action = data.get("action", "tambah")
    cfg = M.ConfigManager.load()
    daftar = [dict(d) for d in (cfg.get("daftar_warnet") or []) if isinstance(d, dict)]
    pc_id = str(data.get("pc_id", "")).strip()
    if action == "hapus":
        daftar = [d for d in daftar if d.get("pc_id") != pc_id]
    elif action == "edit":
        for d in daftar:
            if d.get("pc_id") == pc_id:
                if data.get("nama"):
                    d["nama"] = str(data["nama"]).strip()
                if data.get("nama_grup"):
                    d["nama_grup"] = str(data["nama_grup"]).strip()
                if data.get("client_id") is not None:
                    d["client_id"] = str(data["client_id"]).strip()
                if data.get("pc_ip") is not None:
                    d["pc_ip"] = str(data["pc_ip"]).strip()
                break
    else:
        nama = str(data.get("nama", "")).strip() or f"PC {len(daftar) + 1}"
        if not pc_id:
            return jsonify({"error": "pc_id wajib diisi (mis. PC_1)"}), 400
        daftar.append({
            "nama": nama,
            "nama_grup": str(data.get("nama_grup", "")).strip() or "Warnet",
            "client_id": str(data.get("client_id", "")).strip(),
            "pc_id": pc_id,
            "pc_ip": str(data.get("pc_ip", "")).strip(),
            "pc_locked": False,
        })
    cfg["daftar_warnet"] = daftar
    M.ConfigManager.save(cfg)
    STORE.load_kartu()
    return jsonify({"ok": True, "daftar_warnet": daftar})


@app.route("/api/settings/warnet_client", methods=["POST"])
@require_admin
@require_auth
def api_settings_warnet_client():
    data = request.get_json(silent=True) or {}
    action = data.get("action", "tambah")
    cfg = M.ConfigManager.load()
    clients = [dict(c) for c in (cfg.get("warnet_clients") or []) if isinstance(c, dict)]
    client_id = str(data.get("client_id", "")).strip()
    if action == "hapus":
        clients = [c for c in clients if c.get("client_id") != client_id]
    else:
        password = str(data.get("password", "") or "")
        if not client_id:
            return jsonify({"error": "client_id wajib"}), 400
        idx = next((i for i, c in enumerate(clients) if c.get("client_id") == client_id), None)
        if action == "tambah" and idx is not None:
            return jsonify({"error": "client_id sudah terdaftar"}), 400
        pcs = []
        for p in (data.get("pcs") or []):
            if isinstance(p, dict) and p.get("pc_id"):
                pcs.append({"pc_id": str(p["pc_id"]).strip(),
                            "ip": str(p.get("ip", "")).strip(),
                            "name": str(p.get("name", "")).strip()})
        entry = {
            "client_id": client_id,
            "location": str(data.get("location", "")).strip(),
            "pcs": pcs,
            "allowed_actions": list(data.get("allowed_actions") or ["ON", "OFF", "VOL+", "VOL-"]),
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        if action == "tambah":
            if len(password) < 4:
                return jsonify({"error": "password minimal 4 karakter"}), 400
            entry["password_hash"] = M.hash_password(password)
            entry["password_enc"] = password
            clients.append(entry)
        elif idx is not None:
            old = clients[idx]
            old.update({k: v for k, v in entry.items() if v or k == "pcs"})
            if password:
                old["password_hash"] = M.hash_password(password)
                old["password_enc"] = password
            clients[idx] = old
        else:
            return jsonify({"error": "client_id tidak ditemukan"}), 400
    cfg["warnet_clients"] = clients
    M.ConfigManager.save(cfg)
    return jsonify({"ok": True})


@app.route("/api/settings/printer", methods=["POST"])
@require_admin
@require_auth
def api_settings_printer():
    data = request.get_json(silent=True) or {}
    ptype = str(data.get("type", "file")).strip()
    if ptype not in ("file", "bluetooth", "usb", "network"):
        return jsonify({"error": "type printer tak dikenal"}), 400
    cfg = M.ConfigManager.load()
    cfg["printer_settings"] = {"type": ptype, "address": str(data.get("address", "")).strip()}
    M.ConfigManager.save(cfg)
    return jsonify({"ok": True})


@app.route("/api/settings/overlay", methods=["POST"])
@require_admin
@require_auth
def api_settings_overlay():
    """Simpan pengaturan overlay popup waktu (mode + threshold menit).
    Global untuk semua TV. Push ke Firestore call_meta agar TV sync real-time."""
    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode", "always")).strip()
    if mode not in ("always", "hide", "remaining"):
        return jsonify({"error": "mode harus always/hide/remaining"}), 400
    try:
        remaining_minutes = max(1, min(120, int(data.get("remaining_minutes", 5))))
    except (ValueError, TypeError):
        remaining_minutes = 5
    cfg = M.ConfigManager.load()
    setting = {
        "mode": mode,
        "remaining_minutes": remaining_minutes,
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    cfg["overlay_setting"] = setting
    M.ConfigManager.save(cfg)
    _push_call_meta()
    return jsonify({"ok": True, "setting": setting})


@app.route("/api/printer/scan", methods=["POST"])
@require_auth
def api_printer_scan():
    """Cari printer BLE: 1) perangkat BLE ter-pair Windows (Get-PnpDevice BTHLE),
    2) pindai iklan BLE via BleakScanner. Kembalikan daftar {name,address}."""
    devices = []
    mode = "pnp"
    try:
        import re
        import subprocess
        ps_cmd = ('powershell -NoProfile -Command '
                  '"Get-PnpDevice -PresentOnly -Class Bluetooth | '
                  'Where-Object { $_.InstanceId -like \'BTHLE*\' } | '
                  'ForEach-Object { \"$($_.FriendlyName)`t$($_.InstanceId)\" }"')
        out = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True, timeout=20)
        for line in (out.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            name, iid = (parts[0] or "").strip(), (parts[1] or "").strip()
            if not name or not any(h in name.upper() for h in _BLE_PRINTER_HINTS):
                continue
            m = re.search(r"BTHLE\\DEV_([0-9A-F]{12})", iid.upper())
            addr = ""
            if m:
                mac = m.group(1)
                addr = ":".join(mac[i:i + 2] for i in range(0, 12, 2)).lower()
            devices.append({"name": name, "address": addr})
    except Exception:
        pass
    if not devices:
        mode = "ble"
        try:
            import asyncio
            from bleak import BleakScanner

            async def _scan():
                found = []

                def _cb(_d, _adv):
                    nm = (_d.name or "").strip()
                    if nm and any(h in nm.upper() for h in _BLE_PRINTER_HINTS):
                        found.append({"name": nm, "address": _d.address})

                scanner = BleakScanner(detection_callback=_cb)
                await scanner.start()
                await asyncio.sleep(6)
                await scanner.stop()
                return found
            devices = asyncio.run(_scan())
        except Exception:
            pass
    uniq = {}
    for dv in devices:
        uniq.setdefault((dv.get("name") or "", dv.get("address") or ""), dv)
    return jsonify({"ok": True, "mode": mode, "devices": list(uniq.values())[:20]})


@app.route("/api/settings/password", methods=["POST"])
@require_auth
def api_settings_password():
    data = request.get_json(silent=True) or {}
    old = str(data.get("old", ""))
    new = str(data.get("new", ""))
    users = M.ConfigManager.get("users", {}) or {}
    u = users.get(STORE.user)
    if not isinstance(u, dict):
        # Akun login Google belum punya record lokal → buat sekarang
        u = {"password_enc": "", "role": STORE.role or "admin",
             "admin_utama": "" if (STORE.role or "admin") == "admin" else STORE.user}
        users[STORE.user] = u
        applog(f"[USER BUAT] {STORE.user} dibuat otomatis saat buat password")
    has_pw = bool(u.get("password_enc") or u.get("password"))
    if has_pw:
        # Sudah ada password → wajib verifikasi password lama
        if not M.verify_password(old, u.get("password_enc") or ""):
            return jsonify({"error": "Password lama salah"}), 401
    # Belum punya password (akun Google) → boleh langsung buat
    if len(new) < 6:
        return jsonify({"error": "Password baru minimal 6 karakter"}), 400
    u["password_enc"] = M.hash_password(new)
    cfg = M.ConfigManager.load()
    cfg["users"] = users
    M.ConfigManager.save(cfg)
    applog(f"[PASSWORD] {'buat' if not has_pw else 'ganti'} | user={STORE.user}")
    return jsonify({"ok": True})


@app.route("/api/omzet")
@require_auth
def api_omzet():
    days = 0
    from_ts = to_ts = None
    raw = (request.args.get("days", "0") or "0").strip().lower()
    if raw == "all":
        days = -1
    else:
        try:
            days = int(raw)
        except Exception:
            days = 0
    f = request.args.get("from")
    t = request.args.get("to")
    if f:
        try:
            from_ts = datetime.datetime.strptime(str(f)[:16], "%Y-%m-%d %H:%M").timestamp()
        except Exception:
            from_ts = None
    if t:
        try:
            to_ts = datetime.datetime.strptime(str(t)[:16], "%Y-%m-%d %H:%M").timestamp()
        except Exception:
            to_ts = None
    return jsonify(STORE.omzet(days=days, from_ts=from_ts, to_ts=to_ts))


@app.route("/api/tv/remote", methods=["POST"])
@require_auth
def api_tv_remote():
    data = request.get_json(silent=True) or {}
    key = data.get("key", "")
    action = str(data.get("action", "")).strip() or "power"
    s = STORE.get_sesi("tv", key)
    if not s:
        return jsonify({"error": "TV tidak ditemukan"}), 404
    if not s.ip:
        return jsonify({"error": "TV tidak punya IP"}), 400
    out = {}

    def _run():
        try:
            if action == "power":
                out["ok"], out["msg"] = _adbres(M.ADBHelper.power_toggle(s.ip))
            elif action == "vol_up":
                out["ok"], out["msg"] = _adbres(M.ADBHelper.volume(s.ip, naik=True))
            elif action == "vol_dn":
                out["ok"], out["msg"] = _adbres(M.ADBHelper.volume(s.ip, naik=False))
            elif action == "home":
                out["ok"], out["msg"] = _adbres(M.ADBHelper.home(s.ip))
            else:
                out["ok"], out["msg"] = _adbres(M.ADBHelper.send_key(s.ip, action))
        except Exception as e:
            out["ok"] = False
            out["msg"] = str(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=25)
    if "ok" not in out:
        out.update({"ok": False,
                    "msg": "TV tidak merespon (timeout). Pastikan TV hidup & sudah dipairing lewat aplikasi desktop."})
    return jsonify(out)


# ─────────────────────────────────────────────────────────────────────────
#  PAIRING ANDROID TV (port 6466 + 6467) —
#  port dari flow pairing desktop main.py (ADBHelper.pair_dan_connect).
#  Alur: start -> tunggu PIN di TV -> finish -> (opsional) connect & simpan.
# ─────────────────────────────────────────────────────────────────────────
@app.route("/api/tv/pair/start", methods=["POST"])
@require_admin
@require_auth
def api_tv_pair_start():
    data = request.get_json(silent=True) or {}
    ip = str(data.get("ip", "")).strip()
    if not ip or "." not in ip:
        return jsonify({"error": "IP TV wajib diisi & valid"}), 400
    _pairing_cleanup()
    job = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    with PAIRING_JOBS_LOCK:
        PAIRING_JOBS[job] = {"ip": ip, "state": "starting", "remote": None,
                             "device_name": "", "device_mac": "", "message": "",
                             "ts": time.time()}

    def _worker():
        try:
            res = tv_mesin.pair_tv_sync(ip)
        except Exception as e:
            _LOGGER.warning("Pairing start gagal %s: %s", ip, e)
            with PAIRING_JOBS_LOCK:
                j = PAIRING_JOBS.get(job)
                if j:
                    j["state"] = "error"
                    j["message"] = str(e)
            return
        with PAIRING_JOBS_LOCK:
            j = PAIRING_JOBS.get(job)
            if not j:
                return
            if res.get("status") != "pairing_started":
                j["state"] = "error"
                j["message"] = res.get("message", "Pairing gagal dimulai")
                return
            j["state"] = "awaiting_pin"
            j["remote"] = res.get("remote")
            j["device_name"] = res.get("device_name", "Unknown")
            j["device_mac"] = res.get("device_mac", "Unknown")
        _LOGGER.info("Pairing TV %s dimulai (job %s) — tunggu PIN", ip, job)

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"ok": True, "job": job, "ip": ip})


@app.route("/api/tv/pair/status")
@require_admin
@require_auth
def api_tv_pair_status():
    job = request.args.get("job", "")
    with PAIRING_JOBS_LOCK:
        j = PAIRING_JOBS.get(job)
    if not j:
        return jsonify({"error": "Sesi pairing tidak ditemukan atau kedaluwarsa"}), 404
    return jsonify({
        "state": j["state"],
        "ip": j.get("ip", ""),
        "device_name": j.get("device_name", ""),
        "device_mac": j.get("device_mac", ""),
        "message": j.get("message", ""),
    })


@app.route("/api/tv/pair/finish", methods=["POST"])
@require_admin
@require_auth
def api_tv_pair_finish():
    data = request.get_json(silent=True) or {}
    job = str(data.get("job", ""))
    pin = str(data.get("pin", "")).strip()
    with PAIRING_JOBS_LOCK:
        j = PAIRING_JOBS.get(job)
    if not j or not j.get("remote"):
        return jsonify({"error": "Sesi pairing tidak valid atau kedaluwarsa. Ulangi pairing dari awal."}), 404
    if not pin or len(pin) < 4:
        return jsonify({"error": "PIN wajib diisi (4-6 karakter)"}), 400
    remote = j["remote"]
    ip = j.get("ip", "")
    fin = tv_mesin.finish_pair_sync(remote, pin)
    if fin.get("status") != "paired":
        return jsonify({"error": fin.get("message", "PIN salah atau pairing gagal")}), 400

    connected = False
    conn_msg = ""
    try:
        ok, conn_msg = M.ADBHelper.connect(ip, method="atpv2")
        connected = bool(ok)
    except Exception as e:
        conn_msg = str(e)

    cfg = M.ConfigManager.load()
    daftar = [dict(d) for d in (cfg.get("daftar_tv") or []) if isinstance(d, dict)]
    exists = any(str(d.get("ip", "")).strip() == ip for d in daftar)
    nama = str(data.get("nama", "")).strip() or j.get("device_name") or f"TV {len(daftar) + 1}"
    nama_grup = str(data.get("nama_grup", "")).strip() or M.NAMA_GRUP_DEFAULT
    if not exists:
        try:
            port = int(data.get("port", 0) or 0)
        except Exception:
            port = 0
        daftar.append({"ip": ip, "nama": nama, "port": port, "nama_grup": nama_grup})
        cfg["daftar_tv"] = daftar
        M.ConfigManager.save(cfg)
        STORE.load_kartu()
    with PAIRING_JOBS_LOCK:
        PAIRING_JOBS.pop(job, None)
    return jsonify({"ok": True, "nama": nama, "nama_grup": nama_grup,
                    "connected": connected, "message": conn_msg or "Pairing berhasil"})


@app.route("/api/tv/pair/cancel", methods=["POST"])
@require_admin
@require_auth
def api_tv_pair_cancel():
    data = request.get_json(silent=True) or {}
    job = str(data.get("job", ""))
    with PAIRING_JOBS_LOCK:
        PAIRING_JOBS.pop(job, None)
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────────────────
#  QR PANGILAN OPERATOR — generate/unduh QR per TV + daftar panggilan masuk
#  (popup kasir) — backend call.html (Firestore calls/) diproses poller.
# ─────────────────────────────────────────────────────────────────────────
@app.route("/api/tv/qr", methods=["POST"])
@require_auth
def api_tv_qr():
    data = request.get_json(silent=True) or {}
    nama = str(data.get("nama", "")).strip()
    if not nama:
        return jsonify({"error": "Nama TV wajib diisi"}), 400
    kode = _qr_generate_untuk(nama)
    if not kode:
        return jsonify({"error": "Gagal generate QR — lihat web_app.log"}), 500
    png = _qr_png_data_uri(nama)
    return jsonify({"ok": True, "nama": nama, "kode": kode,
                    "url": _qr_url(nama, kode, _qr_grup_tv(nama)),
                    "png": png or ("/api/tv/qr/png?tv=" + quote(nama))})


@app.route("/api/tv/qr/png")
@require_auth
def api_tv_qr_png():
    tv = str(request.args.get("tv", "") or "").strip()
    if not tv:
        return jsonify({"error": "Param tv wajib"}), 400
    kode = _qr_generate_untuk(tv)
    if not kode:
        return jsonify({"error": "Gagal buat QR"}), 500
    folder = os.path.join(BASE_DIR, "qr_panggilan")
    aman = "".join(c if c.isalnum() or c in " -_" else "_" for c in tv).strip() or "TV"
    path = os.path.join(folder, f"{aman}.png")
    if not os.path.isfile(path):
        _qr_simpan_png(tv, _qr_url(tv, kode, _qr_grup_tv(tv)))
    return send_file(path, mimetype="image/png")


def _qr_cari_sesi(tv):
    """Cari sesi kartu TV berdasar nama (label) dari QR call — port _qr_cari_kartu
    (main.py): cocokkan label persis dulu, lalu "TV <angka>" sebagai fallback."""
    tv_s = str(tv or "").strip()
    if not tv_s:
        return None
    bagi = tv_s.upper()
    for s in STORE.sesi_tv.values():
        lt = str(getattr(s, "label", "") or "").strip().upper()
        if lt == bagi:
            return s
        if tv_s.isdigit() and (lt == f"TV {tv_s}" or lt == f"TV{tv_s}"):
            return s
    return None


def _qr_pak_info(sesi, nama):
    """Cari harga & menit paket di grup kartu TV. Return (harga, menit) —
    port _qr_pak_info (main.py)."""
    try:
        d = sesi.paket_data() or {}
    except Exception:
        d = {}
    if not d:
        return 0, 0
    info = d.get(nama) or {}
    if isinstance(info, dict):
        try:
            return int(info.get("harga", 0) or 0), int(info.get("menit", 0) or 0)
        except Exception:
            return 0, 0
    try:
        return int(info or 0), 0
    except Exception:
        return 0, 0


def _qr_apply_item_ke_kartu(sesi, tipe, nama, qty, harga_item, paid):
    """Terapkan satu item pesanan QR ke kartu TV — port _qr_mark_sudah (main.py):
    paket langsung masuk kartu (tambah waktu + biaya; sesi otomatis mulai kalau
    kosong), makanan/minuman masuk ke tagihan. Return (ok, msg)."""
    if tipe == "paket":
        harga, menit = _qr_pak_info(sesi, nama)
        harga = harga or harga_item
        if harga <= 0:
            return False, f"Paket '{nama}' tidak ada di data tarif grup {sesi.nama_grup}."
        sesi_kosong = sesi.sesi_kosong()
        sesi.start_paket(nama, harga, menit, {}, 0, 0, "nominal", paid=paid)
        lbl = "LUNAS" if paid else "TAGIHAN"
        if sesi_kosong:
            return True, (f"TV {sesi.label}: sesi baru '{nama}' ({M.fmt_rp(harga)}) "
                          f"otomatis berjalan ({menit:g} menit) — {lbl}.")
        return True, (f"TV {sesi.label}: paket '{nama}' +{menit:g} mnt → "
                      f"total {M.fmt_rp(sesi.total_setelah_diskon())} ({lbl}).")
    else:
        # F&B saat kartu KOSONG & LUNAS → catat langsung sebagai transaksi
        # tersendiri di riwayat (pembukuan bersih); tidak menempel ke kartu
        # supaya tidak dihitung dobel saat paket nanti dimulai.
        if sesi.sesi_kosong() and paid:
            subtotal = harga_item * qty
            try:
                sesi.store.catat(sesi.label, nama, {nama: qty}, subtotal,
                                 source="tv", paid=True)
                return True, (f"TV {sesi.label}: {nama} LUNAS "
                              f"({M.fmt_rp(subtotal)}) langsung dicatat di riwayat.")
            except Exception as e:
                _LOGGER.warning("Catat F&B QR langsung gagal: %s", e)
        sesi.tambah_pesanan({nama: qty}, paid=paid)
        lbl = "LUNAS" if paid else "TAGIHAN"
        if sesi.sesi_kosong():
            return True, (f"TV {sesi.label}: {nama} masuk ke tagihan ({lbl}). "
                          "Sesi belum aktif — mulai paket dari kartu TV untuk timer.")
        sub = f"({M.fmt_rp(harga_item * qty)}) " if harga_item else ""
        return True, f"TV {sesi.label}: {nama} masuk ke tagihan {sub}({lbl})."


@app.route("/api/panggilan")
@require_auth
def api_panggilan():
    rows = _qr_log_load()
    rows.sort(key=lambda r: str(r.get("waktu", "")), reverse=True)
    baru = [r for r in rows if str(r.get("status", "")) == "baru"]
    return jsonify({
        "baru": baru[:20],
        "total_baru": len(baru),
        "riwayat": rows[:100],
    })


@app.route("/api/panggilan", methods=["POST"])
@require_auth
def api_panggilan_aksi():
    data = request.get_json(silent=True) or {}
    oid = str(data.get("id", ""))
    action = str(data.get("action", "")).strip()
    if not oid or action not in ("sudah", "belum", "hapus"):
        return jsonify({"error": "action harus sudah/belum/hapus + id"}), 400
    rows = _qr_log_load()
    row = next((r for r in rows if str(r.get("id", "")) == oid), None)
    if row is None:
        return jsonify({"error": "Panggilan tidak ditemukan"}), 404
    if action == "hapus":
        rows = [r for r in rows if str(r.get("id", "")) != oid]
        _qr_log_save(rows)
        return jsonify({"ok": True, "status": "hapus"})
    paid = action == "sudah"
    items = row.get("items") or []
    idx = data.get("idx")
    if idx is None or idx == "" or str(idx) == "all":
        target = list(range(len(items)))
    else:
        try:
            target = [int(idx)]
        except Exception:
            target = [0]
    if not all(0 <= i < len(items) and isinstance(items[i], dict) for i in target):
        return jsonify({"error": "Item tidak ditemukan"}), 404

    # Terapkan item ke kartu TV (paket → tambah waktu & biaya, makanan/minuman →
    # tagihan) — port _qr_mark_sudah (main.py). Hanya item berstatus 'baru'.
    tv = str(row.get("tv", ""))
    sesi = _qr_cari_sesi(tv)
    if sesi is None:
        return jsonify({"error": f"Kartu TV '{tv}' tidak ditemukan di dashboard. "
                        "Tambahkan kartunya dulu, lalu klik lagi."}), 404
    pesan = []
    for i in target:
        it = items[i]
        if str(it.get("status", "baru")) != "baru":
            continue  # sudah diproses sebelumnya — jangan dobel
        tipe = str(it.get("tipe", ""))
        nama = str(it.get("nama", "?"))
        qty = int(it.get("qty", 1) or 1)
        harga_item = int(it.get("harga", 0) or 0)
        ok, msg = _qr_apply_item_ke_kartu(sesi, tipe, nama, qty, harga_item, paid)
        if not ok:
            return jsonify({"error": msg}), 400
        pesan.append(msg)
    if pesan and not sesi.sesi_kosong():
        # Per-item: hanya item baru yang ikut status LUNAS/TAGIHAN —
        # sesi yang sudah lunas TIDAK ikut terflip (beda dengan set_paid).
        sesi.paid = sesi._recalc_paid()
        sesi._sync_paid_state()

    if idx is None or idx == "" or str(idx) == "all":
        for it in items:
            if isinstance(it, dict) and str(it.get("status", "baru")) == "baru":
                it["status"] = "sudah"
                it["paid"] = bool(paid)
                if not paid:
                    it["lunas"] = False
        row["status"] = "selesai" if paid else "tagihan"
        row["paid"] = bool(paid)
        if not paid:
            row["lunas"] = False
    else:
        try:
            idx = int(idx)
        except Exception:
            idx = 0
        if 0 <= idx < len(items) and isinstance(items[idx], dict):
            it = items[idx]
            it["status"] = "sudah"
            it["paid"] = bool(paid)
            if not paid:
                it["lunas"] = False
            if all(str(x.get("status", "baru")) == "sudah" for x in items if isinstance(x, dict)):
                semua_paid = all(bool(x.get("paid", False)) for x in items if isinstance(x, dict))
                row["status"] = "selesai" if semua_paid else "tagihan"
                row["paid"] = semua_paid
            else:
                row["status"] = "baru"
        else:
            return jsonify({"error": "Item tidak ditemukan"}), 404
    row["item"] = row.get("item") or [str(x.get("nama", "")) for x in items if isinstance(x, dict)]
    _qr_log_save(rows)
    return jsonify({"ok": True, "status": row.get("status"), "tv": row.get("tv", ""), "pesan": pesan})


# ─────────────────────────────────────────────────────────────────────
#  INSTALL / UPGRADE APK CLIENT TV VIA ADB (port DialogInstallAPK desktop)
# ─────────────────────────────────────────────────────────────────────
APK_JOBS = {}                                   # job_id -> status dict
APK_JOBS_LOCK = threading.Lock()
APK_PACKAGE = "com.rrbillingpro.tvclient"
APK_URL_DEFAULT = ("https://github.com/dedekemoking-commits/rr_billing_pro_windows/"
                   "releases/latest/download/RRBillingPro-TV.apk")


def _apk_url_terbaru():
    """Sumber APK terbaru: config 'apk_tv_url' → auto-detect GitHub release → bawaan."""
    url = str(M.ConfigManager.get("apk_tv_url") or "").strip()
    if url:
        return url, "config 'apk_tv_url'"
    manifest_url = str(M.ConfigManager.get("update_manifest_url") or "").strip()
    if manifest_url:
        try:
            from scripts import check_update
            found = check_update.find_latest_apk_url(manifest_url)
            if found:
                return found, "GitHub release terbaru"
        except Exception:
            pass
    return APK_URL_DEFAULT, "URL resmi otomatis"


def _apk_job_update(job, pct, msg):
    job["progress"] = max(0, min(100, int(pct or 0)))
    job["message"] = str(msg)


def _apk_job_runner(job_id, ip, apk_path=None, url=None):
    with APK_JOBS_LOCK:
        job = APK_JOBS.get(job_id)
    if not job:
        return
    tmpdir = tempfile.mkdtemp(prefix="rr_web_apk_")
    try:
        def cb(pct, msg):
            _apk_job_update(job, pct, msg)

        if url and not apk_path:
            from scripts import check_update
            apk_path = os.path.join(tmpdir, "tv_client.apk")

            def _dl(d, t):
                pct = int(d * 78 // max(t, 1))
                _apk_job_update(job, pct, f"Mengunduh APK… {pct}%")
            check_update.download_asset(url, apk_path, None, progress_cb=_dl)
            _apk_job_update(job, 80, "Unduhan selesai — memeriksa versi…")
            # Anti-downgrade: bandingkan versionCode sumber vs TV
            try:
                new_code, new_name = check_update.read_apk_version(apk_path)
            except Exception:
                new_code, new_name = None, None
            sukses_c, _stc, _pc = M.ADBHelper.cek_dan_reconnect(ip)
            if new_code is not None and sukses_c:
                ok3, out3 = M.ADBHelper.adb_shell(
                    ip, f"dumpsys package {APK_PACKAGE}")
                m = re.search(r"versionCode=(\d+)", out3 or "")
                cur_code = int(m.group(1)) if m else None
                if cur_code is not None and new_code <= cur_code:
                    job["state"] = "selesai"
                    job["progress"] = 100
                    job["message"] = (f"Tidak perlu upgrade — TV sudah memakai "
                                      f"v{cur_code} (sumber v{new_name or new_code}).")
                    return
        elif not apk_path:
            job["state"] = "gagal"
            job["message"] = "File APK tidak tersedia."
            return

        _apk_job_update(job, 2, "Menghubungkan ADB ke TV…")
        sukses, _st, pesan_c = M.ADBHelper.cek_dan_reconnect(ip)
        if not sukses:
            job["state"] = "gagal"
            job["message"] = (f"TV tidak terhubung ADB ({ip}:5555). "
                              "Pairing/WiFi-ADB TV dulu lalu coba lagi. "
                              + str(pesan_c)[:100])
            return

        _apk_job_update(job, 82, "Memasang APK via ADB… (bisa 1-3 menit)")
        ok, pesan = M.ADBHelper.adb_install_with_progress(ip, apk_path, cb)
        if not ok:
            if "INSTALL_FAILED_VERSION_DOWNGRADE" in (pesan or ""):
                pesan = "Versi APK lebih lama dari yang terpasang di TV — upgrade ditolak."
            job["state"] = "gagal"
            job["message"] = str(pesan)
            return
        versi = ""
        try:
            ok2, out2 = M.ADBHelper.adb_shell(ip, f"dumpsys package {APK_PACKAGE}")
            m = re.search(r"versionName=([0-9.]+)", out2 or "")
            if m:
                versi = m.group(1)
        except Exception:
            pass
        job["state"] = "selesai"
        job["progress"] = 100
        job["message"] = f"✅ APK terpasang di {ip}." + (f" Versi: v{versi}" if versi else "")
    except Exception as e:
        job["state"] = "gagal"
        job["message"] = str(e)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _apk_mulai(label, **kw):
    s = _qr_cari_sesi(label)
    if s is None or not getattr(s, "ip", ""):
        return jsonify({"error": f"TV '{label}' tidak ditemukan / tanpa IP."}), 404
    jid = "apk_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    with APK_JOBS_LOCK:
        APK_JOBS[jid] = {"state": "mulai", "progress": 0,
                         "message": "Menyiapkan…", "tv": label, "ts": time.time()}
    threading.Thread(target=_apk_job_runner,
                     args=(jid, s.ip), kwargs=kw,
                     daemon=True, name=f"ApkJob-{label}").start()
    return jsonify({"ok": True, "job": jid})


@app.route("/api/tv/apk/status")
@require_admin
@require_auth
def api_tv_apk_status():
    label = str(request.args.get("label", "") or "").strip()
    s = _qr_cari_sesi(label)
    if s is None or not getattr(s, "ip", ""):
        return jsonify({"error": f"TV '{label}' tidak ditemukan / tanpa IP."}), 404
    ip = s.ip
    out = {"label": label, "ip": ip,
           "ws_online": bool(getattr(s, "ws_online", False))}
    sukses, _st, pesan = M.ADBHelper.cek_dan_reconnect(ip)
    out["adb"] = bool(sukses)
    if sukses:
        ok, outp = M.ADBHelper.adb_shell(ip, f"dumpsys package {APK_PACKAGE}")
        m_c = re.search(r"versionCode=(\d+)", outp or "")
        m_n = re.search(r"versionName=([0-9.]+)", outp or "")
        out["terpasang"] = bool(ok and (m_c or m_n))
        out["versionCode"] = int(m_c.group(1)) if m_c else None
        out["versionName"] = m_n.group(1) if m_n else None
    else:
        out["terpasang"] = None
        out["pesan"] = str(pesan)[:120]
    return jsonify(out)


@app.route("/api/tv/apk/upload", methods=["POST"])
@require_admin
@require_auth
def api_tv_apk_upload():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".apk"):
        return jsonify({"error": "Pilih file .apk"}), 400
    d = tempfile.mkdtemp(prefix="rr_web_apk_")
    path = os.path.join(d, "tv_client.apk")
    f.save(path)
    return jsonify({"ok": True, "path": path})


@app.route("/api/tv/apk/install", methods=["POST"])
@require_admin
@require_auth
def api_tv_apk_install():
    data = request.get_json(silent=True) or {}
    label = str(data.get("label", "") or "").strip()
    path = str(data.get("path", "") or "").strip()
    if not label or not path or not os.path.isfile(path):
        return jsonify({"error": "label + file APK wajib diisi"}), 400
    return _apk_mulai(label, apk_path=path)


@app.route("/api/tv/apk/upgrade", methods=["POST"])
@require_admin
@require_auth
def api_tv_apk_upgrade():
    data = request.get_json(silent=True) or {}
    label = str(data.get("label", "") or "").strip()
    if not label:
        return jsonify({"error": "label wajib diisi"}), 400
    url, _src = _apk_url_terbaru()
    try:
        M.ConfigManager.set("apk_tv_url", url)
    except Exception:
        pass
    return _apk_mulai(label, url=url)


@app.route("/api/tv/apk/job/<jid>")
@require_admin
@require_auth
def api_tv_apk_job(jid):
    with APK_JOBS_LOCK:
        j = APK_JOBS.get(jid)
        if j is None:
            return jsonify({"error": "job tidak ditemukan"}), 404
        return jsonify(dict(j))


# ─────────────────────────────────────────────────────────────────────────
#  KONEKSI APK CLIENT → TV — panel status, tes, lock/unlock, media promosi,
#  logo lock & scan LAN. Semua lewat hub WebSocket (port 8080) + TvMediaServer.
# ─────────────────────────────────────────────────────────────────────────
MEDIA_JOBS = {}       # job_id -> {"state","message","action","terkirim","ts"}
MEDIA_JOBS_LOCK = threading.Lock()
MEDIA_JOBS_TTL = 900
SCAN_JOBS = {}        # job_id -> {"state","progress","total","results","message","ts"}
SCAN_JOBS_LOCK = threading.Lock()
SCAN_JOBS_TTL = 900


def _lan_ip():
    """IP LAN mesin kasir untuk URL media client TV — port dari main.py
    _get_lan_ip: override config dulu, lalu udp-connect ke IP TV yang dikenal."""
    try:
        manual = M.ConfigManager.load().get("tv_media_ip", "").strip()
        if manual:
            return manual
    except Exception:
        pass
    tv_ips = set()
    try:
        for item in M.ConfigManager.get("daftar_tv", []) or []:
            ip = str(item.get("ip", "")).strip()
            if ip:
                tv_ips.add(ip)
    except Exception:
        pass
    for tip in sorted(tv_ips):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect((tip, 9))
                ip = s.getsockname()[0]
            finally:
                s.close()
            if ip and ip != "0.0.0.0":
                return ip
        except Exception:
            continue
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and ip != "0.0.0.0":
            return ip
    except Exception:
        pass
    return "127.0.0.1"


def _media_url(filename):
    ms = STORE.media
    port = ms.port if ms else 8082
    return f"http://{_lan_ip()}:{port}/media/{quote(filename)}"


def _sanitize_filename(name):
    name = os.path.basename(str(name or "") or "").strip() or "media"
    name = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in name)
    return name or "media"


def _simpan_logo_lock(src_path):
    """Salin logo lock jadi logo_lock.png (PNG, max 1920x1080) di media_promo."""
    ms = STORE.media
    if not ms or not ms.running:
        raise RuntimeError("Server media (port 8082) tidak berjalan.")
    dest = os.path.join(ms.media_dir, "logo_lock.png")
    try:
        if _PILImage is not None:
            img = _PILImage.open(src_path)
            img.load()
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            if img.width > 1920 or img.height > 1080:
                img.thumbnail((1920, 1080), _PILImage.LANCZOS)
            img.save(dest, "PNG")
            return dest
        raise ValueError("PIL tidak tersedia")
    except Exception:
        shutil.copyfile(src_path, dest)
    return dest


def _tv_logo_url():
    ms = STORE.media
    if not ms or not ms.running:
        return ""
    path = os.path.join(ms.media_dir, "logo_lock.png")
    if not os.path.isfile(path):
        return ""
    try:
        versi = int(os.path.getmtime(path))
    except Exception:
        versi = 0
    return f"http://{_lan_ip()}:{ms.port}/media/logo_lock.png?v={versi}"


def _hub_send(s, cmd, *args, **kwargs):
    """Kirim perintah ke client APK TV via hub; return (ok, msg)."""
    hub = STORE.hub
    if not hub or not hub.running:
        return False, "Hub TV (ws :8080) tidak berjalan."
    fn = getattr(hub, cmd, None)
    if fn is None:
        return False, f"Perintah {cmd} tidak dikenal."
    try:
        ok = fn(s.label, *args, **kwargs)
        return bool(ok), ("terkirim" if ok else "client APK tidak terhubung / kehabisan waktu")
    except Exception as e:
        return False, str(e)


def _hub_kirim_media(cmd, *args, target="tv"):
    """Kirim media (SHOW_MEDIA/HIDE_MEDIA) ke satu TV atau broadcast ke semua.

    target='tv' → args=(label, ...) via _hub_send ke sesi TV; target='all' →
    broadcast ke semua client terhubung. Return (ok, msg, n_tv)."""
    hub = STORE.hub
    if not hub or not hub.running:
        return False, "Hub TV (ws :8080) tidak berjalan.", 0
    fn = getattr(hub, cmd, None)
    if fn is None:
        return False, f"Perintah {cmd} tidak dikenal.", 0
    if target == "all":
        if cmd == "send_show_media":
            n = hub.broadcast_show_media(args[0], args[1])
        else:
            n = hub.broadcast_hide_media()
        msg = ("terkirim ke semua TV" if n else "tidak ada client APK terhubung")
        return n > 0, f"{msg} ({n} TV)", n
    try:
        ok = fn(args[0], *args[1:])
        return bool(ok), ("terkirim" if ok else "client APK tidak terhubung / kehabisan waktu"), int(ok)
    except Exception as e:
        return False, str(e), 0


def _lock_detail_tv(s):
    """Rincian tagihan untuk LOCK_SCREEN (port main.py KartuTV._lock_detail)."""
    semua = {**STORE.menu_makanan, **STORE.menu_minuman}
    lunas_pesanan = getattr(s, "lunas_pesanan", None) or {}
    mak = [{"item": f"{qty}x {nm}", "harga": M.fmt_rp(semua.get(nm, 0) * qty),
            "lunas": bool(lunas_pesanan.get(nm, getattr(s, "paid", True)))}
           for nm, qty in s.pesanan_aktif.items() if nm in STORE.menu_makanan]
    minu = [{"item": f"{qty}x {nm}", "harga": M.fmt_rp(semua.get(nm, 0) * qty),
             "lunas": bool(lunas_pesanan.get(nm, getattr(s, "paid", True)))}
            for nm, qty in s.pesanan_aktif.items() if nm in STORE.menu_minuman]
    try:
        lunas_r, tagihan_r = s.split_lunas_tagihan()
    except Exception:
        lunas_r, tagihan_r = 0, 0
    sewa_lunas = all(
        (s.lunas_paket[i] if i < len(s.lunas_paket) else True)
        for i in range(len(s.daftar_paket_sesi or []) or 1))
    # ─ Bug Fix 3: Tampilkan Rp berjalan untuk Main Bebas di popup TV ─
    sewa_harga = s.paket_harga_tetap
    sewa_label = " + ".join(s.daftar_paket_sesi) or (s.paket_aktif or "-")
    if getattr(s, "is_bebas", False) and getattr(s, "waktu_mulai", None):
        try:
            tarif = M.hitung_tarif_per_menit(s.paket_data())
            menit_total = s.menit_dipakai_awal + int((datetime.datetime.now() - s.waktu_mulai).total_seconds() / 60)
            biaya_waktu = tarif * menit_total
            sewa_harga = s.total_setelah_diskon(biaya_waktu + s.biaya_pesanan)
            sewa_label = f"Main Bebas ({menit_total} menit)"
        except Exception:
            pass  # Gunakan nilai default jika error
    # ─ Bug Fix 4: Status LUNAS/TAGIHAN jelas dengan tombol conditional ─
    all_paid = (lunas_r > 0 and tagihan_r == 0)
    return {
        "meja": s.label,
        "sewa": sewa_label,
        "sewa_harga": M.fmt_rp(sewa_harga),
        "sewa_lunas": bool(sewa_lunas),
        "lunas_total": M.fmt_rp(lunas_r),
        "tagihan_total": M.fmt_rp(tagihan_r),
        "all_paid": all_paid,  # Flag untuk disable tombol TAGIHAN jika semua LUNAS
        "makanan": mak,
        "minuman": minu,
        "fnb": M.fmt_rp(s.biaya_pesanan),
        "total": M.fmt_rp(s.total_setelah_diskon()),
        "logo_url": _tv_logo_url(),
        "member_nama": getattr(s, "member_nama", None),  # Nama member tampil di overlay saat member session aktif
    }


def _paired_info(ip):
    """Apakah TV ini sudah pernah dipairing (ada sertifikat pairing)."""
    try:
        cert, _ = tv_mesin._cert_paths_for_ip(ip)
        ok = os.path.isfile(cert)
    except Exception:
        ok = False
    if not ok:
        return {"ok": False}
    try:
        return {"ok": True, "ip": ip,
                "nama": M.ConfigManager.get("daftar_tv", []) and next(
                    (d.get("nama", "") for d in M.ConfigManager.get("daftar_tv", [])
                     if d.get("ip") == ip), "")}
    except Exception:
        return {"ok": True, "ip": ip}


@app.route("/api/tv/status", methods=["GET", "POST"])
@require_auth
def api_tv_status():
    """Panel status koneksi APK → TV. GET = semua kartu TV; POST {key} = satu TV."""
    data = request.get_json(silent=True) or {}
    key = str(data.get("key", "")).strip()
    hub = STORE.hub
    connected = {t.get("meja_id"): t for t in (hub.get_connected_tvs() if hub else [])}
    if key:
        s = STORE.get_sesi("tv", key)
        if not s:
            return jsonify({"error": "TV tidak ditemukan"}), 404
        c = connected.get(s.label) or {}
        return jsonify({
            "label": s.label,
            "nomor": s.nomor,
            "ip": s.ip,
            "ws_online": bool(c),
            "device": c.get("device", ""),
            "address": c.get("address", ""),
            "screen_on": c.get("screen_on"),
            "last_seen": c.get("last_seen", 0),
            "locked": bool(hub and hub.is_locked(s.label)),
            "paired": _paired_info(s.ip),
            "media_server": bool(STORE.media and STORE.media.running),
            "media_aktif": STORE.media.current_file if STORE.media else "",
        })
    out = []
    for s in STORE.sesi_tv.values():
        c = connected.get(s.label) or {}
        out.append({
            "label": s.label,
            "nomor": s.nomor,
            "ip": s.ip,
            "ws_online": bool(c),
            "device": c.get("device", ""),
            "address": c.get("address", ""),
            "screen_on": c.get("screen_on"),
            "last_seen": c.get("last_seen", 0),
            "locked": bool(hub and hub.is_locked(s.label)),
            "paired": _paired_info(s.ip),
            "media_aktif": bool(STORE.media and STORE.media.current_file),
        })
    return jsonify({
        "hub_running": bool(hub and hub.running),
        "media_running": bool(STORE.media and STORE.media.running),
        "media_port": STORE.media.port if STORE.media else 8082,
        "lan_ip": _lan_ip(),
        "media_aktif": STORE.media.current_file if STORE.media else "",
        "tv": out,
    })


@app.route("/api/tv/test", methods=["POST"])
@require_auth
def api_tv_test():
    """Tes koneksi TV: cek WS APK + (opsional) tes lanjutan."""
    data = request.get_json(silent=True) or {}
    s = STORE.get_sesi("tv", data.get("key", ""))
    if not s:
        return jsonify({"error": "TV tidak ditemukan"}), 404
    hub = STORE.hub
    ws = bool(hub and hub.is_meja_connected(s.label))
    out = {"ok": True, "key": s.timer_key(), "label": s.label, "ip": s.ip,
           "ws_online": ws,
            "screen_on": (hub.get_screen_state(s.label) if hub else None),
            "paired": _paired_info(s.ip),
           "media_server": bool(STORE.media and STORE.media.running)}
    if data.get("deep") and s.ip:
        # Tes koneksi sungguhan (connect) di background
        def _run():
            try:
                ok, msg = M.ADBHelper.connect(s.ip, method="atpv2")
                out["atpv2"] = {"ok": bool(ok), "msg": msg}
            except Exception as e:
                out["atpv2"] = {"ok": False, "msg": str(e)}
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=25)
        if "atpv2" not in out:
            out["atpv2"] = {"ok": False, "msg": "TV tidak merespon (timeout)"}
    return jsonify(out)


@app.route("/api/tv/lock", methods=["POST"])
@require_auth
def api_tv_lock():
    data = request.get_json(silent=True) or {}
    s = STORE.get_sesi("tv", data.get("key", ""))
    if not s:
        return jsonify({"error": "TV tidak ditemukan"}), 404
    pesan = str(data.get("pesan", "TV DIKUNCI ADMIN")).strip() or "TV DIKUNCI ADMIN"
    detail = data.get("detail")
    if detail is None:
        detail = _lock_detail_tv(s)
    ok, msg = _hub_send(s, "send_lock_screen", pesan, detail)
    return jsonify({"ok": ok, "message": msg, "terkirim": ok})


@app.route("/api/tv/unlock", methods=["POST"])
@require_auth
def api_tv_unlock():
    data = request.get_json(silent=True) or {}
    s = STORE.get_sesi("tv", data.get("key", ""))
    if not s:
        return jsonify({"error": "TV tidak ditemukan"}), 404
    ok, msg = _hub_send(s, "send_unlock_screen")
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/tv/media", methods=["POST"])
@require_auth
def api_tv_media():
    """Kirim media promosi (video/gambar) ke satu TV atau semua TV.
    Form-data: key=TVA, kind=video|image, target=tv|all, file=<upload>."""
    ms = STORE.media
    if not ms or not ms.running:
        return jsonify({"error": "Server media (port 8082) tidak berjalan."}), 503
    hub = STORE.hub
    if not hub or not hub.running:
        return jsonify({"error": "Hub TV (ws :8080) tidak berjalan."}), 503
    target = str((request.form or {}).get("target", "")).strip()
    if target != "all":
        target = "tv"
    key = str((request.form or {}).get("key", "")).strip()
    s = None
    if target == "tv":
        s = STORE.get_sesi("tv", key)
        if not s:
            return jsonify({"error": "TV tidak ditemukan"}), 404
    kind = str((request.form or {}).get("kind", "")).strip() or "image"
    if kind not in ("video", "image"):
        kind = "image"
    upload = request.files.get("file")
    if not upload or not getattr(upload, "filename", ""):
        return jsonify({"error": "File wajib dipilih"}), 400

    def _valid_video(name):
        return os.path.splitext(name)[1].lower() in (".mp4", ".webm", ".3gp", ".ts")

    def _valid_image(name):
        return os.path.splitext(name)[1].lower() in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")

    if kind == "video" and not _valid_video(upload.filename):
        return jsonify({"error": "Format video didukung: mp4/webm/3gp/ts"}), 400
    if kind == "image" and not _valid_image(upload.filename):
        return jsonify({"error": "Format gambar didukung: jpg/png/gif/bmp/webp"}), 400

    os.makedirs(ms.media_dir, exist_ok=True)
    fname = _sanitize_filename(upload.filename)
    dest = os.path.join(ms.media_dir, fname)
    upload.save(dest)

    if kind == "image":
        ms.set_current("image", fname)
        url = _media_url(fname)
        if target == "tv":
            ok, msg, n_tv = _hub_kirim_media("send_show_media", s.label, "image", url, target="tv")
        else:
            ok, msg, n_tv = _hub_kirim_media("send_show_media", "image", url, target="all")
        return jsonify({"ok": True, "kind": "image", "filename": fname,
                        "url": url, "terkirim": ok, "n_tv": n_tv, "message": msg})

    # Video → proses ffmpeg di background (normalisasi) supaya jalan di semua TV.
    job = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    with MEDIA_JOBS_LOCK:
        MEDIA_JOBS[job] = {"state": "processing", "message": "Menyiapkan video…",
                           "progress": 0, "terkirim": False, "ts": time.time()}

    def _proses_video():
        tmp_out = os.path.join(tempfile.gettempdir(),
                               f"rr_promo_web_{int(time.time() * 1000)}.mp4")
        try:
            action = media_prepare.prepare_video(dest, tmp_out)
            vname = _sanitize_filename(
                os.path.splitext(fname)[0] + "_prepped.mp4")
            vdest = os.path.join(ms.media_dir, vname)
            os.replace(tmp_out, vdest)
            ms.set_current("video", vname)
            url = _media_url(vname)
            if target == "tv":
                ok, msg, n_tv = _hub_kirim_media("send_show_media", s.label, "video", url, target="tv")
            else:
                ok, msg, n_tv = _hub_kirim_media("send_show_media", "video", url, target="all")
            ket = {"copy": "langsung (format sudah kompatibel)",
                   "remux": "dirapikan (faststart)",
                   "transcode": "dikonversi ke H.264 + faststart"}.get(action, action)
            with MEDIA_JOBS_LOCK:
                MEDIA_JOBS[job] = {"state": "done", "message": f"{msg} ({ket})",
                                   "progress": 100, "terkirim": ok, "n_tv": n_tv,
                                   "filename": vname, "url": url, "ts": time.time()}
        except Exception as e:
            # fallback: kirim apa adanya
            try:
                ms.set_current("video", fname)
                url = _media_url(fname)
                if target == "tv":
                    ok, msg, n_tv = _hub_kirim_media("send_show_media", s.label, "video", url, target="tv")
                else:
                    ok, msg, n_tv = _hub_kirim_media("send_show_media", "video", url, target="all")
                with MEDIA_JOBS_LOCK:
                    MEDIA_JOBS[job] = {"state": "done", "message": f"{msg} (dikirim apa adanya — {e})",
                                       "progress": 100, "terkirim": ok, "n_tv": n_tv,
                                       "filename": fname, "url": url, "ts": time.time()}
            except Exception as e2:
                with MEDIA_JOBS_LOCK:
                    MEDIA_JOBS[job] = {"state": "error", "message": str(e2),
                                       "progress": 0, "terkirim": False, "ts": time.time()}
        finally:
            try:
                if os.path.isfile(tmp_out):
                    os.remove(tmp_out)
            except Exception:
                pass

    threading.Thread(target=_proses_video, daemon=True).start()
    return jsonify({"ok": True, "job": job, "kind": "video", "filename": fname})


@app.route("/api/tv/media/status")
@require_auth
def api_tv_media_status():
    job = request.args.get("job", "")
    with MEDIA_JOBS_LOCK:
        j = MEDIA_JOBS.get(job)
    if not j:
        return jsonify({"error": "Job media tidak ditemukan atau kedaluwarsa"}), 404
    return jsonify(j)


@app.route("/api/tv/media/hide", methods=["POST"])
@require_auth
def api_tv_media_hide():
    data = request.get_json(silent=True) or {}
    key = str(data.get("key", "")).strip()
    if key:
        s = STORE.get_sesi("tv", key)
        if not s:
            return jsonify({"error": "TV tidak ditemukan"}), 404
        ok, msg, n_tv = _hub_kirim_media("send_hide_media", s.label, target="tv")
    else:
        # Semua TV
        ok, msg, n_tv = _hub_kirim_media("send_hide_media", target="all")
    if STORE.media:
        try:
            STORE.media.clear_current()
        except Exception:
            pass
    return jsonify({"ok": True, "message": msg, "terkirim": ok})


@app.route("/api/tv/logo", methods=["POST"])
@require_auth
def api_tv_logo():
    """Ubah logo lock screen global lalu broadcast UPDATE_LOGO ke semua TV."""
    upload = request.files.get("file")
    if not upload or not getattr(upload, "filename", ""):
        return jsonify({"error": "File gambar wajib dipilih"}), 400
    if os.path.splitext(upload.filename)[1].lower() not in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"):
        return jsonify({"error": "Format logo: jpg/png/gif/bmp/webp"}), 400
    tmp = os.path.join(tempfile.gettempdir(), f"logo_up_{int(time.time() * 1000)}")
    try:
        upload.save(tmp)
        _simpan_logo_lock(tmp)
    except Exception as e:
        return jsonify({"error": f"Gagal menyimpan logo: {e}"}), 500
    finally:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass
    try:
        logo_url = _tv_logo_url()
        hub = STORE.hub
        n = hub.broadcast_update_logo(logo_url) if hub else 0
        return jsonify({"ok": True, "url": logo_url, "dikirim": n,
                        "message": f"Logo diganti & dikirim ke {n} TV."})
    except Exception as e:
        return jsonify({"error": f"Gagal broadcast logo: {e}"}), 500


# ── Scan TV di LAN ──────────────────────────────────────────────────────────
def _scan_one(ip):
    """Cek satu IP: ping, lalu port ADB (5555) / pairing ATV (6467, 6466)."""
    if not _ping(ip, timeout=1.5):
        return None
    hostname = ""
    try:
        hostname = socket.gethostbyaddr(ip)[0]
    except Exception:
        pass
    if _port_open(ip, 5555, 0.6):
        return {"ip": ip, "hostname": hostname, "adb": True, "atv_pairing": False}
    if _port_open(ip, 6467, 0.6) or _port_open(ip, 6466, 0.6):
        return {"ip": ip, "hostname": hostname, "adb": False, "atv_pairing": True}
    return None


def _ping(ip, timeout=1.5):
    try:
        r = subprocess.run(
            ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip],
            capture_output=True, text=True, timeout=timeout + 1,
            creationflags=0x08000000)
        return r.returncode == 0
    except Exception:
        return False


def _port_open(ip, port, timeout=0.5):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False


def _subnet_detect():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        parts = ip.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
    except Exception:
        pass
    return "192.168.1.0/24"


@app.route("/api/scan", methods=["POST"])
@require_auth
def api_tv_scan_start():
    """Mulai scan LAN untuk menemukan TV / ADB TV? (background, progress)."""
    data = request.get_json(silent=True) or {}
    subnet = str(data.get("subnet", "")).strip() or _subnet_detect()
    if "/" not in subnet:
        subnet = f"{subnet.replace(' ', '')}/24"
    try:
        import ipaddress
        net = ipaddress.ip_network(subnet, strict=False)
    except Exception:
        return jsonify({"error": "Subnet tidak valid, contoh: 192.168.1.0/24"}), 400
    job = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    with SCAN_JOBS_LOCK:
        SCAN_JOBS[job] = {"state": "running", "subnet": str(net),
                          "progress": 0, "total": 0, "results": [],
                          "message": "", "ts": time.time()}

    import concurrent.futures as _cf

    def _worker():
        hosts = list(net.hosts())
        total = len(hosts)
        results = []
        done = [0]
        with _cf.ThreadPoolExecutor(max_workers=64) as ex:
            futs = {}
            for ip in hosts:
                futs[ex.submit(_scan_one, str(ip))] = str(ip)
            for fut in _cf.as_completed(futs):
                try:
                    r = fut.result()
                except Exception:
                    r = None
                if r:
                    results.append(r)
                done[0] += 1
                with SCAN_JOBS_LOCK:
                    j = SCAN_JOBS.get(job)
                    if j:
                        j["progress"] = done[0]
                        j["total"] = total
        results.sort(key=lambda x: [int(o) for o in x["ip"].split(".")])
        with SCAN_JOBS_LOCK:
            if job in SCAN_JOBS:
                SCAN_JOBS[job].update({"state": "done", "results": results, "progress": total})
                SCAN_JOBS[job]["message"] = f"{len(results)} perangkat ditemukan"

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"ok": True, "job": job, "subnet": str(net)})


@app.route("/api/scan/status")
@require_auth
def api_tv_scan_status():
    job = request.args.get("job", "")
    with SCAN_JOBS_LOCK:
        j = SCAN_JOBS.get(job)
    if not j:
        return jsonify({"error": "Scan tidak ditemukan atau kedaluwarsa"}), 404
    return jsonify({k: j[k] for k in ("state", "subnet", "progress", "total", "results", "message")})


@app.route("/api/devices")
@require_auth
def api_devices():
    hub = STORE.hub
    tvs = [dict(x) for x in (hub.get_connected_tvs() if hub else [])]
    warnet = STORE.warnet.get_clients_online() if STORE.warnet else []
    return jsonify({
        "tv": tvs,
        "warnet": warnet,
        "hub_running": bool(hub and hub.running),
        "warnet_running": bool(STORE.warnet and STORE.warnet._running),
        "media_running": bool(STORE.media and STORE.media.running),
        "lan_ip": _lan_ip(),
    })


# ─────────────────────────────────────────────────────────────────────────
#  PROFIL RENTAL & USER (tab Profil — port _setup_profil/_simpan_profil_rental)
# ─────────────────────────────────────────────────────────────────────────
PROFIL_KEYS = ("nama_rental", "nama_pemilik", "hp", "email", "alamat",
               "nama_dana", "no_dana", "logo", "qr_pembayaran")


def _profil_saya():
    cfg = M.ConfigManager.load()
    pus = (cfg.get("profil_rental", {}) or {}).get(STORE.user, {}) or {}
    return pus if isinstance(pus, dict) else {}


@app.route("/api/profil")
@require_auth
def api_profil():
    pus = _profil_saya()
    sec = M.ConfigManager.load().get("security") or {}
    pin = str(sec.get("pin_hapus") or "").strip() if isinstance(sec, dict) else ""
    _cfg = M.ConfigManager.load()
    _users = _cfg.get("users") or {}
    _u = _users.get(STORE.user) or {} if isinstance(_users, dict) else {}
    theme = str(_u.get("theme", "") or "").strip() if isinstance(_u, dict) else ""
    if theme not in ("cyan", "synth", "carbon", "sunset", "ocean", "neon-green", "neon-pink", "neon-yellow", "neon-orange", "neon-blue", "neon-purple", "neon-red"):
        theme = "cyan"
    bg_path = str(M.ConfigManager.get("app_bg_image", "") or "")
    try:
        lisensi_pesan = LicenseManager.get_status(
            current_user=STORE._resolve_license_user()).get("pesan", "-")
    except Exception:
        lisensi_pesan = "-"
    return jsonify({
        "username": STORE.user,
        "role": STORE.role,
        "admin": STORE.role == "admin",
        "profil": {k: (pus.get(k) or "") for k in PROFIL_KEYS},
        "has_pin": bool(pin),
        "pin_updated": (sec.get("pin_hapus_updated", "") if isinstance(sec, dict) else ""),
        "qr_page_url": str((_cfg.get("qr_page_url") or "") or "").strip(),
        "theme": theme,
        "versi": WEB_APP_VERSION,
        "developer": "RR CCTV",
        "kontak": "0812-7064-7744",
        "website": "rrcctv.online",
        "lisensi": lisensi_pesan,
        "bg_url": ("/api/bg" if bg_path and os.path.isfile(bg_path) else ""),
    })


@app.route("/api/profil", methods=["POST"])
@require_admin
@require_auth
def api_profil_save():
    """Simpan profil rental user aktif + push call_meta (halaman web pelanggan)."""
    data = request.get_json(silent=True) or {}
    cfg = M.ConfigManager.load()
    profil = cfg.get("profil_rental", {}) or {}
    if not isinstance(profil, dict):
        profil = {}
    lama = profil.get(STORE.user, {}) or {}
    if not isinstance(lama, dict):
        lama = {}
    for k in PROFIL_KEYS:
        if k not in data:
            continue
        v = data.get(k)
        if k in ("logo", "qr_pembayaran"):
            lama[k] = str(v or "").strip()
        else:
            lama[k] = M.sanitize_text(str(v or ""))
    profil[STORE.user] = lama
    cfg["profil_rental"] = profil
    theme = str(data.get("theme", "") or "").strip()
    if theme in ("cyan", "synth", "carbon", "sunset", "ocean", "neon-green", "neon-pink", "neon-yellow", "neon-orange", "neon-blue", "neon-purple", "neon-red"):
        users = cfg.get("users") or {}
        if not isinstance(users, dict):
            users = {}
        u = users.get(STORE.user)
        if isinstance(u, dict):
            u["theme"] = theme
            cfg["users"] = users
    M.ConfigManager.save(cfg)
    _push_call_meta()
    if STORE.hub and STORE.hub.running:
        try:
            STORE.hub.broadcast_update_rental(lama.get("nama_rental", ""))
        except Exception:
            pass
    return jsonify({"ok": True, "profil": {k: (lama.get(k) or "") for k in PROFIL_KEYS}})


def _push_call_meta():
    """Port _qr_push_menu_bg (main.py): push menu/nama rental ke Firestore
    call_meta/<owner> — dipakai halaman web pelanggan (rrcctv.online/b/<user>)."""

    def worker():
        try:
            owner = STORE._resolve_license_user()
            if not owner:
                return
            pus = _profil_saya()
            nama_rental = str(pus.get("nama_rental", "") or "").strip() or "RR Billing Pro"
            paket_grup = {}
            for g in STORE.daftar_grup_tv():
                d = STORE.paket_data(g)
                if d:
                    paket_grup[g] = {
                        n: {"harga": int(v.get("harga", 0) if isinstance(v, dict) else v),
                            "menit": int(v.get("menit", 60) if isinstance(v, dict) else 60)}
                        for n, v in d.items()
                    }
            cfg = M.ConfigManager.load()
            data = {
                "nama_rental": nama_rental,
                "logo": str(pus.get("logo", "") or "").strip(),
                "daftar_tv": [str(x.get("nama", "")) for x in (cfg.get("daftar_tv") or []) if isinstance(x, dict)],
                "paket_grup": paket_grup,
                "makanan": dict(STORE.menu_makanan),
                "minuman": dict(STORE.menu_minuman),
                "stok": STORE.stok,
                "stok_min": STORE.stok_min,
                "updatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            for k in ("nama_dana", "no_dana", "alamat"):
                v = str(pus.get(k, "") or "").strip()
                if v:
                    data[k] = v
            if str(pus.get("qr_pembayaran", "") or "").strip():
                data["qr_pembayaran"] = str(pus.get("qr_pembayaran", "")).strip()
            # Status operasional: situs booking pakai ini untuk menonaktifkan
            # tanggal libur di kalender & menampilkan jam buka saat tutup.
            _ops = _booking_ops()
            data["booking_ops"] = {
                "mode": str(_ops.get("mode", "buka")),
                "jam_buka": str(_ops.get("jam_buka", "08:00")),
                "jam_tutup": str(_ops.get("jam_tutup", "22:00")),
                "libur_mulai": str(_ops.get("libur_mulai", "")),
                "buka_kembali": str(_ops.get("buka_kembali", "")),
            }
            # Push overlay setting (timer popup configuration untuk semua TV)
            overlay_setting = cfg.get("overlay_setting")
            if overlay_setting and isinstance(overlay_setting, dict):
                data["overlay_setting"] = {
                    "mode": str(overlay_setting.get("mode", "always")),
                    "remaining_minutes": int(overlay_setting.get("remaining_minutes", 5)),
                }
            FirestoreClient().set_document(f"call_meta/{owner}", data, merge=True)
        except Exception as e:
            _LOGGER.warning("Push call_meta gagal: %s", e)

    threading.Thread(target=worker, daemon=True).start()


# ── PIN keamanan (hapus TV & kursi warnet) ──────────────────────────────
@app.route("/api/pin", methods=["POST"])
@require_admin
@require_auth
def api_pin():
    data = request.get_json(silent=True) or {}
    act = str(data.get("action", "") or "").strip()
    cfg = M.ConfigManager.load()
    sec = dict(cfg.get("security") or {}) if isinstance(cfg.get("security"), dict) else {}
    if act == "set":
        pin = str(data.get("pin", "") or "").strip()
        if not pin.isdigit() or len(pin) != 4:
            return jsonify({"error": "PIN harus tepat 4 digit angka"}), 400
        sec["pin_hapus"] = pin
        sec["pin_hapus_updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    elif act == "hapus":
        sec.pop("pin_hapus", None)
        sec.pop("pin_hapus_updated", None)
    elif act == "lihat":
        return jsonify({"ok": True, "pin": sec.get("pin_hapus", "")})
    else:
        return jsonify({"error": "action harus set/hapus/lihat"}), 400
    cfg["security"] = sec
    M.ConfigManager.save(cfg)
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────────────────
#  BOOKING ONLINE (tab Booking — port _booking_riwayat_* / _simpan_profil_rental)
# ─────────────────────────────────────────────────────────────────────────
def _booking_ops():
    """Status operasional rental untuk booking (buka/libur/tutup + jam buka)."""
    ops = dict(M.ConfigManager.get("booking_ops", {}) or {})
    if not str(ops.get("jam_buka", "") or "").strip():
        ops["jam_buka"] = "08:00"
    if not str(ops.get("jam_tutup", "") or "").strip():
        ops["jam_tutup"] = "22:00"
    if not str(ops.get("mode", "") or "").strip():
        ops["mode"] = "buka"
    return ops


def _booking_ops_push():
    """Push status operasional ke Firestore (rental_status/{owner}) supaya
    situs booking pelanggan bisa menampilkan pemberitahuan libur/tutup/jam buka."""
    try:
        owner = (STORE._resolve_license_user() or "").strip().lower()
        if not owner:
            return
        data = dict(_booking_ops())
        data["owner"] = owner
        data["updatedAt"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        FirestoreClient().set_document(f"rental_status/{owner}", data, merge=True)
        applog(f"[BOOKING OPS] push rental_status/{owner} mode={data.get('mode')}")
    except Exception as e:
        _LOGGER.warning("Push rental_status gagal: %s", e)


@app.route("/api/booking/ops")
@require_auth
def api_booking_ops_get():
    return jsonify({"ops": _booking_ops()})


@app.route("/api/booking/ops", methods=["POST"])
@require_admin
@require_auth
def api_booking_ops_set():
    """Aksi status booking: libur / tutup / buka / jam.
    - libur: {libur_mulai: YYYY-MM-DD, buka_kembali: YYYY-MM-DD} → situs menampilkan tanggal buka kembali.
    - tutup: rental offline sementara → situs menampilkan jam buka rental.
    - buka : normal kembali.   - jam: set jam_buka & jam_tutup default."""
    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "") or "").strip()
    ops = _booking_ops()
    nows = datetime.datetime.now()
    if action == "libur":
        mulai = str(data.get("libur_mulai", "") or "").strip() or nows.strftime("%Y-%m-%d")
        kembali = str(data.get("buka_kembali", "") or "").strip()
        for v in (mulai, kembali):
            if v:
                try:
                    datetime.datetime.strptime(v, "%Y-%m-%d")
                except ValueError:
                    return jsonify({"error": "format tanggal harus YYYY-MM-DD"}), 400
        if kembali and kembali < mulai:
            return jsonify({"error": "Tanggal buka kembali tidak boleh sebelum tanggal libur."}), 400
        ops.update({"mode": "libur", "libur_mulai": mulai, "buka_kembali": kembali})
    elif action == "tutup":
        ops["mode"] = "tutup"
        ops["libur_mulai"] = ""
        ops["buka_kembali"] = ""
    elif action == "buka":
        ops["mode"] = "buka"
        ops["libur_mulai"] = ""
        ops["buka_kembali"] = ""
    elif action == "jam":
        jb = str(data.get("jam_buka", "") or "").strip()
        jt = str(data.get("jam_tutup", "") or "").strip()
        for v in (jb, jt):
            try:
                datetime.datetime.strptime(v, "%H:%M")
            except ValueError:
                return jsonify({"error": "format jam harus HH:MM"}), 400
        if jb >= jt:
            return jsonify({"error": "Jam buka harus lebih awal dari jam tutup."}), 400
        ops["jam_buka"], ops["jam_tutup"] = jb, jt
    else:
        return jsonify({"error": "action harus libur/tutup/buka/jam"}), 400
    ops["updated"] = nows.strftime("%Y-%m-%d %H:%M:%S")
    M.ConfigManager.set("booking_ops", ops)
    threading.Thread(target=_booking_ops_push, daemon=True).start()
    threading.Thread(target=_push_call_meta, daemon=True).start()
    return jsonify({"ok": True, "ops": ops})


@app.route("/api/booking/ops/beacon", methods=["POST"])
def api_booking_ops_beacon():
    """Dikirim navigator.sendBeacon saat tab kasir (admin, mode BUKA) ditutup:
    set rental TUTUP otomatis. Token lewat query string — sendBeacon tak bisa
    memasang header. Popup 'Rental Belum Buka' saat app dibuka lagi menutup
    loop-nya bila kasir salah tutup/refresh."""
    tok = request.args.get("token", "").strip()
    if not tok or tok not in TOKENS:
        return "", 401
    try:
        ops = _booking_ops()
        if str(ops.get("mode", "buka")) == "buka":
            ops["mode"] = "tutup"
            ops["libur_mulai"] = ""
            ops["buka_kembali"] = ""
            ops["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            M.ConfigManager.set("booking_ops", ops)
            threading.Thread(target=_booking_ops_push, daemon=True).start()
            applog("[BOOKING OPS] auto-TUTUP via beacon (tab kasir ditutup)")
    except Exception as e:
        _LOGGER.warning("Beacon tutup error: %s", e)
    return "", 204


@app.route("/api/booking/ops/local-close", methods=["POST"])
def api_booking_ops_local_close():
    """Khusus jendela aplikasi kasir (wrapper pywebview): dipanggil saat jendela
    ditutup → set rental TUTUP otomatis. Aman karena Flask bind ke 127.0.0.1."""
    try:
        ops = _booking_ops()
        if str(ops.get("mode", "buka")) == "buka":
            ops["mode"] = "tutup"
            ops["libur_mulai"] = ""
            ops["buka_kembali"] = ""
            ops["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            M.ConfigManager.set("booking_ops", ops)
            threading.Thread(target=_booking_ops_push, daemon=True).start()
            threading.Thread(target=_push_call_meta, daemon=True).start()
            applog("[BOOKING OPS] auto-TUTUP via jendela aplikasi ditutup")
    except Exception as e:
        _LOGGER.warning("Local close error: %s", e)
    return "", 204


@app.route("/api/booking")
@require_auth
def api_booking_list():
    """Daftar booking milik owner (admin atau admin_utama kasir) dari Firestore."""
    owner = (STORE._resolve_license_user() or "").strip().lower()
    if not owner:
        return jsonify({"rows": [], "owner": ""})
    try:
        docs = FirestoreClient().query_all("bookings", limit=100, order_field="createdAt") or []
    except Exception as e:
        _LOGGER.warning("Booking list error: %s", e)
        docs = []
    rows = []
    for d in docs:
        if str(d.get("owner", "")).strip().lower() != owner:
            continue
        bukti = str(d.get("bukti", "") or "")
        rows.append({
            "_id": str(d.get("_id", "")),
            "namaPelanggan": str(d.get("namaPelanggan", "") or ""),
            "noHp": str(d.get("noHp", "") or ""),
            "perangkat": str(d.get("perangkat", "") or ""),
            "tanggal": str(d.get("tanggal", "") or ""),
            "jam": str(d.get("jam", "") or ""),
            "metode": str(d.get("metode", "") or ""),
            "statusBayar": str(d.get("statusBayar", "") or ""),
            "sisaBayar": int(d.get("sisaBayar", 0) or 0),
            "totalHarga": int(d.get("totalHarga", 0) or 0),
            "status": str(d.get("status", "") or ""),
            "createdAt": str(d.get("createdAt", "") or ""),
            "updatedAt": str(d.get("updatedAt", "") or ""),
            "alasan": str(d.get("alasan", "") or ""),
            "kasir": str(d.get("kasir", "") or ""),
            "bukti": bukti if bukti.startswith("data:image/") else "",
        })
    rows.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
    return jsonify({"rows": rows, "owner": owner, "username": STORE.user,
                    "ops": _booking_ops()})


@app.route("/api/booking/aktif")
@require_auth
def api_booking_aktif():
    """Booking valid untuk satu label TV: status dikonfirmasi, belum
    sesiDimulai, jam mulai belum lewat — port _booking_fetch_valid (main.py)."""
    label = str(request.args.get("label", "") or "").strip()
    if not label:
        return jsonify({"rows": [], "label": ""})
    owner = (STORE._resolve_license_user() or "").strip().lower()
    rows = []
    if owner:
        try:
            docs = FirestoreClient().query_all("bookings", limit=100,
                                               order_field="createdAt") or []
        except Exception as e:
            _LOGGER.warning("Booking aktif error: %s", e)
            docs = []
        now = datetime.datetime.now()
        for d in docs:
            if str(d.get("owner", "")).strip().lower() != owner:
                continue
            if str(d.get("status", "")) != "dikonfirmasi":
                continue
            if str(d.get("perangkat", "") or "").strip() != label:
                continue
            if d.get("sesiDimulai"):
                continue
            tgl = str(d.get("tanggal", "") or "").strip()
            jam = str(d.get("jam", "") or "").strip()[:5]
            try:
                mulai = datetime.datetime.strptime(f"{tgl} {jam}", "%Y-%m-%d %H:%M")
            except ValueError:
                mulai = None
            if mulai is not None and mulai < now:
                continue  # jam sudah lewat → buang (sama seperti desktop)
            rows.append({
                "_id": str(d.get("_id", "")),
                "namaPelanggan": str(d.get("namaPelanggan", "") or ""),
                "noHp": str(d.get("noHp", "") or ""),
                "perangkat": str(d.get("perangkat", "") or ""),
                "tanggal": tgl,
                "jam": jam,
                "grup": str(d.get("grup", "") or ""),
                "paket": str(d.get("paket", "") or ""),
                "pesanan": d.get("pesanan", {}) or {},
                "metode": str(d.get("metode", "") or ""),
                "statusBayar": str(d.get("statusBayar", "") or ""),
                "sisaBayar": int(d.get("sisaBayar", 0) or 0),
                "nominalDp": int(d.get("nominalDp", 0) or 0),
                "totalHarga": int(d.get("totalHarga", 0) or 0),
            })
        rows.sort(key=lambda x: x.get("jam", ""))
    return jsonify({"rows": rows, "label": label})


def _booking_menit(grup, paket):
    """Durasi booking (menit) dari tarif grup; default 60 jika tak dikenal."""
    cfg = M.ConfigManager.load()
    tarif = (cfg.get("grup_tarif", {}) or {}).get(str(grup or "")) \
            or (cfg.get("grup_tarif_warnet", {}) or {}).get(str(grup or "")) or {}
    try:
        m = int(((tarif.get(str(paket or "")) or {}).get("menit")) or 0)
    except Exception:
        m = 0
    return m if m > 0 else 60


def _booking_range(b):
    """(mulai, akhir) datetime dari dokumen booking; None jika tidak valid."""
    tgl = str(b.get("tanggal", "") or "").strip()
    jam = str(b.get("jam", "") or "").strip()[:5]
    try:
        mulai = datetime.datetime.strptime(f"{tgl} {jam}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return mulai, mulai + datetime.timedelta(minutes=_booking_menit(b.get("grup"), b.get("paket")))


def _booking_overlaps(fc, owner, perangkat, tanggal, mulai, akhir, exclude_id=""):
    """Daftar booking aktif lain (baru/dikonfirmasi) yang bentrok waktu pada TV sama."""
    out = []
    try:
        docs = fc.query_all("bookings", limit=100, order_field="createdAt") or []
    except Exception as e:
        _LOGGER.warning("Booking overlap query error: %s", e)
        return out
    for d in docs:
        if str(d.get("_id", "")) == exclude_id:
            continue
        if str(d.get("owner", "")).strip().lower() != owner:
            continue
        if str(d.get("perangkat", "") or "").strip() != perangkat:
            continue
        if str(d.get("tanggal", "") or "").strip() != tanggal:
            continue
        if str(d.get("status", "")) == "ditolak":
            continue
        r = _booking_range(d)
        if r and mulai < r[1] and r[0] < akhir:
            out.append((d, r))
    return out


def _booking_bentrok_msg(fc, did):
    """Pesan bentrok untuk konfirmasi booking did, atau None jika aman."""
    try:
        b = fc.get_document(f"bookings/{did}") or {}
    except Exception as e:
        _LOGGER.warning("Booking bentrok fetch error: %s", e)
        return None
    if not b:
        return None
    owner = str(b.get("owner", "")).strip().lower()
    r = _booking_range(b)
    if not r or not owner:
        return None
    mulai, akhir = r
    perangkat = str(b.get("perangkat", "") or "").strip()
    tanggal = str(b.get("tanggal", "") or "").strip()
    ov = _booking_overlaps(fc, owner, perangkat, tanggal, mulai, akhir, exclude_id=did)
    if not ov:
        return None
    d, (dm, da) = ov[0]
    return (f"Bentrok jadwal: {perangkat} sudah dibooking {tanggal} "
            f"{dm.strftime('%H:%M')}-{da.strftime('%H:%M')} oleh "
            f"{d.get('namaPelanggan', '-')} (kode {str(d.get('_id', ''))[:8].upper()}). "
            f"Pilih TV lain atau tolak booking ini.")


@app.route("/api/booking/cek")
@require_auth
def api_booking_cek():
    """Cek ketersediaan slot booking (dipakai aplikasi pembuat booking sebelum
    membuat booking): ?perangkat=TV 1&tanggal=2026-08-24&jam=08:00&paket=5 Jam[&grup=PS3]"""
    perangkat = str(request.args.get("perangkat", "") or "").strip()
    tanggal = str(request.args.get("tanggal", "") or "").strip()
    jam = str(request.args.get("jam", "") or "").strip()[:5]
    paket = str(request.args.get("paket", "") or "").strip()
    grup = str(request.args.get("grup", "") or "").strip()
    if not (perangkat and tanggal and jam and paket):
        return jsonify({"error": "perangkat, tanggal, jam, paket wajib diisi"}), 400
    if not grup:
        cfg = M.ConfigManager.load()
        for g, t in list((cfg.get("grup_tarif", {}) or {}).items()) + \
                     list((cfg.get("grup_tarif_warnet", {}) or {}).items()):
            if isinstance(t, dict) and paket in t:
                grup = g
                break
    fake = {"tanggal": tanggal, "jam": jam, "paket": paket, "grup": grup}
    r = _booking_range(fake)
    if not r:
        return jsonify({"error": "format tanggal/jam tidak valid (YYYY-MM-DD, HH:MM)"}), 400
    mulai, akhir = r
    ops = _booking_ops()
    if str(ops.get("mode", "buka")) != "buka":
        alasan = ("Rental LIBUR" + (f" s/d {ops.get('buka_kembali')}" if ops.get("buka_kembali") else "")
                  ) if ops.get("mode") == "libur" else \
                 (f"Rental TUTUP — buka kembali {ops.get('jam_buka')}-{ops.get('jam_tutup')}")
        return jsonify({"tersedia": False, "alasan": alasan, "ops": ops,
                        "perangkat": perangkat, "tanggal": tanggal, "jam": jam,
                        "durasi_menit": int((akhir - mulai).total_seconds() // 60),
                        "bentrok": []})
    owner = (STORE._resolve_license_user() or "").strip().lower()
    ov = _booking_overlaps(FirestoreClient(), owner, perangkat, tanggal,
                           mulai, akhir) if owner else []
    return jsonify({
        "tersedia": not ov,
        "perangkat": perangkat,
        "tanggal": tanggal,
        "jam": jam,
        "durasi_menit": int((akhir - mulai).total_seconds() // 60),
        "bentrok": [{"kode": str(d.get("_id", ""))[:8].upper(),
                     "nama": d.get("namaPelanggan", ""),
                     "mulai": dm.strftime("%H:%M"),
                     "selesai": da.strftime("%H:%M")} for d, (dm, da) in ov],
    })


@app.route("/api/booking/<did>", methods=["POST"])
@require_auth
def api_booking_aksi(did):
    """Aksi booking: status (dikonfirmasi/ditolak + alasan) atau lunas (sisa)."""
    data = request.get_json(silent=True) or {}
    act = str(data.get("action", "") or "").strip()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        fc = FirestoreClient()
        if act == "status":
            status = str(data.get("status", "") or "").strip()
            if status not in ("dikonfirmasi", "ditolak"):
                return jsonify({"error": "status harus dikonfirmasi/ditolak"}), 400
            if status == "dikonfirmasi":
                bentrok = _booking_bentrok_msg(fc, did)
                if bentrok:
                    return jsonify({"error": bentrok}), 409
            fc.set_document(f"bookings/{did}", {
                "status": status,
                "kasir": STORE.user or "",
                "alasan": str(data.get("alasan", "") or "").strip(),
                "updatedAt": now,
            }, merge=True)
            return jsonify({"ok": True, "status": status})
        if act == "lunas":
            fc.set_document(f"bookings/{did}", {
                "statusBayar": "lunas_transfer",
                "sisaBayar": 0,
                "kasir": STORE.user or "",
                "updatedAt": now,
            }, merge=True)
            return jsonify({"ok": True, "statusBayar": "lunas_transfer"})
        return jsonify({"error": "action harus status/lunas"}), 400
    except Exception as e:
        _LOGGER.warning("Booking aksi error: %s", e)
        return jsonify({"error": f"Gagal update booking: {e}"}), 500


# ─────────────────────────────────────────────────────────────────────────
#  AKTIVASI & BERLANGGANAN (tab Aktivasi — port _setup_aktivasi/rr_license)
# ─────────────────────────────────────────────────────────────────────────
#  PROFIL: background aplikasi + backup & restore (port _pilih_bg_image/_export_backup)
# ─────────────────────────────────────────────────────────────────────────
@app.route("/api/settings/bg", methods=["POST"])
@require_admin
@require_auth
def api_settings_bg():
    """Upload/hapus background (key config app_bg_image, sama seperti desktop)."""
    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "") or "").strip()
    if action == "clear":
        M.ConfigManager.set("app_bg_image", "")
        return jsonify({"ok": True})
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Pilih file gambar dulu"}), 400
    try:
        from PIL import Image
        img = Image.open(f.stream)
        img.verify()
    except Exception:
        return jsonify({"error": "File bukan gambar yang valid"}), 400
    f.stream.seek(0)
    dest = os.path.join(BASE_DIR, "bg_user.png")
    try:
        f.save(dest)
    except Exception as e:
        return jsonify({"error": f"Gagal simpan gambar: {e}"}), 500
    M.ConfigManager.set("app_bg_image", dest)
    return jsonify({"ok": True, "url": "/api/bg"})


@app.route("/api/bg")
def api_bg():
    """Public: file background aktif (dipakai <img>/CSS di browser, tanpa token)."""
    path = str(M.ConfigManager.get("app_bg_image", "") or "")
    if path and os.path.isfile(path):
        return send_file(path, max_age=3600)
    return jsonify({"error": "Tidak ada background"}), 404


@app.route("/api/backup/export")
@require_auth
def api_backup_export():
    """Port _export_backup (main.py): config (tanpa users, plus users_safe) + riwayat + audit."""
    cfg = M.ConfigManager.load()
    export_cfg = {k: v for k, v in cfg.items() if k != "users"}
    export_cfg["users_safe"] = {
        u: {kk: vv for kk, vv in d.items() if kk not in ("password", "password_enc", "password_hash")}
        for u, d in cfg.get("users", {}).items()
    } if isinstance(cfg.get("users", {}), dict) else {}
    audit_logs = []
    try:
        if os.path.exists(M.AUDIT_FILE):
            with open(M.AUDIT_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        audit_logs.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    backup = {
        "app_version": WEB_APP_VERSION,
        "exported_at": datetime.datetime.now().isoformat(),
        "exported_by": STORE.user or "unknown",
        "config": export_cfg,
        "riwayat": {
            "riwayat_transaksi": [list(r) for r in STORE.riwayat_transaksi],
            "riwayat_meta": STORE.riwayat_meta,
        },
        "audit_log": audit_logs[-5000:] if len(audit_logs) > 5000 else audit_logs,
    }
    fname = "rr_billing_backup_{}.json".format(datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    resp = Response(
        json.dumps(backup, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )
    return resp


@app.route("/api/backup/import", methods=["POST"])
@require_auth
def api_backup_import():
    """Port _import_backup (main.py): merge config (users tidak ditimpa), append riwayat & audit."""
    data = request.get_json(silent=True) or {}
    backup = data.get("backup")
    if not isinstance(backup, dict) or not isinstance(backup.get("config"), dict):
        return jsonify({"error": "File backup tidak valid"}), 400
    overwrite_users = bool(data.get("overwrite_users"))
    try:
        cfg = M.ConfigManager.load()
        imported_cfg = backup.get("config", {})
        for k, v in imported_cfg.items():
            if k in ("users_safe",):
                continue
            if k == "users" and not overwrite_users:
                continue
            cfg[k] = v
        M.ConfigManager.save(cfg)
    except Exception as e:
        return jsonify({"error": f"Gagal simpan config: {e}"}), 500
    try:
        rows = backup.get("riwayat", {}).get("riwayat_transaksi", []) or []
        metas = backup.get("riwayat", {}).get("riwayat_meta", []) or []
        for r in rows:
            STORE.riwayat_transaksi.append(tuple(r))
        for m in metas:
            STORE.riwayat_meta.append(m)
        STORE.save_riwayat()
        _x = 0
        for entry in backup.get("audit_log", []) or []:
            try:
                M.AuditLogger._append_line(json.dumps(entry, ensure_ascii=False))
                _x += 1
            except Exception:
                pass
        M.AuditLogger.log(action="backup_import", username=STORE.user or "",
                          status="success", details={"riwayat_count": len(rows)})
    except Exception as e:
        return jsonify({"error": f"Gagal simpan riwayat/log: {e}"}), 500
    return jsonify({"ok": True, "riwayat": len(rows), "audit": len(backup.get("audit_log", []) or [])})


@app.route("/api/backup/reset", methods=["POST"])
@require_auth
def api_backup_reset():
    """Port _reset_all_data (main.py): hapus riwayat & audit (konfirmasi ketik RESET)."""
    data = request.get_json(silent=True) or {}
    if str(data.get("confirm", "")).strip() != "RESET":
        return jsonify({"error": "Ketik 'RESET' untuk konfirmasi"}), 400
    STORE.riwayat_transaksi.clear()
    STORE.riwayat_meta.clear()
    STORE.save_riwayat()
    try:
        with open(M.AUDIT_FILE, "w", encoding="utf-8") as f:
            f.write("")
            f.flush()
    except Exception:
        pass
    M.AuditLogger.log(action="data_reset", username=STORE.user or "", status="success")
    return jsonify({"ok": True})


_PAKET_KEY_MAP = {"Bulanan": "1 Bulan", "3 Bulan": "3 Bulan", "Tahunan": "1 Tahun", "LIFETIME": "LIFETIME"}


def _fmt_rp(angka):
    s = f"{angka:,}".replace(",", ".")
    return f"Rp {s}"


def _qris_path():
    return os.path.join(BASE_DIR, "qris.png")


def _paket_langganan():
    """Mirror paket_base + diskon/addTv promo di _setup_aktivasi (main.py)."""
    promo_data = None
    try:
        promo_data = FirestoreClient().fetch_promo_settings()
    except Exception:
        promo_data = None
    promo_aktif = bool((promo_data or {}).get("promoAktif", False))
    diskon_map = (promo_data or {}).get("diskonPerPaket", {}) or {}
    add_tv_map = (promo_data or {}).get("addTvOverride", {}) or {}

    paket_base = [
        ("Bulanan",  "Rp 99.000 / bulan",   99_000,  "5 TV + 5 PC Warnet",          "#8b5cf6", "💎"),
        ("3 Bulan",  "Rp 299.000",           299_000, "10 TV + 10 PC Warnet",        "#22c55e", "🚀"),
        ("Tahunan",  "Rp 999.000 / tahun",   999_000, "15 TV + 15 PC Warnet",        "#eab308", "👑"),
        ("LIFETIME", "Rp 2.000.000",         2_000_000, "UNLIMITED TV + PC Warnet 🏆","#ef4444", "🏆"),
    ]
    pkgs = []
    for nama, harga_default, base_harga, deskripsi, warna, ico in paket_base:
        harga_diskon = base_harga
        key = _PAKET_KEY_MAP.get(nama)
        if promo_aktif and key:
            diskon = int(diskon_map.get(key, 0) or 0)
            if diskon > 0:
                harga_diskon = base_harga * (100 - diskon) // 100
            tv_ov = add_tv_map.get(key)
            if tv_ov is not None:
                deskripsi = f"🔥 ADD TV {tv_ov}"
        if promo_aktif and harga_diskon < base_harga:
            harga_tampil = f"~~{_fmt_rp(base_harga)}~~ → {_fmt_rp(harga_diskon)}"
        else:
            harga_tampil = harga_default
        pkgs.append({
            "nama": nama, "harga": harga_default, "harga_diskon": harga_diskon,
            "harga_tampil": harga_tampil, "deskripsi": deskripsi,
            "warna": warna, "ico": ico, "promo": promo_aktif and harga_diskon < base_harga,
        })
    return pkgs


@app.route("/api/aktivasi")
@require_auth
def api_aktivasi_status():
    try:
        status = LicenseManager.get_status(current_user=STORE._resolve_license_user())
    except Exception as e:
        _LOGGER.exception("Gagal get_status web: %s", e)
        status = {"status": "unknown", "sisa_hari": 0, "pesan": f"Error: {e}"}
    try:
        lic = LicenseManager.load() or {}
    except Exception:
        lic = {}
    return jsonify({
        "status": status,
        "kode": str(lic.get("kode_aktivasi", "") or ""),
        "tgl_aktivasi": str(lic.get("tgl_aktivasi", "") or "")[:10],
        "edition": str(lic.get("edition", "") or ""),
        "promo_add_tv": int(lic.get("promo_add_tv", 0) or 0),
        "aktif": bool(lic.get("aktif", False)),
        "revoked": bool(lic.get("revoked", False)),
        "admin": STORE.role == "admin",
        "paket": _paket_langganan(),
        "qris_available": os.path.isfile(_qris_path()),
        "wa_admin": "6281270647744",
    })


@app.route("/qris.png")
def api_qris_png():
    p = _qris_path()
    if p and os.path.isfile(p):
        return send_file(p, mimetype="image/png", max_age=3600)
    return jsonify({"error": "QRIS tidak tersedia — letakkan qris.png di folder app"}), 404


def _sync_aktivasi_cloud(kode):
    """Port _sync_aktivasi_ke_cloud (main.py): update license doc + licenseStatus."""
    uname = STORE.user or ""
    if not uname:
        return
    try:
        fc = FirestoreClient()
        record = fc.find_license_by_code(kode)
        doc_id = (record or {}).get("_id", "")
        if record and record.get("revoked"):
            _LOGGER.warning("Sync aktivasi dilewati — lisensi %s sudah direvoke", kode)
            return
        status = LicenseManager.get_status(current_user=STORE._resolve_license_user())
        expiry_str = status.get("expiry", "")
        if record and doc_id:
            fc.activate_license(doc_id, expiry=expiry_str, device_type="desktop")
        lic_local = LicenseManager.load()
        max_tv = int((record or {}).get("maxTv", 0) or 0)
        if max_tv <= 0:
            max_tv = int(lic_local.get("promo_add_tv", 0) or 0)
        if max_tv <= 0:
            max_tv = {"BULANAN": 5, "3BULAN": 10, "TAHUNAN": 15, "LIFETIME": 999999}.get(
                str(lic_local.get("edition", "") or "").upper(), 0)
        if max_tv <= 0:
            pkg = str((record or {}).get("package", "BULANAN") or "BULANAN").upper()
            max_tv = {"BULANAN": 5, "3BULAN": 10, "TAHUNAN": 15, "LIFETIME": 999999}.get(pkg, 5)
        ls = {
            "status": "active",
            "pesan": f"Lisensi aktif hingga {expiry_str}",
            "expiresAt": expiry_str,
            "maxTv": max_tv,
            "maxPc": max_tv,
            "promoAddTv": int(lic_local.get("promo_add_tv", 0) or 0),
            "cloud_restored": True,
        }
        fc.write_license_status(uname, ls)
        _LOGGER.info("Cloud activation sync OK %s (maxTv=%d)", uname, max_tv)
    except Exception as e:
        _LOGGER.warning("Cloud activation sync error: %s", e)


@app.route("/api/aktivasi", methods=["POST"])
@require_admin
@require_auth
def api_aktivasi_act():
    kode = str((request.get_json(silent=True) or {}).get("kode", "") or "").strip()
    if not kode:
        return jsonify({"error": "Masukkan kode aktivasi dulu"}), 400
    uname = STORE.user or ""
    try:
        sukses, pesan = LicenseManager.aktivasi(
            kode,
            username=uname,
            binding_mode="username" if uname else "machine",
            promo_add_tv=0,
        )
    except Exception as e:
        sukses, pesan = False, f"Gagal aktivasi: {e}"
    try:
        M.AuditLogger.log(
            action="activation_attempt",
            username=uname,
            status="success" if sukses else "failed",
            details={"binding_mode": "username" if uname else "machine", "message": pesan},
        )
    except Exception:
        pass
    if not sukses:
        return jsonify({"error": pesan}), 400
    STORE._lic_invalidate()
    threading.Thread(target=_sync_aktivasi_cloud, args=(kode,), daemon=True).start()
    return jsonify({"ok": True, "message": pesan})


@app.route("/api/aktivasi/revoke", methods=["POST"])
@require_admin
@require_auth
def api_aktivasi_revoke():
    alasan = str((request.get_json(silent=True) or {}).get("alasan", "") or "").strip()
    try:
        sukses, pesan = LicenseManager.deactivate()
        if not sukses:
            return jsonify({"error": pesan}), 400
        try:
            fc = FirestoreClient()
            lic = LicenseManager.load()
            kode = str(lic.get("kode_aktivasi", "") or "")
            if kode:
                record = fc.find_license_by_code(kode)
                if record and record.get("_id"):
                    fc.revoke_license(record.get("_id"), reason=alasan)
            fc.write_license_status(STORE.user or "", {
                "status": "revoked",
                "pesan": "Lisensi dicabut oleh pengguna.",
                "expiresAt": "",
            })
        except Exception as e:
            _LOGGER.warning("Cloud revoke error: %s", e)
        lic_data = LicenseManager.load()
        lic_data["aktif"] = False
        lic_data["revoked"] = True
        lic_data["revoked_at"] = datetime.datetime.now().isoformat()
        LicenseManager.save(lic_data)
        STORE._lic_invalidate()
        try:
            M.AuditLogger.log(
                action="license_revoked",
                username=STORE.user or "",
                status="success",
                details={"reason": alasan},
            )
        except Exception:
            pass
        return jsonify({"ok": True})
    except Exception as e:
        _LOGGER.exception("Revoke web error: %s", e)
        return jsonify({"error": f"Gagal revoke: {e}"}), 500


# ─────────────────────────────────────────────────────────────────────────
#  LOG APLIKASI (tab Log — port _setup_log_aplikasi, file rr_billing_audit.jsonl)
# ─────────────────────────────────────────────────────────────────────────
@app.route("/api/logs")
@require_admin
@require_auth
def api_logs():
    f = str(request.args.get("f", "all") or "all").strip()
    path = M.app_path("rr_billing_audit.jsonl")
    entries = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    action = str(e.get("action", ""))
                    if f == "login" and "login" not in action:
                        continue
                    if f == "transaction" and "transaksi" not in action:
                        continue
                    if f == "rental" and "rental" not in action:
                        continue
                    if f == "update" and "update" not in action:
                        continue
                    if f == "error" and str(e.get("status", "")) != "failed":
                        continue
                    try:
                        det = json.dumps(e.get("details", {}), ensure_ascii=False)
                    except Exception:
                        det = ""
                    entries.append({
                        "timestamp": str(e.get("timestamp", "")),
                        "action": action,
                        "username": str(e.get("username", "")),
                        "status": str(e.get("status", "")),
                        "details": det,
                    })
        except Exception as ex:
            _LOGGER.warning("Baca audit log error: %s", ex)
    entries.sort(key=lambda x: x["timestamp"], reverse=True)
    try:
        limit = max(10, min(3000, int(request.args.get("limit", 2000) or 2000)))
    except Exception:
        limit = 2000
    return jsonify({
        "logs": entries[:limit],
        "total": len(entries),
        "file": os.path.basename(path),
        "exists": os.path.exists(path),
    })


if __name__ == "__main__":
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((HOST, PORT))
        sock.close()
    except OSError:
        print(f"❌ Port {PORT} sudah dipakai. Pastikan server web tidak berjalan dua kali.")
        sys.exit(1)

    print("=" * 56)
    print("  RR BILLING PRO — WEB KASIR (localhost)")
    print(f"  Buka di browser:  http://localhost:{PORT}")
    print("  (buka via localhost agar login Google berfungsi)")
    print("  Data & cloud sama dengan aplikasi desktop.")
    print("  Catatan: jangan jalankan aplikasi desktop bersamaan.")
    print("=" * 56)
    start_servers()
    STORE.start_ticker()
    try:
        if os.environ.get("RRB_NO_BROWSER") != "1":
            import webbrowser
            threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    except Exception:
        pass
    app.run(host=HOST, port=PORT, threaded=True, debug=False, use_reloader=False)
