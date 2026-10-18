"""The SummaryCoordinator: discovery, recompute and the Schedule sensors (TECH_SPEC 4.4).

Two levels of work, both event driven and never polled:

- The index: which automation acts on which device, parsed into lines. Rebuilt, debounced
  two seconds, when automations reload, automation entities come or go, or the entity,
  device, area, floor or label registries change.
- The views: next runs, the state sentence, items and conflicts per device. Recomputed
  from the index at every rebuild, when an automation is turned on or off, when an entity
  a time trigger reads changes, and at the earliest next run through one point in time
  listener that is replaced on every recompute.

Discovery walks the automations, not the devices: for each loaded automation the reference
helpers name the entities, devices, areas, floors and labels it references, each resolved
to the devices it can reach, and the parser then keeps only actions on that device
(decision L30).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import logging
from typing import Any, Final

from homeassistant.const import (
    EVENT_CORE_CONFIG_UPDATE,
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_STATE_CHANGED,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util

from . import conflicts, ha_adapter, nextrun, parser
from .models import (
    Conflict,
    DeviceContext,
    EntityRef,
    Occurrence,
    ParsedLine,
    ParseError,
    SummaryItem,
    TimeTrigger,
)
from .sentence import Phrases, Writer
from .settings import GlobalSettings, ScheduleScope

_LOGGER = logging.getLogger(__name__)

DEBOUNCE_SECONDS: Final = 2.0
CONFLICT_WINDOW: Final = timedelta(days=1)
OCCURRENCE_LIMIT: Final = 20
SCHEDULE_KEY: Final = "schedule"
KIND_AUTOMATION: Final = "automation"
SOURCE_PARSER: Final = "parser"
SOURCE_NONE: Final = "none"

_REGISTRY_EVENTS: Final = (
    er.EVENT_ENTITY_REGISTRY_UPDATED,
    dr.EVENT_DEVICE_REGISTRY_UPDATED,
    ar.EVENT_AREA_REGISTRY_UPDATED,
    fr.EVENT_FLOOR_REGISTRY_UPDATED,
    lr.EVENT_LABEL_REGISTRY_UPDATED,
)


def schedule_unique_id(device_id: str) -> str:
    """Return the unique id of a device's Schedule sensor."""
    return f"device_routines_{device_id}_{SCHEDULE_KEY}"


@dataclass(frozen=True, slots=True)
class IndexedLine:
    """One parsed line and the automation it came from."""

    automation_entity: str
    line: ParsedLine


@dataclass(frozen=True, slots=True)
class DeviceSummary:
    """What a device's Schedule sensor shows (PRD FR-S4)."""

    device_id: str
    device_name: str | None
    identifiers: frozenset[tuple[str, str]]
    connections: frozenset[tuple[str, str]]
    state: str | None
    items: tuple[SummaryItem, ...]
    conflicts: tuple[Conflict, ...] = ()
    next_change: datetime | None = None

    def attributes(self) -> dict[str, Any]:
        """Return the sensor attributes."""
        return {
            "items": [
                {
                    "kind": item.kind,
                    "automation": item.automation_entity,
                    "alias": item.alias,
                    "summary": item.summary,
                    "next_run": item.next_run.isoformat() if item.next_run else None,
                    "source": item.source,
                    "enabled": item.enabled,
                }
                for item in self.items
            ],
            "paused_until": None,
            "skipped_action": None,
            "conflicts": [
                {
                    "items": [conflict.a, conflict.b],
                    "reason": conflict.reason_key,
                    "at": conflict.at.isoformat() if conflict.at else None,
                }
                for conflict in self.conflicts
            ],
        }


type AddSensors = Callable[[list[str]], None]


@dataclass(slots=True)
class _Index:
    lines: dict[str, list[IndexedLine]] = field(default_factory=dict)
    time_entities: frozenset[str] = frozenset()


