"""
test_tv_controller.py — GUI Testing untuk TVController (LG WebOS TV)
Jalankan: python test_tv_controller.py

Fitur:
- Input MAC address dan IP address TV
- Tombol: Power On (WOL), Power Off, Toast, Check Status
- Log output real-time
- Simpan/load konfigurasi TV
"""

import asyncio
import json
import logging
import os
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext

# Tambahkan current directory ke path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tv_controller import TVController


# ═══════════════════════════════════════════════════════════════════════════════
#  THEME COLORS
# ═══════════════════════════════════════════════════════════════════════════════
BG = "#1a1a2e"
BG_PANEL = "#16213e"
BG_CARD = "#0f3460"
FG = "#e6e6e6"
FG_MUTED = "#7f8c8d"
ACCENT = "#00d2ff"
GREEN = "#2ecc71"
RED = "#e74c3c"
YELLOW = "#f39c12"
ORANGE = "#e67e22"
BTN_BG = "#2980b9"
BTN_HOVER = "#3498db"


class TestTVControllerApp:
    """GUI Test untuk TVController"""

    CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "tv_controller_config.json")

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("TV Controller Test - LG WebOS")
        self.root.geometry("700x750")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)

        # Inisialisasi controller
        self.controller = TVController()
        self._running = False

        # Load config tersimpan
        self._saved_config = self._load_config()

        # Setup UI
        self._build_ui()

        # Load config ke entry fields
        if self._saved_config:
            self.entry_mac.delete(0, tk.END)
            self.entry_mac.insert(0, self._saved_config.get("mac", ""))
            self.entry_ip.delete(0, tk.END)
            self.entry_ip.insert(0, self._saved_config.get("ip", ""))

        self.root.mainloop()

    def _build_ui(self):
        """Bangun seluruh UI"""

        # ═══════════ HEADER ═══════════
        hdr = tk.Frame(self.root, bg=BG_PANEL)
        hdr.pack(fill="x", padx=10, pady=(10, 5))

        tk.Label(
            hdr, text="TV Controller Test",
            font=("Segoe UI", 16, "bold"), fg=ACCENT, bg=BG_PANEL
        ).pack(pady=8)

        tk.Label(
            hdr, text="LG WebOS TV - LAN/Wi-Fi Control",
            font=("Segoe UI", 10), fg=FG_MUTED, bg=BG_PANEL
        ).pack(pady=(0, 8))

        # ═══════════ INPUT PANEL ═══════════
        input_frame = tk.Frame(self.root, bg=BG_PANEL)
        input_frame.pack(fill="x", padx=10, pady=5)

        # MAC Address
        tk.Label(
            input_frame, text="MAC Address:",
            font=("Segoe UI", 10, "bold"), fg=FG, bg=BG_PANEL, anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=5, pady=3)

        self.entry_mac = tk.Entry(
            input_frame, width=25, font=("Consolas", 11),
            bg=BG_CARD, fg=FG, insertbackground=FG,
            relief="flat", bd=3
        )
        self.entry_mac.grid(row=0, column=1, padx=5, pady=3, sticky="ew")
        self.entry_mac.insert(0, "AA:BB:CC:DD:EE:FF")

        # IP Address
        tk.Label(
            input_frame, text="IP Address:",
            font=("Segoe UI", 10, "bold"), fg=FG, bg=BG_PANEL, anchor="w"
        ).grid(row=1, column=0, sticky="w", padx=5, pady=3)

        self.entry_ip = tk.Entry(
            input_frame, width=25, font=("Consolas", 11),
            bg=BG_CARD, fg=ACCENT, insertbackground=FG,
            relief="flat", bd=3
        )
        self.entry_ip.grid(row=1, column=1, padx=5, pady=3, sticky="ew")
        self.entry_ip.insert(0, "192.168.1.100")

        # Toast Message
        tk.Label(
            input_frame, text="Toast Message:",
            font=("Segoe UI", 10, "bold"), fg=FG, bg=BG_PANEL, anchor="w"
        ).grid(row=2, column=0, sticky="w", padx=5, pady=3)

        self.entry_toast = tk.Entry(
            input_frame, width=25, font=("Segoe UI", 11),
            bg=BG_CARD, fg=YELLOW, insertbackground=FG,
            relief="flat", bd=3
        )
        self.entry_toast.grid(row=2, column=1, padx=5, pady=3, sticky="ew")
        self.entry_toast.insert(0, "Waktu tersisa 5 menit!")

        input_frame.columnconfigure(1, weight=1)

        # ═══════════ ACTION BUTTONS ═══════════
        btn_frame = tk.Frame(self.root, bg=BG_PANEL)
        btn_frame.pack(fill="x", padx=10, pady=5)

        tk.Label(
            btn_frame, text="Aksi:",
            font=("Segoe UI", 10, "bold"), fg=FG, bg=BG_PANEL
        ).pack(anchor="w", padx=5)

        btn_row = tk.Frame(btn_frame, bg=BG_PANEL)
        btn_row.pack(fill="x", padx=5, pady=5)

        # Tombol Power ON (WOL)
        self.btn_power_on = tk.Button(
            btn_row, text="POWER ON\n(WOL)",
            font=("Segoe UI", 10, "bold"), fg="white", bg=GREEN,
            activebackground="#27ae60", relief="flat",
            width=14, height=3,
            command=lambda: self._run_async(self._action_power_on)
        )
        self.btn_power_on.pack(side="left", padx=3)

        # Tombol Check Status
        self.btn_check = tk.Button(
            btn_row, text="CEK\nSTATUS",
            font=("Segoe UI", 10, "bold"), fg="white", bg=BTN_BG,
            activebackground=BTN_HOVER, relief="flat",
            width=14, height=3,
            command=lambda: self._run_async(self._action_check_status)
        )
        self.btn_check.pack(side="left", padx=3)

        # Tombol Toast Message
        self.btn_toast = tk.Button(
            btn_row, text="TOAST\nMESSAGE",
            font=("Segoe UI", 10, "bold"), fg="white", bg=ORANGE,
            activebackground="#d35400", relief="flat",
            width=14, height=3,
            command=lambda: self._run_async(self._action_toast)
        )
        self.btn_toast.pack(side="left", padx=3)

        # Tombol Power OFF
        self.btn_power_off = tk.Button(
            btn_row, text="POWER\nOFF",
            font=("Segoe UI", 10, "bold"), fg="white", bg=RED,
            activebackground="#c0392b", relief="flat",
            width=14, height=3,
            command=lambda: self._run_async(self._action_power_off)
        )
        self.btn_power_off.pack(side="left", padx=3)

        # ═══════════ STATUS BAR ═══════════
        status_frame = tk.Frame(self.root, bg=BG_PANEL)
        status_frame.pack(fill="x", padx=10, pady=5)

        self.lbl_status = tk.Label(
            status_frame, text="Siap - masukkan MAC & IP, lalu pilih aksi",
            font=("Segoe UI", 9), fg=FG_MUTED, bg=BG_PANEL, anchor="w"
        )
        self.lbl_status.pack(fill="x", padx=5, pady=5)

        self.lbl_tv_status = tk.Label(
            status_frame, text="TV Status: -",
            font=("Segoe UI", 10, "bold"), fg=FG_MUTED, bg=BG_PANEL, anchor="w"
        )
        self.lbl_tv_status.pack(fill="x", padx=5, pady=(0, 5))

        # ═══════════ LOG OUTPUT ═══════════
        log_frame = tk.Frame(self.root, bg=BG_PANEL)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        tk.Label(
            log_frame, text="Log Output:",
            font=("Segoe UI", 10, "bold"), fg=FG, bg=BG_PANEL, anchor="w"
        ).pack(anchor="w", padx=5, pady=(5, 0))

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=12,
            font=("Consolas", 9), fg=FG, bg="#0d1117",
            insertbackground=FG, relief="flat",
            state="disabled", wrap="word"
        )
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)

        # Tombol Clear Log
        tk.Button(
            log_frame, text="Clear Log",
            font=("Segoe UI", 8), fg=FG_MUTED, bg=BG_CARD,
            relief="flat", command=self._clear_log
        ).pack(anchor="e", padx=5, pady=(0, 5))

    def _log(self, message: str, level: str = "INFO"):
        """Tulis pesan ke log output"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {"INFO": "[i]", "OK": "[OK]", "WARN": "[!]", "ERROR": "[X]"}.get(level, "[i]")

        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"[{timestamp}] {prefix} {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        """Bersihkan log"""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _update_status(self, text: str, color: str = FG_MUTED):
        """Update status label"""
        self.lbl_status.configure(text=text, fg=color)
        self.root.update_idletasks()

    def _update_tv_status(self, text: str, color: str = FG_MUTED):
        """Update TV status label"""
        self.lbl_tv_status.configure(text=f"TV Status: {text}", fg=color)
        self.root.update_idletasks()

    def _run_async(self, coro_func):
        """Jalankan async function di background thread"""
        if self._running:
            self._log("Masih ada aksi yang berjalan, tunggu...", "WARN")
            return

        self._running = True
        self._set_buttons_state("disabled")

        def _thread():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(coro_func())
                loop.close()
            except Exception as e:
                self._log(f"Thread error: {e}", "ERROR")
            finally:
                self.root.after(0, self._on_action_done)

        threading.Thread(target=_thread, daemon=True).start()

    def _on_action_done(self):
        """Callback setelah aksi selesai"""
        self._running = False
        self._set_buttons_state("normal")
        self._update_status("Siap - pilih aksi berikutnya", FG_MUTED)

    def _set_buttons_state(self, state: str):
        """Enable/disable semua tombol aksi"""
        for btn in [self.btn_power_on, self.btn_check,
                    self.btn_toast, self.btn_power_off]:
            btn.configure(state=state)

    def _save_config(self):
        """Simpan MAC dan IP ke file config"""
        try:
            config = {
                "mac": self.entry_mac.get().strip(),
                "ip": self.entry_ip.get().strip(),
            }
            with open(self.CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)
            self._log(f"Config disimpan ke {os.path.basename(self.CONFIG_FILE)}", "OK")
        except Exception as e:
            self._log(f"Gagal simpan config: {e}", "ERROR")

    def _load_config(self) -> dict:
        """Load config dari file"""
        try:
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    # ═════════════════════════════════════════════════════════════════════════
    #  ACTIONS
    # ═════════════════════════════════════════════════════════════════════════

    async def _action_power_on(self):
        """Aksi: Power ON via WOL"""
        mac = self.entry_mac.get().strip()
        if not mac:
            self._log("MAC address kosong!", "ERROR")
            return

        self.root.after(0, lambda: self._update_status(
            f"Mengirim WOL ke {mac}...", YELLOW))

        self._log(f"Mengirim Wake-on-LAN ke {mac}...")
        ok = self.controller.turn_on_tv(mac)

        if ok:
            self._log(f"WOL Magic Packet berhasil dikirim ke {mac}", "OK")
            self._log("Note: TV butuh beberapa detik untuk menyala setelah WOL", "INFO")
            self._save_config()
        else:
            self._log(f"Gagal mengirim WOL ke {mac}", "ERROR")

    async def _action_check_status(self):
        """Aksi: Cek Status TV"""
        ip = self.entry_ip.get().strip()
        if not ip:
            self._log("IP address kosong!", "ERROR")
            return

        self.root.after(0, lambda: self._update_status(
            f"Mengecek status TV {ip}...", YELLOW))

        self._log(f"Mengecek status power TV {ip}...")

        state = await self.controller.get_power_state(ip)

        if state:
            power = state.get("state", "Unknown")
            is_on = power.lower() in ("active", "on", "unknown")

            if is_on:
                self._log(f"TV {ip} MENYALA (state: {power})", "OK")
                self.root.after(0, lambda: self._update_tv_status(
                    f"MENYALA ({power})", GREEN))
            else:
                self._log(f"TV {ip} MATI (state: {power})", "WARN")
                self.root.after(0, lambda: self._update_tv_status(
                    f"MATI ({power})", RED))
        else:
            self._log(f"Tidak dapat cek status TV {ip}", "ERROR")
            self.root.after(0, lambda: self._update_tv_status(
                "OFFLINE / BELUM PAIRING", RED))

        self._save_config()

    async def _action_toast(self):
        """Aksi: Kirim Toast Message"""
        ip = self.entry_ip.get().strip()
        msg = self.entry_toast.get().strip()

        if not ip:
            self._log("IP address kosong!", "ERROR")
            return
        if not msg:
            self._log("Pesan toast kosong!", "ERROR")
            return

        self.root.after(0, lambda: self._update_status(
            f"Mengirim toast ke {ip}...", YELLOW))

        self._log(f"Mengirim toast ke {ip}: {msg}")
        ok = await self.controller.show_toast_message(ip, msg)

        if ok:
            self._log(f"Toast berhasil dikirim ke {ip}", "OK")
            self._save_config()
        else:
            self._log(f"Gagal kirim toast ke {ip}", "ERROR")

    async def _action_power_off(self):
        """Aksi: Power OFF"""
        ip = self.entry_ip.get().strip()
        if not ip:
            self._log("IP address kosong!", "ERROR")
            return

        # Konfirmasi
        confirm = messagebox.askyesno(
            "Konfirmasi Power Off",
            f"Yakin ingin mematikan TV {ip}?",
            icon="warning"
        )
        if not confirm:
            self._log("Power off dibatalkan oleh user", "WARN")
            return

        self.root.after(0, lambda: self._update_status(
            f"Mematikan TV {ip}...", YELLOW))

        self._log(f"Mematikan TV {ip}...")
        ok = await self.controller.turn_off_tv(ip)

        if ok:
            self._log(f"TV {ip} berhasil dimatikan", "OK")
            self.root.after(0, lambda: self._update_tv_status(
                "MATI (standby)", RED))
            self._save_config()
        else:
            self._log(f"Gagal matikan TV {ip}", "ERROR")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Setup logging ke console juga
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 60)
    print("  TV Controller Test - LG WebOS TV")
    print("  Jalankan test dengan GUI interaktif")
    print("=" * 60)
    print()
    print("  1. Pastikan TV dan komputer satu jaringan")
    print("  2. Masukkan MAC address dan IP TV")
    print("  3. Klik tombol aksi untuk test")
    print()
    print("  Pertama kali: TV akan muncul popup pairing")
    print("  Tekan Allow/OK di remote TV untuk approve")
    print()
    print("=" * 60)

    app = TestTVControllerApp()
