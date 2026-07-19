import json
cfg = json.load(open("rr_billing_config.json", "r", encoding="utf-8"))
for c in cfg.get("warnet_clients", []):
    print(f"Client: {c['client_id']}")
    for p in c.get("pcs", []):
        print(f'  {p["pc_id"]}: {p["ip"]} - {p["name"]}')