class SummaryCoordinator:
    """Owns the summary index, the views and the Schedule sensor lifecycle."""

    def __init__(
        self, hass: HomeAssistant, entry_id: str, settings: GlobalSettings, phrases: Phrases
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.settings = settings
        self.phrases = phrases
        self.summaries: dict[str, DeviceSummary] = {}
        self._index = _Index()
        self._listeners: dict[str, list[CALLBACK_TYPE]] = {}
        self._add_sensors: AddSensors | None = None
        self._sensor_devices: set[str] = set()
        self._unsubscribe: list[CALLBACK_TYPE] = []
        self._timer: CALLBACK_TYPE | None = None
        self._debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=DEBOUNCE_SECONDS,
            immediate=False,
            function=self._async_rebuild,
        )

    # ----------------------------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------------------------

    @callback
    def async_set_sensor_adder(self, add_sensors: AddSensors) -> None:
        """Take the sensor platform's callback for new Schedule sensors."""
        self._add_sensors = add_sensors

    async def async_start(self) -> None:
        """Subscribe to every recompute trigger and build the first index."""
        bus = self.hass.bus
        self._unsubscribe.append(
            bus.async_listen(ha_adapter.EVENT_AUTOMATION_RELOADED, self._rebuild_soon)
        )
        self._unsubscribe.extend(
            bus.async_listen(event, self._rebuild_soon, event_filter=self._foreign_change)
            for event in _REGISTRY_EVENTS
        )
        self._unsubscribe.append(
            bus.async_listen(
                EVENT_STATE_CHANGED, self._state_changed, event_filter=self._relevant_state
            )
        )
        self._unsubscribe.append(bus.async_listen(EVENT_CORE_CONFIG_UPDATE, self._refresh_soon))
        if not self.hass.is_running:
            self._unsubscribe.append(
                bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._rebuild_soon)
            )
        await self._async_rebuild()

    @callback
    def async_stop(self) -> None:
        """Drop every listener and the timer."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        self._debouncer.async_cancel()
        self._cancel_timer()

    @callback
    def async_add_listener(self, device_id: str, update: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Call `update` whenever a device's summary changes; return the unsubscriber."""
        self._listeners.setdefault(device_id, []).append(update)

        @callback
        def remove() -> None:
            self._listeners[device_id].remove(update)

        return remove

    # ----------------------------------------------------------------------------------
    # Event plumbing
    # ----------------------------------------------------------------------------------

    @callback
    def _rebuild_soon(self, _event: Event[Any] | None = None) -> None:
        self._debouncer.async_schedule_call()

    @callback
    def _refresh_soon(self, _event: Event[Any] | None = None) -> None:
        self._refresh_views()

    @callback
    def _foreign_change(self, event_data: Mapping[str, Any]) -> bool:
        """Ignore registry changes this integration made itself (its own entities)."""
        entity_id = event_data.get("entity_id")
        if isinstance(entity_id, str):
            entry = er.async_get(self.hass).async_get(entity_id)
            return entry is None or entry.config_entry_id != self.entry_id
        device_id = event_data.get("device_id")
        if isinstance(device_id, str):
            device = dr.async_get(self.hass).async_get(device_id)
            return device is None or device.config_entry_id != self.entry_id
        return True

    @callback
    def _relevant_state(self, event_data: Mapping[str, Any]) -> bool:
        entity_id: str = event_data["entity_id"]
        if entity_id.startswith("automation."):
            old: State | None = event_data.get("old_state")
            new: State | None = event_data.get("new_state")
            return old is None or new is None or old.state != new.state
        return entity_id in self._index.time_entities

    @callback
    def _state_changed(self, event: Event[Any]) -> None:
        if event.data["entity_id"].startswith("automation.") and (
            event.data.get("old_state") is None or event.data.get("new_state") is None
        ):
            self._rebuild_soon()
            return
        self._refresh_views()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer()
            self._timer = None

    # ----------------------------------------------------------------------------------
    # The index
    # ----------------------------------------------------------------------------------

    async def _async_rebuild(self) -> None:
        self._index = self._build_index()
        self._refresh_views()

    def _build_index(self) -> _Index:
        entities = er.async_get(self.hass)
        registry_ids = {entry.id: entry.entity_id for entry in entities.entities.values()}
        contexts: dict[str, DeviceContext] = {}
        lines: dict[str, list[IndexedLine]] = {}
        for refs in ha_adapter.automation_references(self.hass):
            for device_id in sorted(self._reachable_devices(refs)):
                context = contexts.get(device_id)
                if context is None:
                    context = contexts[device_id] = self._device_context(device_id, registry_ids)
                try:
                    parsed = parser.summarize(refs.config, context)
                except ParseError:
                    _LOGGER.debug("%s is not an automation config", refs.entity_id)
                    break
                lines.setdefault(device_id, []).extend(
                    IndexedLine(refs.entity_id, line) for line in parsed
                )
        lines = {device_id: found for device_id, found in lines.items() if found}
        return _Index(lines=lines, time_entities=_time_entities(lines.values()))

    def _reachable_devices(self, refs: ha_adapter.AutomationRefs) -> set[str]:
        """Return every device an automation's references can reach, except our own."""
        entities = er.async_get(self.hass)
        devices = dr.async_get(self.hass)
        areas = set(refs.areas)
        for floor_id in refs.floors:
            areas.update(
                area.id
                for area in ar.async_get(self.hass).async_list_areas()
                if area.floor_id == floor_id
            )
        found = set(refs.devices)
        entries = [
            entry
            for entity_id in refs.entities
            if (entry := entities.async_get(entity_id)) is not None
        ]
        for area_id in areas:
            found.update(device.id for device in dr.async_entries_for_area(devices, area_id))
            entries.extend(er.async_entries_for_area(entities, area_id))
        for label_id in refs.labels:
            found.update(device.id for device in dr.async_entries_for_label(devices, label_id))
            entries.extend(er.async_entries_for_label(entities, label_id))
        found.update(entry.device_id for entry in entries if entry.device_id is not None)
        return {
            device_id
            for device_id in found
            if (device := devices.async_get(device_id)) is not None
            and device.config_entry_id != self.entry_id
        }

    def _device_context(self, device_id: str, registry_ids: Mapping[str, str]) -> DeviceContext:
        device = dr.async_get(self.hass).async_get(device_id)
        assert device is not None  # noqa: S101  # _reachable_devices checked it
        areas = ar.async_get(self.hass)
        refs: list[EntityRef] = []
        for entry in er.async_entries_for_device(er.async_get(self.hass), device_id):
            area_id = entry.area_id or device.area_id
            area = areas.async_get_area(area_id) if area_id else None
            refs.append(
                EntityRef(
                    entity_id=entry.entity_id,
                    area_id=area_id,
                    floor_id=area.floor_id if area else None,
                    labels=frozenset(entry.labels | device.labels),
                    registry_id=entry.id,
                )
            )
        return DeviceContext(device_id=device_id, entities=tuple(refs), registry_ids=registry_ids)

    # ----------------------------------------------------------------------------------
    # The views
    # ----------------------------------------------------------------------------------

    @callback
    def _refresh_views(self) -> None:
        now = dt_util.now()
        lookups = nextrun.Lookups(sun=self._sun, entity_times=self._entity_times())
        writer = Writer(
            self.phrases,
            self.settings.resolved_time_format(self.hass.config.country),
            _NameLookup(self.hass),
        )
        devices = dr.async_get(self.hass)
        summaries: dict[str, DeviceSummary] = {}
        for device_id, indexed in self._index.lines.items():
            device = devices.async_get(device_id)
            if device is None:
                continue
            summaries[device_id] = self._summary(device, indexed, now, lookups, writer)
        changed = {
            device_id
            for device_id in summaries.keys() | self.summaries.keys()
            if summaries.get(device_id) != self.summaries.get(device_id)
        }
        self.summaries = summaries
        self._reconcile_sensors()
        for device_id in changed:
            for update in list(self._listeners.get(device_id, [])):
                update()
        self._schedule_next(now)

    def _summary(
        self,
        device: dr.AnyDeviceEntry,
        indexed: list[IndexedLine],
        now: datetime,
        lookups: nextrun.Lookups,
        writer: Writer,
    ) -> DeviceSummary:
        rows: list[tuple[SummaryItem, list[Occurrence], tuple[str, ...]]] = []
        for entry in indexed:
            enabled = _is_on(self.hass.states.get(entry.automation_entity))
            occurrences = (
                nextrun.next_occurrences(entry.line, now, lookups, limit=OCCURRENCE_LIMIT)
                if enabled
                else []
            )
            item = SummaryItem(
                kind=KIND_AUTOMATION,
                automation_entity=entry.automation_entity,
                alias=entry.line.alias,
                summary=writer.line(entry.line),
                next_run=occurrences[0].at if occurrences else None,
                source=SOURCE_PARSER if entry.line.understood else SOURCE_NONE,
                enabled=enabled,
                custom_logic=entry.line.custom_logic,
            )
            # One automation acting several times on a device the same way reads once.
            if any(row[0] == item for row in rows):
                continue
            rows.append((item, occurrences, entry.line.entity_ids))
        rows.sort(key=_row_order)
        items = tuple(row[0] for row in rows)
        upcoming = nextrun.earliest(row[1][0] for row in rows if row[1])
        fallback = next((item.summary for item in items if item.enabled), items[0].summary)
        planned = [
            conflicts.Planned(index, entity_ids, tuple(occurrences))
            for index, (_, occurrences, entity_ids) in enumerate(rows)
        ]
        return DeviceSummary(
            device_id=device.id,
            device_name=device.name,
            identifiers=frozenset(device.identifiers),
            connections=(
                frozenset(device.connections) if isinstance(device, dr.DeviceEntry) else frozenset()
            ),
            state=writer.state(upcoming, fallback, now),
            items=items,
            conflicts=tuple(conflicts.find(planned, now, now + CONFLICT_WINDOW)),
            next_change=upcoming.at if upcoming else None,
        )

    def _sun(self, day: date, event: str) -> datetime | None:
        return get_astral_event_date(self.hass, event, day)

    def _entity_times(self) -> dict[str, time | datetime]:
        held: dict[str, time | datetime] = {}
        for entity_id in self._index.time_entities:
            value = _held_time(self.hass.states.get(entity_id))
            if value is not None:
                held[entity_id] = value
        return held

    def _schedule_next(self, now: datetime) -> None:
        self._cancel_timer()
        upcoming = [s.next_change for s in self.summaries.values() if s.next_change is not None]
        if not upcoming:
            return
        when = max(min(upcoming), now) + timedelta(seconds=1)
        self._timer = async_track_point_in_time(self.hass, self._timer_fired, when)

    @callback
    def _timer_fired(self, _now: datetime) -> None:
        self._timer = None
        self._refresh_views()

    # ----------------------------------------------------------------------------------
    # Sensor lifecycle per schedule_scope
    # ----------------------------------------------------------------------------------

    def _wanted_sensors(self) -> set[str]:
        if self.settings.schedule_scope is ScheduleScope.ALL:
            return set(self.summaries)
        # Routines arrive in Phase 2; until then the routines scope has no device.
        return set()

    def _reconcile_sensors(self) -> None:
        wanted = self._wanted_sensors()
        registry = er.async_get(self.hass)
        stale = [
            entry
            for entry in er.async_entries_for_config_entry(registry, self.entry_id)
            if entry.unique_id.endswith(f"_{SCHEDULE_KEY}")
            and entry.unique_id not in {schedule_unique_id(device) for device in wanted}
        ]
        for entry in stale:
            registry.async_remove(entry.entity_id)
        self._sensor_devices &= wanted
        new = sorted(wanted - self._sensor_devices)
        if new and self._add_sensors is not None:
            self._sensor_devices.update(new)
            self._add_sensors(new)


