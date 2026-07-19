#!/usr/bin/env python3
"""
Rebuild both RRBILLINGPRO.exe and RRBILLINGCLIENT.exe
"""
import subprocess
import sys
import os
from datetime import datetime

os.chdir(r"c:\Aplikasi VSC\BillingPSkuDesktop")

def rebuild_app(spec_file, app_name):
    print(f"\n{'='*60}")
    print(f"Rebuilding {app_name}...")
    print(f"{'='*60}")
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    cmd = [sys.executable, "-m", "PyInstaller", spec_file, "--clean", "-y"]
    print(f"Running: {' '.join(cmd)}\n")
    
    result = subprocess.run(cmd, capture_output=False, text=True)
    
    print(f"\nEnd time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Exit code: {result.returncode}")
    
    if result.returncode == 0:
        print(f"[OK] {app_name} build completed successfully")
    else:
        print(f"[FAIL] {app_name} build failed with exit code {result.returncode}")
    
    return result.returncode == 0

def main():
    print("RR Billing Pro - EXE Rebuild Script")
    print("="*60)
    
    # Rebuild RRBILLINGPRO.exe
    success1 = rebuild_app("RRBILLINGPRO.spec", "RRBILLINGPRO.exe")
    
    # Rebuild RRBILLINGCLIENT.exe
    success2 = rebuild_app("RRBILLINGCLIENT.spec", "RRBILLINGCLIENT.exe")
    
    print(f"\n{'='*60}")
    print("REBUILD SUMMARY")
    print(f"{'='*60}")
    print(f"RRBILLINGPRO.exe:  {'SUCCESS' if success1 else 'FAILED'}")
    print(f"RRBILLINGCLIENT.exe: {'SUCCESS' if success2 else 'FAILED'}")

    if success1 and success2:
        print("\nAll builds completed successfully!")
        return 0
    else:
        print("\nOne or more builds failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
