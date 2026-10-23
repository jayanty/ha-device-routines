"""Routine settings to blueprint inputs and back (TECH_SPEC 3.3 and 5.2).

`compile` writes the exact input mapping of the blueprint: the 39 keys of input schema 3
(plan Section 6.2.1, decision L83) in the blueprint's file order (`INPUT_KEYS`), the derived inputs
included, as plain YAML types
(times as `HH:MM:SS`, sun offsets as `[-]HH:MM:SS` text with whole minutes, kinds as
`time`, `sunrise` or `sunset`, days as lists of weekday values from Monday to Sunday,
minutes as `int`, flags as `bool`, entity ids and action names as `str`, conditions as a
list of mappings). `decompile` reads it back. The blueprint form is the second editor, so
`decompile` reads only the primary inputs and never the derived ones (`days_end`,
`crosses_midnight`, `late_window_end`, the four sun flags, `late_sun_offset`,
`timer_enabled`) or the
profile's (`on_action`, `off_action`, `inactive_state`): a form edit of a primary input
reads correctly, and the next write repairs the rest.

Sun bounds (FR-R10, decision L60). Each side is a kind and, for a time, `on_time` behind
`on_time_enabled`, or for sunrise or sunset an offset in whole minutes; the off side
alike. The four sun flags enable the blueprint's sun triggers, and `late_sun_offset` (the
on offset plus the late start window) ends a sun start's late window. Every schema 2 input
defaults to schema 1 behavior, so schema 1 inputs read here exactly as schema 1 read them.

Round trips. The inputs carry no `days` value, only the day set, so settings have a
canonical form (`canonical`): a day set with a name reads as that name (Monday to Friday
as Weekdays), `day_set` is the full week unless `days` is Some days, `schedule_entity` is
kept only for a weekly schedule, times have whole seconds and no zone, a time bound has
offset 0 and a sun bound no time. For every `s` that `validate` accepts,
`decompile(compile(s)) == canonical(s)`; for every `i` that `compile` produced,
`compile(decompile(i), profile, refs_of(i)) == i`.

Helpers. An input that names a helper holds the sentinel while its feature is off: the
timer without a duration, the schedule without Weekly schedule. A step that names a
sentinel never runs: `schedule_enabled` switches the schedule's steps and, since schema 3,
`timer_enabled` the timer's, off exactly when the timer input holds its sentinel (live
finding F8, decision L83). The override switch and the Paused until entity belong to every
routine and always come from `HelperRefs`.

Refusals (PRD 5.4) are data in `domains`: a profile for a refused device class has no
activating action. A profile without one writes its deactivating action into `on_action`
as well, so the input is still a valid action name and no branch can weaken safety with
it. `validate` also rejects a profile that carries a refused action, and
`has_refused_action` checks raw inputs on sync back.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import time
import re
from typing import Any, Final

from . import markers
from .domains import is_refused_action
from .models import (
    ALL_DAYS,
    WEEKDAYS,
    WEEKEND,
    CompiledInputs,
    CompileError,
    Days,
    DomainProfile,
    Option,
    Problem,
    Pulse,
    RoutineSettings,
    TimeKind,
    Weekday,
)

BLUEPRINT_SCHEMA_VERSION: Final = 3
# Defined in `markers` (decision L34) and re-exported here: the same object.
BLUEPRINT_PATH: Final = markers.BLUEPRINT_PATH

EVENT_ACTION_SKIPPED: Final = "device_routines_action_skipped"
EVENT_TIMER_CAUGHT_UP: Final = "device_routines_timer_caught_up"

# Sentinel entities never exist, so a trigger on one never fires (TECH_SPEC 5.2).
UNUSED_TIMER: Final = "timer.device_routines_unused"
UNUSED_SCHEDULE: Final = "schedule.device_routines_unused"
UNUSED_SWITCH: Final = "switch.device_routines_unused"
UNUSED_DATETIME: Final = "datetime.device_routines_unused"
# A disabled time trigger still needs a valid time.
UNUSED_TIME: Final = "00:00:00"

MAX_DURATION_MIN: Final = 1440
# The same bound as the global default late start window (settings.RANGES).
MAX_LATE_START_MIN: Final = 180
# A sun offset keeps a nominal sun time plus its offset inside one day (decision L60).
MAX_SUN_OFFSET_MIN: Final = 180

# The blueprint's inputs in file order, which is the order the core flattens the form's
# sections in (owner decision O3, decision L74): Target holds the device and, marked as set
# by Device Routines, the four inputs without a default (the core's form keeps a section
# with one open); then the inputs `decompile` reads, which a person may change in the
# form (Schedule, Timers, Behavior, Advanced); then the 12 other inputs Device Routines
# sets itself and `decompile` never reads, in the collapsed last section. The order is
# layout only: inputs are stored flat, and `decompile` reads them in any order.
INPUT_KEYS: Final[tuple[str, ...]] = (
    "target_entity",
    "on_action",
    "off_action",
    "inactive_state",
    "device_id",
    "on_time_enabled",
    "on_time",
    "on_kind",
    "on_sun_offset",
    "off_time_enabled",
    "off_time",
    "off_kind",
    "off_sun_offset",
    "days_start",
    "schedule_enabled",
    "schedule_entity",
    "turn_off_after_min",
    "turn_back_on_after_min",
    "catch_up",
    "late_start_window_min",
    "respect_manual",
    "pulse_enabled",
    "pulse_at",
    "pulse_minutes",
    "pulse_min_steady_min",
    "docked_guard",
    "extra_conditions",
    "on_at_sunrise",
    "on_at_sunset",
    "off_at_sunrise",
    "off_at_sunset",
    "days_end",
    "crosses_midnight",
    "timer_enabled",
    "timer_entity",
    "late_window_end",
    "late_sun_offset",
    "override_entity",
    "paused_until_entity",
)

# Inputs without a default in the blueprint; a form edit may omit every other one.
REQUIRED_KEYS: Final = frozenset(
    {"target_entity", "on_action", "off_action", "inactive_state", "device_id"}
)

_ALL_DAY_VALUES: Final = [day.value for day in Weekday]

# The blueprint's defaults (TECH_SPEC 5.2, plan 6.2.1), which `decompile` assumes for
# omitted inputs. The schema 2 ones reproduce schema 1 behavior: time bounds, no sun
# trigger, the late window of a time start; the schema 3 one reproduces schema 2's: the
# timer's steps on. Read only: the lists are shared.
INPUT_DEFAULTS: Final[Mapping[str, Any]] = {
    "on_time_enabled": False,
    "on_time": UNUSED_TIME,
    "on_kind": TimeKind.TIME.value,
    "on_sun_offset": "00:00:00",
    "off_time_enabled": False,
    "off_time": UNUSED_TIME,
    "off_kind": TimeKind.TIME.value,
    "off_sun_offset": "00:00:00",
    "days_start": _ALL_DAY_VALUES,
    "schedule_enabled": False,
    "schedule_entity": UNUSED_SCHEDULE,
    "turn_off_after_min": 0,
    "turn_back_on_after_min": 0,
    "catch_up": True,
    "late_start_window_min": 15,
    "respect_manual": True,
    "pulse_enabled": False,
    "pulse_at": UNUSED_TIME,
    "pulse_minutes": 3,
    "pulse_min_steady_min": 5,
    "docked_guard": True,
    "extra_conditions": [],
    "on_at_sunrise": False,
    "on_at_sunset": False,
    "off_at_sunrise": False,
    "off_at_sunset": False,
    "days_end": _ALL_DAY_VALUES,
    "crosses_midnight": False,
    "timer_enabled": True,
    "timer_entity": UNUSED_TIMER,
    "late_window_end": "00:15:00",
    "late_sun_offset": "00:15:00",
    "override_entity": UNUSED_SWITCH,
    "paused_until_entity": UNUSED_DATETIME,
}

# Every translation key `validate` and `decompile` can raise (strings.json `exceptions`).
PROBLEM_KEYS: Final = frozenset(
    {
        "refused_action",
        "on_time_not_supported",
        "same_on_and_off_time",
        "schedule_entity_missing",
        "times_with_weekly_schedule",
        "no_days_selected",
        "duration_not_supported",
        "both_durations",
        "pulse_not_supported",
        "out_of_range",
        "invalid_inputs",
    }
)

# Options that need an activating action, as in `domains.profile_for`.
_NEEDS_ON_ACTION: Final = frozenset({Option.ON_TIME, Option.TURN_BACK_ON_AFTER, Option.PULSE})
_NAMED_DAYS: Final[Mapping[frozenset[Weekday], Days]] = {
    ALL_DAYS: Days.EVERY_DAY,
    WEEKDAYS: Days.WEEKDAYS,
    WEEKEND: Days.WEEKENDS,
}
_WEEKDAY_VALUES: Final = frozenset(_ALL_DAY_VALUES)
_KIND_VALUES: Final = frozenset(kind.value for kind in TimeKind)
_NAME: Final = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+")
_TIME: Final = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")
# A sun offset: `[-]HH:MM:SS` as compile writes it, `H:MM`, or a leading `+` as the core's
# time period text allows; seconds are dropped toward zero.
_OFFSET: Final = re.compile(r"([-+])?(\d{1,2}):([0-5]\d)(?::[0-5]\d)?")
_MINUTES_PER_DAY: Final = 1440


@dataclass(frozen=True, slots=True)
class HelperRefs:
    """The entities a routine's automation names besides its target."""

    device_id: str
    timer_entity: str = UNUSED_TIMER
    schedule_entity: str = UNUSED_SCHEDULE
    override_entity: str = UNUSED_SWITCH
    paused_until_entity: str = UNUSED_DATETIME


