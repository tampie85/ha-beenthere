"""Focused tests for BeenThere storage operations."""

import unittest
import importlib.util
from pathlib import Path

_storage_path = Path(__file__).with_name("storage.py")
_storage_spec = importlib.util.spec_from_file_location("beenthere_storage", _storage_path)
_storage = importlib.util.module_from_spec(_storage_spec)
assert _storage_spec.loader is not None
_storage_spec.loader.exec_module(_storage)

apply_change = _storage.apply_change
normalize_data = _storage.normalize_data
valid_country_code = _storage.valid_country_code
valid_name = _storage.valid_name


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

    def test_add_and_rename_traveller(self):
        data = normalize_data({})
        apply_change(data, "add_traveller", {"name": " Alice "})
        ident = next(iter(data["travellers"]))
        self.assertEqual(data["travellers"][ident], {"name": "Alice", "countries": []})
        apply_change(data, "rename_traveller", {"target_id": ident, "name": "Bob"})
        self.assertEqual(data["travellers"][ident]["name"], "Bob")

    def test_update_and_delete_group(self):
        data = normalize_data({"travellers": {"one": {"name": "One"}}})
        apply_change(data, "add_group", {"name": "Old", "members": []})
        ident = next(iter(data["groups"]))
        apply_change(data, "update_group", {
            "target_id": ident, "name": "New", "members": ["one", "one"],
        })
        self.assertEqual(data["groups"][ident], {"name": "New", "members": ["one"]})
        apply_change(data, "delete_group", {"target_id": ident})
        self.assertEqual(data["groups"], {})
        self.assertIn("one", data["travellers"])

    def test_territories_and_legacy_visits_remain_independent(self):
        data = normalize_data({"travellers": {"one": {
            "name": "One", "countries": ["GF", "US-CA", "GB-ENG", "PT-20"],
        }}})
        apply_change(data, "toggle_country", {"target_id": "one", "country": "FR"})
        self.assertEqual(data["travellers"]["one"]["countries"], [
            "FR", "GB-ENG", "GF", "PT-20", "US-CA",
        ])

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

    def test_delete_traveller_removes_group_membership(self):
        data = normalize_data({
            "travellers": {
                "one": {"name": "One", "countries": []},
                "two": {"name": "Two", "countries": []},
            },
            "groups": {"group": {"name": "Group", "members": ["one", "two"]}},
        })
        apply_change(data, "delete_traveller", {"target_id": "one"})
        self.assertNotIn("one", data["travellers"])
        self.assertEqual(data["groups"]["group"]["members"], ["two"])

    def test_group_members_are_unique_and_country_toggle_is_sorted(self):
        data = normalize_data({"travellers": {"one": {"name": "One", "countries": []}}})
        apply_change(data, "toggle_country", {"target_id": "one", "country": "US-TX"})
        apply_change(data, "add_group", {"name": "Group", "members": ["one", "one"]})
        group = next(iter(data["groups"].values()))
        self.assertEqual(data["travellers"]["one"]["countries"], ["US-TX"])
        self.assertEqual(group["members"], ["one"])

    def test_unknown_targets_fail_without_mutating_data(self):
        data = normalize_data({})
        with self.assertRaises(ValueError):
            apply_change(data, "delete_group", {"target_id": "missing"})
        self.assertEqual(data, {"travellers": {}, "groups": {}})


if __name__ == "__main__":
    unittest.main()
