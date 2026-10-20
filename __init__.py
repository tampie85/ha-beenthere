"""Visited Countries Home Assistant integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import CARD_URL, DOMAIN, STORAGE_VERSION, UPDATED_EVENT
from .storage import apply_change, create_default_data, normalize_data


GET_COMMAND = {vol.Required("type"): f"{DOMAIN}/get"}
CHANGE_COMMAND = {
    vol.Required("type"): f"{DOMAIN}/change",
    vol.Required("action"): str,
    vol.Optional("target_id"): str,
    vol.Optional("name"): str,
    vol.Optional("country"): str,
    vol.Optional("members"): [str],
}


def _store(hass: HomeAssistant, entry: ConfigEntry) -> Store:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Visited Countries config entry."""
    store = _store(hass, entry)
    data = normalize_data(await store.async_load() or create_default_data())
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = data

    await hass.http.async_register_static_paths([
        StaticPathConfig(
            CARD_URL,
            str(Path(__file__).parent / "frontend" / "visited-countries-card.js"),
            cache_headers=False,
        )
    ])

    @websocket_api.websocket_command(GET_COMMAND)
    @websocket_api.async_response
    async def get_data(
        hass: HomeAssistant, connection, msg: dict[str, Any]
    ) -> None:
        connection.send_result(msg["id"], data)

    @websocket_api.websocket_command(CHANGE_COMMAND)
    @websocket_api.async_response
    async def change_data(
        hass: HomeAssistant, connection, msg: dict[str, Any]
    ) -> None:
        try:
            apply_change(data, msg["action"], msg)
            await store.async_save(data)
        except (TypeError, ValueError) as err:
            connection.send_error(msg["id"], "invalid_request", str(err))
            return

        hass.bus.async_fire(UPDATED_EVENT, {"entry_id": entry.entry_id})
        connection.send_result(msg["id"], data)

    websocket_api.async_register_command(hass, get_data)
    websocket_api.async_register_command(hass, change_data)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one Visited Countries config entry."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True
