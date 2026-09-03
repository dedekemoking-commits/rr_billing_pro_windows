using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Configuration;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.ServiceProcess;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace BillingClientService
{
    public class ServiceCore : ServiceBase
    {
        // ── Configuration ──────────────────────────────────────────────
        private string _serverHost = "127.0.0.1";
        private int _serverPort = 5000;
        private string _clientId = "WARNET_01";
        private string _password = "admin123";
        private int _heartbeatIntervalMs = 1000;
        private int _heartbeatTimeoutMs = 15000;
        private int _watchdogIntervalMs = 10000;
        private int _trayHangTimeoutMs = 30000;
        private string _lockAppPath = "";

        // ── State ──────────────────────────────────────────────────────
        private TcpClient _tcpClient;
        private NetworkStream _stream;
        private readonly object _tcpLock = new object();
        private CancellationTokenSource _cts;
        private Thread _mainThread;
        private Thread _watchdogThread;
        private DateTime _lastHeartbeatResponse = DateTime.MinValue;
        private DateTime _lastTrayPing = DateTime.MinValue;
        private bool _isLocked = false;
        private string _pcId = null;
        private string _sessionToken = null;
        private string _kursiName = null;  // Nama kursi dari server
        private string _lockMessage = "";
        private int _getStatusFailCount = 0;
        private readonly TimeSpan _logoDownloadTimeout = TimeSpan.FromSeconds(8);
        private string _macOverride = "";

        // ── Billing status cache (for IPC) ─────────────────────────────
        private string _billingPaket = "-";
        private int _billingTimeLeft = 0;
        private int _billingTotalBiaya = 0;
        private bool _billingIsPlaying = false;
        private readonly object _billingLock = new object();

        // ── Named Pipe IPC ─────────────────────────────────────────────
        private const string PIPE_NAME = "RRBillingClientService_Pipe";
        private const string EVENT_PIPE_NAME = "RRBillingClientService_Pipe_Events";
        private Thread _pipeThread;
        private Thread _eventThread;
        private readonly object _eventPipeLock = new object();
        private PipeStream _eventPipe;

        // ── Log file ───────────────────────────────────────────────────
        private const string LOG_FILE = "rr_billing_client_service.log";

        public ServiceCore()
        {
            ServiceName = "RRBillingClientService";
            CanStop = true;
            CanPauseAndContinue = false;
            AutoLog = true;
        }

        // Hapus tanda "dari internet" (Mark-of-the-Web / Zone.Identifier ADS)
        // dari semua executable di folder instalasi. Jalan saat service start
        // (= sebelum user login), sehingga Run key / ShellExecute tidak pernah
        // lagi memunculkan dialog "Open File - Security Warning".
        private void StripMarkOfTheWeb()
        {
            int cleaned = 0;
            try
            {
                string dir = AppDomain.CurrentDomain.BaseDirectory;
                string self = Process.GetCurrentProcess().MainModule?.FileName ?? "";
                foreach (string pattern in new[] { "*.exe", "*.dll", "*.bat", "*.cmd", "*.vbs", "*.ps1" })
                {
                    foreach (string file in Directory.GetFiles(dir, pattern, SearchOption.TopDirectoryOnly))
                    {
                        try
                        {
                            if (!string.IsNullOrEmpty(self) &&
                                string.Equals(file, self, StringComparison.OrdinalIgnoreCase))
                                continue; // jangan sentuh file yang sedang berjalan
                            File.Delete(file + ":Zone.Identifier");
                            cleaned++;
                        }
                        catch (FileNotFoundException) { }
                        catch (DirectoryNotFoundException) { }
                        catch { }
                    }
                }
                Log($"MotW cleanup: {cleaned} file(s) dibersihkan dari tanda internet.");
            }
            catch (Exception ex)
            {
                Log($"MotW cleanup error: {ex.Message} (dibersihkan {cleaned}).");
            }
        }

        protected override void OnStart(string[] args)
        {
            try
            {
                LoadConfig();
                LoadLockState();
                StripMarkOfTheWeb();
                _cts = new CancellationTokenSource();

                // Start named pipe server for IPC with tray app
                _pipeThread = new Thread(PipeServerLoop)
                {
                    IsBackground = true,
                    Name = "BillingPipeServer",
                };
                _pipeThread.Start();

                // Event pipe: push LOCK/UNLOCK instan ke tray app (tanpa
                // menunggu poll tray berikutnya) — lockscreen tampil cepat.
                _eventThread = new Thread(EventPushLoop)
                {
                    IsBackground = true,
                    Name = "BillingEventPush",
                };
                _eventThread.Start();

                _mainThread = new Thread(ServiceLoop)
                {
                    IsBackground = false,
                    Name = "BillingServiceMain",
                };
                _mainThread.Start();

                // Watchdog: pastikan tray app (pengeksekusi lock) selalu hidup
                // di user session, termasuk setelah PC reboot.
                _watchdogThread = new Thread(WatchdogLoop)
                {
                    IsBackground = true,
                    Name = "BillingWatchdog",
                };
                _watchdogThread.Start();

                Log("Service started.");
            }
            catch (Exception ex)
            {
                Log($"OnStart error: {ex.Message}");
                throw;
            }
        }

        protected override void OnStop()
        {
            Log("Service stopping...");
            _cts?.Cancel();

            if (_isLocked)
            {
                DesktopLocker.Unlock();
                _isLocked = false;
            }

            Disconnect();

            _mainThread?.Join(TimeSpan.FromSeconds(5));
            _pipeThread?.Join(TimeSpan.FromSeconds(2));

            Log("Service stopped.");
        }

        // ── Console mode support ───────────────────────────────────────
        public void StartForConsole()
        {
            LoadConfig();
            LoadLockState();
            StripMarkOfTheWeb();
            _cts = new CancellationTokenSource();

            _pipeThread = new Thread(PipeServerLoop)
            {
                IsBackground = true,
                Name = "BillingPipeServer",
            };
            _pipeThread.Start();

            _eventThread = new Thread(EventPushLoop)
            {
                IsBackground = true,
                Name = "BillingEventPush",
            };
            _eventThread.Start();

            _mainThread = new Thread(ServiceLoop)
            {
                IsBackground = true,
                Name = "BillingServiceMain",
            };
            _mainThread.Start();

            _watchdogThread = new Thread(WatchdogLoop)
            {
                IsBackground = true,
                Name = "BillingWatchdog",
            };
            _watchdogThread.Start();

            Log("Service started (console mode).");
        }

        public void StopForConsole()
        {
            Log("Service stopping (console mode)...");
            _cts?.Cancel();

            if (_isLocked)
            {
                DesktopLocker.Unlock();
                _isLocked = false;
            }

            Disconnect();

            Log("Service stopped (console mode).");
        }

        // ════════════════════════════════════════════════════════════════
        //  NAMED PIPE IPC (for BillingClientTray.exe)
        // ════════════════════════════════════════════════════════════════
        private void PipeServerLoop(object obj)
        {
            var token = _cts.Token;
            while (!token.IsCancellationRequested)
            {
                try
                {
                    // Allow all users to connect to the pipe
                    var pipeSecurity = new PipeSecurity();
                    var everyone = new SecurityIdentifier(WellKnownSidType.WorldSid, null);
                    pipeSecurity.AddAccessRule(
                        new PipeAccessRule(everyone, PipeAccessRights.ReadWrite, AccessControlType.Allow));
                    var system = new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null);
                    pipeSecurity.AddAccessRule(
                        new PipeAccessRule(system, PipeAccessRights.FullControl, AccessControlType.Allow));

                    using (NamedPipeServerStream pipeServer = new NamedPipeServerStream(
                        PIPE_NAME, PipeDirection.InOut, 1,
                        PipeTransmissionMode.Message, PipeOptions.Asynchronous,
                        65536, 65536, pipeSecurity))
                    {
                        // Wait for client connection (async with cancellation)
                        var waitTask = Task.Run(() => pipeServer.WaitForConnection(), token);
                        waitTask.Wait(token);

                        if (!pipeServer.IsConnected) continue;

                        // Read request
                        var buffer = new byte[4096];
                        int bytesRead = pipeServer.Read(buffer, 0, buffer.Length);
                        if (bytesRead > 0)
                        {
                            string request = Encoding.UTF8.GetString(buffer, 0, bytesRead).Trim();
                            string response = HandlePipeRequest(request);
                            byte[] respBytes = Encoding.UTF8.GetBytes(response);
                            pipeServer.Write(respBytes, 0, respBytes.Length);
                            pipeServer.Flush();
                        }

                        pipeServer.WaitForPipeDrain();
                    }
                }
                catch (OperationCanceledException) { break; }
                catch (Exception ex)
                {
                    Debug.WriteLine($"[PipeServer] Error: {ex.Message}");
                    SleepWithCancellation(1000, _cts.Token);
                }
            }
        }

        // ════════════════════════════════════════════════════════════════
        //  EVENT PIPE — push LOCK/UNLOCK instan ke tray app
        // ════════════════════════════════════════════════════════════════
        private void EventPushLoop(object obj)
        {
            var token = _cts.Token;
            while (!token.IsCancellationRequested)
            {
                try
                {
                    var pipeSecurity = new PipeSecurity();
                    var everyone = new SecurityIdentifier(WellKnownSidType.WorldSid, null);
                    pipeSecurity.AddAccessRule(
                        new PipeAccessRule(everyone, PipeAccessRights.ReadWrite, AccessControlType.Allow));
                    var system = new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null);
                    pipeSecurity.AddAccessRule(
                        new PipeAccessRule(system, PipeAccessRights.FullControl, AccessControlType.Allow));

                    using (NamedPipeServerStream pipeServer = new NamedPipeServerStream(
                        EVENT_PIPE_NAME, PipeDirection.InOut, 1,
                        PipeTransmissionMode.Byte, PipeOptions.None,
                        65536, 65536, pipeSecurity))
                    {
                        var waitTask = Task.Run(() => pipeServer.WaitForConnection(), token);
                        waitTask.Wait(token);
                        if (!pipeServer.IsConnected) continue;

                        Log("Event pipe: tray app terhubung.");
                        lock (_eventPipeLock) _eventPipe = pipeServer;

                        // Tunggu sampai tray menutup koneksi (service restart / tray quit)
                        try
                        {
                            var buf = new byte[1];
                            while (!token.IsCancellationRequested)
                            {
                                if (pipeServer.Read(buf, 0, 1) <= 0) break;
                            }
                        }
                        catch { }
                        lock (_eventPipeLock) _eventPipe = null;
                        Log("Event pipe: tray app terputus.");
                    }
                }
                catch (OperationCanceledException) { break; }
                catch (Exception ex)
                {
                    Debug.WriteLine($"[EventPipe] Error: {ex.Message}");
                    SleepWithCancellation(1000, _cts.Token);
                }
            }
        }

        private void PushEvent(string evt, string message = null)
        {
            try
            {
                PipeStream pipe;
                lock (_eventPipeLock) pipe = _eventPipe;
                if (pipe == null) return;

                string frame = "{\"event\":\"" + evt + "\"";
                if (!string.IsNullOrEmpty(message))
                    frame += ",\"message\":\"" + message.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
                frame += "}\n";

                byte[] bytes = Encoding.UTF8.GetBytes(frame);
                lock (pipe)
                {
                    pipe.Write(bytes, 0, bytes.Length);
                    pipe.Flush();
                }
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[EventPipe] Push error: {ex.Message}");
            }
        }

        private string HandlePipeRequest(string request)
        {
            try
            {
                var req = ManualJsonDeserialize(request);
                string action = req.GetValueOrDefault("action", "")?.ToString();

                // Tray app hidup & sehat = selalu poll GET_STATUS/GET_BILLING
                // atau PING via pipe. Dipakai watchdog untuk deteksi hang.
                string actionUpper = action?.ToUpperInvariant();
                if (actionUpper == "GET_STATUS" || actionUpper == "GET_BILLING" || actionUpper == "PING")
                {
                    _lastTrayPing = DateTime.UtcNow;
                }

                switch (actionUpper)
                {
                    case "GET_STATUS":
                        lock (_billingLock)
                        {
                            return ManualJsonSerialize(new Dictionary<string, object>
                            {
                                ["status"] = "OK",
                                ["connected"] = IsConnected(),
                                ["is_locked"] = _isLocked,
                                ["lock_message"] = _lockMessage,
                                ["pc_id"] = _pcId ?? "",
                                ["client_id"] = _clientId,
                                ["kursi_name"] = _kursiName ?? "",
                                ["billing"] = new Dictionary<string, object>
                                {
                                    ["paket_aktif"] = _billingPaket,
                                    ["time_left"] = _billingTimeLeft,
                                    ["total_biaya"] = _billingTotalBiaya,
                                    ["is_playing"] = _billingIsPlaying,
                                }
                            });
                        }

                    case "GET_BILLING":
                        lock (_billingLock)
                        {
                            return ManualJsonSerialize(new Dictionary<string, object>
                            {
                                ["status"] = "OK",
                                ["paket_aktif"] = _billingPaket,
                                ["time_left"] = _billingTimeLeft,
                                ["total_biaya"] = _billingTotalBiaya,
                                ["is_playing"] = _billingIsPlaying,
                                ["is_locked"] = _isLocked,
                            });
                        }

                    case "PING":
                        return ManualJsonSerialize(new Dictionary<string, object>
                        {
                            ["status"] = "OK",
                            ["is_locked"] = _isLocked,
                        });

                    default:
                        return ManualJsonSerialize(new Dictionary<string, object>
                        {
                            ["status"] = "ERROR",
                            ["message"] = $"Unknown action: {action}"
                        });
                }
            }
            catch (Exception ex)
            {
                return ManualJsonSerialize(new Dictionary<string, object>
                {
                    ["status"] = "ERROR",
                    ["message"] = ex.Message
                });
            }
        }

        // ════════════════════════════════════════════════════════════════
        //  MAIN SERVICE LOOP
        // ════════════════════════════════════════════════════════════════
        private void ServiceLoop(object obj)
        {
            var token = _cts.Token;

            while (!token.IsCancellationRequested)
            {
                try
                {
                    if (!IsConnected())
                    {
                        Log($"Connecting to {_serverHost}:{_serverPort}...");
                        if (Connect())
                        {
                            Log("Connected. Sending AUTH...");
                            if (SendAuth())
                            {
                                Log("AUTH successful.");
                            }
                            else
                            {
                                Log("AUTH failed. Will retry...");
                                Disconnect();
                                SleepWithCancellation(5000, token);
                                continue;
                            }
                        }
                        else
                        {
                            Log("Connection failed. Will retry...");
                            SleepWithCancellation(5000, token);
                            continue;
                        }
                    }

                    // GET_STATUS rangkap sebagai heartbeat: server sudah
                    // memperbarui last_heartbeat utk GET_STATUS, jadi PING
                    // terpisah dihapus — 1 round-trip per siklus (lebih cepat,
                    // respons tidak bisa tertukar/tertinggal di buffer).
                    if (IsConnected())
                    {
                        if (SendGetStatus())
                        {
                            _getStatusFailCount = 0;
                        }
                        else
                        {
                            _getStatusFailCount++;
                            if (_getStatusFailCount >= 3)
                            {
                                Log("GET_STATUS tanpa respons berulang. Reconnect...");
                                Disconnect();
                                _getStatusFailCount = 0;
                            }
                        }
                    }

                    // Check heartbeat timeout
                    CheckHeartbeatTimeout();

                    SleepWithCancellation(_heartbeatIntervalMs, token);
                }
                catch (OperationCanceledException) { break; }
                catch (Exception ex)
                {
                    Log($"ServiceLoop error: {ex.Message}");
                    Disconnect();
                    SleepWithCancellation(3000, token);
                }
            }
        }

        // ════════════════════════════════════════════════════════════════
        //  TCP CONNECTION
        // ════════════════════════════════════════════════════════════════
        private bool Connect()
        {
            lock (_tcpLock)
            {
                try
                {
                    Disconnect();

                    _tcpClient = new TcpClient();
                    var result = _tcpClient.BeginConnect(_serverHost, _serverPort, null, null);
                    var success = result.AsyncWaitHandle.WaitOne(TimeSpan.FromSeconds(5));

                    if (!success)
                    {
                        _tcpClient.Close();
                        _tcpClient = null;
                        return false;
                    }

                    _tcpClient.EndConnect(result);
                    _tcpClient.SendTimeout = 5000;
                    _tcpClient.ReceiveTimeout = 5000;
                    _tcpClient.NoDelay = true;

                    _stream = _tcpClient.GetStream();
                    _lastHeartbeatResponse = DateTime.UtcNow;
                    return true;
                }
                catch (Exception ex)
                {
                    Log($"Connect error: {ex.Message}");
                    _tcpClient = null;
                    _stream = null;
                    return false;
                }
            }
        }

        private void Disconnect()
        {
            lock (_tcpLock)
            {
                try { _stream?.Close(); } catch { }
                try { _stream?.Dispose(); } catch { }
                try { _tcpClient?.Close(); } catch { }

                _stream = null;
                _tcpClient = null;
                _sessionToken = null;
                _pcId = null;
                lock (_billingLock)
                {
                    _billingIsPlaying = false;
                }
            }
        }

        private bool IsConnected()
        {
            lock (_tcpLock)
            {
                if (_tcpClient == null || _stream == null)
                    return false;
                try
                {
                    return !(_tcpClient.Client.Poll(1000, SelectMode.SelectRead) &&
                             _tcpClient.Client.Available == 0);
                }
                catch { return false; }
            }
        }

        // ════════════════════════════════════════════════════════════════
        //  AUTH
        // ════════════════════════════════════════════════════════════════
        private bool SendAuth()
        {
            try
            {
                var authMsg = new Dictionary<string, object>
                {
                    ["type"] = "AUTH",
                    ["client_id"] = _clientId,
                    ["password"] = _password,
                    ["timestamp"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                    ["mac"] = GetLocalMac(),
                };

                SendJson(authMsg);

                var response = ReceiveJson();
                if (response != null &&
                    response.TryGetValue("status", out var status) &&
                    status?.ToString() == "OK")
                {
                    _sessionToken = response.GetValueOrDefault("session_token", "")?.ToString();

                    // Get PC list from response (only if _pcId not set from config)
                    if (string.IsNullOrEmpty(_pcId))
                    {
                        if (response.TryGetValue("pcs", out var pcsObj) && pcsObj is List<object> pcsList && pcsList.Count > 0)
                        {
                            if (pcsList[0] is Dictionary<string, object> firstPc)
                            {
                                _pcId = firstPc.GetValueOrDefault("pc_id", "")?.ToString();
                            }
                        }
                    }

                    Log($"Authenticated as {_clientId}, PC: {_pcId}");
                    return true;
                }

                return false;
            }
            catch (Exception ex)
            {
                Log($"Auth error: {ex.Message}");
                return false;
            }
        }

        // ════════════════════════════════════════════════════════════════
        //  HEARTBEAT (PING)
        // ════════════════════════════════════════════════════════════════
        private void SendHeartbeat()
        {
            try
            {
                var hb = new Dictionary<string, object>
                {
                    ["type"] = "PING",
                    ["timestamp"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                };

                SendJson(hb);
                var pong = ReceiveJson(2000);
                _lastHeartbeatResponse = DateTime.UtcNow;
            }
            catch (Exception ex)
            {
                Log($"Heartbeat error: {ex.Message}");
                Disconnect();
            }
        }
        // ════════════════════════════════════════════════════════════════
        //  GET_STATUS (poll billing data + pending commands)
        // ════════════════════════════════════════════════════════════════
        private bool SendGetStatus()
        {
            try
            {
                if (string.IsNullOrEmpty(_sessionToken) || string.IsNullOrEmpty(_pcId))
                    return false;

                var req = new Dictionary<string, object>
                {
                    ["type"] = "GET_STATUS",
                    ["session_token"] = _sessionToken,
                    ["pc_id"] = _pcId,
                    ["timestamp"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                };

                SendJson(req);

                var response = ReceiveJson();
                if (response == null) return false;

                // Update last heartbeat on any response
                _lastHeartbeatResponse = DateTime.UtcNow;

                // Process billing data
                if (response.TryGetValue("billing", out var billingObj) &&
                    billingObj is Dictionary<string, object> billing)
                {
                    lock (_billingLock)
                    {
                        _billingPaket = billing.GetValueOrDefault("paket_aktif", "-")?.ToString() ?? "-";
                        _billingTimeLeft = ParseInt(billing.GetValueOrDefault("time_left", 0));
                        _billingTotalBiaya = ParseInt(billing.GetValueOrDefault("total_biaya", 0));
                        _billingIsPlaying = billing.GetValueOrDefault("is_playing", false)?.ToString() == "True" ||
                                            (billing.GetValueOrDefault("is_playing", 0)?.ToString() == "1");
                    }

                    // Process pending_commands
                    if (billing.TryGetValue("pending_commands", out var cmdsObj) &&
                        cmdsObj is List<object> pendingCmds && pendingCmds.Count > 0)
                    {
                        foreach (var cmdObj in pendingCmds)
                        {
                            if (cmdObj is Dictionary<string, object> cmd)
                            {
                                ProcessCommand(cmd);
                            }
                        }
                    }

                    // Fallback LOCK dari server: field is_locked=true dikirim
                    // saat kartu ditandai pc_locked (waktu habis / selesai /
                    // manual OFF). Dipakai bila pending_commands terlewat,
                    // mis. misalignment respons atau server restart.
                    bool serverLocked = billing.GetValueOrDefault("is_locked", false)?.ToString() == "True";
                    if (serverLocked && !_isLocked)
                    {
                        Log("[GetStatus] Fallback is_locked=true dari server -> lock PC.");
                        LockWorkstation("Waktu PC telah habis. Silahkan hubungi admin.");
                    }
                }

                return true;
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"[GetStatus] Error: {ex.Message}");
                return false;
            }
        }

        private void ProcessCommand(Dictionary<string, object> cmd)
        {
            string cmdType = cmd.GetValueOrDefault("cmd", "")?.ToString()?.ToUpperInvariant();
            string reason = cmd.GetValueOrDefault("reason", "")?.ToString();
            string message = cmd.GetValueOrDefault("message", "")?.ToString();

            Log($"Processing command: {cmdType} (reason: {reason})");

            switch (cmdType)
            {
                case "LOCK":
                case "LOCK_SCREEN":
                    string lockMsg = message;
                    if (string.IsNullOrEmpty(lockMsg))
                        lockMsg = reason == "waktu_habis" ? "Waktu PC telah habis." :
                                  reason == "selesai_manual" ? "Sesi dihentikan admin." :
                                  "PC Terkunci. Silahkan hubungi admin.";

                    LockWorkstation(lockMsg);
                    break;

                case "UNLOCK":
                    UnlockWorkstation();
                    break;

                case "SET_LOGO":
                    // Unduh logo lockscreen dari server (http://<kasir>:8082/media/...)
                    // lalu simpan sebagai lockscreen_logo.png di folder instalasi.
                    // Jangan refresh lock screen yang sedang aktif — logo baru akan
                    // terpakai di sesi lock berikutnya. Gagal = pertahankan logo lama.
                    {
                        string url = cmd.GetValueOrDefault("url", "")?.ToString();
                        if (string.IsNullOrEmpty(url))
                        {
                            Log("SET_LOGO: url kosong, logo lama dipertahankan.");
                            break;
                        }
                        Task.Run(() => DownloadLogoWorker(url));
                    }
                    break;

                case "SHUTDOWN":
                    // Matikan PC dari server (service LocalSystem punya privilege).
                    // Delay 10 dtk agar respons GET_STATUS sempat terkirim dulu.
                    Log($"[SHUTDOWN] Perintah dari server (reason: {reason})");
                    RunShutdown(false);
                    break;

                case "RESTART":
                    Log($"[RESTART] Perintah dari server (reason: {reason})");
                    RunShutdown(true);
                    break;

                default:
                    Log($"Unknown pending command: {cmdType}");
                    break;
            }
        }

        // ════════════════════════════════════════════════════════════════
        //  MAC ADDRESS — dilaporkan server saat AUTH untuk Wake-on-LAN
        // ════════════════════════════════════════════════════════════════
        private string GetLocalMac()
        {
            try
            {
                if (!string.IsNullOrEmpty(_macOverride))
                    return _macOverride;

                foreach (NetworkInterface ni in NetworkInterface.GetAllNetworkInterfaces())
                {
                    if (ni.OperationalStatus != OperationalStatus.Up) continue;
                    if (ni.NetworkInterfaceType == NetworkInterfaceType.Loopback ||
                        ni.NetworkInterfaceType == NetworkInterfaceType.Tunnel) continue;
                    byte[] mac = ni.GetPhysicalAddress()?.GetAddressBytes();
                    if (mac == null || mac.Length != 6) continue;
                    bool allZero = true;
                    foreach (byte b in mac) { if (b != 0) { allZero = false; break; } }
                    if (allZero) continue;
                    return string.Join(":", Array.ConvertAll(mac, b => b.ToString("X2")));
                }
            }
            catch (Exception ex)
            {
                Log($"GetLocalMac error: {ex.Message}");
            }
            return "";
        }

        // ════════════════════════════════════════════════════════════════
        //  SHUTDOWN / RESTART — matikan atau nyalakan ulang PC client
        //  Service berjalan sebagai LocalSystem → berhak mematikan mesin.
        // ════════════════════════════════════════════════════════════════
        private void RunShutdown(bool restart)
        {
            try
            {
                string verb = restart ? "/r" : "/s";
                string args = $"{verb} /t 10 /f";
                Log($"SHUTDOWN: menjalankan shutdown.exe {args}");
                var psi = new ProcessStartInfo("shutdown.exe", args)
                {
                    CreateNoWindow = true,
                    UseShellExecute = false,
                };
                using (var p = Process.Start(psi))
                {
                    // jangan tunggu — /t 10 memberi waktu koneksi ditutup rapi
                }
            }
            catch (Exception ex)
            {
                Log($"SHUTDOWN: gagal menjalankan shutdown.exe: {ex.Message}");
            }
        }

        // ════════════════════════════════════════════════════════════════
        //  SET_LOGO — unduh logo lockscreen dari server media (port 8082)
        // ════════════════════════════════════════════════════════════════
        private void DownloadLogoWorker(string url)
        {
            try
            {
                // Muat ulang URL unik per versi (?v=<mtime>) — download ke tmp
                // agar file logo aktif tidak pernah rusak.
                string baseDir = AppDomain.CurrentDomain.BaseDirectory;
                string tmpPath = Path.Combine(baseDir, "lockscreen_logo.downloading");
                string nameNew = "lockscreen_logo_" + DateTimeOffset.UtcNow.ToUnixTimeSeconds() + ".png";
                string pathNew = Path.Combine(baseDir, nameNew);

                var request = (HttpWebRequest)WebRequest.Create(url);
                request.Timeout = (int)_logoDownloadTimeout.TotalMilliseconds;
                request.ReadWriteTimeout = (int)_logoDownloadTimeout.TotalMilliseconds;
                request.UserAgent = "RRBillingClient";

                using (var response = (HttpWebResponse)request.GetResponse())
                using (var stream = response.GetResponseStream())
                {
                    if (stream == null) throw new IOException("Respons kosong.");
                    using (var fs = new FileStream(tmpPath, FileMode.Create, FileAccess.Write, FileShare.None))
                    {
                        stream.CopyTo(fs);
                        fs.Flush(true);
                    }
                }

                File.Move(tmpPath, pathNew);   // move — file baru, tidak terkunci

                // Bersihkan file logo versi lama (best effort — kalau terkunci lock
                // screen yang sedang tampil, dilewati; akan dibersihkan nanti).
                CleanupOldLogos(baseDir, nameNew);

                // Perbarui nama kanonik (dipakai INSTALL/legacy reader). Gagal aman
                // bila lock screen aktif mengunci file lama — versi baru tetap terpakai.
                try { File.Copy(pathNew, Path.Combine(baseDir, "lockscreen_logo.png"), true); }
                catch { }

                Log($"SET_LOGO: logo diterapkan -> {nameNew} ({url})");
            }
            catch (Exception ex)
            {
                try
                {
                    string p = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "lockscreen_logo.downloading");
                    if (File.Exists(p)) File.Delete(p);
                }
                catch { }
                Log($"SET_LOGO: gagal mengunduh logo: {ex.Message} — logo lama dipertahankan.");
            }
        }

        // Hapus lock logo versi lama kecuali yang terbaru (agar folder tidak penuh).
        private void CleanupOldLogos(string baseDir, string keepName)
        {
            try
            {
                string[] candidates = Directory.GetFiles(baseDir, "lockscreen_logo_*.png");
                foreach (string f in candidates)
                {
                    string name = Path.GetFileName(f);
                    if (name.Equals(keepName, StringComparison.OrdinalIgnoreCase)) continue;
                    try { File.Delete(f); } catch { }
                }
            }
            catch { }
        }

        // ════════════════════════════════════════════════════════════════
        //  LOCK / UNLOCK
        // ════════════════════════════════════════════════════════════════
        private void LockWorkstation(string message = null)
        {
            if (_isLocked)
            {
                Log("Already locked, skipping.");
                return;
            }

            Log($"Lock flag set: {message}");
            _isLocked = true;
            _lockMessage = message ?? "";
            SaveLockState();
            SendClientStatus("locked");
            PushEvent("NOTIFY_LOCK", message ?? "");
        }

        private void UnlockWorkstation()
        {
            if (!_isLocked)
            {
                Log("Not locked, skipping unlock.");
                return;
            }

            Log("Unlock flag set.");
            _isLocked = false;
            _lockMessage = "";
            ClearLockState();
            SendClientStatus("unlocked");
            PushEvent("NOTIFY_UNLOCK");
        }

        private void CheckHeartbeatTimeout()
        {
            if (_isLocked) return; // Already locked

            var elapsed = DateTime.UtcNow - _lastHeartbeatResponse;
            if (elapsed.TotalMilliseconds > _heartbeatTimeoutMs)
            {
                Log($"Heartbeat timeout ({elapsed.TotalSeconds:F1}s). Auto-locking.");
                LockWorkstation("Koneksi ke server billing terputus. Silahkan hubungi admin.");
            }
        }

        private void SendClientStatus(string status)
        {
            try
            {
                if (!IsConnected()) return;
                var msg = new Dictionary<string, object>
                {
                    ["type"] = "STATUS",
                    ["status"] = status,
                    ["client_id"] = _clientId,
                    ["pc_id"] = _pcId ?? "",
                    ["timestamp"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                };
                SendJson(msg);
            }
            catch (Exception ex)
            {
                Log($"SendStatus error: {ex.Message}");
            }
        }

        // ════════════════════════════════════════════════════════════════
        //  WATCHDOG — pastikan tray app selalu berjalan di user session
        // ════════════════════════════════════════════════════════════════
        private void WatchdogLoop(object obj)
        {
            var token = _cts.Token;
            while (!token.IsCancellationRequested)
            {
                try
                {
                    EnsureTrayAppRunning();
                }
                catch (Exception ex)
                {
                    Log($"Watchdog error: {ex.Message}");
                }
                SleepWithCancellation(_watchdogIntervalMs, token);
            }
        }

        private void EnsureTrayAppRunning()
        {
            if (_cts.IsCancellationRequested) return;

            // Sudah ada tray app yang jalan? (di session mana pun)
            try
            {
                Process[] procs = Process.GetProcessesByName("BillingClientApp");
                if (procs != null && procs.Length > 0)
                {
                    // Proses ada tapi tidak pernah/tidak lagi poll pipe (hang):
                    // kill lalu relaunch. Beri jeda untuk tray yang baru start.
                    bool hung = _lastTrayPing != DateTime.MinValue &&
                                (DateTime.UtcNow - _lastTrayPing).TotalMilliseconds > _trayHangTimeoutMs;
                    if (!hung) return;

                    Log($"Watchdog: tray app hang (ping terakhir >{_trayHangTimeoutMs / 1000}s lalu). Restart...");
                    foreach (Process p in procs)
                    {
                        try { p.Kill(); } catch { }
                    }
                }
            }
            catch { }

            string appPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "BillingClientApp.exe");
            if (!File.Exists(appPath))
            {
                Log("Watchdog: BillingClientApp.exe tidak ditemukan di folder install.");
                return;
            }

            uint sessionId = WTSGetActiveConsoleSessionId();
            if (sessionId == 0 || sessionId == INVALID_SESSION_ID)
            {
                // Belum ada user yang login — coba lagi di tick berikutnya.
                return;
            }

            IntPtr userToken = IntPtr.Zero;
            if (!WTSQueryUserToken(sessionId, out userToken) || userToken == IntPtr.Zero)
            {
                Log($"Watchdog: WTSQueryUserToken gagal (session {sessionId}, err {Marshal.GetLastWin32Error()}).");
                return;
            }

            try
            {
                IntPtr primary = IntPtr.Zero;
                const int TOKEN_ALL = TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_QUERY;
                if (!DuplicateTokenEx(userToken, TOKEN_ALL, IntPtr.Zero,
                                      SecurityImpersonation, TokenPrimary, out primary))
                {
                    Log($"Watchdog: DuplicateTokenEx gagal (err {Marshal.GetLastWin32Error()}).");
                    return;
                }

                try
                {
                    IntPtr env = IntPtr.Zero;
                    bool haveEnv = false;
                    try { haveEnv = CreateEnvironmentBlock(out env, primary, false); }
                    catch { }

                    var si = new STARTUPINFO();
                    si.cb = (uint)Marshal.SizeOf(typeof(STARTUPINFO));
                    si.lpDesktop = "winsta0\\default";
                    si.dwFlags = STARTF_USESHOWWINDOW;
                    si.wShowWindow = SW_SHOWNORMAL;

                    string cmdLine = "\"" + appPath + "\"";
                    PROCESS_INFORMATION pi;
                    bool ok = CreateProcessAsUser(
                        primary, null, cmdLine,
                        IntPtr.Zero, IntPtr.Zero, false, 0,
                        haveEnv ? env : IntPtr.Zero, null, ref si, out pi);

                    if (haveEnv) { try { DestroyEnvironmentBlock(env); } catch { } }

                    if (ok)
                    {
                        CloseHandle(pi.hThread);
                        CloseHandle(pi.hProcess);
                        Log($"Watchdog: BillingClientApp diluncurkan ulang di session {sessionId}.");
                    }
                    else
                    {
                        Log($"Watchdog: CreateProcessAsUser gagal (err {Marshal.GetLastWin32Error()}).");
                    }
                }
                finally
                {
                    CloseHandle(primary);
                }
            }
            finally
            {
                CloseHandle(userToken);
            }
        }

        // ── P/Invoke untuk watchdog (launch di user session aktif) ─────
        private const uint INVALID_SESSION_ID = 0xFFFFFFFF;
        private const int TOKEN_ASSIGN_PRIMARY = 0x0001;
        private const int TOKEN_DUPLICATE = 0x0002;
        private const int TOKEN_QUERY = 0x0008;
        private const int SecurityImpersonation = 2;
        private const int TokenPrimary = 1;
        private const uint STARTF_USESHOWWINDOW = 0x00000001;
        private const ushort SW_SHOWNORMAL = 1;

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint WTSGetActiveConsoleSessionId();

        [DllImport("wtsapi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool WTSQueryUserToken(uint sessionId, out IntPtr phToken);

        [DllImport("advapi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool DuplicateTokenEx(
            IntPtr hExistingToken, int dwDesiredAccess, IntPtr lpTokenAttributes,
            int ImpersonationLevel, int TokenType, out IntPtr phNewToken);

        [DllImport("userenv.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CreateEnvironmentBlock(out IntPtr lpEnvironment, IntPtr hToken, bool bInherit);

        [DllImport("userenv.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool DestroyEnvironmentBlock(IntPtr lpEnvironment);

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CreateProcessAsUser(
            IntPtr hToken, string lpApplicationName, string lpCommandLine,
            IntPtr lpProcessAttributes, IntPtr lpThreadAttributes,
            [MarshalAs(UnmanagedType.Bool)] bool bInheritHandles, uint dwCreationFlags,
            IntPtr lpEnvironment, string lpCurrentDirectory,
            ref STARTUPINFO lpStartupInfo, out PROCESS_INFORMATION lpProcessInformation);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CloseHandle(IntPtr hObject);

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct STARTUPINFO
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
        private struct PROCESS_INFORMATION
        {
            public IntPtr hProcess;
            public IntPtr hThread;
            public uint dwProcessId;
            public uint dwThreadId;
        }

        // ════════════════════════════════════════════════════════════════
        //  JSON SEND / RECEIVE
        // ════════════════════════════════════════════════════════════════
        private void SendJson(Dictionary<string, object> msg)
        {
            string json = ManualJsonSerialize(msg);
            byte[] data = Encoding.UTF8.GetBytes(json + "\n");

            lock (_tcpLock)
            {
                if (_stream != null && _stream.CanWrite)
                {
                    _stream.Write(data, 0, data.Length);
                    _stream.Flush();
                }
            }
        }

        private Dictionary<string, object> ReceiveJson(int timeoutMs = 3000)
        {
            lock (_tcpLock)
            {
                if (_stream == null || !_stream.CanRead)
                    return null;

                try
                {
                    var sb = new StringBuilder();
                    int start = Environment.TickCount;

                    while (Environment.TickCount - start < timeoutMs)
                    {
                        if (_stream.DataAvailable)
                        {
                            int b = _stream.ReadByte();
                            if (b == -1) return null;
                            if (b == '\n') break;
                            if (b != '\r') sb.Append((char)b);
                        }
                        else
                        {
                            System.Threading.Thread.Sleep(20);
                        }
                    }

                    string raw = sb.ToString().Trim();
                    if (string.IsNullOrEmpty(raw)) return null;

                    return ManualJsonDeserialize(raw);
                }
                catch (IOException) { return null; }
                catch (ObjectDisposedException) { return null; }
            }
        }

        // ════════════════════════════════════════════════════════════════
        //  MANUAL JSON (no external dependencies)
        // ════════════════════════════════════════════════════════════════
        private string ManualJsonSerialize(Dictionary<string, object> dict)
        {
            var sb = new StringBuilder();
            sb.Append('{');
            bool first = true;
            foreach (var kvp in dict)
            {
                if (!first) sb.Append(',');
                first = false;
                sb.Append('"').Append(kvp.Key).Append('"').Append(':');
                if (kvp.Value is Dictionary<string, object> nested)
                    sb.Append(ManualJsonSerialize(nested));
                else if (kvp.Value is List<object> list)
                {
                    sb.Append('[');
                    for (int i = 0; i < list.Count; i++)
                    {
                        if (i > 0) sb.Append(',');
                        if (list[i] is Dictionary<string, object> nested2)
                            sb.Append(ManualJsonSerialize(nested2));
                        else if (list[i] is string s)
                            sb.Append('"').Append(EscapeJsonString(s)).Append('"');
                        else
                            sb.Append(list[i]?.ToString() ?? "null");
                    }
                    sb.Append(']');
                }
                else if (kvp.Value is string s)
                    sb.Append('"').Append(EscapeJsonString(s)).Append('"');
                else if (kvp.Value is int i)
                    sb.Append(i);
                else if (kvp.Value is long l)
                    sb.Append(l);
                else if (kvp.Value is bool b)
                    sb.Append(b ? "true" : "false");
                else if (kvp.Value == null)
                    sb.Append("null");
                else
                    sb.Append('"').Append(EscapeJsonString(kvp.Value.ToString())).Append('"');
            }
            sb.Append('}');
            return sb.ToString();
        }

        private Dictionary<string, object> ManualJsonDeserialize(string json)
        {
            var result = new Dictionary<string, object>();
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

                if (json[i] == '[')
                {
                    // Parse array
                    i++;
                    var list = new List<object>();
                    int depth = 1;
                    var itemSb = new StringBuilder();
                    while (i < json.Length && depth > 0)
                    {
                        if (json[i] == '[' || json[i] == '{') depth++;
                        else if (json[i] == ']' || json[i] == '}') { depth--; if (depth == 0 && json[i] == ']') break; }
                        else if (json[i] == ',' && depth == 1)
                        {
                            if (itemSb.Length > 0)
                            {
                                var item = ParseJsonValue(itemSb.ToString().Trim());
                                if (item != null) list.Add(item);
                                itemSb.Clear();
                            }
                            i++;
                            continue;
                        }
                        itemSb.Append(json[i]);
                        i++;
                    }
                    if (itemSb.Length > 0)
                    {
                        var item = ParseJsonValue(itemSb.ToString().Trim());
                        if (item != null) list.Add(item);
                    }
                    result[key] = list;
                    i++;
                }
                else if (json[i] == '{')
                {
                    int depth = 1;
                    i++;
                    var objSb = new StringBuilder();
                    while (i < json.Length && depth > 0)
                    {
                        if (json[i] == '{') depth++;
                        else if (json[i] == '}') { depth--; if (depth == 0) break; }
                        objSb.Append(json[i]);
                        i++;
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
                        else valSb.Append(json[i]);
                        i++;
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
                {
                    result[key] = null;
                    i += 4;
                }
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

        private object ParseJsonValue(string val)
        {
            if (string.IsNullOrEmpty(val)) return null;
            if (val.StartsWith("{")) return ManualJsonDeserialize(val);
            if (val.StartsWith("\"")) { val = val.Trim('"'); return val; }
            if (val == "true") return true;
            if (val == "false") return false;
            if (val == "null") return null;
            if (int.TryParse(val, out int i)) return i;
            if (long.TryParse(val, out long l)) return l;
            if (double.TryParse(val, out double d)) return d;
            return val;
        }

        private string EscapeJsonString(string s)
        {
            if (s == null) return "";
            var sb = new StringBuilder();
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default: sb.Append(c); break;
                }
            }
            return sb.ToString();
        }

        // ════════════════════════════════════════════════════════════════
        //  LOCK STATE PERSISTENCE — lock tetap terkunci setelah reboot
        // ════════════════════════════════════════════════════════════════
        private const string LOCK_STATE_FILE = "rr_billing_lock_state.json";

        private string LockStatePath()
        {
            return Path.Combine(AppDomain.CurrentDomain.BaseDirectory, LOCK_STATE_FILE);
        }

        private void SaveLockState()
        {
            try
            {
                var state = new Dictionary<string, object>
                {
                    ["is_locked"] = true,
                    ["lock_message"] = _lockMessage ?? "",
                    ["timestamp"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                };
                string json = ManualJsonSerialize(state);
                File.WriteAllText(LockStatePath(), json);
                Log("Lock state disimpan (persisten lintas reboot).");
            }
            catch (Exception ex)
            {
                Log($"SaveLockState error: {ex.Message}");
            }
        }

        private void ClearLockState()
        {
            try
            {
                string path = LockStatePath();
                if (File.Exists(path))
                    File.Delete(path);
                Log("Lock state dihapus.");
            }
            catch (Exception ex)
            {
                Log($"ClearLockState error: {ex.Message}");
            }
        }

        private void LoadLockState()
        {
            try
            {
                string path = LockStatePath();
                if (!File.Exists(path)) return;

                string json = File.ReadAllText(path);
                var state = ManualJsonDeserialize(json);
                if (state.TryGetValue("is_locked", out var locked) && locked is bool b && b)
                {
                    _isLocked = true;
                    _lockMessage = state.GetValueOrDefault("lock_message", "")?.ToString() ?? "";
                    Log("Lock state dimuat dari file — PC akan terkunci kembali setelah login.");
                }
            }
            catch (Exception ex)
            {
                Log($"LoadLockState error: {ex.Message}");
            }
        }

        // ════════════════════════════════════════════════════════════════
        //  CONFIG LOADER
        // ════════════════════════════════════════════════════════════════
        private void LoadConfig()
        {
            string configPath = Path.Combine(
                AppDomain.CurrentDomain.BaseDirectory,
                "rr_billing_config.json");

            try
            {
                if (File.Exists(configPath))
                {
                    string json = File.ReadAllText(configPath);
                    var config = ManualJsonDeserialize(json);

                    if (config.TryGetValue("server_host", out var host))
                        _serverHost = host?.ToString() ?? _serverHost;
                    if (config.TryGetValue("server_port", out var port))
                        int.TryParse(port?.ToString(), out _serverPort);
                    if (config.TryGetValue("client_id", out var cid))
                        _clientId = cid?.ToString() ?? _clientId;
                    if (config.TryGetValue("password", out var pwd))
                        _password = pwd?.ToString() ?? _password;
                    if (config.TryGetValue("pc_id", out var pcid))
                        _pcId = pcid?.ToString() ?? _pcId;
                    if (config.TryGetValue("mac", out var mac))
                        _macOverride = mac?.ToString() ?? "";
                }

                // Override from environment variables
                _serverHost = GetEnv("RR_BILLING_SERVER_HOST", _serverHost);
                _serverPort = int.Parse(GetEnv("RR_BILLING_SERVER_PORT", _serverPort.ToString()));
                _clientId = GetEnv("RR_BILLING_CLIENT_ID", _clientId);
                _password = GetEnv("RR_BILLING_PASSWORD", _password);
                string envPcId = GetEnv("RR_BILLING_PC_ID", null);
                if (envPcId != null) _pcId = envPcId;

                _lockAppPath = Path.Combine(
                    AppDomain.CurrentDomain.BaseDirectory,
                    "BillingLockScreenUI.exe");

                Log($"Config: Server={_serverHost}:{_serverPort}, Client={_clientId}, PC={_pcId ?? "(auto)"}");
            }
            catch (Exception ex)
            {
                Log($"Config load error: {ex.Message}. Using defaults.");
            }
        }

        private static string GetEnv(string key, string defaultValue)
        {
            string val = Environment.GetEnvironmentVariable(key);
            return string.IsNullOrEmpty(val) ? defaultValue : val;
        }

        private static int ParseInt(object value, int defaultValue = 0)
        {
            if (value == null) return defaultValue;
            if (value is int i) return i;
            if (value is long l) return (int)l;
            if (int.TryParse(value.ToString(), out int result)) return result;
            return defaultValue;
        }

        // ════════════════════════════════════════════════════════════════
        //  LOGGING
        // ════════════════════════════════════════════════════════════════
        public void Log(string message)
        {
            string line = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {message}";
            Debug.WriteLine(line);
            Console.WriteLine(line);

            try
            {
                string logPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, LOG_FILE);
                lock (typeof(ServiceCore))
                {
                    File.AppendAllText(logPath, line + Environment.NewLine);
                }
            }
            catch { }

            try
            {
                if (!EventLog.SourceExists(ServiceName))
                    EventLog.CreateEventSource(ServiceName, "Application");
                EventLog.WriteEntry(ServiceName, message, EventLogEntryType.Information);
            }
            catch { }
        }

        private static void SleepWithCancellation(int ms, CancellationToken token)
        {
            try { Thread.Sleep(ms); } catch (ThreadInterruptedException) { }
        }
    }

    internal static class DictionaryExtensions
    {
        public static TValue GetValueOrDefault<TKey, TValue>(
            this IDictionary<TKey, TValue> dict, TKey key, TValue defaultValue = default)
        {
            if (dict.TryGetValue(key, out var value))
                return value;
            return defaultValue;
        }
    }
}
