"""The device page buttons Skip next and Resume, and the hub's Clean up now.

Thin callers of the RoutineManager and the maintenance actions (PRD P16, TECH_SPEC 4.5).
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceRoutinesConfigEntry, maintenance
from .entity import (
    DeviceRoutinesDeviceEntity,
    DeviceRoutinesHubEntity,
    async_setup_device_entities,
)
from .maintenance import MaintenanceAction
from .manager import RoutineManager

# Nothing here polls, so there is nothing to serialize.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceRoutinesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the hub's Clean up now and give every opted in device its buttons."""
    runtime = entry.runtime_data
    async_add_entities([CleanUpNowButton(entry.entry_id, runtime.version, runtime.manager)])
    async_setup_device_entities(
        entry,
        async_add_entities,
        Platform.BUTTON,
        {"skip_next": SkipNextButton, "resume": ResumeButton},
    )


class SkipNextButton(DeviceRoutinesDeviceEntity, ButtonEntity):
    """Skips the action the Schedule shows next (FR-R11); unavailable with nothing next.

    The manager says when (`unavailable_reason`, reason `nothing_to_skip`).
    """

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page."""
        super().__init__(manager, device_id, "skip_next")

    async def async_press(self) -> None:
        """Skip the next action."""
        await self._manager.async_skip_next(self._device_id)


class ResumeButton(DeviceRoutinesDeviceEntity, ButtonEntity):
    """Ends a pause or a skip now (FR-R13); unavailable unless paused or skipping.

    The manager says when (`unavailable_reason`, reason `not_paused`).
    """

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        """Attach to the device's page."""
        super().__init__(manager, device_id, "resume")

    async def async_press(self) -> None:
        """Resume the routine."""
        await self._manager.async_resume(self._device_id)


class CleanUpNowButton(DeviceRoutinesHubEntity, ButtonEntity):
    """Runs the automatic cleanup now (PRD 4.4, D28)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry_id: str, version: str, manager: RoutineManager) -> None:
        """Attach to the hub."""
        super().__init__(entry_id, "hub_cleanup_now", version)
        self._manager = manager

    async def async_press(self) -> None:
        """Delete every routine whose device opted out or is gone, whatever its age."""
        await maintenance.async_run(
            self.hass, self._manager, MaintenanceAction.CLEAN_UP_NOW, dry_run=False
        )