# --------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------


def _whole(moment: time) -> time:
    return moment.replace(microsecond=0, tzinfo=None)


def _named(day_set: frozenset[Weekday]) -> tuple[Days, frozenset[Weekday]]:
    """Return Some days with its set, or the name a day set has and the full week."""
    named = _NAMED_DAYS.get(day_set)
    if named is None:
        return Days.SOME_DAYS, day_set
    return named, ALL_DAYS


def _bound(kind: TimeKind, at: time | None, offset_min: int) -> tuple[time | None, int]:
    """Return a side's time and offset as the inputs hold them: a time or an offset."""
    if kind is TimeKind.TIME:
        return (None if at is None else _whole(at)), 0
    return None, offset_min


def canonical(settings: RoutineSettings) -> RoutineSettings:
    """Return the settings in the form `decompile` reads back (see the module docstring)."""
    days, day_set = settings.days, ALL_DAYS
    if days is Days.SOME_DAYS:
        days, day_set = _named(settings.day_set)
    pulse = settings.pulse
    on_time, on_offset = _bound(settings.on_kind, settings.on_time, settings.on_sun_offset_min)
    off_time, off_offset = _bound(settings.off_kind, settings.off_time, settings.off_sun_offset_min)
    return replace(
        settings,
        days=days,
        day_set=day_set,
        schedule_entity=settings.schedule_entity if days is Days.WEEKLY_SCHEDULE else None,
        on_time=on_time,
        off_time=off_time,
        pulse=None if pulse is None else replace(pulse, at=_whole(pulse.at)),
        extra_conditions=tuple(settings.extra_conditions),
        on_sun_offset_min=on_offset,
        off_sun_offset_min=off_offset,
    )


