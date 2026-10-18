"""The device page times: Turn on at and Turn off at, in the words of the device's domain.

Thin callers of the RoutineManager (PRD P16, TECH_SPEC 4.5). The name follows the domain
profile's label (PRD 4.2 and 5.3): a vacuum shows Start at, a cover Open at, a lock Lock at.
"""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceRoutinesConfigEntry
from .entity import DeviceRoutinesDeviceEntity, async_setup_device_entities
from .manager import RoutineManager

# Nothing here polls, so there is nothing to serialize.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceRoutinesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Give every opted in device its times."""
    async_setup_device_entities(
        entry, async_add_entities, Platform.TIME, {"on_time": OnTime, "off_time": OffTime}
    )


class _RoutineTime(DeviceRoutinesDeviceEntity, TimeEntity):
    """A scheduled time whose setting field is the key; empty until set."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self) -> time | None:
        """Return the time, or None while it is not set."""
        view = self._view
        value: time | None = None if view is None else getattr(view.settings, self._key)
        return value

    async def async_set_value(self, value: time) -> None:
        """Set the time; the manager creates the routine if there is none yet."""
        await self._async_update({self._key: value})


class OnTime(_RoutineTime):
    """Turn on at (FR-R1); not created for a domain without an activating action."""

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page with the profile's word for it."""
        super().__init__(manager, device_id, "on_time")
        profile = manager.profile(device_id)
        self._attr_translation_key = (profile and profile.on_label_key) or "on_time"


class OffTime(_RoutineTime):
    """Turn off at (FR-R1)."""

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page with the profile's word for it."""
        super().__init__(manager, device_id, "off_time")
        profile = manager.profile(device_id)
        self._attr_translation_key = (profile and profile.off_label_key) or "off_time"
