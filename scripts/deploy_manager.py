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

    # ════════════════════════════════════════════════════════════════════
    #  DEPLOY PAKET CLIENT WARNET (3 exe + config + installer)
    # ════════════════════════════════════════════════════════════════════
    #  Urutan aman (pengganti copy manual):
    #   1. stop service RRBillingClientService
    #   2. taskkill tray (BillingClientApp) + lock UI (BillingLockScreenUI)
    #   3. copy 3 exe + INSTALL_CLIENT.bat (+ config jika --keep-config tidak dipakai)
    #   4. install ulang service (jika perlu) + net start
    #   5. start tray app (jika belum jalan)
    # ════════════════════════════════════════════════════════════════════

    PKG_FILES = ["BillingClientService.exe", "BillingLockScreenUI.exe",
                 "BillingClientApp.exe", "INSTALL_CLIENT.bat"]
    LOGO_FILES = ["lockscreen_logo.png", "lockscreen_logo.jpg", "lockscreen_logo.jpeg"]
    SERVICE_NAME = "RRBillingClientService"

    def deploy_package(self, host, pkg_dir, remote_dir="C:\\RRBillingClient",
                       keep_config=False, start_tray=True):
        """Deploy paket client lengkap ke satu PC via SSH.

        Args:
            host: IP client PC
            pkg_dir: Folder lokal berisi 3 exe + INSTALL_CLIENT.bat (+ config opsional)
            remote_dir: Direktori tujuan di client PC
            keep_config: True = JANGAN timpa rr_billing_config.json yang ada di client
            start_tray: True = jalankan BillingClientApp.exe setelah selesai

        Returns:
            dict: {"host": str, "success": bool, "message": str, "steps": list}
        """
        steps = []

        # 0. Validasi paket (logo bersifat opsional — tidak wajib ada)
        missing = [f for f in self.PKG_FILES
                   if not os.path.isfile(os.path.join(pkg_dir, f))]
        if missing:
            return {"host": host, "success": False,
                    "message": f"Paket tidak lengkap: {', '.join(missing)}", "steps": []}
        logo_available = [f for f in self.LOGO_FILES
                          if os.path.isfile(os.path.join(pkg_dir, f))]

        # 1. Test koneksi
        ok, msg = self.test_connection(host)
        if not ok:
            return {"host": host, "success": False, "message": msg, "steps": []}
        steps.append(("test", True, msg))

        # 2. Stop service + kill proses lama (tray, lock UI)
        stop_cmd = (f'net stop {self.SERVICE_NAME} 2>nul & '
                    f'taskkill /f /im BillingClientApp.exe 2>nul & '
                    f'taskkill /f /im BillingLockScreenUI.exe 2>nul & '
                    f'timeout /t 2 /nobreak >nul & exit /b 0')
        self.exec_command(host, stop_cmd)
        steps.append(("stop", True, "Service & proses client dihentikan"))

        # 3. Buat direktori remote
        self.exec_command(host, f'if not exist "{remote_dir}" mkdir "{remote_dir}"')

        # 4. Kirim 3 exe + installer
        sent_ok = True
        for fname in self.PKG_FILES:
            ok, msg = self.send_file(host,
                                     os.path.join(pkg_dir, fname),
                                     f"{remote_dir}\\{fname}")
            if not ok:
                sent_ok = False
                steps.append(("send_file", False, f"{fname}: {msg}"))
                break
            steps.append(("send_file", True, f"{fname} terkirim"))
        if not sent_ok:
            return {"host": host, "success": False, "message": "Gagal kirim file", "steps": steps}

        # 5. Kirim config (kecuali keep_config / tidak ada di paket)
        cfg_local = os.path.join(pkg_dir, "rr_billing_config.json")
        if not keep_config and os.path.isfile(cfg_local):
            ok, msg = self.send_file(host, cfg_local, f"{remote_dir}\\rr_billing_config.json")
            if not ok:
                steps.append(("send_file", False, f"config: {msg}"))
            else:
                steps.append(("send_file", True, "rr_billing_config.json terkirim"))

        # 5b. Kirim logo lockscreen (opsional — salah satu format saja yang ada)
        for fname in logo_available:
            ok, msg = self.send_file(host,
                                     os.path.join(pkg_dir, fname),
                                     f"{remote_dir}\\{fname}")
            steps.append(("send_file_logo", ok, f"{fname} terkirim" if ok else f"{fname}: {msg}"))

        # 6. Instal service (idempotent: hapus dulu jika ada, pasang lagi)
        svc_exe = f'"{remote_dir}\\BillingClientService.exe"'
        install_cmd = (f'net stop {self.SERVICE_NAME} 2>nul & '
                       f'{svc_exe} -u 2>nul & '
                       f'{svc_exe} -i & '
                       f'net start {self.SERVICE_NAME}')
        ok, msg = self.exec_command(host, install_cmd)
        steps.append(("install_svc", ok, "Service dipasang & dijalankan" if ok else msg))
        if not ok:
            return {"host": host, "success": False,
                    "message": f"Install service gagal: {msg}", "steps": steps}

        # 7. Jalankan tray app (jika belum jalan)
        if start_tray:
            tray_cmd = (f'tasklist /fi "IMAGENAME eq BillingClientApp.exe" '
                        f'2>nul | findstr /i "BillingClientApp.exe" >nul || '
                        f'start "" "{remote_dir}\\BillingClientApp.exe"')
            self.exec_command(host, tray_cmd)
            steps.append(("start_tray", True, "Tray app dijalankan"))

        return {
            "host": host,
            "success": True,
            "message": f"Paket client ter-deploy ke {host}",
            "steps": steps,
        }

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
