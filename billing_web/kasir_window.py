"""RR Billing Pro â€” Jendela Aplikasi Kasir (wrapper pywebview, frameless).

- Server.py dijalankan sebagai proses anak (tanpa auto-buka browser).
- Title bar milik Windows diganti titlebar HTML yang ikut tema aplikasi.
- Tombol X jendela â†’ popup aplikasi sendiri:
      [Batal] [Keluar Saja] [Tutup Rental & Keluar]
- Jika keluar dengan "Tutup Rental" â†’ rental diset TUTUP + push web booking.

ATURAN THREAD: semua operasi form WinForms HANYA lewat Api._ui()
(BeginInvoke ke UI thread). Jangan sentuh form langsung dari thread js_api.
"""
import faulthandler
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
URL = "http://localhost:8000"   # WAJIB localhost (bukan 127.0.0.1) agar login Google valid
ICON_ICO = os.path.join(BASE, "static", "logo.ico")
ICON_PNG = os.path.join(BASE, "static", "logo.png")

# Referensi jendela disimpan di sini (closure modul) â€” BUKAN sebagai atribut
# objek Api! pywebview merefleksikan seluruh atribut instance Api saat membangun
# window.pywebview.api; objek Window/.NET di dalamnya menyebabkan deadlock UI.
_ST = {"win": None}

# Perekam stack semua thread tiap 60 detik â€” untuk diagnosis bila macet.
try:
    _fh = open(os.path.join(tempfile.gettempdir(), "kasir_stacks.log"), "w", buffering=1)
    faulthandler.dump_traceback_later(60, repeat=True, file=_fh)
except Exception:
    _fh = None


def server_sudah_jalan():
    try:
        urllib.request.urlopen(URL + "/", timeout=1)
        return True
    except Exception:
        return False


def tunggu_server(timeout=40):
    for _ in range(int(timeout / 0.5)):
        if server_sudah_jalan():
            return True
        time.sleep(0.5)
    return False


def tutup_rental():
    try:
        req = urllib.request.Request(URL + "/api/booking/ops/local-close", method="POST")
        urllib.request.urlopen(req, timeout=4)
    except Exception:
        pass


def matikan_server(proc):
    if proc is not None:
        try:
            proc.terminate()
        except Exception:
            pass


class Api:
    """Jembatan JS â†” Python.
    SEMUA operasi form dieksekusi di UI thread via BeginInvoke â€”
    jangan pernah sentuh form langsung dari thread js_api (deadlock!)."""

    def __init__(self):
        self.exit_mode = None
        self._bg = None

    @property
    def _w(self):
        return _ST.get("win")

    def _ui(self, fn):
        """Marshal ke UI thread tanpa menunggu (BeginInvoke)."""
        form = getattr(self._w, "native", None) if self._w else None
        if form is None:
            return
        try:
            from System.Windows.Forms import MethodInvoker
            form.BeginInvoke(MethodInvoker(fn))
        except Exception:
            pass

    def _apply_bg(self):
        if not self._bg:
            return
        from System.Drawing import Color
        c = Color.FromArgb(255, *self._bg)

        def _set():
            try:
                form = getattr(self._w, "native", None)
                if form:
                    form.BackColor = c
            except Exception:
                pass
        self._ui(_set)

    def set_bg(self, hexcolor=None):
        """Dipanggil dari web saat tema berubah agar tepi jendela ikut warna."""
        try:
            if not hexcolor:
                return
            h = str(hexcolor).strip().lstrip("#")
            if len(h) >= 6:
                self._bg = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
                self._apply_bg()
        except Exception:
            pass

    def exit_app(self, mode=None):
        # TANPA panggilan jaringan di sini â€” tutup rental dilakukan oleh
        # handler closed setelah jendela benar-benar tertutup.
        self.exit_mode = mode or "saja"

        def _close():
            time.sleep(0.15)
            try:
                self._w.destroy()
            except Exception:
                pass
        threading.Thread(target=_close, daemon=True).start()

    def minimize(self):
        def _do():
            try:
                from System.Windows.Forms import FormWindowState
                form = getattr(self._w, "native", None)
                if form:
                    form.WindowState = FormWindowState.Minimized
            except Exception:
                pass
        self._ui(_do)

    def toggle_maximize(self):
        def _do():
            try:
                from System.Windows.Forms import FormWindowState
                form = getattr(self._w, "native", None)
                if not form:
                    return
                if form.WindowState == FormWindowState.Maximized:
                    form.WindowState = FormWindowState.Normal
                else:
                    form.WindowState = FormWindowState.Maximized
            except Exception:
                pass
        self._ui(_do)

    def drag(self):
        def _do():
            try:
                import ctypes
                form = getattr(self._w, "native", None)
                if not form:
                    return
                ctypes.windll.user32.ReleaseCapture()
                ctypes.windll.user32.SendMessageW(int(form.Handle), 0xA1, 2, 0)
            except Exception:
                pass
        self._ui(_do)   # modal move-loop berjalan di UI thread


