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

The provider also hands over the routine's settings as the manager holds them (Build B
lane 22, L69): the routine's next actions, its conflicts and its Today rows read them
rather than the inputs, which follow a change only after the debounced write and the
index rebuild, so a conflict a change creates is answered at once. The state names a
sun instant to the whole minute (`stated`); a device whose automations are all off reads
"Automation off" or "Automations off".

The optional AI path (Build A lane 14, PRD FR-S5) lives in `AiSummaries`: after every
index rebuild it queues the hand written automations with a line the parser could not
fully read, asks the chosen AI Task entity about them one at a time, and the views show
a cached answer in place of the custom logic line, marked `(AI)` and `source: ai`. A
change listener (`async_add_change_listener`) lets the hub Routines sensor follow every
device's summary, and tells the manager after each view refresh that moved one, which
it pushes to its listeners as one debounced `schedule_changed` (L49).

Conversion offers (Build B lane 20, PRD FR-M1, decisions L61 and L65). While
`offer_conversions` is on, every index rebuild asks `conversion.match` about each hand
written automation (not owned, not detached) on each device it acts on, and keeps the
matches whose settings `compiler.validate` accepts for the profile of the entity they
drive, an entity a routine can drive (`domains.pick_targets`), of an automation with an
entity registry entry (the `Replaced by routine` label lives there). Every view refresh
turns the matches into offers (`conversion_offers`): only an automation that is on, only
for a device without a routine (an owned automation in the index, or any routine the
provider knows, a detached one included), one offer per automation. The offers raise
and clear the `conversion_offer` Repairs issues, one per automation, and a change of the
offers tells the change listeners, so the console hears it as `schedule_changed`.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
import logging
from typing import Any, Final, Protocol

