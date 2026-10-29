"""Storage validation, normalization and invalid targets."""

import unittest

from helpers import apply_change, normalize_data, valid_country_code, valid_name


class StorageValidationTests(unittest.TestCase):
    def test_country_codes_include_subdivisions(self):
        for code in ("GB-ENG", "PT-20", "US-CA", "FR"):
            self.assertEqual(valid_country_code(code.lower()), code)

    def test_invalid_values_are_rejected(self):
        with self.assertRaises(ValueError):
            valid_name(None)
        with self.assertRaises(ValueError):
            valid_country_code("US-INVALID")

    def test_name_length_boundaries(self):
        self.assertEqual(valid_name(" x "), "x")
        self.assertEqual(valid_name("x" * 80), "x" * 80)
        for value in ("", "  ", "x" * 81):
            with self.subTest(value=value), self.assertRaises(ValueError):
                valid_name(value)

    def test_malformed_group_members_are_normalized(self):
        for members in (None, 42, "one", {"one": True}):
            with self.subTest(members=members):
                data = normalize_data({
                    "travellers": {"one": {"name": "One", "countries": []}},
                    "groups": {"group": {"name": "Group", "members": members}},
                })
                self.assertEqual(data["groups"]["group"]["members"], [])
                self.assertIn("one", data["travellers"])

    def test_normalize_data_removes_invalid_records_and_members(self):
        data = normalize_data({
            "travellers": {
                "valid": {"name": " Alice ", "countries": ["fr", "US-CA", "bad"]},
                "invalid": {"name": ""},
            },
            "groups": {
                "group": {"name": " Family ", "members": ["valid", "missing", "valid"]},
            },
        })
        self.assertEqual(data["travellers"], {
            "valid": {"name": "Alice", "countries": ["FR", "US-CA"]},
        })
        self.assertEqual(data["groups"], {
            "group": {"name": "Family", "members": ["valid"]},
        })

    def test_unknown_targets_fail_without_mutating_data(self):
        data = normalize_data({})
        with self.assertRaises(ValueError):
            apply_change(data, "delete_group", {"target_id": "missing"})
        self.assertEqual(data, {"travellers": {}, "groups": {}})