def _supports(profile: DomainProfile, option: Option) -> bool:
    if option in _NEEDS_ON_ACTION and profile.on_action is None:
        return False
    return option in profile.options


def _refusals(profile: DomainProfile) -> list[Problem]:
    """Reject a profile that carries a refused action at all (PRD 5.4)."""
    return [
        Problem("target_entity", "refused_action", {"action": action})
        for action in (profile.on_action, profile.off_action)
        if action is not None and is_refused_action(action, None)
    ]


def _same_bounds(settings: RoutineSettings) -> bool:
    """Tell whether both sides are the same bound: one kind with one time or one offset."""
    if not (settings.has_on and settings.has_off) or settings.on_kind is not settings.off_kind:
        return False
    if settings.on_kind is TimeKind.TIME:
        return settings.on_time == settings.off_time
    return settings.on_sun_offset_min == settings.off_sun_offset_min


def _schedule_problems(settings: RoutineSettings, profile: DomainProfile) -> list[Problem]:
    """Reject times and days that cannot run: TECH_SPEC 3.3 and the weekly schedule rule.

    A sun bound is a scheduled time like any other (L60): an on side needs an on action,
    two equal bounds are the same time, and a weekly schedule takes none.
    """
    found: list[Problem] = []
    if settings.has_on and not _supports(profile, Option.ON_TIME):
        key = "on_time" if settings.on_kind is TimeKind.TIME else "on_kind"
        found.append(Problem(key, "on_time_not_supported", {"domain": profile.domain}))
    if _same_bounds(settings):
        key = "off_time" if settings.off_kind is TimeKind.TIME else "off_sun_offset_min"
        found.append(Problem(key, "same_on_and_off_time"))
    if settings.days is Days.WEEKLY_SCHEDULE:
        if settings.schedule_entity in {None, UNUSED_SCHEDULE}:
            found.append(Problem("schedule_entity", "schedule_entity_missing"))
        if settings.has_on or settings.has_off:
            found.append(Problem("days", "times_with_weekly_schedule"))
    if settings.days is Days.SOME_DAYS and not settings.day_set:
        found.append(Problem("day_set", "no_days_selected"))
    return found


