import os
import sys
import threading
import time
from datetime import datetime


class DeployManager:
    """
    Mengelola deploy & update client warnet via SSH.
    
    Flow deploy:
      1. SSH ke client
      2. SCP kirim installer .exe
      3. Execute silent install
      4. Register di config
    
    Flow update:
      1. SSH ke client yang sudah terdaftar
      2. SCP kirim .exe baru
      3. Kill proses lama
      4. Start proses baru
    """

    def __init__(self, ssh_username="Administrator", ssh_password="",
                 ssh_key_file="", ssh_port=22, timeout=30):
        self.ssh_username = ssh_username
        self.ssh_password = ssh_password
        self.ssh_key_file = ssh_key_file
        self.ssh_port = ssh_port
        self.timeout = timeout
        self._results_lock = threading.Lock()
        self.results = []
        self._stop_flag = False

    def _get_ssh(self):
        """Import dan return paramiko. None jika tidak tersedia."""
        try:
            import paramiko
            return paramiko
        except ImportError:
            return None

    def test_connection(self, host):
        """Test SSH connection ke host. Return (bool, message)."""
        paramiko = self._get_ssh()
        if not paramiko:
            return False, "Paramiko tidak tersedia"

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                "hostname": host,
                "port": self.ssh_port,
                "username": self.ssh_username,
                "timeout": self.timeout,
            }
            if self.ssh_key_file:
                connect_kwargs["key_filename"] = self.ssh_key_file
            else:
                connect_kwargs["password"] = self.ssh_password

            client.connect(**connect_kwargs)
            client.close()
            return True, f"SSH OK ke {host}"
        except Exception as e:
            return False, f"SSH gagal: {e}"

    def send_file(self, host, local_path, remote_path):
        """Copy file via SFTP. Return (bool, message)."""
        paramiko = self._get_ssh()
        if not paramiko:
            return False, "Paramiko tidak tersedia"

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                "hostname": host,
                "port": self.ssh_port,
                "username": self.ssh_username,
                "timeout": self.timeout,
            }
            if self.ssh_key_file:
                connect_kwargs["key_filename"] = self.ssh_key_file
            else:
                connect_kwargs["password"] = self.ssh_password

            client.connect(**connect_kwargs)

            sftp = client.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.close()
            client.close()
            return True, f"File terkirim: {os.path.basename(local_path)}"
        except Exception as e:
            return False, f"Gagal kirim file: {e}"

    def exec_command(self, host, command):
        """Execute command via SSH. Return (bool, output)."""
        paramiko = self._get_ssh()
        if not paramiko:
            return False, "Paramiko tidak tersedia"

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                "hostname": host,
                "port": self.ssh_port,
                "username": self.ssh_username,
                "timeout": self.timeout,
            }
            if self.ssh_key_file:
                connect_kwargs["key_filename"] = self.ssh_key_file
            else:
                connect_kwargs["password"] = self.ssh_password

            client.connect(**connect_kwargs)

            stdin, stdout, stderr = client.exec_command(command, timeout=self.timeout)
            output = stdout.read().decode("utf-8", errors="replace")
            error = stderr.read().decode("utf-8", errors="replace")
            client.close()

            if error and not output:
                return False, error
            return True, output or error
        except Exception as e:
            return False, str(e)

    def deploy_single(self, host, exe_path, remote_dir="C:\\RRBillingClient", app_name="RRBILLINGCLIENT.exe"):
        """Deploy client app ke satu PC via SSH.
        
        Args:
            host: IP client PC
            exe_path: Path lokal ke file .exe yang akan di-deploy
            remote_dir: Direktori tujuan di client PC
            app_name: Nama file .exe di client
        
        Returns:
            dict: {"host": str, "success": bool, "message": str}
        """
        steps = []

        # 1. Test koneksi
        ok, msg = self.test_connection(host)
        if not ok:
            return {"host": host, "success": False, "message": msg, "steps": steps + [("test", False, msg)]}
        steps.append(("test", True, msg))

        # 2. Buat direktori remote
        ok, msg = self.exec_command(host, f'if not exist "{remote_dir}" mkdir "{remote_dir}"')
        steps.append(("mkdir", ok, msg))

        # 3. Kirim file
        remote_path = f"{remote_dir}\\{app_name}"
        ok, msg = self.send_file(host, exe_path, remote_path)
        if not ok:
            return {"host": host, "success": False, "message": msg, "steps": steps}
        steps.append(("send_file", True, msg))

        # 4. Copy file pendukung (logo, config template)
        base_dir = os.path.dirname(exe_path)
        for extra in ["logo.png", "lock_screen.jpg"]:
            extra_path = os.path.join(base_dir, extra)
            if os.path.exists(extra_path):
                self.send_file(host, extra_path, f"{remote_dir}\\{extra}")

        # 5. Buat shortcut startup (opsional)
        startup_script = (
            f'powershell -Command "$WS = New-Object -ComObject WScript.Shell; '
            f'$SC = $WS.CreateShortcut(\'$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\{app_name}.lnk\'); '
            f'$SC.TargetPath = \'{remote_dir}\\{app_name}\'; $SC.Save()"'
        )
        ok, msg = self.exec_command(host, startup_script)
        steps.append(("shortcut", ok, msg))

        # 6. Create desktop shortcut
        desktop_script = (
            f'powershell -Command "$WS = New-Object -ComObject WScript.Shell; '
            f'$SC = $WS.CreateShortcut(\'$env:PUBLIC\\Desktop\\{app_name}.lnk\'); '
            f'$SC.TargetPath = \'{remote_dir}\\{app_name}\'; $SC.Save()"'
        )
        self.exec_command(host, desktop_script)

        return {
            "host": host,
            "success": True,
            "message": f"Deploy selesai ke {host}",
            "steps": steps,
        }

    def update_single(self, host, exe_path, remote_dir="C:\\RRBillingClient", app_name="RRBILLINGCLIENT.exe"):
        """Update client app di satu PC via SSH.
        
        Returns:
            dict: {"host": str, "success": bool, "message": str}
        """
        steps = []

        ok, msg = self.test_connection(host)
        if not ok:
            return {"host": host, "success": False, "message": msg, "steps": steps}
        steps.append(("test", True, msg))

        # Kill proses lama
        ok, msg = self.exec_command(host, f'taskkill /f /im {app_name} 2>nul')
        steps.append(("kill", True, "Proses lama dihentikan"))

        # Kirim file baru
        remote_path = f"{remote_dir}\\{app_name}"
        ok, msg = self.send_file(host, exe_path, remote_path)
        if not ok:
            return {"host": host, "success": False, "message": msg, "steps": steps}
        steps.append(("send_file", True, msg))

        # Start aplikasi baru
        ok, msg = self.exec_command(host, f'start "" "{remote_path}"')
        steps.append(("start", ok, msg if ok else "Aplikasi akan start manual atau saat login ulang"))

        return {
            "host": host,
            "success": True,
            "message": f"Update selesai ke {host}",
            "steps": steps,
        }

    def deploy_multi(self, hosts, exe_path, max_parallel=10, progress_callback=None):
        """Deploy ke banyak PC secara paralel.
        
        Args:
            hosts: list of IP strings
            exe_path: path ke .exe
            max_parallel: max thread paralel
            progress_callback: callable(completed, total, result)
        
        Returns:
            list[dict]: hasil tiap PC
        """
        self.results = []
        self._stop_flag = False
        threads = []
        completed = 0
        total = len(hosts)

        def _deploy_one(host):
            result = self.deploy_single(host, exe_path)
            with self._results_lock:
                self.results.append(result)
                nonlocal completed
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, result)

        for host in hosts:
            if self._stop_flag:
                break
            t = threading.Thread(target=_deploy_one, args=(host,), daemon=True)
            threads.append(t)

            if len(threads) >= max_parallel:
                for th in threads:
                    th.start()
                for th in threads:
                    th.join()
                threads = []

        if threads:
            for th in threads:
                th.start()
            for th in threads:
                th.join()

        return sorted(self.results, key=lambda x: (not x["success"], x["host"]))

    def update_multi(self, hosts, exe_path, max_parallel=10, progress_callback=None):
        """Update ke banyak PC secara paralel."""
        self.results = []
        self._stop_flag = False
        threads = []
        completed = 0
        total = len(hosts)

        def _update_one(host):
            result = self.update_single(host, exe_path)
            with self._results_lock:
                self.results.append(result)
                nonlocal completed
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, result)

        for host in hosts:
            if self._stop_flag:
                break
            t = threading.Thread(target=_update_one, args=(host,), daemon=True)
            threads.append(t)

            if len(threads) >= max_parallel:
                for th in threads:
                    th.start()
                for th in threads:
                    th.join()
                threads = []

        if threads:
            for th in threads:
                th.start()
            for th in threads:
                th.join()

        return sorted(self.results, key=lambda x: (not x["success"], x["host"]))

    def stop(self):
        """Hentikan semua operasi."""
        self._stop_flag = True


