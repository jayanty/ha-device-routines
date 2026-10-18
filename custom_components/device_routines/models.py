"""Plain data shared by the pure modules (TECH_SPEC 3.1).

Everything here is a frozen dataclass or a string enum, so values can be compared, hashed
and stored without surprises. Nothing imports Home Assistant.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Any


class Days(StrEnum):
    """Which days a routine's scheduled times apply to."""

    EVERY_DAY = "every_day"
    WEEKDAYS = "weekdays"
    WEEKENDS = "weekends"
    SOME_DAYS = "some_days"
    WEEKLY_SCHEDULE = "weekly_schedule"


class Weekday(StrEnum):
    """A day of the week, spelled the way Home Assistant's time condition spells it."""

    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"

    @property
    def number(self) -> int:
        """Monday is 0, as in `datetime.weekday()`."""
        return list(Weekday).index(self)

    @classmethod
    def of(cls, moment: datetime) -> Weekday:
        """Return the weekday of a local datetime."""
        return list(cls)[moment.weekday()]

    @property
    def following(self) -> Weekday:
        """The next day of the week; Sunday is followed by Monday."""
        return list(Weekday)[(self.number + 1) % 7]


ALL_DAYS: frozenset[Weekday] = frozenset(Weekday)
WEEKDAYS: frozenset[Weekday] = frozenset(
    {Weekday.MON, Weekday.TUE, Weekday.WED, Weekday.THU, Weekday.FRI}
)
WEEKEND: frozenset[Weekday] = frozenset({Weekday.SAT, Weekday.SUN})


class Status(StrEnum):
    """What a routine is doing now."""

    ACTIVE = "active"
    PAUSED = "paused"
    SKIPPING = "skipping"
    OFF = "off"
    DETACHED = "detached"
    MISSING_TARGET = "missing_target"
    INVALID = "invalid"


class Source(StrEnum):
    """Who changed a device last (TECH_SPEC 4.3)."""

    AUTOMATION = "automation"
    USER = "user"
    DEVICE = "device"


class Option(StrEnum):
    """A routine option a domain may support (PRD 5.3)."""

    ON_TIME = "on_time"
    OFF_TIME = "off_time"
    DAYS = "days"
    TURN_OFF_AFTER = "turn_off_after"
    TURN_BACK_ON_AFTER = "turn_back_on_after"
    PULSE = "pulse"


class Verb(StrEnum):
    """What an action does to a device, independent of the domain's service names."""

    ON = "on"
    OFF = "off"
    TOGGLE = "toggle"
    START = "start"
    DOCK = "dock"
    PAUSE = "pause"
    STOP = "stop"
    OPEN = "open"
    CLOSE = "close"
    LOCK = "lock"
    UNLOCK = "unlock"


# Verbs that undo each other, for conflict detection and expected states.
OPPOSITES: Mapping[Verb, Verb] = {
    Verb.ON: Verb.OFF,
    Verb.OFF: Verb.ON,
    Verb.START: Verb.DOCK,
    Verb.DOCK: Verb.START,
    Verb.OPEN: Verb.CLOSE,
    Verb.CLOSE: Verb.OPEN,
    Verb.LOCK: Verb.UNLOCK,
    Verb.UNLOCK: Verb.LOCK,
}

# Verbs that make a device active (on, running, open, unlocked) and the ones that make it
# inactive, so an action can be compared with a routine's expected state.
ACTIVATING: frozenset[Verb] = frozenset({Verb.ON, Verb.START, Verb.OPEN, Verb.UNLOCK})
DEACTIVATING: frozenset[Verb] = frozenset({Verb.OFF, Verb.DOCK, Verb.CLOSE, Verb.LOCK})


@dataclass(frozen=True, slots=True)
class Problem:
    """A translated reason something is not valid."""

    key: str
    translation_key: str
    placeholders: Mapping[str, str] = field(default_factory=dict)


class TranslatedError(ValueError):
    """Base for the errors the pure modules raise, carrying a translation key."""

    def __init__(self, translation_key: str, placeholders: Mapping[str, str] | None = None) -> None:
        super().__init__(translation_key)
        self.translation_key = translation_key
        self.placeholders: Mapping[str, str] = dict(placeholders or {})


