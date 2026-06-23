#!/usr/bin/env python3
"""
Test Git update feature untuk memastikan error handling bekerja dengan baik.
"""

import os
import sys

# Add scripts folder to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.git_updater import GitUpdater

def test_from_repo():
    """Test dari repo folder (punya .git)"""
    print("\n=== Test 1: Dari repo folder (punya .git) ===")
    repo_path = os.path.dirname(os.path.abspath(__file__))
    updater = GitUpdater(repo_path)
    
    has_update, msg, info = updater.check_for_updates()
    print(f"Has update: {has_update}")
    print(f"Message: {msg}")
    if info:
        print(f"Info: {info}")

def test_from_dist():
    """Test dari dist folder (punya .git sekarang)"""
    print("\n=== Test 2: Dari dist folder (punya .git sekarang) ===")
    dist_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")
    if not os.path.exists(dist_path):
        print("dist folder tidak ditemukan")
        return
        
    updater = GitUpdater(dist_path)
    has_update, msg, info = updater.check_for_updates()
    print(f"Has update: {has_update}")
    print(f"Message: {msg}")
    if info:
        print(f"Info: {info}")

def test_from_nonrepo():
    """Test dari folder yang bukan repository"""
    print("\n=== Test 3: Dari folder bukan repository ===")
    nonrepo_path = "C:\\Windows\\Temp"
    
    updater = GitUpdater(nonrepo_path)
    has_update, msg, info = updater.check_for_updates()
    print(f"Has update: {has_update}")
    print(f"Message: {msg}")
    if info:
        print(f"Info: {info}")

if __name__ == "__main__":
    try:
        test_from_repo()
    except Exception as e:
        print(f"Error test 1: {e}")
    
    try:
        test_from_dist()
    except Exception as e:
        print(f"Error test 2: {e}")
    
    try:
        test_from_nonrepo()
    except Exception as e:
        print(f"Error test 3: {e}")
    
    print("\n✓ Semua test selesai")
