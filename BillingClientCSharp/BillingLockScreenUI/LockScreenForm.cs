using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Text;
using System.IO;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace BillingLockScreenUI
{
    public partial class LockScreenForm : Form
    {
        // ── Anti-ALT+F4, Anti-TaskSwitch, Anti-Bypass ─────────────────────
        private const int WS_EX_TOOLWINDOW = 0x00000080;
        private const int WS_EX_APPWINDOW = 0x00040000;
        private const int WS_EX_TOPMOST = 0x00000008;
        private const int WS_EX_NOACTIVATE = 0x08000000;
        private const int GWL_EXSTYLE = -20;
        private const int WM_SYSCOMMAND = 0x0112;
        private const int SC_CLOSE = 0xF060;
        private const int SC_MINIMIZE = 0xF020;
        private const int SC_MAXIMIZE = 0xF030;
        private const int SC_RESTORE = 0xF120;
        private const int SC_MOVE = 0xF010;
        private const int SC_SIZE = 0xF000;
        private const int WM_KEYDOWN = 0x0100;
        private const int WM_SYSKEYDOWN = 0x0104;
        private const int WM_HOTKEY = 0x0312;
        private const int WM_WINDOWPOSCHANGING = 0x0046;

        [DllImport("user32.dll")]
        private static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);

        [DllImport("user32.dll")]
        private static extern int GetWindowLong(IntPtr hWnd, int nIndex);

        [DllImport("user32.dll")]
        private static extern bool BlockInput(bool fBlock);

        [DllImport("user32.dll")]
        private static extern IntPtr FindWindow(string lpClassName, string lpWindowName);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern IntPtr FindWindowEx(IntPtr hwndParent, IntPtr hwndChildAfter, string lpszClass, string lpszWindow);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool PostMessage(IntPtr hWnd, int Msg, IntPtr wParam, IntPtr lParam);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool CloseWindow(IntPtr hWnd);

        [DllImport("user32.dll", EntryPoint = "SystemParametersInfo")]
        private static extern bool SystemParametersInfo(uint uiAction, uint uiParam, IntPtr pvParam, uint fWinIni);

        private const uint SPI_SETSCREENSAVERRUNNING = 0x0061;
        private const uint SPIF_SENDWININICHANGE = 0x02;

        // ── UI Components ──────────────────────────────────────────────
        private Label _lblMessage;
        private Label _lblSubMessage;
        private Label _lblTime;
        private Label _lblStatus;
        private Label _lblWatermark;
        private PictureBox _logoBox;
        private System.Windows.Forms.Timer _timer;
        private DateTime _startTime;

        // ── Server communication (optional, for real-time status) ──────
        private TcpClient _tcpClient;
        private NetworkStream _stream;
        private Thread _serverThread;
        private bool _keepRunning = true;
        private string _serverHost = "127.0.0.1";
        private int _serverPort = 5000;

        public LockScreenForm(string message = null)
        {
            InitializeComponent();
            _startTime = DateTime.Now;
            SetupUI(message ?? "PC TERKUNCI");
            StartTimer();
            IdentifyDesktop();
        }

        private void InitializeComponent()
        {
            _lblMessage = new Label();
            _lblSubMessage = new Label();
            _lblTime = new Label();
            _lblStatus = new Label();
            _lblWatermark = new Label();
            _logoBox = new PictureBox();
            _timer = new System.Windows.Forms.Timer();

            SuspendLayout();

            // Form
            Text = "PC Terkunci - RR Billing Pro";
            WindowState = FormWindowState.Maximized;
            FormBorderStyle = FormBorderStyle.None;
            StartPosition = FormStartPosition.Manual;
            Bounds = Screen.PrimaryScreen.Bounds;
            TopMost = true;
            ShowInTaskbar = false;
            ControlBox = false;
            BackColor = Color.FromArgb(18, 18, 30);
            DoubleBuffered = true;
            Cursor = Cursors.No;
            KeyPreview = false;

            // Prevent the form from being shown in Alt+Tab
            int exStyle = GetWindowLong(Handle, GWL_EXSTYLE);
            SetWindowLong(Handle, GWL_EXSTYLE, exStyle | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE);

            // Timer for clock update
            _timer.Interval = 1000;
            _timer.Tick += Timer_Tick;

            // ESC key handling
            KeyDown += LockScreenForm_KeyDown;

            ResumeLayout(false);
        }

        protected override void OnLoad(EventArgs e)
        {
            base.OnLoad(e);

            // Hide the taskbar on this desktop
            IntPtr taskbarHwnd = FindWindow("Shell_TrayWnd", null);
            if (taskbarHwnd != IntPtr.Zero)
                ShowWindow(taskbarHwnd, SW_HIDE);

            // Disable Alt+Tab / Ctrl+Alt+Del prevention
            SystemParametersInfo(SPI_SETSCREENSAVERRUNNING, 1, IntPtr.Zero, SPIF_SENDWININICHANGE);
        }

        [DllImport("user32.dll")]
        static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
        const int SW_HIDE = 0;

        private void SetupUI(string message)
        {
            Controls.Clear();

            // ── Logo / Icon ────────────────────────────────────────────
            _logoBox = new PictureBox
            {
                Size = new Size(96, 96),
                BackColor = Color.Transparent,
                Image = DrawLockIcon(96, 96),
                SizeMode = PictureBoxSizeMode.CenterImage,
            };

            // ── Main Message ───────────────────────────────────────────
            _lblMessage = new Label
            {
                Text = "🔒  " + message.Replace("\\n", "\n"),
                Font = new Font("Segoe UI", 28, FontStyle.Bold),
                ForeColor = Color.FromArgb(124, 77, 255),
                BackColor = Color.Transparent,
                AutoSize = false,
                TextAlign = ContentAlignment.MiddleCenter,
                Width = Screen.PrimaryScreen.Bounds.Width - 200,
                Height = 120,
            };

            // ── Sub Message ────────────────────────────────────────────
            _lblSubMessage = new Label
            {
                Text = "Sesi PC ini sedang dikunci oleh sistem billing.\n" +
                       "Silahkan hubungi admin untuk membuka kunci.",
                Font = new Font("Segoe UI", 14, FontStyle.Regular),
                ForeColor = Color.FromArgb(180, 180, 180),
                BackColor = Color.Transparent,
                AutoSize = false,
                TextAlign = ContentAlignment.MiddleCenter,
                Width = Screen.PrimaryScreen.Bounds.Width - 200,
                Height = 60,
            };

            // ── Clock ──────────────────────────────────────────────────
            _lblTime = new Label
            {
                Text = DateTime.Now.ToString("HH:mm:ss"),
                Font = new Font("Segoe UI", 48, FontStyle.Bold),
                ForeColor = Color.FromArgb(50, 50, 80),
                BackColor = Color.Transparent,
                AutoSize = false,
                TextAlign = ContentAlignment.MiddleCenter,
                Width = 400,
                Height = 80,
            };

            // ── Status ─────────────────────────────────────────────────
            _lblStatus = new Label
            {
                Text = "Status: Terkunci",
                Font = new Font("Segoe UI", 10, FontStyle.Regular),
                ForeColor = Color.FromArgb(100, 100, 120),
                BackColor = Color.Transparent,
                AutoSize = false,
                TextAlign = ContentAlignment.MiddleCenter,
                Width = 400,
                Height = 30,
            };

            // ── Watermark ──────────────────────────────────────────────
            _lblWatermark = new Label
            {
                Text = "RR Billing Pro v2.3 | Hubungi Admin untuk Buka Kunci",
                Font = new Font("Segoe UI", 9, FontStyle.Regular),
                ForeColor = Color.FromArgb(60, 60, 80),
                BackColor = Color.Transparent,
                AutoSize = false,
                TextAlign = ContentAlignment.MiddleCenter,
                Width = Screen.PrimaryScreen.Bounds.Width,
                Height = 24,
            };

            // ── Layout ─────────────────────────────────────────────────
            int centerX = Screen.PrimaryScreen.Bounds.Width / 2;
            int centerY = Screen.PrimaryScreen.Bounds.Height / 2;

            _logoBox.Location = new Point(centerX - 48, centerY - 220);
            _lblMessage.Location = new Point(100, centerY - 100);
            _lblSubMessage.Location = new Point(100, centerY + 10);
            _lblTime.Location = new Point(centerX - 200, centerY + 100);
            _lblStatus.Location = new Point(centerX - 200, centerY + 190);
            _lblWatermark.Location = new Point(0, Screen.PrimaryScreen.Bounds.Height - 40);

            Controls.Add(_logoBox);
            Controls.Add(_lblMessage);
            Controls.Add(_lblSubMessage);
            Controls.Add(_lblTime);
            Controls.Add(_lblStatus);
            Controls.Add(_lblWatermark);
        }

        private void StartTimer()
        {
            _timer.Start();
        }

        private void Timer_Tick(object sender, EventArgs e)
        {
            _lblTime.Text = DateTime.Now.ToString("HH:mm:ss");

            TimeSpan elapsed = DateTime.Now - _startTime;
            if (elapsed.TotalMinutes >= 1)
            {
                _lblStatus.Text = $"Status: Terkunci ({elapsed.TotalMinutes:F0} menit)";
            }
        }

        // ── Key Handling ───────────────────────────────────────────────
        private void LockScreenForm_KeyDown(object sender, KeyEventArgs e)
        {
            // Block ALL keys except those needed for accessibility
            e.Handled = true;
            e.SuppressKeyPress = true;

            // Log key presses for audit (optional)
            Debug.WriteLine($"[LockScreen] Key pressed: {e.KeyCode} (Alt={e.Alt}, Control={e.Control}, Shift={e.Shift})");
        }

        protected override void WndProc(ref Message m)
        {
            // Block Alt+F4, system menu commands, etc.
            if (m.Msg == WM_SYSCOMMAND)
            {
                int cmd = m.WParam.ToInt32() & 0xFFF0;
                if (cmd == SC_CLOSE || cmd == SC_MINIMIZE || cmd == SC_MAXIMIZE ||
                    cmd == SC_RESTORE || cmd == SC_MOVE || cmd == SC_SIZE)
                {
                    return; // Block the command
                }
            }

            if (m.Msg == WM_SYSKEYDOWN)
            {
                // Block Alt+Tab, Alt+Esc, etc.
                return;
            }

            if (m.Msg == WM_HOTKEY)
            {
                return; // Block registered hotkeys
            }

            if (m.Msg == WM_WINDOWPOSCHANGING)
            {
                return; // Block window position changes (minimize attempts)
            }

            base.WndProc(ref m);
        }

        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            _keepRunning = false;

            // Show taskbar again
            IntPtr taskbarHwnd = FindWindow("Shell_TrayWnd", null);
            if (taskbarHwnd != IntPtr.Zero)
                ShowWindow(taskbarHwnd, SW_HIDE + 5); // SW_SHOW

            _timer?.Stop();

            base.OnFormClosed(e);
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            // Prevent user from closing the form
            // Only the service can close us
            if (_keepRunning)
            {
                e.Cancel = true;
            }

            base.OnFormClosing(e);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _keepRunning = false;
                _timer?.Dispose();
                _logoBox?.Dispose();
            }
            base.Dispose(disposing);
        }

        // ── Identify which desktop we're running on ────────────────────
        private void IdentifyDesktop()
        {
            string desktopName = "Unknown";
            try
            {
                IntPtr hDesk = GetThreadDesktop(GetCurrentThreadId());
                // We can't easily get the name, but we can check if we're on the lock desktop
                Debug.WriteLine($"[LockScreen] Running on desktop handle: {hDesk}");
            }
            catch { }

            Debug.WriteLine("[LockScreen] Lock screen initialized.");
        }

        [DllImport("kernel32.dll")]
        static extern uint GetCurrentThreadId();

        [DllImport("user32.dll")]
        static extern IntPtr GetThreadDesktop(uint dwThreadId);

        // ── Draw a lock icon ───────────────────────────────────────────
        private Bitmap DrawLockIcon(int width, int height)
        {
            var bmp = new Bitmap(width, height);
            using (var g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                g.TextRenderingHint = TextRenderingHint.AntiAlias;

                // Simple lock icon using text
                using (var font = new Font("Segoe UI", 48, FontStyle.Bold))
                using (var brush = new SolidBrush(Color.FromArgb(124, 77, 255)))
                {
                    g.DrawString("🔒", font, brush, width / 2 - 30, height / 2 - 30);
                }
            }
            return bmp;
        }
    }
}