def _option_problems(settings: RoutineSettings, profile: DomainProfile) -> list[Problem]:
    """Reject durations and pulses the profile lacks, and both durations at once (D27)."""
    domain = {"domain": profile.domain}
    found: list[Problem] = []
    if settings.turn_off_after_min and not _supports(profile, Option.TURN_OFF_AFTER):
        found.append(Problem("turn_off_after_min", "duration_not_supported", domain))
    if settings.turn_back_on_after_min and not _supports(profile, Option.TURN_BACK_ON_AFTER):
        found.append(Problem("turn_back_on_after_min", "duration_not_supported", domain))
    if settings.turn_off_after_min and settings.turn_back_on_after_min:
        found.append(Problem("turn_back_on_after_min", "both_durations"))
    if settings.pulse is not None and not _supports(profile, Option.PULSE):
        found.append(Problem("pulse", "pulse_not_supported", domain))
    return found


def _range_problems(settings: RoutineSettings) -> list[Problem]:
    """Reject minutes outside what the blueprint's number selectors allow."""
    ranges = [
        ("turn_off_after_min", settings.turn_off_after_min, 0, MAX_DURATION_MIN),
        ("turn_back_on_after_min", settings.turn_back_on_after_min, 0, MAX_DURATION_MIN),
        ("late_start_window_min", settings.late_start_window_min, 0, MAX_LATE_START_MIN),
        ("on_sun_offset_min", settings.on_sun_offset_min, -MAX_SUN_OFFSET_MIN, MAX_SUN_OFFSET_MIN),
        (
            "off_sun_offset_min",
            settings.off_sun_offset_min,
            -MAX_SUN_OFFSET_MIN,
            MAX_SUN_OFFSET_MIN,
        ),
    ]
    if settings.pulse is not None:
        ranges += [
            ("pulse_minutes", settings.pulse.minutes, 1, MAX_DURATION_MIN),
            ("pulse_min_steady_min", settings.pulse.min_steady_min, 0, MAX_DURATION_MIN),
        ]
    return [
        Problem(key, "out_of_range", {"setting": key, "min": str(low), "max": str(high)})
        for key, value, low, high in ranges
        if not low <= value <= high
    ]


