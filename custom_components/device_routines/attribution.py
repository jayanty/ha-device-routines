"""The manual change attributor (TECH_SPEC 4.3, PRD 9.3, decision D26).

Contexts alone cannot say whether a change was manual: a run started by a time, sun,
timer or start trigger has a parentless, userless context, exactly like a wall switch
(Stage 0 V3). The attributor therefore keeps a bounded map of the contexts automation and
script runs use, filled from `automation_triggered` and `script_started`, and classifies
each state change of a watched entity by its context:

- `AUTOMATION` when the context id or its parent id is in the map;
- `USER` when the context carries a user id (app, dashboard, voice assistant);
- `DEVICE` otherwise (wall switch, physical button, the device's own timer).

`USER` and `DEVICE` are manual. On a manual change of a routine that is active, not paused
and respects manual changes, and whose window expects a state now, the new state reads as
off when it equals the domain's inactive state and as on otherwise: different from the
expectation sets the Manual override, equal clears it. Every other classified change only
records its source. The attributor never acts on a device; the manager behind the
`OverrideSink` owns the switch.

What counts as a change: a new state value between two available states. Attribute
updates, an entity appearing or going away, and every transition to or from `unknown` or
`unavailable` are no one's change, so they are neither classified nor reported. A device
coming back is catch up's business (PRD FR-R5), and an override set by its return would
suppress exactly that catch up.

Startup grace: set up while Home Assistant boots, the attributor only fills the map until
30 seconds after the started event, while integrations settle and report their devices.
Set up in a running instance (an install or a reload), devices are settled already and
there is no grace.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any, Final, Literal, Protocol

from homeassistant.const import (
    ATTR_ENTITY_ID,
    EVENT_HOMEASSISTANT_STARTED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    CoreState,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .models import Source

_LOGGER = logging.getLogger(__name__)

MAP_LIMIT: Final = 10_000
MAP_TTL: Final = timedelta(hours=24)
STARTUP_GRACE: Final = timedelta(seconds=30)

# The run events of the automation and script components. Only the adapter may import
# those components; a test pins these names to theirs.
EVENT_AUTOMATION_TRIGGERED: Final = "automation_triggered"
EVENT_SCRIPT_STARTED: Final = "script_started"

_NOT_AVAILABLE: Final = frozenset({STATE_UNKNOWN, STATE_UNAVAILABLE})


@dataclass(frozen=True, slots=True)
class RoutineRuntime:
    """What the attributor needs to know about a routine when its target changes.

    `expected` is the window's expectation now (`nextrun.expected_state`), None when the
    routine has no window. A state equal to `inactive_state` reads as off, any other
    available state as on, so vacuums, covers, locks and climates compare like switches.
    """

    device_id: str
    active: bool
    paused: bool
    respect_manual: bool
    expected: Literal["on", "off"] | None
    inactive_state: str


class RoutineLookup(Protocol):
    """Finds the routine that drives an entity (the manager implements it)."""

    def routine_for(self, entity_id: str) -> RoutineRuntime | None:
        """Return the runtime facts of the routine targeting `entity_id`, or None."""


class OverrideSink(Protocol):
    """Receives every classified change of a watched entity (the manager implements it)."""

    async def async_set_override(
        self, device_id: str, on: bool | None, source: Source, new_state: str
    ) -> None:
        """Set (True) or clear (False) the override, or only record the source (None)."""


@dataclass(frozen=True, slots=True)
class _Run:
    """When a run context was last seen, and the automation or script it belongs to."""

    seen: datetime
    entity_id: str | None


def _override_for(routine: RoutineRuntime, source: Source, new_state: str) -> bool | None:
    """Return True to set the override, False to clear it, None to leave it as it is."""
    if (
        source is Source.AUTOMATION
        or not routine.active
        or routine.paused
        or not routine.respect_manual
        or routine.expected is None
    ):
        return None
    reading = "off" if new_state == routine.inactive_state else "on"
    return reading != routine.expected


class Attributor:
    """Tells automation, user and device changes apart and reports them to the sink."""

    def __init__(self, hass: HomeAssistant, lookup: RoutineLookup, sink: OverrideSink) -> None:
        self.hass = hass
        self._lookup = lookup
        self._sink = sink
        self._runs: OrderedDict[str, _Run] = OrderedDict()
        self._watched: set[str] = set()
        self._trackers: dict[str, CALLBACK_TYPE] = {}
        self._unsubscribe: list[CALLBACK_TYPE] = []
        self._unsubscribe_started: CALLBACK_TYPE | None = None
        self._running = False
        self._booting = False
        self._grace_ends: datetime | None = None

    # ----------------------------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------------------------

    async def async_start(self) -> None:
        """Listen to runs and to the watched entities; a second call does nothing."""
        if self._running:
            return
        self._running = True
        bus = self.hass.bus
        self._unsubscribe = [
            bus.async_listen(EVENT_AUTOMATION_TRIGGERED, self._record_run),
            bus.async_listen(EVENT_SCRIPT_STARTED, self._record_run),
        ]
        if self.hass.state is not CoreState.running:
            self._booting = True
            self._unsubscribe_started = bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._started
            )
        for entity_id in self._watched:
            self._track(entity_id)

    @callback
    def async_stop(self) -> None:
        """Drop every listener and the run map; the watched entities are kept."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        if self._unsubscribe_started is not None:
            self._unsubscribe_started()
            self._unsubscribe_started = None
        for remove in self._trackers.values():
            remove()
        self._trackers.clear()
        self._runs.clear()
        self._running = False
        self._booting = False
        self._grace_ends = None

    @callback
    def watch(self, entity_id: str) -> None:
        """Classify the changes of `entity_id` from now on (or from the start)."""
        if entity_id in self._watched:
            return
        self._watched.add(entity_id)
        if self._running:
            self._track(entity_id)

    @callback
    def unwatch(self, entity_id: str) -> None:
        """Stop classifying the changes of `entity_id`."""
        self._watched.discard(entity_id)
        if (remove := self._trackers.pop(entity_id, None)) is not None:
            remove()

    # ----------------------------------------------------------------------------------
    # Classification
    # ----------------------------------------------------------------------------------

    @callback
    def classify(self, context: Context) -> Source:
        """Return who made the change that carries `context`."""
        source, _origin = self._attribute(context)
        return source

    @callback
    def _attribute(self, context: Context) -> tuple[Source, str | None]:
        """Return the source and, for a run, the automation or script it came from."""
        self._expire(dt_util.utcnow())
        run = self._runs.get(context.id)
        if run is None and context.parent_id is not None:
            run = self._runs.get(context.parent_id)
        if run is not None:
            return Source.AUTOMATION, run.entity_id
        if context.user_id is not None:
            return Source.USER, None
        return Source.DEVICE, None

    @callback
    def _expire(self, now: datetime) -> None:
        """Drop the runs older than the TTL; the oldest are first in the map."""
        horizon = now - MAP_TTL
        runs = self._runs
        while runs and next(iter(runs.values())).seen <= horizon:
            runs.popitem(last=False)

    # ----------------------------------------------------------------------------------
    # Event plumbing
    # ----------------------------------------------------------------------------------

    @callback
    def _record_run(self, event: Event[Any]) -> None:
        """Remember the context a run's actions use, newest last, at most MAP_LIMIT."""
        now = dt_util.utcnow()
        self._expire(now)
        runs = self._runs
        runs[event.context.id] = _Run(now, event.data.get(ATTR_ENTITY_ID))
        runs.move_to_end(event.context.id)
        if len(runs) > MAP_LIMIT:
            runs.popitem(last=False)

    @callback
    def _started(self, _event: Event[Any]) -> None:
        self._unsubscribe_started = None
        self._booting = False
        self._grace_ends = dt_util.utcnow() + STARTUP_GRACE

    def _in_grace(self) -> bool:
        if self._booting:
            return True
        return self._grace_ends is not None and dt_util.utcnow() < self._grace_ends

    @callback
    def _track(self, entity_id: str) -> None:
        self._trackers[entity_id] = async_track_state_change_event(
            self.hass, entity_id, self._state_changed
        )

    @callback
    def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Classify a change of a watched entity and report it, in event order."""
        if self._in_grace():
            return
        old = event.data["old_state"]
        new = event.data["new_state"]
        if (
            old is None
            or new is None
            or old.state == new.state
            or old.state in _NOT_AVAILABLE
            or new.state in _NOT_AVAILABLE
        ):
            return
        routine = self._lookup.routine_for(new.entity_id)
        if routine is None:
            return
        source, origin = self._attribute(event.context)
        on = _override_for(routine, source, new.state)
        _LOGGER.debug(
            "%s changed to %s by %s%s, override %s",
            new.entity_id,
            new.state,
            source,
            f" ({origin})" if origin else "",
            {True: "set", False: "cleared", None: "unchanged"}[on],
        )
        # Eager start: the sink is called now, so calls keep the order of the changes.
        self.hass.async_create_task(
            self._sink.async_set_override(routine.device_id, on, source, new.state),
            name=f"device_routines attribution {new.entity_id}",
        )
