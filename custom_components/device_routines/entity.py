"""Entity base classes shared by the platforms.

Device page controls (TECH_SPEC 4.5) are thin callers of the RoutineManager (PRD P16): they
render the manager's view of one device's routine, hand every change to the manager and
re render on its events. `async_setup_device_entities` gives each platform the controls
the manager names for a device (`page_keys`), adds them when a device opts in or its set
grows, and removes the ones that leave it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.util import dt as dt_util

from . import DeviceRoutinesConfigEntry
from .const import ATTR_REASON, DOMAIN, HUB_IDENTIFIER, HUB_MODEL, INTEGRATION_TITLE
from .manager import SOURCE_ENTITY, ManagerEvent, RestoredRuntime, RoutineManager
from .models import Occurrence, RoutineView, Source, Verb


def linked_device_info(
    identifiers: frozenset[tuple[str, str]],
    connections: frozenset[tuple[str, str]],
    name: str | None,
) -> DeviceInfo:
    """Return device info that places an entity on a user's device (decision L25).

    The identifiers are copied verbatim from the device registry entry, and the name is
    the one the device shows (`name_by_user or name`, so a rename reaches the linked
    record, plan A4.0 item 29); a device known only by its connections is matched
    through those instead.
    """
    if identifiers:
        return DeviceInfo(identifiers=set(identifiers), name=name)
    return DeviceInfo(connections=set(connections), name=name)


class DeviceRoutinesHubEntity(Entity):
    """An entity on the hub device, the one service device the integration creates."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry_id: str, key: str, version: str) -> None:
        """Attach to the hub device with a stable unique id."""
        self._attr_unique_id = f"{DOMAIN}_{HUB_IDENTIFIER}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, HUB_IDENTIFIER)},
            name=INTEGRATION_TITLE,
            manufacturer=INTEGRATION_TITLE,
            model=HUB_MODEL,
            sw_version=version,
            entry_type=DeviceEntryType.SERVICE,
        )
        self._entry_id = entry_id


class DeviceRoutinesDeviceEntity(Entity):
    """A routine control on a user's device page (TECH_SPEC 4.5).

    Unique id `device_routines_<device id>_<key>`, translation key equal to the key (the two
    times take their domain's words instead, see `time.py`), on the linked record of the
    user's device (L25). Unavailable while the manager names a reason
    for this control, with that `reason` as an attribute: a capability attribute, because
    Home Assistant drops the state attributes of an unavailable entity.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: RoutineManager, device_id: str, key: str) -> None:
        """Attach to the user's device as the device registry holds it now."""
        self._manager = manager
        self._device_id = device_id
        self._key = key
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{key}"
        self._attr_translation_key = key
        device = dr.async_get(manager.hass).async_get(device_id, include_child_devices=False)
        if device is not None:
            self._attr_device_info = linked_device_info(
                frozenset(device.identifiers),
                frozenset(device.connections),
                device.name_by_user or device.name,
            )

    async def async_added_to_hass(self) -> None:
        """Re render on every manager event for this device, and on house wide ones."""
        await super().async_added_to_hass()
        self.async_on_remove(self._manager.async_add_listener(self._heard))

    @callback
    def _heard(self, event: ManagerEvent) -> None:
        if event.device_id not in {None, self._device_id}:
            return
        if er.async_get(self.hass).async_get(self.entity_id) is None:
            # Removed from the registry (opt out, the device gone): the platform removes
            # the entity next, and writing its state now would fail (plan A4.0 item 26).
            return
        self.async_write_ha_state()

    @property
    def _view(self) -> RoutineView | None:
        """The manager's snapshot of this device's routine."""
        return self._manager.get(self._device_id)

    @property
    def _reason(self) -> str | None:
        return self._manager.unavailable_reason(self._device_id, self._key)

    @property
    def available(self) -> bool:
        """Return whether the manager names no reason to take this control away."""
        return self._reason is None

    @property
    def capability_attributes(self) -> dict[str, Any]:
        """Add the reason this control is unavailable, if there is one."""
        capabilities = super().capability_attributes or {}
        if (reason := self._reason) is None:
            return capabilities
        return {**capabilities, ATTR_REASON: reason}

    async def _async_update(self, patch: Mapping[str, Any]) -> None:
        """Hand a settings patch to the manager; a refused one raises its translated problem."""
        result = await self._manager.async_update(self._device_id, patch, source=SOURCE_ENTITY)
        if (problem := result.problem) is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=problem.translation_key,
                translation_placeholders=dict(problem.placeholders),
            )


