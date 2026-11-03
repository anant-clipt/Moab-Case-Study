"""Answer the three questions from LeaseLedger, not from what landed in Keystone.

Writes data/answers.json. Prints the working so I can see why a number came out
the way it did.
"""

import json
import sys
from calendar import monthrange
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import find_merges, keeper_for, load_tables, months_overlapping, parse_date, parse_money

AS_OF = date(2026, 10, 1)
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "answers.json"


def rent_by_lease(charges):
    rents = {}
    for charge in charges:
        if charge["CHG_TYPE"] != "RENT":
            continue
        amount, problem = parse_money(charge["AMT"])
        if problem or amount is None:
            raise SystemExit(f"Could not read rent on {charge['CHG_ID']}")
        rents.setdefault(charge["LEASE_NO"], []).append((charge["UNIT_ID"], float(amount)))
    return rents


def month_aligned(start, end):
    last = monthrange(end.year, end.month)[1]
    return start.day == 1 and end.day == last


def overlapping_pairs(leases, rents):
    """Active or notice leases that claim the same apartment on the same days."""
    by_unit = defaultdict(list)
    for lease in leases:
        if lease["status"] not in ("A", "N"):
            continue
        for unit_id, _amount in rents.get(lease["id"], []):
            by_unit[unit_id].append(lease)
    blocked = {}
    for _unit_id, group in by_unit.items():
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                if left["start"] <= right["end"] and right["start"] <= left["end"]:
                    blocked.setdefault(left["id"], set()).add(right["id"])
                    blocked.setdefault(right["id"], set()).add(left["id"])
    return blocked


def prepare():
    tables = load_tables()
    merges = find_merges(tables["tenants"])
    names = {row["TEN_NO"]: row["TEN_NAME"].strip() for row in tables["tenants"]}
    rents = rent_by_lease(tables["charges"])
    buildings = {row["BLDG_ID"]: row["BLDG_NAME"] for row in tables["buildings"]}
    units = tables["units"]

    leases = []
    for row in tables["leases"]:
        start = parse_date(row["START_DT"])
        end = parse_date(row["END_DT"])
        leases.append(
            {
                "id": row["LEASE_NO"],
                "tenant": row["TEN_NO"],
                "kept": keeper_for(row["TEN_NO"], merges) if row["TEN_NO"] in names else row["TEN_NO"],
                "building": row["BLDG_ID"],
                "status": row["STATUS"],
                "start": start,
                "end": end,
                "raw_start": row["START_DT"],
                "raw_end": row["END_DT"],
            }
        )
    return tables, merges, names, rents, buildings, units, leases


def billed_rent(leases, rents):
    ours = defaultdict(float)
    report_style = defaultdict(float)
    cancelled = defaultdict(list)
    skipped_unreadable = []
    for lease in leases:
        if lease["status"] == "D":
            continue
        if lease["start"] is None or lease["end"] is None or lease["end"] < lease["start"]:
            skipped_unreadable.append(lease["id"])
            continue
        if not month_aligned(lease["start"], lease["end"]):
            raise SystemExit(f"{lease['id']} is not a full-month lease, so the month count needs another look")
        if lease["id"] not in rents:
            skipped_unreadable.append(lease["id"])
            continue
        amount = sum(value for _unit, value in rents[lease["id"]])
        months = months_overlapping(lease["start"], lease["end"], 2025)
        if months == 0:
            continue
        total = round(amount * months, 2)
        report_style[lease["building"]] += total
        if lease["status"] == "X":
            cancelled[lease["building"]].append((lease["id"], total, lease["tenant"]))
            continue
        ours[lease["building"]] += total
    return ours, report_style, cancelled, skipped_unreadable


