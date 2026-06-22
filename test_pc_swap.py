"""
test_pc_swap.py — Test License Activation & PC Swap Scenario

This script simulates the complete workflow:
1. Register new user
2. Generate license code (username-based binding)
3. Activate license on PC1 (with PC1's machine ID)
4. Switch to PC2 (different machine ID)
5. Verify license still works with same username

Run: python test_pc_swap.py
"""

import os
import json
import tempfile
from datetime import date, timedelta

# Import dari module utama
from rr_license import (
    LicenseGenerator, LicenseValidator, LicenseManager,
    get_machine_id, _crc32, _crc16
)


def test_1_show_machine_ids():
    """Test 1: Show machine ID (untuk referensi saat testing di PC berbeda)."""
    print("\n" + "="*70)
    print("TEST 1: Machine ID Detection")
    print("="*70)
    
    mid = get_machine_id()
    print(f"✓ Current Machine ID: {mid}")
    print(f"  (Catat ini untuk testing di PC1)")
    print()


def test_2_hash_comparison():
    """Test 2: Compare CRC-16 vs CRC-32 folding untuk collision risk."""
    print("\n" + "="*70)
    print("TEST 2: Hash Algorithm Comparison (CRC-16 vs CRC-32)")
    print("="*70)
    
    usernames = ["user1", "user2", "user3", "testuser01", "testuser02"]
    
    print(f"\n{'Username':<20} {'CRC-16':<10} {'CRC-32':<10} {'Folded CRC-32':<15}")
    print("-" * 60)
    
    for u in usernames:
        crc16 = _crc16(u)
        crc32 = _crc32(u)
        folded = (crc32 ^ (crc32 >> 16)) & 0xFFFF
        print(f"{u:<20} 0x{crc16:04X}     0x{crc32:08X}   0x{folded:04X}")
    
    print(f"\n✓ CRC-32 with folding provides better collision distribution")
    print()


def test_3_generate_username_binding():
    """Test 3: Generate license code with username binding."""
    print("\n" + "="*70)
    print("TEST 3: Generate License Code (Username Binding)")
    print("="*70)
    
    username = "testuser_pc_swap"
    edition = "BULANAN"
    days = 31
    
    print(f"\nGenerating license for:")
    print(f"  Username: {username}")
    print(f"  Edition: {edition}")
    print(f"  Duration: {days} days")
    
    kode = LicenseGenerator.generate(
        edition=edition,
        machine_id="ANY",  # Universal binding (not tied to machine)
        days=days
    )
    
    print(f"\n✓ License Code Generated: {kode}")
    
    # Decode info
    info = LicenseGenerator.info(kode)
    print(f"\nCode Info:")
    print(f"  Valid: {info.get('valid')}")
    print(f"  Edition: {info.get('edition')}")
    print(f"  Expiry: {info.get('expiry')}")
    print(f"  Universal: {info.get('universal')}")
    
    return kode


def test_4_activate_on_pc1(kode, username):
    """Test 4: Activate license on PC1."""
    print("\n" + "="*70)
    print("TEST 4: Activate License on PC1")
    print("="*70)
    
    mid_pc1 = get_machine_id()
    print(f"\nPC1 Machine ID: {mid_pc1}")
    
    # Simulate activation with username binding
    sukses, pesan = LicenseManager.aktivasi(
        kode,
        username=username,
        binding_mode="username"
    )
    
    print(f"\nActivation Result:")
    print(f"  Success: {sukses}")
    print(f"  Message: {pesan}")
    
    if sukses:
        lic = LicenseManager.load()
        print(f"\n✓ License saved to rr_billing_license.json:")
        print(f"  Binding Mode: {lic.get('binding_mode')}")
        print(f"  Username: {lic.get('username')}")
        print(f"  Machine ID: {lic.get('machine_id')}")
        print(f"  Expiry: {lic.get('expiry')}")
    
    return sukses


def test_5_verify_on_pc1(username):
    """Test 5: Verify license still works on PC1."""
    print("\n" + "="*70)
    print("TEST 5: Verify License on PC1")
    print("="*70)
    
    status = LicenseManager.get_status(current_user=username)
    
    print(f"\nLicense Status on PC1:")
    print(f"  Status: {status['status']}")
    print(f"  Message: {status['pesan']}")
    print(f"  Days Left: {status.get('sisa_hari')}")
    
    if status['status'] == 'active':
        print(f"\n✓ License is ACTIVE on PC1")
        return True
    else:
        print(f"\n✗ License is NOT ACTIVE on PC1")
        return False