def validate(settings: RoutineSettings, profile: DomainProfile) -> list[Problem]:
    """Return every reason the settings cannot run on the profile, in a fixed order."""
    return [
        *_refusals(profile),
        *_schedule_problems(settings, profile),
        *_option_problems(settings, profile),
        *_range_problems(settings),
    ]


# --------------------------------------------------------------------------------------
# compile
# --------------------------------------------------------------------------------------


def _clock(moment: time) -> str:
    return f"{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}"


def _day_values(days: frozenset[Weekday]) -> list[str]:
    return [day.value for day in Weekday if day in days]


def _late_window_end(on_time: time | None, minutes: int) -> str:
    """Return the on time plus the late start window, wrapped at midnight."""
    start = on_time or time()
    total = (start.hour * 60 + start.minute + minutes) % _MINUTES_PER_DAY
    return _clock(time(total // 60, total % 60, start.second))


def _offset(minutes: int) -> str:
    """Return a sun offset as the blueprint's text: `[-]HH:MM:SS`, whole minutes."""
    hours, rest = divmod(abs(minutes), 60)
    return f"{'-' if minutes < 0 else ''}{hours:02d}:{rest:02d}:00"


def compile(  # noqa: A001  # the contract name (plan Section 4.2)
    settings: RoutineSettings, profile: DomainProfile, refs: HelperRefs
) -> CompiledInputs:
    """Return the blueprint inputs for valid settings; raise the first problem otherwise."""
    problems = validate(settings, profile)
    if problems:
        raise CompileError(problems[0].translation_key, problems[0].placeholders)
    settings = canonical(settings)
    weekly = settings.days is Days.WEEKLY_SCHEDULE
    schedule = settings.schedule_entity if weekly and settings.schedule_entity else None
    timed = bool(settings.turn_off_after_min or settings.turn_back_on_after_min)
    timer = refs.timer_entity if timed else UNUSED_TIMER
    pulse = settings.pulse or Pulse(time())
    inputs: dict[str, Any] = {
        "target_entity": settings.target_entity,
        "on_action": profile.on_action or profile.off_action,
        "off_action": profile.off_action,
        "inactive_state": profile.inactive_state,
        "device_id": refs.device_id,
        "on_time_enabled": settings.on_time is not None,
        "on_time": UNUSED_TIME if settings.on_time is None else _clock(settings.on_time),
        "on_kind": settings.on_kind.value,
        "on_sun_offset": _offset(settings.on_sun_offset_min),
        "off_time_enabled": settings.off_time is not None,
        "off_time": UNUSED_TIME if settings.off_time is None else _clock(settings.off_time),
        "off_kind": settings.off_kind.value,
        "off_sun_offset": _offset(settings.off_sun_offset_min),
        "days_start": _day_values(settings.effective_days),
        "schedule_enabled": weekly,
        "schedule_entity": schedule or UNUSED_SCHEDULE,
        "turn_off_after_min": int(settings.turn_off_after_min),
        "turn_back_on_after_min": int(settings.turn_back_on_after_min),
        "catch_up": bool(settings.catch_up),
        "late_start_window_min": int(settings.late_start_window_min),
        "respect_manual": bool(settings.respect_manual),
        "pulse_enabled": settings.pulse is not None,
        "pulse_at": _clock(pulse.at),
        "pulse_minutes": int(pulse.minutes),
        "pulse_min_steady_min": int(pulse.min_steady_min),
        "docked_guard": bool(settings.docked_guard),
        "extra_conditions": [dict(condition) for condition in settings.extra_conditions],
        "on_at_sunrise": settings.on_kind is TimeKind.SUNRISE,
        "on_at_sunset": settings.on_kind is TimeKind.SUNSET,
        "off_at_sunrise": settings.off_kind is TimeKind.SUNRISE,
        "off_at_sunset": settings.off_kind is TimeKind.SUNSET,
        "days_end": _day_values(settings.end_days),
        "crosses_midnight": settings.crosses_midnight,
        "timer_enabled": timer != UNUSED_TIMER,
        "timer_entity": timer,
        "late_window_end": _late_window_end(settings.on_time, settings.late_start_window_min),
        "late_sun_offset": _offset(settings.on_sun_offset_min + settings.late_start_window_min),
        "override_entity": refs.override_entity,
        "paused_until_entity": refs.paused_until_entity,
    }
    return CompiledInputs(inputs)


# --------------------------------------------------------------------------------------
# Sync back: shape, decompile, helper references, refusals
# --------------------------------------------------------------------------------------


def _parse_time(value: object) -> time | None:
    if not isinstance(value, str) or (match := _TIME.fullmatch(value)) is None:
        return None
    hour, minute, second = (int(part or 0) for part in match.groups())
    try:
        return time(hour, minute, second)
    except ValueError:
        return None


def _parse_offset(value: object) -> int | None:
    """Return a sun offset text as whole minutes, the seconds dropped toward zero."""
    if not isinstance(value, str) or (match := _OFFSET.fullmatch(value)) is None:
        return None
    sign, hours, minutes = match.groups()
    total = int(hours) * 60 + int(minutes)
    return -total if sign == "-" else total


def _is_name(value: object) -> bool:
    return isinstance(value, str) and _NAME.fullmatch(value) is not None


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_flag(value: object) -> bool:
    return isinstance(value, bool)


def _is_minutes(value: object) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, float) and value.is_integer())


