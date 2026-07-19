using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace BillingLockScreenUI
{
    static class Program
    {
        [DllImport("user32.dll")]
        static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

        [DllImport("user32.dll")]
        static extern IntPtr GetForegroundWindow();

        [DllImport("user32.dll")]
        static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int count);

        const int SW_HIDE = 0;
        const int SW_SHOW = 5;

        /// <summary>
        /// The main entry point for the application.
        /// Launches the lock screen on the current desktop.
        /// </summary>
        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            // Parse command-line arguments for optional server info
            string serverHost = "127.0.0.1";
            int serverPort = 5000;
            string message = "PC TERKUNCI\nSilahkan hubungi admin billing.";

            string[] args = Environment.GetCommandLineArgs();
            for (int i = 1; i < args.Length; i++)
            {
                switch (args[i].ToLowerInvariant())
                {
                    case "--host":
                        if (++i < args.Length) serverHost = args[i];
                        break;
                    case "--port":
                        if (++i < args.Length) int.TryParse(args[i], out serverPort);
                        break;
                    case "--message":
                        if (++i < args.Length) message = args[i];
                        break;
                }
            }

            // Hide the console window if running in console mode
            try
            {
                IntPtr hWnd = GetForegroundWindow();
                if (hWnd != IntPtr.Zero)
                {
                    var sb = new System.Text.StringBuilder(256);
                    GetWindowText(hWnd, sb, 256);
                    if (sb.ToString().Contains("BillingLockScreenUI"))
                        ShowWindow(hWnd, SW_HIDE);
                }
            }
            catch { }

            // Keep the process alive in background for monitoring
            Application.Run(new LockScreenForm(message));
        }

        /// <summary>
        /// Parse command line for simple key=value pairs (legacy support)
        /// </summary>
        private static string GetArgValue(string[] args, string key, string defaultValue)
        {
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i].Equals(key, StringComparison.OrdinalIgnoreCase))
                    return args[i + 1];
            }
            return defaultValue;
        }
    }
}
