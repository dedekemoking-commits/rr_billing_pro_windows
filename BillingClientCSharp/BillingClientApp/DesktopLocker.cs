using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
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

        [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
        public static extern IntPtr OpenDesktop(
            string lpszDesktop,
            uint dwFlags,
            bool fInherit,
            uint dwDesiredAccess);

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
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool GetUserObjectInformation(
            IntPtr hObj,
            int nIndex,
            StringBuilder pvInfo,
            uint nLength,
            out uint lpnLengthNeeded);

        [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool CreateProcess(
            string lpApplicationName,
            string lpCommandLine,
            IntPtr lpProcessAttributes,
            IntPtr lpThreadAttributes,
            [MarshalAs(UnmanagedType.Bool)] bool bInheritHandles,
            uint dwCreationFlags,
            IntPtr lpEnvironment,
            string lpCurrentDirectory,
            ref STARTUPINFO lpStartupInfo,
            out PROCESS_INFORMATION lpProcessInformation);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool CloseHandle(IntPtr hObject);

        public const uint DESKAP_CREATEMENU = 0x0004;
        public const uint DESKAP_CREATEWINDOW = 0x0002;
        public const uint DESKAP_ENUMERATE = 0x0040;
        public const uint DESKAP_SWITCHDESKTOP = 0x0100;
        public const uint DESKAP_WRITEOBJECTS = 0x0080;
        public const uint DESKAP_READOBJECTS = 0x0001;

        public const uint DESKTOP_ALL_ACCESS = DESKAP_CREATEMENU | DESKAP_CREATEWINDOW |
                                                DESKAP_ENUMERATE | DESKAP_SWITCHDESKTOP |
                                                DESKAP_WRITEOBJECTS | DESKAP_READOBJECTS;

        private const uint WINSTA_ALL_ACCESS = 0x0437;

        private const int CREATE_DESKTOP_FLAGS = 0;
        private const int UOI_NAME = 2;
        private const uint MAXIMUM_ALLOWED = 0x02000000;

        public const string LOCK_DESKTOP_NAME = "BillingLockDesktop_v1";

        private const string LOG_FILE = "rr_billing_client_app.log";

        private static IntPtr _originalDesktop = IntPtr.Zero;
        private static IntPtr _lockDesktop = IntPtr.Zero;
        private static IntPtr _originalWinSta = IntPtr.Zero;
        private static Process _lockProcess;
        private static readonly object _lock = new object();

        public static bool IsLocked
        {
            get { lock (_lock) return _lockDesktop != IntPtr.Zero; }
        }

        // TRUE hanya jika desktop input saat ini BENAR-BENAR masih lock desktop
        // kita. Setelah sleep/resume (atau logoff-lock Windows), desktop input
        // bisa balik ke "Default"/"Winlogon" walau handle _lockDesktop masih
        // tersisa — di situ IsLocked=true tapi layar tidak terkunci.
        public static bool IsActuallyActive()
        {
            lock (_lock)
            {
                if (_lockDesktop == IntPtr.Zero) return false;
                try
                {
                    IntPtr hInput = OpenInputDesktop(0, false, DESKTOP_ALL_ACCESS);
                    if (hInput == IntPtr.Zero) return false;
                    try
                    {
                        return string.Equals(GetDesktopName(hInput),
                            LOCK_DESKTOP_NAME, StringComparison.OrdinalIgnoreCase);
                    }
                    finally { CloseDesktopHandle(hInput); }
                }
                catch { return false; }
            }
        }

        // Pastikan lock benar-benar aktif. Jika handle ada tapi desktop input
        // sudah lepas (wake/logon Windows), bubarkan status lama lalu bangun
        // lock baru dari nol (kill UI lama + cleanup + Lock()).
        public static bool EnsureLockActive(string lockAppPath = null, string args = null)
        {
            lock (_lock)
            {
                if (_lockDesktop != IntPtr.Zero)
                {
                    bool active = false;
                    try
                    {
                        IntPtr hInput = OpenInputDesktop(0, false, DESKTOP_ALL_ACCESS);
                        if (hInput != IntPtr.Zero)
                        {
                            try
                            {
                                active = string.Equals(GetDesktopName(hInput),
                                    LOCK_DESKTOP_NAME, StringComparison.OrdinalIgnoreCase);
                            }
                            finally { CloseDesktopHandle(hInput); }
                        }
                    }
                    catch { }

                    if (active) return true; // sudah benar-benar terkunci

                    Log("[DesktopLocker] Lock state stale (desktop input lepas) — membangun ulang...");
                    KillLockProcess();
                    Cleanup();
                }
                return Lock(lockAppPath, args);
            }
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
                    {
                        int err = Marshal.GetLastWin32Error();
                        if (err == 183) // ERROR_ALREADY_EXISTS — sisa desktop lock lama
                        {
                            _lockDesktop = OpenDesktop(
                                LOCK_DESKTOP_NAME, 0, false, DESKTOP_ALL_ACCESS);
                            if (_lockDesktop == IntPtr.Zero)
                                throw new Win32Exception(Marshal.GetLastWin32Error(),
                                    $"OpenDesktop('{LOCK_DESKTOP_NAME}') failed.");
                            Log("[DesktopLocker] Desktop lock lama dibuka kembali (OpenDesktop).");
                        }
                        else
                        {
                            throw new Win32Exception(err,
                                $"CreateDesktop('{LOCK_DESKTOP_NAME}') failed.");
                        }
                    }

                    // NOTE: SetThreadDesktop deliberately NOT used here.
                    //  - It is redundant: CreateProcess + lpDesktop (below) already
                    //    launches the lock UI on the lock desktop.
                    //  - Calling it from the WinForms UI thread (which owns the tray
                    //    window) can fail or destabilize the message loop, aborting
                    //    the lock before SwitchDesktop.

                    // Launch lock screen UI EXPLICITLY on the lock desktop.
                    // (Process.Start/ShellExecute ignores SetThreadDesktop and
                    //  launches on the parent process desktop — that would make
                    //  the UI invisible. CreateProcess + lpDesktop is required.)
                    if (!string.IsNullOrWhiteSpace(lockAppPath))
                    {
                        string winsta = GetWindowStationName();
                        if (string.IsNullOrEmpty(winsta)) winsta = "WinSta0";
                        string cmdLine = "\"" + lockAppPath + "\"";
                        if (!string.IsNullOrWhiteSpace(args))
                            cmdLine += " " + args;

                        var si = new STARTUPINFO();
                        si.cb = (uint)Marshal.SizeOf(typeof(STARTUPINFO));
                        si.lpDesktop = winsta + "\\" + LOCK_DESKTOP_NAME;
                        si.dwFlags = STARTF_USESHOWWINDOW;
                        si.wShowWindow = SW_SHOWNORMAL;

                        PROCESS_INFORMATION pi;
                        if (!CreateProcess(null, cmdLine, IntPtr.Zero, IntPtr.Zero,
                                           false, 0, IntPtr.Zero, null, ref si, out pi))
                        {
                            int err = Marshal.GetLastWin32Error();
                            throw new Win32Exception(err,
                                $"CreateProcess('{lockAppPath}') failed (desktop: {winsta}\\{LOCK_DESKTOP_NAME}).");
                        }

                        CloseHandle(pi.hThread);
                        _lockProcess = Process.GetProcessById((int)pi.dwProcessId);
                        CloseHandle(pi.hProcess);
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

                    Log("[DesktopLocker] Lock successful.");
                    return true;
                }
                catch (Exception ex)
                {
                    Debug.WriteLine($"[DesktopLocker] Lock error: {ex.Message}");
                    Log($"[DesktopLocker] Lock error: {ex.Message}");
                    Cleanup();
                    return false;
                }
            }
        }

        public static void EnsureLockUIAlive(string lockAppPath = null, string args = null)
        {
            lock (_lock)
            {
                if (_lockDesktop == IntPtr.Zero) return; // PC tidak terkunci
                if (string.IsNullOrWhiteSpace(lockAppPath)) return;

                // UI lock screen masih hidup?
                try
                {
                    Process[] procs = Process.GetProcessesByName("BillingLockScreenUI");
                    if (procs != null && procs.Length > 0) return;
                }
                catch { }

                // UI mati (di-kill/crash) — relaunch di lock desktop tanpa SwitchDesktop.
                try
                {
                    string winsta = GetWindowStationName();
                    if (string.IsNullOrEmpty(winsta)) winsta = "WinSta0";

                    string cmdLine = "\"" + lockAppPath + "\"";
                    if (!string.IsNullOrWhiteSpace(args))
                        cmdLine += " " + args;

                    var si = new STARTUPINFO();
                    si.cb = (uint)Marshal.SizeOf(typeof(STARTUPINFO));
                    si.lpDesktop = winsta + "\\" + LOCK_DESKTOP_NAME;
                    si.dwFlags = STARTF_USESHOWWINDOW;
                    si.wShowWindow = SW_SHOWNORMAL;

                    PROCESS_INFORMATION pi;
                    if (CreateProcess(null, cmdLine, IntPtr.Zero, IntPtr.Zero,
                                       false, 0, IntPtr.Zero, null, ref si, out pi))
                    {
                        CloseHandle(pi.hThread);
                        _lockProcess = Process.GetProcessById((int)pi.dwProcessId);
                        CloseHandle(pi.hProcess);
                        Log("[DesktopLocker] Lock UI relaunched (BillingLockScreenUI mati).");
                    }
                    else
                    {
                        Log($"[DesktopLocker] Relaunch lock UI gagal (err {Marshal.GetLastWin32Error()}).");
                    }
                }
                catch (Exception ex)
                {
                    Log($"[DesktopLocker] Relaunch lock UI error: {ex.Message}");
                }
            }
        }

        // Adopsi "orphan lock": PC sedang berada di lock desktop buatan proses
        // lama yang sudah mati (handle hilang). Deteksi nama desktop input aktif;
        // jika bernama BillingLockDesktop_v1, kita ambil alih handle-nya sehingga
        // Unlock() bisa kembali memindahkan user ke desktop default.
        public static bool AdoptOrphanDesktop()
        {
            lock (_lock)
            {
                if (_lockDesktop != IntPtr.Zero) return true; // sudah menguasai lock

                try
                {
                    IntPtr hInput = OpenInputDesktop(0, false, DESKTOP_ALL_ACCESS);
                    if (hInput == IntPtr.Zero) return false;

                    string name = GetDesktopName(hInput);
                    CloseDesktopHandle(hInput);

                    if (!string.Equals(name, LOCK_DESKTOP_NAME, StringComparison.OrdinalIgnoreCase))
                        return false; // desktop aktif normal, bukan orphan

                    // Kita berada di atas lock desktop orphan. Ambil alih handle-nya.
                    IntPtr desk = OpenDesktop(
                        LOCK_DESKTOP_NAME, 0, false, DESKTOP_ALL_ACCESS);
                    if (desk == IntPtr.Zero)
                        return false;

                    _lockDesktop = desk;
                    _originalDesktop = IntPtr.Zero; // tidak tahu desktop asli; Unlock akan cari "default"

                    // UI lock screen mati (proses lama sudah di-kill saat update) —
                    // relaunch kembali di lock desktop ini.
                    EnsureLockUIAliveUnlocked();

                    Debug.WriteLine("[DesktopLocker] Orphan lock desktop adopted.");
                    Log("[DesktopLocker] Orphan lock desktop adopted (masih terkunci).");
                    return true;
                }
                catch (Exception ex)
                {
                    Debug.WriteLine($"[DesktopLocker] Adopt orphan error: {ex.Message}");
                    Log($"[DesktopLocker] Adopt orphan error: {ex.Message}");
                    return false;
                }
            }
        }

        // Relaunch lock UI di desktop yang sudah diadopsi (tanpa SwitchDesktop).
        private static void EnsureLockUIAliveUnlocked()
        {
            try
            {
                string app = AppDomain.CurrentDomain.BaseDirectory;
                string exe = Path.Combine(app, "BillingLockScreenUI.exe");
                if (!File.Exists(exe)) return;

                Process[] procs;
                try
                {
                    procs = Process.GetProcessesByName("BillingLockScreenUI");
                    if (procs != null && procs.Length > 0) return;
                }
                catch { procs = null; }

                string winsta = GetWindowStationName();
                if (string.IsNullOrEmpty(winsta)) winsta = "WinSta0";

                var si = new STARTUPINFO();
                si.cb = (uint)Marshal.SizeOf(typeof(STARTUPINFO));
                si.lpDesktop = winsta + "\\" + LOCK_DESKTOP_NAME;
                si.dwFlags = STARTF_USESHOWWINDOW;
                si.wShowWindow = SW_SHOWNORMAL;

                PROCESS_INFORMATION pi;
                if (CreateProcess(null, "\"" + exe + "\"", IntPtr.Zero, IntPtr.Zero,
                                   false, 0, IntPtr.Zero, null, ref si, out pi))
                {
                    CloseHandle(pi.hThread);
                    _lockProcess = Process.GetProcessById((int)pi.dwProcessId);
                    CloseHandle(pi.hProcess);
                    Log("[DesktopLocker] Lock UI relaunched on adopted desktop.");
                }
            }
            catch (Exception ex)
            {
                Log($"[DesktopLocker] EnsureLockUIAliveUnlocked error: {ex.Message}");
            }
        }

        public static bool Unlock()
        {
            lock (_lock)
            {
                // Jika tray baru tidak memegang handle, tetapi user sedang di
                // lock desktop orphan, adopsi dulu supaya bisa dipindahkan kembali.
                if (_lockDesktop == IntPtr.Zero)
                    AdoptOrphanDesktop();

                if (_lockDesktop == IntPtr.Zero)
                {
                    Debug.WriteLine("[DesktopLocker] Not locked, skipping.");
                    return false;
                }

                try
                {
                    IntPtr target = _originalDesktop;
                    bool openedTarget = false;

                    if (target == IntPtr.Zero)
                    {
                        // Orphan: buka desktop "default" sebagai tujuan.
                        IntPtr def = OpenDesktop("default", 0, false, DESKTOP_ALL_ACCESS);
                        if (def == IntPtr.Zero)
                            def = OpenDesktop("Default", 0, false, DESKTOP_ALL_ACCESS);
                        if (def != IntPtr.Zero)
                        {
                            target = def;
                            openedTarget = true;
                        }
                    }

                    bool switched = false;
                    if (target != IntPtr.Zero)
                        switched = SwitchDesktop(target);

                    if (openedTarget)
                        CloseDesktopHandle(target);

                    if (!switched)
                    {
                        // Fallback: canvas desktop input aktif saat ini.
                        IntPtr currentInput = OpenInputDesktop(0, false, DESKTOP_ALL_ACCESS);
                        if (currentInput != IntPtr.Zero)
                        {
                            SwitchDesktop(currentInput);
                            CloseDesktopHandle(currentInput);
                        }
                    }

                    System.Threading.Thread.Sleep(500);
                    KillLockProcess();
                    Cleanup();

                    Debug.WriteLine("[DesktopLocker] Unlock successful.");
                    Log("[DesktopLocker] Unlock successful.");
                    return true;
                }
                catch (Exception ex)
                {
                    Debug.WriteLine($"[DesktopLocker] Unlock error: {ex.Message}");
                    Log($"[DesktopLocker] Unlock error: {ex.Message}");
                    return false;
                }
            }
        }

        private static string GetDesktopName(IntPtr hDesktop)
        {
            try
            {
                uint len = 0;
                GetUserObjectInformation(hDesktop, UOI_NAME, null, 0, out len);
                if (len <= 1) return null;
                var sb = new StringBuilder((int)len);
                if (!GetUserObjectInformation(hDesktop, UOI_NAME, sb, len, out len))
                    return null;
                return sb.ToString();
            }
            catch { return null; }
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

        private static string GetWindowStationName()
        {
            try
            {
                IntPtr hSta = GetProcessWindowStation();
                if (hSta == IntPtr.Zero) return null;
                uint len = 0;
                GetUserObjectInformation(hSta, UOI_NAME, null, 0, out len);
                if (len <= 1) return null;
                var sb = new StringBuilder((int)len);
                if (!GetUserObjectInformation(hSta, UOI_NAME, sb, len, out len))
                    return null;
                return sb.ToString();
            }
            catch { return null; }
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

        private static void Log(string message)
        {
            string line = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {message}";
            Debug.WriteLine(line);
            try
            {
                string logPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, LOG_FILE);
                lock (typeof(DesktopLocker))
                {
                    File.AppendAllText(logPath, line + Environment.NewLine);
                }
            }
            catch { }
        }

        // ── Structs ────────────────────────────────────────────────────
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        public struct STARTUPINFO
        {
            public uint cb;
            public string lpReserved;
            public string lpDesktop;
            public string lpTitle;
            public uint dwX;
            public uint dwY;
            public uint dwXSize;
            public uint dwYSize;
            public uint dwXCountChars;
            public uint dwYCountChars;
            public uint dwFillAttribute;
            public uint dwFlags;
            public ushort wShowWindow;
            public ushort cbReserved2;
            public IntPtr lpReserved2;
            public IntPtr hStdInput;
            public IntPtr hStdOutput;
            public IntPtr hStdError;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct PROCESS_INFORMATION
        {
            public IntPtr hProcess;
            public IntPtr hThread;
            public uint dwProcessId;
            public uint dwThreadId;
        }

        public const uint STARTF_USESHOWWINDOW = 0x00000001;
        public const ushort SW_SHOWNORMAL = 1;
    }
}
