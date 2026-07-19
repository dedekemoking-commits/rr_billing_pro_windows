import ipaddress
import socket
import subprocess
import threading
import time
from datetime import datetime


class NetworkScanner:
    """Scan subnet untuk menemukan IP aktif dan cek port SSH."""

    def __init__(self, timeout=2, max_threads=50):
        self.timeout = timeout
        self.max_threads = max_threads
        self.results = []
        self._lock = threading.Lock()
        self._stop_flag = False

    def detect_subnet(self):
        """Deteksi subnet lokal dari IP pertama yang valid."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
            parts = local_ip.split(".")
            return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
        except Exception:
            return "192.168.1.0/24"

    def ping(self, ip):
        """Ping satu IP, return True jika reachable."""
        try:
            startupinfo = None
            if hasattr(subprocess, "STARTUPINFO"):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            out = subprocess.run(
                ["ping", "-n", "1", "-w", str(self.timeout * 1000), ip],
                capture_output=True, text=True, timeout=self.timeout + 1,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            return out.returncode == 0
        except Exception:
            return False

    def check_port(self, ip, port=22):
        """Cek apakah port terbuka di IP."""
        try:
            with socket.create_connection((ip, port), timeout=self.timeout):
                return True
        except Exception:
            return False

    def get_hostname(self, ip):
        """Coba resolve hostname dari IP."""
        try:
            name, _, _ = socket.gethostbyaddr(ip)
            return name
        except Exception:
            return ip

    def _scan_worker(self, ip):
        """Thread worker untuk scan satu IP."""
        if self._stop_flag:
            return

        alive = self.ping(ip)
        if not alive:
            return

        ssh_open = self.check_port(ip, 22)
        hostname = self.get_hostname(ip)

        with self._lock:
            self.results.append({
                "ip": ip,
                "hostname": hostname,
                "ssh_available": ssh_open,
                "timestamp": datetime.now().isoformat(),
            })

    def scan(self, subnet=None, progress_callback=None):
        """
        Scan subnet untuk IP aktif.
        
        Args:
            subnet: CIDR subnet (e.g., "192.168.1.0/24"). Auto-detect jika None.
            progress_callback: callable(completed, total) untuk progress.
        
        Returns:
            list[dict]: [{"ip": "...", "hostname": "...", "ssh_available": bool}, ...]
        """
        if subnet is None:
            subnet = self.detect_subnet()

        self.results = []
        self._stop_flag = False

        try:
            network = ipaddress.IPv4Network(subnet, strict=False)
        except Exception:
            return []

        hosts = list(network.hosts())
        total = len(hosts)
        completed = 0
        threads = []

        for host in hosts:
            ip = str(host)
            t = threading.Thread(target=self._scan_worker, args=(ip,), daemon=True)
            threads.append(t)

            if len(threads) >= self.max_threads:
                for th in threads:
                    th.start()
                for th in threads:
                    th.join()
                completed += len(threads)
                if progress_callback:
                    progress_callback(completed, total)
                threads = []

        if threads:
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            completed += len(threads)
            if progress_callback:
                progress_callback(completed, total)

        # Sort: SSH available first, then by IP
        self.results.sort(key=lambda x: (not x["ssh_available"], [int(p) for p in x["ip"].split(".")]))
        return self.results

    def scan_quick(self, subnet=None, progress_callback=None):
        """
        Quick scan: cuma ping, tanpa port check. Lebih cepat.
        """
        if subnet is None:
            subnet = self.detect_subnet()

        self.results = []
        self._stop_flag = False

        try:
            network = ipaddress.IPv4Network(subnet, strict=False)
        except Exception:
            return []

        hosts = list(network.hosts())
        total = len(hosts)
        completed = 0
        threads = []

        for host in hosts:
            ip = str(host)
            t = threading.Thread(target=lambda ip=ip: self._ping_only(ip), daemon=True)
            threads.append(t)

            if len(threads) >= self.max_threads:
                for th in threads:
                    th.start()
                for th in threads:
                    th.join()
                completed += len(threads)
                if progress_callback:
                    progress_callback(completed, total)
                threads = []

        if threads:
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            completed += len(threads)
            if progress_callback:
                progress_callback(completed, total)

        self.results.sort(key=lambda x: [int(p) for p in x["ip"].split(".")])
        return self.results

    def _ping_only(self, ip):
        if self._stop_flag:
            return
        if self.ping(ip):
            with self._lock:
                self.results.append({
                    "ip": ip,
                    "hostname": self.get_hostname(ip),
                    "ssh_available": False,
                })

    def stop(self):
        """Hentikan scan yang sedang berjalan."""
        self._stop_flag = True


if __name__ == "__main__":
    scanner = NetworkScanner(timeout=1)
    print("Scanning subnet...")
    
    def progress(done, total):
        print(f"  Progress: {done}/{total}", end="\r")

    results = scanner.scan(progress_callback=progress)
    print(f"\n\nDitemukan {len(results)} perangkat aktif:")
    print(f"{'IP':<18} {'Hostname':<30} {'SSH':<6}")
    print("-" * 55)
    for r in results:
        ssh = "✅" if r["ssh_available"] else "❌"
        print(f"{r['ip']:<18} {r['hostname']:<30} {ssh:<6}")
