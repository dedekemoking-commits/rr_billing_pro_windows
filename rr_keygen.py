"""
rr_keygen.py — Developer Tool: Generate Kode Aktivasi via Username
===================================================================
Jalankan: python rr_keygen.py
Hanya untuk developer/admin — JANGAN distribusikan ke user.

Perubahan di rr_license.py:
- LicenseGenerator.generate() mendukung parameter username=
  Kode yang dihasilkan terikat ke username (via CRC-16 username
  yang dimasukkan ke field machine_crc, ATAU mode universal ANY).

Flow:
  1. App baca rr_billing_config.json → tampilkan daftar user terdaftar
  2. Developer pilih user, pilih paket, pilih durasi
  3. Sistem generate kode → simpan log ke rr_keygen_log.json
  4. Developer copy kode → kirim ke user (WA/email)
  5. User input kode di tab Aktivasi → LicenseValidator.verify() → aktif
"""

import os
import json
import hashlib
import bcrypt  # ← Password hashing with salt
import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk
from datetime import datetime, date, timedelta
from rr_license import (
    LicenseGenerator, LicenseValidator, LicenseManager,
    get_machine_id, EDITION_MAP, EDITION_HARI, _crc16
)

# ─── TEMA (sama dengan main.py) ───────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C_BG     = "#0D0D1A"
C_PANEL  = "#12122A"
C_CARD   = "#1A1A3A"
C_ACCENT = "#00FFCC"
C_ACCENT2= "#7B2FFF"
C_RED    = "#FF3366"
C_GREEN  = "#39FF14"
C_YELLOW = "#FFD700"
C_TEXT   = "#E0E0FF"
C_MUTED  = "#6060A0"
C_BTN    = "#1E1E4A"
C_BORDER = "#2A2A5A"
C_ORANGE = "#FF8C00"

FONT_TITLE = ("Russo One", 15, "bold")
FONT_SUB   = ("Russo One", 10, "bold")
FONT_BODY  = ("Courier New", 10)
FONT_SMALL = ("Courier New", 9)
FONT_LABEL = ("Consolas", 10)
FONT_MONO  = ("Consolas", 13, "bold")

CONFIG_FILE  = "rr_billing_config.json"
KEYGEN_LOG   = "rr_keygen_log.json"

