"""RoutineManager: the service layer that turns device settings into managed automations.

One manager per config entry (`entry.runtime_data.manager`, TECH_SPEC 4.1). Every device
page entity, action, WebSocket command, trigger and Repairs fix flow calls it and nothing
else (PRD P16). It owns:

- Opting devices in and out: the `Routines` label on the device is the visible truth,
  `async_opt_in` and `async_opt_out` apply or remove it, and a label a person adds or
  removes reaches the same methods through the device registry.
- The write path (PRD 7.2): a patch is validated against the merged settings at once and
  shown at once; the write is debounced one second per device, compiled, written through
  the adapter with the file hash guard, reloaded (the adapter reloads the one id) and its
  hash recorded, so sync back can tell its own writes from foreign ones.
- Sync back (PRD 7.3, 8.2): on every `automation_reloaded` the file is read once and every
  entry carrying M1 is judged on the file entry (decision L43): a hash the manager wrote
  is skipped, a foreign valid edit becomes the settings, an invalid one turns the routine
  off and raises `invalid_inputs`, an entry without M2 is detached, a missing one resets
  the routine.
- The runtime state of each routine (Paused until, the skipped action, the Manual
  override and the source of the last change): the manager is its source of truth, the
  device page entities render it and call back (decision 1 of the lane brief), and the
  blueprint reads the entities.
- Skip, pause, resume, enable and disable (PRD 5.5, D18 to D21, decision L40), the pause
  end at its stored time (L22) and the bus events `device_routines_paused` and
  `device_routines_resumed`.
- Reconcile and self healing (TECH_SPEC 7, PRD 3.1), the registry reactions, the D28
  cleanup with one point in time listener, and the timers that ran out during a restart
  (L20).

Results. Every public method returns a result dataclass; the only exception raised to a
caller is `ServiceValidationError` with a translation key. A patch problem is returned as
`UpdateResult.problem`, never raised.
"""

from __future__ import annotations

import asyncio
import builtins
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta
import logging
from typing import Any, Final, Literal

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_STATE_CHANGED,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    label_registry as lr,
)
from homeassistant.helpers.event import async_call_later, async_track_point_in_utc_time
from homeassistant.helpers.typing import UNDEFINED
from homeassistant.util import dt as dt_util

from . import compiler, ha_adapter, maintenance, markers, migration, nextrun, repairs
from .attribution import Attributor, OverrideSink, RoutineLookup, RoutineRuntime
from .const import (
    CONF_SYSTEM_USER_ID,
    DOMAIN,
    EVENT_PAUSED,
    EVENT_RESUMED,
    KEY_MANUAL_OVERRIDE,
    KEY_PAUSED_UNTIL,
)
from .domains import PROFILES, Candidate, pick_targets, profile_for
from .models import (
    ALL_DAYS,
    CompileError,
    Days,
    DomainProfile,
    FollowUp,
    NamedTrigger,
    Occurrence,
    ParsedLine,
    Problem,
    Pulse,
    RoutineSettings,
    RoutineView,
    Source,
    StateTrigger,
    Status,
    SummaryItem,
    TimeTrigger,
    Verb,
    Weekday,
)
from .parser_grammar import ACTION_VERBS
from .sentence import Writer
from .settings import GlobalSettings, from_options
from .store import OwnedRecord, RoutineStore
from .summary import KIND_ROUTINE, SOURCE_PARSER, RoutineSummary, SummaryCoordinator

_LOGGER = logging.getLogger(__name__)

# Settings changes inside this many seconds of each other are one write (PRD 7.2).
DEBOUNCE_SECONDS: Final = 1.0

# Who asked for a change; logged and carried in listener events.
SOURCE_API: Final = "api"
SOURCE_ENTITY: Final = "entity"
SOURCE_LABEL: Final = "label"
SOURCE_FLOW: Final = "flow"

# Why a routine changed, as `ManagerEvent.reason`.
REASON_OPTED_IN: Final = "opted_in"
REASON_OPTED_OUT: Final = "opted_out"
REASON_ACTION_SKIPPED: Final = compiler.EVENT_ACTION_SKIPPED

# Statuses under which the blueprint runs scheduled actions (or skips them while paused).
_RUNNING: Final = frozenset({Status.ACTIVE, Status.PAUSED, Status.SKIPPING})

# Every device page entity key (TECH_SPEC 4.5), longest first, so a unique id
# `device_routines_<device id>_<key>` names its device unambiguously.
ENTITY_KEYS: Final[tuple[str, ...]] = tuple(
    sorted(
        (
            "schedule",
            "routine",
            "on_time",
            "off_time",
            "days",
            "turn_off_after",
            "turn_back_on_after",
            "catch_up",
            "respect_manual",
            "skip_next",
            "resume",
            KEY_PAUSED_UNTIL,
            KEY_MANUAL_OVERRIDE,
            "target",
        ),
        key=len,
        reverse=True,
    )
)
_SCHEDULE_KEY: Final = "schedule"
_UNIQUE_PREFIX: Final = f"{DOMAIN}_"

# Why the manager turned an automation off, so it turns it back on when that ends.
_OFF_INVALID: Final = "invalid"
_OFF_MISSING_TARGET: Final = "missing_target"

# The per routine Repairs issues, keyed by the automation id (decision L41).
_ROUTINE_ISSUES: Final = (
    repairs.INVALID_INPUTS,
    repairs.DETACHED_ROUTINE,
    repairs.SCHEDULE_BLOCKS_NEEDED,
    repairs.WRITE_CONFLICT,
    repairs.AUTOMATION_LOAD_FAILED,
)

type ManagerEventKind = Literal[
    "routine_changed", "schedule_changed", "settings_changed", "health_changed"
]
type Patch = Mapping[str, Any]
type ActionName = Literal["skip_next", "pause", "resume", "enable", "disable"]


# --------------------------------------------------------------------------------------
# Results (lane brief decision 2)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ManagerEvent:
    """What a listener hears: a routine, the schedule, the settings or Health changed.

    `reason` says why when the manager knows (`opted_in`, `opted_out`, or the
    `device_routines_action_skipped` event the blueprint fired, re emitted with its data).
    """

    kind: ManagerEventKind
    device_id: str | None
    reason: str | None = None
    data: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """The routine after a patch, or the first problem that kept the patch out."""

    view: RoutineView | None
    problem: Problem | None = None


@dataclass(frozen=True, slots=True)
class ActionResult:
    """One device's answer to skip, pause, resume, enable or disable (TECH_SPEC 4.6)."""

    device_id: str
    device_name: str
    action: str
    paused_until: datetime | None
    skipped_action: Occurrence | None
    next_action: Occurrence | None


@dataclass(frozen=True, slots=True)
class IgnoredTarget:
    """A target an action did not apply to, with why (`no_routine`, `detached`, ...)."""

    target: str
    kind: Literal["device", "entity", "area", "label", "floor"]
    reason: str


@dataclass(frozen=True, slots=True)
class TargetResolution:
    """The routine devices a native target names, and everything it names that is not."""

    device_ids: tuple[str, ...]
    ignored: tuple[IgnoredTarget, ...]


@dataclass(frozen=True, slots=True)
class ActionResults:
    """What an action over a target did: one result per device, and the ignored list."""

    results: tuple[ActionResult, ...]
    ignored: tuple[IgnoredTarget, ...]


@dataclass(frozen=True, slots=True)
class OptResult:
    """A device opted in or out; `changed` is false when it already was."""

    device_id: str
    opted_in: bool
    changed: bool
    view: RoutineView | None


@dataclass(frozen=True, slots=True)
class DeviceChoice:
    """A device the config flow can offer, with the entities a routine could drive."""

    device_id: str
    name: str
    area_id: str | None
    targets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RestoredRuntime:
    """The runtime state a device page entity restores after a restart and hands over.

    `restore_data(device_id)` returns what to keep; `async_restore_runtime` takes it back.
    """

    paused_until: datetime | None = None
    skipped_action: Occurrence | None = None
    override: bool = False
    override_by_skip: bool = False
    last_change_source: Source | None = None


@dataclass(frozen=True, slots=True)
class HealthInputs:
    """What the Health sensor reads from the manager (TECH_SPEC 10.3)."""

    owned_count: int
    loaded_count: int
    issues: tuple[str, ...]
    last_reconcile: datetime | None
    blueprint_status: str | None
    blueprint_schema: int | None
    adapter_failed: tuple[str, ...]


# --------------------------------------------------------------------------------------
# Patches: RoutineSettings field names to values (lane brief decision 2)
# --------------------------------------------------------------------------------------


def _as_time(value: Any) -> time | None:
    if value is None or isinstance(value, time):
        return value
    if isinstance(value, str):
        return time.fromisoformat(value)
    raise TypeError(value)


