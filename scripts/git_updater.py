"""
Git-based updater: Pull latest changes dari GitHub dan restart aplikasi.
Ini memungkinkan user untuk update aplikasi langsung dari dalam aplikasi.
"""
import os
import subprocess
import sys
import json
import time
from typing import Tuple, Optional
from datetime import datetime


class GitUpdater:
    """Manager untuk update aplikasi via Git."""
    
    def __init__(self, repo_path: str, remote: str = "origin", branch: str = "master"):
        """
        Args:
            repo_path: Path ke directory repository (root aplikasi)
            remote: Nama remote (default: origin)
            branch: Branch yang di-pull (default: master)
        """
        self.repo_path = repo_path
        self.remote = remote
        self.branch = branch
        self.log_file = os.path.join(repo_path, "update.log")
    
    def _run_git_command(self, cmd: list, timeout: int = 30) -> Tuple[bool, str]:
        """
        Jalankan git command dan return (success, output/error).
        
        Args:
            cmd: List command (e.g., ["git", "pull", "origin", "master"])
            timeout: Timeout dalam detik
            
        Returns:
            (success: bool, message: str)
        """
        try:
            result = subprocess.run(
                cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
            else:
                return False, result.stderr.strip() or result.stdout.strip()
        except subprocess.TimeoutExpired:
            return False, f"Command timeout ({timeout}s)"
        except Exception as e:
            return False, str(e)
    
    def _log(self, msg: str):
        """Log message ke file update.log."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"[{timestamp}] {msg}\n"
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_msg)
        except Exception as e:
            print(f"Log error: {e}")
    
    def _is_git_repository(self) -> bool:
        """Check if the repo_path is a valid git repository."""
        git_dir = os.path.join(self.repo_path, ".git")
        return os.path.isdir(git_dir)
    
    def check_for_updates(self) -> Tuple[bool, str, Optional[dict]]:
        """
        Cek apakah ada update tersedia di remote.
        
        Returns:
            (has_update: bool, message: str, info: dict)
            info contains: local_commit, remote_commit, behind_count, commits_info
        """
        self._log("Checking for updates...")
        
        # Cek apakah ini git repository
        if not self._is_git_repository():
            msg = f"Bukan git repository. App berjalan dari: {self.repo_path}"
            self._log(msg)
            return False, msg, None
        
        # Fetch latest info dari remote
        success, msg = self._run_git_command(
            ["git", "fetch", self.remote, self.branch]
        )
        if not success:
            self._log(f"Fetch failed: {msg}")
            return False, f"Gagal fetch dari {self.remote}: {msg}", None
        
        # Get local commit
        success, local_commit = self._run_git_command(
            ["git", "rev-parse", "HEAD"]
        )
        if not success:
            return False, "Gagal mendapatkan local commit", None
        
        # Get remote commit
        success, remote_commit = self._run_git_command(
            ["git", "rev-parse", f"{self.remote}/{self.branch}"]
        )
        if not success:
            return False, f"Gagal mendapatkan remote commit dari {self.remote}/{self.branch}", None
        
        local_commit = local_commit[:7]
        remote_commit = remote_commit[:7]
        
        if local_commit == remote_commit:
            self._log("Aplikasi sudah up-to-date")
            return False, f"Aplikasi sudah up-to-date (v{local_commit})", {
                "local_commit": local_commit,
                "remote_commit": remote_commit,
                "behind_count": 0
            }
        
        # Get commit count difference
        success, behind = self._run_git_command(
            ["git", "rev-list", "--count", f"HEAD..{self.remote}/{self.branch}"]
        )
        behind_count = int(behind) if success else 0
        
        # Get list of commits yang beda
        success, commits_log = self._run_git_command(
            ["git", "log", "--oneline", f"HEAD..{self.remote}/{self.branch}", "-n", "10"]
        )
        commits_info = commits_log if success else ""
        
        info = {
            "local_commit": local_commit,
            "remote_commit": remote_commit,
            "behind_count": behind_count,
            "commits_info": commits_info
        }
        
        msg = f"Update tersedia: {behind_count} commit(s) di remote ({local_commit} → {remote_commit})"
        self._log(msg)
        return True, msg, info
    
    def pull_updates(self) -> Tuple[bool, str]:
        """
        Pull latest changes dari remote.
        
        Returns:
            (success: bool, message: str)
        """
        self._log(f"Pulling updates dari {self.remote}/{self.branch}...")
        
        # Cek apakah ini git repository
        if not self._is_git_repository():
            msg = f"Bukan git repository. Tidak bisa pull dari: {self.repo_path}"
            self._log(msg)
            return False, msg
        
        # Stash uncommitted changes (local changes dibackup)
        success, stash_msg = self._run_git_command(["git", "stash"])
        if not success:
            self._log(f"Stash warning: {stash_msg}")
        
        # Pull latest
        success, pull_msg = self._run_git_command(
            ["git", "pull", self.remote, self.branch]
        )
        
        if not success:
            self._log(f"Pull failed: {pull_msg}")
            # Restore stash jika ada
            self._run_git_command(["git", "stash", "pop"])
            return False, f"Pull gagal: {pull_msg}"
        
        self._log("Pull successful")
        return True, pull_msg
    
    def get_update_info(self) -> dict:
        """Get info tentang update yang tersedia."""
        has_update, msg, info = self.check_for_updates()
        return {
            "has_update": has_update,
            "message": msg,
            "info": info or {}
        }
    
    def update_and_restart(self, app_exe_path: Optional[str] = None) -> Tuple[bool, str]:
        """
        Pull updates dan restart aplikasi.
        
        Args:
            app_exe_path: Path ke aplikasi executable (untuk restart)
            
        Returns:
            (success: bool, message: str)
        """
        # Pull updates
        success, pull_msg = self.pull_updates()
        if not success:
            return False, pull_msg
        
        self._log("Update successful, restarting application...")
        
        # Restart aplikasi jika exe path provided
        if app_exe_path and os.path.exists(app_exe_path):
            try:
                # Delay kecil supaya log bisa disave
                time.sleep(1)
                
                # Restart
                if sys.platform == "win32":
                    # Windows: gunakan START command
                    subprocess.Popen(
                        f'cmd /c start "" "{app_exe_path}"',
                        shell=True,
                        close_fds=True
                    )
                else:
                    # Unix/Linux/Mac
                    subprocess.Popen(
                        [app_exe_path],
                        close_fds=True
                    )
                
                return True, "Update berhasil! Aplikasi akan restart..."
            except Exception as e:
                self._log(f"Restart error: {e}")
                return False, f"Update berhasil tapi gagal restart: {e}"
        else:
            return True, "Update berhasil! Silakan restart aplikasi secara manual."
    
    def get_current_version(self) -> str:
        """Get current git commit hash (short)."""
        success, commit = self._run_git_command(["git", "rev-parse", "--short", "HEAD"])
        return commit if success else "unknown"
    
    def get_update_log(self, lines: int = 20) -> str:
        """Get last N lines dari update log."""
        try:
            if not os.path.exists(self.log_file):
                return "No update log yet"
            
            with open(self.log_file, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            
            return "".join(all_lines[-lines:])
        except Exception as e:
            return f"Error reading log: {e}"
    
    def get_remote_url(self) -> str:
        """Get remote repository URL."""
        success, url = self._run_git_command(
            ["git", "config", "--get", f"remote.{self.remote}.url"]
        )
        return url if success else "unknown"
