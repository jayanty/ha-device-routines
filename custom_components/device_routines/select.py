"""The device page selects: Days, Routine controls (the target) and the two timings.

Thin callers of the RoutineManager (PRD P16, TECH_SPEC 4.5). A timing says whether a time
is a time of day, sunrise or sunset (FR-R10); like the times, it takes the words of the
device's domain (PRD 5.3): a vacuum shows Start timing, a lock Lock timing.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceRoutinesConfigEntry
from .entity import DeviceRoutinesDeviceEntity, async_setup_device_entities
from .manager import RoutineManager
from .models import Days, TimeKind

# Nothing here polls, so there is nothing to serialize.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceRoutinesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Give every opted in device its selects."""
    async_setup_device_entities(
        entry,
        async_add_entities,
        Platform.SELECT,
        {
            "days": DaysSelect,
            "target": TargetSelect,
            "on_kind": OnKindSelect,
            "off_kind": OffKindSelect,
        },
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


class _KindSelect(DeviceRoutinesDeviceEntity, SelectEntity):
    """Time, Sunrise or Sunset for one side; the key is its setting (FR-R10).

    Advanced, so created disabled. Sunrise or Sunset makes the side follow the sun with
    the side's sun offset, and its time unavailable; Time makes it a time of day again.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, manager: RoutineManager, device_id: str, key: str) -> None:
        """Attach to the device's page."""
        super().__init__(manager, device_id, key)
        self._attr_options = [kind.value for kind in TimeKind]

    @property
    def current_option(self) -> str | None:
        """Return what the side follows."""
        view = self._view
        return None if view is None else str(getattr(view.settings, self._key).value)

    async def async_select_option(self, option: str) -> None:
        """Choose a time of day, sunrise or sunset for the side."""
        await self._async_update({self._key: option})


class OnKindSelect(_KindSelect):
    """Turn on timing; not created for a domain without an activating action."""

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page with the profile's word for it."""
        super().__init__(manager, device_id, "on_kind")
        profile = manager.profile(device_id)
        label = profile and profile.on_label_key
        self._attr_translation_key = f"{label}_kind" if label else "on_kind"


class OffKindSelect(_KindSelect):
    """Turn off timing."""

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page with the profile's word for it."""
        super().__init__(manager, device_id, "off_kind")
        profile = manager.profile(device_id)
        self._attr_translation_key = f"{profile.off_label_key}_kind" if profile else "off_kind"