from homeassistant.const import (
    EVENT_CORE_CONFIG_UPDATE,
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_STATE_CHANGED,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_point_in_time, async_track_point_in_utc_time
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util
import probatio as vol

from . import (
    ai_prompt,
    compiler,
    conflicts,
    conversion,
    ha_adapter,
    markers,
    nextrun,
    parser,
    repairs,
)
from .domains import Candidate, pick_targets, profile_for
from .models import (
    PAUSING_STATUSES,
    Conflict,
    DeviceContext,
    DomainProfile,
    EntityRef,
    Occurrence,
    ParsedLine,
    ParseError,
    RoutineSettings,
    Status,
    SummaryItem,
    SunTrigger,
    TimeTrigger,
    Verb,
    Weekday,
)
from .sentence import Phrases, Writer
from .settings import GlobalSettings, ScheduleScope
from .store import AiCacheEntry, RoutineStore

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
SOURCE_AI: Final = "ai"

# The AI path (PRD FR-S5): never in the first five minutes after a start, and at most
# `ai_calls_per_hour` calls in any hour.
AI_STARTUP_DELAY: Final = timedelta(minutes=5)
AI_PERIOD: Final = timedelta(hours=1)
AI_TASK_DOMAIN: Final = "ai_task"
AI_TASK_SERVICE: Final = "generate_data"

# Statuses whose state reads "Routine off": the switch is off, or the manager turned the
# routine off because its inputs are invalid or its target is gone (PRD 8.2, FR-R14).
_OFF_STATUSES: Final = frozenset({Status.OFF, Status.INVALID, Status.MISSING_TARGET})
# Statuses under which the routine's automation runs its scheduled actions.
_RUNNING_STATUSES: Final = frozenset({Status.ACTIVE, Status.PAUSED, Status.SKIPPING})

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


# The sun events and offsets lines run at: ("sunset", 30 minutes) for "Sunset + 30 min".
type SunMarks = frozenset[tuple[str, timedelta]]


def sun_marks(lines: Iterable[ParsedLine]) -> SunMarks:
    """Return the sun events and offsets of the lines' sun triggers and their follow ups.

    A routine's lines (`nextrun.routine_lines`) carry its sun bounds as sun triggers, so
    a routine and a hand written automation give their marks alike.
    """
    marks: set[tuple[str, timedelta]] = set()
    for line in lines:
        for trigger in line.triggers:
            if not isinstance(trigger, SunTrigger):
                continue
            offset = trigger.offset
            marks.add((trigger.event, offset))
            for follow_up in line.follow_ups:
                offset += follow_up.delay
                marks.add((trigger.event, offset))
    return frozenset(marks)


def stated(
    occurrence: Occurrence | None, marks: SunMarks, sun: nextrun.SunLookup
) -> Occurrence | None:
    """Return an occurrence as the Schedule state names it: a sun instant to the minute.

    A sun bound runs at the second the astral helper gives (7:26:28 AM); the state reads
    "On at 7:26 AM" (L69's third carry over). Only the words change: scheduling, skip
    targets, `next_action` and `next_run` keep the exact instant, and a time written by
    hand with seconds keeps them. An instant is a sun one when it is a marked event of
    its day (or a day either side) plus the offset, on the local wall clock, as
    `nextrun` places it.
    """
    if occurrence is None or not marks or not (occurrence.at.second or occurrence.at.microsecond):
        return occurrence
    at = occurrence.at
    for event, offset in marks:
        day = (at - offset).date()
        for nearby in (day - timedelta(days=1), day, day + timedelta(days=1)):
            moment = sun(nearby, event)
            if moment is not None and moment.astimezone(at.tzinfo) + offset == at:
                return replace(occurrence, at=at.replace(second=0, microsecond=0))
    return occurrence


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
    `next_action` (plan A4.0, L43) is the manager's own next action that really runs,
    after any pause: the summary falls back to it when the inputs alone cannot tell,
    which is the case while Skip next skips weekly schedule blocks (the schedule entity
    names only its next change, L53). `settings` (Build B lane 22, L69) are the routine's
    settings as the manager holds them: they move with a change at once, while the owned
    automation's inputs follow after the debounced write and the index rebuild, so the
    routine's rows, its conflicts and the Today view read them in preference to the
    inputs.
    """

    items: tuple[SummaryItem, ...]
    paused_until: datetime | None
    skipped_action: Occurrence | None
    status: Status
    next_action: Occurrence | None = None
    settings: RoutineSettings | None = None


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


@dataclass(frozen=True, slots=True)
class ConversionOffer:
    """A hand written automation a routine on its device can replace exactly (FR-M1).

    `settings` are the routine's as `conversion.match` read them, before the manager adds
    the global defaults; `original_sentence` is what the Schedule reads for the automation
    on the device and `routine_sentence` what it would read for the routine, so the
    Repairs issue and the console show both side by side.
    """

    automation_id: str
    automation_entity_id: str
    alias: str
    device_id: str
    device_name: str
    settings: RoutineSettings
    original_sentence: str
    routine_sentence: str


@dataclass(frozen=True, slots=True)
class _Match:
    """An exact match the index found: the automation, its device and the routine's settings.

    `digest` is the hash of the config it was read from, so an offer of an automation
    edited since the last rebuild is never taken (`offer_for`).
    """

    automation_entity: str
    automation_id: str
    digest: str
    device_id: str
    device_name: str
    settings: RoutineSettings
    lines: tuple[ParsedLine, ...]


@dataclass(slots=True)
class _Index:
    lines: dict[str, list[IndexedLine]] = field(default_factory=dict)
    time_entities: frozenset[str] = frozenset()
    routines: dict[str, _OwnedRoutine] = field(default_factory=dict)
    # The timer and weekly schedule helpers of the routines, whose states move the views.
    runtime_entities: frozenset[str] = frozenset()
    # The exact conversion matches, while `offer_conversions` is on (FR-M1).
    matches: tuple[_Match, ...] = ()


@dataclass(frozen=True, slots=True)
class _Row:
    """One item with the occurrences the state, the timer and the conflicts read.

    `sun` holds the sun events and offsets the item runs at, so the state names such an
    instant to the whole minute (`stated`).
    """

    item: SummaryItem
    occurrences: Sequence[Occurrence]
    entity_ids: tuple[str, ...]
    routine: RoutineSettings | None = None
    sun: SunMarks = frozenset()


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
        # The optional AI summary of the lines the parser cannot read (Build A lane 14).
        self.ai = AiSummaries(hass, settings, phrases, self._refresh_views)
        # The conversion offers of the last view refresh, by automation entity (FR-M1).
        self._offers: dict[str, ConversionOffer] = {}

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
            # A handle that stays safe to call after it fired (plan A4.0 item 24).
            self._unsubscribe.append(async_at_started(self.hass, self._rebuild_at_start))
        self._started = True
        self.ai.async_start()
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
        self.ai.async_stop()

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
        writer = self._writer()
        async_sync_conflict_issues(
            self.hass, summaries, writer, enabled=self.settings.raise_conflict_repairs
        )
        # A routine created or gone on the device takes its offers away or brings them back.
        self._sync_offers(writer)
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
    def _rebuild_at_start(self, _hass: HomeAssistant) -> None:
        self._rebuild_soon()

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
        self.ai.async_update(self._index.lines)
        self._refresh_views()

    def _build_index(self) -> _Index:
        entities = er.async_get(self.hass)
        registry_ids = {entry.id: entry.entity_id for entry in entities.entities.values()}
        contexts: dict[str, DeviceContext] = {}
        lines: dict[str, list[IndexedLine]] = {}
        routines: dict[str, _OwnedRoutine] = {}
        matches: list[_Match] = []
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
                if owned is not None:
                    # Read through its inputs, as the manager reads it (PRD 12, plan A4.0
                    # item 20): the parser cannot read the rendered blueprint.
                    parsed = _routine_lines(owned, refs.config, context)
                else:
                    try:
                        parsed = parser.summarize(refs.config, context)
                    except ParseError:
                        _LOGGER.debug("%s is not an automation config", refs.entity_id)
                        break
                    if kind == KIND_AUTOMATION and self.settings.offer_conversions:
                        matches.extend(self._matches(refs, context, parsed))
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
            matches=tuple(matches),
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
    def set_ai_store(self, store: RoutineStore) -> None:
        """Take the Store whose `ai_cache` holds the AI lines; without it no AI is asked."""
        self.ai.store = store

    @callback
    def async_add_change_listener(self, update: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Call `update` whenever any device's summary changes; return the unsubscriber.

        The hub Routines sensor follows the routines' next actions this way, so it moves
        on at each action without a timer of its own; the manager turns it into one
        debounced `schedule_changed` for its listeners, so an edit of a hand written
        automation reaches the console as a routine change does (L49).
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
        self._sync_offers(writer)
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
        # Take control saved the rendered config under the same id, so the core kept the
        # loaded entity with its blueprint block until the next start; the manager read
        # the file and says detached, and its word wins (PRD 8.2, plan A4.0 item 22).
        detached = routine is not None and routine.status is Status.DETACHED
        for entry in indexed:
            own = entry.kind == KIND_ROUTINE and entry.line.automation_id == own_id
            if provided and own:
                continue
            if detached and own:
                entry = replace(entry, kind=KIND_DETACHED)  # noqa: PLW2901  # read as detached
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
        enabled = [item for item in items if item.enabled]
        fallback = (
            enabled[0].summary
            if enabled
            # Every automation on the device is off: nothing its lines say is planned.
            else writer.automations_off(len({item.automation_entity for item in items}))
        )
        planned = [
            conflicts.Planned(index, row.entity_ids, tuple(row.occurrences), row.routine)
            for index, row in enumerate(rows)
        ]
        changes = [m for m in (upcoming.at if upcoming else None, pause_end) if m is not None]
        marks: SunMarks = frozenset().union(*(row.sun for row in rows))
        return DeviceSummary(
            device_id=device.id,
            device_name=device.name_by_user or device.name,
            identifiers=frozenset(device.identifiers),
            connections=(
                frozenset(device.connections) if isinstance(device, dr.DeviceEntry) else frozenset()
            ),
            state=_state(
                writer,
                routine,
                pause_end=pause_end,
                routine_next=stated(routine_next, marks, self._sun),
                upcoming=stated(upcoming, marks, self._sun),
                fallback=fallback,
                now=now,
            ),
            items=items,
            conflicts=tuple(conflicts.find(planned, now, now + CONFLICT_WINDOW, lookups)),
            next_change=min(changes, default=None),
            paused_until=pause_end,
            skipped_action=_skipped_line(
                writer, stated(_skipped(routine, pause_end), marks, self._sun), now
            ),
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
        item = self.ai.item(entry, item)
        return _Row(item, occurrences, entry.line.entity_ids, sun=sun_marks((entry.line,)))

    def _routine_rows(
        self, device_id: str, routine: RoutineSummary, pause_end: datetime | None, now: datetime
    ) -> list[_Row]:
        """Return the provider's items as rows.

        The first item stands for the owned automation: while it runs, its next actions
        are computed from the manager's settings (its inputs, for a provider without
        them) after Paused until; while it does not, it has none. Every other item, and
        every item before the owned automation is indexed, counts its own next run with
        its action unknown.
        """
        owned = self._index.routines.get(device_id)
        settings = routine.settings or (owned.settings if owned else None)
        marks = sun_marks(nextrun.routine_lines(settings, "", "")) if settings else frozenset()
        rows = [
            _Row(item, [Occurrence(item.next_run, None)] if item.next_run else [], (), sun=marks)
            for item in routine.items
        ]
        if owned is None or settings is None:
            return rows
        first = rows[0].item
        if routine.status in _RUNNING_STATUSES and _is_on(
            self.hass.states.get(owned.automation_entity)
        ):
            occurrences = self._routine_occurrences(owned, settings, pause_end, now)
            if not occurrences and routine.next_action is not None:
                # The inputs cannot see past a skipped weekly block; the manager can.
                occurrences = [routine.next_action]
            rows[0] = _Row(first, occurrences, (settings.target_entity,), settings, marks)
        else:
            rows[0] = _Row(first, [], ())
        return rows

    def _routine_occurrences(
        self,
        owned: _OwnedRoutine,
        settings: RoutineSettings,
        pause_end: datetime | None,
        now: datetime,
    ) -> list[Occurrence]:
        """Return the routine's coming actions from its settings and its helpers' states."""
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
        """Wake at the earliest next change, or at local midnight if that comes first.

        One point in time listener. At midnight a sentence written the day before is
        reworded ("Off Tue 9:00 AM" becomes "Off at 9:00 AM" on Tuesday, FR-S4; plan
        A4.0 item 23).
        """
        self._cancel_timer()
        upcoming = [s.next_change for s in self.summaries.values() if s.next_change is not None]
        if not upcoming:
            return
        midnight = dt_util.start_of_local_day(now.date() + timedelta(days=1))
        when = max(min(*upcoming, midnight), now) + timedelta(seconds=1)
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
    # Conversion offers (Build B lane 20: PRD FR-M1, decisions L61 and L65)
    # ----------------------------------------------------------------------------------

    def conversion_offers(self) -> tuple[ConversionOffer, ...]:
        """Return the automations a routine can replace exactly, by device and alias."""
        return tuple(
            sorted(
                self._offers.values(),
                key=lambda offer: (offer.device_name, offer.alias, offer.automation_entity_id),
            )
        )

    def offer_for(self, automation_entity_id: str) -> ConversionOffer | None:
        """Return the offer of an automation while it still stands, or None.

        Read again now: the automation is still on, its device still has no routine, and
        its config is still the one the match was read from, so an edit inside the index
        rebuild's debounce is never converted from what the automation used to do.
        """
        match = next(
            (
                found
                for found in self._index.matches
                if found.automation_entity == automation_entity_id
            ),
            None,
        )
        config = ha_adapter.automation_config(self.hass, automation_entity_id)
        if match is None or config is None or markers.config_hash(config) != match.digest:
            return None
        return self._offer(match, self._writer())

    def _matches(
        self, refs: ha_adapter.AutomationRefs, context: DeviceContext, lines: list[ParsedLine]
    ) -> list[_Match]:
        """Return the automation's exact match on the device as a list of none or one.

        A match counts when the routine could run it: its settings validate for the
        profile of the entity it drives (the PRD 5.4 refusals included), the entity is one
        a routine can drive, and the automation has a registry entry for the label.
        """
        settings = conversion.match(refs.config, context)
        if (
            settings is None
            or not lines
            or not _drivable(self.hass, context.device_id, settings.target_entity)
        ):
            return []
        profile = _profile(self.hass, settings.target_entity)
        registered = er.async_get(self.hass).async_get(refs.entity_id) is not None
        if profile is None or compiler.validate(settings, profile) or not registered:
            return []
        device = dr.async_get(self.hass).async_get(context.device_id)
        assert device is not None  # noqa: S101  # _reachable_devices checked it
        return [
            _Match(
                automation_entity=refs.entity_id,
                automation_id=str(refs.config.get("id", "")),
                digest=markers.config_hash(refs.config),
                device_id=context.device_id,
                device_name=device.name_by_user or device.name or context.device_id,
                settings=settings,
                lines=tuple(lines),
            )
        ]

    def _offer(self, match: _Match, writer: Writer) -> ConversionOffer | None:
        """Return a match as an offer while the automation is on and the device has no routine."""
        if not _is_on(self.hass.states.get(match.automation_entity)) or self._has_routine(
            match.device_id
        ):
            return None
        separator = writer.say("list_separator")
        alias = match.lines[0].alias
        routine = nextrun.routine_lines(match.settings, match.automation_id, alias)
        return ConversionOffer(
            automation_id=match.automation_id,
            automation_entity_id=match.automation_entity,
            alias=alias,
            device_id=match.device_id,
            device_name=match.device_name,
            settings=match.settings,
            original_sentence=separator.join(writer.line(line) for line in match.lines),
            routine_sentence=separator.join(writer.line(line) for line in routine),
        )

    def _has_routine(self, device_id: str) -> bool:
        """Tell whether a device has a routine: an owned automation, or one the manager knows."""
        provided = self._provider.routine_summary(device_id) if self._provider else None
        return device_id in self._index.routines or provided is not None

    def _sync_offers(self, writer: Writer) -> None:
        """Turn the matches into offers and keep the `conversion_offer` issues in line.

        One issue per offered automation, its subject the automation entity's object id;
        every other `conversion_offer` issue is cleared, all of them while
        `offer_conversions` is off (the index then holds no match). A change of the offers
        tells the change listeners.
        """
        offers: dict[str, ConversionOffer] = {}
        for match in self._index.matches:
            offer = None if match.automation_entity in offers else self._offer(match, writer)
            if offer is not None:
                offers[match.automation_entity] = offer
        repairs.async_sync_issues(
            self.hass,
            repairs.CONVERSION_OFFER,
            {
                entity_id.partition(".")[2]: {
                    "alias": offer.alias,
                    "device": offer.device_name,
                    "original": offer.original_sentence,
                    "routine": offer.routine_sentence,
                }
                for entity_id, offer in offers.items()
            },
        )
        changed = offers != self._offers
        self._offers = offers
        for update in list(self._change_listeners) if changed else ():
            update()

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
        conflict in its own minute, with the device's name, the alias of the automation or
        routine and the number of conditions that gate it (FR-R9's Today flag, plan 6.2.5).
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
            found.extend(_day_items(device, rows, start, end, lookups))
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
                    alias=entry.line.alias,
                    conditions=entry.line.condition_count,
                )
            )
        return rows

    def _day_routine_rows(
        self, device_id: str, routine: RoutineSummary, start: datetime, now: datetime
    ) -> list[_DayRow]:
        """Return the provider's items as rows, the way `_routine_rows` reads them.

        The first item stands for the owned automation: while it runs, its actions come
        from the manager's settings (its inputs, for a provider without them), less those
        its pause skips; while it does not, it has none. Every other item, and every item
        before the owned automation is indexed, counts its next run with its action
        unknown.
        """
        owned = self._index.routines.get(device_id)
        pause_end = _pause_end(routine, now)
        rows: list[_DayRow] = []
        for index, item in enumerate(routine.items):
            if index or owned is None:
                runs: tuple[Occurrence, ...] = (
                    (Occurrence(item.next_run, None),) if item.next_run else ()
                )
                rows.append(_DayRow(item.kind, item.automation_entity, (), runs, alias=item.alias))
            elif routine.status in _RUNNING_STATUSES and _is_on(
                self.hass.states.get(owned.automation_entity)
            ):
                settings = routine.settings or owned.settings
                planned = self._routine_occurrences(owned, settings, None, start - _INSTANT)
                runs = tuple(
                    run
                    for run in planned
                    if pause_end is None or not now < run.at < pause_end  # skipped by the pause
                )
                rows.append(
                    _DayRow(
                        item.kind,
                        item.automation_entity,
                        (settings.target_entity,),
                        runs,
                        settings,
                        alias=item.alias,
                    )
                )
            else:
                rows.append(_DayRow(item.kind, item.automation_entity, (), (), alias=item.alias))
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


# --------------------------------------------------------------------------------------
# The AI path (Build A lane 14: PRD FR-S5, TECH_SPEC 4.4)
# --------------------------------------------------------------------------------------


class TokenBucket:
    """At most `capacity` calls in any `period`: each spent token returns a period later."""

    def __init__(self, capacity: int, period: timedelta = AI_PERIOD) -> None:
        """Start full."""
        self.capacity = capacity
        self.period = period
        self._spent: deque[datetime] = deque()

    def next_free(self, now: datetime) -> datetime:
        """Return when the next token is free: `now` when one is free now."""
        while self._spent and self._spent[0] + self.period <= now:
            self._spent.popleft()
        if len(self._spent) < self.capacity:
            return now
        return self._spent[0] + self.period

    def take(self, now: datetime) -> None:
        """Spend a token now; call it only when `next_free(now)` is `now`."""
        self._spent.append(now)


@dataclass(frozen=True, slots=True)
class _AiRequest:
    """One automation waiting for an AI line: its entity and the blocks to send."""

    automation_entity: str
    blocks: Mapping[str, Any]


def _unread(line: ParsedLine) -> bool:
    """Tell whether the parser could not fully read a line (FR-S5 sends those)."""
    return line.custom_logic or not line.understood


class AiSummaries:
    """The optional AI line for automations the parser cannot fully read (PRD FR-S5).

    Off unless `ai_task_entity` names an AI Task entity (and the Store is there for the
    cache). After every index rebuild the hand written automations with a line the
    parser could not fully read are queued, keyed by their config hash; one at a time
    their trigger, condition and action blocks (`ai_prompt.blocks`: entity ids only) go
    to that entity through the core's `ai_task.generate_data` action, never in the first
    five minutes after Home Assistant started and at most `ai_calls_per_hour` times in
    any hour (`TokenBucket`). The answer, cut to twelve words, is cached in the Store by
    config hash, so it is asked again only when the automation changes, and the item
    shows it with the `(AI)` suffix and `source: ai`. A failed call is not repeated for
    that config while the entry runs. The cache is pruned to the hashes still present.
    No interval: one point in time listener waits for the next allowed call.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        settings: GlobalSettings,
        phrases: Phrases,
        on_answer: Callable[[], None],
    ) -> None:
        """Hold the settings; `on_answer` recomputes the views after a new line."""
        self.hass = hass
        self.store: RoutineStore | None = None
        self._entity = settings.ai_task_entity
        self._phrases = phrases
        self._on_answer = on_answer
        self._bucket = TokenBucket(settings.ai_calls_per_hour)
        self._digests: dict[str, str] = {}
        self._queue: dict[str, _AiRequest] = {}
        self._failed: set[str] = set()
        self._asking: str | None = None
        self._ready_at: datetime | None = None
        self._task: asyncio.Task[None] | None = None
        self._timer: CALLBACK_TYPE | None = None
        self._unsub_started: CALLBACK_TYPE | None = None

    @property
    def enabled(self) -> bool:
        """True when an AI Task entity is chosen and the cache can be kept."""
        return self._entity is not None and self.store is not None

    @callback
    def async_start(self) -> None:
        """Count the five minutes from now, or from Home Assistant's start if it is booting."""
        if not self.enabled:
            return
        if self.hass.is_running:
            self._begin()
            return
        self._unsub_started = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, self._started
        )

    @callback
    def _started(self, _event: Event[Any]) -> None:
        self._unsub_started = None
        self._begin()

    @callback
    def _begin(self) -> None:
        self._ready_at = dt_util.utcnow() + AI_STARTUP_DELAY
        self._pump()

    @callback
    def async_stop(self) -> None:
        """Drop the queue, the timer and the call in flight."""
        if self._unsub_started is not None:
            self._unsub_started()
            self._unsub_started = None
        self._cancel_timer()
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._asking = None
        self._queue.clear()
        self._ready_at = None

    @callback
    def async_update(self, lines: Mapping[str, Sequence[IndexedLine]]) -> None:
        """Queue every unread hand written automation whose config has no line yet."""
        store = self.store
        if self._entity is None or store is None:
            return
        unread = sorted(
            {
                entry.automation_entity
                for group in lines.values()
                for entry in group
                if entry.kind == KIND_AUTOMATION and _unread(entry.line)
            }
        )
        registry_ids = {
            entry.id: entry.entity_id for entry in er.async_get(self.hass).entities.values()
        }
        digests: dict[str, str] = {}
        queue: dict[str, _AiRequest] = {}
        for entity_id in unread:
            config = ha_adapter.automation_config(self.hass, entity_id)
            if config is None:
                continue
            digest = digests[entity_id] = markers.config_hash(config)
            if digest in store.data.ai_cache or digest in self._failed or digest == self._asking:
                continue
            queue[digest] = self._queue.get(digest) or _AiRequest(
                entity_id, ai_prompt.blocks(config, registry_ids)
            )
        self._digests = digests
        self._queue = queue
        self._prune(store, set(digests.values()))
        self._pump()

    def _prune(self, store: RoutineStore, known: set[str]) -> None:
        """Drop cached lines of configs that are gone, once the start has settled."""
        if self._ready_at is None or dt_util.utcnow() < self._ready_at:
            return
        stale = [digest for digest in store.data.ai_cache if digest not in known]
        for digest in stale:
            del store.data.ai_cache[digest]
        if stale:
            store.async_delay_save()

    def item(self, entry: IndexedLine, item: SummaryItem) -> SummaryItem:
        """Return the item with the AI line when the parser could not read it and one exists."""
        store = self.store
        if (
            self._entity is None
            or store is None
            or entry.kind != KIND_AUTOMATION
            or not _unread(entry.line)
        ):
            return item
        cached = store.data.ai_cache.get(self._digests.get(entry.automation_entity, ""))
        if cached is None:
            return item
        text = self._phrases["ai_line"].format(text=cached.text)
        return replace(item, summary=text, source=SOURCE_AI)

    @callback
    def _pump(self) -> None:
        """Send the next queued automation when a call is allowed, else wait for that."""
        self._cancel_timer()
        if self._asking is not None or not self._queue or self._ready_at is None:
            return
        now = dt_util.utcnow()
        due = max(self._ready_at, self._bucket.next_free(now))
        if due > now:
            self._timer = async_track_point_in_utc_time(self.hass, self._timer_fired, due)
            return
        digest = next(iter(self._queue))
        request = self._queue.pop(digest)
        self._bucket.take(now)
        self._asking = digest
        # Not started eagerly: the call finishes after this task is known, never inside.
        self._task = self.hass.async_create_task(
            self._async_ask(digest, request), "device_routines AI summary", eager_start=False
        )

    @callback
    def _timer_fired(self, _now: datetime) -> None:
        self._timer = None
        self._pump()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer()
            self._timer = None

    async def _async_ask(self, digest: str, request: _AiRequest) -> None:
        """Ask the AI Task entity about one automation and cache the line it answers."""
        text: str | None = None
        try:
            response = await self.hass.services.async_call(
                AI_TASK_DOMAIN,
                AI_TASK_SERVICE,
                {
                    "task_name": ai_prompt.TASK_NAME,
                    "entity_id": self._entity,
                    "instructions": ai_prompt.instructions(request.blocks),
                },
                blocking=True,
                return_response=True,
            )
            text = ai_prompt.trim((response or {}).get("data"))
        except (HomeAssistantError, vol.Invalid) as err:
            _LOGGER.warning("The AI summary of %s failed: %s", request.automation_entity, err)
        self._task = None
        self._asking = None
        store = self.store
        if text is None or store is None:
            _LOGGER.debug("No AI line for %s", request.automation_entity)
            self._failed.add(digest)
        else:
            store.data.ai_cache[digest] = AiCacheEntry(text, dt_util.utcnow())
            store.async_delay_save()
            self._on_answer()
        self._pump()


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