def top_accounts(leases, rents, names):
    blocked = overlapping_pairs(leases, rents)
    blocked_ids = set(blocked)
    totals = defaultdict(float)
    included_anyway = defaultdict(float)
    for lease in leases:
        if lease["status"] not in ("A", "N"):
            continue
        if lease["start"] is None or lease["end"] is None:
            continue
        if not (lease["start"] <= AS_OF <= lease["end"]):
            continue
        if lease["id"] not in rents:
            continue
        amount = sum(value for _unit, value in rents[lease["id"]])
        annual = round(amount * 12, 2)
        included_anyway[lease["kept"]] += annual
        if lease["id"] in blocked_ids:
            continue
        totals[lease["kept"]] += annual
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    other = sorted(included_anyway.items(), key=lambda item: (-item[1], item[0]))
    return ranked, other, blocked, names


def occupancy(leases, rents, units):
    real_units = defaultdict(set)
    for unit in units:
        if unit["BLDG_ID"] == "B-09":
            continue
        real_units[unit["BLDG_ID"]].add(unit["UNIT_ID"])
    # The second copy of a door is not a second apartment.
    doors = defaultdict(list)
    for unit in units:
        doors[(unit["BLDG_ID"], unit["UNIT_NO"].strip())].append(unit["UNIT_ID"])
    extras = set()
    for ids in doors.values():
        if len(ids) < 2:
            continue
        ranked = sorted(ids, key=lambda unit_id: int(unit_id.split("-")[1]))
        # Keep the lower id, which is the one the leases point at.
        extras.update(ranked[1:])
    for building, ids in real_units.items():
        real_units[building] = ids - extras

    occupied = defaultdict(set)
    for lease in leases:
        if lease["status"] not in ("A", "N"):
            continue
        if lease["start"] is None or lease["end"] is None:
            continue
        if not (lease["start"] <= AS_OF <= lease["end"]):
            continue
        if lease["building"] == "B-09":
            continue
        for unit_id, _amount in rents.get(lease["id"], []):
            if unit_id in real_units[lease["building"]]:
                occupied[lease["building"]].add(unit_id)
    fractions = {}
    detail = {}
    for building in sorted(real_units):
        denom = len(real_units[building])
        numer = len(occupied[building])
        fractions[building] = round(numer / denom, 4)
        detail[building] = (numer, denom)
    return fractions, detail


def money(value):
    return round(value, 2)


def main():
    _tables, merges, names, rents, _buildings, units, leases = prepare()
    ours, report_style, cancelled, skipped = billed_rent(leases, rents)
    report = {row["BLDG_ID"]: row["BILLED_RENT"] for row in _tables["rent_report"]["rows"]}

    print("Q1 ours vs report vs report-style (includes cancelled)")
    q1 = {}
    for building in ["B-01", "B-02", "B-03", "B-04", "B-05", "B-06", "B-07", "B-09"]:
        q1[building] = money(ours[building])
        print(
            building,
            "ours", q1[building],
            "report", report[building],
            "with cancelled", money(report_style[building]),
            "cancelled", cancelled.get(building, []),
        )
    print("unreadable leases skipped", skipped)

    ranked, other, blocked, names = top_accounts(leases, rents, names)
    print("\nQ2 blocked leases", {k: sorted(v) for k, v in blocked.items()})
    print("top 8 excluding blocked")
    for account, total in ranked[:8]:
        print(f"  {account} {names.get(account)} {money(total)}")
    print("top 8 if blocked leases were counted")
    for account, total in other[:8]:
        print(f"  {account} {names.get(account)} {money(total)}")

    fractions, detail = occupancy(leases, rents, units)
    print("\nQ3")
    for building, (numer, denom) in detail.items():
        print(f"  {building} {numer}/{denom} = {fractions[building]}")

    print("\nmerges", merges)

    answers = {
        "q1_billed_rent_2025": q1,
        "q1_explanation": q1_explanation(q1, report, cancelled),
        "q2_top_accounts": [
            {"account": account, "annualized_rent": money(total)}
            for account, total in ranked[:5]
        ],
        "q2_explanation": q2_explanation(ranked[:5], names, blocked),
        "q3_occupancy": fractions,
        "q3_explanation": q3_explanation(detail),
    }
    OUT.write_text(json.dumps(answers, indent=2, ensure_ascii=False) + "\n")
    print("\nwrote", OUT)


