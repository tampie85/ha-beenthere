"""Storage and domain operations for the BeenThere integration."""

from __future__ import annotations

from copy import deepcopy
import uuid
from typing import Any

from .geography import get_geography, persisted_location_id

NAME_MAX_LENGTH = 80
ACTION_FIELDS = {
    "add_traveller": {"name"},
    "rename_traveller": {"target_id", "name"},
    "delete_traveller": {"target_id"},
    "toggle_country": {"target_id", "country"},
    "set_visit": {"target_id", "location", "visited"},
    "set_map_detail": {"country", "enabled"},
    "add_group": {"name", "members"},
    "update_group": {"target_id", "name", "members"},
    "delete_group": {"target_id"},
}


def create_default_data() -> dict[str, dict[str, Any]]:
    """Return a fresh empty data structure."""
    return {
        "travellers": {}, "groups": {},
        "map_settings": {"subdivision_countries": ["GB"]},
    }


def migrate_data(old_major_version: int, old_minor_version: int, value: Any) -> dict:
    """Upgrade known storage versions without interpreting explicit visits."""
    if old_major_version != 1 or old_minor_version != 1:
        raise NotImplementedError("Unsupported BeenThere storage version")
    if not isinstance(value, dict):
        raise ValueError("Invalid BeenThere storage snapshot")
    migrated = deepcopy(value)
    migrated.setdefault("map_settings", {"subdivision_countries": ["GB"]})
    return migrated


def valid_name(value: Any) -> str:
    """Validate and normalize a traveller or group name."""
    if not isinstance(value, str):
        raise ValueError("Name must be a string")
    name = value.strip()
    if not 1 <= len(name) <= NAME_MAX_LENGTH:
        raise ValueError(f"Name must be 1-{NAME_MAX_LENGTH} characters")
    return name


def valid_country_code(value: Any) -> str:
    """Validate and normalize a country or subdivision code."""
    return get_geography().valid_id(value)


def normalize_data(value: Any) -> dict[str, dict[str, Any]]:
    """Normalize persisted data while keeping valid existing records."""
    if not isinstance(value, dict):
        return create_default_data()

    travellers: dict[str, dict[str, Any]] = {}
    raw_travellers = value.get("travellers", {})
    if isinstance(raw_travellers, dict):
        for ident, traveller in raw_travellers.items():
            if not isinstance(ident, str) or not isinstance(traveller, dict):
                continue
            try:
                name = valid_name(traveller.get("name", ""))
            except (TypeError, ValueError):
                continue
            raw_countries = traveller.get("countries", [])
            if not isinstance(raw_countries, list):
                raw_countries = []
            countries = set()
            for code in raw_countries:
                if not isinstance(code, str):
                    continue
                try:
                    countries.add(persisted_location_id(code))
                except ValueError:
                    continue
            travellers[ident] = {"name": name, "countries": sorted(countries)}

    groups: dict[str, dict[str, Any]] = {}
    raw_groups = value.get("groups", {})
    if isinstance(raw_groups, dict):
        for ident, group in raw_groups.items():
            if not isinstance(ident, str) or not isinstance(group, dict):
                continue
            try:
                name = valid_name(group.get("name", ""))
            except (TypeError, ValueError):
                continue
            raw_members = group.get("members", [])
            if not isinstance(raw_members, list):
                raw_members = []
            members = list(dict.fromkeys(
                member for member in raw_members
                if isinstance(member, str) and member in travellers
            ))
            groups[ident] = {"name": name, "members": members}

    settings = value.get("map_settings", {})
    enabled = settings.get("subdivision_countries", ["GB"]) if isinstance(settings, dict) else ["GB"]
    if not isinstance(enabled, list):
        enabled = ["GB"]
    supported = get_geography().subdivision_countries
    return {
        "travellers": travellers,
        "groups": groups,
        "map_settings": {"subdivision_countries": sorted({
            code for code in enabled if isinstance(code, str) and code in supported
        })},
    }


def _require_id(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("A target id is required")
    return value


def _require_traveller(data: dict[str, Any], ident: Any) -> dict[str, Any]:
    ident = _require_id(ident)
    try:
        return data["travellers"][ident]
    except KeyError as err:
        raise ValueError("Unknown traveller") from err


def _require_group(data: dict[str, Any], ident: Any) -> tuple[str, dict[str, Any]]:
    ident = _require_id(ident)
    try:
        return ident, data["groups"][ident]
    except KeyError as err:
        raise ValueError("Unknown group") from err


def _members(data: dict[str, Any], value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("Members must be a list")
    members = list(dict.fromkeys(value))
    if any(not isinstance(member, str) or member not in data["travellers"] for member in members):
        raise ValueError("Unknown traveller")
    return members


def apply_change(data: dict[str, Any], action: str, message: dict[str, Any]) -> None:
    """Apply one validated websocket mutation to the in-memory data."""
    if not isinstance(action, str) or action not in ACTION_FIELDS:
        raise ValueError("Unknown action")
    if set(message) - {"id", "type", "action"} - ACTION_FIELDS[action]:
        raise ValueError("Unexpected fields for action")
    target_id = message.get("target_id")

    if action == "set_map_detail":
        code = valid_country_code(message.get("country"))
        if code not in get_geography().subdivision_countries:
            raise ValueError("Subdivision detail is not supported for this country")
        enabled = message.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("Enabled must be a boolean")
        countries = set(data["map_settings"]["subdivision_countries"])
        if enabled:
            countries.add(code)
        else:
            countries.discard(code)
        data["map_settings"]["subdivision_countries"] = sorted(countries)
        return

    if action == "add_traveller":
        ident = uuid.uuid4().hex
        data["travellers"][ident] = {
            "name": valid_name(message.get("name")),
            "countries": [],
        }
        return

    if action == "rename_traveller":
        _require_traveller(data, target_id)["name"] = valid_name(message.get("name"))
        return

    if action == "delete_traveller":
        ident = _require_id(target_id)
        _require_traveller(data, ident)
        del data["travellers"][ident]
        for group in data["groups"].values():
            group["members"] = [member for member in group["members"] if member != ident]
        return

    if action in {"toggle_country", "set_visit"}:
        traveller = _require_traveller(data, target_id)
        code = valid_country_code(message.get("location" if action == "set_visit" else "country"))
        countries = traveller["countries"]
        visited = message.get("visited") if action == "set_visit" else code not in countries
        if not isinstance(visited, bool):
            raise ValueError("Visited must be a boolean")
        if not visited and code in countries:
            countries.remove(code)
        elif visited and code not in countries:
            countries.append(code)
            countries.sort()
        return

    if action in {"add_group", "update_group"}:
        members = _members(data, message.get("members", []))
        name = valid_name(message.get("name"))
        if action == "add_group":
            target_id = uuid.uuid4().hex
        else:
            target_id, _ = _require_group(data, target_id)
        data["groups"][target_id] = {"name": name, "members": members}
        return

    if action == "delete_group":
        ident, _ = _require_group(data, target_id)
        del data["groups"][ident]
        return

    raise ValueError("Unknown action")
