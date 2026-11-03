"""Turn the old files into two piles.

data/ready is what I are willing to send to Keystone.
data/review is the spreadsheet Carmen uses for everything I skipped or changed.

This step does not call Keystone.
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    CHARGE,
    HOLDING,
    SOLD_BUILDING,
    STATUS,
    find_merges,
    keeper_for,
    load_tables,
    name_tokens,
    parse_date,
    parse_email,
    parse_money,
    parse_phone,
    parse_sqft,
    parse_terms,
    parse_timezone,
    parse_zip,
    template_headers,
)

ROOT = Path(__file__).resolve().parents[1]
READY = ROOT / "data" / "ready"
REVIEW = ROOT / "data" / "review"

EXTRA = ["legacy_id", "load_status", "issue", "what_we_need_from_you"]


def index(rows, key):
    return {row[key]: row for row in rows}


def members_of(merges):
    groups = defaultdict(list)
    for dropped, kept in merges.items():
        groups[kept].append(dropped)
    return groups


def po_choice(rows):
    flags = {(row.get("REQ_PO") or "").strip().upper() for row in rows}
    if "Y" in flags:
        return True
    if "N" in flags:
        return False
    return None


def ask_from(text):
    """Turn the issue into the one thing Carmen should do about it."""
    asks = []
    if "extension" in text:
        asks.append("Keystone cannot store an extension. Send it only if you need it written down somewhere else.")
    if "area code" in text or "could not read the phone" in text:
        asks.append("Send a phone number with an area code if you want one saved.")
    if "email" in text:
        asks.append("Send the full email address if you want it saved.")
    if "deposit" in text:
        asks.append("Send the real deposit amount if there is one.")
    if "parent" in text:
        asks.append("Tell me which company is the parent.")
    if "main contact" in text:
        asks.append("Tell me who the main contact should be.")
    if "payment terms" in text:
        asks.append("Tell me if I read the payment terms wrong.")
    return " ".join(asks)


def add_review(bucket, sheet, headers, values, legacy_id, status, issue, need):
    row = {column: "" if values.get(column) is None else str(values.get(column)) for column in headers}
    row["legacy_id"] = legacy_id
    row["load_status"] = status
    row["issue"] = issue
    row["what_we_need_from_you"] = need
    bucket[sheet].append(row)


def decide():
    tables = load_tables()
    tenants = tables["tenants"]
    occupants = tables["occupants"]
    leases = tables["leases"]
    charges = tables["charges"]
    units = tables["units"]
    buildings = index(tables["buildings"], "BLDG_ID")
    portfolios = tables["portfolios"]
    unit_types = tables["unit_types"]
    vendors = tables["vendors"]

    by_tenant = index(tenants, "TEN_NO")
    by_unit = index(units, "UNIT_ID")
    merges = find_merges(tenants)
    grouped = members_of(merges)

    charges_for_unit = defaultdict(list)
    charges_for_lease = defaultdict(list)
    for charge in charges:
        charges_for_unit[charge["UNIT_ID"]].append(charge)
        charges_for_lease[charge["LEASE_NO"]].append(charge)

    # Same door number twice. Keep the copy that actually has leases.
    door_groups = defaultdict(list)
    for unit in units:
        door = (unit["UNIT_NO"] or "").strip()
        door_groups[(unit["BLDG_ID"], door)].append(unit["UNIT_ID"])
    drop_units = {}
    for (building_id, door), unit_ids in door_groups.items():
        if len(unit_ids) < 2:
            continue
        ranked = sorted(
            unit_ids,
            key=lambda unit_id: (
                -len(charges_for_unit[unit_id]),
                int(unit_id.split("-")[1]),
            ),
        )
        keeper = ranked[0]
        if len(charges_for_unit[keeper]) == 0 and any(charges_for_unit[unit_id] for unit_id in unit_ids):
            raise SystemExit(f"Could not tell which copy of {building_id} {door} to keep")
        for unit_id in ranked[1:]:
            drop_units[unit_id] = keeper

    reviews = defaultdict(list)
    ready = {
        "portfolios": [],
        "vendor_payment_terms": [],
        "unit_types": [],
        "accounts": [],
        "properties": [],
        "vendors": [],
        "contacts": [],
        "account_contacts": [],
        "units": [],
        "leases": [],
    }

    for portfolio in portfolios:
        ready["portfolios"].append(
            {"identifier": portfolio["PF_CODE"].strip(), "name": portfolio["PF_NAME"].strip()}
        )

    for floor in unit_types:
        rent, rent_note = parse_money(str(floor["BASE_RENT"]))
        baths, _bath_note = parse_money(str(floor["BATHS"]))
        if rent is None or baths is None:
            raise SystemExit(f"Floor plan {floor['TYPE_CODE']} is missing rent or baths")
        ready["unit_types"].append(
            {
                "identifier": floor["TYPE_CODE"].strip(),
                "name": floor["DESCR"].strip(),
                "bedrooms": int(floor["BEDS"]),
                "bathrooms": baths,
                "base_rent": rent,
            }
        )

    term_names = {}
    for vendor in vendors:
        parsed = parse_terms(vendor["TERMS"])
        if not parsed:
            continue
        code, label = parsed
        term_names[code] = label
    for code, label in sorted(term_names.items(), key=lambda item: item[1]):
        ready["vendor_payment_terms"].append({"name": label, "terms": code})

    vendor_headers = template_headers("vendors")
    for vendor in vendors:
        parsed = parse_terms(vendor["TERMS"])
        email, email_note = parse_email(vendor["EMAIL"])
        phone, phone_note = parse_phone(vendor["PHONE"])
        values = {
            "identifier": vendor["VENDOR_ID"],
            "name": vendor["VEND_NAME"].strip(),
            "type": "business" if vendor["VEND_TYPE"] == "CO" else "individual",
            "email": email or "",
            "phone": phone or "",
            "payment_terms_name": "",
        }
        if not parsed:
            add_review(
                reviews, "vendors", vendor_headers, values, vendor["VENDOR_ID"],
                "not_loaded",
                f"The payment terms were written as \"{vendor['TERMS']}\". I could not tell what that means, so I left this vendor out.",
                "Tell me if they are due on receipt, or net 10, 15, 30, 45, or 60.",
            )
            continue
        code, label = parsed
        values["payment_terms_name"] = label
        record = {
            "identifier": vendor["VENDOR_ID"],
            "name": values["name"],
            "type": values["type"],
            "payment_terms_name": label,
        }
        if email:
            record["email"] = email
        if phone:
            record["phone"] = phone
        ready["vendors"].append(record)
        notes = [f"The payment terms were written as \"{vendor['TERMS'].strip()}\". I read that as {label}."]
        if phone_note:
            notes.append(phone_note)
        if email_note:
            notes.append(email_note)
        issue = " ".join(notes)
        add_review(
            reviews, "vendors", vendor_headers, values, vendor["VENDOR_ID"],
            "loaded_with_changes",
            issue,
            ask_from(issue),
        )

    # Accounts. Parents are attached after I know which links make a loop.
    account_headers = template_headers("accounts")
    account_rows = {}
    for tenant in tenants:
        if tenant["TEN_NO"] in merges:
            continue
        kept = tenant["TEN_NO"]
        group_ids = [kept] + grouped.get(kept, [])
        group = [by_tenant[ten_id] for ten_id in group_ids]
        email, email_note = parse_email(tenant["EMAIL"])
        phone, phone_note = parse_phone(tenant["PHONE"])
        deposit, deposit_note = parse_money(tenant["DEPOSIT"])
        parent_raw = (tenant.get("PARENT_TEN_NO") or "").strip()
        parent = keeper_for(parent_raw, merges) if parent_raw else ""
        if parent == kept:
            parent = ""
        po = po_choice(group)
        record = {
            "identifier": kept,
            "name": tenant["TEN_NAME"].strip(),
            "type": "individual" if tenant["TEN_TYPE"] == "I" else "business",
        }
        if parent:
            record["parent_identifier"] = parent
        if email:
            record["billing_email"] = email
        if phone:
            record["phone"] = phone
        if deposit is not None:
            record["security_deposit"] = deposit
        if po is not None:
            record["requires_po_number"] = po
        record["_email_note"] = email_note
        record["_phone_note"] = phone_note
        record["_deposit_note"] = deposit_note
        record["_source_primary"] = (tenant.get("PRIMARY_OCC") or "").strip()
        account_rows[kept] = record

    def cycle_members():
        found = set()
        for start in account_rows:
            seen = []
            current = start
            while current and current not in seen and current in account_rows:
                seen.append(current)
                current = account_rows[current].get("parent_identifier")
            if current and current in seen:
                found.update(seen[seen.index(current) :])
        return found

    # A loop means I cannot tell who the parent is. Drop every link in the loop.
    cycled = cycle_members()
    for ident in cycled:
        account_rows[ident].pop("parent_identifier", None)

    # Contacts.
    contact_headers = template_headers("contacts")
    occupants_sorted = sorted(occupants, key=lambda row: (int(row["OCC_ID"].split("-")[1])))
    kept_people = {}
    occ_alias = {}
    loaded_occs = {}

    for person in occupants_sorted:
        ten_id = person["TEN_NO"]
        email, email_note = parse_email(person.get("EMAIL"))
        phone, phone_note = parse_phone(person.get("PHONE"))
        first = (person.get("FIRST_NM") or "").strip()
        last = (person.get("LAST_NM") or "").strip()
        values = {
            "account_identifier": ten_id,
            "first_name": first,
            "last_name": last,
            "email": email or "",
            "phone": phone or "",
        }
        if ten_id not in by_tenant:
            add_review(
                reviews, "contacts", contact_headers, values, person["OCC_ID"],
                "not_loaded",
                f"This person is filed under tenant {ten_id}, and there is no tenant with that number. I did not make up an account for them.",
                "If Mesa is still collecting from them, send the tenant name and the tenant number you want me to use.",
            )
            continue
        kept = keeper_for(ten_id, merges)
        person_key = (kept, name_tokens(f"{first} {last}"), email or "")
        if person_key in kept_people and email:
            original = kept_people[person_key]
            occ_alias[person["OCC_ID"]] = original
            add_review(
                reviews, "contacts", contact_headers, values, person["OCC_ID"],
                "not_loaded",
                f"This is the same person as {first} {last} on account {kept}. I kept one person record.",
                "Tell me if these are actually two different people.",
            )
            continue
        if not first or not last:
            add_review(
                reviews, "contacts", contact_headers, values, person["OCC_ID"],
                "not_loaded",
                "This person is missing a first or last name, so I left them out.",
                "Send the full name.",
            )
            continue
        if email:
            kept_people[person_key] = person["OCC_ID"]
        record = {
            "legacy_id": person["OCC_ID"],
            "account_identifier": kept,
            "first_name": first,
            "last_name": last,
        }
        if email:
            record["email"] = email
        if phone:
            record["phone"] = phone
        ready["contacts"].append(record)
        loaded_occs[person["OCC_ID"]] = record
        notes = [note for note in (email_note, phone_note) if note]
        if notes:
            values["account_identifier"] = kept
            issue = " ".join(notes)
            add_review(
                reviews, "contacts", contact_headers, values, person["OCC_ID"],
                "loaded_with_changes",
                issue,
                ask_from(issue),
            )

    # Main contact, only when that person really belongs to the account.
    primary_email = {}
    for ident, record in account_rows.items():
        wanted = record["_source_primary"]
        chosen = occ_alias.get(wanted, wanted)
        contact = loaded_occs.get(chosen)
        wrong = wanted and (contact is None or contact["account_identifier"] != ident)
        if contact and contact["account_identifier"] == ident:
            ready["account_contacts"].append(
                {"account_identifier": ident, "contact_legacy_id": contact["legacy_id"]}
            )
            primary_email[ident] = contact.get("email", "")
        deposit_words = {
            "was negative": "The deposit on file was a negative number, so I left it off.",
            "was not a number": "The deposit on file was not a real amount, so I left it off.",
        }
        notes = []
        if record["_phone_note"]:
            notes.append(record["_phone_note"])
        if record["_email_note"]:
            notes.append(record["_email_note"])
        if record["_deposit_note"]:
            notes.append(deposit_words.get(record["_deposit_note"], record["_deposit_note"]))
        if ident in cycled:
            other = " and ".join(sorted(item for item in cycled if item != ident))
            notes.append(
                f"The file has this account and {other} listed as each other's parent company. That is a loop, so I did not set a parent."
            )
        if wrong:
            other = loaded_occs.get(wanted)
            who = f"{other['first_name']} {other['last_name']}" if other else wanted
            notes.append(
                f"The main contact on file points at {who}, who is not a person on this account. I left the main contact blank."
            )
        if notes:
            parent = record.get("parent_identifier", "")
            values = {
                "identifier": ident,
                "name": record["name"],
                "type": record["type"],
                "parent_account_identifier": parent,
                "billing_email": record.get("billing_email", ""),
                "phone": record.get("phone", ""),
                "security_deposit": record.get("security_deposit", ""),
                "requires_po_number": "" if "requires_po_number" not in record else str(record["requires_po_number"]).lower(),
                "primary_contact_email": primary_email.get(ident, ""),
            }
            issue = " ".join(notes)
            add_review(
                reviews, "accounts", account_headers, values, ident,
                "loaded_with_changes",
                issue,
                ask_from(issue),
            )

    for dropped, kept in sorted(merges.items()):
        old = by_tenant[dropped]
        kept_row = by_tenant[kept]
        email, _note = parse_email(old["EMAIL"])
        phone, _phone_note = parse_phone(old["PHONE"])
        values = {
            "identifier": dropped,
            "name": old["TEN_NAME"].strip(),
            "type": "individual" if old["TEN_TYPE"] == "I" else "business",
            "parent_account_identifier": "",
            "billing_email": email or "",
            "phone": phone or "",
            "security_deposit": "",
            "requires_po_number": "",
            "primary_contact_email": "",
        }
        add_review(
            reviews, "accounts", account_headers, values, dropped,
            "not_loaded",
            f"This is the same account as {kept} ({kept_row['TEN_NAME'].strip()}). The name, email, and phone match. I kept {kept} and pointed the leases at that one.",
            "Tell me if these are actually two different accounts and I will split them.",
        )

    for ident, record in account_rows.items():
        clean = {key: value for key, value in record.items() if not key.startswith("_")}
        ready["accounts"].append(clean)

    # Buildings.
    property_headers = template_headers("properties")
    for building in tables["buildings"]:
        zone, zone_problem = parse_timezone(building["TZ"], building["ST"])
        zip_code, zip_note = parse_zip(building["ZIP"])
        values = {
            "identifier": building["BLDG_ID"],
            "name": building["BLDG_NAME"].strip(),
            "portfolio_identifier": building["PORTFOLIO"].strip(),
            "timezone": zone or "",
            "address_one": (building.get("ADDR") or "").strip(),
            "city": (building.get("CITY") or "").strip(),
            "region_code": (building.get("ST") or "").strip().upper(),
            "zip": zip_code or "",
        }
        if not zone:
            add_review(
                reviews, "properties", property_headers, values, building["BLDG_ID"],
                "not_loaded",
                f"The time zone was written as \"{building['TZ']}\". I could not tell what that means, so I left this building out.",
                "Send the time zone, for example America/Phoenix or America/Denver.",
            )
            continue
        record = {
            "identifier": building["BLDG_ID"],
            "name": values["name"],
            "portfolio_identifier": values["portfolio_identifier"],
            "timezone": zone,
        }
        if values["address_one"]:
            record["address_one"] = values["address_one"]
        if values["city"]:
            record["city"] = values["city"]
        if values["region_code"]:
            record["region_code"] = values["region_code"]
        if zip_code:
            record["zip"] = zip_code
        ready["properties"].append(record)
        city = values["city"]
        state = values["region_code"]
        if city == "El Paso" and zone == "America/Chicago":
            zone_sentence = (
                f"The file said the time zone was \"{building['TZ']}\". I stored America/Chicago, which is Central time. "
                "El Paso is usually on Mountain time, so please check this."
            )
        elif state == "AZ":
            zone_sentence = (
                f"The file said the time zone was \"{building['TZ']}\". I stored America/Phoenix. "
                "This building is in Arizona, and Arizona does not switch clocks for daylight saving."
            )
        else:
            zone_sentence = f"The file said the time zone was \"{building['TZ']}\". I stored {zone}."
        notes = [zone_sentence]
        if zip_note:
            notes.append(zip_note)
        add_review(
            reviews, "properties", property_headers, values, building["BLDG_ID"],
            "loaded_with_changes",
            " ".join(notes),
            "Tell me if the time zone should be different.",
        )

    loaded_properties = {row["identifier"] for row in ready["properties"]}
    loaded_types = {row["identifier"] for row in ready["unit_types"]}
    loaded_vendors = {row["identifier"] for row in ready["vendors"]}

    unit_headers = template_headers("units")
    for unit in units:
        building_id = unit["BLDG_ID"]
        building_name = buildings.get(building_id, {}).get("BLDG_NAME", building_id)
        door = (unit["UNIT_NO"] or "").strip()
        sqft = parse_sqft(unit.get("SQFT"))
        rent, _rent_note = parse_money(unit.get("MKT_RENT"))
        vendor_id = (unit.get("MAINT_VENDOR") or "").strip()
        values = {
            "identifier": unit["UNIT_ID"],
            "property_identifier": building_id,
            "unit_type_identifier": (unit.get("TYPE_CODE") or "").strip(),
            "unit_number": door,
            "square_feet": "" if sqft is None else sqft,
            "market_rent": rent or "",
            "maintenance_vendor_identifier": vendor_id if vendor_id in loaded_vendors else "",
        }
        if building_id == SOLD_BUILDING or building_id not in loaded_properties:
            add_review(
                reviews, "units", unit_headers, values, unit["UNIT_ID"],
                "not_loaded",
                f"This is apartment {door} at Ocotillo Place, which you sold. I did not bring the apartment over.",
                "Nothing, unless this apartment is not really at Ocotillo Place.",
            )
            continue
        if unit["UNIT_ID"] in drop_units:
            other = drop_units[unit["UNIT_ID"]]
            add_review(
                reviews, "units", unit_headers, values, unit["UNIT_ID"],
                "not_loaded",
                f"This is the same door as {other}, apartment {door} at {building_name}. The other record is the one with the leases, so I kept that one. This copy has a different asking rent ({unit.get('MKT_RENT')}). I did not change the asking rent on the one I kept.",
                "Tell me if this is actually a second apartment, or if the asking rent should be the one on this copy.",
            )
            continue
        if values["unit_type_identifier"] not in loaded_types or not door:
            add_review(
                reviews, "units", unit_headers, values, unit["UNIT_ID"],
                "not_loaded",
                "This apartment is missing a floor plan or a door number, so I left it out.",
                "Send the floor plan and the door number.",
            )
            continue
        record = {
            "identifier": unit["UNIT_ID"],
            "property_identifier": building_id,
            "unit_type_identifier": values["unit_type_identifier"],
            "unit_number": door,
        }
        if sqft is not None:
            record["square_feet"] = sqft
        if rent is not None:
            record["market_rent"] = rent
        if vendor_id in loaded_vendors:
            record["maintenance_vendor_identifier"] = vendor_id
        ready["units"].append(record)

    loaded_units = {row["identifier"] for row in ready["units"]}
    lease_headers = template_headers("leases")
    line_headers = template_headers("lease_charge_lines")

    prepared_leases = []
    for lease in leases:
        ten_id = lease["TEN_NO"]
        kept = keeper_for(ten_id, merges) if ten_id in by_tenant else ten_id
        tenant = by_tenant.get(ten_id)
        tenant_name = tenant["TEN_NAME"].strip() if tenant else ten_id
        start = parse_date(lease["START_DT"])
        end = parse_date(lease["END_DT"])
        unit_ids = []
        line_records = []
        line_problem = None
        for charge in charges_for_lease[lease["LEASE_NO"]]:
            amount, amount_note = parse_money(charge["AMT"])
            kind = CHARGE.get(charge["CHG_TYPE"])
            if amount is None or kind is None:
                line_problem = f"Charge {charge['CHG_ID']} could not be read."
            else:
                line_records.append(
                    {
                        "unit_identifier": charge["UNIT_ID"],
                        "charge_type": kind,
                        "monthly_amount": amount,
                    }
                )
                unit_ids.append(charge["UNIT_ID"])
        door_unit = unit_ids[0] if unit_ids else ""
        unit = by_unit.get(door_unit, {})
        door = (unit.get("UNIT_NO") or "").strip()
        building_name = buildings.get(lease["BLDG_ID"], {}).get("BLDG_NAME", lease["BLDG_ID"])
        values = {
            "identifier": lease["LEASE_NO"],
            "account_identifier": kept if ten_id in by_tenant else ten_id,
            "property_identifier": lease["BLDG_ID"],
            "contact_email": "",
            "status": STATUS.get(lease["STATUS"], lease["STATUS"]),
            "start_date": start.isoformat() if start else lease["START_DT"],
            "end_date": end.isoformat() if end else lease["END_DT"],
            "po_number": (lease.get("PO_NO") or "").strip(),
        }
        occ_id = (lease.get("OCC_ID") or "").strip()
        contact_id = occ_alias.get(occ_id, occ_id)
        contact = loaded_occs.get(contact_id)
        if contact and contact["account_identifier"] == kept:
            values["contact_email"] = contact.get("email", "")

        def skip(issue, need):
            add_review(
                reviews, "leases", lease_headers, values, lease["LEASE_NO"],
                "not_loaded", issue, need,
            )

        if lease["STATUS"] == "D":
            skip(
                "This is still a draft. You said drafts are just ideas the leasing team typed in, so I left it out. The end date on it is not a real day.",
                "If this lease is actually signed, send the unit, the start date, the end date, and the rent.",
            )
            continue
        if lease["BLDG_ID"] == SOLD_BUILDING or lease["BLDG_ID"] not in loaded_properties:
            skip(
                f"This lease is at Ocotillo Place, which you sold. I left the lease out. I kept the tenant, {tenant_name}.",
                "Nothing, unless this lease is not really for Ocotillo Place.",
            )
            continue
        if ten_id not in by_tenant:
            skip(
                f"This lease points at tenant {ten_id}, and there is no tenant with that number.",
                "Tell me who the tenant is.",
            )
            continue
        if start is None or end is None or end < start:
            skip(
                "The start date or the end date is missing or backwards, so I left this lease out.",
                "Send the real start date and end date.",
            )
            continue
        account = account_rows[kept]
        if account.get("requires_po_number") and not values["po_number"]:
            skip(
                f"{account['name']} needs a PO number on every lease. This one does not have one, so I left it out.",
                "Send the PO number and I can add the lease.",
            )
            continue
        if line_problem or not any(line["charge_type"] == "rent" for line in line_records):
            skip(
                line_problem or "This lease has no rent charge, and I did not invent one.",
                "Send the monthly rent and the apartment it belongs to.",
            )
            continue
        bad_unit = next((line["unit_identifier"] for line in line_records if line["unit_identifier"] not in loaded_units), None)
        if bad_unit:
            skip(
                f"The apartment on this lease ({bad_unit}) is not coming over, so the lease stays out too.",
                "Tell me which apartment this lease belongs on.",
            )
            continue
        if any(by_unit[line["unit_identifier"]]["BLDG_ID"] != lease["BLDG_ID"] for line in line_records):
            skip(
                "A charge on this lease points at an apartment in a different building. I did not guess which one is right.",
                "Tell me the right apartment.",
            )
            continue
        prepared_leases.append(
            {
                "identifier": lease["LEASE_NO"],
                "account_identifier": kept,
                "property_identifier": lease["BLDG_ID"],
                "contact_legacy_id": contact["legacy_id"] if contact and contact["account_identifier"] == kept else "",
                "status": STATUS[lease["STATUS"]],
                "status_code": lease["STATUS"],
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "start": start,
                "end": end,
                "po_number": values["po_number"],
                "unit_id": door_unit,
                "door": door,
                "building_name": building_name,
                "charge_lines": line_records,
                "values": values,
            }
        )

    by_door = defaultdict(list)
    for lease in prepared_leases:
        if lease["status_code"] in HOLDING:
            by_door[lease["unit_id"]].append(lease)
    blocked = {}
    for unit_id, group in by_door.items():
        overlaps = defaultdict(set)
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                if left["start"] <= right["end"] and right["start"] <= left["end"]:
                    overlaps[left["identifier"]].add(right["identifier"])
                    overlaps[right["identifier"]].add(left["identifier"])
        seen = set()
        for lease in group:
            if lease["identifier"] in seen or lease["identifier"] not in overlaps:
                continue
            stack = [lease["identifier"]]
            names = []
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                names.append(current)
                stack.extend(overlaps[current])
            others = {name: [item for item in names if item != name] for name in names}
            blocked.update(others)

    for lease in prepared_leases:
        if lease["identifier"] in blocked:
            others = ", ".join(blocked[lease["identifier"]])
            add_review(
                reviews, "leases", lease_headers, lease["values"], lease["identifier"],
                "not_loaded",
                f"This lease and {others} are both open for apartment {lease['door']} at {lease['building_name']} on the same days. I could not tell which one is the real lease, so I left both out.",
                "Tell me which lease is the real one. If one of them ended, send the end date.",
            )
            continue
        record = {
            "identifier": lease["identifier"],
            "account_identifier": lease["account_identifier"],
            "property_identifier": lease["property_identifier"],
            "status": lease["status"],
            "start_date": lease["start_date"],
            "end_date": lease["end_date"],
            "charge_lines": lease["charge_lines"],
        }
        if lease["contact_legacy_id"]:
            record["contact_legacy_id"] = lease["contact_legacy_id"]
        if lease["po_number"]:
            record["po_number"] = lease["po_number"]
        ready["leases"].append(record)

    summary = {
        "merges": merges,
        "dropped_units": drop_units,
        "blocked_leases": blocked,
        "ready_counts": {name: len(rows) for name, rows in ready.items()},
        "review_counts": {name: len(rows) for name, rows in reviews.items()},
    }
    return ready, reviews, summary


def write_outputs(ready, reviews):
    READY.mkdir(parents=True, exist_ok=True)
    REVIEW.mkdir(parents=True, exist_ok=True)
    for name, rows in ready.items():
        (READY / f"{name}.json").write_text(json.dumps(rows, indent=2) + "\n")
    for old in REVIEW.glob("review_*.csv"):
        old.unlink()
    for sheet, rows in reviews.items():
        if not rows:
            continue
        headers = template_headers(sheet) + EXTRA
        path = REVIEW / f"review_{sheet}.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)


def main():
    ready, reviews, summary = decide()
    write_outputs(ready, reviews)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