class CompileError(TranslatedError):
    """Raised by the compiler for settings that cannot become blueprint inputs."""


class ParseError(TranslatedError):
    """Raised by the parser for input that is not an automation config at all."""


# --------------------------------------------------------------------------------------
# Routines (written by the compiler in Phase 2; read by nextrun and conflicts already)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Pulse:
    """FR-R8: at a time, the opposite state for some minutes, then back."""

    at: time
    minutes: int = 3
    min_steady_min: int = 5


@dataclass(frozen=True, slots=True)
class RoutineSettings:
    """Every setting of one routine, the inverse image of the blueprint inputs."""

    target_entity: str
    on_time: time | None = None
    off_time: time | None = None
    days: Days = Days.EVERY_DAY
    day_set: frozenset[Weekday] = ALL_DAYS
    schedule_entity: str | None = None
    turn_off_after_min: int = 0
    turn_back_on_after_min: int = 0
    catch_up: bool = True
    late_start_window_min: int = 15
    respect_manual: bool = True
    pulse: Pulse | None = None
    extra_conditions: tuple[Mapping[str, Any], ...] = ()
    docked_guard: bool = True

    @property
    def effective_days(self) -> frozenset[Weekday]:
        """The day set the scheduled times apply to."""
        if self.days is Days.WEEKDAYS:
            return WEEKDAYS
        if self.days is Days.WEEKENDS:
            return WEEKEND
        if self.days is Days.SOME_DAYS:
            return self.day_set
        return ALL_DAYS

    @property
    def crosses_midnight(self) -> bool:
        """True when the window ends the day after it starts: on at 17:00, off at 09:00."""
        return (
            self.on_time is not None and self.off_time is not None and self.off_time < self.on_time
        )

    @property
    def end_days(self) -> frozenset[Weekday]:
        """The days the off time runs on: a window belongs to the weekday it starts on.

        Across midnight these are the start days shifted by one; otherwise the same days.
        """
        if not self.crosses_midnight:
            return self.effective_days
        return frozenset(day.following for day in self.effective_days)


@dataclass(frozen=True, slots=True)
class DomainProfile:
    """What a routine can do with one domain (PRD 5.3)."""

    domain: str
    on_action: str | None
    off_action: str
    inactive_state: str
    on_label_key: str | None
    off_label_key: str
    options: frozenset[Option]
    refused_device_classes: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class CompiledInputs:
    """The exact blueprint input dict, keys in a fixed order."""

    inputs: Mapping[str, Any]


# --------------------------------------------------------------------------------------
# What the parser understands of an automation (TECH_SPEC 3.5)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TimeTrigger:
    """A `time` trigger at a fixed time, or at the time an entity holds."""

    at: time | None = None
    entity: str | None = None
    offset: timedelta = timedelta(0)
    weekdays: frozenset[Weekday] | None = None


@dataclass(frozen=True, slots=True)
class PatternTrigger:
    """A `time_pattern` trigger; each field is `*`, a number, or `/N`."""

    hours: str = "*"
    minutes: str = "*"
    seconds: str = "0"


@dataclass(frozen=True, slots=True)
class SunTrigger:
    """A `sun` trigger at sunrise or sunset with an offset."""

    event: str
    offset: timedelta = timedelta(0)


@dataclass(frozen=True, slots=True)
class StateTrigger:
    """A `state` trigger, or a device trigger that means the same thing."""

    entity: str
    to: str | None = None
    from_state: str | None = None
    duration: timedelta | None = None


@dataclass(frozen=True, slots=True)
class NumericTrigger:
    """A `numeric_state` trigger with fixed bounds."""

    entity: str
    above: float | None = None
    below: float | None = None
    duration: timedelta | None = None


@dataclass(frozen=True, slots=True)
class StartTrigger:
    """A `homeassistant` trigger: `start` or `shutdown`."""

    event: str


@dataclass(frozen=True, slots=True)
class CalendarTrigger:
    """A `calendar` trigger at the start or end of events."""

    entity: str
    event: str
    offset: timedelta = timedelta(0)


