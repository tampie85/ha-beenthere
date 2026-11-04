"""Shared geographic catalogue and explicit-visit derivation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from types import MappingProxyType


LOCATION_ID_PATTERN = re.compile(r"^[A-Z]{2}(?:-[A-Z0-9]{1,3})?$")


@dataclass(frozen=True, slots=True)
class Location:
    """One stable location independent of map geometry or visit history."""

    id: str
    name: str
    level: int
    parent_id: str | None
    continent: str


class Geography:
    """Validated immutable catalogue shared by storage and geographic helpers."""

    def __init__(self, value: dict) -> None:
        if value.get("version") != 1:
            raise ValueError("Unsupported geographic catalogue version")
        locations = {}
        for continent, countries in value["countries"].items():
            for code, name in countries.items():
                if not re.fullmatch(r"[A-Z]{2}", code) or code in locations or not name:
                    raise ValueError("Invalid country in geographic catalogue")
                locations[code] = Location(code, name, 1, None, continent)
        for parent_id, subdivisions in value["subdivisions"].items():
            parent = locations.get(parent_id)
            if parent is None or parent.level != 1:
                raise ValueError("Unknown subdivision parent")
            for code, name in subdivisions.items():
                if (
                    not LOCATION_ID_PATTERN.fullmatch(code)
                    or not code.startswith(f"{parent_id}-")
                    or code in locations
                    or not name
                ):
                    raise ValueError("Invalid subdivision in geographic catalogue")
                locations[code] = Location(code, name, 2, parent_id, parent.continent)
        supported = frozenset(value["subdivision_countries"])
        if any(code not in value["subdivisions"] for code in supported):
            raise ValueError("Missing subdivisions for configurable country")
        non_iso = frozenset(value.get("non_iso_country_ids", []))
        if any(code not in locations or locations[code].level != 1 for code in non_iso):
            raise ValueError("Unknown non-ISO country identifier")
        self.locations = MappingProxyType(locations)
        self.subdivision_countries = supported
        self.non_iso_country_ids = non_iso

    def valid_id(self, value: object) -> str:
        """Accept only known locations for new visit writes."""
        code = persisted_location_id(value)
        if code not in self.locations:
            raise ValueError("Unknown or unsupported geographic location")
        return code

    def visited_countries(self, explicit: Iterable[str]) -> set[str]:
        """Derive country visits without modifying the explicit visit set."""
        return {
            location.parent_id or location.id
            for code in explicit
            if (location := self.locations.get(code)) is not None
        }

    def visited_subdivisions(self, explicit: Iterable[str]) -> set[str]:
        """Return exact subdivision visits, never inferred children."""
        return {
            code for code in explicit
            if (location := self.locations.get(code)) is not None and location.level == 2
        }

    def visitors(self, histories: dict[str, Iterable[str]], location_id: str) -> set[str]:
        """Return country-effective or subdivision-exact visitor membership."""
        location = self.locations[self.valid_id(location_id)]
        return {
            ident for ident, explicit in histories.items()
            if location.id in (
                self.visited_countries(explicit) if location.level == 1 else set(explicit)
            )
        }


def persisted_location_id(value: object) -> str:
    """Retain well-formed historical IDs even if a future catalogue omits them."""
    if not isinstance(value, str):
        raise ValueError("Location ID must be a string")
    code = value.strip().upper()
    if not LOCATION_ID_PATTERN.fullmatch(code):
        raise ValueError("Expected a country or subdivision ID")
    return code


@lru_cache(maxsize=1)
def get_geography() -> Geography:
    """Load once; integration setup warms this cache in the executor."""
    with Path(__file__).with_name("geography.json").open(encoding="utf-8") as source:
        return Geography(json.load(source))