def _as_minutes(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(value)
    if value != int(value):
        raise ValueError(value)
    return int(value)


def _as_flag(value: Any) -> bool:
    if not isinstance(value, bool):
        raise TypeError(value)
    return value


def _as_entity(value: Any) -> str:
    if not isinstance(value, str) or "." not in value:
        raise TypeError(value)
    return value


def _as_optional_entity(value: Any) -> str | None:
    return None if value is None else _as_entity(value)


def _as_day_set(value: Any) -> frozenset[Weekday]:
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise TypeError(value)
    return frozenset(Weekday(day) for day in value)


def _as_pulse(value: Any) -> Pulse | None:
    if value is None or isinstance(value, Pulse):
        return value
    if not isinstance(value, Mapping):
        raise TypeError(value)
    at = _as_time(value["at"])
    if at is None:
        raise ValueError(value)
    return Pulse(
        at=at,
        minutes=_as_minutes(value.get("minutes", 3)),
        min_steady_min=_as_minutes(value.get("min_steady_min", 5)),
    )


def _as_conditions(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list | tuple) or not all(isinstance(i, Mapping) for i in value):
        raise ValueError(value)
    return tuple(value)


_CONVERTERS: Final[Mapping[str, Callable[[Any], Any]]] = {
    "target_entity": _as_entity,
    "on_time": _as_time,
    "off_time": _as_time,
    "days": Days,
    "day_set": _as_day_set,
    "schedule_entity": _as_optional_entity,
    "turn_off_after_min": _as_minutes,
    "turn_back_on_after_min": _as_minutes,
    "catch_up": _as_flag,
    "late_start_window_min": _as_minutes,
    "respect_manual": _as_flag,
    "pulse": _as_pulse,
    "extra_conditions": _as_conditions,
    "docked_guard": _as_flag,
}


def apply_patch(base: RoutineSettings, patch: Patch) -> tuple[RoutineSettings, Problem | None]:
    """Merge a patch into settings; return the base and a problem for a bad key or value.

    Values may be native (`time`, `Days`, `Pulse`) or the JSON forms a WebSocket client
    sends (`"17:00"`, `"weekdays"`, `{"at": "08:00", "minutes": 3}`). `compiler.validate`
    judges the merged settings afterwards; this only reads the values.
    """
    values: dict[str, Any] = {}
    for key, value in patch.items():
        converter = _CONVERTERS.get(key)
        if converter is None:
            return base, Problem(key, "unknown_setting", {"setting": key})
        try:
            values[key] = converter(value)
        except ValueError, TypeError, KeyError:
            return base, Problem(key, "invalid_value", {"setting": key})
    return replace(base, **values), None


# --------------------------------------------------------------------------------------
# Routine lines for the Schedule summary item
# --------------------------------------------------------------------------------------


def routine_verbs(target_entity: str) -> tuple[Verb, Verb]:
    """Return the verbs of a target's on and off actions, as the sentences name them."""
    profile = PROFILES.get(target_entity.partition(".")[0])
    if profile is None:
        return Verb.ON, Verb.OFF
    on = ACTION_VERBS[profile.on_action.partition(".")[2]] if profile.on_action else Verb.ON
    return on, ACTION_VERBS[profile.off_action.partition(".")[2]]


def routine_lines(settings: RoutineSettings, automation_id: str, alias: str) -> list[ParsedLine]:
    """Return the routine's actions as parsed lines the Writer renders, one per action."""
    target = settings.target_entity
    on, off = routine_verbs(target)
    profile = PROFILES.get(target.partition(".")[0])
    inactive = profile.inactive_state if profile else "off"

    def line(verb: Verb, *triggers: Any, follow_ups: tuple[FollowUp, ...] = ()) -> ParsedLine:
        return ParsedLine(
            automation_id=automation_id,
            alias=alias,
            entity_ids=(target,),
            verb=verb,
            triggers=triggers,
            follow_ups=follow_ups,
        )

    def days(day_set: frozenset[Weekday]) -> frozenset[Weekday] | None:
        return None if day_set == ALL_DAYS else day_set

    lines: list[ParsedLine] = []
    if settings.on_time is not None:
        lines.append(
            line(on, TimeTrigger(at=settings.on_time, weekdays=days(settings.effective_days)))
        )
    if settings.off_time is not None:
        lines.append(line(off, TimeTrigger(at=settings.off_time, weekdays=days(settings.end_days))))
    if settings.days is Days.WEEKLY_SCHEDULE and settings.schedule_entity is not None:
        blocks = (settings.schedule_entity,)
        lines.append(line(on, NamedTrigger("schedule.block_started", blocks)))
        lines.append(line(off, NamedTrigger("schedule.block_ended", blocks)))
    active = "on" if inactive == "off" else None
    if settings.turn_off_after_min:
        period = timedelta(minutes=settings.turn_off_after_min)
        moved = None if active else inactive
        lines.append(line(off, StateTrigger(target, active, moved, period)))
    if settings.turn_back_on_after_min:
        period = timedelta(minutes=settings.turn_back_on_after_min)
        lines.append(line(on, StateTrigger(target, inactive, None, period)))
    if settings.pulse is not None:
        back = (FollowUp(timedelta(minutes=settings.pulse.minutes), Verb.TOGGLE),)
        lines.append(line(Verb.TOGGLE, TimeTrigger(at=settings.pulse.at), follow_ups=back))
    return lines


# --------------------------------------------------------------------------------------
# The manager
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Routine:
    """What the manager holds in memory for one device's routine."""

    device_id: str
    automation_id: str
    settings: RoutineSettings | None = None
    paused_until: datetime | None = None
    skipped_action: Occurrence | None = None
    override: bool = False
    override_by_skip: bool = False
    last_change_source: Source | None = None
    invalid: bool = False
    detached: bool = False
    missing_target: bool = False
    load_failed: bool = False
    regenerated: bool = False
    migration_failed: bool = False
    turned_off_for: str | None = None
    slug: str | None = None
    watched: str | None = None
    write_handle: CALLBACK_TYPE | None = None
    resume_handle: CALLBACK_TYPE | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


type AttributorFactory = Callable[[HomeAssistant, RoutineLookup, OverrideSink], Attributor]


class RoutineManager:
    """The service layer of TECH_SPEC 4.1 (see the module docstring)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: RoutineStore,
        summary: SummaryCoordinator,
        attributor_factory: AttributorFactory,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self._store = store
        self.summary = summary
        self._attributor = attributor_factory(hass, self, self)
        self._routines: dict[str, _Routine] = {}
        self._listeners: builtins.list[Callable[[ManagerEvent], None]] = []
        self._unsubscribe: builtins.list[CALLBACK_TYPE] = []
        self._cleanup_handle: CALLBACK_TYPE | None = None
        self._sync_task: asyncio.Task[None] | None = None
        self._sync_again = False
        self._missed_timers: dict[str, str] = {}
        self._adapter = ha_adapter.AdapterReport()
        self._label_id: str = markers.LABEL_ID
        self._blueprint_status: str | None = None
        self._last_reconcile: datetime | None = None
        self._stopping = False

    # ----------------------------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------------------------

    @property
    def store(self) -> RoutineStore:
        """The loaded Store the index lives in (`maintenance.MaintenanceTarget`)."""
        return self._store

    @property
    def adapter_report(self) -> ha_adapter.AdapterReport:
        """The adapter capabilities as the last reconcile found them."""
        return self._adapter

    @property
    def settings(self) -> GlobalSettings:
        """The global settings of the config entry options."""
        return from_options(self.entry.options)

    async def async_start(self) -> None:
        """Load the routines, listen, and reconcile now or once Home Assistant started."""
        self._load_routines()
        bus = self.hass.bus
        self._unsubscribe = [
            bus.async_listen(ha_adapter.EVENT_AUTOMATION_RELOADED, self._automations_reloaded),
            bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, self._device_registry_updated),
            bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, self._entity_registry_updated),
            bus.async_listen(lr.EVENT_LABEL_REGISTRY_UPDATED, self._label_registry_updated),
            bus.async_listen(compiler.EVENT_ACTION_SKIPPED, self._action_skipped),
            bus.async_listen(
                EVENT_STATE_CHANGED, self._automation_changed, event_filter=self._automation_filter
            ),
        ]
        self.summary.set_routine_provider(self)
        await self._attributor.async_start()
        if self.hass.is_running:
            await self.async_reconcile()
            return
        timers = {
            refs.timer_entity: record.device_id
            for record in self._store.data.owned.values()
            if (refs := _refs(record.last_valid_inputs)) is not None
            and refs.timer_entity != compiler.UNUSED_TIMER
        }
        for timer in ha_adapter.missed_timer_finishes(self.hass, timers):
            self._missed_timers[timer] = timers[timer]
        self._unsubscribe.append(bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._started))

    async def async_stop(self) -> None:
        """Write what is pending, then drop every listener and timer."""
        await self.async_flush()
        self._stopping = True
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        for routine in self._routines.values():
            self._cancel_resume(routine)
        self._cancel_cleanup()
        self._attributor.async_stop()

    async def async_flush(self) -> None:
        """Write every debounced change now."""
        for routine in list(self._routines.values()):
            if routine.write_handle is not None:
                await self._async_write(routine)

    @callback
    def async_add_listener(self, update: Callable[[ManagerEvent], None]) -> CALLBACK_TYPE:
        """Call `update` with every manager event; return the unsubscriber."""
        self._listeners.append(update)

        @callback
        def remove() -> None:
            self._listeners.remove(update)

        return remove

    @callback
    def _notify(self, event: ManagerEvent) -> None:
        for update in list(self._listeners):
            update(event)

    @callback
    def _changed(self, device_id: str, reason: str | None = None) -> None:
        """Tell listeners and the summary that a routine changed."""
        self._notify(ManagerEvent("routine_changed", device_id, reason))
        self.summary.async_refresh_device(device_id)

    async def _started(self, _event: Event[Any]) -> None:
        for timer, device_id in self._missed_timers.items():
            _LOGGER.debug("%s ran out during the restart; catching it up", timer)
            self.hass.bus.async_fire(compiler.EVENT_TIMER_CAUGHT_UP, {"device_id": device_id})
        self._missed_timers.clear()
        await self.async_reconcile()

    def _load_routines(self) -> None:
        """Rebuild the in memory routines from the Store; reconcile refines them."""
        data = self._store.data
        for automation_id, record in data.owned.items():
            routine = self._routine(record.device_id, automation_id)
            routine.settings = _settings(record.last_valid_inputs)
            self._remember_slug(routine, _refs(record.last_valid_inputs))
            self._watch(routine)
        for device_id in data.opted_in:
            self._routine(device_id)

    # ----------------------------------------------------------------------------------
    # Lookups
    # ----------------------------------------------------------------------------------

    def _routine(self, device_id: str, automation_id: str | None = None) -> _Routine:
        """Return the routine of a device, creating its in memory record."""
        routine = self._routines.get(device_id)
        if routine is None:
            routine = self._routines[device_id] = _Routine(
                device_id, automation_id or markers.automation_id(device_id)
            )
        elif automation_id is not None:
            routine.automation_id = automation_id
        return routine

    def _device(self, device_id: str) -> dr.DeviceEntry | None:
        return dr.async_get(self.hass).async_get(device_id, include_child_devices=False)

    def _device_name(self, device_id: str) -> str:
        device = self._device(device_id)
        if device is None:
            return device_id
        return device.name_by_user or device.name or device_id

    def _device_of_automation(self, automation_id: str) -> str | None:
        """Return the device whose routine automation has this id, if any."""
        if (record := self._store.data.owned.get(automation_id)) is not None:
            return record.device_id
        for routine in self._routines.values():
            if routine.automation_id == automation_id:
                return routine.device_id
        return None

    def _automation_entity(self, automation_id: str) -> str | None:
        return er.async_get(self.hass).async_get_entity_id(
            "automation", "automation", automation_id
        )

    def _enabled(self, routine: _Routine) -> bool:
        entity_id = self._automation_entity(routine.automation_id)
        state = self.hass.states.get(entity_id) if entity_id else None
        return state is not None and state.state == STATE_ON

    def _loaded(self, automation_id: str) -> bool:
        entity_id = self._automation_entity(automation_id)
        state = self.hass.states.get(entity_id) if entity_id else None
        return state is not None and state.state != STATE_UNAVAILABLE

    def _exists(self, entity_id: str) -> bool:
        return (
            er.async_get(self.hass).async_get(entity_id) is not None
            or self.hass.states.get(entity_id) is not None
        )

    def _device_class(self, entity_id: str) -> str | None:
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is not None and (entry.device_class or entry.original_device_class):
            return entry.device_class or entry.original_device_class
        state = self.hass.states.get(entity_id)
        device_class = state.attributes.get("device_class") if state else None
        return device_class if isinstance(device_class, str) else None

    def _profile(self, entity_id: str) -> DomainProfile | None:
        return profile_for(entity_id.partition(".")[0], self._device_class(entity_id))

    def candidates(self, device_id: str) -> tuple[str, ...]:
        """Return the entities of a device a routine can drive, in registry order."""
        entries = er.async_entries_for_device(er.async_get(self.hass), device_id)
        return tuple(
            pick_targets(
                Candidate(entry.entity_id, entry.entity_category, entry.disabled)
                for entry in entries
            )
        )

    def profile(self, device_id: str) -> DomainProfile | None:
        """Return the domain profile of the entity a device's routine drives."""
        routine = self._routines.get(device_id)
        target = self._settings_of(routine).target_entity if routine else ""
        return self._profile(target) if target else None

    def _draft(self, device_id: str) -> RoutineSettings:
        """Return the settings a new routine starts from: the first candidate, the defaults."""
        candidates = self.candidates(device_id)
        defaults = self.settings
        return RoutineSettings(
            target_entity=candidates[0] if candidates else "",
            catch_up=defaults.default_catch_up,
            respect_manual=defaults.default_respect_manual,
            late_start_window_min=defaults.default_late_start_window_min,
        )

    def _settings_of(self, routine: _Routine) -> RoutineSettings:
        return routine.settings or self._draft(routine.device_id)

    def _paused(self, routine: _Routine, now: datetime | None = None) -> bool:
        until = routine.paused_until
        return until is not None and until > (now or dt_util.utcnow())

    def _status(self, routine: _Routine) -> Status:
        if routine.detached:
            return Status.DETACHED
        if routine.missing_target:
            return Status.MISSING_TARGET
        if routine.invalid or routine.load_failed:
            return Status.INVALID
        if not self._enabled(routine):
            return Status.OFF
        if self._paused(routine):
            return Status.SKIPPING if routine.skipped_action else Status.PAUSED
        return Status.ACTIVE

    def _schedule_lookup(self, settings: RoutineSettings) -> tuple[str | None, nextrun.Lookups]:
        """Return a weekly schedule's state and its next change, as nextrun reads them."""
        if settings.schedule_entity is None:
            return None, nextrun.Lookups()
        state = self.hass.states.get(settings.schedule_entity)
        if state is None:
            return None, nextrun.Lookups()
        held = _moment(state.attributes.get("next_event"))
        times = {settings.schedule_entity: held} if held is not None else {}
        return state.state, nextrun.Lookups(entity_times=times)

    def _timer_entity(self, routine: _Routine) -> str | None:
        record = self._store.data.owned.get(routine.automation_id)
        refs = _refs(record.last_valid_inputs if record else None)
        if refs is None or refs.timer_entity == compiler.UNUSED_TIMER:
            return None
        return refs.timer_entity

    def _countdown_ends(self, routine: _Routine) -> datetime | None:
        timer = self._timer_entity(routine)
        state = self.hass.states.get(timer) if timer else None
        if state is None or state.state != "active":
            return None
        return _moment(state.attributes.get("finishes_at"))

    def _occurrences(self, routine: _Routine, status: Status) -> builtins.list[Occurrence]:
        """Return the routine's coming actions after any pause, while it runs."""
        if routine.settings is None or status not in _RUNNING:
            return []
        schedule_state, lookups = self._schedule_lookup(routine.settings)
        return nextrun.routine_occurrences(
            routine.settings,
            dt_util.now(),
            schedule_state,
            lookups,
            countdown_ends=self._countdown_ends(routine),
            not_before=routine.paused_until if self._paused(routine) else None,
        )

    # ----------------------------------------------------------------------------------
    # Views
    # ----------------------------------------------------------------------------------

    def get(self, device_id: str) -> RoutineView | None:
        """Return a snapshot of a device's routine, or None for a device without one."""
        routine = self._routines.get(device_id)
        if routine is None:
            return None
        device = self._device(device_id)
        status = self._status(routine)
        upcoming = self._occurrences(routine, status)
        summary = self.summary.summaries.get(device_id)
        return RoutineView(
            device_id=device_id,
            device_name=self._device_name(device_id),
            area_id=device.area_id if device else None,
            automation_id=routine.automation_id,
            automation_entity_id=self._automation_entity(routine.automation_id),
            settings=self._settings_of(routine),
            status=status,
            enabled=self._enabled(routine),
            paused_until=routine.paused_until if self._paused(routine) else None,
            skipped_action=routine.skipped_action if status is Status.SKIPPING else None,
            next_action=upcoming[0] if upcoming else None,
            sentence=summary.state if summary else None,
            items=summary.items if summary else (),
            conflicts=summary.conflicts if summary else (),
            override=routine.override,
            last_change_source=routine.last_change_source,
        )

    def list(self) -> tuple[RoutineView, ...]:
        """Return every routine the manager knows, by device name."""
        views = (self.get(device_id) for device_id in self._routines)
        return tuple(sorted((v for v in views if v), key=lambda v: (v.device_name, v.device_id)))

    def opted_in_devices(self) -> tuple[str, ...]:
        """Return the devices with routine controls, for the platforms to add entities."""
        return tuple(sorted(self._store.data.opted_in))

    def unavailable_reason(self, device_id: str) -> str | None:
        """Return why a device's routine controls are unavailable, or None.

        `adapter_incompatible`, `detached` or `missing_target` (TECH_SPEC 4.5); the
        platforms show the entity unavailable with this `reason` attribute.
        """
        if not self._adapter.works(ha_adapter.CAPABILITY_WRITE):
            return "adapter_incompatible"
        routine = self._routines.get(device_id)
        if routine is not None and routine.detached:
            return "detached"
        if routine is not None and routine.missing_target:
            return "missing_target"
        return None

    def entity_id_for(self, device_id: str, key: str) -> str | None:
        """Return the entity id of one of a device's page entities, if registered."""
        return er.async_get(self.hass).async_get_entity_id(
            _platform_of(key), DOMAIN, f"{_UNIQUE_PREFIX}{device_id}_{key}"
        )

    def eligible_devices(self) -> tuple[DeviceChoice, ...]:
        """Return every device with an entity a routine can drive, by name."""
        found: builtins.list[DeviceChoice] = []
        for device in dr.async_get(self.hass).devices:
            if device.config_entry_id == self.entry.entry_id:
                continue
            if targets := self.candidates(device.id):
                name = device.name_by_user or device.name or device.id
                found.append(DeviceChoice(device.id, name, device.area_id, targets))
        return tuple(sorted(found, key=lambda choice: (choice.name, choice.device_id)))

    def suggested_devices(self) -> tuple[DeviceChoice, ...]:
        """Return eligible devices a time based automation drives, not yet opted in."""
        timed = {
            device_id
            for device_id, summary in self.summary.summaries.items()
            if any(item.kind != KIND_ROUTINE and item.next_run for item in summary.items)
        }
        opted_in = self._store.data.opted_in
        return tuple(
            choice
            for choice in self.eligible_devices()
            if choice.device_id in timed and choice.device_id not in opted_in
        )

    def health_inputs(self) -> HealthInputs:
        """Return what Health reports about routines (Build A lane 15 reads it)."""
        owned = self._store.data.owned
        return HealthInputs(
            owned_count=len(owned),
            loaded_count=sum(self._loaded(automation_id) for automation_id in owned),
            issues=tuple(repairs.open_issue_ids(self.hass)),
            last_reconcile=self._last_reconcile,
            blueprint_status=self._blueprint_status,
            blueprint_schema=self._store.data.blueprint_schema,
            adapter_failed=self._adapter.failed,
        )

    # ----------------------------------------------------------------------------------
    # The protocols of summary.py and attribution.py: items, lookup and sink
    # ----------------------------------------------------------------------------------

    def routine_summary(self, device_id: str) -> RoutineSummary | None:
        """Return the device's routine for the Schedule summary, or None without one."""
        routine = self._routines.get(device_id)
        if routine is None:
            return None
        if routine.detached:
            return RoutineSummary((), None, None, Status.DETACHED)
        if routine.settings is None or routine.automation_id not in self._store.data.owned:
            return None
        status = self._status(routine)
        upcoming = self._occurrences(routine, status)
        entity_id = self._automation_entity(routine.automation_id)
        state = self.hass.states.get(entity_id) if entity_id else None
        history = self._store.data.owned[routine.automation_id].alias_history
        alias = state.name if state is not None else (history[-1] if history else "")
        lines = routine_lines(routine.settings, routine.automation_id, alias)
        writer = self._writer(routine.settings)
        text = writer.say("list_separator").join(writer.line(line) for line in lines)
        item = SummaryItem(
            kind=KIND_ROUTINE,
            automation_entity=entity_id or "",
            alias=alias,
            summary=text or writer.routine_kind(),
            next_run=upcoming[0].at if upcoming else None,
            source=SOURCE_PARSER,
            enabled=self._enabled(routine),
            custom_logic=bool(routine.settings.extra_conditions),
            parts=tuple(writer.line(line) for line in lines),
        )
        return RoutineSummary(
            (item,),
            routine.paused_until,
            routine.skipped_action if status is Status.SKIPPING else None,
            status,
        )

    def _writer(self, settings: RoutineSettings) -> Writer:
        """Return a Writer that names the weekly schedule a routine follows."""
        time_format = self.settings.resolved_time_format(self.hass.config.country)
        names = {
            entity_id: state.name
            for entity_id in (settings.schedule_entity,)
            if entity_id and (state := self.hass.states.get(entity_id)) is not None
        }
        return Writer(self.summary.phrases, time_format, names)

    def routine_for(self, entity_id: str) -> RoutineRuntime | None:
        """Return the runtime facts of the routine driving `entity_id`, or None."""
        for routine in self._routines.values():
            if routine.watched != entity_id or routine.settings is None:
                continue
            settings = routine.settings
            profile = self._profile(entity_id)
            schedule_state, _lookups = self._schedule_lookup(settings)
            expected = nextrun.expected_state(settings, dt_util.now(), schedule_state)
            return RoutineRuntime(
                device_id=routine.device_id,
                active=self._status(routine) in _RUNNING,
                paused=self._paused(routine),
                respect_manual=settings.respect_manual,
                expected="on" if expected == "on" else ("off" if expected == "off" else None),
                inactive_state=profile.inactive_state if profile else "off",
            )
        return None

    async def async_set_override(
        self, device_id: str, on: bool | None, source: Source, new_state: str
    ) -> None:
        """Record a classified change of a routine's device (the attributor's sink).

        Applied before any await and idempotent, as the attributor asks (L35).
        """
        routine = self._routines.get(device_id)
        if routine is None:
            return
        changed = routine.last_change_source is not source
        routine.last_change_source = source
        if on is not None and routine.override is not on:
            routine.override = on
            routine.override_by_skip = False
            changed = True
        _LOGGER.debug("%s changed to %s by %s", device_id, new_state, source)
        if changed:
            self._changed(device_id)

    async def async_set_manual_override(self, device_id: str, on: bool) -> None:
        """Turn the Manual override on or off: a person, or the blueprint at a scheduled time.

        Turning it off makes the blueprint catch up (its `override_cleared` trigger).
        """
        routine = self._require(device_id)
        routine.override = on
        routine.override_by_skip = False
        self._changed(device_id)

    async def async_restore_runtime(self, device_id: str, restored: RestoredRuntime) -> None:
        """Take back what a device page entity restored after a restart.

        A Paused until still ahead pauses again until then; one that passed while Home
        Assistant was down is dropped (the blueprint's start catch up applies the state).
        """
        routine = self._routines.get(device_id)
        if routine is None:
            return
        routine.override = restored.override
        routine.override_by_skip = restored.override_by_skip
        routine.last_change_source = restored.last_change_source
        if restored.paused_until is not None and restored.paused_until > dt_util.utcnow():
            routine.paused_until = restored.paused_until
            routine.skipped_action = restored.skipped_action
            self._schedule_resume(routine)
        self._changed(device_id)

    def restore_data(self, device_id: str) -> RestoredRuntime | None:
        """Return what a device page entity should keep across a restart."""
        routine = self._routines.get(device_id)
        if routine is None:
            return None
        return RestoredRuntime(
            paused_until=routine.paused_until,
            skipped_action=routine.skipped_action,
            override=routine.override,
            override_by_skip=routine.override_by_skip,
            last_change_source=routine.last_change_source,
        )

    # ----------------------------------------------------------------------------------
    # Opt in and out
    # ----------------------------------------------------------------------------------

    def _require(self, device_id: str, *, editing: bool = False) -> _Routine:
        """Return an opted in device's routine, or raise the translated reason it has none."""
        routine = self._routines.get(device_id)
        name = {"device": self._device_name(device_id)}
        if routine is None or device_id not in self._store.data.opted_in:
            raise _invalid("not_opted_in", name)
        if routine.detached:
            raise _invalid("detached", name)
        if editing and not self._adapter.works(ha_adapter.CAPABILITY_WRITE):
            raise _invalid("editing_unavailable")
        return routine

    async def async_opt_in(self, device_id: str, source: str = SOURCE_API) -> OptResult:
        """Give a device routine controls: the label, the entities, the routine back on."""
        device = self._device(device_id)
        if device is None or device.config_entry_id == self.entry.entry_id:
            raise _invalid("unknown_device", {"device": device_id})
        if not self.candidates(device_id):
            raise _invalid("not_eligible", {"device": self._device_name(device_id)})
        data = self._store.data
        changed = device_id not in data.opted_in
        data.opted_in.add(device_id)
        data.opted_out_at.pop(device_id, None)
        routine = self._routine(device_id)
        label = self._label()
        if label not in device.labels:
            dr.async_get(self.hass).async_update_device(device_id, labels={*device.labels, label})
        self._ensure_entities(device_id)
        if changed:
            _LOGGER.debug("%s opted in (%s)", device_id, source)
            self._store.async_delay_save()
            if routine.automation_id in data.owned and not routine.invalid:
                await self._async_turn(routine, on=True)
                await self._async_write(routine)
            self._schedule_cleanup()
            self._changed(device_id, REASON_OPTED_IN)
        return OptResult(device_id, opted_in=True, changed=changed, view=self.get(device_id))

    async def async_opt_out(self, device_id: str, source: str = SOURCE_API) -> OptResult:
        """Take a device's controls away: the routine off, settings kept, cleanup later."""
        data = self._store.data
        if device_id not in data.opted_in:
            return OptResult(device_id, opted_in=False, changed=False, view=self.get(device_id))
        _LOGGER.debug("%s opted out (%s)", device_id, source)
        routine = self._routine(device_id)
        if routine.write_handle is not None:
            await self._async_write(routine)
        data.opted_in.discard(device_id)
        data.opted_out_at[device_id] = dt_util.utcnow()
        device = self._device(device_id)
        label = self._label()
        if device is not None and label in device.labels:
            dr.async_get(self.hass).async_update_device(device_id, labels=device.labels - {label})
        await self._async_turn(routine, on=False)
        self._clear_runtime(routine)
        self._remove_entities(device_id)
        self._store.async_delay_save()
        self._schedule_cleanup()
        self._changed(device_id, REASON_OPTED_OUT)
        return OptResult(device_id, opted_in=False, changed=True, view=self.get(device_id))

    def _ensure_entities(self, device_id: str) -> tuple[str, str]:
        """Register the Manual override and Paused until entities; return their ids.

        The blueprint names both in its inputs, so their entity ids must be known at the
        first write, before the platforms add the entities; the platforms then claim the
        registry entries by unique id.
        """
        slug = markers.slugify(self._device_name(device_id))
        registry = er.async_get(self.hass)
        ids = [
            registry.async_get_or_create(
                _platform_of(key),
                DOMAIN,
                f"{_UNIQUE_PREFIX}{device_id}_{key}",
                config_entry=self.entry,
                suggested_object_id=f"{slug}_{key}",
            ).entity_id
            for key in (KEY_MANUAL_OVERRIDE, KEY_PAUSED_UNTIL)
        ]
        return ids[0], ids[1]

    def _remove_entities(self, device_id: str) -> None:
        """Remove a device's page entities from the registry; the Schedule sensor stays."""
        registry = er.async_get(self.hass)
        prefix = f"{_UNIQUE_PREFIX}{device_id}_"
        for entry in er.async_entries_for_config_entry(registry, self.entry.entry_id):
            if entry.unique_id.startswith(prefix) and entry.unique_id != f"{prefix}{_SCHEDULE_KEY}":
                registry.async_remove(entry.entity_id)

    def _label(self) -> str:
        """Return the Routines label id, creating the label when it is missing."""
        self._label_id = ha_adapter.ensure_label(
            self.hass, self._label_id, markers.LABEL_NAME, markers.ICON
        )
        return self._label_id

    def _labelled_devices(self) -> set[str]:
        """Return the user's devices carrying the Routines label."""
        return {
            device.id
            for device in dr.async_entries_for_label(dr.async_get(self.hass), self._label_id)
            if isinstance(device, dr.DeviceEntry) and not self._ours(device.id)
        }

    def _category(self) -> str:
        return ha_adapter.ensure_category(
            self.hass, "automation", markers.CATEGORY_NAME, markers.ICON
        )

    # ----------------------------------------------------------------------------------
    # Settings: the write path (TECH_SPEC 4.1)
    # ----------------------------------------------------------------------------------

    async def async_update(
        self, device_id: str, patch: Patch, source: str = SOURCE_API
    ) -> UpdateResult:
        """Validate a patch against the merged settings, show it at once, write it soon.

        On a problem nothing changes, listeners hear the routine as it was (so an entity
        that showed the new value reverts) and the problem is returned.
        """
        routine = self._require(device_id, editing=True)
        merged, problem = apply_patch(self._settings_of(routine), patch)
        if problem is None and merged.target_entity not in self.candidates(device_id):
            problem = Problem("target_entity", "invalid_target", {"entity": merged.target_entity})
        if problem is None:
            profile = self._profile(merged.target_entity)
            assert profile is not None  # noqa: S101  # candidates are supported domains
            problems = compiler.validate(merged, profile)
            problem = problems[0] if problems else None
        if problem is not None:
            _LOGGER.debug("%s refused a patch from %s: %s", device_id, source, problem.key)
            self._changed(device_id)
            return UpdateResult(self.get(device_id), problem)
        routine.settings = merged
        self._schedule_write(routine)
        self._changed(device_id)
        return UpdateResult(self.get(device_id))

    def _schedule_write(self, routine: _Routine) -> None:
        self._cancel_write(routine)

        @callback
        def due(_now: datetime) -> None:
            routine.write_handle = None
            self.entry.async_create_task(
                self.hass, self._async_write(routine), f"{DOMAIN} write {routine.device_id}"
            )

        routine.write_handle = async_call_later(self.hass, DEBOUNCE_SECONDS, due)

    def _cancel_write(self, routine: _Routine) -> None:
        if routine.write_handle is not None:
            routine.write_handle()
            routine.write_handle = None

    async def _async_write(self, routine: _Routine, *, raise_errors: bool = False) -> bool:
        """Compile the routine's settings and write them now; True when written.

        The write algorithm of TECH_SPEC 4.1 under the device's lock: helpers first, then
        the read and its guard with no await between (L37), the compile, the adapter write
        (which reloads that id), then `last_hash` and `last_valid_inputs`. A moved file
        raises `write_conflict`, an entry without M2 is detached. With `raise_errors` every
        failure propagates (the schema migration needs that, migration.py).
        """
        failure: Exception | None = None
        async with routine.lock:
            self._cancel_write(routine)
            settings = routine.settings
            if settings is None or routine.detached:
                return False
            try:
                await self._async_put(routine, settings)
            except (CompileError, HomeAssistantError, ha_adapter.AdapterError) as err:
                if raise_errors:
                    raise
                failure = err
        if failure is not None:
            await self._async_write_failed(routine, failure)
            return False
        self._changed(routine.device_id)
        return True

    async def _async_put(self, routine: _Routine, settings: RoutineSettings) -> None:
        """Compile and write under the device's lock (see `_async_write`)."""
        automation_id = routine.automation_id
        profile = self._profile(settings.target_entity)
        if profile is None:
            raise CompileError("invalid_inputs")
        refs = await self._async_refs(routine, settings)
        inputs = dict(compiler.compile(settings, profile, refs).inputs)
        current = await ha_adapter.async_read_automation(self.hass, automation_id)
        guard = ha_adapter.file_hash(self.hass)
        if current is not None and not markers.is_owned(current):
            raise ha_adapter.NotOwnedError(automation_id)
        config = self._entry_config(routine, current, inputs)
        result = await ha_adapter.async_write_automation(self.hass, automation_id, config, guard)
        self._record_write(routine, config, inputs)
        if result.created:
            self._present(routine, automation_id)

    async def _async_write_failed(self, routine: _Routine, err: Exception) -> None:
        """Turn a failed write into its outcome: detached, `write_conflict`, or a log line."""
        if isinstance(err, ha_adapter.NotOwnedError):
            await self.async_handle_detached(routine.automation_id)
        elif isinstance(err, ha_adapter.WriteConflictError):
            self._sync_issue(repairs.WRITE_CONFLICT, routine, present=True)
        else:
            _LOGGER.warning("Could not write the routine of %s: %s", routine.device_id, err)

    def _record_write(
        self, routine: _Routine, config: Mapping[str, Any], inputs: Mapping[str, Any]
    ) -> None:
        settings = routine.settings
        assert settings is not None  # noqa: S101  # only settings are written
        data = self._store.data
        record = data.owned.get(routine.automation_id)
        alias = str(config.get("alias", ""))
        history = record.alias_history if record else ()
        if alias not in history and self._alias_generated(alias, routine.device_id, history):
            history = (*history, alias)
        data.owned[routine.automation_id] = OwnedRecord(
            device_id=routine.device_id,
            target_entity=settings.target_entity,
            last_hash=markers.config_hash(config),
            last_valid_inputs=dict(inputs),
            previous_inputs=record.previous_inputs if record else None,
            schema=compiler.BLUEPRINT_SCHEMA_VERSION,
            alias_history=history,
        )
        self._store.async_delay_save()
        self._sync_issue(repairs.WRITE_CONFLICT, routine, present=False)
        self._watch(routine)

    async def _async_refs(
        self, routine: _Routine, settings: RoutineSettings
    ) -> compiler.HelperRefs:
        """Return the helper entities the routine's automation names, creating a timer."""
        device_id = routine.device_id
        record = self._store.data.owned.get(routine.automation_id)
        old = _refs(record.last_valid_inputs if record else None) or compiler.HelperRefs(device_id)
        override, paused = old.override_entity, old.paused_until_entity
        if device_id in self._store.data.opted_in:
            override, paused = self._ensure_entities(device_id)
        timer = compiler.UNUSED_TIMER
        if settings.turn_off_after_min or settings.turn_back_on_after_min:
            timer = old.timer_entity
            if timer == compiler.UNUSED_TIMER:
                timer = f"timer.routine_{self._slug(routine)}"
            if not self._exists(timer):
                await self._async_create_helper(routine, "timer", timer)
        return compiler.HelperRefs(
            device_id=device_id,
            timer_entity=timer,
            schedule_entity=settings.schedule_entity or compiler.UNUSED_SCHEDULE,
            override_entity=override,
            paused_until_entity=paused,
        )

    async def _async_create_helper(
        self, routine: _Routine, domain: Literal["timer", "schedule"], entity_id: str
    ) -> None:
        """Create a timer or schedule helper with this entity id and the label (L36)."""
        user_id = await self._async_system_user()
        fields: dict[str, Any] = (
            {"duration": "00:00:00", "restore": True} if domain == "timer" else {}
        )
        name = self.summary.phrases["routine_alias"].format(
            device=self._device_name(routine.device_id)
        )
        await ha_adapter.async_create_helper(
            self.hass, user_id, domain, name, entity_id=entity_id, labels=[self._label()], **fields
        )

    async def _async_system_user(self) -> str:
        stored = self.entry.data.get(CONF_SYSTEM_USER_ID)
        user_id = await ha_adapter.async_ensure_system_user(self.hass, stored)
        if user_id != stored:
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_SYSTEM_USER_ID: user_id}
            )
        return user_id

    def _slug(self, routine: _Routine) -> str:
        """Return the slug a routine's helpers and automation entity id use (M8, PRD 9.2)."""
        if routine.slug is None:
            taken = {other.slug for other in self._routines.values() if other.slug}
            name = self._device_name(routine.device_id)
            routine.slug = markers.helper_slug(name, routine.device_id, taken)
        return routine.slug

    def _remember_slug(self, routine: _Routine, refs: compiler.HelperRefs | None) -> None:
        """Take a routine's slug from the helpers it already names."""
        if routine.slug is not None or refs is None:
            return
        for entity_id in (refs.timer_entity, refs.schedule_entity):
            object_id = entity_id.partition(".")[2]
            if object_id.startswith("routine_"):
                routine.slug = object_id.removeprefix("routine_")
                return

    def _alias_generated(self, alias: str, device_id: str, history: tuple[str, ...]) -> bool:
        template = self.summary.phrases["routine_alias"]
        return alias in history or markers.alias_is_generated(
            alias, [self._device_name(device_id)], template
        )

    def _entry_config(
        self, routine: _Routine, current: Mapping[str, Any] | None, inputs: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Build the `automations.yaml` entry: presentation set on create, respected after.

        The alias (and with it the description) follows the device name while it is a
        generated one (PRD 8.1); keys a person added stay.
        """
        name = self._device_name(routine.device_id)
        phrases = self.summary.phrases
        generated = markers.presentation(name, phrases)
        entry = dict(current or {})
        record = self._store.data.owned.get(routine.automation_id)
        history = record.alias_history if record else ()
        alias = entry.get("alias")
        if not isinstance(alias, str) or self._alias_generated(alias, routine.device_id, history):
            previous = alias if isinstance(alias, str) else None
            old_names = [_name_from(phrases["routine_alias"], old) for old in (*history, previous)]
            descriptions = {
                markers.presentation(old, phrases).description for old in old_names if old
            }
            if entry.get("description") in descriptions or "description" not in entry:
                entry["description"] = generated.description
            entry["alias"] = generated.alias
        entry["id"] = routine.automation_id
        entry["use_blueprint"] = {"path": markers.BLUEPRINT_PATH, "input": dict(inputs)}
        return entry

    def _present(self, routine: _Routine, automation_id: str) -> None:
        """Set the presentation markers of a new automation: M5 to M9 (PRD 8.1)."""
        entity_id = self._automation_entity(automation_id)
        if entity_id is None:
            return
        registry = er.async_get(self.hass)
        entry = registry.async_get(entity_id)
        assert entry is not None  # noqa: S101  # the registry just named it
        desired = f"{markers.ENTITY_ID_PREFIX}{self._slug(routine)}"
        device = self._device(routine.device_id)
        area = device.area_id if device and self.settings.assign_area else UNDEFINED
        ha_adapter.async_update_registry_entity(
            self.hass,
            entity_id,
            new_entity_id=(
                desired
                if desired != entity_id and not registry.async_is_registered(desired)
                else UNDEFINED
            ),
            labels={*entry.labels, self._label()},
            categories={**entry.categories, "automation": self._category()},
            icon=markers.ICON,
            area_id=area,
        )

    def _watch(self, routine: _Routine) -> None:
        target = routine.settings.target_entity if routine.settings else None
        if routine.watched == target:
            return
        if routine.watched is not None:
            self._attributor.unwatch(routine.watched)
        routine.watched = target
        if target is not None:
            self._attributor.watch(target)

    async def _async_turn(self, routine: _Routine, *, on: bool) -> bool:
        """Turn the routine's automation on or off; True when its state changed."""
        entity_id = self._automation_entity(routine.automation_id)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state == STATE_UNAVAILABLE or (state.state == STATE_ON) is on:
            return False
        await self.hass.services.async_call(
            "automation",
            "turn_on" if on else "turn_off",
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        return True

    async def _async_suspend(self, routine: _Routine, reason: str) -> None:
        """Turn the routine off for a reason, remembering it was the manager that did."""
        if await self._async_turn(routine, on=False) and routine.turned_off_for is None:
            routine.turned_off_for = reason

    async def _async_unsuspend(self, routine: _Routine, reason: str) -> None:
        """Turn the routine back on when the manager turned it off for this reason."""
        if routine.turned_off_for == reason:
            routine.turned_off_for = None
            await self._async_turn(routine, on=True)

    def _sync_issue(
        self, issue_id: str, routine: _Routine, *, present: bool, **placeholders: str
    ) -> None:
        """Raise or clear a per routine Repairs issue (decision L41)."""
        values = {
            "device": self._device_name(routine.device_id),
            "automation": self._automation_entity(routine.automation_id) or routine.automation_id,
            **placeholders,
        }
        repairs.async_sync_issue(
            self.hass, issue_id, present, values, subject=routine.automation_id
        )

    # ----------------------------------------------------------------------------------
    # The migration's side (migration.SchemaMigrationTarget) and the fix flows
    # ----------------------------------------------------------------------------------

    async def async_write_settings(self, automation_id: str, settings: RoutineSettings) -> None:
        """Compile and write settings for an owned automation now; raise on any failure."""
        record = self._store.data.owned[automation_id]
        routine = self._routine(record.device_id, automation_id)
        previous, routine.settings = routine.settings, settings
        try:
            await self._async_write(routine, raise_errors=True)
        except Exception:
            routine.settings = previous
            raise

    async def async_restore_last_valid(self, automation_id: str) -> None:
        """Fix flow of `invalid_inputs`: write the last valid inputs back, routine on."""
        routine = self._fixable(automation_id)
        record = self._store.data.owned[automation_id]
        settings = _settings(record.last_valid_inputs)
        if settings is None:
            raise _invalid("no_valid_settings", {"device": self._device_name(routine.device_id)})
        routine.settings = settings
        routine.invalid = False
        if await self._async_write(routine):
            self._sync_issue(repairs.INVALID_INPUTS, routine, present=False)
            routine.turned_off_for = None
            await self._async_turn(routine, on=True)
            self._changed(routine.device_id)

    async def async_regenerate(self, automation_id: str) -> None:
        """Fix flow of `automation_load_failed`: write the last valid inputs and reload."""
        routine = self._fixable(automation_id)
        routine.regenerated = False
        await self._async_check_loaded(routine)

    async def async_retry_write(self, automation_id: str) -> None:
        """Fix flow of `write_conflict`: write the routine's settings again now."""
        await self._async_write(self._fixable(automation_id))

    async def async_create_new_routine(self, device_id: str) -> None:
        """Fix flow of `detached_routine`: a new routine; the detached one is never touched.

        The new automation gets the first free id derived from the device id, writes the
        settings the routine had before it was detached, and the controls come back.
        """
        routine = self._routines.get(device_id)
        if routine is None or not routine.detached:
            return
        taken = {entry.get("id") for entry in await ha_adapter.async_read_automations(self.hass)}
        old_id = routine.automation_id
        number = 2
        while (candidate := markers.automation_id(f"{device_id}#{number}")) in taken:
            number += 1
        repairs.async_sync_issue(self.hass, repairs.DETACHED_ROUTINE, present=False, subject=old_id)
        routine.automation_id = candidate
        routine.detached = False
        await self._async_write(routine)
        self._changed(device_id)

    def _fixable(self, automation_id: str) -> _Routine:
        device_id = self._device_of_automation(automation_id)
        if device_id is None or automation_id not in self._store.data.owned:
            raise _invalid("unknown_routine", {"automation": automation_id})
        return self._routines[device_id]

    async def async_ensure_blueprint(self) -> bool:
        """Install the shipped blueprint when missing or previously shipped (TECH_SPEC 7 step 2).

        True when the installed file is the shipped one afterwards; False for a hand
        edited file, which stays untouched and raises `blueprint_modified`.
        """
        shipped = await self.hass.async_add_executor_job(maintenance.shipped_blueprint_text)
        installed = await self.hass.async_add_executor_job(
            ha_adapter.installed_blueprint_text, self.hass
        )
        shipped_hash = maintenance.blueprint_hash(shipped)
        data = self._store.data
        installed_hash = None if installed is None else maintenance.blueprint_hash(installed)
        if installed_hash not in {None, shipped_hash, data.blueprint_hash}:
            self._blueprint_status = "modified"
            repairs.async_sync_issue(self.hass, repairs.BLUEPRINT_MODIFIED, present=True)
            return False
        if installed_hash != shipped_hash:
            await ha_adapter.async_install_blueprint(self.hass, shipped)
        if data.blueprint_hash != shipped_hash:
            data.blueprint_hash = shipped_hash
            self._store.async_delay_save()
        self._blueprint_status = "shipped"
        repairs.async_sync_issue(self.hass, repairs.BLUEPRINT_MODIFIED, present=False)
        return True

    async def async_blueprint_reinstalled(self) -> None:
        """React to the `reinstall_blueprint` maintenance action having put it back."""
        await self.async_ensure_blueprint()
        await self._async_migrate()
        self._notify(ManagerEvent("health_changed", None))

    async def _async_migrate(self) -> None:
        """Run the blueprint schema migration; a failed rewrite is `automation_load_failed`.

        The issue stays until a later run (every start retries) rewrites the automation.
        """
        failed = await migration.async_migrate_blueprint_schema(self.hass, self, self._store)
        for routine in list(self._routines.values()):
            failing = routine.automation_id in failed
            if failing is not routine.migration_failed:
                routine.migration_failed = routine.load_failed = failing
                self._sync_issue(repairs.AUTOMATION_LOAD_FAILED, routine, present=failing)
                self._changed(routine.device_id)

    # ----------------------------------------------------------------------------------
    # Skip, pause, resume, enable, disable (PRD 5.5, D18 to D21, L22, L40)
    # ----------------------------------------------------------------------------------

    def _result(self, device_id: str, action: str) -> ActionResult:
        view = self.get(device_id)
        assert view is not None  # noqa: S101  # only routine devices get here
        return ActionResult(
            device_id=device_id,
            device_name=view.device_name,
            action=action,
            paused_until=view.paused_until,
            skipped_action=view.skipped_action,
            next_action=view.next_action,
        )

    def _require_automation(self, device_id: str) -> _Routine:
        routine = self._require(device_id)
        if routine.settings is None or routine.automation_id not in self._store.data.owned:
            raise _invalid("no_routine", {"device": self._device_name(device_id)})
        return routine

    async def async_skip_next(self, device_id: str) -> ActionResult:
        """Skip the action the Schedule shows next (FR-R11, D18, D19, L40)."""
        routine = self._require_automation(device_id)
        settings = routine.settings
        assert settings is not None  # noqa: S101  # _require_automation checked
        now = dt_util.now()
        countdown = self._countdown_ends(routine)
        schedule_state, lookups = self._schedule_lookup(settings)
        target = nextrun.skip_target(
            settings,
            now,
            routine.paused_until if self._paused(routine) else None,
            schedule_state,
            lookups,
            countdown_ends=countdown,
        )
        if target is None:
            raise _invalid("nothing_to_skip", {"device": self._device_name(device_id)})
        if target.at == countdown:
            await self.hass.services.async_call(
                "timer", "cancel", {ATTR_ENTITY_ID: self._timer_entity(routine)}, blocking=True
            )
        elif _is_window_end(settings, target):
            routine.override = True
            routine.override_by_skip = True
            self._changed(device_id)
        routine.paused_until = target.paused_until
        routine.skipped_action = Occurrence(target.at, target.verb)
        self._paused_now(routine)
        return self._result(device_id, "skip_next")

    async def async_pause(
        self, device_id: str, *, until: datetime | None = None, duration: timedelta | None = None
    ) -> ActionResult:
        """Pause until a moment or for a duration, exactly one of them (FR-R12)."""
        if (until is None) == (duration is None):
            raise _invalid("pause_until_or_for")
        moment = until if until is not None else dt_util.utcnow() + (duration or timedelta())
        if moment <= dt_util.utcnow():
            raise _invalid("paused_until_in_past")
        routine = self._require_automation(device_id)
        if routine.override_by_skip:
            routine.override = routine.override_by_skip = False
            self._changed(device_id)
        routine.paused_until = moment
        routine.skipped_action = None
        self._paused_now(routine)
        return self._result(device_id, "pause")

    def _paused_now(self, routine: _Routine) -> None:
        self._schedule_resume(routine)
        self._changed(routine.device_id)
        self.hass.bus.async_fire(EVENT_PAUSED, self._pause_data(routine))

    def _pause_data(self, routine: _Routine) -> dict[str, Any]:
        until = routine.paused_until
        return {
            "device_id": routine.device_id,
            "automation_id": routine.automation_id,
            "until": until.isoformat() if until else None,
        }

    async def async_resume(self, device_id: str) -> ActionResult:
        """End a pause or skip now; the blueprint catches up (FR-R13, D20, L40).

        An override the skip set is cleared first, so the catch up applies the window.
        """
        routine = self._require_automation(device_id)
        if routine.override_by_skip:
            routine.override = routine.override_by_skip = False
            self._changed(device_id)
        if self._paused(routine):
            self._end_pause(routine)
        return self._result(device_id, "resume")

    def _schedule_resume(self, routine: _Routine) -> None:
        self._cancel_resume(routine)
        until = routine.paused_until
        assert until is not None  # noqa: S101  # only a pause schedules its end

        @callback
        def ended(_now: datetime) -> None:
            routine.resume_handle = None
            routine.override_by_skip = False
            self._end_pause(routine)

        routine.resume_handle = async_track_point_in_utc_time(self.hass, ended, until)

    def _end_pause(self, routine: _Routine) -> None:
        """Clear Paused until (the blueprint resumes timers and catches up) and tell."""
        self._cancel_resume(routine)
        data = self._pause_data(routine)
        routine.paused_until = None
        routine.skipped_action = None
        self._changed(routine.device_id)
        self.hass.bus.async_fire(EVENT_RESUMED, data)

    def _cancel_resume(self, routine: _Routine) -> None:
        if routine.resume_handle is not None:
            routine.resume_handle()
            routine.resume_handle = None

    def _clear_runtime(self, routine: _Routine) -> None:
        self._cancel_write(routine)
        self._cancel_resume(routine)
        routine.paused_until = None
        routine.skipped_action = None
        routine.override = routine.override_by_skip = False

    async def async_enable(self, device_id: str) -> ActionResult:
        """Turn the routine on (FR-R14): the Routine switch."""
        await self._async_turn(self._require_automation(device_id), on=True)
        return self._result(device_id, "enable")

    async def async_disable(self, device_id: str) -> ActionResult:
        """Turn the routine off (FR-R14); a Paused until value is kept."""
        await self._async_turn(self._require_automation(device_id), on=False)
        return self._result(device_id, "disable")

    async def async_run_action(
        self,
        action: ActionName,
        target: Mapping[str, Any],
        *,
        until: datetime | None = None,
        duration: timedelta | None = None,
    ) -> ActionResults:
        """Run one action over a native target (FR-R15, S13, TECH_SPEC 4.6).

        Devices without a routine are listed as ignored; no routine device at all raises
        `no_routine_targets`. A device the action cannot apply to (nothing to skip) is
        ignored with that reason.
        """
        if action == "pause" and (until is None) == (duration is None):
            raise _invalid("pause_until_or_for")
        resolved = self.resolve_targets(target)
        if not resolved.device_ids:
            raise _invalid("no_routine_targets")
        results: builtins.list[ActionResult] = []
        ignored = list(resolved.ignored)
        for device_id in resolved.device_ids:
            try:
                if action == "pause":
                    results.append(
                        await self.async_pause(device_id, until=until, duration=duration)
                    )
                else:
                    results.append(await getattr(self, f"async_{action}")(device_id))
            except ServiceValidationError as err:
                ignored.append(IgnoredTarget(device_id, "device", str(err.translation_key)))
        return ActionResults(tuple(results), tuple(ignored))

    # ----------------------------------------------------------------------------------
    # Targets, as S13 asks
    # ----------------------------------------------------------------------------------

    def _is_routine_device(self, device_id: str) -> str | None:
        """Return None for a device with a routine, else why it has none."""
        routine = self._routines.get(device_id)
        if routine is not None and routine.detached:
            return "detached"
        if (
            routine is None
            or device_id not in self._store.data.opted_in
            or routine.automation_id not in self._store.data.owned
        ):
            return "no_routine"
        return None

    def _device_of_entity(self, entity_id: str) -> str | None:
        """Return the user's device an entity belongs to, our page entities included."""
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is None:
            return None
        if entry.platform == DOMAIN and entry.unique_id.startswith(_UNIQUE_PREFIX):
            rest = entry.unique_id.removeprefix(_UNIQUE_PREFIX)
            for key in ENTITY_KEYS:
                if rest.endswith(f"_{key}"):
                    return rest.removesuffix(f"_{key}")
        if entry.domain == "automation":
            return self._device_of_automation(entry.unique_id)
        return entry.device_id

    def resolve_targets(self, target: Mapping[str, Any]) -> TargetResolution:
        """Turn a native target into routine devices plus the ignored list (S13).

        `device_id`, `entity_id`, `area_id`, `floor_id` and `label_id` (each a string or a
        list). An area, floor or label expands to its devices, and each device it covers
        without a routine is ignored by name; a target naming nothing is ignored itself.
        """
        found: dict[str, None] = {}
        ignored: builtins.list[IgnoredTarget] = []

        def consider(device_id: str) -> None:
            if (reason := self._is_routine_device(device_id)) is None:
                found[device_id] = None
            elif all(item.target != device_id for item in ignored):
                ignored.append(IgnoredTarget(device_id, "device", reason))

        for device_id in _ids(target.get("device_id")):
            consider(device_id)
        for entity_id in _ids(target.get("entity_id")):
            if (owner := self._device_of_entity(entity_id)) is None:
                ignored.append(IgnoredTarget(entity_id, "entity", "no_routine"))
            else:
                consider(owner)
        areas = {kind: list(_ids(target.get(f"{kind}_id"))) for kind in ("area", "floor", "label")}
        for floor_id in areas["floor"]:
            on_floor = [
                area.id
                for area in ar.async_get(self.hass).async_list_areas()
                if area.floor_id == floor_id
            ]
            self._expand("floor", floor_id, self._area_devices(on_floor), consider, ignored)
        for area_id in areas["area"]:
            self._expand("area", area_id, self._area_devices([area_id]), consider, ignored)
        for label_id in areas["label"]:
            self._expand("label", label_id, self._label_devices(label_id), consider, ignored)
        return TargetResolution(tuple(found), tuple(ignored))

    def _expand(
        self,
        kind: Literal["area", "floor", "label"],
        target: str,
        devices: Iterable[str],
        consider: Callable[[str], None],
        ignored: builtins.list[IgnoredTarget],
    ) -> None:
        covered = list(dict.fromkeys(devices))
        if not covered:
            ignored.append(IgnoredTarget(target, kind, "no_routine"))
        for device_id in covered:
            consider(device_id)

    def _ours(self, device_id: str | None) -> bool:
        device = self._device(device_id) if device_id else None
        return device is not None and device.config_entry_id == self.entry.entry_id

    def _area_devices(self, area_ids: Iterable[str]) -> builtins.list[str]:
        devices = dr.async_get(self.hass)
        entities = er.async_get(self.hass)
        found: builtins.list[str] = []
        for area_id in area_ids:
            found += [device.id for device in dr.async_entries_for_area(devices, area_id)]
            found += [
                entry.device_id
                for entry in er.async_entries_for_area(entities, area_id)
                if entry.device_id
            ]
        return [device_id for device_id in found if not self._ours(device_id)]

    def _label_devices(self, label_id: str) -> builtins.list[str]:
        found = [
            device.id for device in dr.async_entries_for_label(dr.async_get(self.hass), label_id)
        ]
        found += [
            entry.device_id
            for entry in er.async_entries_for_label(er.async_get(self.hass), label_id)
            if entry.device_id
        ]
        return [device_id for device_id in found if not self._ours(device_id)]

    # ----------------------------------------------------------------------------------
    # Sync back (PRD 7.3 and 8.2)
    # ----------------------------------------------------------------------------------

    @callback
    def _automations_reloaded(self, _event: Event[Any]) -> None:
        self._request_sync()

    @callback
    def _request_sync(self) -> None:
        """Run one sync of the whole file soon; a burst of reloads is one or two syncs."""
        self._sync_again = True
        if self._sync_task is None or self._sync_task.done():
            self._sync_task = self.entry.async_create_task(
                self.hass, self._async_sync_loop(), f"{DOMAIN} sync back"
            )

    async def _async_sync_loop(self) -> None:
        while self._sync_again and not self._stopping:
            self._sync_again = False
            await self._async_sync_all()

    async def _async_sync_all(self) -> bool:
        """Read the file once and bring every routine in line with it; False on a bad file."""
        try:
            entries = await ha_adapter.async_read_automations(self.hass)
        except ha_adapter.AdapterError, HomeAssistantError:
            _LOGGER.warning("Could not read the automations file", exc_info=True)
            return False
        by_id: dict[str, Mapping[str, Any]] = {}
        for entry in entries:
            if markers.has_routine_id(entry):
                by_id.setdefault(entry["id"], entry)
        for automation_id, config in by_id.items():
            if markers.is_owned(config):
                await self.async_sync_back(automation_id, config)
            elif self._device_of_automation(automation_id) is not None:
                await self.async_handle_detached(automation_id)
        for automation_id in [key for key in self._store.data.owned if key not in by_id]:
            await self.async_handle_removed(automation_id)
        for routine in list(self._routines.values()):
            if routine.detached and routine.automation_id not in by_id:
                await self.async_handle_removed(routine.automation_id)
        return True

    def _input_problem(self, inputs: Any) -> str | None:
        """Return why blueprint inputs cannot run as a routine, or None."""
        if not compiler.is_valid_shape(inputs):
            return "invalid_inputs"
        target = inputs["target_entity"]
        device_class = self._device_class(target)
        if compiler.has_refused_action(inputs, device_class):
            return "refused_action"
        profile = profile_for(target.partition(".")[0], device_class)
        if profile is None:
            return "invalid_inputs"
        problems = compiler.validate(compiler.decompile(inputs), profile)
        return problems[0].translation_key if problems else None

    async def async_sync_back(self, automation_id: str, config: Mapping[str, Any]) -> None:
        """Bring one owned entry of the file into the routine (PRD 7.3).

        A hash the manager wrote is skipped. A valid foreign edit becomes the settings
        (and stale derived inputs are written back, so the blueprint never runs on them);
        an invalid one turns the routine off, overwrites nothing and raises
        `invalid_inputs`.
        """
        inputs = config["use_blueprint"].get("input")
        record = self._store.data.owned.get(automation_id)
        device_id = record.device_id if record else _input(inputs, "device_id")
        if device_id is None:
            _LOGGER.warning("%s names no device; it is left alone", automation_id)
            return
        routine = self._routine(device_id, automation_id)
        if routine.detached:
            routine.detached = False
            self._sync_issue(repairs.DETACHED_ROUTINE, routine, present=False)
        digest = markers.config_hash(config)
        async with routine.lock:
            record = self._store.data.owned.get(automation_id)
            own = record is not None and record.last_hash == digest
            reason = None if own else self._input_problem(inputs)
            if not own and reason is None:
                routine.settings = compiler.decompile(inputs)
                self._store.data.owned[automation_id] = OwnedRecord(
                    device_id=device_id,
                    target_entity=routine.settings.target_entity,
                    last_hash=digest,
                    last_valid_inputs=dict(inputs),
                    previous_inputs=record.previous_inputs if record else None,
                    schema=record.schema if record else compiler.BLUEPRINT_SCHEMA_VERSION,
                    alias_history=record.alias_history if record else (),
                )
                self._store.async_delay_save()
                self._remember_slug(routine, compiler.refs_of(inputs))
                self._watch(routine)
            elif reason is not None and record is None:
                self._store.data.owned[automation_id] = OwnedRecord(
                    device_id, str(_input(inputs, "target_entity") or "")
                )
                self._store.async_delay_save()
        if reason is not None:
            routine.invalid = True
            await self._async_suspend(routine, _OFF_INVALID)
            self._sync_issue(repairs.INVALID_INPUTS, routine, present=True, reason=reason)
            self._changed(device_id)
            return
        await self._async_valid_again(routine)
        if own:
            return
        settings = routine.settings
        assert settings is not None  # noqa: S101  # decompiled above
        profile = self._profile(settings.target_entity)
        assert profile is not None  # noqa: S101  # _input_problem checked
        if compiler.compile(settings, profile, compiler.refs_of(inputs)).inputs != {
            **compiler.INPUT_DEFAULTS,
            **inputs,
        }:
            await self._async_write(routine)
        self._changed(device_id)

    async def _async_valid_again(self, routine: _Routine) -> None:
        if routine.invalid:
            routine.invalid = False
            self._sync_issue(repairs.INVALID_INPUTS, routine, present=False)
            await self._async_unsuspend(routine, _OFF_INVALID)
            self._changed(routine.device_id)

    async def async_handle_removed(self, automation_id: str) -> None:
        """Reset a routine whose automation was deleted by hand; the device stays opted in."""
        data = self._store.data
        record = data.owned.pop(automation_id, None)
        device_id = record.device_id if record else self._device_of_automation(automation_id)
        for issue_id in _ROUTINE_ISSUES:
            repairs.async_sync_issue(self.hass, issue_id, present=False, subject=automation_id)
        await self._async_delete_helpers(
            _refs(record.last_valid_inputs if record else None) or compiler.HelperRefs("")
        )
        self._store.async_delay_save()
        if device_id is None:
            return
        routine = self._routine(device_id)
        self._clear_runtime(routine)
        routine.settings = None
        routine.invalid = routine.detached = routine.missing_target = False
        routine.load_failed = routine.regenerated = False
        routine.turned_off_for = None
        routine.automation_id = markers.automation_id(device_id)
        self._watch(routine)
        if device_id not in data.opted_in:
            del self._routines[device_id]
        self._changed(device_id)

    async def async_handle_detached(self, automation_id: str) -> None:
        """Take control happened: no longer owned, controls unavailable, one issue (PRD 8.2)."""
        device_id = self._device_of_automation(automation_id)
        if device_id is None:
            return
        data = self._store.data
        if data.owned.pop(automation_id, None) is not None:
            self._store.async_delay_save()
        routine = self._routine(device_id, automation_id)
        if routine.detached:
            return
        routine.detached = True
        self._cancel_write(routine)
        for issue_id in (repairs.INVALID_INPUTS, repairs.WRITE_CONFLICT):
            self._sync_issue(issue_id, routine, present=False)
        self._sync_issue(repairs.DETACHED_ROUTINE, routine, present=True)
        self._changed(device_id)

    async def _async_delete_helpers(self, refs: compiler.HelperRefs) -> None:
        for entity_id in (refs.timer_entity, refs.schedule_entity):
            if entity_id in {compiler.UNUSED_TIMER, compiler.UNUSED_SCHEDULE}:
                continue
            if er.async_get(self.hass).async_get(entity_id) is None:
                continue
            try:
                await ha_adapter.async_delete_helper(
                    self.hass, await self._async_system_user(), entity_id
                )
            except ha_adapter.HelperError:
                _LOGGER.warning("Could not delete %s", entity_id, exc_info=True)

    # ----------------------------------------------------------------------------------
    # Registry reactions (TECH_SPEC 7)
    # ----------------------------------------------------------------------------------

    @callback
    def _device_registry_updated(self, event: Event[dr.EventDeviceRegistryUpdatedData]) -> None:
        data = event.data
        device_id = data["device_id"]
        if data["action"] == "remove":
            if device_id in self._routines:
                self.entry.async_create_task(
                    self.hass, self._async_device_removed(device_id, data["device"])
                )
            return
        if data["action"] != "update" or self._ours(device_id):
            return
        changes = data["changes"]
        if "labels" in changes:
            self._labels_changed(device_id, set(changes["labels"]))
        if device_id in self._routines and {"name", "name_by_user", "area_id"} & set(changes):
            self.entry.async_create_task(self.hass, self._async_follow_device(device_id))

    @callback
    def _labels_changed(self, device_id: str, old_labels: set[str]) -> None:
        device = self._device(device_id)
        labels = device.labels if device is not None else frozenset()
        label = self._label_id
        # A label deleted from the registry is no opt out: the label listener repairs it.
        exists = lr.async_get(self.hass).async_get_label(label) is not None
        # A labelled device with nothing a routine can drive stays as it is.
        if label in labels and label not in old_labels and self.candidates(device_id):
            self.entry.async_create_task(self.hass, self.async_opt_in(device_id, SOURCE_LABEL))
        elif label in old_labels and label not in labels and exists:
            self.entry.async_create_task(self.hass, self.async_opt_out(device_id, SOURCE_LABEL))

    @callback
    def _label_registry_updated(self, event: Event[lr.EventLabelRegistryUpdatedData]) -> None:
        if event.data["action"] == "remove" and event.data["label_id"] == self._label_id:
            self._repair_label()

    @callback
    def _repair_label(self) -> None:
        """Recreate the deleted Routines label and apply it again from `opted_in`.

        Deleting the label is not every device opting out at once (plan Section 4.9). It
        runs while the label registry dispatches the removal, so the devices are labelled
        again before their own label change events reach `_labels_changed`.
        """
        label = self._label()
        devices = dr.async_get(self.hass)
        for device_id in sorted(self._store.data.opted_in):
            device = self._device(device_id)
            if device is not None and label not in device.labels:
                devices.async_update_device(device_id, labels={*device.labels, label})
        entities = er.async_get(self.hass)
        for record in list(self._store.data.owned.values()):
            refs = _refs(record.last_valid_inputs)
            automation = self._automation_entity(self._routines[record.device_id].automation_id)
            for entity_id in (
                automation,
                *(() if refs is None else (refs.timer_entity, refs.schedule_entity)),
            ):
                entry = entities.async_get(entity_id) if entity_id else None
                if entry is not None and label not in entry.labels:
                    ha_adapter.async_update_registry_entity(
                        self.hass, entry.entity_id, labels={*entry.labels, label}
                    )

    async def _async_device_removed(self, device_id: str, device: Mapping[str, Any]) -> None:
        """Turn off the routine of a device that left Home Assistant; clean up later (D28)."""
        data = self._store.data
        data.removed_devices_at.setdefault(device_id, dt_util.utcnow())
        routine = self._routines[device_id]
        await self._async_turn(routine, on=False)
        self._clear_runtime(routine)
        self._remove_entities(device_id)
        devices = dr.async_get(self.hass)
        for identifier in device.get("identifiers", ()):
            linked = devices.async_get_device_by_identifier(
                (identifier[0], identifier[1]), self.entry.entry_id
            )
            if linked is not None:
                devices.async_remove_device(linked.id)
        self._store.async_delay_save()
        self._schedule_cleanup()
        self._changed(device_id)

    async def _async_follow_device(self, device_id: str) -> None:
        """Follow a device rename or move: the alias, the helper names and the area."""
        routine = self._routines[device_id]
        if routine.automation_id in self._store.data.owned and not routine.invalid:
            await self._async_follow_name(routine)
            self._follow_area(routine)
        self._changed(device_id)

    async def _async_follow_name(self, routine: _Routine) -> None:
        """Rewrite a generated alias after a rename, and rename the routine's helpers."""
        current = await ha_adapter.async_read_automation(self.hass, routine.automation_id)
        if current is None or not markers.is_owned(current):
            return
        inputs = current["use_blueprint"].get("input") or {}
        if self._entry_config(routine, current, inputs).get("alias") == current.get("alias"):
            return
        await self._async_write(routine)
        name = self.summary.phrases["routine_alias"].format(
            device=self._device_name(routine.device_id)
        )
        record = self._store.data.owned[routine.automation_id]
        refs = _refs(record.last_valid_inputs) or compiler.HelperRefs(routine.device_id)
        helpers = [
            entity_id
            for entity_id in (refs.timer_entity, refs.schedule_entity)
            if er.async_get(self.hass).async_get(entity_id) is not None
        ]
        for entity_id in helpers:
            await ha_adapter.async_update_helper(
                self.hass, await self._async_system_user(), entity_id, name=name
            )

    def _follow_area(self, routine: _Routine) -> None:
        """M9: the automation sits in the device's area while `assign_area` is on."""
        entity_id = self._automation_entity(routine.automation_id)
        device = self._device(routine.device_id)
        if not self.settings.assign_area or entity_id is None or device is None:
            return
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is not None and entry.area_id != device.area_id:
            ha_adapter.async_update_registry_entity(self.hass, entity_id, area_id=device.area_id)

    @callback
    def _entity_registry_updated(self, event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        data = event.data
        if data["action"] == "update" and "old_entity_id" in data:
            old, new = data["old_entity_id"], data["entity_id"]
            for routine in list(self._routines.values()):
                if self._names(routine, old):
                    self.entry.async_create_task(
                        self.hass, self._async_entity_renamed(routine, old, new)
                    )
        elif data["action"] in {"create", "remove"}:
            for routine in self._routines.values():
                if (
                    routine.settings is not None
                    and routine.settings.target_entity == data["entity_id"]
                ):
                    self.entry.async_create_task(self.hass, self._async_check_target(routine))

    def _names(self, routine: _Routine, entity_id: str) -> bool:
        """Tell whether a routine's automation names an entity (its target or a helper)."""
        if routine.settings is not None and routine.settings.target_entity == entity_id:
            return True
        record = self._store.data.owned.get(routine.automation_id)
        refs = _refs(record.last_valid_inputs if record else None)
        return refs is not None and entity_id in {
            refs.timer_entity,
            refs.schedule_entity,
            refs.override_entity,
            refs.paused_until_entity,
        }

    async def _async_entity_renamed(self, routine: _Routine, old: str, new: str) -> None:
        """Rewrite an input whose entity id changed, and reload (PRD 3.1)."""
        settings = routine.settings
        if settings is not None and settings.target_entity == old:
            routine.settings = replace(settings, target_entity=new)
            routine.missing_target = False
        record = self._store.data.owned.get(routine.automation_id)
        if record is not None and record.last_valid_inputs is not None:
            inputs = {
                key: new if value == old else value
                for key, value in record.last_valid_inputs.items()
            }
            self._store.data.owned[routine.automation_id] = replace(
                record, last_valid_inputs=inputs
            )
        await self._async_write(routine)

    async def _async_check_target(self, routine: _Routine) -> None:
        """Turn the routine off while its target is missing, back on when it returns."""
        assert routine.settings is not None  # noqa: S101  # callers pass routines with settings
        exists = self._exists(routine.settings.target_entity)
        if not exists and not routine.missing_target:
            routine.missing_target = True
            await self._async_suspend(routine, _OFF_MISSING_TARGET)
            self._changed(routine.device_id)
        elif exists and routine.missing_target:
            routine.missing_target = False
            await self._async_unsuspend(routine, _OFF_MISSING_TARGET)
            self._changed(routine.device_id)

    @callback
    def _action_skipped(self, event: Event[Any]) -> None:
        """Re emit the blueprint's skipped action event to the listeners."""
        device_id = event.data.get("device_id")
        if device_id in self._routines:
            self._notify(
                ManagerEvent("routine_changed", device_id, REASON_ACTION_SKIPPED, dict(event.data))
            )
            self.summary.async_refresh_device(device_id)

    @callback
    def _automation_filter(self, event_data: Mapping[str, Any]) -> bool:
        entity_id: str = event_data["entity_id"]
        if not entity_id.startswith("automation."):
            return False
        old: State | None = event_data.get("old_state")
        new: State | None = event_data.get("new_state")
        if old is not None and new is not None and old.state == new.state:
            return False
        entry = er.async_get(self.hass).async_get(entity_id)
        return entry is not None and self._device_of_automation(entry.unique_id) is not None

    @callback
    def _automation_changed(self, event: Event[Any]) -> None:
        """Follow the automation's on and off state: the Routine switch (PRD 8.2)."""
        entry = er.async_get(self.hass).async_get(event.data["entity_id"])
        assert entry is not None  # noqa: S101  # the filter checked
        device_id = self._device_of_automation(entry.unique_id)
        assert device_id is not None  # noqa: S101  # the filter checked
        self._changed(device_id)

    # ----------------------------------------------------------------------------------
    # Reconcile (TECH_SPEC 7) and self healing (PRD 3.1)
    # ----------------------------------------------------------------------------------

    async def async_reconcile(self) -> None:
        """Run the TECH_SPEC 7 checklist; idempotent, at setup and from maintenance."""
        self._adapter = ha_adapter.check(self.hass)
        repairs.async_sync_adapter_issue(self.hass, self._adapter)
        self._last_reconcile = dt_util.utcnow()
        if not self._adapter.ok:
            self._notify(ManagerEvent("health_changed", None))
            return
        if await self.async_ensure_blueprint():
            await self._async_migrate()
        label_was_missing = lr.async_get(self.hass).async_get_label(self._label_id) is None
        self._label()
        self._category()
        if await self._async_sync_all():
            for automation_id in list(self._store.data.owned):
                routine = self._routines[self._store.data.owned[automation_id].device_id]
                await self._async_heal(routine)
        await self._async_reconcile_devices(label_was_missing=label_was_missing)
        await self.async_cleanup()
        for device_id in list(self._routines):
            self.summary.async_refresh_device(device_id)
        self._notify(ManagerEvent("schedule_changed", None))
        self._notify(ManagerEvent("health_changed", None))

    async def _async_heal(self, routine: _Routine) -> None:
        """TECH_SPEC 7 step 5 for one owned automation; an invalid one is never rewritten."""
        if routine.invalid:
            return
        await self._async_check_target(routine)
        await self._async_check_helpers(routine)
        await self._async_check_loaded(routine)
        await self._async_follow_name(routine)
        self._follow_area(routine)

    async def _async_check_helpers(self, routine: _Routine) -> None:
        """Recreate a missing timer or schedule with the same entity id (PRD 3.1)."""
        record = self._store.data.owned[routine.automation_id]
        refs = _refs(record.last_valid_inputs) or compiler.HelperRefs(routine.device_id)
        if refs.timer_entity != compiler.UNUSED_TIMER and not self._exists(refs.timer_entity):
            await self._async_create_helper(routine, "timer", refs.timer_entity)
        schedule = refs.schedule_entity
        if schedule != compiler.UNUSED_SCHEDULE and not self._exists(schedule):
            await self._async_create_helper(routine, "schedule", schedule)
            self._sync_issue(
                repairs.SCHEDULE_BLOCKS_NEEDED, routine, present=True, schedule=schedule
            )

    async def _async_check_loaded(self, routine: _Routine) -> None:
        """Regenerate an owned automation that does not load once, then report it."""
        automation_id = routine.automation_id
        if routine.migration_failed:
            return
        if not self._loaded(automation_id) and not routine.regenerated:
            routine.regenerated = True
            record = self._store.data.owned[automation_id]
            routine.settings = _settings(record.last_valid_inputs) or routine.settings
            await self._async_write(routine)
        loaded = self._loaded(automation_id)
        if loaded:
            routine.regenerated = False
        if loaded is routine.load_failed:
            routine.load_failed = not loaded
            self._sync_issue(repairs.AUTOMATION_LOAD_FAILED, routine, present=not loaded)
            self._changed(routine.device_id)

    async def _async_reconcile_devices(self, *, label_was_missing: bool) -> None:
        """TECH_SPEC 7 step 6: the label and the opted in set agree, devices still exist.

        A label missing from the registry was deleted, which opts nobody out: it was
        recreated, and is applied again from `opted_in` (plan Section 4.9).
        """
        data = self._store.data
        if label_was_missing:
            self._repair_label()
        labelled = self._labelled_devices()
        for device_id in sorted(labelled - data.opted_in):
            if self.candidates(device_id):
                await self.async_opt_in(device_id, SOURCE_LABEL)
        for device_id in sorted(data.opted_in - labelled):
            if self._device(device_id) is not None:
                await self.async_opt_out(device_id, SOURCE_LABEL)
            elif device_id not in data.removed_devices_at:
                self._routine(device_id)
                await self._async_device_removed(device_id, {})
        for device_id in sorted(data.opted_in):
            if self._device(device_id) is not None:
                self._routine(device_id)
                self._ensure_entities(device_id)

    # ----------------------------------------------------------------------------------
    # Cleanup (D28) and the maintenance side (maintenance.MaintenanceTarget)
    # ----------------------------------------------------------------------------------

    async def async_cleanup(self, *, dry_run: bool = False) -> builtins.list[str]:
        """Delete routines whose cleanup period passed (D28); return the device ids."""
        due = maintenance.due_for_cleanup(
            self._store.data, dt_util.utcnow(), self.settings.cleanup_after_days
        )
        if dry_run:
            return due
        cleaned = await maintenance.async_clean_up(self, due) if due else []
        self._schedule_cleanup()
        return cleaned

    def _schedule_cleanup(self) -> None:
        """One point in time listener at the next due cleanup, never an interval."""
        self._cancel_cleanup()
        due = maintenance.next_cleanup_at(self._store.data, self.settings.cleanup_after_days)
        if due is None or self._stopping:
            return

        @callback
        def run(_now: datetime) -> None:
            self._cleanup_handle = None
            self.entry.async_create_task(self.hass, self.async_cleanup(), f"{DOMAIN} cleanup")

        self._cleanup_handle = async_track_point_in_utc_time(self.hass, run, due)

    def _cancel_cleanup(self) -> None:
        if self._cleanup_handle is not None:
            self._cleanup_handle()
            self._cleanup_handle = None

    async def async_delete_routine(self, device_id: str) -> None:
        """Delete the device's automation, helpers and entities; the caller drops the Store."""
        for automation_id, record in list(self._store.data.owned.items()):
            if record.device_id != device_id:
                continue
            await ha_adapter.async_delete_automation(self.hass, automation_id)
            await self._async_delete_helpers(
                _refs(record.last_valid_inputs) or compiler.HelperRefs(device_id)
            )
        self._remove_entities(device_id)
        if (routine := self._routines.pop(device_id, None)) is not None:
            self._clear_runtime(routine)
            routine.settings = None
            self._watch(routine)
        self._changed(device_id)

    async def async_rebuild_index(self, *, dry_run: bool) -> builtins.list[str]:
        """Rebuild `owned`, `opted_in` and `blueprint_hash` from the markers (TECH_SPEC 6)."""
        data = self._store.data
        owned: dict[str, OwnedRecord] = {}
        for entry in await ha_adapter.async_read_automations(self.hass):
            if not markers.is_owned(entry):
                continue
            inputs = entry["use_blueprint"].get("input")
            device_id = _input(inputs, "device_id")
            if device_id is None:
                continue
            kept = data.owned.get(entry["id"])
            owned[entry["id"]] = (
                kept
                if kept is not None and kept.device_id == device_id
                else OwnedRecord(
                    device_id,
                    str(_input(inputs, "target_entity") or ""),
                    last_hash=markers.config_hash(entry) if _refs(inputs) else None,
                    last_valid_inputs=dict(inputs) if _refs(inputs) else None,
                )
            )
        changed = sorted(
            key for key in owned.keys() | data.owned.keys() if owned.get(key) != data.owned.get(key)
        )
        if dry_run:
            return changed
        if lr.async_get(self.hass).async_get_label(self._label_id) is not None:
            data.opted_in = self._labelled_devices()
        installed = await self.hass.async_add_executor_job(
            ha_adapter.installed_blueprint_text, self.hass
        )
        data.blueprint_hash = None if installed is None else maintenance.blueprint_hash(installed)
        data.owned = owned
        await self._store.async_save()
        self._load_routines()
        await self._async_sync_all()
        for device_id in list(self._routines):
            self._changed(device_id)
        return changed

    async def async_refresh_summaries(self, *, dry_run: bool) -> builtins.list[str]:
        """Recompute every routine device's Schedule summary; return the device ids."""
        devices = sorted(self._routines)
        if not dry_run:
            for device_id in devices:
                self._changed(device_id)
            self._notify(ManagerEvent("schedule_changed", None))
        return devices


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------


def _invalid(key: str, placeholders: Mapping[str, str] | None = None) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=dict(placeholders or {}),
    )


def _platform_of(key: str) -> str:
    """Return the platform of the two page entities the blueprint reads."""
    return "switch" if key == KEY_MANUAL_OVERRIDE else "datetime"


def _refs(inputs: Mapping[str, Any] | None) -> compiler.HelperRefs | None:
    return compiler.refs_of(inputs) if compiler.is_valid_shape(inputs) and inputs else None


def _settings(inputs: Mapping[str, Any] | None) -> RoutineSettings | None:
    return compiler.decompile(inputs) if compiler.is_valid_shape(inputs) and inputs else None


def _input(inputs: Any, key: str) -> str | None:
    value = inputs.get(key) if isinstance(inputs, Mapping) else None
    return value if isinstance(value, str) else None


def _ids(value: Any) -> Iterable[str]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _moment(value: Any) -> datetime | None:
    if isinstance(value, str):
        value = dt_util.parse_datetime(value)
    return value if isinstance(value, datetime) else None


def _name_from(template: str, alias: str | None) -> str | None:
    """Read the device name back out of a generated alias, or None."""
    prefix, _, suffix = template.partition("{device}")
    if alias is None or not alias.startswith(prefix) or not alias.endswith(suffix):
        return None
    return alias[len(prefix) : len(alias) - len(suffix)] or None


def _is_window_end(settings: RoutineSettings, target: nextrun.SkipTarget) -> bool:
    """Tell whether Skip next skips the end of a window or a weekly schedule block."""
    window = (
        settings.on_time is not None and settings.off_time is not None
    ) or settings.days is Days.WEEKLY_SCHEDULE
    return (
        window
        and target.paired_end is None
        and target.verb is routine_verbs(settings.target_entity)[1]
    )
