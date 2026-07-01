"""
Auto-Update Module untuk RR Billing Pro
- Check update dari GitHub releases
- Download latest release zip
- Extract dan pasang update otomatis
- Restart aplikasi tanpa perlu install EXE baru
"""

import os
import json
import zipfile
import shutil
import urllib.request
import urllib.error
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional, Callable, Tuple


def _subprocess_no_window_kwargs() -> dict:
    if os.name != "nt":
        return {}
    kwargs = {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags
    startup_cls = getattr(subprocess, "STARTUPINFO", None)
    if startup_cls is not None:
        startupinfo = startup_cls()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    return kwargs


class AutoUpdater:
    """Auto-update manager untuk aplikasi RR Billing Pro."""
    
    def __init__(self, app_dir: str, version: str = "v2.2.3"):
        self.app_dir = app_dir
        self.current_version = version
        self.github_repo = "dedekemoking-commits/rr_billing_pro_windows"
        self.github_api_url = f"https://api.github.com/repos/{self.github_repo}/releases/latest"
        self.update_log_file = os.path.join(app_dir, "update.log")
        self.update_backup_dir = os.path.join(app_dir, "backups", "auto_update")
        
    def check_for_updates(self) -> dict:
        """
        Check untuk update terbaru di GitHub.
        Return: {
            'update_available': bool,
            'current_version': str,
            'latest_version': str,
            'download_url': str,
            'message': str,
            'changelog': str
        }
        """
        try:
            # Fetch latest release dari GitHub
            with urllib.request.urlopen(self.github_api_url, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            latest_version = data.get('tag_name', 'unknown').lstrip('v')
            current_version = self.current_version.lstrip('v')
            changelog = data.get('body', 'Tidak ada changelog')
            
            # Cari download URL untuk source code zip
            download_url = None
            for asset in data.get('assets', []):
                if asset['name'].endswith('.zip'):
                    download_url = asset['browser_download_url']
                    break
            
            if not download_url:
                # Fallback: use zipball URL
                download_url = data.get('zipball_url', '')
            
            # Compare versi
            update_available = self._compare_versions(current_version, latest_version)
            
            return {
                'update_available': update_available,
                'current_version': self.current_version,
                'latest_version': f"v{latest_version}",
                'download_url': download_url,
                'changelog': changelog,
                'message': f"Versi terbaru: {latest_version}" if update_available else f"Sudah versi terbaru ({self.current_version})"
            }
        
        except urllib.error.URLError as e:
            return {
                'update_available': False,
                'current_version': self.current_version,
                'latest_version': 'unknown',
                'download_url': '',
                'changelog': '',
                'message': f"Tidak dapat koneksi ke GitHub: {e.reason}"
            }
        except Exception as e:
            return {
                'update_available': False,
                'current_version': self.current_version,
                'latest_version': 'unknown',
                'download_url': '',
                'changelog': '',
                'message': f"Error cek update: {str(e)}"
            }
    
    def download_update(self, url: str, progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """
        Download update zip dari URL.
        Return: (success: bool, file_path: str atau error_message: str)
        """
        try:
            # Create temp directory
            temp_dir = tempfile.mkdtemp(prefix='rr_update_')
            zip_path = os.path.join(temp_dir, 'update.zip')
            
            # Download dengan progress tracking
            def download_hook(block_num, block_size, total_size):
                if total_size > 0 and progress_callback:
                    percent = min(100, (block_num * block_size * 100) / total_size)
                    progress_callback(percent)
            
            urllib.request.urlretrieve(url, zip_path, hook=download_hook)
            
            # Verify file exists dan tidak kosong
            if not os.path.exists(zip_path) or os.path.getsize(zip_path) == 0:
                return False, "File download kosong atau gagal"
            
            # Log download
            self._log_update(f"✓ Download update sukses: {zip_path}")
            return True, zip_path
        
        except Exception as e:
            return False, f"Error download update: {str(e)}"
    
    def install_update(self, zip_path: str, progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """
        Install update dari zip file.
        Return: (success: bool, message: str)
        """
        try:
            # Create backup dari current app
            if progress_callback:
                progress_callback(10, "📦 Membuat backup...")
            
            backup_path = self._create_backup()
            if not backup_path:
                self._log_update("⚠ Warning: Tidak dapat membuat backup (lanjut tanpa backup)")
            else:
                self._log_update(f"✓ Backup berhasil: {backup_path}")
            
            # Extract zip
            if progress_callback:
                progress_callback(30, "📂 Mengekstrak file...")
            
            temp_extract = os.path.join(tempfile.gettempdir(), 'rr_extract')
            if os.path.exists(temp_extract):
                shutil.rmtree(temp_extract)
            os.makedirs(temp_extract)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_extract)
            
            # Find main.py dan scripts folder di extracted files
            # GitHub zipball membuat folder dengan repo-branch name
            extracted_items = os.listdir(temp_extract)
            if extracted_items:
                repo_folder = os.path.join(temp_extract, extracted_items[0])
            else:
                repo_folder = temp_extract
            
            # Copy files dari extracted ke app_dir
            if progress_callback:
                progress_callback(50, "📋 Menyalin file aplikasi...")
            
            files_to_copy = ['main.py', 'scripts', 'rr_crypto.py', 'rr_user_manager.py', 
                             'rr_license.py', 'rr_keygen.py', 'logo.png']
            
            for item in files_to_copy:
                src = os.path.join(repo_folder, item)
                dst = os.path.join(self.app_dir, item)
                
                if os.path.exists(src):
                    if os.path.isdir(src):
                        # Remove old dir if exists
                        if os.path.exists(dst):
                            shutil.rmtree(dst)
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                    self._log_update(f"✓ Copied: {item}")
            
            # Clean up
            if progress_callback:
                progress_callback(80, "🧹 Membersihkan...")
            
            shutil.rmtree(temp_extract, ignore_errors=True)
            os.remove(zip_path)
            
            if progress_callback:
                progress_callback(100, "✅ Update siap dipasang!")
            
            self._log_update("✓ Update install sukses - siap restart aplikasi")
            return True, "Update berhasil dipasang! Aplikasi akan restart..."
        
        except Exception as e:
            self._log_update(f"✗ Error install update: {str(e)}")
            return False, f"Error install update: {str(e)}"
    
    def restart_app(self) -> bool:
        """Restart aplikasi setelah update."""
        try:
            # Get main.py path
            main_py = os.path.join(self.app_dir, 'main.py')
            
            if not os.path.exists(main_py):
                self._log_update("✗ main.py tidak ditemukan, tidak bisa restart")
                return False
            
            # Restart using Python
            import sys
            
            # On Windows
            if sys.platform == 'win32':
                subprocess.Popen(
                    [sys.executable, main_py],
                    cwd=self.app_dir,
                    close_fds=True,
                    **_subprocess_no_window_kwargs()
                )
            else:
                # On Unix/Linux
                subprocess.Popen([sys.executable, main_py], cwd=self.app_dir, close_fds=True)
            
            self._log_update("✓ Restart command sent")
            return True
        
        except Exception as e:
            self._log_update(f"✗ Error restart: {str(e)}")
            return False
    
    def _compare_versions(self, current: str, latest: str) -> bool:
        """Compare versi. Return True jika ada update."""
        try:
            # Simple version comparison (v2.2.3 vs v2.2.4)
            curr_parts = [int(x) for x in current.split('.')]
            latest_parts = [int(x) for x in latest.split('.')]
            
            # Pad dengan zeros
            while len(curr_parts) < len(latest_parts):
                curr_parts.append(0)
            while len(latest_parts) < len(curr_parts):
                latest_parts.append(0)
            
            return tuple(latest_parts) > tuple(curr_parts)
        except Exception:
            # Jika parse error, asumsikan ada update
            return latest != current
    
    def _create_backup(self) -> Optional[str]:
        """Create backup dari current app files."""
        try:
            os.makedirs(self.update_backup_dir, exist_ok=True)
            
            # Create timestamped backup
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(self.update_backup_dir, f"backup_{timestamp}")
            
            # Backup key files
            os.makedirs(backup_path, exist_ok=True)
            
            files_to_backup = ['main.py', 'rr_crypto.py', 'rr_user_manager.py', 'rr_license.py']
            for file in files_to_backup:
                src = os.path.join(self.app_dir, file)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(backup_path, file))
            
            # Backup scripts folder
            src_scripts = os.path.join(self.app_dir, 'scripts')
            if os.path.exists(src_scripts):
                shutil.copytree(src_scripts, os.path.join(backup_path, 'scripts'), 
                               dirs_exist_ok=True)
            
            return backup_path
        
        except Exception as e:
            self._log_update(f"Backup error: {e}")
            return None
    
    def _log_update(self, message: str):
        """Log update activity."""
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] {message}\n"
            
            with open(self.update_log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as e:
            print(f"Log error: {e}")
    
    def get_update_history(self, limit: int = 20) -> list:
        """Get recent update history."""
        try:
            if not os.path.exists(self.update_log_file):
                return []
            
            with open(self.update_log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            return lines[-limit:] if limit else lines
        except Exception:
            return []


# Convenience function untuk digunakan di main.py
def auto_check_and_update(app_dir: str, version: str, progress_callback: Optional[Callable] = None) -> dict:
    """One-shot auto-update dengan all steps."""
    updater = AutoUpdater(app_dir, version)
    return {
        'updater': updater,
        'check': updater.check_for_updates
    }
