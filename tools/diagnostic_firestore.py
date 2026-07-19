"""
Diagnostic Tool -- Cek Firestore data & test write ke invoices/
Jalankan: python tools/diagnostic_firestore.py
"""
import json
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.disable(logging.CRITICAL)

def p(text):
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode('ascii', errors='replace').decode('ascii'))

def main():
    p("=" * 60)
    p("  FIRESTORE DIAGNOSTIC TOOL")
    p("=" * 60)

    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rr_billing_config.json")
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)
        fb_username = cfg.get("fb_username", "")
        p(f"\n[CONFIG] fb_username: {fb_username}")
    except Exception as e:
        p(f"\n[CONFIG] Gagal baca config: {e}")
        fb_username = ""

    p(f"[CONFIG] trial_users: {list(cfg.get('trial_users', {}).keys())}")

    from firebase_auth import get_firebase_auth, FirebaseAuth
    from firestore_sync import get_firestore_client

    # Test A: pakai auth yg sudah ada (Google token)
    p("\n[FIREBASE AUTH] Memakai auth yang sudah ada...")
    auth = get_firebase_auth()
    has_token = bool(auth.get_id_token())
    p(f"  Punya token: {has_token}")
    p(f"  Email      : {auth.get_email()}")
    p(f"  DisplayName: {auth.get_display_name()}")
    if auth.ensure_anonymous():
        p("[OK] Token valid")
    else:
        p("[FAIL] Token tidak valid")

    fc = get_firestore_client()

    p(f"\n[FIRESTORE] Mengambil daftar user dari billingps_users...")
    users = fc.query_all("billingps_users", limit=30)
    if users:
        p(f"  Ditemukan {len(users)} dokumen user:")
        for u in users:
            uid = u.get("_id", "???")
            email = u.get("email", "-")
            ls = u.get("licenseStatus")
            if isinstance(ls, dict):
                status = ls.get("status", "N/A")
                expires = ls.get("expiresAt", "")
                p(f"  [{uid}] email={email} | status={status} | expires={expires}")
            else:
                p(f"  [{uid}] email={email} | (tanpa licenseStatus)")
    else:
        p("  Tidak ada dokumen user atau query gagal")
        doc_test = fc.get_document("billingps_users")
        if doc_test:
            p(f"  Root doc billingps_users ditemukan: {str(doc_test)[:200]}")
        else:
            p("  Root doc billingps_users tidak ditemukan (404)")

    if fb_username:
        p(f"\n[CEK] billingps_users/{fb_username}...")
        doc = fc.get_document(f"billingps_users/{fb_username}")
        if doc:
            ls = doc.get("licenseStatus")
            p("[OK] DOKUMEN DITEMUKAN")
            p(f"  Email    : {doc.get('email', 'N/A')}")
            p(f"  Username : {doc.get('username', 'N/A')}")
            if isinstance(ls, dict):
                p(f"  licenseStatus:")
                p(f"    status    : {ls.get('status', 'N/A')}")
                p(f"    pesan     : {ls.get('pesan', 'N/A')}")
                p(f"    expiresAt : {ls.get('expiresAt', 'N/A')}")
                p(f"    maxTv     : {ls.get('maxTv', 'N/A')}")
            else:
                p(f"  licenseStatus: {ls} (TIDAK ADA)")
        else:
            p("[FAIL] DOKUMEN TIDAK DITEMUKAN (404)")

    alt_username = fb_username.replace("_user_", "", 1) if fb_username.startswith("_user_") else None
    if alt_username:
        p(f"\n[CEK ALT] billingps_users/{alt_username} (tanpa _user_)...")
        doc = fc.get_document(f"billingps_users/{alt_username}")
        if doc:
            ls = doc.get("licenseStatus")
            p("[OK] DOKUMEN DITEMUKAN")
            p(f"  Email    : {doc.get('email', 'N/A')}")
            p(f"  Username : {doc.get('username', 'N/A')}")
            if isinstance(ls, dict):
                p(f"  licenseStatus:")
                p(f"    status    : {ls.get('status', 'N/A')}")
                p(f"    pesan     : {ls.get('pesan', 'N/A')}")
                p(f"    expiresAt : {ls.get('expiresAt', 'N/A')}")
            else:
                p(f"  licenseStatus: {ls}")
        else:
            p("[FAIL] DOKUMEN TIDAK DITEMUKAN (404)")

    # Test B: paksa anonymous auth murni (tanpa Google token)
    p(f"\n[TEST ANONYMOUS ONLY] Backup auth, paksa anonymous sign-in...")
    import requests
    auth_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rr_billing_auth.json")
    auth_backup = None
    if os.path.exists(auth_path):
        with open(auth_path, "r") as f:
            auth_backup = f.read()
        os.rename(auth_path, auth_path + ".bak")
        p("  Auth file dibackup, buat fresh anonymous sign-in...")

    fresh_auth = FirebaseAuth()  # instance baru, baca file (skrg kosong)
    if fresh_auth.ensure_anonymous():
        fresh_token = fresh_auth.get_id_token()
        p(f"[OK] Anonymous sign-in murni berhasil")
        p(f"  Token: {fresh_token[:40]}...")

        FIRESTORE_BASE = "https://firestore.googleapis.com/v1/projects/rrbillingpro/databases/(default)/documents"
        headers = {"Authorization": f"Bearer {fresh_token}", "Content-Type": "application/json"}

        # Test write anonymous ke invoices/
        test_id2 = "TEST-ANON-001"
        from firestore_sync import _dict_to_doc
        body = _dict_to_doc({
            "id": test_id2, "username": "anon_test", "email": "",
            "paket": "TEST", "harga": 0, "status": "PENDING",
            "dibuat": 0, "dibayar": 0, "confirmedBy": "", "kodeLisensi": "", "buktiBase64": "",
        })
        resp = requests.patch(f"{FIRESTORE_BASE}/invoices/{test_id2}", json=body, headers=headers, timeout=15)
        if resp.status_code in (200, 201):
            p(f"[OK] Anonymous WRITE ke invoices/ BERHASIL ({resp.status_code})")
            requests.delete(f"{FIRESTORE_BASE}/invoices/{test_id2}", headers=headers, timeout=15)
            p("[OK] Test document dihapus")
        else:
            p(f"[FAIL] Anonymous WRITE ke invoices/ GAGAL (HTTP {resp.status_code})")
            p(f"  Response: {resp.text[:200]}")
            p("  -> Firestore Security Rules BLOKIR anonymous write ke invoices/")

        # Test read anonymous dari billingps_users/
        p(f"\n  Anonymous READ billingps_users/_user_rrbillingpro...")
        resp2 = requests.get(f"{FIRESTORE_BASE}/billingps_users/{fb_username}", headers=headers, timeout=15)
        if resp2.status_code == 200:
            p("  [OK] Read berhasil")
        else:
            p(f"  [FAIL] Read gagal (HTTP {resp2.status_code})")

        fresh_auth.clear()
    else:
        p("[FAIL] Anonymous sign-in gagal total")

    # Restore auth
    if auth_backup:
        if os.path.exists(auth_path + ".bak"):
            os.rename(auth_path + ".bak", auth_path)
        p("  Auth file direstore")

    p(f"\n[TEST WRITE] Mencoba write ke invoices/ (dengan auth normal)...")
    test_id = "TEST-DIAG-001"
    test_inv = {
        "id": test_id, "username": fb_username or "test", "email": "",
        "paket": "DIAGNOSTIK", "harga": 0, "status": "PENDING",
        "dibuat": 0, "dibayar": 0, "confirmedBy": "", "kodeLisensi": "", "buktiBase64": "",
    }
    result = fc.set_document(f"invoices/{test_id}", test_inv, merge=False)
    if result:
        p("[OK] WRITE KE INVOICES BERHASIL (200/201)")
        fc.delete_document(f"invoices/{test_id}")
        p("[OK] Test document dihapus")
    else:
        p("[FAIL] WRITE KE INVOICES GAGAL!")
        p("  Kemungkinan: Firestore Security Rules blokir anonymous write")

    p(f"\n[TEST QUERY] Mencoba query invoices/...")
    invs = fc.query_all("invoices", limit=5)
    if invs is not None:
        p(f"  Query berhasil, {len(invs)} invoice ditemukan")
        for inv in invs[:3]:
            p(f"  - {inv.get('_id', inv.get('id', '?'))} status={inv.get('status', '?')}")
    else:
        p("  Query invoices gagal")

    # 8. Test fetch_license_status_by_username dengan fallback
    p(f"\n[TEST FALLBACK] fetch_license_status_by_username('_user_rrbillingpro')...")
    ls = fc.fetch_license_status_by_username("_user_rrbillingpro")
    if ls:
        p(f"  [OK] Ditemukan! status={ls.get('status')} expires={ls.get('expiresAt')}")
    else:
        p(f"  [FAIL] Tidak ditemukan")

    p(f"\n[TEST FALLBACK] fetch_license_status_by_username('rrbillingpro')...")
    ls = fc.fetch_license_status_by_username("rrbillingpro")
    if ls:
        p(f"  [OK] Ditemukan! status={ls.get('status')} expires={ls.get('expiresAt')}")

    p(f"\n[TEST FALLBACK] fetch_license_status_by_username('rrgaming')...")
    ls = fc.fetch_license_status_by_username("rrgaming")
    if ls:
        p(f"  [OK] Ditemukan! status={ls.get('status')} expires={ls.get('expiresAt')}")
    else:
        p(f"  [OK] Tidak ditemukan (expected - no active license)")

    p("\n" + "=" * 60)
    p("  DIAGNOSTIK SELESAI")
    p("=" * 60)

if __name__ == "__main__":
    main()
