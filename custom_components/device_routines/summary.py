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

Routines (Build A lane 7, plan Section 4.2). The manager is a `RoutineItemsProvider`: for
a device it returns a `RoutineSummary` whose items are the routine's own lines, sorted
first, and whose status picks the state form of PRD FR-S4 (Skipped, Paused until, Routine
off). The manager calls `async_refresh_device` after every change of a routine, which
recomputes that device's view without rebuilding the index. Ownership is read from the
markers, never from the provider:

- An owned automation (M1 and M2) is parsed like every automation and its lines carry the
  kind `routine`. When the provider returns a summary for the device whose routine id it
  carries, the provider's items replace those lines, and the routine's next actions come
  from its blueprint inputs (`compiler.decompile`, then `nextrun.routine_occurrences`
  after Paused until), so the state names the action Skip next would skip.
- A detached routine (M1 without M2, Stage 0 V8) is parsed like any automation with the
  kind `detached_routine`; a line the parser cannot read is the translated kind phrase.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import logging
from typing import Any, Final, Protocol

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

from . import compiler, conflicts, ha_adapter, markers, nextrun, parser, repairs
from .models import (
    Conflict,
    DeviceContext,
    EntityRef,
    Occurrence,
    ParsedLine,
    ParseError,
    RoutineSettings,
    Status,
    SummaryItem,
    TimeTrigger,
    Verb,
    Weekday,
)
from .sentence import Phrases, Writer
from .settings import GlobalSettings, ScheduleScope

_LOGGER = logging.getLogger(__name__)

DEBOUNCE_SECONDS: Final = 2.0
CONFLICT_WINDOW: Final = timedelta(days=1)
OCCURRENCE_LIMIT: Final = 20
SCHEDULE_KEY: Final = "schedule"
KIND_AUTOMATION: Final = "automation"
KIND_ROUTINE: Final = "routine"
KIND_DETACHED: Final = "detached_routine"
SOURCE_PARSER: Final = "parser"
SOURCE_NONE: Final = "none"

# Statuses whose state reads "Routine off": the switch is off, or the manager turned the
# routine off because its inputs are invalid or its target is gone (PRD 8.2, FR-R14).
_OFF_STATUSES: Final = frozenset({Status.OFF, Status.INVALID, Status.MISSING_TARGET})
# Statuses under which the routine's automation runs its scheduled actions.
_RUNNING_STATUSES: Final = frozenset({Status.ACTIVE, Status.PAUSED, Status.SKIPPING})
_PAUSING_STATUSES: Final = frozenset({Status.PAUSED, Status.SKIPPING})

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
class RoutineSummary:
    """A device's routine as the manager hands it to the summary (plan Section 4.2).

    `items` are the routine's own lines (kind `routine`); they sort first and replace the
    parsed lines of the device's owned automation. `paused_until` is the stored Paused
    until value; it counts while `status` is paused or skipping and it is in the future.
    `skipped_action` is the action Skip next skipped (the `RoutineView` field, not the
    next one that runs); it fills the `skipped_action` attribute while skipping. The
    state names the next action that really runs, computed here from the routine's
    inputs. `status` picks the state form; `detached` hands the device back to the parser.
    """

    items: tuple[SummaryItem, ...]
    paused_until: datetime | None
    skipped_action: Occurrence | None
    status: Status


class RoutineItemsProvider(Protocol):
    """What the manager implements so the Schedule summary shows routines."""

    def routine_summary(self, device_id: str) -> RoutineSummary | None:
        """Return the device's routine, or None when the device has none the manager knows."""


@dataclass(frozen=True, slots=True)
class IndexedLine:
    """One parsed line, the automation it came from and that automation's kind."""

    automation_entity: str
    line: ParsedLine
    kind: str = KIND_AUTOMATION


