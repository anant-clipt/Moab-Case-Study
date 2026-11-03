"""Checks for the small decisions: phones, dates, money, and who is a duplicate."""

import unittest
from datetime import date

from common import (
    find_merges,
    months_overlapping,
    parse_date,
    parse_email,
    parse_money,
    parse_phone,
    parse_terms,
    parse_timezone,
    parse_zip,
    load_tables,
)


class CleanTests(unittest.TestCase):
    def test_phone_keeps_the_number_and_drops_the_extension(self):
        phone, note = parse_phone("505-555-3369 x24")
        self.assertEqual(phone, "+15055553369")
        self.assertIn("extension", note)

    def test_phone_without_an_area_code_is_left_off(self):
        phone, note = parse_phone("555-1234")
        self.assertIsNone(phone)
        self.assertIn("area code", note)

    def test_dates_and_money(self):
        self.assertEqual(parse_date("01-Apr-24"), date(2024, 4, 1))
        self.assertEqual(parse_date("02/28/2025"), date(2025, 2, 28))
        self.assertEqual(parse_date("0000-00-00"), None)
        self.assertEqual(parse_money("$1,400.00")[0], "1400.00")
        self.assertIsNone(parse_money("-1")[0])
        self.assertIsNone(parse_money("N/A")[0])

    def test_zip_timezone_and_terms(self):
        self.assertEqual(parse_zip("79950-7595")[0], "79950")
        self.assertEqual(parse_timezone("CST", "TX")[0], "America/Chicago")
        self.assertEqual(parse_timezone("Arizona", "AZ")[0], "America/Phoenix")
        self.assertEqual(parse_timezone("MST", "NM")[0], "America/Denver")
        self.assertEqual(parse_terms("net 45 days")[0], "net_45")
        self.assertEqual(parse_terms("COD")[0], "due_on_receipt")
        self.assertEqual(parse_terms("N30")[0], "net_30")

    def test_bad_email(self):
        self.assertIsNone(parse_email("zoe.hart@outlook")[0])
        self.assertEqual(parse_email(" OLIVIA.ANDERSON@GMAIL.COM ")[0], "olivia.anderson@gmail.com")

    def test_the_four_duplicate_accounts(self):
        tenants = load_tables()["tenants"]
        merges = find_merges(tenants)
        self.assertEqual(
            merges,
            {
                "T-1149": "T-1084",
                "T-1147": "T-1105",
                "T-1148": "T-1122",
                "T-1146": "T-1118",
            },
        )

    def test_a_full_year_of_rent_is_twelve_months(self):
        self.assertEqual(
            months_overlapping(date(2025, 1, 1), date(2025, 12, 31), 2025),
            12,
        )
        self.assertEqual(
            months_overlapping(date(2024, 6, 1), date(2025, 5, 31), 2025),
            5,
        )


if __name__ == "__main__":
    unittest.main()
