import os
import json
import hashlib
import threading
from datetime import datetime, timezone
import requests
from github_config import GITHUB_OWNER, GITHUB_REPO, USERS_PATH, GITHUB_TOKEN

USERS_CACHE = None
USERS_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{USERS_PATH}"
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rr_billing_github_users.json")

_lock = threading.Lock()

def _auth_headers():
    h = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "rr-billing-pro",
    }
    if GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h

def _fetch_from_github():
    try:
        r = requests.get(USERS_API_URL, headers=_auth_headers(), timeout=15)
        if r.status_code == 404:
            return None
        if not r.ok:
            return None
        data = r.json()
        import base64
        raw = base64.b64decode(data["content"])
        return json.loads(raw)
    except Exception:
        return None

def _save_to_github(users):
    if not GITHUB_TOKEN:
        return False
    try:
        r = requests.get(USERS_API_URL, headers=_auth_headers(), timeout=15)
        sha = None
        if r.ok:
            sha = r.json().get("sha")
        import base64
        content = base64.b64encode(json.dumps(users, indent=2).encode()).decode()
        put_r = requests.put(USERS_API_URL, headers={**_auth_headers(), "Content-Type": "application/json"},
                             json={"message": "Update users", "content": content, "sha": sha}, timeout=15)
        return put_r.ok
    except Exception:
        return False

def _load_local_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_local_cache(users):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)
    except Exception:
        pass

def fetch_users(force_refresh=False):
    global USERS_CACHE
    if USERS_CACHE is not None and not force_refresh:
        return USERS_CACHE
    with _lock:
        if GITHUB_TOKEN:
            remote = _fetch_from_github()
            if remote is not None:
                USERS_CACHE = remote
                _save_local_cache(remote)
                return remote
        local = _load_local_cache()
        USERS_CACHE = local
        return local

def seed_admin():
    users = fetch_users()
    if len(users) == 0:
        password_hash = hashlib.sha256("dheedek01".encode()).hexdigest()
        users["rrgaming"] = {"passwordHash": password_hash, "role": "admin"}
        USERS_CACHE = users
        if GITHUB_TOKEN:
            ok = _save_to_github(users)
            if ok:
                return
        _save_local_cache(users)

def cek_username(username):
    users = fetch_users()
    return username.strip().lower() in users

def daftar_user(username, password_hash, email=""):
    key = username.strip().lower()
    with _lock:
        users = fetch_users(force_refresh=True)
        if key in users:
            raise ValueError("Username sudah ada")
        users[key] = {
            "passwordHash": password_hash,
            "role": "kasir",
            "email": email or "",
            "dibuat": datetime.now(timezone.utc).isoformat(),
        }
        USERS_CACHE = users
        if GITHUB_TOKEN:
            ok = _save_to_github(users)
            if ok:
                return True
        _save_local_cache(users)
        return True

def login_user(username, password_hash):
    users = fetch_users()
    key = username.strip().lower()
    user = users.get(key)
    if not user or user.get("passwordHash") != password_hash:
        return None
    return {"username": key, "role": user.get("role", "kasir")}

def get_user_info(username):
    users = fetch_users()
    key = username.strip().lower()
    return users.get(key)

def update_user_role(username, new_role):
    key = username.strip().lower()
    with _lock:
        users = fetch_users(force_refresh=True)
        if key not in users:
            return False
        users[key]["role"] = new_role
        USERS_CACHE = users
        if GITHUB_TOKEN:
            ok = _save_to_github(users)
            if ok:
                return True
        _save_local_cache(users)
        return True