@dataclass(frozen=True, slots=True)
class _OwnedRoutine:
    """A device's own routine automation (M1 and M2) with the settings its inputs hold.

    `automation_id` and `device_id` (the `device_id` input) tie it to its device even
    under an id other than `markers.automation_id(device_id)`: the manager gives a new
    routine the next free id when the device's old one was taken over (detached).
    """

    automation_entity: str
    settings: RoutineSettings
    timer_entity: str | None
    automation_id: str = ""
    device_id: str | None = None


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
    paused_until: datetime | None = None
    skipped_action: str | None = None
    has_routine: bool = False

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
            "paused_until": self.paused_until.isoformat() if self.paused_until else None,
            "skipped_action": self.skipped_action,
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
    routines: dict[str, _OwnedRoutine] = field(default_factory=dict)
    # The timer and weekly schedule helpers of the routines, whose states move the views.
    runtime_entities: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class _Row:
    """One item with the occurrences the state, the timer and the conflicts read."""

    item: SummaryItem
    occurrences: Sequence[Occurrence]
    entity_ids: tuple[str, ...]
    routine: RoutineSettings | None = None


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
        self._provider: RoutineItemsProvider | None = None
        # Devices the manager named that the index may not hold (a routine whose
        # automation is not loaded); dropped once the provider no longer knows them.
        self._routine_devices: set[str] = set()
        self._started = False
        self._debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=DEBOUNCE_SECONDS,
            immediate=False,
            function=self._async_rebuild,
        )
        # Listeners of every device's changes: the hub Routines sensor (Build A lane 14).
        self._change_listeners: list[CALLBACK_TYPE] = []

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
        self._started = True
        await self._async_rebuild()

    @callback
    def async_stop(self) -> None:
        """Drop every listener and the timer."""
        self._started = False
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        self._debouncer.async_cancel()
        self._cancel_timer()

    @callback
    def set_routine_provider(self, provider: RoutineItemsProvider | None) -> None:
        """Take the manager as the source of routine items; None stops asking.

        Once started, every view is recomputed from the index as it is (no rebuild).
        """
        self._provider = provider
        if self._started:
            self._refresh_views()

    @callback
    def async_refresh_device(self, device_id: str) -> None:
        """Recompute one device's view and push its sensor, without rebuilding the index.

        A callback, not awaited. The manager calls it after every change of a routine;
        a device the index does not hold is shown from the provider alone and is asked
        about at every later refresh until the provider returns None for it.
        """
        self._routine_devices.add(device_id)
        if not self._started:
            return
        now = dt_util.now()
        summary = self._device_summary(device_id, now, self._lookups(), self._writer())
        summaries = dict(self.summaries)
        previous = summaries.pop(device_id, None)
        if summary is not None:
            summaries[device_id] = summary
        self.summaries = summaries
        self._reconcile_sensors()
        async_sync_conflict_issues(
            self.hass, summaries, self._writer(), enabled=self.settings.raise_conflict_repairs
        )
        if summary != previous:
            self._notify(device_id)
        self._schedule_next(now)

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
        return entity_id in self._index.time_entities or entity_id in self._index.runtime_entities

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
        routines: dict[str, _OwnedRoutine] = {}
        for refs in ha_adapter.automation_references(self.hass):
            config = _marked(refs)
            kind = _kind(config)
            owned = _owned_routine(refs.entity_id, config) if kind == KIND_ROUTINE else None
            for device_id in sorted(self._reachable_devices(refs)):
                if owned is not None and (
                    owned.device_id == device_id
                    or config.get("id") == markers.automation_id(device_id)
                ):
                    routines[device_id] = owned
                context = contexts.get(device_id)
                if context is None:
                    context = contexts[device_id] = self._device_context(device_id, registry_ids)
                try:
                    parsed = parser.summarize(refs.config, context)
                except ParseError:
                    _LOGGER.debug("%s is not an automation config", refs.entity_id)
                    break
                lines.setdefault(device_id, []).extend(
                    IndexedLine(refs.entity_id, line, kind) for line in parsed
                )
        lines = {device_id: found for device_id, found in lines.items() if found}
        return _Index(
            lines=lines,
            time_entities=_time_entities(lines.values()),
            routines=routines,
            runtime_entities=frozenset(
                entity
                for owned in routines.values()
                for entity in (owned.timer_entity, owned.settings.schedule_entity)
                if entity is not None
            ),
        )

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

    def _lookups(self) -> nextrun.Lookups:
        return nextrun.Lookups(sun=self._sun, entity_times=self._entity_times())

    def _writer(self) -> Writer:
        return Writer(
            self.phrases,
            self.settings.resolved_time_format(self.hass.config.country),
            _NameLookup(self.hass),
        )

    def _notify(self, device_id: str) -> None:
        for update in list(self._listeners.get(device_id, [])):
            update()
        for update in list(self._change_listeners):
            update()

    @callback
    def async_add_change_listener(self, update: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Call `update` whenever any device's summary changes; return the unsubscriber.

        The hub Routines sensor follows the routines' next actions this way, so it moves
        on at each action without a timer of its own.
        """
        self._change_listeners.append(update)

        @callback
        def remove() -> None:
            self._change_listeners.remove(update)

        return remove

    @callback
    def _refresh_views(self) -> None:
        now = dt_util.now()
        lookups = self._lookups()
        writer = self._writer()
        summaries: dict[str, DeviceSummary] = {}
        for device_id in sorted(self._index.lines.keys() | self._routine_devices):
            summary = self._device_summary(device_id, now, lookups, writer)
            if summary is not None:
                summaries[device_id] = summary
        changed = {
            device_id
            for device_id in summaries.keys() | self.summaries.keys()
            if summaries.get(device_id) != self.summaries.get(device_id)
        }
        self.summaries = summaries
        self._reconcile_sensors()
        async_sync_conflict_issues(
            self.hass, summaries, writer, enabled=self.settings.raise_conflict_repairs
        )
        for device_id in changed:
            self._notify(device_id)
        self._schedule_next(now)

    def _device_summary(
        self, device_id: str, now: datetime, lookups: nextrun.Lookups, writer: Writer
    ) -> DeviceSummary | None:
        """Return a device's view from the index and the provider; None with no item."""
        routine = self._provider.routine_summary(device_id) if self._provider else None
        if routine is None:
            self._routine_devices.discard(device_id)
        device = dr.async_get(self.hass).async_get(device_id)
        if device is None:
            return None
        return self._summary(device, routine, now, lookups, writer)

    def _summary(
        self,
        device: dr.AnyDeviceEntry,
        routine: RoutineSummary | None,
        now: datetime,
        lookups: nextrun.Lookups,
        writer: Writer,
    ) -> DeviceSummary | None:
        indexed = self._index.lines.get(device.id, [])
        pause_end = _pause_end(routine, now)
        # The provider's items stand for the device's own routine automation, unless the
        # routine was detached (then that automation is an ordinary one again) or the
        # provider has no line for it (then the parsed lines stay).
        provided = (
            routine
            if routine is not None and routine.status is not Status.DETACHED and routine.items
            else None
        )
        rows = self._routine_rows(device.id, provided, pause_end, now) if provided else []
        # The next action the routine really runs, known when its inputs were read.
        routine_next = (
            rows[0].occurrences[0] if rows and rows[0].routine and rows[0].occurrences else None
        )
        owned_routine = self._index.routines.get(device.id)
        own_id = owned_routine.automation_id if owned_routine else markers.automation_id(device.id)
        for entry in indexed:
            if provided and entry.kind == KIND_ROUTINE and entry.line.automation_id == own_id:
                continue
            row = self._parsed_row(entry, now, lookups, writer)
            # One automation acting several times on a device the same way reads once.
            if any(existing.item == row.item for existing in rows):
                continue
            rows.append(row)
        if not rows:
            return None
        rows.sort(key=_row_order)
        items = tuple(row.item for row in rows)
        upcoming = nextrun.earliest(row.occurrences[0] for row in rows if row.occurrences)
        fallback = next((item.summary for item in items if item.enabled), items[0].summary)
        planned = [
            conflicts.Planned(index, row.entity_ids, tuple(row.occurrences), row.routine)
            for index, row in enumerate(rows)
        ]
        changes = [m for m in (upcoming.at if upcoming else None, pause_end) if m is not None]
        return DeviceSummary(
            device_id=device.id,
            device_name=device.name,
            identifiers=frozenset(device.identifiers),
            connections=(
                frozenset(device.connections) if isinstance(device, dr.DeviceEntry) else frozenset()
            ),
            state=_state(
                writer,
                routine,
                pause_end=pause_end,
                routine_next=routine_next,
                upcoming=upcoming,
                fallback=fallback,
                now=now,
            ),
            items=items,
            conflicts=tuple(conflicts.find(planned, now, now + CONFLICT_WINDOW)),
            next_change=min(changes, default=None),
            paused_until=pause_end,
            skipped_action=_skipped_line(writer, routine, pause_end, now),
            has_routine=routine is not None or any(e.kind == KIND_ROUTINE for e in indexed),
        )

    def _parsed_row(
        self, entry: IndexedLine, now: datetime, lookups: nextrun.Lookups, writer: Writer
    ) -> _Row:
        enabled = _is_on(self.hass.states.get(entry.automation_entity))
        occurrences = (
            nextrun.next_occurrences(entry.line, now, lookups, limit=OCCURRENCE_LIMIT)
            if enabled
            else []
        )
        if entry.kind != KIND_AUTOMATION and not entry.line.understood:
            # "Routine" or "Detached routine" where an automation reads "Automation: ...".
            text = writer.routine_kind(detached=entry.kind == KIND_DETACHED)
        else:
            text = writer.line(entry.line)
        item = SummaryItem(
            kind=entry.kind,
            automation_entity=entry.automation_entity,
            alias=entry.line.alias,
            summary=text,
            next_run=occurrences[0].at if occurrences else None,
            source=SOURCE_PARSER if entry.line.understood else SOURCE_NONE,
            enabled=enabled,
            custom_logic=entry.line.custom_logic,
        )
        return _Row(item, occurrences, entry.line.entity_ids)

    def _routine_rows(
        self, device_id: str, routine: RoutineSummary, pause_end: datetime | None, now: datetime
    ) -> list[_Row]:
        """Return the provider's items as rows.

        The first item stands for the owned automation: while it runs, its next actions
        are computed from its inputs after Paused until; while it does not, it has none.
        Every other item, and every item before the owned automation is indexed, counts
        its own next run with its action unknown.
        """
        rows = [
            _Row(item, [Occurrence(item.next_run, None)] if item.next_run else [], ())
            for item in routine.items
        ]
        owned = self._index.routines.get(device_id)
        if owned is None:
            return rows
        first = rows[0].item
        if routine.status in _RUNNING_STATUSES and _is_on(
            self.hass.states.get(owned.automation_entity)
        ):
            settings = owned.settings
            occurrences = self._routine_occurrences(owned, pause_end, now)
            rows[0] = _Row(first, occurrences, (settings.target_entity,), settings)
        else:
            rows[0] = _Row(first, [], ())
        return rows

    def _routine_occurrences(
        self, owned: _OwnedRoutine, pause_end: datetime | None, now: datetime
    ) -> list[Occurrence]:
        """Return the routine's coming actions from its settings and its helpers' states."""
        settings = owned.settings
        schedule_state: str | None = None
        entity_times: dict[str, time | datetime] = {}
        if settings.schedule_entity is not None:
            schedule = self.hass.states.get(settings.schedule_entity)
            schedule_state = schedule.state if schedule else None
            if (next_event := _attribute_moment(schedule, "next_event")) is not None:
                entity_times[settings.schedule_entity] = next_event
        timer = self.hass.states.get(owned.timer_entity) if owned.timer_entity else None
        return nextrun.routine_occurrences(
            settings,
            now,
            schedule_state,
            nextrun.Lookups(sun=self._sun, entity_times=entity_times),
            countdown_ends=_attribute_moment(timer, "finishes_at", "active"),
            not_before=pause_end,
        )[:OCCURRENCE_LIMIT]

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
        if self.settings.schedule_scope is ScheduleScope.ROUTINES:
            return {device for device, summary in self.summaries.items() if summary.has_routine}
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

    # ----------------------------------------------------------------------------------
    # A day's planned actions: the console's Today view (Build A lane 12, decision L45)
    # ----------------------------------------------------------------------------------

    def day_schedule(self, day: date) -> list[DayItem]:
        """Return every action planned for a local day, routines and automations, by time.

        The data of the `schedule/today` WebSocket command (TECH_SPEC 4.7). The day is read
        from the index and the routines as they stand now, so an action earlier in the day
        is listed as planned; a routine action its pause skips (after now and before
        Paused until) and every action of an automation that is off are left out. Each
        action is one item per device, its `conflict` set when it takes part in an FR-S6
        conflict in its own minute.
        """
        start = dt_util.start_of_local_day(day)
        end = dt_util.start_of_local_day(day + timedelta(days=1))
        now = dt_util.now()
        lookups = self._lookups()
        devices = dr.async_get(self.hass)
        found: list[DayItem] = []
        for device_id in sorted(self.summaries):
            device = devices.async_get(device_id)
            if device is None:
                continue
            rows = self._day_rows(device_id, start, end, now, lookups)
            found.extend(_day_items(device_id, device.area_id, rows, start, end))
        return sorted(found, key=lambda item: (item.time, item.device_id, item.automation))

    def _day_rows(
        self,
        device_id: str,
        start: datetime,
        end: datetime,
        now: datetime,
        lookups: nextrun.Lookups,
    ) -> list[_DayRow]:
        """Return a device's rows with their runs from the start of the day.

        The rows the device's view is made of (`_summary`): the provider's items stand for
        the owned routine automation, whose parsed lines are then left out.
        """
        routine = self._provider.routine_summary(device_id) if self._provider else None
        provided = (
            routine
            if routine is not None and routine.status is not Status.DETACHED and routine.items
            else None
        )
        rows = self._day_routine_rows(device_id, provided, start, now) if provided else []
        owned = self._index.routines.get(device_id)
        own_id = owned.automation_id if owned else markers.automation_id(device_id)
        since = start - _INSTANT
        for entry in self._index.lines.get(device_id, []):
            if provided and entry.kind == KIND_ROUTINE and entry.line.automation_id == own_id:
                continue
            runs = (
                nextrun.next_occurrences(
                    entry.line, since, lookups, horizon=timedelta(days=1), limit=DAY_LIMIT
                )
                if _is_on(self.hass.states.get(entry.automation_entity))
                else []
            )
            rows.append(
                _DayRow(
                    entry.kind,
                    entry.automation_entity,
                    entry.line.entity_ids,
                    tuple(run for run in runs if run.at < end),
                )
            )
        return rows

    def _day_routine_rows(
        self, device_id: str, routine: RoutineSummary, start: datetime, now: datetime
    ) -> list[_DayRow]:
        """Return the provider's items as rows, the way `_routine_rows` reads them.

        The first item stands for the owned automation: while it runs, its actions come
        from its inputs, less those its pause skips; while it does not, it has none. Every
        other item, and every item before the owned automation is indexed, counts its next
        run with its action unknown.
        """
        owned = self._index.routines.get(device_id)
        pause_end = _pause_end(routine, now)
        rows: list[_DayRow] = []
        for index, item in enumerate(routine.items):
            if index or owned is None:
                runs: tuple[Occurrence, ...] = (
                    (Occurrence(item.next_run, None),) if item.next_run else ()
                )
                rows.append(_DayRow(item.kind, item.automation_entity, (), runs))
            elif routine.status in _RUNNING_STATUSES and _is_on(
                self.hass.states.get(owned.automation_entity)
            ):
                planned = self._routine_occurrences(owned, None, start - _INSTANT)
                runs = tuple(
                    run
                    for run in planned
                    if pause_end is None or not now < run.at < pause_end  # skipped by the pause
                )
                settings = owned.settings
                rows.append(
                    _DayRow(
                        item.kind, item.automation_entity, (settings.target_entity,), runs, settings
                    )
                )
            else:
                rows.append(_DayRow(item.kind, item.automation_entity, (), ()))
        return rows


@callback
def async_sync_conflict_issues(
    hass: HomeAssistant, summaries: Mapping[str, DeviceSummary], writer: Writer, *, enabled: bool
) -> None:
    """Keep the `conflict` Repairs issues in line with the views (FR-S6, Build A lane 11).

    An issue is raised only for a routine against another automation that drives the same
    entity in the opposite direction in the same minute: never for two hand written
    automations, and never for an action that only contradicts a routine window (both stay
    in the `conflicts` attribute). One issue per routine, keyed by its automation id
    (decision L41), names the routine, every automation it collides with and the earliest
    time of day they collide; it clears when the collision ends. While
    `raise_conflict_repairs` is off, every `conflict` issue is cleared.
    """
    routines: dict[str, tuple[str, str]] = {}  # subject: the device and the routine
    others: dict[str, set[str]] = {}
    earliest: dict[str, time] = {}
    for summary in summaries.values() if enabled else ():
        for conflict in summary.conflicts:
            first, second = summary.items[conflict.a], summary.items[conflict.b]
            if first.kind != KIND_ROUTINE:
                first, second = second, first
            if (
                conflict.reason_key != conflicts.SAME_MINUTE
                or first.kind != KIND_ROUTINE
                or first.automation_entity == second.automation_entity
            ):
                continue
            assert conflict.at is not None  # noqa: S101  # same minute conflicts have a time
            entry = er.async_get(hass).async_get(first.automation_entity)
            subject = entry.unique_id if entry is not None else first.automation_entity
            device = dr.async_get(hass).async_get(summary.device_id)
            name = (device.name_by_user or device.name) if device else summary.device_name
            at = dt_util.as_local(conflict.at).time().replace(second=0, microsecond=0)
            routines[subject] = (name or summary.device_id, first.alias)
            others.setdefault(subject, set()).add(second.alias)
            earliest[subject] = min(earliest.get(subject, at), at)
    repairs.async_sync_issues(
        hass,
        repairs.CONFLICT,
        {
            subject: {
                "device": device_name,
                "first": routine,
                "second": ", ".join(sorted(others[subject])),
                "time": writer.clock(earliest[subject]),
            }
            for subject, (device_name, routine) in routines.items()
        },
    )


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


def _row_order(row: _Row) -> tuple[Any, ...]:
    """Routines first (PRD FR-S4); then timed lines by time, read lines, custom logic."""
    item = row.item
    rank = 0 if item.next_run else (1 if item.source == SOURCE_PARSER else 2)
    return (
        item.kind != KIND_ROUTINE,
        rank,
        item.next_run or datetime.max.replace(tzinfo=dt_util.UTC),
        item.alias,
    )


def _marked(refs: ha_adapter.AutomationRefs) -> Mapping[str, Any]:
    """Return the config as `automations.yaml` holds it, `use_blueprint` included.

    The loaded entity's config is the rendered one, so the adapter reads the block apart.
    """
    if refs.blueprint is None:
        return refs.config
    return {**refs.config, "use_blueprint": refs.blueprint}


def _kind(config: Mapping[str, Any]) -> str:
    """Owned (M1 and M2) is a routine; M1 alone is a detached routine (Stage 0 V8)."""
    if markers.is_owned(config):
        return KIND_ROUTINE
    if markers.has_routine_id(config):
        return KIND_DETACHED
    return KIND_AUTOMATION


def _owned_routine(entity_id: str, config: Mapping[str, Any]) -> _OwnedRoutine | None:
    """Return an owned automation's settings, or None when its inputs do not read."""
    inputs = config["use_blueprint"].get("input")
    if not compiler.is_valid_shape(inputs):
        return None
    refs = compiler.refs_of(inputs)
    timer = refs.timer_entity
    return _OwnedRoutine(
        automation_entity=entity_id,
        settings=compiler.decompile(inputs),
        timer_entity=None if timer == compiler.UNUSED_TIMER else timer,
        automation_id=str(config.get("id", "")),
        device_id=refs.device_id,
    )


def _pause_end(routine: RoutineSummary | None, now: datetime) -> datetime | None:
    """Return Paused until while the routine is paused or skipping and it is ahead."""
    if (
        routine is None
        or routine.status not in _PAUSING_STATUSES
        or routine.paused_until is None
        or routine.paused_until <= now
    ):
        return None
    return routine.paused_until


def _state(  # noqa: PLR0913  # every input of the FR-S4 state
    writer: Writer,
    routine: RoutineSummary | None,
    *,
    pause_end: datetime | None,
    routine_next: Occurrence | None,
    upcoming: Occurrence | None,
    fallback: str,
    now: datetime,
) -> str | None:
    """Return the state: the routine's form first (FR-S4), else the earliest action."""
    if routine is not None and routine.status in _OFF_STATUSES:
        return writer.routine_off()
    if pause_end is not None:
        assert routine is not None  # noqa: S101  # a pause needs a routine
        if routine.status is Status.SKIPPING and routine_next is not None:
            assert routine_next.verb is not None  # noqa: S101  # routine actions have verbs
            return writer.skipped(routine_next.verb, routine_next.at, now)
        return writer.paused(pause_end, now)
    return writer.state(upcoming, fallback, now)


def _skipped_line(
    writer: Writer, routine: RoutineSummary | None, pause_end: datetime | None, now: datetime
) -> str | None:
    """Return the skipped action as a line ("5:00 PM: on") while the routine skips."""
    if (
        pause_end is None
        or routine is None
        or routine.status is not Status.SKIPPING
        or routine.skipped_action is None
        or routine.skipped_action.verb is None
    ):
        return None
    action = routine.skipped_action
    moment = action.at.astimezone(now.tzinfo)
    weekdays = None if moment.date() == now.date() else frozenset({Weekday.of(moment)})
    line = ParsedLine(
        automation_id="",
        alias="",
        entity_ids=(),
        verb=action.verb,
        triggers=(TimeTrigger(at=moment.time(), weekdays=weekdays),),
    )
    return writer.line(line)


def _moment(value: Any) -> datetime | None:
    """Return an aware datetime from a state attribute: a datetime or an ISO string."""
    if isinstance(value, str):
        value = dt_util.parse_datetime(value)
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt_util.get_default_time_zone())


