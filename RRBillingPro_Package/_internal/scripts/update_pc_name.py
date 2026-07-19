import json, os

os.chdir("C:/Aplikasi VSC/BillingPSkuDesktop")
cfg = json.load(open("rr_billing_config.json", "r", encoding="utf-8"))
for c in cfg.get("warnet_clients", []):
    for p in c.get("pcs", []):
        if p["ip"] == "192.168.1.13":
            p["name"] = "Kursi 5"
            print(f"Updated {p['pc_id']}: {p['ip']} -> {p['name']}")
json.dump(cfg, open("rr_billing_config.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("Done")