def _is_time(value: object) -> bool:
    return _parse_time(value) is not None


def _is_offset(value: object) -> bool:
    return _parse_offset(value) is not None


def _is_kind(value: object) -> bool:
    return isinstance(value, str) and value in _KIND_VALUES


def _is_days(value: object) -> bool:
    return isinstance(value, list | tuple) and all(
        isinstance(day, str) and day in _WEEKDAY_VALUES for day in value
    )


def _is_conditions(value: object) -> bool:
    return isinstance(value, list | tuple) and all(isinstance(item, Mapping) for item in value)


_KINDS: Final[Mapping[str, Callable[[object], bool]]] = {
    "target_entity": _is_name,
    "on_action": _is_name,
    "off_action": _is_name,
    "inactive_state": _is_text,
    "device_id": _is_text,
    "on_time_enabled": _is_flag,
    "on_time": _is_time,
    "on_kind": _is_kind,
    "on_sun_offset": _is_offset,
    "off_time_enabled": _is_flag,
    "off_time": _is_time,
    "off_kind": _is_kind,
    "off_sun_offset": _is_offset,
    "days_start": _is_days,
    "schedule_enabled": _is_flag,
    "schedule_entity": _is_name,
    "turn_off_after_min": _is_minutes,
    "turn_back_on_after_min": _is_minutes,
    "catch_up": _is_flag,
    "late_start_window_min": _is_minutes,
    "respect_manual": _is_flag,
    "pulse_enabled": _is_flag,
    "pulse_at": _is_time,
    "pulse_minutes": _is_minutes,
    "pulse_min_steady_min": _is_minutes,
    "docked_guard": _is_flag,
    "extra_conditions": _is_conditions,
    "on_at_sunrise": _is_flag,
    "on_at_sunset": _is_flag,
    "off_at_sunrise": _is_flag,
    "off_at_sunset": _is_flag,
    "days_end": _is_days,
    "crosses_midnight": _is_flag,
    "timer_enabled": _is_flag,
    "timer_entity": _is_name,
    "late_window_end": _is_time,
    "late_sun_offset": _is_offset,
    "override_entity": _is_name,
    "paused_until_entity": _is_name,
}


