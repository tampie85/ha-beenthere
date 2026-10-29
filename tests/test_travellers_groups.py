"""Traveller and group operations, membership and territory visits."""

import unittest

from helpers import apply_change, normalize_data


class TravellersAndGroupsTests(unittest.TestCase):
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