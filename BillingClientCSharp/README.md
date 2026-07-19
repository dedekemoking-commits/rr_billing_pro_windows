# RR Billing Pro — Client C# (Topologi Baru)

## Arsitektur Topologi

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SERVER (Python)                             │
│                     main.py — WarnetSocketServer                    │
│         TCP port 5000 — JSON protocol — Single Source of Truth      │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ TCP/JSON (AUTH, PING, GET_STATUS, COMMAND)
                           │
              ┌────────────┴────────────┐
              │  Local PC (Client Side) │
              │  ─────────────────────  │
              │                         │
              │  [1] BillingClientService.exe  ── Windows Service     │
              │  ───────────────────────────                           │
              │  • Runs as LocalSystem                                │
              │  • TCP client → server (heartbeat 5s)                 │
              │  • Named pipe IPC → BillingClientApp                  │
              │  • Receives LOCK/UNLOCK commands                      │
              │  • Auto-lock on heartbeat timeout (15s)               │
              │  • Calls DesktopLocker.Lock()/Unlock()                │
              │                         │
              │  [2] BillingLockScreenUI.exe  ── WinForms             │
              │  ───────────────────────────                           │
              │  • Runs on virtual desktop "BillingLockDesktop_v1"    │
              │  • Fullscreen, anti-Alt+F4, anti-Alt+Tab              │
              │  • Only shown when PC is locked                       │
              │  • Cannot be closed by user                           │
              │  • Game/apps continue on original desktop             │
              │                         │
              │  [3] BillingClientApp.exe  ── System Tray             │
              │  ───────────────────────────                           │
              │  • Shows in notification area                         │
              │  • Displays billing status (paket, waktu, biaya)      │
              │  • Balloon notification on lock/unlock                │
              │  • Communicates with service via named pipe           │
              │  • Auto-start with Windows (via Startup folder)       │
              └───────────────────────────────────────────────────────┘
```

## Mekanisme Lock Screen (CreateDesktop API)

### Flow LOCK:
1. Service menerima `{"cmd": "LOCK"}` dari server
2. `OpenInputDesktop()` — simpan handle desktop asli
3. `CreateDesktop("BillingLockDesktop_v1")` — buat desktop virtual
4. `SetThreadDesktop()` — set thread ke desktop baru
5. `Process.Start(BillingLockScreenUI.exe)` — launch lock screen di desktop baru
6. `SwitchDesktop()` — pindah input layar ke desktop virtual
7. User hanya melihat lock screen — game tetap jalan di background

### Flow UNLOCK:
1. Service menerima `{"cmd": "UNLOCK"}` dari server
2. `SwitchDesktop(hOriginalDesktop)` — kembali ke desktop asli
3. Kill process BillingLockScreenUI
4. `CloseDesktop(hLockDesktop)` — tutup handle desktop virtual

## Protokol Komunikasi

### Server → Client (via GET_STATUS response → pending_commands):
```json
{
  "type": "STATUS_RESPONSE",
  "status": "OK",
  "billing": {
    "pc_id": "PC_1",
    "paket_aktif": "-",
    "time_left": 0,
    "total_biaya": 0,
    "is_playing": false,
    "pending_commands": [
      {"cmd": "LOCK", "reason": "waktu_habis", "message": "Waktu PC telah habis."}
    ]
  }
}
```

### Client → Server (heartbeat):
```json
{"type": "PING", "timestamp": 1712345678}
```

### Named Pipe IPC (C# Service ↔ C# Tray App):
```
Request:  {"action": "GET_STATUS"}
Response: {"status": "OK", "connected": true, "is_locked": false, ...}
```

## File Output (`dist/`)

| File | Ukuran | Fungsi |
|------|--------|--------|
| `BillingClientService.exe` | 29 KB | Windows Service (LocalSystem) |
| `BillingLockScreenUI.exe` | 12 KB | Lock Screen UI (virtual desktop) |
| `BillingClientApp.exe` | 12 KB | System Tray App (billing info) |

## Cara Install & Deploy

### 1. Build
```
cd BillingClientCSharp
build_direct.bat
```

### 2. Install Service
```
cd dist
BillingClientService.exe -i
net start RRBillingClientService
```

### 3. Konfigurasi
Buat `rr_billing_config.json` di folder `dist/`:
```json
{
  "server_host": "192.168.1.100",
  "server_port": 5000,
  "client_id": "WARNET_01",
  "password": "admin123"
}
```

### 4. Auto-start Tray App
- Buat shortcut `BillingClientApp.exe` di `shell:startup`

### 5. Debug Mode
```
BillingClientService.exe -c
```

### 6. Test LOCK/UNLOCK
Dari dashboard warnet server:
- Mulai sesi → client terima UNLOCK (PC aktif)
- Waktu habis → client terima LOCK (PC terkunci)

## Catatan Keamanan
1. Windows Service (LocalSystem) — tidak bisa dimatikan user biasa
2. CreateDesktop API — Task Manager user tidak bisa switch ke desktop asli
3. LockScreenUI block: Alt+F4, Alt+Tab, Ctrl+Alt+Del (via WndProc)
4. Auto-lock on heartbeat timeout — PC terkunci jika koneksi server putus
5. Game tetap berjalan di desktop asli — tidak di-terminate
