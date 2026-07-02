#!/usr/bin/env python3
"""
Test script to verify email functionality works in the rebuilt EXE
This tests the email verification code by importing functions from main.py
"""
import sys
import json
import os

# Add path to import from main.py
sys.path.insert(0, r"c:\Aplikasi VSC\BillingPSkuDesktop")

# Import the functions we need from main.py
try:
    from main import _get_email_settings, _email_configured, _normalize_email_settings, DEFAULT_EMAIL_SETTINGS
    print("✓ Successfully imported email functions from main.py")
except ImportError as e:
    print(f"✗ Failed to import: {e}")
    sys.exit(1)

print("\n" + "="*60)
print("EMAIL SETTINGS VERIFICATION TEST")
print("="*60)

# Test 1: Check DEFAULT_EMAIL_SETTINGS
print("\n1. DEFAULT_EMAIL_SETTINGS constant:")
print(f"   {DEFAULT_EMAIL_SETTINGS}")

# Test 2: Load and normalize email settings from config
print("\n2. Loading email_settings from rr_billing_config.json:")
settings = _get_email_settings()
print(f"   ✓ Retrieved settings: {list(settings.keys())}")
print(f"   - smtp_server: {settings.get('smtp_server', 'NOT SET')[:30] if settings.get('smtp_server') else 'NOT SET'}")
print(f"   - smtp_port: {settings.get('smtp_port', 'NOT SET')}")
print(f"   - smtp_username: {settings.get('smtp_username', 'NOT SET')[:20] if settings.get('smtp_username') else 'NOT SET'}")
print(f"   - use_tls: {settings.get('use_tls', 'NOT SET')}")

# Test 3: Check if email is configured
print("\n3. Checking if email is properly configured:")
configured = _email_configured()
print(f"   Email configured: {configured}")

if configured:
    print(f"   ✓ Email verification will be AVAILABLE in the EXE")
else:
    print(f"   ✗ Email verification will be UNAVAILABLE in the EXE")
    print(f"   Debug info:")
    print(f"     - smtp_server empty: {not settings.get('smtp_server', '').strip()}")
    print(f"     - smtp_port empty: {not settings.get('smtp_port')}")
    print(f"     - smtp_username empty: {not settings.get('smtp_username', '').strip()}")
    print(f"     - smtp_password empty: {not settings.get('smtp_password', '').strip()}")

print("\n" + "="*60)
print("TEST COMPLETE")
print("="*60)
