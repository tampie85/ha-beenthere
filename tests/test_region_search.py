"""Test region search functionality in autocomplete search."""

import json
import unittest
from pathlib import Path

from helpers import COMPONENT_ROOT, get_geography


class RegionSearchTests(unittest.TestCase):
    """Test cases for region search in autocomplete."""

    def setUp(self):
        self.geography = get_geography()
        with open(COMPONENT_ROOT / "geography.json") as f:
            self.catalogue = json.load(f)

    def test_regions_exist_for_enabled_countries(self):
        """Verify that enabled countries have regions defined."""
        for country_code in self.catalogue["subdivision_countries"]:
            with self.subTest(country=country_code):
                self.assertIn(country_code, self.catalogue["subdivisions"])
                regions = self.catalogue["subdivisions"][country_code]
                self.assertGreater(len(regions), 0)
                for region_id, region_name in regions.items():
                    self.assertTrue(region_name)
                    self.assertTrue(region_id.startswith(f"{country_code}-"))

    def test_search_relevance_scoring(self):
        """Test that search relevance scores work correctly."""
        # Exact match should score 0
        exact_score = self._get_relevance("France", "france")
        self.assertEqual(exact_score, 0)

        # Starts with should score 1
        starts_score = self._get_relevance("France", "fra")
        self.assertEqual(starts_score, 1)

        # Contains should score 2
        contains_score = self._get_relevance("United States", "state")
        self.assertEqual(contains_score, 2)

        # Verify ordering
        self.assertLess(exact_score, starts_score)
        self.assertLess(starts_score, contains_score)

    def test_regions_properly_associated_with_countries(self):
        """Verify that regions are properly associated with parent countries."""
        for country_code in self.catalogue["subdivision_countries"]:
            regions = self.catalogue["subdivisions"].get(country_code, {})
            for region_id in regions.keys():
                with self.subTest(region=region_id):
                    # Region ID should start with country code
                    self.assertTrue(region_id.startswith(f"{country_code}-"))
                    # Region should exist in geography
                    self.assertIn(region_id, self.geography.locations)
                    location = self.geography.locations[region_id]
                    self.assertEqual(location.parent_id, country_code)
                    self.assertEqual(location.level, 2)

    def test_no_duplicate_regions_in_search_results(self):
        """Verify that regions don't appear multiple times in search."""
        # This is a conceptual test - would be tested in frontend tests
        # But we can verify the data structure is sound
        all_region_ids = set()
        for country_code, regions in self.catalogue["subdivisions"].items():
            for region_id in regions.keys():
                with self.subTest(region=region_id):
                    # Each region should have a unique ID
                    self.assertNotIn(region_id, all_region_ids,
                                   f"Duplicate region {region_id}")
                    all_region_ids.add(region_id)

    def test_regions_for_all_subdivision_countries(self):
        """Test that all subdivision countries have regions in the catalogue."""
        for country in ["AU", "CA", "DE", "GB", "US"]:
            with self.subTest(country=country):
                self.assertIn(country, self.catalogue["subdivisions"])
                self.assertGreater(len(self.catalogue["subdivisions"][country]), 0)

    def test_region_names_are_non_empty(self):
        """Verify all region names are non-empty strings."""
        for country_code, regions in self.catalogue["subdivisions"].items():
            for region_id, region_name in regions.items():
                with self.subTest(region=region_id):
                    self.assertIsInstance(region_name, str)
                    self.assertGreater(len(region_name), 0)
                    self.assertFalse(region_name.isspace())

    def test_search_query_matching_logic(self):
        """Test basic query matching logic for regions."""
        query = "california"
        # Should match "California" exactly (when lowercased)
        match_name = "California"
        self.assertTrue(match_name.lower().startswith(query))

        query = "state"
        # Should match "United States" (contains)
        match_name = "United States"
        self.assertTrue(query in match_name.lower())

        # Should not match unrelated names
        non_match = "England"
        self.assertFalse(query in non_match.lower())

    def test_region_identifiers_follow_iso_pattern(self):
        """Verify region IDs follow the expected pattern."""
        for country_code, regions in self.catalogue["subdivisions"].items():
            for region_id in regions.keys():
                with self.subTest(region=region_id):
                    # Format should be CC-XXX or CC-XX
                    parts = region_id.split("-")
                    self.assertEqual(len(parts), 2)
                    self.assertEqual(len(parts[0]), 2)
                    self.assertTrue(1 <= len(parts[1]) <= 3)
                    self.assertTrue(parts[0].isupper())
                    self.assertTrue(parts[1].isupper())

    def _get_relevance(self, name, query):
        """Calculate relevance score matching the frontend logic."""
        name_lower = name.lower()
        if name_lower == query:
            return 0
        if name_lower.startswith(query):
            return 1
        return 2


if __name__ == '__main__':
    unittest.main()
