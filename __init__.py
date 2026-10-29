"""BeenThere Home Assistant integration."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .const import CARD_URL, DOMAIN, PANEL_PATH, PANEL_URL, STORAGE_VERSION, UPDATED_EVENT
from .storage import apply_change, create_default_data, normalize_data

_LOGGER = logging.getLogger(__name__)


@dataclass
class BeenThereRuntime:
    """State and pending writes belonging to one loaded config entry."""

    entry_id: str
    store: Store
    data: dict[str, Any]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active: bool = True


GET_COMMAND = {
    vol.Required("type"): f"{DOMAIN}/get",
}

CHANGE_COMMAND = {
    vol.Required("type"): f"{DOMAIN}/change",
    vol.Required("action"): str,
    vol.Optional("target_id"): str,
    vol.Optional("name"): str,
    vol.Optional("country"): str,
    vol.Optional("members"): [str],
}


def _store(hass: HomeAssistant, entry: ConfigEntry) -> Store:
    """Return the persistent storage instance."""
    return Store(
        hass,
        STORAGE_VERSION,
        f"{DOMAIN}.{entry.entry_id}",
        private=True,
        atomic_writes=True,
    )


def _runtime(hass: HomeAssistant) -> BeenThereRuntime | None:
    """Return only a fully loaded, active runtime."""
    runtime = hass.data.get(DOMAIN, {}).get("runtime")
    return runtime if runtime is not None and runtime.active else None


@websocket_api.websocket_command(GET_COMMAND)
@websocket_api.async_response
async def get_data(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Return the current shared data to authenticated users."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], "not_loaded", "BeenThere is not loaded.")
        return
    connection.send_result(msg["id"], runtime.data)


@websocket_api.websocket_command(CHANGE_COMMAND)
@websocket_api.async_response
async def change_data(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Validate, persist and publish an administrator's change."""
    if connection.user is None or not connection.user.is_admin:
        connection.send_error(
            msg["id"], "unauthorized",
            "Administrator access is required to change BeenThere data.",
        )
        return
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], "not_loaded", "BeenThere is not loaded.")
        return

    async with runtime.lock:
        if _runtime(hass) is not runtime:
            connection.send_error(msg["id"], "not_loaded", "BeenThere is not loaded.")
            return
        candidate = deepcopy(runtime.data)
        try:
            apply_change(candidate, msg["action"], msg)
        except (TypeError, ValueError) as err:
            connection.send_error(msg["id"], "invalid_request", str(err))
            return
        try:
            await runtime.store.async_save(candidate)
        except (OSError, HomeAssistantError) as err:
            _LOGGER.error("Unable to save BeenThere data (%s)", type(err).__name__)
            connection.send_error(
                msg["id"], "storage_error",
                "Could not save BeenThere data. Check Home Assistant storage and logs.",
            )
            return
        runtime.data = candidate
        if runtime.active:
            hass.bus.async_fire(UPDATED_EVENT, {"entry_id": runtime.entry_id})
        connection.send_result(msg["id"], candidate)


async def async_setup(
    hass: HomeAssistant,
    config: dict[str, Any],
) -> bool:
    """Set up the integration domain."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.get("commands_registered"):
        websocket_api.async_register_command(hass, get_data)
        websocket_api.async_register_command(hass, change_data)
        domain_data["commands_registered"] = True
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up one BeenThere config entry."""

    store = _store(hass, entry)

    data = normalize_data(
        await store.async_load() or create_default_data()
    )

    if not hass.data[DOMAIN].get("static_registered"):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    url,
                    str(Path(__file__).parent / "frontend" / filename),
                    cache_headers=False,
                )
                for url, filename in (
                    (CARD_URL, "beenthere-card.js"),
                    (PANEL_URL, "beenthere-panel.js"),
                )
            ]
        )
        hass.data[DOMAIN]["static_registered"] = True

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="beenthere-panel",
        frontend_url_path=PANEL_PATH,
        sidebar_title="BeenThere",
        sidebar_icon="mdi:map-marker-check",
        module_url=f"{PANEL_URL}?v=2",
        embed_iframe=False,
        require_admin=False,
    )

    hass.data[DOMAIN]["runtime"] = BeenThereRuntime(entry.entry_id, store, data)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload one BeenThere config entry."""

    domain_data = hass.data.get(DOMAIN, {})
    runtime = domain_data.get("runtime")
    if runtime is not None and runtime.entry_id == entry.entry_id:
        runtime.active = False
        async with runtime.lock:
            domain_data.pop("runtime", None)
    frontend.async_remove_panel(hass, PANEL_PATH)
    return True
