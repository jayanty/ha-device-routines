"""The device page datetime Paused until (FR-R12).

A thin caller of the RoutineManager (PRD P16, TECH_SPEC 4.5). The blueprint reads it
through its one template condition (decision L22); it keeps the routine's runtime across a
restart (decision L44).
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceRoutinesConfigEntry
from .const import KEY_PAUSED_UNTIL
from .entity import DeviceRoutinesRuntimeEntity, async_setup_device_entities
from .manager import RoutineManager

# Nothing here polls, so there is nothing to serialize.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceRoutinesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Give every opted in device its Paused until."""
    async_setup_device_entities(
        entry, async_add_entities, Platform.DATETIME, {KEY_PAUSED_UNTIL: PausedUntilDateTime}
    )


class PausedUntilDateTime(DeviceRoutinesRuntimeEntity, DateTimeEntity):
    """Empty unless paused or skipping; a future value pauses, a past one is refused."""

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page."""
        super().__init__(manager, device_id, KEY_PAUSED_UNTIL)

    @property
    def native_value(self) -> datetime | None:
        """Return when the pause or skip ends."""
        view = self._view
        return None if view is None else view.paused_until

    async def async_set_value(self, value: datetime) -> None:
        """Pause the routine until then."""
        await self._manager.async_pause(self._device_id, until=value)