def register_client(host, client_id, pc_id, nama_kursi, nama_grup="Warnet", config_path=None):
    """
    Daftarkan PC client ke rr_billing_config.json.
    
    Args:
        host: IP client
        client_id: WARNET_XX
        pc_id: PC_XX  
        nama_kursi: Nama kursi display
        nama_grup: Grup tarif
        config_path: Path ke config file (None = default)
    
    Returns:
        bool: True jika berhasil
    """
    import json

    if config_path is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base, "rr_billing_config.json")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return False

    warnet_clients = cfg.get("warnet_clients", [])
    
    # Cari atau buat client entry
    client_entry = None
    for c in warnet_clients:
        if c.get("client_id") == client_id:
            client_entry = c
            break

    if client_entry is None:
        import hashlib
        dummy_hash = hashlib.sha256("default123".encode()).hexdigest()
        client_entry = {
            "client_id": client_id,
            "password_hash": dummy_hash,
            "location": f"Warnet {client_id}",
            "pcs": [],
            "allowed_actions": ["ON", "OFF", "VOL+", "VOL-"],
            "created_at": datetime.now().isoformat(),
            "tokens": [],
        }
        warnet_clients.append(client_entry)

    # Cek duplikat PC
    for pc in client_entry.get("pcs", []):
        if pc.get("ip") == host or pc.get("pc_id") == pc_id:
            return True  # Already registered

    max_existing = 0
    for pc in client_entry.get("pcs", []):
        pid = pc.get("pc_id", "PC_0")
        try:
            num = int(pid.replace("PC_", ""))
            if num > max_existing:
                max_existing = num
        except ValueError:
            pass

    new_pc = {
        "pc_id": pc_id or f"PC_{max_existing + 1}",
        "ip": host,
        "adb_port": 5555,
        "name": nama_kursi or f"Kursi {max_existing + 1}",
    }
    client_entry["pcs"].append(new_pc)
    cfg["warnet_clients"] = warnet_clients

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    print("Deploy Manager Test")
    print("=" * 50)

    dm = DeployManager(ssh_username="Administrator", ssh_password="admin123")

    def progress(done, total, result):
        icon = "✅" if result["success"] else "❌"
        print(f"  {icon} [{done}/{total}] {result['host']}: {result['message']}")

    # Test scan dulu
    from scripts.network_scanner import NetworkScanner
    scanner = NetworkScanner(timeout=1)
    print("Scanning network...")
    scan_results = scanner.scan_quick()

    ssh_hosts = [r["ip"] for r in scan_results]
    if not ssh_hosts:
        print("Tidak ada perangkat ditemukan.")
        sys.exit(0)

    print(f"Ditemukan {len(ssh_hosts)} perangkat:")
    for h in ssh_hosts[:10]:
        print(f"  {h}")

    # Deploy test
    # exe_path = r"C:\Aplikasi VSC\BillingPSkuDesktop\dist\RRBILLINGCLIENT.exe"
    # if os.path.exists(exe_path):
    #     print(f"\nDeploy ke {len(ssh_hosts)} PC...")
    #     results = dm.deploy_multi(ssh_hosts, exe_path, progress_callback=progress)
    #     print("\nHasil:")
    #     for r in results:
    #         print(f"  {'✅' if r['success'] else '❌'} {r['host']}: {r['message']}")
    # else:
    #     print(f"\nFile {exe_path} tidak ditemukan. Buat build dulu.")
