"""Focused tests for Visited Countries storage operations."""

import unittest
import importlib.util
from pathlib import Path

_storage_path = Path(__file__).with_name("storage.py")
_storage_spec = importlib.util.spec_from_file_location("visited_countries_storage", _storage_path)
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