def _attribute_moment(
    state: State | None, attribute: str, when: str | None = None
) -> datetime | None:
    """Return a datetime attribute of a state, only in the state `when` if one is given."""
    if state is None or (when is not None and state.state != when):
        return None
    return _moment(state.attributes.get(attribute))


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


# --------------------------------------------------------------------------------------
# A day's planned actions (Build A lane 12)
# --------------------------------------------------------------------------------------

# How many runs of one line a day may hold: a time pattern every minute, with a follow up.
DAY_LIMIT: Final = 2 * 24 * 60
# Just before midnight, so an action at 00:00 counts as the day's first.
_INSTANT: Final = timedelta(microseconds=1)


@dataclass(frozen=True, slots=True)
class DayItem:
    """One action planned for a local day: an item of the console's Today view.

    `action` is None when it is not known (a routine whose automation is not indexed yet);
    `kind` and `automation` are those of the Schedule item it belongs to.
    """

    time: datetime
    device_id: str
    area_id: str | None
    action: Verb | None
    kind: str
    automation: str
    conflict: bool = False


@dataclass(frozen=True, slots=True)
class _DayRow:
    """One Schedule item of a device with its runs; `routine` is set while a routine runs."""

    kind: str
    automation: str
    entity_ids: tuple[str, ...]
    runs: tuple[Occurrence, ...]
    routine: RoutineSettings | None = None


