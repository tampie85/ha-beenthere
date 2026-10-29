
"""Register the BeenThere Lovelace card resource."""

import logging

from homeassistant.components.lovelace.const import LOVELACE_DATA

from .const import CARD_URL

_LOGGER = logging.getLogger(__name__)


async def async_register_card_resource(hass):
    """Register the card in storage-managed Lovelace resources."""
    lovelace = hass.data.get(LOVELACE_DATA)

    if lovelace is None:
        _LOGGER.warning(
            "Lovelace is unavailable; add %s manually",
            CARD_URL,
        )
        return

    if lovelace.resource_mode != "storage":
        _LOGGER.info(
            "Lovelace resources are YAML-managed; "
            "add %s as a JavaScript module",
            CARD_URL,
        )
        return

    resources = lovelace.resources

    # Load existing resources before inspecting or modifying them.
    if not resources.loaded:
        await resources.async_load()

    existing_urls = [
        item["url"].split("?")[0]
        for item in resources.async_items()
    ]

    if CARD_URL in existing_urls:
        return

    await resources.async_create_item(
        {
            "res_type": "module",
            "url": CARD_URL,
        }
    )

    _LOGGER.info(
        "Registered BeenThere dashboard card"
    )
