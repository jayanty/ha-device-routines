"""The device page selects: Days and Routine controls (the target).

Thin callers of the RoutineManager (PRD P16, TECH_SPEC 4.5).
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceRoutinesConfigEntry
from .entity import DeviceRoutinesDeviceEntity, async_setup_device_entities
from .manager import RoutineManager
from .models import Days

# Nothing here polls, so there is nothing to serialize.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceRoutinesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Give every opted in device its selects."""
    async_setup_device_entities(
        entry, async_add_entities, Platform.SELECT, {"days": DaysSelect, "target": TargetSelect}
    )


class DaysSelect(DeviceRoutinesDeviceEntity, SelectEntity):
    """Every day, Weekdays, Weekends, Some days or Weekly schedule (PRD 4.2, D34).

    Some days keeps the routine's day set, which the routine form or the console chooses;
    Weekly schedule follows the routine's schedule helper (FR-R2).
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page."""
        super().__init__(manager, device_id, "days")
        self._attr_options = [days.value for days in Days]

    @property
    def current_option(self) -> str | None:
        """Return the routine's days."""
        view = self._view
        return None if view is None else view.settings.days.value

    async def async_select_option(self, option: str) -> None:
        """Choose the days."""
        await self._async_update({"days": option})


class TargetSelect(DeviceRoutinesDeviceEntity, SelectEntity):
    """Which entity the routine drives, on a device with several (PRD 5.3)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page."""
        super().__init__(manager, device_id, "target")

    @property
    def options(self) -> list[str]:
        """Return the entities a routine can drive, in registry order."""
        return list(self._manager.candidates(self._device_id))

    @property
    def current_option(self) -> str | None:
        """Return the entity the routine drives."""
        view = self._view
        return None if view is None else view.settings.target_entity

    async def async_select_option(self, option: str) -> None:
        """Drive another entity of the device."""
        await self._async_update({"target_entity": option})