def _day_items(
    device_id: str, area_id: str | None, rows: Sequence[_DayRow], start: datetime, end: datetime
) -> list[DayItem]:
    """Return a device's runs inside the day as items, each once, with its conflict flag.

    `conflicts.find` reports one conflict per pair and reason in a window, so it is asked
    minute by minute: every run in a conflicting minute of a conflicting row is marked.
    """
    inside = [tuple(run for run in row.runs if start <= run.at < end) for row in rows]
    planned = [
        conflicts.Planned(index, row.entity_ids, runs, row.routine)
        for index, (row, runs) in enumerate(zip(rows, inside, strict=True))
    ]
    marked: set[tuple[int, datetime]] = set()
    for minute in sorted({_minute_of(run.at) for runs in inside for run in runs}):
        for found in conflicts.find(planned, minute, minute + timedelta(minutes=1)):
            marked.update(((found.a, minute), (found.b, minute)))
    items: dict[tuple[Any, ...], DayItem] = {}
    for index, (row, runs) in enumerate(zip(rows, inside, strict=True)):
        for run in runs:
            key = (run.at, run.verb, row.kind, row.automation)
            earlier = items.get(key)
            conflict = (index, _minute_of(run.at)) in marked or bool(earlier and earlier.conflict)
            items[key] = DayItem(
                run.at, device_id, area_id, run.verb, row.kind, row.automation, conflict
            )
    return list(items.values())


def _minute_of(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)