class _NameLookup(Mapping[str, str]):
    """Friendly names from the state machine, looked up only when a sentence needs one."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def __getitem__(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        if state is None:
            raise KeyError(entity_id)
        return state.name

    def __iter__(self) -> Any:
        return iter(self.hass.states.async_entity_ids())

    def __len__(self) -> int:
        return self.hass.states.async_entity_ids_count()


def _is_on(state: State | None) -> bool:
    return state is not None and state.state == "on"


def _row_order(row: tuple[SummaryItem, list[Occurrence], tuple[str, ...]]) -> tuple[Any, ...]:
    item = row[0]
    rank = 0 if item.next_run else (1 if item.source == SOURCE_PARSER else 2)
    return (rank, item.next_run or datetime.max.replace(tzinfo=dt_util.UTC), item.alias)


def _time_entities(groups: Iterable[list[IndexedLine]]) -> frozenset[str]:
    """Return every entity a time trigger or a time window reads."""
    found: set[str] = set()
    for group in groups:
        for entry in group:
            for trigger in entry.line.triggers:
                if isinstance(trigger, TimeTrigger) and trigger.entity:
                    found.add(trigger.entity)
            for window in entry.line.windows:
                found.update(b for b in (window.after, window.before) if isinstance(b, str))
    return frozenset(found)


def _held_time(state: State | None) -> time | datetime | None:
    """Return the time an input_datetime or timestamp sensor holds, or None."""
    if state is None or state.state in {"unknown", "unavailable", ""}:
        return None
    if state.domain == "input_datetime" and not state.attributes.get("has_date", False):
        return dt_util.parse_time(state.state)
    moment = dt_util.parse_datetime(state.state)
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt_util.get_default_time_zone())
