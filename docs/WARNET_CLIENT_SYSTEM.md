# Sistem Koneksi Client Warnet (RR Billing Pro)

Dokumentasi alur koneksi antara **server billing** (PC kasir, `main.py`) dan
**client warnet** (PC warnet, `BillingClientService.exe` C#).

## Arsitektur

```
┌─────────────────────────┐        TCP :5000 (JSON line-based)        ┌─────────────────────────┐
│  SERVER BILLING (PC)   │ ◄──────────────────────────────────────────► │  PC CLIENT WARNET      │
│  WarnetSocketServer     │  WS  :5001 (opsional, protokol sama)        │  BillingClientService  │
│  (main.py)              │                                             │  BillingClientApp      │
│  port TCP 5000          │                                             │  BillingLockScreenUI   │
│  port WS  5001          │                                             └─────────────────────────┘
└─────────────────────────┘
```

- **Satu arah data**: client PC meminta status (poll), server menjawab
  billing asli + perintah pending (LOCK/UNLOCK).
- **Kasir → PC**: perintah tidak dikirim langsung; antri di server
  (`pending_commands`), diambil client pada GET_STATUS berikutnya.
- Server warnet DULU juga mendukung perintah socket teks
  `START {kursi}` / `STOP {kursi}` — **telah dihapus** (tidak punya penerima;
  kontrol PC sepenuhnya lewat LOCK/UNLOCK).

## Protokol

Semua pesan = JSON satu baris + `\n` (newline).

### 1. AUTH
Client → server:
```json
{"type": "AUTH", "client_id": "WARNET_01", "password": "admin123"}
```
Server → client (`_handle_auth`, main.py):
```json
{"type": "AUTH_RESPONSE", "status": "OK", "client_id": "...",
 "session_token": "<JWT 6 bulan>", "pcs": [{"pc_id": "PC_1", "ip": "...", "name": "..."}]}
```
- Validasi: `client_id` harus ada di `warnet_clients` pada
  `rr_billing_config.json`; password dicocokkan dengan `password_hash`
  (SHA256 plain atau `bcrypt$`).
- Jika `pc_id` tidak diset di config client, client memakai PC pertama
  dari daftar `pcs`.

### 2. GET_STATUS (poll 5 detik)
Client → server:
```json
{"type": "GET_STATUS", "session_token": "...", "pc_id": "PC_1"}
```
Server → client (`_handle_get_status`):
```json
{"type": "STATUS_RESPONSE", "status": "OK", "billing": {
   "pc_id": "PC_1", "time_left": 3540, "paket_aktif": "1 Jam",
   "total_biaya": 10000, "is_playing": true,
   "pending_commands": [{"cmd": "LOCK", "reason": "waktu_habis", "message": "..."}]}}
```
- Data billing diambil dari kartu warnet di dashboard (`_semua_kartu_warnet`
  dicari by `_pc_id`).
- `paket_aktif = "SELESAI"` dikirim bila sesi baru saja berakhir
  (memicu lock screen di client).
- `pending_commands` **dipop** sekali; client memproses LOCK/UNLOCK.

### 3. PING (heartbeat, 5 detik)
```json
{"type": "PING"}   →   {"type": "PONG", "server_timestamp": ...}
```
- Client auto-lock bila tidak ada respons server > 15 detik.

### 4. REQUEST add_time
Client meminta tambah waktu paket (mis. sisa waktu tinggal sedikit):
```json
{"type": "REQUEST", "session_token": "...", "pc_id": "PC_1",
 "request_type": "add_time", "data": {"package": "1 Jam"}}
```
Server → cari kartu warnet by `pc_id`, tambahkan paket langsung di dashboard
(harga + durasi, dicatat transaksi, `sisa_waktu` bertambah) → respons
`REQUEST_RESPONSE` OK/FAIL. Panggilan dipindah ke thread utama via
`app.after(0, ...)` agar aman untuk Tk.

## Mengelola Client (warnet_clients)

Edit `rr_billing_config.json` (tidak ada UI khusus):
```json
"warnet_clients": [
  {
    "client_id": "WARNET_01",
    "password_hash": "<sha256 plaintext atau bcrypt$...>",
    "location": "Warnet Lokasi 1",
    "pcs": [
      {"pc_id": "PC_1", "ip": "192.168.1.13", "name": "Kursi 5"},
      {"pc_id": "PC_2", "ip": "192.168.1.14", "adb_port": 5555, "name": "Kursi 2"}
    ],
    "allowed_actions": ["ON", "OFF", "VOL+", "VOL-"],
    "created_at": "2026-07-18T00:00:00",
    "tokens": []
  }
]
```
- Buat hash SHA256: `python -c "import hashlib; print(hashlib.sha256(b'password').hexdigest())"`
- `allowed_actions` dipakai oleh `COMMAND` (dieksekusi via ADB ke `ip` PC).

## Alur Kasir di Dashboard

| Aksi | Efek ke PC client |
|------|-------------------|
| Mulai paket (DialogPaket) | `pending_commands: UNLOCK` (reason `sesi_baru`) |
| Waktu habis | `pending_commands: LOCK` (reason `waktu_habis`) |
| Selesai manual (SELESAI) | `pending_commands: LOCK` (reason `selesai_manual`) |
| Tombol ON/OFF kartu | `UNLOCK`/`LOCK` (reason `manual_on`/`manual_off`) + peringatan bila client offline |
| Client request add_time | Tambah waktu langsung di kartu + catat transaksi |

## Status Koneksi di UI

- Header warnet: label `Client: Tersambung / Belum tersambung` —
  dicek dari sesi AUTH aktif (`WarnetSocketServer.sessions`), diperbarui
  otomatis tiap 10 detik.
- Tiap kartu: `● Connected / ● Disconnected` (poll 5 detik).
- Tombol `➕ Tambah Kursi` hanya aktif bila ada client terhubung.

## Tes Tanpa PC Fisik

```bash
# 1. Jalankan server (main.py) lalu:
python tools/warnet_sim_client.py --host 127.0.0.1 --port 5000 \
    --client WARNET_01 --password admin123 --pc PC_1 --iterations 3
```
Harusnya tampil: `AUTH OK` lalu baris status billing tiap iterasi.
Untuk tes perintah LOCK: buka paket/matikan kartu di dashboard, lalu amati
`pending=1` + detail command di output sim.
