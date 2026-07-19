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

        // ── UI ────────────────────────────────────────────────────────
        private NotifyIcon _trayIcon;
        private ContextMenuStrip _trayMenu;
        private ToolStripMenuItem _miStatus;
        private ToolStripMenuItem _miBilling;
        private ToolStripMenuItem _miPaket;
        private ToolStripMenuItem _miTime;
        private ToolStripMenuItem _miTotal;
        private ToolStripMenuItem _miConnect;
        private ToolStripMenuItem _miExit;
        private System.Windows.Forms.Timer _clockTimer;

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

            _miExit = new ToolStripMenuItem("✖ Keluar");
            _miExit.Click += (s, e) => ExitApp();

            _trayMenu.Items.Add(_miStatus);
            _trayMenu.Items.Add(new ToolStripSeparator());
            _trayMenu.Items.Add(_miPaket);
            _trayMenu.Items.Add(_miTime);
            _trayMenu.Items.Add(_miTotal);
            _trayMenu.Items.Add(new ToolStripSeparator());
            _trayMenu.Items.Add(_miConnect);
            _trayMenu.Items.Add(_miExit);

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

                // Detect lock state change and call DesktopLocker from user session
                if (_isLocked != _previousIsLocked)
                {
                    _previousIsLocked = _isLocked;
                    if (_isLocked)
                    {
                        _trayIcon.ShowBalloonTip(5000, "🔒 PC Terkunci",
                            string.IsNullOrEmpty(_lockMessage)
                                ? "Waktu habis. Silahkan hubungi admin."
                                : _lockMessage,
                            ToolTipIcon.Warning);
                        try { DesktopLocker.Lock(_lockAppPath); }
                        catch (Exception lockEx)
                        {
                            Debug.WriteLine($"[ClientApp] Lock error: {lockEx.Message}");
                        }
                    }
                    else
                    {
                        try { DesktopLocker.Unlock(); }
                        catch (Exception unlockEx)
                        {
                            Debug.WriteLine($"[ClientApp] Unlock error: {unlockEx.Message}");
                        }
                    }
                }

                if (dict.TryGetValue("billing", out var billingObj) && billingObj is System.Collections.Generic.Dictionary<string, object> billing)
                {
                    _paketAktif = billing.GetValueOrDefault("paket_aktif", "-")?.ToString() ?? "-";
                    _timeLeft = ParseInt(billing.GetValueOrDefault("time_left", 0));
                    _totalBiaya = ParseInt(billing.GetValueOrDefault("total_biaya", 0));
                    _isPlaying = billing.GetValueOrDefault("is_playing", false)?.ToString() == "True";
                }

                UpdateDisplay();
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[ClientApp] Poll error: {ex.Message}");
                _isConnected = false;
                UpdateDisplay();
            }
        }

        private void UpdateDisplay()
        {
            // Tray icon text
            string iconText = "RR Billing Client";
            if (_isLocked)
                iconText += "\n🔒 Terkunci";
            else if (_isPlaying)
                iconText += "\n🟢 Sedang Bermain";
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

        private void ExitApp()
        {
            _pollTimer?.Stop();
            _clockTimer?.Stop();
            _trayIcon?.Visible = false;
            Application.Exit();
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
