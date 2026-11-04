"""Geographic identifiers, hierarchy and explicit visit semantics."""

import json
import math
import unittest

from helpers import COMPONENT_ROOT, get_geography, normalize_data, valid_country_code


class GeographyTests(unittest.TestCase):
    def setUp(self):
        self.geography = get_geography()

    def test_bundled_maps_cover_exact_catalogue_ids_and_valid_boundaries(self):
        for country in sorted(self.geography.subdivision_countries):
            with self.subTest(country=country):
                self.assert_bundled_map(country)

    def assert_bundled_map(self, country):
        data = json.loads((COMPONENT_ROOT / f"frontend/maps/{country}.geojson").read_text())
        self.assertEqual(data["type"], "FeatureCollection")
        features = data["features"]
        expected = {node.id for node in self.geography.locations.values() if node.parent_id == country}
        self.assertEqual(len(features), len(expected))
        self.assertEqual({feature["properties"]["id"] for feature in features}, expected)
        self.assertIn("public domain", data["source"])
        for feature in features:
            with self.subTest(location=feature["id"]):
                self.assertEqual(feature["id"], feature["properties"]["id"])
                self.assertEqual(feature["properties"]["name"], self.geography.locations[feature["id"]].name)
                geometry = feature["geometry"]
                self.assertIn(geometry["type"], {"Polygon", "MultiPolygon"})
                polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
                self.assertTrue(polygons)
                for polygon in polygons:
                    for ring in polygon:
                        self.assertGreaterEqual(len(ring), 4)
                        self.assertEqual(ring[0], ring[-1])
                        for lon, lat in ring:
                            self.assertTrue(math.isfinite(lon) and math.isfinite(lat))
                            self.assertTrue(-180 <= lon <= 180 and -90 <= lat <= 90)

    def test_exact_supported_subdivision_counts(self):
        self.assertEqual(self.geography.subdivision_countries, {"GB", "US", "AU", "CA", "DE"})
        for parent, count in {"GB": 4, "US": 51, "AU": 8, "CA": 13, "DE": 16}.items():
            with self.subTest(parent=parent):
                children = [node for node in self.geography.locations.values() if node.parent_id == parent]
                self.assertEqual(len(children), count)
                self.assertTrue(all(node.level == 2 for node in children))

    def test_catalogue_contains_249_iso_countries_and_existing_map_exception(self):
        countries = [node for node in self.geography.locations.values() if node.level == 1]
        self.assertEqual(len(countries), 250)
        self.assertTrue(all(node.parent_id is None for node in countries))
        self.assertEqual(self.geography.non_iso_country_ids, {"XK"})
        self.assertEqual(valid_country_code("xk"), "XK")

    def test_new_writes_require_catalogue_membership(self):
        for code in ("ZZ", "US-XX", "US-PR", "RU-MOW", "AU-CX", "DE-XYZ"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                valid_country_code(code)
        for code in ("US-DC", "AU-ACT", "CA-NU", "DE-HB", "GB-NIR", "PT-20", "RU"):
            self.assertEqual(valid_country_code(code.lower()), code)

    def test_country_derivation_does_not_infer_siblings_or_merge_territories(self):
        explicit = {"US-CA", "US-FL", "GB-ENG", "GF"}
        self.assertEqual(self.geography.visited_countries(explicit), {"US", "GB", "GF"})
        self.assertEqual(self.geography.visited_subdivisions(explicit), {"US-CA", "US-FL", "GB-ENG"})
        self.assertEqual(explicit, {"US-CA", "US-FL", "GB-ENG", "GF"})
        self.assertEqual(self.geography.visited_subdivisions({"US"}), set())

    def test_country_visitors_include_children_but_subdivisions_require_exact_visit(self):
        histories = {"alice": ["US-CA"], "bob": ["US"], "carol": ["US-FL"], "dave": []}
        self.assertEqual(self.geography.visitors(histories, "US"), {"alice", "bob", "carol"})
        self.assertEqual(self.geography.visitors(histories, "US-CA"), {"alice"})

    def test_unknown_persisted_ids_survive_without_inferred_parents(self):
        data = normalize_data({"travellers": {"alice": {
            "name": "Alice", "countries": ["US-XX", "ZZ", "INVALID", "US-CA"],
        }}})
        codes = data["travellers"]["alice"]["countries"]
        self.assertEqual(codes, ["US-CA", "US-XX", "ZZ"])
        self.assertEqual(self.geography.visited_countries(codes), {"US"})

    def test_catalogue_rejects_bad_relationships_and_versions(self):
        geography_type = type(self.geography)
        valid = {"version": 1, "countries": {"North America": {"US": "United States"}},
                 "subdivisions": {"US": {"US-CA": "California"}}, "subdivision_countries": ["US"]}
        for overrides in (
            {"version": 2}, {"subdivisions": {"CA": {"CA-AB": "Alberta"}}},
            {"subdivisions": {"US": {"CA-AB": "Alberta"}}},
            {"subdivision_countries": ["RU"]}, {"non_iso_country_ids": ["ZZ"]},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                geography_type(valid | overrides)