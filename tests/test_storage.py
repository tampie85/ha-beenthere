"""Storage validation, normalization and invalid targets."""

import unittest

from helpers import apply_change, migrate_data, normalize_data, valid_country_code, valid_name


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
        self.assertEqual(data, {
            "travellers": {}, "groups": {},
            "map_settings": {"subdivision_countries": ["GB"]},
        })

    def test_map_settings_default_and_normalization(self):
        self.assertEqual(normalize_data({})["map_settings"], {"subdivision_countries": ["GB"]})
        for enabled, expected in (
            ([], []), (["US", "GB", "US", "RU", {}, 1], ["GB", "US"]),
            (None, ["GB"]), ("US", ["GB"]),
        ):
            with self.subTest(enabled=enabled):
                self.assertEqual(normalize_data({"map_settings": {
                    "subdivision_countries": enabled,
                }})["map_settings"], {"subdivision_countries": expected})

    def test_migration_preserves_exact_history_and_does_not_mutate_source(self):
        original = {"travellers": {"alice": {
            "name": "Alice", "countries": ["US-CA", "US", "PT-20", "US-XX"],
        }}, "groups": {"family": {"name": "Family", "members": ["alice"]}}}
        migrated = migrate_data(1, 1, original)
        self.assertEqual(migrated["travellers"], original["travellers"])
        self.assertEqual(migrated["groups"], original["groups"])
        self.assertEqual(migrated["map_settings"], {"subdivision_countries": ["GB"]})
        self.assertNotIn("map_settings", original)
        migrated["travellers"]["alice"]["countries"].append("FR")
        self.assertNotIn("FR", original["travellers"]["alice"]["countries"])

    def test_migration_rejects_unknown_versions_instead_of_resetting(self):
        for major, minor in ((0, 1), (1, 2), (2, 1), (3, 1)):
            with self.subTest(version=(major, minor)), self.assertRaises(NotImplementedError):
                migrate_data(major, minor, {})
        with self.assertRaises(ValueError):
            migrate_data(1, 1, None)

    def test_set_visit_is_idempotent_and_preserves_explicit_children(self):
        data = normalize_data({"travellers": {"alice": {"name": "Alice", "countries": ["US-CA"]}}})
        message = {"target_id": "alice", "location": "US", "visited": True}
        apply_change(data, "set_visit", message)
        apply_change(data, "set_visit", message)
        self.assertEqual(data["travellers"]["alice"]["countries"], ["US", "US-CA"])
        message["visited"] = False
        apply_change(data, "set_visit", message)
        apply_change(data, "set_visit", message)
        self.assertEqual(data["travellers"]["alice"]["countries"], ["US-CA"])

    def test_set_visit_rejects_non_boolean_without_mutation(self):
        data = normalize_data({"travellers": {"alice": {"name": "Alice", "countries": ["US-CA"]}}})
        for value in (None, "false", 0, 1, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                apply_change(data, "set_visit", {"target_id": "alice", "location": "US", "visited": value})
        self.assertEqual(data["travellers"]["alice"]["countries"], ["US-CA"])

    def test_map_detail_is_global_idempotent_and_preserves_history(self):
        data = normalize_data({
            "travellers": {"alice": {"name": "Alice", "countries": ["GB-ENG", "US", "US-CA"]}},
            "groups": {"family": {"name": "Family", "members": ["alice"]}},
        })
        before = repr((data["travellers"], data["groups"]))
        for enabled in (True, True, False, False):
            apply_change(data, "set_map_detail", {"country": "us", "enabled": enabled})
            self.assertEqual(data["map_settings"]["subdivision_countries"], ["GB", "US"] if enabled else ["GB"])
            self.assertEqual(repr((data["travellers"], data["groups"])), before)
        apply_change(data, "set_map_detail", {"country": "GB", "enabled": False})
        self.assertEqual(data["map_settings"]["subdivision_countries"], [])
        self.assertEqual(normalize_data(data), data)

    def test_map_detail_rejects_invalid_requests_without_mutation(self):
        data = normalize_data({})
        before = repr(data)
        for message in (
            {"country": "RU", "enabled": True}, {"country": "FR", "enabled": True},
            {"country": "US-CA", "enabled": True}, {"country": "ZZ", "enabled": True},
            {"country": "US", "enabled": "true"}, {"country": "US", "enabled": 1},
            {"country": "US"}, {"enabled": True},
            {"country": "US", "enabled": True, "target_id": "alice"},
            {"country": "US", "enabled": True, "members": []},
            {"country": "US", "enabled": True, "map_settings": {}},
        ):
            with self.subTest(message=message), self.assertRaises(ValueError):
                apply_change(data, "set_map_detail", message)
            self.assertEqual(repr(data), before)