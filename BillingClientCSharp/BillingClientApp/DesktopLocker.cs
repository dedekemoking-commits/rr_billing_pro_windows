using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace BillingClientApp
{
    public static class DesktopLocker
    {
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

        public const string LOCK_DESKTOP_NAME = "BillingLockDesktop_v1";

        private static IntPtr _originalDesktop = IntPtr.Zero;
        private static IntPtr _lockDesktop = IntPtr.Zero;
        private static IntPtr _originalWinSta = IntPtr.Zero;
        private static Process _lockProcess;
        private static readonly object _lock = new object();

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
                    _originalDesktop = OpenInputDesktop(0, false, DESKTOP_ALL_ACCESS);
                    if (_originalDesktop == IntPtr.Zero)
                        throw new Win32Exception(Marshal.GetLastWin32Error(),
                            "OpenInputDesktop failed.");

                    _originalWinSta = GetProcessWindowStation();
                    if (_originalWinSta == IntPtr.Zero)
                        throw new Win32Exception(Marshal.GetLastWin32Error(),
                            "GetProcessWindowStation failed.");

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

                    if (!SetThreadDesktop(_lockDesktop))
                        throw new Win32Exception(Marshal.GetLastWin32Error(),
                            "SetThreadDesktop failed.");

                    if (!string.IsNullOrWhiteSpace(lockAppPath))
                    {
                        var psi = new ProcessStartInfo(lockAppPath, args ?? "")
                        {
                            UseShellExecute = true,
                            WindowStyle = ProcessWindowStyle.Normal,
                            CreateNoWindow = false,
                            ErrorDialog = false,
                        };
                        _lockProcess = Process.Start(psi);
                    }

                    if (!SwitchDesktop(_lockDesktop))
                    {
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
                    if (_originalDesktop != IntPtr.Zero)
                    {
                        if (!SwitchDesktop(_originalDesktop))
                        {
                            IntPtr currentInput = OpenInputDesktop(0, false, DESKTOP_ALL_ACCESS);
                            if (currentInput != IntPtr.Zero)
                            {
                                SwitchDesktop(currentInput);
                                CloseDesktopHandle(currentInput);
                            }
                        }
                    }

                    System.Threading.Thread.Sleep(500);
                    KillLockProcess();
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
