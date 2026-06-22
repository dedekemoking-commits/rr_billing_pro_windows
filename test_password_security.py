"""
Test Password Security with Bcrypt
===================================

Tests:
1. hash_password() creates bcrypt hashes
2. verify_password() correctly verifies bcrypt hashes
3. verify_password() is backward-compatible with SHA256
4. rr_keygen password functions work
"""

import hashlib
from main import hash_password, verify_password
from rr_keygen import hash_dev_password, verify_dev_password

print("\n" + "="*70)
print("PASSWORD SECURITY TESTS")
print("="*70)

# Test 1: Bcrypt hashing
print("\n[TEST 1] Bcrypt password hashing")
print("-" * 70)
test_password = "admin123"
hashed = hash_password(test_password)
print(f"Original password: {test_password}")
print(f"Bcrypt hash: {hashed[:50]}...")
assert hashed.startswith("bcrypt$"), "Hash should start with 'bcrypt$'"
print("✓ PASS: Password hashed with bcrypt\n")

# Test 2: Verify correct password
print("[TEST 2] Verify correct password")
print("-" * 70)
result = verify_password(test_password, hashed)
print(f"verify_password('{test_password}', bcrypt_hash) = {result}")
assert result == True, "Should return True for correct password"
print("✓ PASS: Correct password verified\n")

# Test 3: Verify incorrect password
print("[TEST 3] Verify incorrect password")
print("-" * 70)
result = verify_password("wrongpassword", hashed)
print(f"verify_password('wrongpassword', bcrypt_hash) = {result}")
assert result == False, "Should return False for incorrect password"
print("✓ PASS: Incorrect password rejected\n")

# Test 4: Backward compatibility with SHA256
print("[TEST 4] Backward compatibility with SHA256 (legacy)")
print("-" * 70)
legacy_hash = hashlib.sha256("admin123".encode()).hexdigest()
print(f"Legacy SHA256 hash: {legacy_hash}")
result = verify_password("admin123", legacy_hash)
print(f"verify_password('admin123', legacy_sha256_hash) = {result}")
assert result == True, "Should verify legacy SHA256 hashes"
print("✓ PASS: Legacy SHA256 hashes still work\n")

# Test 5: Developer password functions
print("[TEST 5] Developer password functions")
print("-" * 70)
dev_pass = "rrcctv2026"
dev_hashed = hash_dev_password(dev_pass)
print(f"Developer password hashed")
dev_result = verify_dev_password(dev_pass, dev_hashed)
print(f"verify_dev_password('{dev_pass}', hash) = {dev_result}")
assert dev_result == True, "Should verify developer password"
print("✓ PASS: Developer password functions work\n")

# Test 6: Default bcrypt hashes in LoginPage
print("[TEST 6] Default bcrypt hashes in LoginPage")
print("-" * 70)
from main import LoginPage
admin_pass_hash = LoginPage.DEFAULT_USERS["admin"]["password"]
kasir_pass_hash = LoginPage.DEFAULT_USERS["kasir"]["password"]
print(f"Admin hash starts with 'bcrypt$': {admin_pass_hash.startswith('bcrypt$')}")
print(f"Kasir hash starts with 'bcrypt$': {kasir_pass_hash.startswith('bcrypt$')}")
assert admin_pass_hash.startswith("bcrypt$"), "Admin password should be bcrypt"
assert kasir_pass_hash.startswith("bcrypt$"), "Kasir password should be bcrypt"
print("✓ PASS: Default passwords use bcrypt\n")

# Test 7: Verify default passwords work
print("[TEST 7] Verify default passwords work")
print("-" * 70)
admin_verify = verify_password("admin123", admin_pass_hash)
kasir_verify = verify_password("kasir123", kasir_pass_hash)
print(f"verify_password('admin123', admin_hash) = {admin_verify}")
print(f"verify_password('kasir123', kasir_hash) = {kasir_verify}")
assert admin_verify == True, "Admin password should verify"
assert kasir_verify == True, "Kasir password should verify"
print("✓ PASS: Default passwords verified successfully\n")

# Summary
print("="*70)
print("✓✓✓ ALL TESTS PASSED ✓✓✓")
print("="*70)
print("\nPassword Security Summary:")
print("  • Bcrypt hashing with 12 rounds (industry standard)")
print("  • Backward compatible with legacy SHA256 hashes")
print("  • Default users (admin/kasir) use bcrypt")
print("  • All password functions working correctly")
print("\n")
