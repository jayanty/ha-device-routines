"""The hub Problem sensor: on while a Repairs issue of this integration reports a problem.

PRD 4.4, with the offers left out (decision L67): a conversion offer is a suggestion.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.issue_registry import EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED

from . import DeviceRoutinesConfigEntry
from .const import DOMAIN
from .entity import DeviceRoutinesHubEntity
from .repairs import problem_issue_ids

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceRoutinesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the hub Problem sensor."""
    async_add_entities([ProblemSensor(entry.entry_id, entry.runtime_data.version)])


@callback
def _ours(event_data: Mapping[str, Any]) -> bool:
    return bool(event_data.get("domain") == DOMAIN)


class ProblemSensor(DeviceRoutinesHubEntity, BinarySensorEntity):
    """On while an issue is open; the attribute lists the issue ids."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry_id: str, version: str) -> None:
        """Attach to the hub."""
        super().__init__(entry_id, "hub_problem", version)
        self._issues: list[str] = []

    async def async_added_to_hass(self) -> None:
        """Follow the issue registry."""
        self._issues = problem_issue_ids(self.hass)
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED,
                self._issues_changed,
                event_filter=_ours,
            )
        )

    @callback
    def _issues_changed(self, _event: Event[Any]) -> None:
        self._issues = problem_issue_ids(self.hass)
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return whether an issue that reports a problem is open."""
        return bool(self._issues)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the open issue ids."""
        return {"issues": list(self._issues)}
