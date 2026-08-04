using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Text;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace BillingClientApp
{
    public class ClientAppForm : Form
    {
        // ── Named Pipe IPC ke Service ─────────────────────────────────
        private const string PIPE_NAME = "RRBillingClientService_Pipe";
        private System.Windows.Forms.Timer _pollTimer;
        private bool _isLocked = false;
        private bool _isConnected = false;
        private string _paketAktif = "-";
        private int _timeLeft = 0;
        private int _totalBiaya = 0;
        private bool _isPlaying = false;
        private bool _previousIsLocked = false;
        private string _lockAppPath = "";
        private string _lockMessage = "";
        private bool _warned5 = false;
        private bool _warned3 = false;
        private bool _warned1 = false;
        private string _lastPaket = "-";

        // ── UI ────────────────────────────────────────────────────────
        private NotifyIcon _trayIcon;
        private ContextMenuStrip _trayMenu;
        private ToolStripMenuItem _miStatus;
        private ToolStripMenuItem _miBilling;
        private ToolStripMenuItem _miPaket;
        private ToolStripMenuItem _miTime;
        private ToolStripMenuItem _miTotal;
        private ToolStripMenuItem _miConnect;
        private System.Windows.Forms.Timer _clockTimer;

        private const string APP_LOG_FILE = "rr_billing_client_app.log";

        public ClientAppForm()
        {
            InitializeComponent();
            _lockAppPath = Path.Combine(
                AppDomain.CurrentDomain.BaseDirectory,
                "BillingLockScreenUI.exe");
            _previousIsLocked = _isLocked;
            StartPolling();
        }

        private void InitializeComponent()
        {
            Text = "RR Billing Client";
            WindowState = FormWindowState.Minimized;
            ShowInTaskbar = false;
            FormBorderStyle = FormBorderStyle.None;
            Load += (s, e) => Hide();

            // ── Tray Icon ─────────────────────────────────────────────
            _trayIcon = new NotifyIcon
            {
                Text = "RR Billing Client\nStatus: Menghubungkan...",
                Icon = SystemIcons.Shield,
                Visible = true,
            };

            // ── Tray Menu ─────────────────────────────────────────────
            _trayMenu = new ContextMenuStrip();

            _miStatus = new ToolStripMenuItem("Status: Menghubungkan...")
            {
                Enabled = false,
                ForeColor = Color.Gray,
            };

            _miPaket = new ToolStripMenuItem("Paket: -")
            {
                Enabled = false,
            };

            _miTime = new ToolStripMenuItem("Sisa Waktu: --:--")
            {
                Enabled = false,
            };

            _miTotal = new ToolStripMenuItem("Total Biaya: Rp0")
            {
                Enabled = false,
            };

            _miBilling = new ToolStripMenuItem("💳 Info Billing")
            {
                Enabled = false,
            };

            _miConnect = new ToolStripMenuItem("🔌 Hubungkan ke Server");
            _miConnect.Click += (s, e) => Reconnect();

            _trayMenu.Items.Add(_miStatus);
            _trayMenu.Items.Add(new ToolStripSeparator());
            _trayMenu.Items.Add(_miPaket);
            _trayMenu.Items.Add(_miTime);
            _trayMenu.Items.Add(_miTotal);
            _trayMenu.Items.Add(new ToolStripSeparator());
            _trayMenu.Items.Add(_miConnect);

            _trayIcon.ContextMenuStrip = _trayMenu;
            _trayIcon.MouseClick += TrayIcon_Click;
            _trayIcon.BalloonTipClicked += (s, e) => ShowBillingPopup();

            // ── Clock Timer ───────────────────────────────────────────
            _clockTimer = new System.Windows.Forms.Timer();
            _clockTimer.Interval = 1000;
            _clockTimer.Tick += (s, e) => UpdateDisplay();
            _clockTimer.Start();

            // ── Poll Timer ────────────────────────────────────────────
            _pollTimer = new System.Windows.Forms.Timer();
            _pollTimer.Interval = 3000;
            _pollTimer.Tick += (s, e) => PollStatus();
        }

        private void StartPolling()
        {
            _pollTimer?.Start();
        }

        private void PollStatus()
        {
            try
            {
                string response = PipeRequest("{\"action\":\"GET_STATUS\"}", 3000);
                if (string.IsNullOrEmpty(response))
                {
                    _isConnected = false;
                    UpdateDisplay();
                    return;
                }

                var dict = ManualJsonDeserialize(response);
                string status = dict.GetValueOrDefault("status", "")?.ToString();
                if (status != "OK")
                {
                    _isConnected = false;
                    UpdateDisplay();
                    return;
                }

                _isConnected = dict.GetValueOrDefault("connected", false)?.ToString() == "True";
                _isLocked = dict.GetValueOrDefault("is_locked", false)?.ToString() == "True";
                _lockMessage = dict.GetValueOrDefault("lock_message", "")?.ToString() ?? "";

                // Lock state machine — retried EVERY poll, so a single failed
                // DesktopLocker.Lock() is not fatal: we keep trying until it works.
                bool actuallyLocked = false;
                try
                {
                    // Jika PC terjebak di lock desktop orphan (handle hilang karena
                    // proses lama sudah di-kill saat update), adopsi dulu supaya
                    // Unlock() bisa memindahkan user kembali ke desktop normal.
                    DesktopLocker.AdoptOrphanDesktop();
                    actuallyLocked = DesktopLocker.IsLocked;
                }
                catch { }

                if (_isLocked && !actuallyLocked)
                {
                    bool wasLocked = _previousIsLocked;
                    _previousIsLocked = true;
                    if (!wasLocked)
                    {
                        _trayIcon.ShowBalloonTip(5000, "🔒 PC Terkunci",
                            string.IsNullOrEmpty(_lockMessage)
                                ? "Waktu habis. Silahkan hubungi admin."
                                : _lockMessage,
                            ToolTipIcon.Warning);
                    }
                    try
                    {
                        string lockArgs = "";
                        if (!string.IsNullOrEmpty(_lockMessage))
                            lockArgs = "--message \"" + _lockMessage.Replace("\"", "\\\"") + "\"";
                        if (DesktopLocker.Lock(_lockAppPath, lockArgs))
                        {
                            if (!wasLocked) Log($"[ClientApp] PC terkunci. ({_lockMessage})");
                        }
                        else if (!wasLocked)
                        {
                            Log("[ClientApp] Lock GAGAL dijalankan (akan dicoba lagi di poll berikutnya).");
                        }
                    }
                    catch (Exception lockEx)
                    {
                        Log($"[ClientApp] Lock error: {lockEx.Message}");
                    }
                }
                else if (!_isLocked && actuallyLocked)
                {
                    bool wasLocked = _previousIsLocked;
                    _previousIsLocked = false;
                    try
                    {
                        DesktopLocker.Unlock();
                        if (wasLocked) Log("[ClientApp] PC dibuka kuncinya.");
                    }
                    catch (Exception unlockEx)
                    {
                        Log($"[ClientApp] Unlock error: {unlockEx.Message}");
                    }
                }
                else if (_isLocked && actuallyLocked)
                {
                    // Lock aktif — pastikan UI lock screen masih hidup.
                    // Jika BillingLockScreenUI mati/di-kill, relaunch otomatis.
                    _previousIsLocked = true;
                    try
                    {
                        string lockArgs = "";
                        if (!string.IsNullOrEmpty(_lockMessage))
                            lockArgs = "--message \"" + _lockMessage.Replace("\"", "\\\"") + "\"";
                        DesktopLocker.EnsureLockUIAlive(_lockAppPath, lockArgs);
                    }
                    catch (Exception uiEx)
                    {
                        Log($"[ClientApp] EnsureLockUIAlive error: {uiEx.Message}");
                    }
                }
                else
                {
                    _previousIsLocked = _isLocked;
                }

                if (dict.TryGetValue("billing", out var billingObj) && billingObj is System.Collections.Generic.Dictionary<string, object> billing)
                {
                    _paketAktif = billing.GetValueOrDefault("paket_aktif", "-")?.ToString() ?? "-";
                    _timeLeft = ParseInt(billing.GetValueOrDefault("time_left", 0));
                    _totalBiaya = ParseInt(billing.GetValueOrDefault("total_biaya", 0));
                    _isPlaying = billing.GetValueOrDefault("is_playing", false)?.ToString() == "True";
                }

                ShowRealtimeNotifications();

                UpdateDisplay();
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[ClientApp] Poll error: {ex.Message}");
                _isConnected = false;
                UpdateDisplay();
            }
        }

        // ── Notifikasi realtime (balloon kanan bawah) ─────────────────
        private void ShowRealtimeNotifications()
        {
            if (_isLocked)
            {
                _lastPaket = _paketAktif;
                _warned5 = _warned3 = _warned1 = false;
                return;
            }

            if (_isPlaying && _timeLeft > 0)
            {
                // Deteksi sesi baru → info billing tampil realtime
                if (_lastPaket != _paketAktif)
                {
                    _lastPaket = _paketAktif;
                    _warned5 = _warned3 = _warned1 = false;
                    int m = _timeLeft / 60;
                    int s = _timeLeft % 60;
                    _trayIcon.ShowBalloonTip(6000, "🟢 Sesi Dimulai",
                        $"Paket: {_paketAktif}\nSisa Waktu: {m:D2}:{s:D2}\nTotal: Rp{_totalBiaya:N0}".Replace(",00", ""),
                        ToolTipIcon.Info);
                }

                // Peringatan 5 / 3 / 1 menit — terpicu saat countdown MENURUN
                // melewati ambang, jadi tidak terlewat walau poll melompat.
                int minutesLeft = (int)Math.Ceiling(_timeLeft / 60.0);
                if (minutesLeft > 5)
                {
                    _warned5 = _warned3 = _warned1 = false; // tambah waktu → reset
                }
                else
                {
                    if (minutesLeft <= 5 && !_warned5)
                    {
                        _warned5 = true;
                        _trayIcon.ShowBalloonTip(8000, "⏰ Sisa Waktu Habis",
                            $"Paket {_paketAktif} tersisa 5 menit lagi!\nHubungi kasir untuk tambah waktu.",
                            ToolTipIcon.Warning);
                    }
                    if (minutesLeft <= 3 && !_warned3)
                    {
                        _warned3 = true;
                        _trayIcon.ShowBalloonTip(8000, "⏰ Sisa Waktu Habis",
                            $"Paket {_paketAktif} tersisa 3 menit lagi!\nHubungi kasir untuk tambah waktu.",
                            ToolTipIcon.Warning);
                    }
                    if (minutesLeft <= 1 && !_warned1)
                    {
                        _warned1 = true;
                        _trayIcon.ShowBalloonTip(8000, "⏰ Sisa Waktu Habis",
                            $"Paket {_paketAktif} tersisa 1 menit lagi!\nHubungi kasir untuk tambah waktu.",
                            ToolTipIcon.Warning);
                    }
                }
            }
            else
            {
                _lastPaket = _paketAktif;
                if (!_isPlaying)
                    _warned5 = _warned3 = _warned1 = false;
            }
        }

        private void UpdateDisplay()
        {
            // Tray icon text (realtime, update tiap poll 3 detik)
            string iconText = "RR Billing Client";
            if (_isLocked)
                iconText += "\n🔒 Terkunci";
            else if (_isPlaying)
            {
                int m = _timeLeft / 60;
                int s = _timeLeft % 60;
                iconText += $"\n🟢 {_paketAktif} {m:D2}:{s:D2}";
            }
            else if (_isConnected)
                iconText += "\n⏸ Siap";
            else
                iconText += "\n🔴 Offline";
            _trayIcon.Text = iconText;

            // Menu items
            _miStatus.Text = _isConnected
                ? (_isLocked ? "Status: 🔒 Terkunci" : (_isPlaying ? "Status: 🟢 Sedang Bermain" : "Status: ⏸ Siap"))
                : "Status: 🔴 Offline (Klik untuk hubungkan)";
            _miStatus.ForeColor = _isConnected ? (_isLocked ? Color.Red : Color.Green) : Color.Gray;

            _miPaket.Text = $"Paket: {_paketAktif}";
            _miPaket.Enabled = _isConnected;

            int minutes = _timeLeft / 60;
            int seconds = _timeLeft % 60;
            _miTime.Text = _timeLeft > 0
                ? $"Sisa Waktu: {minutes:D2}:{seconds:D2}"
                : "Sisa Waktu: --:--";
            _miTime.Enabled = _isConnected;

            _miTotal.Text = $"Total Biaya: Rp{_totalBiaya:N0}".Replace(",00", "");
            _miTotal.Enabled = _isConnected;

            _miBilling.Enabled = _isConnected;
        }

        private void ShowBillingPopup()
        {
            int minutes = _timeLeft / 60;
            int seconds = _timeLeft % 60;
            string timeStr = _timeLeft > 0 ? $"{minutes:D2}:{seconds:D2}" : "--:--";

            string msg = $"Paket: {_paketAktif}\n" +
                         $"Sisa Waktu: {timeStr}\n" +
                         $"Total Biaya: Rp{_totalBiaya:N0}\n\n" +
                         $"Status: {(_isLocked ? "🔒 Terkunci" : (_isPlaying ? "🟢 Bermain" : "⏸ Siap"))}";

            _trayIcon.ShowBalloonTip(8000, "💳 Info Billing", msg, ToolTipIcon.Info);
        }

        private void Reconnect()
        {
            // Try to force service to reconnect by sending a PING
            string response = PipeRequest("{\"action\":\"PING\"}", 3000);
            PollStatus();
        }

        // ── File logging (visible: log di C:\RRBillingClient\) ─────────
        private void Log(string message)
        {
            string line = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {message}";
            Debug.WriteLine(line);
            try
            {
                string logPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, APP_LOG_FILE);
                lock (typeof(ClientAppForm))
                {
                    File.AppendAllText(logPath, line + Environment.NewLine);
                }
            }
            catch { }
        }

        private void TrayIcon_Click(object sender, MouseEventArgs e)
        {
            if (e.Button == MouseButtons.Left)
            {
                ShowBillingPopup();
            }
        }

        // ── Named Pipe Client ─────────────────────────────────────────
        private string PipeRequest(string jsonRequest, int timeoutMs)
        {
            try
            {
                using (var pipe = new NamedPipeClientStream(".", PIPE_NAME, PipeDirection.InOut,
                    PipeOptions.Asynchronous))
                {
                    pipe.Connect(timeoutMs);
                    if (!pipe.IsConnected) return null;

                    byte[] reqBytes = Encoding.UTF8.GetBytes(jsonRequest);
                    pipe.Write(reqBytes, 0, reqBytes.Length);
                    pipe.Flush();

                    var buffer = new byte[4096];
                    int bytesRead = pipe.Read(buffer, 0, buffer.Length);
                    if (bytesRead > 0)
                    {
                        return Encoding.UTF8.GetString(buffer, 0, bytesRead);
                    }
                }
            }
            catch (TimeoutException) { }
            catch (FileNotFoundException) { }
            catch (Exception ex)
            {
                Debug.WriteLine($"[PipeClient] Error: {ex.Message}");
            }
            return null;
        }

        // ── Simple JSON Parser ─────────────────────────────────────────
        private System.Collections.Generic.Dictionary<string, object> ManualJsonDeserialize(string json)
        {
            var result = new System.Collections.Generic.Dictionary<string, object>();
            json = json?.Trim();
            if (string.IsNullOrEmpty(json) || !json.StartsWith("{") || !json.EndsWith("}"))
                return result;

            json = json.Substring(1, json.Length - 2).Trim();
            int i = 0;
            while (i < json.Length)
            {
                while (i < json.Length && char.IsWhiteSpace(json[i])) i++;
                if (i >= json.Length) break;
                if (json[i] != '"') break;
                i++;
                var keySb = new StringBuilder();
                while (i < json.Length && json[i] != '"')
                {
                    if (json[i] == '\\') { i++; if (i < json.Length) keySb.Append(json[i]); }
                    else keySb.Append(json[i]);
                    i++;
                }
                i++;
                string key = keySb.ToString();
                while (i < json.Length && char.IsWhiteSpace(json[i])) i++;
                if (i >= json.Length || json[i] != ':') break;
                i++;
                while (i < json.Length && char.IsWhiteSpace(json[i])) i++;
                if (i >= json.Length) break;

                if (json[i] == '{')
                {
                    int depth = 1; i++;
                    var objSb = new StringBuilder();
                    while (i < json.Length && depth > 0)
                    {
                        if (json[i] == '{') depth++;
                        else if (json[i] == '}') { depth--; if (depth == 0) break; }
                        objSb.Append(json[i]); i++;
                    }
                    result[key] = ManualJsonDeserialize("{" + objSb.ToString() + "}");
                    i++;
                }
                else if (json[i] == '"')
                {
                    i++;
                    var valSb = new StringBuilder();
                    while (i < json.Length && json[i] != '"')
                    {
                        if (json[i] == '\\') { i++; if (i < json.Length) valSb.Append(json[i]); }
                        else valSb.Append(json[i]); i++;
                    }
                    i++;
                    result[key] = valSb.ToString();
                }
                else if (json[i] == 't' || json[i] == 'f')
                {
                    if (i + 4 <= json.Length && json.Substring(i, 4) == "true") { result[key] = true; i += 4; }
                    else if (i + 5 <= json.Length && json.Substring(i, 5) == "false") { result[key] = false; i += 5; }
                }
                else if (json[i] == 'n' && i + 4 <= json.Length && json.Substring(i, 4) == "null")
                { result[key] = null; i += 4; }
                else
                {
                    var numSb = new StringBuilder();
                    while (i < json.Length && (char.IsDigit(json[i]) || json[i] == '-' || json[i] == '.'))
                    { numSb.Append(json[i]); i++; }
                    string numStr = numSb.ToString();
                    if (int.TryParse(numStr, out int intVal)) result[key] = intVal;
                    else if (long.TryParse(numStr, out long longVal)) result[key] = longVal;
                    else if (double.TryParse(numStr, out double dblVal)) result[key] = dblVal;
                }
                while (i < json.Length && (char.IsWhiteSpace(json[i]) || json[i] == ',')) i++;
            }
            return result;
        }

        private static int ParseInt(object value, int defaultValue = 0)
        {
            if (value == null) return defaultValue;
            if (value is int i) return i;
            if (value is long l) return (int)l;
            if (int.TryParse(value?.ToString(), out int result)) return result;
            return defaultValue;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _pollTimer?.Dispose();
                _clockTimer?.Dispose();
                _trayIcon?.Dispose();
                _trayMenu?.Dispose();
            }
            base.Dispose(disposing);
        }
    }

    internal static class DictExt
    {
        public static TValue GetValueOrDefault<TKey, TValue>(
            this System.Collections.Generic.IDictionary<TKey, TValue> dict,
            TKey key, TValue defaultValue = default)
        {
            if (dict.TryGetValue(key, out var value)) return value;
            return defaultValue;
        }
    }
}