def q1_explanation(ours, report, cancelled):
    higher = []
    for building in ["B-01", "B-02", "B-03", "B-04", "B-05", "B-06", "B-07", "B-09"]:
        gap = round(report[building] - ours[building], 2)
        if not gap:
            continue
        bits = " and ".join(f"{lease_id} (${amount:,.0f})" for lease_id, amount, _tenant in cancelled[building])
        label = "lease" if len(cancelled[building]) == 1 else "leases"
        higher.append(f"{building} is ${gap:,.0f} higher because of cancelled {label} {bits}")
    gap_sentence = ". ".join(higher)
    return (
        "I counted rent only. Parking, pet, and storage fees stayed out, because the question is about rent. "
        "For each lease I took the monthly rent times the number of months in 2025 the lease actually covered. "
        "Every lease in the file starts on the first of a month and ends on the last day of a month, so each of those months is a full month of rent. "
        "I left out drafts, because those are not real leases yet, and I left out cancelled leases, because a cancelled lease is not rent Mesa billed. "
        "Ocotillo Place is in this answer. The building was sold and did not move to Keystone, but the 2025 rent on those leases was still billed. "
        f"LeaseLedger's report matches my numbers if the cancelled leases are put back in. {gap_sentence}. "
        "B-06 and B-09 match the report exactly, because neither had a cancelled lease in 2025."
    )


def q2_explanation(top, names, blocked):
    listed = ", ".join(f"{account} ({names[account]}, ${total:,.0f})" for account, total in top)
    conflicts = []
    seen = set()
    for lease_id, others in blocked.items():
        pair = tuple(sorted([lease_id, *[item for item in others if item.startswith("L-")]]))
        if pair in seen:
            continue
        seen.add(pair)
        conflicts.append(" and ".join(pair))
    conflict_sentence = "; ".join(conflicts)
    return (
        "As of October 1, 2026, I counted leases that were active or on notice and that covered that day. "
        "A notice lease still counts, because the tenant has given notice and is still in the lease. "
        "Annualized rent is the monthly rent times 12. I used rent only, not parking, pet, or storage. "
        "Where the same person or company was typed in twice, I added their leases together under the tenant number I kept. "
        f"The five are {listed}. Desert Sky includes the leases that were sitting on duplicate account T-1146. "
        f"Two apartments each have two active leases on the same days ({conflict_sentence}). "
        "I left those four leases out, because counting both would bill one apartment twice. "
        "The top five are the same if those leases are counted. Those tenants are much smaller than this list. "
        "I also did not add child companies onto their parent. SWMG Tucson Residency Housing and SWMG Travel Nurse Program are separate tenant numbers under Southwest Medical Group. "
        "Added together with the parent's own $15,000, that group is $186,900, which would make it the biggest customer. "
        "I kept them separate because the question asks for a tenant number, and these are different accounts, not the same account typed twice."
    )


def q3_explanation(detail):
    bits = ", ".join(f"{building} is {numer} of {denom}" for building, (numer, denom) in detail.items())
    return (
        "For each building that still exists, occupancy is the apartments with an active or notice lease covering October 1, 2026, divided by the apartments at that building. "
        "A fraction of 1 would mean every apartment is full. "
        "An apartment with two leases on it counts once. I also did not count a second copy of a door that was typed in twice, because that is one apartment. "
        "Drafts do not make an apartment full, and neither does a lease that had already ended. "
        "Ocotillo Place is not in this answer. The building was sold and deleted, so it is not a property Mesa is filling. "
        f"The counts are {bits}. I rounded each fraction to four decimal places."
    )


if __name__ == "__main__":
    main()