# ─── PASSWORD SECURITY HELPERS ────────────────────────────────────────────────
def hash_dev_password(password: str) -> str:
    """Hash password dengan bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode(), salt)
    return "bcrypt$" + hashed.decode('utf-8')

def verify_dev_password(password: str, password_hash: str) -> bool:
    """Verify password against bcrypt hash (backward-compatible)."""
    try:
        if password_hash.startswith("bcrypt$"):
            hash_value = password_hash[7:].encode('utf-8')
            return bcrypt.checkpw(password.encode(), hash_value)
        else:
            return hashlib.sha256(password.encode()).hexdigest() == password_hash
    except Exception as e:
        print(f"Password verification error: {e}")
        return False

# Developer password hash (rrcctv2026 hashed dengan bcrypt)
# Untuk generate hash baru: hash_dev_password("yourpassword")
_DEV_PASSWORD_HASH = "bcrypt$$2b$12$DeXvlVtyD0FDXYgUxQWffO.Vom/2IMa12/3j2qmY2novrD3LU60ry"


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPER
# ═══════════════════════════════════════════════════════════════════════════════
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_log() -> list:
    if os.path.exists(KEYGEN_LOG):
        try:
            with open(KEYGEN_LOG, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_log(entries: list):
    with open(KEYGEN_LOG, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def fmt_rp(n):
    return f"Rp {n:,.0f}".replace(",", ".")


# ═══════════════════════════════════════════════════════════════════════════════
#  PATCH: LicenseGenerator.generate_for_username
#  Kode terikat ke username (bukan machine_id hardware).
#  Username di-hash ke CRC-16 → masuk ke field machine_crc di payload.
#  Saat validasi, LicenseValidator.verify_username() memverifikasi CRC username.
# ═══════════════════════════════════════════════════════════════════════════════
def generate_for_username(username: str,
                           edition: str = "BULANAN",
                           days: int = None,
                           start_date: date = None) -> str:
    """
    Generate kode lisensi yang terikat ke USERNAME (bukan machine ID).
    CRC-16 dari username dimasukkan ke field machine_crc.
    User harus memiliki username yang sama saat aktivasi.
    """
    from rr_license import (
        EDITION_MAP, EDITION_HARI, _build_payload, _sign,
        _to_b32, _format_kode, _days_since_epoch, _crc16
    )

    edition_upper = edition.upper().replace(" ", "").replace("-", "")
    if edition_upper not in EDITION_MAP:
        raise ValueError(f"Edition tidak dikenal: {edition}")

    edition_byte = EDITION_MAP[edition_upper]
    hari         = days if days is not None else EDITION_HARI[edition_byte]
    mulai        = start_date or date.today()
    expiry       = mulai + timedelta(days=hari)
    expiry_days  = _days_since_epoch(expiry)

    # CRC-16 dari username (lowercase, strip) → jadi "machine_crc"
    uname_clean  = username.strip().lower()
    machine_crc  = _crc16(uname_clean)

    payload   = _build_payload(edition_byte, expiry_days, machine_crc)
    signature = _sign(payload)
    from rr_license import _to_b32, _format_kode
    encoded   = _to_b32(payload + signature)
    return _format_kode(encoded)


def verify_for_username(kode: str, username: str):
    """
    Verifikasi kode yang terikat username.
    Gunakan ini sebagai pengganti LicenseValidator.verify() di main.py
    jika kamu ingin binding username (opsional — lihat CATATAN di bawah).

    Returns: (sukses, pesan, info)
    """
    # Kita kirim username sebagai "machine_id" — rr_license.py akan
    # menghitung CRC-16-nya dan membandingkan dengan machine_crc di payload.
    uname_clean = username.strip().lower()
    return LicenseValidator.verify(kode, machine_id=uname_clean)


# ═══════════════════════════════════════════════════════════════════════════════
#  HALAMAN LOGIN DEVELOPER
# ═══════════════════════════════════════════════════════════════════════════════
class LoginDeveloper(ctk.CTkToplevel):
    def __init__(self, master, on_success):
        super().__init__(master)
        self.title("🔐 Developer Access")
        self.geometry("400x320")
        self.configure(fg_color=C_BG)
        self.grab_set()
        self.resizable(False, False)
        self.on_success = on_success
        self._attempt = 0
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="🔐  DEVELOPER ACCESS",
                     font=FONT_TITLE, text_color=C_RED).pack(pady=(30, 4))
        ctk.CTkLabel(self, text="Masukkan password developer untuk melanjutkan",
                     font=FONT_SMALL, text_color=C_MUTED).pack(pady=(0, 20))

        panel = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=14)
        panel.pack(padx=30, fill="x")

        ctk.CTkLabel(panel, text="Password Developer:",
                     font=FONT_LABEL, text_color=C_MUTED,
                     anchor="w").pack(anchor="w", padx=20, pady=(16, 4))
        self.entry = ctk.CTkEntry(panel, show="●", height=40, width=320,
                                   fg_color=C_BTN, text_color=C_ACCENT,
                                   border_color=C_BORDER,
                                   font=("Consolas", 13, "bold"))
        self.entry.pack(padx=20, pady=(0, 8))
        self.entry.bind("<Return>", lambda e: self._cek())

        self.lbl_err = ctk.CTkLabel(panel, text="", font=FONT_LABEL,
                                     text_color=C_RED)
        self.lbl_err.pack(pady=(0, 8))

        ctk.CTkButton(panel, text="🔓  Masuk", height=38,
                      fg_color=C_RED, hover_color="#CC0033",
                      font=FONT_SUB, text_color="white",
                      command=self._cek).pack(padx=20, pady=(0, 16), fill="x")

        ctk.CTkLabel(self,
                     text="Default password: rrcctv2026\n(ubah _DEV_PASSWORD_HASH di rr_keygen.py)",
                     font=FONT_SMALL, text_color=C_MUTED, justify="center").pack(pady=10)

    def _cek(self):
        pw = self.entry.get().strip()
        if verify_dev_password(pw, _DEV_PASSWORD_HASH):
            self.destroy()
            self.on_success()
        else:
            self._attempt += 1
            self.lbl_err.configure(text=f"✖  Password salah ({self._attempt}/3)")
            if self._attempt >= 3:
                self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN KEYGEN APP
# ═══════════════════════════════════════════════════════════════════════════════
class KeygenApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🔑 RR BILLING PRO — Developer Keygen Tool")
        self.geometry("1000x720")
        self.configure(fg_color=C_BG)
        self.resizable(True, True)

        # Tanya password dulu
        self._authed = False
        self.after(200, self._minta_login)

    def _minta_login(self):
        LoginDeveloper(self, on_success=self._build_ui)

    def _build_ui(self):
        self._authed = True
        self._kode_terkini = ""

        # ── Header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=C_PANEL, height=60, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="🔑  RR BILLING PRO — Developer Keygen Tool",
                     font=FONT_TITLE, text_color=C_RED).pack(side="left", padx=20, pady=16)
        ctk.CTkLabel(hdr, text="⚠  RAHASIA — Jangan distribusikan tool ini",
                     font=FONT_SMALL, text_color=C_YELLOW).pack(side="right", padx=20)

        # ── Body: dua kolom ───────────────────────────────────────────────────
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=10)
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        # Kolom kiri: form generate
        self._build_form(body)
        # Kolom kanan: log riwayat generate
        self._build_log(body)

    # ── KOLOM KIRI: FORM GENERATE ─────────────────────────────────────────────
    def _build_form(self, parent):
        left = ctk.CTkScrollableFrame(parent, fg_color=C_BG, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        # ── 1. Pilih Username ─────────────────────────────────────────────────
        sec1 = self._sec(left, "👤  PILIH USER TERDAFTAR")
        ctk.CTkLabel(sec1,
                     text="User di bawah berasal dari rr_billing_config.json\n"
                          "Klik nama untuk memilih, atau ketik manual di bawah.",
                     font=FONT_SMALL, text_color=C_MUTED,
                     justify="left").pack(anchor="w", padx=14, pady=(0, 8))

        # Treeview daftar user
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("KG.Treeview",
                        background=C_CARD, fieldbackground=C_CARD,
                        foreground=C_TEXT, rowheight=26,
                        font=("Consolas", 10))
        style.configure("KG.Treeview.Heading",
                        background=C_PANEL, foreground=C_ACCENT,
                        font=("Russo One", 9, "bold"), relief="flat")
        style.map("KG.Treeview", background=[("selected", C_ACCENT2)])

        cols = ("Username", "Role", "Nama Rental", "Tgl Daftar")
        self.tree_user = ttk.Treeview(sec1, columns=cols,
                                       show="headings", style="KG.Treeview", height=6)
        for col, w in zip(cols, [130, 70, 180, 130]):
            self.tree_user.heading(col, text=col)
            self.tree_user.column(col, width=w, anchor="center" if w < 150 else "w")
        self.tree_user.pack(fill="x", padx=14, pady=(0, 6))
        self.tree_user.bind("<<TreeviewSelect>>", self._on_user_select)

        btn_refresh = ctk.CTkButton(sec1, text="🔄 Refresh Daftar User",
                                     height=30, fg_color=C_BTN,
                                     border_width=1, border_color=C_ACCENT,
                                     font=FONT_SMALL, text_color=C_ACCENT,
                                     command=self._load_users)
        btn_refresh.pack(anchor="w", padx=14, pady=(0, 8))

        ctk.CTkLabel(sec1, text="Username (input manual / konfirmasi):",
                     font=FONT_LABEL, text_color=C_MUTED,
                     anchor="w").pack(anchor="w", padx=14, pady=(4, 2))
        self.var_username = ctk.StringVar()
        self.entry_username = ctk.CTkEntry(sec1, textvariable=self.var_username,
                                            placeholder_text="Pilih dari tabel atau ketik di sini",
                                            fg_color=C_BTN, text_color=C_ACCENT,
                                            border_color=C_BORDER,
                                            font=("Consolas", 12, "bold"), height=36)
        self.entry_username.pack(fill="x", padx=14, pady=(0, 10))
        self.lbl_user_info = ctk.CTkLabel(sec1, text="",
                                           font=FONT_SMALL, text_color=C_MUTED,
                                           justify="left")
        self.lbl_user_info.pack(anchor="w", padx=14, pady=(0, 8))

        # ── 2. Pilih Paket ────────────────────────────────────────────────────
        sec2 = self._sec(left, "📦  PILIH PAKET LISENSI")

        paket_items = [
            ("Bulanan",  "0x01", "31 hari",   "Rp 99.000",   C_ACCENT),
            ("3 Bulan",  "0x03", "92 hari",   "Rp 249.000",  C_GREEN),
            ("Tahunan",  "0x0C", "365 hari",  "Rp 799.000",  C_YELLOW),
            ("Lifetime", "0xFF", "36.500 hari","Rp 1.999.000",C_RED),
        ]

        self.var_paket = ctk.StringVar(value="BULANAN")
        paket_grid = ctk.CTkFrame(sec2, fg_color="transparent")
        paket_grid.pack(fill="x", padx=14, pady=(0, 8))

        for i, (nama, kode, durasi, harga, color) in enumerate(paket_items):
            card = ctk.CTkFrame(paket_grid, fg_color=C_CARD, corner_radius=10,
                                 border_width=1, border_color=color)
            card.grid(row=i//2, column=i%2, padx=6, pady=6, sticky="ew")
            paket_grid.columnconfigure(i%2, weight=1)

            rb = ctk.CTkRadioButton(card, text=nama,
                                     variable=self.var_paket,
                                     value=nama.upper().replace(" ", ""),
                                     font=("Russo One", 10, "bold"),
                                     text_color=color,
                                     fg_color=color, hover_color=C_ACCENT2,
                                     command=self._update_preview)
            rb.pack(anchor="w", padx=12, pady=(10, 2))
            ctk.CTkLabel(card, text=f"⏱ {durasi}  ·  {harga}",
                         font=FONT_SMALL, text_color=C_MUTED).pack(anchor="w", padx=12, pady=(0, 10))

        # Override hari (opsional)
        ovr_row = ctk.CTkFrame(sec2, fg_color="transparent")
        ovr_row.pack(fill="x", padx=14, pady=(0, 10))
        ctk.CTkLabel(ovr_row, text="Override hari aktif (opsional):",
                     font=FONT_LABEL, text_color=C_MUTED, width=220, anchor="w").pack(side="left")
        self.var_hari = ctk.StringVar()
        e_hari = ctk.CTkEntry(ovr_row, textvariable=self.var_hari,
                               placeholder_text="kosong = default paket",
                               fg_color=C_BTN, text_color=C_YELLOW,
                               border_color=C_BORDER, font=FONT_BODY, height=32, width=140)
        e_hari.pack(side="left", padx=8)
        e_hari.bind("<KeyRelease>", lambda e: self._update_preview())

        # ── 3. Binding Mode ───────────────────────────────────────────────────
        sec3 = self._sec(left, "🔒  MODE BINDING KODE")
        ctk.CTkLabel(sec3,
                     text="Tentukan apakah kode terikat ke username atau universal.",
                     font=FONT_SMALL, text_color=C_MUTED).pack(anchor="w", padx=14, pady=(0, 8))

        self.var_binding = ctk.StringVar(value="username")
        for val, label, sub, color in [
            ("username", "Terikat Username (Direkomendasikan)",
             "Hanya user dengan username yang sama yang bisa aktivasi.", C_GREEN),
            ("universal", "Universal (Semua Mesin / User)",
             "Kode bisa dipakai siapa saja — gunakan dengan hati-hati.", C_YELLOW),
        ]:
            row_b = ctk.CTkFrame(sec3, fg_color=C_CARD, corner_radius=8)
            row_b.pack(fill="x", padx=14, pady=4)
            rb = ctk.CTkRadioButton(row_b, text=label, variable=self.var_binding,
                                     value=val, font=FONT_LABEL,
                                     text_color=color,
                                     fg_color=color, hover_color=C_ACCENT2,
                                     command=self._update_preview)
            rb.pack(anchor="w", padx=12, pady=(8, 2))
            ctk.CTkLabel(row_b, text=sub, font=FONT_SMALL,
                         text_color=C_MUTED).pack(anchor="w", padx=12, pady=(0, 8))

        # ── 4. Preview & Generate ─────────────────────────────────────────────
        sec4 = self._sec(left, "⚡  PREVIEW & GENERATE")

        self.lbl_preview = ctk.CTkLabel(sec4, text="— pilih user & paket dulu —",
                                         font=FONT_SMALL, text_color=C_MUTED,
                                         justify="left")
        self.lbl_preview.pack(anchor="w", padx=14, pady=(0, 10))

        self.btn_generate = ctk.CTkButton(sec4, text="⚡  GENERATE KODE AKTIVASI",
                                           height=44,
                                           fg_color=C_RED, hover_color="#CC0033",
                                           font=("Russo One", 12, "bold"),
                                           text_color="white",
                                           command=self._generate)
        self.btn_generate.pack(fill="x", padx=14, pady=(0, 8))

        # Hasil kode
        hasil_f = ctk.CTkFrame(sec4, fg_color=C_CARD, corner_radius=10,
                                 border_width=2, border_color=C_GREEN)
        hasil_f.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(hasil_f, text="KODE AKTIVASI:", font=FONT_SUB,
                     text_color=C_GREEN).pack(anchor="w", padx=14, pady=(12, 4))

        self.lbl_kode = ctk.CTkLabel(hasil_f, text="—",
                                      font=("Russo One", 14, "bold"),
                                      text_color=C_ACCENT, wraplength=340,
                                      justify="center")
        self.lbl_kode.pack(padx=14, pady=4)

        copy_row = ctk.CTkFrame(hasil_f, fg_color="transparent")
        copy_row.pack(padx=14, pady=(4, 12))

        self.btn_copy = ctk.CTkButton(copy_row, text="📋 Copy Kode",
                                       width=140, height=34,
                                       fg_color=C_BTN, border_width=1,
                                       border_color=C_GREEN,
                                       font=FONT_SUB, text_color=C_GREEN,
                                       command=self._copy_kode)
        self.btn_copy.pack(side="left", padx=4)

        ctk.CTkButton(copy_row, text="💬 Kirim via WA",
                      width=140, height=34,
                      fg_color=C_BTN, border_width=1,
                      border_color=C_YELLOW,
                      font=FONT_SUB, text_color=C_YELLOW,
                      command=self._kirim_wa).pack(side="left", padx=4)

        self._load_users()
        self._update_preview()

    # ── KOLOM KANAN: LOG ──────────────────────────────────────────────────────
    def _build_log(self, parent):
        right = ctk.CTkFrame(parent, fg_color=C_BG, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")

        hdr = ctk.CTkFrame(right, fg_color=C_PANEL, corner_radius=10)
        hdr.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(hdr, text="📋  RIWAYAT GENERATE KODE",
                     font=FONT_SUB, text_color=C_ACCENT2).pack(side="left", padx=14, pady=10)

        ctk.CTkButton(hdr, text="🗑 Bersihkan Log", height=28,
                      fg_color=C_BTN, border_width=1, border_color=C_RED,
                      font=FONT_SMALL, text_color=C_RED,
                      command=self._bersihkan_log).pack(side="right", padx=10)

        # Stat cards
        stat_row = ctk.CTkFrame(right, fg_color="transparent")
        stat_row.pack(fill="x", pady=(0, 8))
        stat_row.columnconfigure((0, 1, 2), weight=1)

        self.lbl_stat_total  = self._stat_card(stat_row, "Total Generate", "0", C_ACCENT,  col=0)
        self.lbl_stat_aktif  = self._stat_card(stat_row, "Belum Dipakai",  "0", C_GREEN,   col=1)
        self.lbl_stat_user   = self._stat_card(stat_row, "Unique User",    "0", C_YELLOW,  col=2)

        # Treeview log
        style = ttk.Style()
        style.configure("Log.Treeview",
                        background=C_CARD, fieldbackground=C_CARD,
                        foreground=C_TEXT, rowheight=28,
                        font=("Consolas", 9))
        style.configure("Log.Treeview.Heading",
                        background=C_PANEL, foreground=C_ACCENT,
                        font=("Russo One", 8, "bold"), relief="flat")
        style.map("Log.Treeview", background=[("selected", C_ACCENT2)])

        log_cols = ("Tgl Generate", "Username", "Paket", "Expiry", "Binding", "Kode")
        self.tree_log = ttk.Treeview(right, columns=log_cols,
                                      show="headings", style="Log.Treeview")
        widths = [130, 100, 80, 100, 80, 220]
        for col, w in zip(log_cols, widths):
            self.tree_log.heading(col, text=col)
            self.tree_log.column(col, width=w, anchor="w" if w > 100 else "center")
        self.tree_log.pack(fill="both", expand=True)
        self.tree_log.tag_configure("used",    foreground=C_MUTED)
        self.tree_log.tag_configure("valid",   foreground=C_GREEN)
        self.tree_log.tag_configure("expired", foreground=C_RED)

        # Tombol bawah
        bot = ctk.CTkFrame(right, fg_color="transparent")
        bot.pack(fill="x", pady=8)

        ctk.CTkButton(bot, text="📋 Copy Kode Terpilih", height=32,
                      fg_color=C_BTN, border_width=1, border_color=C_ACCENT,
                      font=FONT_LABEL, text_color=C_ACCENT,
                      command=self._copy_log_terpilih).pack(side="left", padx=4)

        ctk.CTkButton(bot, text="🔍 Verifikasi Kode Terpilih", height=32,
                      fg_color=C_BTN, border_width=1, border_color=C_GREEN,
                      font=FONT_LABEL, text_color=C_GREEN,
                      command=self._verif_log_terpilih).pack(side="left", padx=4)

        ctk.CTkButton(bot, text="💬 Kirim WA Terpilih", height=32,
                      fg_color=C_BTN, border_width=1, border_color=C_YELLOW,
                      font=FONT_LABEL, text_color=C_YELLOW,
                      command=self._wa_log_terpilih).pack(side="left", padx=4)

        self._load_log_tree()

    def _stat_card(self, parent, label, val, color, col):
        f = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=10)
        f.grid(row=0, column=col, sticky="ew", padx=4, pady=4)
        lbl_val = ctk.CTkLabel(f, text=val, font=("Russo One", 20, "bold"),
                                text_color=color)
        lbl_val.pack(pady=(10, 2))
        ctk.CTkLabel(f, text=label, font=FONT_SMALL, text_color=C_MUTED).pack(pady=(0, 10))
        return lbl_val

    # ── HELPER UI ─────────────────────────────────────────────────────────────
    def _sec(self, parent, judul):
        f = ctk.CTkFrame(parent, fg_color=C_PANEL, corner_radius=12)
        f.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(f, text=judul, font=FONT_SUB,
                     text_color=C_ACCENT2).pack(anchor="w", padx=14, pady=(12, 6))
        return f

    # ── LOAD USERS ────────────────────────────────────────────────────────────
    def _load_users(self):
        for item in self.tree_user.get_children():
            self.tree_user.delete(item)

        cfg   = load_config()
        users = cfg.get("users", {})
        profil_semua = cfg.get("profil_rental", {})

        if not users:
            self.tree_user.insert("", "end",
                                   values=("—", "—", "Belum ada user terdaftar", "—"))
            return

        # Default users yang ada di LoginPage (admin & kasir bawaan) → skip
        default_users = {"admin", "kasir"}

        for uname, udata in users.items():
            profil = profil_semua.get(uname, {})
            nama_rental  = profil.get("nama_rental", "—")
            tgl_daftar   = profil.get("tanggal_daftar", "—")[:10]
            role         = udata.get("role", "kasir")
            tag = "default" if uname in default_users else ""
            self.tree_user.insert("", "end",
                                   values=(uname, role, nama_rental, tgl_daftar),
                                   tags=(tag,))

        self.tree_user.tag_configure("default", foreground=C_MUTED)

    def _on_user_select(self, event):
        sel = self.tree_user.selection()
        if not sel:
            return
        vals = self.tree_user.item(sel[0], "values")
        uname = vals[0] if vals else ""
        if uname and uname != "—":
            self.var_username.set(uname)
            cfg = load_config()
            profil = cfg.get("profil_rental", {}).get(uname, {})
            nama_p  = profil.get("nama_pemilik", "—")
            nama_r  = profil.get("nama_rental", "—")
            email   = profil.get("email", "—")
            no_hp   = profil.get("no_hp", "—")
            self.lbl_user_info.configure(
                text=f"👤 {nama_p}  |  🏢 {nama_r}  |  📧 {email}  |  📱 {no_hp}",
                text_color=C_ACCENT)
            self._update_preview()

    # ── UPDATE PREVIEW ────────────────────────────────────────────────────────
    def _update_preview(self):
        uname  = self.var_username.get().strip()
        paket  = self.var_paket.get()
        hari_s = self.var_hari.get().strip()
        binding = self.var_binding.get()

        hari_map = {
            "BULANAN": 31, "3BULAN": 92, "TAHUNAN": 365, "LIFETIME": 36500
        }
        hari = int(hari_s) if hari_s.isdigit() and int(hari_s) > 0 else hari_map.get(paket, 31)
        expiry = date.today() + timedelta(days=hari)

        binding_txt = f"Terikat username '{uname}'" if binding == "username" and uname else "Universal (semua user)"
        user_txt = uname if uname else "⚠ Belum dipilih"

        # ── CEK LISENSI EXISTING (opsional warning) ────────────────────────────
        existing_info = ""
        if uname:
            try:
                lic_file = "rr_billing_license.json"
                if os.path.exists(lic_file):
                    with open(lic_file) as f:
                        lic = json.load(f)
                        if lic.get("aktif") and lic.get("username") == uname:
                            lic_expiry = lic.get("expiry", "")
                            existing_info = f"\n⚠ User ini SUDAH punya lisensi aktif hingga {lic_expiry[:10]}"
            except Exception:
                pass

        self.lbl_preview.configure(
            text=f"User      : {user_txt}\n"
                 f"Paket     : {paket}  ({hari} hari)\n"
                 f"Berlaku   : {date.today()}  s/d  {expiry}\n"
                 f"Binding   : {binding_txt}{existing_info}",
            text_color=C_TEXT if uname else C_YELLOW)

    # ── GENERATE ─────────────────────────────────────────────────────────────
    def _generate(self):
        uname   = self.var_username.get().strip().lower()
        paket   = self.var_paket.get()
        hari_s  = self.var_hari.get().strip()
        binding = self.var_binding.get()

        if not uname:
            messagebox.showwarning("⚠ Belum Pilih User", "Pilih atau ketik username dulu.")
            return

        # ── VALIDASI: CEK LISENSI EXISTING ────────────────────────────────────
        try:
            lic_file = "rr_billing_license.json"
            if os.path.exists(lic_file):
                with open(lic_file) as f:
                    lic = json.load(f)
                    if lic.get("aktif") and lic.get("username") == uname:
                        lic_expiry = lic.get("expiry", "")
                        resp = messagebox.askyesno(
                            "⚠ Lisensi Sudah Ada",
                            f"User '{uname}' sudah memiliki lisensi aktif!\n\n"
                            f"Expired: {lic_expiry}\n\n"
                            f"Lanjutkan untuk EXTEND/RENEW lisensi?"
                        )
                        if not resp:
                            return
        except Exception as e:
            print(f"License check error: {e}")

        hari_map = {
            "BULANAN": 31, "3BULAN": 92, "TAHUNAN": 365, "LIFETIME": 36500
        }
        edition_map_clean = {
            "BULANAN": "BULANAN", "3BULAN": "3BULAN",
            "TAHUNAN": "TAHUNAN", "LIFETIME": "LIFETIME"
        }
        hari    = int(hari_s) if hari_s.isdigit() and int(hari_s) > 0 else hari_map.get(paket, 31)
        edition = edition_map_clean.get(paket, "BULANAN")

        try:
            if binding == "username":
                kode = generate_for_username(uname, edition=edition, days=hari)
            else:
                kode = LicenseGenerator.generate(edition=edition,
                                                  machine_id="ANY", days=hari)
        except Exception as e:
            messagebox.showerror("✖ Error Generate", str(e))
            return

        self._kode_terkini = kode
        self.lbl_kode.configure(text=kode, text_color=C_ACCENT)

        # Simpan ke log
        expiry = (date.today() + timedelta(days=hari)).isoformat()
        log    = load_log()
        log.insert(0, {
            "tgl_generate": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "username":     uname,
            "paket":        edition,
            "hari":         hari,
            "expiry":       expiry,
            "binding":      binding,
            "kode":         kode,
            "dipakai":      False,
        })
        save_log(log)
        self._load_log_tree()

        messagebox.showinfo("✅ Kode Berhasil Digenerate",
                            f"Kode untuk '{uname}':\n\n{kode}\n\n"
                            f"Paket: {edition} ({hari} hari)\n"
                            f"Berlaku s/d: {expiry}\n\n"
                            f"Klik 'Copy Kode' atau 'Kirim via WA' untuk mengirim ke user.")

    # ── COPY & WA ─────────────────────────────────────────────────────────────
    def _copy_kode(self):
        if not self._kode_terkini:
            messagebox.showwarning("⚠", "Generate kode dulu.")
            return
        self.clipboard_clear()
        self.clipboard_append(self._kode_terkini)
        self.btn_copy.configure(text="✅ Tersalin!", text_color=C_GREEN)
        self.after(1500, lambda: self.btn_copy.configure(
            text="📋 Copy Kode", text_color=C_GREEN))

    def _kirim_wa(self):
        if not self._kode_terkini:
            messagebox.showwarning("⚠", "Generate kode dulu.")
            return
        uname = self.var_username.get().strip()
        paket = self.var_paket.get()
        cfg   = load_config()
        profil= cfg.get("profil_rental", {}).get(uname, {})
        no_hp = profil.get("no_hp", "").replace("-", "").replace(" ", "")
        if no_hp.startswith("0"):
            no_hp = "62" + no_hp[1:]

        import urllib.parse
        pesan = (
            f"Halo kak {profil.get('nama_pemilik', uname)} 👋\n\n"
            f"Terima kasih sudah berlangganan RR BILLING PRO!\n\n"
            f"Berikut kode aktivasi Anda:\n"
            f"*{self._kode_terkini}*\n\n"
            f"📦 Paket: {paket}\n"
            f"⏱ Aktif selama: {self.var_hari.get() or '(default)'} hari\n\n"
            f"Cara aktivasi:\n"
            f"1. Buka aplikasi RR Billing Pro\n"
            f"2. Login dengan username: *{uname}*\n"
            f"3. Buka tab 🔑 Aktivasi\n"
            f"4. Masukkan kode di atas → klik Aktifkan\n\n"
            f"Terima kasih! 🙏"
        )
        url = f"https://wa.me/{no_hp}?text=" + urllib.parse.quote(pesan)
        import webbrowser
        webbrowser.open(url)

    # ── LOG TREE ──────────────────────────────────────────────────────────────
    def _load_log_tree(self):
        for item in self.tree_log.get_children():
            self.tree_log.delete(item)

        log = load_log()
        for entry in log:
            tag = "used" if entry.get("dipakai") else "valid"
            expiry = entry.get("expiry", "—")
            try:
                if date.fromisoformat(expiry) < date.today():
                    tag = "expired"
            except Exception:
                pass
            binding_txt = "Username" if entry.get("binding") == "username" else "Universal"
            self.tree_log.insert("", "end", values=(
                entry.get("tgl_generate", "—"),
                entry.get("username", "—"),
                entry.get("paket", "—"),
                expiry,
                binding_txt,
                entry.get("kode", "—"),
            ), tags=(tag,))

        # Update stat
        total  = len(log)
        belum  = sum(1 for e in log if not e.get("dipakai"))
        unique = len({e.get("username") for e in log})
        self.lbl_stat_total.configure(text=str(total))
        self.lbl_stat_aktif.configure(text=str(belum))
        self.lbl_stat_user.configure(text=str(unique))

    def _get_log_entry_terpilih(self):
        sel = self.tree_log.selection()
        if not sel:
            messagebox.showwarning("⚠", "Pilih baris di tabel log dulu.")
            return None
        vals = self.tree_log.item(sel[0], "values")
        return vals  # (tgl, username, paket, expiry, binding, kode)

    def _copy_log_terpilih(self):
        vals = self._get_log_entry_terpilih()
        if not vals: return
        kode = vals[5]
        self.clipboard_clear()
        self.clipboard_append(kode)
        messagebox.showinfo("📋 Tersalin", f"Kode disalin:\n{kode}")

    def _verif_log_terpilih(self):
        vals = self._get_log_entry_terpilih()
        if not vals: return
        kode     = vals[5]
        username = vals[1]
        binding  = vals[4]

        if binding == "Username":
            sukses, pesan, info = verify_for_username(kode, username)
        else:
            sukses, pesan, info = LicenseValidator.verify(kode)

        ico = "✅ VALID" if sukses else "✖ TIDAK VALID / EXPIRED"
        messagebox.showinfo("🔍 Verifikasi Kode", f"{ico}\n\n{pesan}\n\nDetail: {info}")

    def _wa_log_terpilih(self):
        vals = self._get_log_entry_terpilih()
        if not vals: return
        kode     = vals[5]
        username = vals[1]
        paket    = vals[2]

        cfg   = load_config()
        profil= cfg.get("profil_rental", {}).get(username, {})
        no_hp = profil.get("no_hp", "").replace("-", "").replace(" ", "")
        if no_hp.startswith("0"):
            no_hp = "62" + no_hp[1:]

        import urllib.parse, webbrowser
        pesan = (
            f"Halo kak {profil.get('nama_pemilik', username)} 👋\n\n"
            f"Berikut kode aktivasi RR BILLING PRO:\n"
            f"*{kode}*\n\n"
            f"📦 Paket: {paket}\n\n"
            f"Cara aktivasi:\n"
            f"1. Login dengan username: *{username}*\n"
            f"2. Buka tab 🔑 Aktivasi → masukkan kode → Aktifkan\n\n"
            f"Terima kasih! 🙏"
        )
        url = f"https://wa.me/{no_hp}?text=" + urllib.parse.quote(pesan)
        webbrowser.open(url)

    def _bersihkan_log(self):
        if messagebox.askyesno("🗑 Bersihkan Log", "Hapus semua riwayat generate?"):
            save_log([])
            self._load_log_tree()

    def _bersihkan_log(self):
        if messagebox.askyesno("🗑 Bersihkan Log",
                                "Hapus semua riwayat generate kode?\n"
                                "(Kode yang sudah dikirim ke user tetap berlaku.)"):
            save_log([])
            self._load_log_tree()


# ═══════════════════════════════════════════════════════════════════════════════
#  PATCH main.py: LicenseManager.aktivasi() perlu mendukung username binding
#  Tambahkan metode ini di class LicenseManager (rr_license.py), ATAU
#  override di main.py dengan monkeypatch:
#
#  from rr_keygen import verify_for_username
#  def _aktivasi_dengan_username(kode):
#      uname = ConfigManager.get("current_user") or ""
#      sukses, pesan, info = verify_for_username(kode, uname)
#      if not sukses:
#          # fallback: coba universal verify
#          sukses, pesan, info = LicenseValidator.verify(kode)
#      ...
#
#  Di tab Aktivasi main.py, ganti panggilan LicenseManager.aktivasi(kode)
#  menjadi panggilan di atas yang juga menyertakan username.
#  ─────────────────────────────────────────────────────────────────────────────
#  CATATAN ARSITEKTUR
#  ─────────────────────────────────────────────────────────────────────────────
#  Kode yang di-generate lewat tool ini menggunakan CRC-16 dari USERNAME
#  sebagai "machine_crc" di payload lisensi (menggantikan CRC-16 machine ID).
#
#  Saat user input kode di tab Aktivasi:
#    - Panggil verify_for_username(kode, username=current_user)
#    - LicenseValidator.verify() akan hitung CRC-16(username) dan
#      bandingkan dengan machine_crc di payload
#    - Jika cocok → aktif
#    - Jika tidak cocok → tolak (kode milik user lain)
#
#  Universal kode (binding=ANY) → machine_crc=0x0000 → lolos semua user
# ═══════════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    app = KeygenApp()
    app.mainloop()