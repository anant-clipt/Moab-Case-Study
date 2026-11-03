"""Shared rules for reading Mesa's old files.

The download step saves the files unchanged. Everything that decides
what a value means lives here, so the later steps do not drift apart.
"""

import csv
import json
import re
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

SOLD_BUILDING = "B-09"
AS_OF = date(2026, 10, 1)

STATUS = {
    "D": "draft",
    "P": "pending",
    "A": "active",
    "N": "notice",
    "E": "ended",
    "X": "cancelled",
}
CHARGE = {"RENT": "rent", "PARK": "parking", "PET": "pet", "STOR": "storage"}

# Active and notice leases are the ones Keystone will not let overlap.
HOLDING = {"A", "N"}


def read_csv(path):
    raw = Path(path).read_bytes()
    text = None
    for encoding in ("utf-8", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise SystemExit(f"Could not read {path}")
    return list(csv.DictReader(text.splitlines()))


def read_json(path):
    return json.loads(Path(path).read_text())


def load_tables():
    return {
        "buildings": read_json(RAW / "bldgs.json"),
        "occupants": read_json(RAW / "occupants.json"),
        "portfolios": read_json(RAW / "portfolios.json"),
        "unit_types": read_json(RAW / "unit_types.json"),
        "vendors": read_json(RAW / "vendors.json"),
        "leases": read_csv(RAW / "leases.csv"),
        "charges": read_csv(RAW / "lease_charges.csv"),
        "tenants": read_csv(RAW / "tenants.csv"),
        "units": read_csv(RAW / "units.csv"),
        "rent_report": read_json(RAW / "rent_roll_2025.json"),
    }


def norm_name(value):
    text = (value or "").lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def name_tokens(value):
    return tuple(sorted(norm_name(value).split()))


def parse_date(value):
    """Read a date the way the leasing office typed it.

    Slash dates are month/day/year. We know that because some of them
    are 02/28 and 04/30, which only make sense that way.
    """
    text = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%y", "%d-%b-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_money(value):
    """Turn '$1,400.00' into '1400.00'. Blank, N/A, and negatives come back empty."""
    text = (value or "").strip()
    if not text:
        return None, None
    if text.lower() in {"n/a", "na", "none", "null"}:
        return None, "was not a number"
    cleaned = text.replace("$", "").replace(",", "").replace("(", "").replace(")", "").strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
        return None, "was not a number"
    amount = float(cleaned)
    if amount < 0:
        return None, "was negative"
    return f"{amount:.2f}", None


def parse_phone(value):
    """Return (phone or None, note or None).

    A note means we dropped something Carmen should see. Rewriting
    dashes into the standard +1 shape is quiet, because the number
    itself did not change.
    """
    original = (value or "").strip()
    if not original:
        return None, None
    text = original
    extension = re.search(r"(?:ext\.?|x)\s*\d+\s*$", text, re.I)
    if extension:
        text = text[: extension.start()]
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        phone = "+1" + digits
        if extension:
            return phone, "We kept the number and left off the extension."
        return phone, None
    if len(digits) == 7:
        return None, "The phone has no area code, so we left it off."
    return None, "We could not read the phone, so we left it off."


def phone_key(value):
    phone, _note = parse_phone(value)
    if not phone:
        return None
    return phone[-10:]


def parse_email(value):
    text = (value or "").strip().lower()
    if not text:
        return None, None
    if text in {"n/a", "na", "none", "null"}:
        return None, "The email was not a real address, so we left it off."
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text):
        return text, None
    return None, "The email is missing part of the address, so we left it off."


def parse_zip(value):
    text = (value or "").strip()
    match = re.fullmatch(r"(\d{5})(?:-\d{4})?", text)
    if not match:
        if text:
            return None, "We could not read the ZIP, so we left it off."
        return None, None
    zip_code = match.group(1)
    if text != zip_code:
        return zip_code, f"The ZIP was {text}. We kept the first five digits, {zip_code}."
    return zip_code, None


