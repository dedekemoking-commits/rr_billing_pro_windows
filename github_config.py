import os
import json

GITHUB_OWNER = "dedekemoking-commits"
GITHUB_REPO = "rr-billing-pro-new"
USERS_PATH = "users.json"

def _get_token():
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rr_billing_config.json")
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("github_token", "")
    except Exception:
        return ""

GITHUB_TOKEN = _get_token()