def is_valid_shape(inputs: object) -> bool:
    """Tell whether blueprint inputs are readable, as sync back must know first.

    Readable means no unknown key, no missing required key, and every value of the type
    `compile` writes. A form may write `HH:MM` times and offsets and whole numbers as
    floats, which read the same. The inputs of a later schema may be missing, as every input
    with a default may: schema 1 and schema 2 inputs are readable.
    """
    if not isinstance(inputs, Mapping):
        return False
    keys = set(inputs)
    if not keys <= _KINDS.keys() or not keys >= REQUIRED_KEYS:
        return False
    return all(_KINDS[key](value) for key, value in inputs.items())


def _filled(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Return the inputs with the blueprint's defaults for omitted keys, or raise."""
    if not is_valid_shape(inputs):
        raise CompileError("invalid_inputs")
    return {**INPUT_DEFAULTS, **inputs}


def _time(value: str) -> time:
    parsed = _parse_time(value)
    assert parsed is not None  # noqa: S101  # the shape was checked
    return parsed


def _side(values: Mapping[str, Any], side: str) -> tuple[time | None, TimeKind, int]:
    """Return one side's time, kind and offset from its primary inputs only."""
    kind = TimeKind(values[f"{side}_kind"])
    if kind is TimeKind.TIME:
        enabled = values[f"{side}_time_enabled"]
        return (_time(values[f"{side}_time"]) if enabled else None), kind, 0
    offset = _parse_offset(values[f"{side}_sun_offset"])
    assert offset is not None  # noqa: S101  # the shape was checked
    return None, kind, offset


def decompile(inputs: Mapping[str, Any]) -> RoutineSettings:
    """Return the canonical settings blueprint inputs describe; raise for a bad shape."""
    values = _filled(inputs)
    if values["schedule_enabled"]:
        days, day_set = Days.WEEKLY_SCHEDULE, ALL_DAYS
    else:
        days, day_set = _named(frozenset(Weekday(day) for day in values["days_start"]))
    schedule_entity = values["schedule_entity"]
    pulse = Pulse(
        at=_time(values["pulse_at"]),
        minutes=int(values["pulse_minutes"]),
        min_steady_min=int(values["pulse_min_steady_min"]),
    )
    on_time, on_kind, on_offset = _side(values, "on")
    off_time, off_kind, off_offset = _side(values, "off")
    return RoutineSettings(
        target_entity=values["target_entity"],
        on_time=on_time,
        off_time=off_time,
        days=days,
        day_set=day_set,
        schedule_entity=(
            schedule_entity
            if days is Days.WEEKLY_SCHEDULE and schedule_entity != UNUSED_SCHEDULE
            else None
        ),
        turn_off_after_min=int(values["turn_off_after_min"]),
        turn_back_on_after_min=int(values["turn_back_on_after_min"]),
        catch_up=values["catch_up"],
        late_start_window_min=int(values["late_start_window_min"]),
        respect_manual=values["respect_manual"],
        pulse=pulse if values["pulse_enabled"] else None,
        extra_conditions=tuple(values["extra_conditions"]),
        docked_guard=values["docked_guard"],
        on_kind=on_kind,
        on_sun_offset_min=on_offset,
        off_kind=off_kind,
        off_sun_offset_min=off_offset,
    )


def refs_of(inputs: Mapping[str, Any]) -> HelperRefs:
    """Return the helper references blueprint inputs name; raise for a bad shape."""
    values = _filled(inputs)
    return HelperRefs(
        device_id=values["device_id"],
        timer_entity=values["timer_entity"],
        schedule_entity=values["schedule_entity"],
        override_entity=values["override_entity"],
        paused_until_entity=values["paused_until_entity"],
    )


def has_refused_action(inputs: Mapping[str, Any], device_class: str | None) -> bool:
    """Tell whether raw inputs name a refused action (PRD 5.4), for sync back."""
    return any(
        isinstance(action, str) and is_refused_action(action, device_class)
        for action in (inputs.get("on_action"), inputs.get("off_action"))
    )
