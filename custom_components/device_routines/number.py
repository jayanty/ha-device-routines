"""The device page minutes: Turn off after, Turn back on after and the two sun offsets.

Thin callers of the RoutineManager (PRD P16, TECH_SPEC 4.5). 0 means off; the manager
refuses both durations at once (D27). Turn off after takes the domain profile's words, as
the times do (PRD 5.3): a cover or a valve shows Close after, a lock Lock after. A sun
offset moves a side that follows sunrise or sunset (FR-R10), negative before the event,
and takes the words of its time: Turn on sun offset, Start sun offset, Lock sun offset.
"""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, Platform, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceRoutinesConfigEntry
from .compiler import MAX_DURATION_MIN, MAX_SUN_OFFSET_MIN
from .entity import DeviceRoutinesDeviceEntity, async_setup_device_entities
from .manager import RoutineManager

# Nothing here polls, so there is nothing to serialize.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceRoutinesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Give every opted in device its durations."""
    async_setup_device_entities(
        entry,
        async_add_entities,
        Platform.NUMBER,
        {
            "turn_off_after": TurnOffAfterNumber,
            "turn_back_on_after": TurnBackOnAfterNumber,
            "on_sun_offset": OnSunOffsetNumber,
            "off_sun_offset": OffSunOffsetNumber,
        },
    )


class _Minutes(DeviceRoutinesDeviceEntity, NumberEntity):
    """A duration in minutes, typed into a box, 0 to 1440; `_field` is its setting."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class: NumberDeviceClass | None = NumberDeviceClass.DURATION
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_DURATION_MIN
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _field: str

    @property
    def native_value(self) -> int | None:
        """Return the minutes; 0 is off."""
        view = self._view
        return None if view is None else int(getattr(view.settings, self._field))

    async def async_set_native_value(self, value: float) -> None:
        """Set the minutes."""
        await self._async_update({self._field: value})


class TurnOffAfterNumber(_Minutes):
    """Turn off after (FR-R3), where the domain offers it, in the domain's words."""

    _field = "turn_off_after_min"

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page with the profile's word for it."""
        super().__init__(manager, device_id, "turn_off_after")
        profile = manager.profile(device_id)
        self._attr_translation_key = profile.off_after_label_key if profile else "turn_off_after"


class TurnBackOnAfterNumber(_Minutes):
    """Turn back on after (FR-R4): advanced, so created disabled; inert until set."""

    _attr_entity_registry_enabled_default = False
    _field = "turn_back_on_after_min"

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page."""
        super().__init__(manager, device_id, "turn_back_on_after")


class _SunOffset(_Minutes):
    """Minutes from sunrise or sunset, -180 to 180 (L60): advanced, so created disabled.

    A signed offset rather than a duration; unavailable while its side is a time of day.
    """

    _attr_device_class = None
    _attr_entity_registry_enabled_default = False
    _attr_native_min_value = -MAX_SUN_OFFSET_MIN
    _attr_native_max_value = MAX_SUN_OFFSET_MIN


class OnSunOffsetNumber(_SunOffset):
    """Turn on sun offset; not created for a domain without an activating action."""

    _field = "on_sun_offset_min"

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page with the profile's word for it."""
        super().__init__(manager, device_id, "on_sun_offset")
        profile = manager.profile(device_id)
        label = profile and profile.on_label_key
        self._attr_translation_key = f"{label}_sun_offset" if label else "on_sun_offset"


class OffSunOffsetNumber(_SunOffset):
    """Turn off sun offset."""

    _field = "off_sun_offset_min"

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page with the profile's word for it."""
        super().__init__(manager, device_id, "off_sun_offset")
        profile = manager.profile(device_id)
        self._attr_translation_key = (
            f"{profile.off_label_key}_sun_offset" if profile else "off_sun_offset"
        )
