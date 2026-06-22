#!/usr/bin/env python3
"""Client helper to request activation from license server.
Usage:
  python scripts\request_activation.py --server http://localhost:5001 --email user@gmail.com --username rrgame --days 30
"""
import requests, argparse, sys

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server", required=True, help="License server URL, e.g. http://localhost:5001")
    p.add_argument("--email", required=True)
    p.add_argument("--username", default="")
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args()

    url = args.server.rstrip('/') + '/generate_activation'
    payload = {"email": args.email, "username": args.username, "days": args.days}
    try:
        r = requests.post(url, json=payload, timeout=20)
    except Exception as e:
        print("Request failed:", e)
        sys.exit(2)
    try:
        data = r.json()
    except Exception:
        print("Invalid response:", r.text)
        sys.exit(2)
    if not data.get('ok'):
        print("Error:", data)
        sys.exit(1)
    print("Activation code:")
    print(data.get('activation_code'))

if __name__ == '__main__':
    main()