def _device_class(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return an entity's device class from its registry entry, else from its state."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is not None and (entry.device_class or entry.original_device_class):
        return entry.device_class or entry.original_device_class
    state = hass.states.get(entity_id)
    device_class = state.attributes.get("device_class") if state else None
    return device_class if isinstance(device_class, str) else None


def _profile(hass: HomeAssistant, entity_id: str) -> DomainProfile | None:
    """Return the profile of the entity a routine would drive, as the manager reads it."""
    return profile_for(entity_id.partition(".")[0], _device_class(hass, entity_id))


def _drivable(hass: HomeAssistant, device_id: str, entity_id: str) -> bool:
    """Tell whether a routine of the device could drive the entity (`domains.pick_targets`)."""
    entry = er.async_get(hass).async_get(entity_id)
    return (
        entry is not None
        and entry.device_id == device_id
        and bool(pick_targets([Candidate(entry.entity_id, entry.entity_category, entry.disabled)]))
    )


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


def _routine_lines(
    owned: _OwnedRoutine, config: Mapping[str, Any], context: DeviceContext
) -> list[ParsedLine]:
    """Return an owned routine's lines from its settings, on the device it drives only.

    A routine with nothing set yet has one line that reads as its kind ("Routine"), as
    the manager's item does.
    """
    target = owned.settings.target_entity
    if all(ref.entity_id != target for ref in context.entities):
        return []
    alias = str(config.get("alias") or "")
    lines = nextrun.routine_lines(owned.settings, owned.automation_id, alias)
    return lines or [ParsedLine(owned.automation_id, alias, (target,), None, understood=False)]


def _pause_end(routine: RoutineSummary | None, now: datetime) -> datetime | None:
    """Return Paused until while the routine is paused or skipping and it is ahead."""
    if (
        routine is None
        or routine.status not in PAUSING_STATUSES
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


def _skipped(routine: RoutineSummary | None, pause_end: datetime | None) -> Occurrence | None:
    """Return the action Skip next skipped while the routine skips, else None."""
    if pause_end is None or routine is None or routine.status is not Status.SKIPPING:
        return None
    return routine.skipped_action


def _skipped_line(writer: Writer, action: Occurrence | None, now: datetime) -> str | None:
    """Return the skipped action as a line ("5:00 PM: on") while the routine skips."""
    if action is None or action.verb is None:
        return None
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
    `kind` and `automation` are those of the Schedule item it belongs to. `device_name` is
    the device's name, `alias` the automation's or the routine's, and `conditions` the
    number of conditions that gate the action (FR-R9's Today flag): a routine's Only when
    conditions on its on actions, which the blueprint gates (L64), a parsed line's
    `condition_count`.
    """

    time: datetime
    device_id: str
    area_id: str | None
    action: Verb | None
    kind: str
    automation: str
    conflict: bool = False
    device_name: str | None = None
    alias: str | None = None
    conditions: int = 0


@dataclass(frozen=True, slots=True)
class _DayRow:
    """One Schedule item of a device with its runs; `routine` is set while a routine runs.

    `conditions` gate every run of a parsed line; a running routine's come from its
    settings, on its on actions only (`_gating`).
    """

    kind: str
    automation: str
    entity_ids: tuple[str, ...]
    runs: tuple[Occurrence, ...]
    routine: RoutineSettings | None = None
    alias: str | None = None
    conditions: int = 0


def _day_items(
    device: dr.AnyDeviceEntry,
    rows: Sequence[_DayRow],
    start: datetime,
    end: datetime,
    lookups: nextrun.Lookups,
) -> list[DayItem]:
    """Return a device's runs inside the day as items, each once, with its conflict flag.

    `conflicts.find` reports one conflict per pair and reason in a window, so it is asked
    minute by minute: every run in a conflicting minute of a conflicting row is marked. A
    sun window is placed with the day's lookups, as the occurrences were.
    """
    inside = [tuple(run for run in row.runs if start <= run.at < end) for row in rows]
    planned = [
        conflicts.Planned(index, row.entity_ids, runs, row.routine)
        for index, (row, runs) in enumerate(zip(rows, inside, strict=True))
    ]
    marked: set[tuple[int, datetime]] = set()
    for minute in sorted({_minute_of(run.at) for runs in inside for run in runs}):
        for found in conflicts.find(planned, minute, minute + timedelta(minutes=1), lookups):
            marked.update(((found.a, minute), (found.b, minute)))
    items: dict[tuple[Any, ...], DayItem] = {}
    for index, (row, runs) in enumerate(zip(rows, inside, strict=True)):
        for run in runs:
            key = (run.at, run.verb, row.kind, row.automation)
            earlier = items.get(key)
            conflict = (index, _minute_of(run.at)) in marked or bool(earlier and earlier.conflict)
            gating = max(_gating(row, run), earlier.conditions if earlier else 0)
            items[key] = DayItem(
                run.at,
                device.id,
                device.area_id,
                run.verb,
                row.kind,
                row.automation,
                conflict,
                device_name=device.name_by_user or device.name,
                alias=row.alias,
                conditions=gating,
            )
    return list(items.values())


def _gating(row: _DayRow, run: Occurrence) -> int:
    """Return the number of conditions gating one run of a row.

    A running routine's Only when conditions gate its on actions only, as the blueprint
    gates them (L64); every other row counts its line's conditions on every run.
    """
    if row.routine is None:
        return row.conditions
    on_verb = nextrun.routine_verbs(row.routine.target_entity)[0]
    return len(row.routine.extra_conditions) if run.verb is on_verb else 0


def _minute_of(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)
