"""The Schedule sensor on each device and the hub sensors. Thin callers only (PRD P16)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceRoutinesConfigEntry
from .const import HEALTH_STATES
from .entity import DeviceRoutinesHubEntity, linked_device_info
from .health import HealthMonitor
from .summary import SCHEDULE_KEY, SummaryCoordinator, schedule_unique_id

# Nothing here polls, so there is nothing to serialize.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceRoutinesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the hub sensors and hand the coordinator a way to add Schedule sensors."""
    runtime = entry.runtime_data
    async_add_entities(
        [
            HealthSensor(entry.entry_id, runtime.version, runtime.health),
            RoutinesSensor(entry.entry_id, runtime.version),
        ]
    )
    coordinator = runtime.summary

    def add_schedule_sensors(device_ids: list[str]) -> None:
        async_add_entities(ScheduleSensor(coordinator, device_id) for device_id in device_ids)

    coordinator.async_set_sensor_adder(add_schedule_sensors)


class HealthSensor(DeviceRoutinesHubEntity, SensorEntity):
    """`ok`, `degraded` or `error`, with the deploy and self check details as attributes."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_options = HEALTH_STATES

    def __init__(self, entry_id: str, version: str, health: HealthMonitor) -> None:
        """Read the report the monitor keeps current."""
        super().__init__(entry_id, "health", version)
        self._health = health

    async def async_added_to_hass(self) -> None:
        """Write the state whenever the report changes."""
        self.async_on_remove(self._health.async_add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> str:
        """Return the overall state."""
        return self._health.report.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the report's details."""
        return self._health.report.as_attributes()


class RoutinesSensor(DeviceRoutinesHubEntity, SensorEntity):
    """The count of active routines; every managed routine as attributes (PRD 4.4).

    Routines arrive in Phase 2, so the count is 0 and the list empty until then.
    """

    def __init__(self, entry_id: str, version: str) -> None:
        """Attach to the hub."""
        super().__init__(entry_id, "hub_routines", version)

    @property
    def native_value(self) -> int:
        """Return the number of active routines."""
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return every managed routine."""
        return {"routines": []}


class ScheduleSensor(SensorEntity):
    """The next action on a device as a sentence; every line as attributes (PRD FR-S4)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = SCHEDULE_KEY

    def __init__(self, coordinator: SummaryCoordinator, device_id: str) -> None:
        """Attach to the user's device as the coordinator last saw it."""
        self._coordinator = coordinator
        self._device_id = device_id
        self._attr_unique_id = schedule_unique_id(device_id)
        summary = coordinator.summaries[device_id]
        self._attr_device_info = linked_device_info(
            summary.identifiers, summary.connections, summary.device_name
        )

    async def async_added_to_hass(self) -> None:
        """Follow the coordinator's updates for this device."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self._device_id, self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        """Return whether the device still has a summary."""
        return self._device_id in self._coordinator.summaries

    @property
    def native_value(self) -> str | None:
        """Return the state sentence."""
        summary = self._coordinator.summaries.get(self._device_id)
        return summary.state if summary else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the items, conflicts and pause fields."""
        summary = self._coordinator.summaries.get(self._device_id)
        return summary.attributes() if summary else {}
