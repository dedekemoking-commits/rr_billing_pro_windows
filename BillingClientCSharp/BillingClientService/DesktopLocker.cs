using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace BillingClientService
{
    public static class DesktopLocker
    {
        // ── P/Invoke Signatures ──────────────────────────────────────────────

        [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
        public static extern IntPtr CreateDesktop(
            string lpszDesktop,
            IntPtr lpszDevice,
            IntPtr pDevmode,
            int dwFlags,
            uint dwDesiredAccess,
            IntPtr lpsa);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern IntPtr OpenInputDesktop(
            uint dwFlags,
            bool fInherit,
            uint dwDesiredAccess);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool SwitchDesktop(IntPtr hDesktop);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool CloseDesktop(IntPtr hDesktop);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool SetThreadDesktop(IntPtr hDesktop);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern IntPtr GetProcessWindowStation();

        [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
        public static extern IntPtr OpenWindowStation(
            string lpszWinSta,
            [MarshalAs(UnmanagedType.Bool)] bool fInherit,
            uint dwDesiredAccess);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool CloseWindowStation(IntPtr hWinSta);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Auto)]
        public static extern IntPtr GetCurrentProcess();

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool TerminateProcess(IntPtr hProcess, uint uExitCode);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern IntPtr GetShellWindow();

        [DllImport("user32.dll", SetLastError = true)]
        public static extern IntPtr GetDesktopWindow();

        public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        // ── Access Rights ────────────────────────────────────────────────────

        private const uint DESKAP_CREATEMENU = 0x0004;
        private const uint DESKAP_CREATEWINDOW = 0x0002;
        private const uint DESKAP_ENUMERATE = 0x0040;
        private const uint DESKAP_SWITCHDESKTOP = 0x0100;
        private const uint DESKAP_WRITEOBJECTS = 0x0080;
        private const uint DESKAP_READOBJECTS = 0x0001;

        private const uint DESKTOP_ALL_ACCESS = DESKAP_CREATEMENU | DESKAP_CREATEWINDOW |
                                                DESKAP_ENUMERATE | DESKAP_SWITCHDESKTOP |
                                                DESKAP_WRITEOBJECTS | DESKAP_READOBJECTS;

        private const uint WINSTA_ALL_ACCESS = 0x0437;

        private const int CREATE_DESKTOP_FLAGS = 0;

        // ── State ────────────────────────────────────────────────────────────

        public const string LOCK_DESKTOP_NAME = "BillingLockDesktop_v1";

        private static IntPtr _originalDesktop = IntPtr.Zero;
        private static IntPtr _lockDesktop = IntPtr.Zero;
        private static IntPtr _originalWinSta = IntPtr.Zero;
        private static Process _lockProcess;
        private static readonly object _lock = new object();

        // ── Public API ───────────────────────────────────────────────────────

        public static bool IsLocked
        {
            get { lock (_lock) return _lockDesktop != IntPtr.Zero; }
        }

        public static bool Lock(string lockAppPath = null, string args = null)
        {
            lock (_lock)
            {
                if (_lockDesktop != IntPtr.Zero)
                {
                    Debug.WriteLine("[DesktopLocker] Already locked, skipping.");
                    return true;
                }

                try
                {
                    // 1. Save reference to the original input desktop
                    _originalDesktop = OpenInputDesktop(0, false, DESKTOP_ALL_ACCESS);
                    if (_originalDesktop == IntPtr.Zero)
                        throw new Win32Exception(Marshal.GetLastWin32Error(),
                            "OpenInputDesktop failed.");

                    // 2. Save original window station
                    _originalWinSta = GetProcessWindowStation();
                    if (_originalWinSta == IntPtr.Zero)
                        throw new Win32Exception(Marshal.GetLastWin32Error(),
                            "GetProcessWindowStation failed.");

                    // 3. Create the new lock desktop
                    _lockDesktop = CreateDesktop(
                        LOCK_DESKTOP_NAME,
                        IntPtr.Zero,
                        IntPtr.Zero,
                        CREATE_DESKTOP_FLAGS,
                        DESKTOP_ALL_ACCESS,
                        IntPtr.Zero);

                    if (_lockDesktop == IntPtr.Zero)
                        throw new Win32Exception(Marshal.GetLastWin32Error(),
                            $"CreateDesktop('{LOCK_DESKTOP_NAME}') failed.");

                    // 4. Set our thread to the new desktop so CreateProcess
                    //    will launch the lock app there
                    if (!SetThreadDesktop(_lockDesktop))
                        throw new Win32Exception(Marshal.GetLastWin32Error(),
                            "SetThreadDesktop failed.");

                    // 5. Launch lock screen UI on the new desktop
                    //    CreateProcess (UseShellExecute=false): menghindari
                    //    dialog "Open File - Security Warning" (Mark-of-the-Web)
                    //    yang dipicu ShellExecute untuk exe bermotW.
                    if (!string.IsNullOrWhiteSpace(lockAppPath))
                    {
                        var psi = new ProcessStartInfo(lockAppPath, args ?? "")
                        {
                            UseShellExecute = false,
                            WindowStyle = ProcessWindowStyle.Normal,
                            CreateNoWindow = false,
                            ErrorDialog = false,
                        };
                        _lockProcess = Process.Start(psi);
                    }

                    // 6. Switch the entire input to the new desktop
                    if (!SwitchDesktop(_lockDesktop))
                    {
                        // Rollback: kill process, close handles
                        KillLockProcess();
                        CloseDesktopHandle(_lockDesktop);
                        _lockDesktop = IntPtr.Zero;
                        SetThreadDesktop(_originalDesktop);
                        throw new Win32Exception(Marshal.GetLastWin32Error(),
                            "SwitchDesktop failed.");
                    }

                    Debug.WriteLine("[DesktopLocker] Lock successful.");
                    return true;
                }
                catch (Exception ex)
                {
                    Debug.WriteLine($"[DesktopLocker] Lock error: {ex.Message}");
                    Cleanup();
                    return false;
                }
            }
        }

        public static bool Unlock()
        {
            lock (_lock)
            {
                if (_lockDesktop == IntPtr.Zero)
                {
                    Debug.WriteLine("[DesktopLocker] Not locked, skipping.");
                    return false;
                }

                try
                {
                    // 1. Switch back to original desktop
                    if (_originalDesktop != IntPtr.Zero)
                    {
                        if (!SwitchDesktop(_originalDesktop))
                        {
                            // Try via OpenInputDesktop
                            IntPtr currentInput = OpenInputDesktop(0, false, DESKTOP_ALL_ACCESS);
                            if (currentInput != IntPtr.Zero)
                            {
                                SwitchDesktop(currentInput);
                                CloseDesktopHandle(currentInput);
                            }
                        }
                    }

                    // 2. Wait a moment for the desktop switch to take effect
                    System.Threading.Thread.Sleep(500);

                    // 3. Kill the lock screen process
                    KillLockProcess();

                    // 4. Clean up handles
                    Cleanup();

                    Debug.WriteLine("[DesktopLocker] Unlock successful.");
                    return true;
                }
                catch (Exception ex)
                {
                    Debug.WriteLine($"[DesktopLocker] Unlock error: {ex.Message}");
                    return false;
                }
            }
        }

        // ── Internal Helpers ─────────────────────────────────────────────────

        private static void KillLockProcess()
        {
            if (_lockProcess != null && !_lockProcess.HasExited)
            {
                try
                {
                    _lockProcess.Kill();
                    _lockProcess.WaitForExit(3000);
                }
                catch (Exception ex)
                {
                    Debug.WriteLine($"[DesktopLocker] Kill process error: {ex.Message}");
                }
                _lockProcess = null;
            }
        }

        private static void CloseDesktopHandle(IntPtr desktop)
        {
            if (desktop != IntPtr.Zero && desktop != _originalDesktop)
            {
                CloseDesktop(desktop);
            }
        }

        private static void Cleanup()
        {
            if (_lockDesktop != IntPtr.Zero)
            {
                CloseDesktop(_lockDesktop);
                _lockDesktop = IntPtr.Zero;
            }

            if (_originalDesktop != IntPtr.Zero)
            {
                // Don't close the original — we might need to switch back to it
                _originalDesktop = IntPtr.Zero;
            }

            if (_originalWinSta != IntPtr.Zero)
            {
                _originalWinSta = IntPtr.Zero;
            }
        }

        public static void ForceUnlock()
        {
            lock (_lock)
            {
                KillLockProcess();
                Cleanup();

                // Try to switch back to the default desktop
                IntPtr defaultDesktop = OpenInputDesktop(0, false, DESKTOP_ALL_ACCESS);
                if (defaultDesktop != IntPtr.Zero)
                {
                    SwitchDesktop(defaultDesktop);
                    SetThreadDesktop(defaultDesktop);
                    CloseDesktop(defaultDesktop);
                }
            }
        }
    }
}
