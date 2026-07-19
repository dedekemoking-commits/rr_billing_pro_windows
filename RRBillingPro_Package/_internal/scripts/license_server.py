#!/usr/bin/env python3
"""
Simple license server for generating activation codes and emailing them.
Run: python scripts\license_server.py
Requires: flask (pip install flask)

Behavior:
- POST /generate_activation with JSON {email, username, days, package}
- Generates payload, HMAC-SHA256 signs it with secret (from env RR_LICENSE_SECRET or rr_billing_config.json["license_server_secret"]) and returns token.
- Sends email to given address using SMTP settings from rr_billing_config.json.
"""
from flask import Flask, request, jsonify
import os, json, hmac, hashlib, base64, time
from datetime import datetime, timedelta
import smtplib
from email.message import EmailMessage

APP = Flask(__name__)
ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "..", "rr_billing_config.json")


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_secret():
    # Prefer env var, fallback to config entry
    s = os.environ.get("RR_LICENSE_SECRET")
    if s:
        return s.encode()
    cfg = load_config()
    s2 = cfg.get("license_server_secret")
    if s2:
        return s2.encode()
    # Last resort (insecure for production)
    return b"dev-default-secret"


def sign_payload(payload_json: str, secret: bytes) -> str:
    mac = hmac.new(secret, payload_json.encode("utf-8"), hashlib.sha256).hexdigest()
    return mac


def make_token(payload: dict, secret: bytes) -> str:
    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode().rstrip("=")
    sig = sign_payload(payload_json, secret)
    return f"{payload_b64}.{sig}"


def send_email(to_email: str, subject: str, body: str) -> tuple:
    cfg = load_config()
    settings = cfg.get("email_settings", {})
    server = os.environ.get("MAIL_SERVER") or settings.get("smtp_server")
    port = int(os.environ.get("MAIL_PORT") or settings.get("smtp_port", 587))
    username = os.environ.get("MAIL_USERNAME") or settings.get("smtp_username")
    password = os.environ.get("MAIL_PASSWORD") or settings.get("smtp_password")
    use_tls = os.environ.get("MAIL_USE_TLS") or settings.get("use_tls", True)

    if not all([server, port, username, password]):
        return False, "SMTP not configured (set rr_billing_config.json email_settings or env vars)."

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = to_email
    msg.set_content(body)

    try:
        if str(use_tls).lower() in ("1", "true", "yes"):
            import ssl
            ctx = ssl.create_default_context()
            with smtplib.SMTP(server, port, timeout=20) as smtp:
                smtp.starttls(context=ctx)
                smtp.login(username, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(server, port, timeout=20) as smtp:
                smtp.login(username, password)
                smtp.send_message(msg)
        return True, "OK"
    except Exception as e:
        return False, str(e)


@APP.route("/generate_activation", methods=["POST"])
def generate_activation():
    data = request.get_json() or {}
    email = data.get("email")
    username = data.get("username") or ""
    days = int(data.get("days") or 30)
    package = data.get("package") or "monthly"

    if not email:
        return jsonify({"ok": False, "error": "email required"}), 400

    now = int(time.time())
    expires = now + days * 86400
    payload = {
        "username": username,
        "email": email,
        "issued_at": now,
        "expires_at": expires,
        "days": days,
        "package": package,
    }

    secret = get_secret()
    token = make_token(payload, secret)

    # Send email with code
    subject = f"RR Billing Activation Code — {package}"
    body = (
        f"Halo {username or 'user'},\n\n"
        f"Berikut kode aktivasi aplikasi Anda:\n\n" + token + "\n\n"
        f"Kode ini berlaku sampai {datetime.utcfromtimestamp(expires).isoformat()} UTC.\n\n"
        "Jika Anda tidak meminta kode ini, abaikan email ini.")

    sent, info = send_email(email, subject, body)

    if not sent:
        return jsonify({"ok": False, "error": "email_failed", "info": info}), 500

    return jsonify({"ok": True, "activation_code": token})


if __name__ == '__main__':
    host = os.environ.get("LICENSE_SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("LICENSE_SERVER_PORT", 5001))
    print(f"Starting license server on {host}:{port}")
    APP.run(host=host, port=port)