@dataclass(frozen=True, slots=True)
class NamedTrigger:
    """A purpose specific trigger the grammar lists, such as `timer.finished`.

    `values` holds what a trigger that waits for one of several values names, such as the
    event types of `event.received`; empty for the others.
    """

    name: str
    entities: tuple[str, ...] = ()
    values: tuple[str, ...] = ()


type Trigger = (
    TimeTrigger
    | PatternTrigger
    | SunTrigger
    | StateTrigger
    | NumericTrigger
    | StartTrigger
    | CalendarTrigger
    | NamedTrigger
)

# Triggers with a computable next run (FR-S3); the others are event driven.
TIMED_TRIGGERS = (TimeTrigger, PatternTrigger, SunTrigger)


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """A time condition's after and before bounds (fixed times or entity ids)."""

    after: time | str | None = None
    before: time | str | None = None


@dataclass(frozen=True, slots=True)
class FollowUp:
    """An action on the same device after a fixed delay: off for 3 min, then on."""

    delay: timedelta
    verb: Verb


@dataclass(frozen=True, slots=True)
class ParsedLine:
    """One action on one device, with what the parser understood of when it runs.

    `understood` is false when nothing about the action could be read, which renders as
    the single custom logic line. `custom_logic` is true when some construct on the way to
    the action is outside the grammar, which appends "plus custom logic".
    """

    automation_id: str
    alias: str
    entity_ids: tuple[str, ...]
    verb: Verb | None
    triggers: tuple[Trigger, ...] = ()
    weekdays: frozenset[Weekday] | None = None
    windows: tuple[TimeWindow, ...] = ()
    condition_count: int = 0
    follow_ups: tuple[FollowUp, ...] = ()
    custom_logic: bool = False
    understood: bool = True
    enabled: bool = True

    @property
    def timed(self) -> bool:
        """True when at least one trigger has a computable next run."""
        return any(isinstance(trigger, TIMED_TRIGGERS) for trigger in self.triggers)


@dataclass(frozen=True, slots=True)
class EntityRef:
    """One entity of a device, with the effective area, floor and labels it inherits."""

    entity_id: str
    name: str = ""
    area_id: str | None = None
    floor_id: str | None = None
    labels: frozenset[str] = frozenset()
    registry_id: str | None = None

    @property
    def domain(self) -> str:
        """The domain part of the entity id."""
        return self.entity_id.split(".", 1)[0]


@dataclass(frozen=True, slots=True)
class DeviceContext:
    """What the parser needs to know about the device it summarizes for.

    `registry_ids` maps entity registry ids to entity ids for the whole instance, because
    device triggers, conditions and actions name entities by registry id (TECH_SPEC 4.2).
    `names` maps entity ids to friendly names for the sentences.
    """

    device_id: str
    entities: tuple[EntityRef, ...]
    registry_ids: Mapping[str, str] = field(default_factory=dict)
    names: Mapping[str, str] = field(default_factory=dict)

    @property
    def entity_ids(self) -> frozenset[str]:
        """Every entity id of the device."""
        return frozenset(entity.entity_id for entity in self.entities)


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One future run of a timed line."""

    at: datetime
    verb: Verb | None


@dataclass(frozen=True, slots=True)
class SummaryItem:
    """One entry of the Schedule sensor's `items` attribute (PRD FR-S4)."""

    kind: str
    automation_entity: str
    alias: str
    summary: str
    next_run: datetime | None
    source: str
    enabled: bool
    custom_logic: bool
    parts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Conflict:
    """Two items that drive the same entity in opposite directions."""

    a: int
    b: int
    reason_key: str
    at: datetime | None


# --------------------------------------------------------------------------------------
# A routine as the platforms, actions and console see it (TECH_SPEC 4.1)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoutineView:
    """A snapshot of one routine, built by the manager and read by every surface.

    `skipped_action` is what Skip next skipped while the routine is skipping; `next_action`
    is the next action that will really run, after any pause.
    """

    device_id: str
    device_name: str
    area_id: str | None
    automation_id: str
    automation_entity_id: str | None
    settings: RoutineSettings
    status: Status
    enabled: bool
    paused_until: datetime | None
    skipped_action: Occurrence | None
    next_action: Occurrence | None
    sentence: str | None
    items: tuple[SummaryItem, ...]
    conflicts: tuple[Conflict, ...]
    override: bool
    last_change_source: Source | None
