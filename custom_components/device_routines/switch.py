"""The device page switches: Routine, the two advanced flags and the Manual override.

Thin callers of the RoutineManager (PRD P16, TECH_SPEC 4.5).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceRoutinesConfigEntry
from .const import KEY_MANUAL_OVERRIDE
from .entity import (
    DeviceRoutinesDeviceEntity,
    DeviceRoutinesRuntimeEntity,
    async_setup_device_entities,
)
from .manager import RoutineManager

# Nothing here polls, so there is nothing to serialize.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceRoutinesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Give every opted in device its switches."""
    async_setup_device_entities(
        entry,
        async_add_entities,
        Platform.SWITCH,
        {
            "routine": RoutineSwitch,
            "catch_up": CatchUpSwitch,
            "respect_manual": RespectManualSwitch,
            KEY_MANUAL_OVERRIDE: ManualOverrideSwitch,
        },
    )


class RoutineSwitch(DeviceRoutinesDeviceEntity, SwitchEntity):
    """Mirrors the managed automation's on and off state both ways (FR-R14)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page."""
        super().__init__(manager, device_id, "routine")

    @property
    def is_on(self) -> bool:
        """Return whether the routine's automation is on."""
        view = self._view
        return view is not None and view.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002  # the core's signature
        """Enable the routine."""
        await self._manager.async_enable(self._device_id)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002  # the core's signature
        """Disable the routine; nothing runs until it is turned back on."""
        await self._manager.async_disable(self._device_id)


class _FlagSwitch(DeviceRoutinesDeviceEntity, SwitchEntity):
    """A routine flag whose setting field is the key; advanced, so created disabled."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    @property
    def is_on(self) -> bool:
        """Return the setting."""
        view = self._view
        return view is not None and bool(getattr(view.settings, self._key))

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002  # the core's signature
        """Turn the setting on."""
        await self._async_update({self._key: True})

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002  # the core's signature
        """Turn the setting off."""
        await self._async_update({self._key: False})


class CatchUpSwitch(_FlagSwitch):
    """Catch up after restart (FR-R5)."""

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page."""
        super().__init__(manager, device_id, "catch_up")


class RespectManualSwitch(_FlagSwitch):
    """Respect manual changes (FR-R6)."""

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page."""
        super().__init__(manager, device_id, "respect_manual")


class ManualOverrideSwitch(DeviceRoutinesRuntimeEntity, SwitchEntity):
    """On while a manual change left the device off schedule (FR-R6, PRD 9.3).

    The blueprint reads it and turns it off at the next scheduled time; a person turning it
    off makes the blueprint catch up at once. It keeps the routine's runtime across a
    restart (decision L44).
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page."""
        super().__init__(manager, device_id, KEY_MANUAL_OVERRIDE)

    @property
    def is_on(self) -> bool:
        """Return whether the override is on."""
        view = self._view
        return view is not None and view.override

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Name what changed the device last."""
        view = self._view
        source = None if view is None else view.last_change_source
        return {"last_change_source": None if source is None else source.value}

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002  # the core's signature
        """Turn the override on."""
        await self._manager.async_set_manual_override(self._device_id, on=True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002  # the core's signature
        """Turn the override off; the schedule takes over again at once."""
        await self._manager.async_set_manual_override(self._device_id, on=False)
