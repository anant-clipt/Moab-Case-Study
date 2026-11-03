"""Download Mesa's old data and the blank Keystone forms.

Saves files under data/raw. Does not change them and does not load Keystone.
"""

import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from client import call, call_json

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
TEMPLATES = RAW / "templates"

API_TABLES = ["BLDGS", "OCCUPANTS", "PORTFOLIOS", "UNIT_TYPES", "VENDORS"]
EXPORT_TABLES = ["LEASES", "LEASE_CHARGES", "TENANTS", "UNITS"]
SHEETS = [
    "accounts",
    "contacts",
    "leases",
    "lease_charge_lines",
    "portfolios",
    "properties",
    "unit_types",
    "units",
    "vendor_payment_terms",
    "vendors",
]
EXPECTED = {
    "BLDGS": 7,
    "LEASES": 166,
    "LEASE_CHARGES": 253,
    "OCCUPANTS": 212,
    "PORTFOLIOS": 3,
    "TENANTS": 149,
    "UNITS": 91,
    "UNIT_TYPES": 6,
    "VENDORS": 12,
}


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def fetch_api_table(name):
    rows = []
    page = 1
    total = None
    while True:
        _, _, payload = call_json(
            "GET", f"/legacy/tables/{name}?page={page}&per_page=100"
        )
        total = payload["total"]
        rows.extend(payload["rows"])
        if not payload.get("next_page"):
            break
        page = payload["next_page"]
    if len(rows) != total:
        raise SystemExit(f"{name}: got {len(rows)} rows, server said {total}")
    save_json(RAW / f"{name.lower()}.json", rows)
    return len(rows)


def decode_export(raw):
    """LeaseLedger's export is usually UTF-8. Some names are in Windows Latin."""
    for encoding in ("utf-8", "cp1252"):
        try:
            return encoding, raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SystemExit("Could not read an export file as text")


def fetch_export(name):
    _, _, started = call_json("POST", "/legacy/exports", {"table": name})
    export_id = started["export_id"]
    poll_url = started.get("poll_url") or f"/legacy/exports/{export_id}"
    for _ in range(40):
        status, hdrs, payload = call_json("GET", poll_url)
        state = payload.get("status")
        if state == "ready":
            download = payload.get("download_url") or f"/legacy/exports/{export_id}/download"
            _, _, raw = call("GET", download)
            path = RAW / f"{name.lower()}.csv"
            # Keep the file exactly as LeaseLedger sent it.
            path.write_bytes(raw)
            encoding, text = decode_export(raw)
            count = sum(1 for _ in csv.reader(text.splitlines())) - 1
            if payload.get("rows") is not None and count != payload["rows"]:
                raise SystemExit(
                    f"{name}: file has {count} rows, export said {payload['rows']}"
                )
            print(f"  encoding {encoding}")
            return count
        delay = float(hdrs.get("Retry-After") or 1)
        time.sleep(delay)
    raise SystemExit(f"{name}: export never finished")


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    TEMPLATES.mkdir(parents=True, exist_ok=True)

    _, _, tables = call_json("GET", "/legacy/tables")
    save_json(RAW / "tables.json", tables)

    counts = {}
    for name in API_TABLES:
        counts[name] = fetch_api_table(name)
        print(f"{name}: {counts[name]}")
    for name in EXPORT_TABLES:
        counts[name] = fetch_export(name)
        print(f"{name}: {counts[name]}")

    for name, expected in EXPECTED.items():
        if counts[name] != expected:
            raise SystemExit(f"{name}: expected {expected}, got {counts[name]}")

    _, _, report = call_json("GET", "/legacy/reports/rent_roll_by_property?year=2025")
    save_json(RAW / "rent_roll_2025.json", report)
    print("rent report saved")

    _, _, schema = call_json("GET", "/keystone/schema")
    save_json(RAW / "keystone-schema.json", schema)

    for sheet in SHEETS:
        _, _, raw = call("GET", f"/keystone/templates/{sheet}.csv")
        (TEMPLATES / f"{sheet}.csv").write_bytes(raw)
        print(f"template {sheet}")

    _, _, workbook = call("GET", "/keystone/templates/onboarding.xlsx")
    (TEMPLATES / "onboarding.xlsx").write_bytes(workbook)
    print("onboarding workbook saved")
    print("download ok")


if __name__ == "__main__":
    main()
