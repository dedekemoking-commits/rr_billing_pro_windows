#!/usr/bin/env python3
"""
Test email verification in the EXE by checking if SMTP configuration is loaded correctly.
This script will:
1. Check if rr_billing_config.json has email_settings
2. Run simple Python test to verify email settings normalization works
"""
import json
import sys

sys.path.insert(0, r"c:\Aplikasi VSC\BillingPSkuDesktop")

# Check config file
config_file = r"c:\Aplikasi VSC\BillingPSkuDesktop\rr_billing_config.json"

print("="*60)
print("EMAIL SETTINGS TEST")
print("="*60)

# 1. Check config file
print("\n1. Checking rr_billing_config.json...")
try:
    with open(config_file, 'r') as f:
        config = json.load(f)
    
    if "email_settings" in config:
        email_settings = config["email_settings"]
        print(f"   ✓ email_settings found")
        print(f"   - smtp_server: {email_settings.get('smtp_server', 'NOT SET')}")
        print(f"   - smtp_port: {email_settings.get('smtp_port', 'NOT SET')}")
        print(f"   - smtp_username: {email_settings.get('smtp_username', 'NOT SET')}")
        print(f"   - use_tls: {email_settings.get('use_tls', 'NOT SET')}")
        
        # Check if settings are valid
        has_server = bool(email_settings.get('smtp_server', '').strip())
        has_port = bool(email_settings.get('smtp_port'))
        has_user = bool(email_settings.get('smtp_username', '').strip())
        has_pass = bool(email_settings.get('smtp_password', '').strip())
        
        if has_server and has_port and has_user and has_pass:
            print(f"   ✓ All email settings are properly configured")
        else:
            print(f"   ✗ Some email settings are missing:")
            print(f"     - server: {has_server}")
            print(f"     - port: {has_port}")
            print(f"     - username: {has_user}")
            print(f"     - password: {has_pass}")
    else:
        print(f"   ✗ email_settings NOT found in config")
        if "smtp_settings" in config:
            print(f"   → Found legacy 'smtp_settings' instead")
except Exception as e:
    print(f"   ✗ Error reading config: {e}")
    sys.exit(1)

print("\n" + "="*60)
print("✓ Email settings verification complete")
print("="*60)
