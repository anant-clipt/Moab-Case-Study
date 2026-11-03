"""Load one layer of Keystone, then stop.

Usage:
    python3 scripts/04_load.py reset
    python3 scripts/04_load.py portfolios
    python3 scripts/04_load.py unit_types
    python3 scripts/04_load.py terms
    python3 scripts/04_load.py properties
    python3 scripts/04_load.py vendors
    python3 scripts/04_load.py accounts
    python3 scripts/04_load.py contacts
    python3 scripts/04_load.py primary_contacts
    python3 scripts/04_load.py units
    python3 scripts/04_load.py leases

Each run sends that layer only, saves the ids, and reads the layer back.
I do not fill in a missing parent. That record is skipped and printed.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from client import call_result

ROOT = Path(__file__).resolve().parents[1]
READY = ROOT / "data" / "ready"
MAP_PATH = ROOT / "data" / "id-map.json"
LOG_PATH = ROOT / "data" / "load-log.jsonl"
RUN_ID = "pass-1"

# Ready-file field -> (id-map bucket, Keystone field)
REFS = {
    "properties": {"portfolio_identifier": ("portfolios", "portfolio_id")},
    "vendors": {"payment_terms_name": ("vendor_payment_terms", "payment_terms_id")},
    "accounts": {"parent_identifier": ("accounts", "parent_account_id")},
    "contacts": {"account_identifier": ("accounts", "account_id")},
    "units": {
        "property_identifier": ("properties", "property_id"),
        "unit_type_identifier": ("unit_types", "unit_type_id"),
        "maintenance_vendor_identifier": ("vendors", "maintenance_vendor_id"),
    },
    "leases": {
        "account_identifier": ("accounts", "account_id"),
        "property_identifier": ("properties", "property_id"),
        "contact_legacy_id": ("contacts", "contact_id"),
    },
}

LAYER_ENTITY = {
    "portfolios": "portfolios",
    "unit_types": "unit_types",
    "terms": "vendor_payment_terms",
    "properties": "properties",
    "vendors": "vendors",
    "accounts": "accounts",
    "contacts": "contacts",
    "units": "units",
    "leases": "leases",
}


def load_map():
    if MAP_PATH.exists():
        return json.loads(MAP_PATH.read_text())
    return {"run_id": RUN_ID}


def save_map(id_map):
    MAP_PATH.write_text(json.dumps(id_map, indent=2) + "\n")


def log(entry):
    with LOG_PATH.open("a") as handle:
        handle.write(json.dumps(entry) + "\n")


def ready_rows(layer):
    name = "vendor_payment_terms" if layer == "terms" else layer
    return json.loads((READY / f"{name}.json").read_text())


def record_key(layer, row):
    if layer == "terms":
        return row["name"]
    if layer == "contacts":
        return row["legacy_id"]
    return row["identifier"]


def parents_first(rows):
    pending = {row["identifier"]: row for row in rows}
    ordered = []
    while pending:
        ready = [
            row for row in pending.values()
            if row.get("parent_identifier") not in pending
        ]
        if not ready:
            ordered.extend(pending.values())
            break
        for row in ready:
            ordered.append(row)
            del pending[row["identifier"]]
    return ordered


def list_all(entity):
    rows = []
    cursor = None
    total = None
    while True:
        path = f"/keystone/{entity}?limit=200"
        if cursor:
            path += "&cursor=" + cursor
        status, _hdrs, body = call_result("GET", path)
        if status != 200:
            raise SystemExit(f"Could not read {entity}: {status} {body}")
        rows.extend(body.get("data") or [])
        total = body.get("total", len(rows))
        cursor = body.get("next_cursor")
        if not cursor:
            return total, rows


def build_body(layer, row, id_map):
    body = {}
    refs = REFS.get(layer, {})
    missing = []
    for field, value in row.items():
        if field in refs:
            bucket, target = refs[field]
            found = id_map.get(bucket, {}).get(value)
            if not found:
                missing.append(f"{field}={value}")
                continue
            body[target] = found
            continue
        if field in ("legacy_id",):
            continue
        body[field] = value
    if layer == "leases":
        lines = []
        for line in row["charge_lines"]:
            unit_id = id_map.get("units", {}).get(line["unit_identifier"])
            if not unit_id:
                missing.append(f"unit={line['unit_identifier']}")
                continue
            lines.append(
                {
                    "unit_id": unit_id,
                    "charge_type": line["charge_type"],
                    "monthly_amount": line["monthly_amount"],
                }
            )
        body["charge_lines"] = lines
    return body, missing


def create(entity, body, idem_key):
    status, _hdrs, resp = call_result(
        "POST",
        f"/keystone/{entity}",
        body,
        headers={"Idempotency-Key": idem_key},
    )
    if status in (200, 201) and isinstance(resp, dict) and resp.get("id"):
        return resp["id"], "created"
    if status == 409 and isinstance(resp, dict) and resp.get("existing_id"):
        return resp["existing_id"], "already there"
    return None, {"status": status, "body": resp}


def load_layer(layer):
    entity = LAYER_ENTITY[layer]
    bucket = entity
    id_map = load_map()
    id_map.setdefault(bucket, {})
    rows = ready_rows(layer)
    if layer == "accounts":
        rows = parents_first(rows)

    created = 0
    already = 0
    skipped = []
    for row in rows:
        key = record_key(layer, row)
        if key in id_map[bucket]:
            already += 1
            continue
        body, missing = build_body(layer, row, id_map)
        if missing:
            skipped.append({"key": key, "missing": missing})
            log({"layer": layer, "key": key, "result": "skipped", "missing": missing})
            print(f"skipped {key}: missing {', '.join(missing)}")
            continue
        idem_key = f"{RUN_ID}:{entity}:{key}"
        record_id, result = create(entity, body, idem_key)
        if not record_id:
            log({"layer": layer, "key": key, "result": "rejected", "detail": result})
            print(f"rejected {key}: {result}")
            continue
        id_map[bucket][key] = record_id
        save_map(id_map)
        log({"layer": layer, "key": key, "result": result, "id": record_id})
        if result == "created":
            created += 1
        else:
            already += 1
        print(f"{result} {key} -> {record_id}")

    total, live = list_all(entity)
    print(f"\n{entity}: sent {created} new, {already} already saved, {len(skipped)} skipped")
    print(f"{entity}: Keystone now has {total}")
    if skipped:
        print("Look at the skipped rows before the next layer.")
    return skipped


def load_primary_contacts():
    id_map = load_map()
    rows = json.loads((READY / "account_contacts.json").read_text())
    linked = 0
    skipped = []
    for row in rows:
        account_key = row["account_identifier"]
        contact_key = row["contact_legacy_id"]
        account_id = id_map.get("accounts", {}).get(account_key)
        contact_id = id_map.get("contacts", {}).get(contact_key)
        if not account_id or not contact_id:
            skipped.append(row)
            print(f"skipped main contact for {account_key}")
            continue
        idem_key = f"{RUN_ID}:primary:{account_key}"
        status, _hdrs, resp = call_result(
            "PATCH",
            f"/keystone/accounts/{account_id}",
            {"primary_contact_id": contact_id},
            headers={"Idempotency-Key": idem_key},
        )
        if status not in (200, 201):
            print(f"rejected main contact for {account_key}: {status} {resp}")
            log({"layer": "primary_contacts", "key": account_key, "result": "rejected", "detail": resp})
            continue
        linked += 1
        log({"layer": "primary_contacts", "key": account_key, "result": "linked", "contact": contact_key})
        print(f"linked {account_key} -> {contact_key}")
    print(f"\nmain contacts linked: {linked}, skipped: {len(skipped)}")


def reset_keystone():
    status, _hdrs, body = call_result("POST", "/reset", {})
    print(status, json.dumps(body))
    if status != 200:
        raise SystemExit("Reset did not work")
    if MAP_PATH.exists():
        MAP_PATH.unlink()
    print("Keystone is empty. The id map for this pass was cleared.")


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    layer = sys.argv[1]
    if layer == "reset":
        reset_keystone()
        return
    if layer == "primary_contacts":
        load_primary_contacts()
        return
    if layer not in LAYER_ENTITY:
        raise SystemExit(f"Unknown layer {layer}")
    load_layer(layer)


if __name__ == "__main__":
    main()
