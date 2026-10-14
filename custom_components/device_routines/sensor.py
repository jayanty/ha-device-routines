"""The hub sensors. Phase 0 ships Health; Routines and the Schedule sensors follow."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceRoutinesConfigEntry
from .const import HEALTH_STATES
from .entity import DeviceRoutinesHubEntity
from .health import HealthReport

# Nothing here polls, so there is nothing to serialize.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceRoutinesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the hub sensors."""
    runtime = entry.runtime_data
    async_add_entities([HealthSensor(entry.entry_id, runtime.version, runtime.health)])


class HealthSensor(DeviceRoutinesHubEntity, SensorEntity):
    """`ok`, `degraded` or `error`, with the deploy and self check details as attributes."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_options = HEALTH_STATES

    def __init__(self, entry_id: str, version: str, report: HealthReport) -> None:
        """Hold the report collected at setup."""
        super().__init__(entry_id, "health", version)
        self._report = report

    @property
    def native_value(self) -> str:
        """Return the overall state."""
        return self._report.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the report's details."""
        return self._report.as_attributes()