def parse_timezone(value, state):
    key = re.sub(r"[^a-z]", "", (value or "").lower())
    arizona = (state or "").strip().upper() == "AZ"
    if key in {"arizona", "az"}:
        return "America/Phoenix", None
    if key in {"mst", "mountain", "mt"}:
        if arizona:
            return "America/Phoenix", None
        return "America/Denver", None
    if key in {"cst", "central", "ct"}:
        return "America/Chicago", None
    if key in {"pst", "pdt", "pacific", "pt"}:
        return "America/Los_Angeles", None
    if key.startswith("america"):
        # Already an official name. Keep it if it is one we know.
        return None, "unrecognized"
    return None, "unrecognized"


def parse_terms(value):
    key = re.sub(r"[^a-z0-9]", "", (value or "").lower())
    table = {
        "cod": ("due_on_receipt", "Due on receipt"),
        "dueonreceipt": ("due_on_receipt", "Due on receipt"),
        "net10": ("net_10", "Net 10"),
        "10days": ("net_10", "Net 10"),
        "net15": ("net_15", "Net 15"),
        "15days": ("net_15", "Net 15"),
        "net30": ("net_30", "Net 30"),
        "n30": ("net_30", "Net 30"),
        "30days": ("net_30", "Net 30"),
        "net45": ("net_45", "Net 45"),
        "net45days": ("net_45", "Net 45"),
        "45days": ("net_45", "Net 45"),
        "net60": ("net_60", "Net 60"),
        "60days": ("net_60", "Net 60"),
    }
    return table.get(key)


def parse_sqft(value):
    text = (value or "").replace(",", "")
    match = re.search(r"\d+", text)
    if not match:
        return None
    return int(match.group(0))


def months_overlapping(start, end, year):
    """How many calendar months of `year` this lease covers.

    Every lease in this file starts on the 1st and ends on the last day
    of a month, so a touched month is a full month of rent.
    """
    window_start = date(year, 1, 1)
    window_end = date(year, 12, 31)
    if end < window_start or start > window_end:
        return 0
    first = max(start, window_start)
    last = min(end, window_end)
    return (last.year - first.year) * 12 + last.month - first.month + 1


def covers(start, end, day):
    return start <= day <= end


class UnionFind:
    def __init__(self):
        self.parent = {}

    def add(self, item):
        self.parent.setdefault(item, item)

    def find(self, item):
        self.add(item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left, right):
        self.parent[self.find(left)] = self.find(right)


def find_merges(tenants):
    """Map a duplicate tenant number to the one we keep.

    We only join two records when it is clearly the same person or company.
    The same name by itself is not enough. We keep the lower tenant number.
    """
    by_id = {row["TEN_NO"]: row for row in tenants}
    ids = list(by_id)
    uf = UnionFind()
    for ten_id in ids:
        uf.add(ten_id)

    def same_person(left, right):
        email_l, _ = parse_email(left["EMAIL"])
        email_r, _ = parse_email(right["EMAIL"])
        phone_l = phone_key(left["PHONE"])
        phone_r = phone_key(right["PHONE"])
        tokens_l = name_tokens(left["TEN_NAME"])
        tokens_r = name_tokens(right["TEN_NAME"])
        same_email = bool(email_l and email_l == email_r)
        same_phone = bool(phone_l and phone_l == phone_r)
        same_name = bool(tokens_l and tokens_l == tokens_r)
        if same_email and (same_phone or same_name):
            return True
        if same_phone and same_name:
            return True
        return False

    for i, left_id in enumerate(ids):
        for right_id in ids[i + 1 :]:
            if same_person(by_id[left_id], by_id[right_id]):
                uf.union(left_id, right_id)

    groups = {}
    for ten_id in ids:
        groups.setdefault(uf.find(ten_id), []).append(ten_id)

    merges = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        keeper = min(members, key=lambda item: int(item.split("-")[1]))
        for member in members:
            if member != keeper:
                merges[member] = keeper
    return merges


def keeper_for(ten_id, merges):
    return merges.get(ten_id, ten_id)


def template_headers(sheet):
    path = RAW / "templates" / f"{sheet}.csv"
    with path.open(newline="") as handle:
        return next(csv.reader(handle))
