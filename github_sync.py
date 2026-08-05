import os
import json
import base64
from datetime import datetime, timezone
import requests
from github_config import GITHUB_OWNER, GITHUB_REPO, GITHUB_TOKEN

SYNC_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rr_billing_github_sync.json")

def _auth_headers():
    h = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "rr-billing-pro",
    }
    if GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h

def _api_path(username):
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/transactions_{username}.json"

def fetch_transaksi_remote(username):
    if not GITHUB_TOKEN:
        return None
    try:
        r = requests.get(_api_path(username), headers=_auth_headers(), timeout=15)
        if r.status_code == 404:
            return None
        if not r.ok:
            return None
        data = r.json()
        raw = base64.b64decode(data["content"])
        return json.loads(raw)
    except Exception:
        return None

def save_transaksi_to_github(username, transactions):
    if not GITHUB_TOKEN:
        return False
    try:
        url = _api_path(username)
        r = requests.get(url, headers=_auth_headers(), timeout=15)
        sha = None
        if r.ok:
            sha = r.json().get("sha")
        content = base64.b64encode(json.dumps(transactions, indent=2).encode()).decode()
        put_r = requests.put(url, headers={**_auth_headers(), "Content-Type": "application/json"},
                             json={"message": "Update transaksi", "content": content, "sha": sha}, timeout=15)
        if put_r.ok:
            _save_sync_time(username)
            return True
        return False
    except Exception:
        return False

def hapus_transaksi_remote(username):
    if not GITHUB_TOKEN:
        return False
    try:
        url = _api_path(username)
        r = requests.get(url, headers=_auth_headers(), timeout=15)
        if not r.ok:
            return False
        existing = r.json()
        del_r = requests.delete(url, headers={**_auth_headers(), "Content-Type": "application/json"},
                                json={"message": "Hapus semua transaksi", "sha": existing["sha"]}, timeout=15)
        if del_r.ok:
            _clear_sync_time(username)
            return True
        return False
    except Exception:
        return False

def sync_transaksi(username, local_transactions):
    remote = fetch_transaksi_remote(username)
    if not remote or len(remote) == 0:
        if len(local_transactions) > 0:
            save_transaksi_to_github(username, local_transactions)
        return local_transactions
    remote_ids = {t["id"] for t in remote if "id" in t}
    local_only = [t for t in local_transactions if t.get("id") not in remote_ids]
    merged = remote + local_only
    merged.sort(key=lambda t: t.get("waktu", ""), reverse=True)
    save_transaksi_to_github(username, merged)
    return merged

def _save_sync_time(username):
    try:
        cache = {}
        if os.path.exists(SYNC_CACHE_FILE):
            with open(SYNC_CACHE_FILE, encoding="utf-8") as f:
                cache = json.load(f)
        cache[username] = datetime.now(timezone.utc).isoformat()
        with open(SYNC_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass

def _clear_sync_time(username):
    try:
        if os.path.exists(SYNC_CACHE_FILE):
            with open(SYNC_CACHE_FILE, encoding="utf-8") as f:
                cache = json.load(f)
            cache.pop(username, None)
            with open(SYNC_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f)
    except Exception:
        pass

def get_last_sync(username):
    try:
        if os.path.exists(SYNC_CACHE_FILE):
            with open(SYNC_CACHE_FILE, encoding="utf-8") as f:
                cache = json.load(f)
            return cache.get(username)
    except Exception:
        pass
    return None
