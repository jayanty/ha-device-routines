"""Entity base classes shared by the platforms."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, HUB_IDENTIFIER, HUB_MODEL, INTEGRATION_TITLE


class DeviceRoutinesHubEntity(Entity):
    """An entity on the hub device, the one service device the integration creates."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry_id: str, key: str, version: str) -> None:
        """Attach to the hub device with a stable unique id."""
        self._attr_unique_id = f"{DOMAIN}_{HUB_IDENTIFIER}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, HUB_IDENTIFIER)},
            name=INTEGRATION_TITLE,
            manufacturer=INTEGRATION_TITLE,
            model=HUB_MODEL,
            sw_version=version,
            entry_type=DeviceEntryType.SERVICE,
        )
        self._entry_id = entry_id