# --------------------------------------------------------------------------------------
# The runtime the Manual override switch and the Paused until datetime keep (L44)
# --------------------------------------------------------------------------------------


def _moment(value: Any) -> datetime:
    """Read an ISO datetime back; raise for anything that is not one."""
    moment = dt_util.parse_datetime(value)
    if moment is None:
        raise ValueError(value)
    return moment


def _occurrence(value: Any) -> Occurrence | None:
    if value is None:
        return None
    verb = value.get("verb")
    return Occurrence(_moment(value["at"]), None if verb is None else Verb(verb))


@dataclass(frozen=True)
class RuntimeExtraData(ExtraStoredData):
    """A routine's runtime as both runtime controls store it across a restart."""

    runtime: RestoredRuntime

    def as_dict(self) -> dict[str, Any]:
        """Return the runtime as JSON values."""
        runtime = self.runtime
        until = runtime.paused_until
        skipped = runtime.skipped_action
        verb = None if skipped is None else skipped.verb
        source = runtime.last_change_source
        return {
            "paused_until": None if until is None else until.isoformat(),
            "skipped_action": None
            if skipped is None
            else {"at": skipped.at.isoformat(), "verb": None if verb is None else verb.value},
            "override": runtime.override,
            "override_by_skip": runtime.override_by_skip,
            "last_change_source": None if source is None else source.value,
        }


def runtime_from_dict(data: Mapping[str, Any]) -> RestoredRuntime | None:
    """Read stored runtime back; None for data this version cannot read."""
    try:
        until = data.get("paused_until")
        source = data.get("last_change_source")
        return RestoredRuntime(
            paused_until=None if until is None else _moment(until),
            skipped_action=_occurrence(data.get("skipped_action")),
            override=bool(data.get("override", False)),
            override_by_skip=bool(data.get("override_by_skip", False)),
            last_change_source=None if source is None else Source(source),
        )
    except AttributeError, KeyError, TypeError, ValueError:
        return None


class DeviceRoutinesRuntimeEntity(DeviceRoutinesDeviceEntity, RestoreEntity):
    """A control that keeps the routine's runtime across a restart and hands it back.

    Both runtime controls store the whole runtime (`manager.restore_data`), so either one
    restores everything, even while the other is disabled; data this version cannot read
    restores nothing rather than clearing what the other control holds.
    """

    async def async_added_to_hass(self) -> None:
        """Hand what was restored to the manager."""
        await super().async_added_to_hass()
        extra = await self.async_get_last_extra_data()
        restored = None if extra is None else runtime_from_dict(extra.as_dict())
        if restored is not None:
            await self._manager.async_restore_runtime(self._device_id, restored)

    @property
    def extra_restore_state_data(self) -> RuntimeExtraData | None:
        """Return the routine's runtime as the manager holds it now."""
        runtime = self._manager.restore_data(self._device_id)
        return None if runtime is None else RuntimeExtraData(runtime)


# --------------------------------------------------------------------------------------
# Adding and removing one platform's controls
# --------------------------------------------------------------------------------------

type ControlFactory = Callable[[RoutineManager, str], DeviceRoutinesDeviceEntity]


@callback
def async_setup_device_entities(
    entry: DeviceRoutinesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    domain: str,
    factories: Mapping[str, ControlFactory],
) -> None:
    """Keep one platform's controls in line with the manager's `page_keys` per device.

    At setup for every opted in device, then at every manager event for a device: a key
    that joined the set gets its control, and a key that left it loses its registry entry
    (a target with another domain profile; for a device that opted out or is gone the
    manager has removed the entries already).
    """
    manager = entry.runtime_data.manager
    hass = manager.hass
    added: set[tuple[str, str]] = set()

    @callback
    def sync(device_id: str) -> None:
        keys = manager.page_keys(device_id)
        registry = er.async_get(hass)
        for key in [key for device, key in added if device == device_id and key not in keys]:
            added.discard((device_id, key))
            unique_id = f"{DOMAIN}_{device_id}_{key}"
            if (entity_id := registry.async_get_entity_id(domain, DOMAIN, unique_id)) is not None:
                registry.async_remove(entity_id)
        new = [key for key in factories if key in keys and (device_id, key) not in added]
        added.update((device_id, key) for key in new)
        if new:
            async_add_entities([factories[key](manager, device_id) for key in new])

    @callback
    def heard(event: ManagerEvent) -> None:
        if event.device_id is not None:
            sync(event.device_id)

    for device_id in manager.opted_in_devices():
        sync(device_id)
    entry.async_on_unload(manager.async_add_listener(heard))
