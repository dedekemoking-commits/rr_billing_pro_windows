╔══════════════════════════════════════════════════════════╗
║        RR Billing Pro v2.3 — Client Warnet             ║
║           Sistem Billing WiFi / Warnet                   ║
╚══════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ISI FOLDER:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  BillingClientService.exe    — Windows Service (LocalSystem)
  BillingLockScreenUI.exe     — Lock Screen App (virtual desktop)
  BillingClientApp.exe        — System Tray App (info billing)
  rr_billing_config.json      — Konfigurasi server
  INSTALL_CLIENT.bat          — Installer otomatis
  README.txt                  — File ini

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CARA INSTALL CEPAT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Edit rr_billing_config.json — isi IP server billing
  2. Klik kanan INSTALL_CLIENT.bat → "Run as Administrator"
  3. Service terinstall & jalan otomatis
  4. BillingClientApp.exe muncul di system tray

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CARA INSTALL MANUAL:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Buka CMD sebagai Administrator
  2. cd ke folder ini
  3. Install service:   BillingClientService.exe -i
  4. Start service:     net start RRBillingClientService
  5. Jalankan tray:     BillingClientApp.exe (double-click)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KONFIGURASI:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  File: rr_billing_config.json

  {
    "server_host": "192.168.1.100",     ← IP server billing
    "server_port": 5000,                ← Port TCP server
    "client_id": "WARNET_01",           ← ID client (dari server)
    "password": "admin123"              ← Password client
  }

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LOG:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  File: rr_billing_client_service.log
  (di folder yang sama dengan service)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UNINSTALL:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CMD sebagai Administrator:
    net stop RRBillingClientService
    BillingClientService.exe -u

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RR Dev Team | RR Billing Pro v2.3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
