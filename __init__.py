
"""BeenThere Home Assistant integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import CARD_URL, DOMAIN, PANEL_PATH, PANEL_URL, STORAGE_VERSION, UPDATED_EVENT
from .frontend_resource import async_register_card_resource
from .storage import apply_change, create_default_data, normalize_data


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
    )


async def async_setup(
    hass: HomeAssistant,
    config: dict[str, Any],
) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up one BeenThere config entry."""

    # Load existing traveller and group data.
    store = _store(hass, entry)

    data = normalize_data(
        await store.async_load() or create_default_data()
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = data

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
        module_url=PANEL_URL,
        embed_iframe=False,
        require_admin=False,
    )

    # Automatically register the dashboard resource.
    # The helper checks for existing registrations to
    # avoid creating duplicates.
    await async_register_card_resource(hass)

    # Return traveller and group data to the frontend.
    @websocket_api.websocket_command(GET_COMMAND)
    @websocket_api.async_response
    async def get_data(
        hass: HomeAssistant,
        connection,
        msg: dict[str, Any],
    ) -> None:
        """Return the current BeenThere data."""
        connection.send_result(msg["id"], data)

    # Handle changes made through the dashboard.
    @websocket_api.websocket_command(CHANGE_COMMAND)
    @websocket_api.async_response
    async def change_data(
        hass: HomeAssistant,
        connection,
        msg: dict[str, Any],
    ) -> None:
        """Apply and persist a traveller or group change."""
        try:
            apply_change(
                data,
                msg["action"],
                msg,
            )

            await store.async_save(data)

        except (TypeError, ValueError) as err:
            connection.send_error(
                msg["id"],
                "invalid_request",
                str(err),
            )
            return

        # Notify listeners that the data has changed.
        hass.bus.async_fire(
            UPDATED_EVENT,
            {"entry_id": entry.entry_id},
        )

        connection.send_result(
            msg["id"],
            data,
        )

    # Register the WebSocket commands.
    websocket_api.async_register_command(
        hass,
        get_data,
    )

    websocket_api.async_register_command(
        hass,
        change_data,
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload one BeenThere config entry."""

    frontend.async_remove_panel(hass, PANEL_PATH)

    hass.data.get(DOMAIN, {}).pop(
        entry.entry_id,
        None,
    )

    return True