def _patch_edgechrome_no_tracking_prevention():
    """Matikan Tracking Prevention WebView2 yang memblokir storage
    iframe Firebase saat login Google (getRedirectResult null)."""
    try:
        import webview.platforms.edgechromium as ec
        from Microsoft.Web.WebView2.Core import (
            CoreWebView2Environment,
            CoreWebView2EnvironmentOptions,
        )
        if getattr(ec.EdgeChrome, "_no_tp_patched", False):
            return

        def _init_no_tp(self, form, window, cache_dir):
            self.pywebview_window = window
            self.webview = ec.WebView2()
            props = ec.CoreWebView2CreationProperties()

            runtime_path = ec.webview_settings['WEBVIEW2_RUNTIME_PATH']
            if runtime_path:
                if not os.path.isabs(runtime_path):
                    runtime_path = os.path.join(ec.get_app_root(), runtime_path)
                if os.path.exists(runtime_path):
                    props.BrowserExecutableFolder = runtime_path

            props.UserDataFolder = cache_dir
            self.user_data_folder = props.UserDataFolder
            props.set_IsInPrivateModeEnabled(ec._state['private_mode'])
            props.AdditionalBrowserArguments = ''
            if ec.webview_settings['ALLOW_FILE_URLS']:
                props.AdditionalBrowserArguments += ' --allow-file-access-from-files'
            if ec.webview_settings['REMOTE_DEBUGGING_PORT'] is not None:
                props.AdditionalBrowserArguments += (
                    f' --remote-debugging-port={ec.webview_settings["REMOTE_DEBUGGING_PORT"]}'
                )

            self.webview.CreationProperties = props
            self.form = form
            form.Controls.Add(self.webview)

            self.js_results = {}
            self.js_result_semaphore = ec.Semaphore(0)
            self.webview.Dock = ec.WinForms.DockStyle.Fill
            self.webview.BringToFront()
            self.webview.CoreWebView2InitializationCompleted += self.on_webview_ready
            self.webview.NavigationStarting += self.on_navigation_start
            self.webview.NavigationCompleted += self.on_navigation_completed
            self.webview.WebMessageReceived += self.on_script_notify
            self.syncContextTaskScheduler = ec.TaskScheduler.FromCurrentSynchronizationContext()
            self.webview.DefaultBackgroundColor = ec.Color.FromArgb(
                255,
                int(window.background_color.lstrip('#')[0:2], 16),
                int(window.background_color.lstrip('#')[2:4], 16),
                int(window.background_color.lstrip('#')[4:6], 16),
            )
            if window.transparent:
                self.webview.DefaultBackgroundColor = ec.Color.Transparent

            self.url = None
            self.ishtml = False
            self.html = ec.DEFAULT_HTML

            opts = CoreWebView2EnvironmentOptions()
            opts.EnableTrackingPrevention = False
            opts.AdditionalBrowserArguments = (
                '--disable-features=ThirdPartyStoragePartitioning,'
                'PartitionedStorage,ElasticOverscroll'
            )
            env = CoreWebView2Environment.CreateAsync(None, cache_dir, opts).Result
            self.webview.EnsureCoreWebView2Async(env)

        _init_no_tp.__name__ = "__init__"
        ec.EdgeChrome.__init__ = _init_no_tp
        ec.EdgeChrome._no_tp_patched = True
    except Exception as e:
        print("Patch Tracking Prevention gagal:", e)


def main():
    proc = None
    if not server_sudah_jalan():
        env = dict(os.environ)
        env["RRB_NO_BROWSER"] = "1"          # jangan buka browser bawaan
        proc = subprocess.Popen([sys.executable, os.path.join(BASE, "server.py")],
                                cwd=BASE, env=env,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        if not tunggu_server():
            print("Server gagal start â€” cek billing_web/web_app.log")
            matikan_server(proc)
            sys.exit(1)
    else:
        print("Server sudah berjalan â€” memakai instance yang ada.")

    import webview

    _patch_edgechrome_no_tracking_prevention()

    api = Api()

    def _pasang_ikon_dan_warna():
        """Ikon HD + judul (dipanggil event shown)."""
        try:
            from System.Drawing import Icon
            form = getattr(win, "native", None)
            if form is None:
                return
            if os.path.isfile(ICON_ICO):
                form.Icon = Icon(ICON_ICO)
            elif os.path.isfile(ICON_PNG):
                from System.Drawing import Bitmap
                bmp = Bitmap.FromFile(ICON_PNG)
                form.Icon = Icon.FromHandle(bmp.GetHicon())
            form.Text = "RR Billing Pro â€” Kasir"
        except Exception as e:
            print("Ikon jendela gagal:", e)
        api._apply_bg()

    def _on_closing():
        """Alt+F4 / WM_CLOSE â†’ batalkan, tampilkan popup milik aplikasi.
        evaluate_js TIDAK boleh dipanggil langsung dari UI thread."""
        if api.exit_mode:
            return None          # izinkan menutup (sudah lewat popup)

        def _tanya():
            time.sleep(0.15)
            try:
                win.evaluate_js("if(window.showExitAsk) showExitAsk();")
            except Exception:
                pass
        threading.Thread(target=_tanya, daemon=True).start()
        return False             # batalkan penutupan (non-blocking)

    win = webview.create_window(
        "RR Billing Pro â€” Kasir",
        URL,
        width=1366,
        height=860,
        min_size=(1100, 700),
        confirm_close=False,     # dialog generik dimatikan â€” pakai popup sendiri
        js_api=api,
        background_color="#05060e",
        frameless=True,          # tanpa title bar Windows â†’ titlebar HTML ikut tema
        easy_drag=False,         # drag manual via titlebar (api.drag)
        text_select=True,
    )
    _ST["win"] = win

    win.events.shown += _pasang_ikon_dan_warna
    win.events.closing += _on_closing

    def on_closed():
        if api.exit_mode != "saja":   # 'tutup' atau ditutup tanpa lewat popup
            tutup_rental()
        matikan_server(proc)

    win.events.closed += on_closed
    webview.start(private_mode=False)

    # fallback jika loop selesai tanpa event closed terpicu
    if api.exit_mode != "saja":
        tutup_rental()
    matikan_server(proc)


if __name__ == "__main__":
    main()