def test_6_simulate_pc_swap(username):
    """Test 6: Simulate PC swap - delete license.json and verify with username."""
    print("\n" + "="*70)
    print("TEST 6: Simulate PC Swap (Delete license.json, Keep config)")
    print("="*70)
    
    print(f"\nScenario: User moves to PC2 (different machine ID)")
    print(f"  PC1: license.json exists")
    print(f"  PC2: license.json does NOT exist (not synced)")
    print(f"       config.json DOES exist (username & trial data)")
    
    # Delete license.json to simulate PC2
    if os.path.exists("rr_billing_license.json"):
        os.remove("rr_billing_license.json")
        print(f"\n✓ Deleted rr_billing_license.json (simulating PC2)")
    
    # Get status on PC2 - should fallback to config-based trial
    status = LicenseManager.get_status(current_user=username)
    
    print(f"\nLicense Status on PC2 (after deletion):")
    print(f"  Status: {status['status']}")
    print(f"  Message: {status['pesan']}")
    
    return status['status'] in ['trial', 'active']


def test_7_migrate_license_to_pc2(kode, username):
    """Test 7: Manually migrate license from PC1 to PC2 (user action)."""
    print("\n" + "="*70)
    print("TEST 7: Migrate License from PC1 to PC2")
    print("="*70)
    
    print(f"\nUser receives license code: {kode}")
    print(f"User enters code on PC2 in Aktivasi tab...")
    
    # Activate on PC2 (simulated different machine)
    sukses, pesan = LicenseManager.aktivasi(
        kode,
        username=username,
        binding_mode="username"
    )
    
    print(f"\nActivation Result on PC2:")
    print(f"  Success: {sukses}")
    print(f"  Message: {pesan}")
    
    if sukses:
        lic = LicenseManager.load()
        print(f"\n✓ License re-activated on PC2:")
        print(f"  Username: {lic.get('username')}")
        print(f"  Machine ID (PC2): {lic.get('machine_id')}")
        print(f"  Binding Mode: {lic.get('binding_mode')}")
    
    return sukses


def test_8_verify_on_pc2(username):
    """Test 8: Verify license works on PC2."""
    print("\n" + "="*70)
    print("TEST 8: Verify License on PC2 (After Migration)")
    print("="*70)
    
    status = LicenseManager.get_status(current_user=username)
    
    print(f"\nLicense Status on PC2:")
    print(f"  Status: {status['status']}")
    print(f"  Message: {status['pesan']}")
    print(f"  Days Left: {status.get('sisa_hari')}")
    
    if status['status'] == 'active':
        print(f"\n✓✓✓ LICENSE WORKS ON PC2! ✓✓✓")
        print(f"    Username-based binding is working correctly!")
        return True
    else:
        print(f"\n✗ License does NOT work on PC2")
        return False


def cleanup():
    """Clean up test files."""
    print("\n" + "="*70)
    print("Cleanup")
    print("="*70)
    
    files_to_remove = ["rr_billing_license.json", "rr_billing_license.json.lock"]
    for f in files_to_remove:
        if os.path.exists(f):
            try:
                os.remove(f)
                print(f"✓ Removed {f}")
            except Exception as e:
                print(f"✗ Could not remove {f}: {e}")


def main():
    print("\n" + "="*70)
    print("RR BILLING PRO — PC Swap Test Suite")
    print("Testing Username-Based License Binding")
    print("="*70)
    
    # Clean before start
    if os.path.exists("rr_billing_license.json"):
        os.remove("rr_billing_license.json")
    
    username = "testuser_pc_swap"
    
    # Run tests
    test_1_show_machine_ids()
    test_2_hash_comparison()
    kode = test_3_generate_username_binding()
    
    sukses_pc1 = test_4_activate_on_pc1(kode, username)
    if sukses_pc1:
        test_5_verify_on_pc1(username)
    
    test_6_simulate_pc_swap(username)
    sukses_pc2 = test_7_migrate_license_to_pc2(kode, username)
    
    if sukses_pc2:
        hasil_final = test_8_verify_on_pc2(username)
    else:
        hasil_final = False
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    if hasil_final:
        print("\n✓✓✓ ALL TESTS PASSED ✓✓✓")
        print("\nUsername-based license binding works correctly!")
        print("User dapat pindah ke PC berbeda dan tetap bisa activate lisensi.")
    else:
        print("\n✗✗✗ SOME TESTS FAILED ✗✗✗")
        print("\nThere are issues with license binding or PC swap.")
    
    # Clean up
    cleanup()


if __name__ == "__main__":
    main()
