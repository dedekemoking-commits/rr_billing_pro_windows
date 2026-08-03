"""
Simulasi client warnet untuk tes alur koneksi ke server billing.
Meniru perilaku BillingClientService.exe (C#):

  1. Connect TCP ke server billing (port 5000 default)
  2. AUTH {client_id, password} -> session_token (JWT)
  3. Loop tiap 5 detik: PING (heartbeat) + GET_STATUS
  4. Cetak billing (paket, sisa waktu, total) + pending_commands

Contoh:
  python tools/warnet_sim_client.py
  python tools/warnet_sim_client.py --host 192.168.1.17 --port 5000 \
      --client WARNET_01 --password admin123 --pc PC_1
"""
import argparse
import json
import socket
import sys
import time


class SimClient:
    def __init__(self, host, port, client_id, password, pc_id):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.password = password
        self.pc_id = pc_id
        self.sock = None
        self.token = None

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=8)
        self.sock.settimeout(8)
        return True

    def send(self, msg):
        data = json.dumps(msg).encode("utf-8") + b"\n"
        self.sock.sendall(data)

    def recv(self, timeout=4):
        self.sock.settimeout(timeout)
        buf = b""
        while b"\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                return None
            buf += chunk
        line = buf.split(b"\n", 1)[0].strip()
        try:
            return json.loads(line.decode("utf-8"))
        except json.JSONDecodeError as e:
            print(f"[sim] respon tidak valid: {line[:200]} ({e})")
            return None

    def auth(self):
        self.send({"type": "AUTH", "client_id": self.client_id,
                   "password": self.password,
                   "timestamp": int(time.time())})
        resp = self.recv()
        if not resp or resp.get("status") != "OK":
            return False, resp
        self.token = resp.get("session_token")
        if not self.pc_id:
            pcs = resp.get("pcs") or []
            if pcs:
                self.pc_id = pcs[0].get("pc_id")
        return True, resp

    def ping(self):
        self.send({"type": "PING", "timestamp": int(time.time())})
        return self.recv(3)

    def get_status(self):
        self.send({"type": "GET_STATUS", "session_token": self.token,
                   "pc_id": self.pc_id, "timestamp": int(time.time())})
        return self.recv(4)

    def run(self, iterations=3):
        self.connect()
        ok, resp = self.auth()
        if not ok:
            print(f"[sim] AUTH GAGAL: {resp}")
            return 1
        print(f"[sim] AUTH OK. client={self.client_id} pc={self.pc_id} "
              f"token={str(self.token)[:24]}...")
        for i in range(iterations):
            try:
                pong = self.ping()
                status = self.get_status()
                bill = (status or {}).get("billing", {})
                cmds = bill.get("pending_commands") or []
                print(f"[sim] #{i+1} paket={bill.get('paket_aktif')} "
                      f"sisa={bill.get('time_left')}s "
                      f"total={bill.get('total_biaya')} "
                      f"playing={bill.get('is_playing')} "
                      f"pending={len(cmds)}")
                for c in cmds:
                    print(f"      -> pending command: {c}")
            except Exception as e:
                print(f"[sim] error iterasi {i+1}: {e}")
                break
            time.sleep(5)
        self.sock.close()
        return 0


def main():
    ap = argparse.ArgumentParser(description="Simulasi client warnet (tes koneksi)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--client", default="WARNET_01")
    ap.add_argument("--password", default="admin123")
    ap.add_argument("--pc", default="PC_1")
    ap.add_argument("--iterations", type=int, default=3)
    args = ap.parse_args()
    return SimClient(args.host, args.port, args.client, args.password, args.pc).run(args.iterations)


if __name__ == "__main__":
    sys.exit(main())
