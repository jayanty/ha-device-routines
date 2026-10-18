"""Hypothesis strategies for routine settings, one profile at a time (Build A lane 1).

Shared by the compiler and next run properties here, the blueprint behavior matrix (lane
2) and the manager (lane 5). Importing this module needs no Home Assistant: it reads only
the pure modules.

- `profile_cases()` draws a `(profile, device_class)` pair for every domain in
  `domains.PROFILES`, with the PRD 5.4 refusals already applied by `profile_for`, so a
  garage cover arrives without an open action.
- `routine_settings(profile)` draws settings that `compiler.validate` accepts for that
  profile and that are already canonical (`compiler.canonical(s) == s`), so
  `decompile(compile(s)) == s` holds for every draw.
- `routines()` draws `(profile, device_class, settings)` triples from the two above.
- `any_settings(profile)` draws settings with no regard for validity, for properties that
  must hold for every input (refused actions are never emitted, whatever is asked).
- `helper_refs()` draws helper references, real ids or the sentinels.
- `loose_settings(profile)` (wave A4) draws valid settings in any form a caller may hand
  the manager: a named day set as Some days, a stray day set or schedule, times with
  microseconds or a zone. `compiler.canonical` of a draw is a `routine_settings` draw.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, time
from typing import Any

from hypothesis import strategies as st

from custom_components.device_routines import compiler
from custom_components.device_routines.domains import PROFILES, profile_for
from custom_components.device_routines.models import (
    ALL_DAYS,
    WEEKDAYS,
    WEEKEND,
    Days,
    DomainProfile,
    Option,
    Pulse,
    RoutineSettings,
    Weekday,
)

# Device classes worth drawing per domain: none, a harmless one and every refused one.
HARMLESS_DEVICE_CLASSES = {"cover": "shade", "valve": "water"}

# Extra conditions as the blueprint's condition selector stores them (FR-R9).
EXAMPLE_CONDITIONS: tuple[dict[str, Any], ...] = (
    {"condition": "state", "entity_id": "input_boolean.guest_mode", "state": "off"},
    {"condition": "numeric_state", "entity_id": "sensor.robot_vacuum_battery", "above": 95},
)

OBJECT_IDS = st.sampled_from(["living_room_fan", "robot_vacuum", "front_door", "patio_light"])


def device_classes(domain: str) -> tuple[str | None, ...]:
    """Return the device classes drawn for a domain."""
    profile = PROFILES[domain]
    harmless = HARMLESS_DEVICE_CLASSES.get(domain)
    extra = (harmless,) if harmless else ()
    return (None, *extra, *sorted(profile.refused_device_classes))


def _case(domain: str, device_class: str | None) -> tuple[DomainProfile, str | None]:
    profile = profile_for(domain, device_class)
    assert profile is not None
    return profile, device_class


def profile_cases() -> st.SearchStrategy[tuple[DomainProfile, str | None]]:
    """Draw a profile with refusals applied, and the device class it was made for."""
    cases = [
        _case(domain, device_class)
        for domain in sorted(PROFILES)
        for device_class in device_classes(domain)
    ]
    return st.sampled_from(cases)


def whole_times() -> st.SearchStrategy[time]:
    """Draw a naive time of day with whole seconds, as the blueprint stores it."""
    return st.builds(
        time,
        hour=st.integers(0, 23),
        minute=st.integers(0, 59),
        second=st.sampled_from([0, 0, 0, 30, 59]),
    )


def _supports(profile: DomainProfile, option: Option) -> bool:
    needs_on = option in {Option.ON_TIME, Option.TURN_BACK_ON_AFTER, Option.PULSE}
    return option in profile.options and (profile.on_action is not None or not needs_on)


some_days = st.frozensets(st.sampled_from(list(Weekday)), min_size=1).filter(
    lambda days: days not in (ALL_DAYS, WEEKDAYS, WEEKEND)
)


@st.composite
def routine_settings(draw: st.DrawFn, profile: DomainProfile) -> RoutineSettings:
    """Draw canonical settings that `compiler.validate` accepts for the profile."""
    days = draw(st.sampled_from(list(Days)))
    on_time: time | None = None
    off_time: time | None = None
    schedule_entity: str | None = None
    day_set = ALL_DAYS
    if days is Days.WEEKLY_SCHEDULE:
        schedule_entity = f"schedule.{draw(OBJECT_IDS)}"
    else:
        if _supports(profile, Option.ON_TIME):
            on_time = draw(st.none() | whole_times())
        off_time = draw(st.none() | whole_times())
        if off_time == on_time:
            off_time = None
    if days is Days.SOME_DAYS:
        day_set = draw(some_days)
    durations = ["none"]
    if _supports(profile, Option.TURN_OFF_AFTER):
        durations.append("off")
    if _supports(profile, Option.TURN_BACK_ON_AFTER):
        durations.append("on")
    duration = draw(st.sampled_from(durations))
    minutes = draw(st.integers(1, compiler.MAX_DURATION_MIN))
    pulse: Pulse | None = None
    if _supports(profile, Option.PULSE):
        pulse = draw(
            st.none()
            | st.builds(
                Pulse,
                at=whole_times(),
                minutes=st.integers(1, compiler.MAX_DURATION_MIN),
                min_steady_min=st.integers(0, compiler.MAX_DURATION_MIN),
            )
        )
    return RoutineSettings(
        target_entity=f"{profile.domain}.{draw(OBJECT_IDS)}",
        on_time=on_time,
        off_time=off_time,
        days=days,
        day_set=day_set,
        schedule_entity=schedule_entity,
        turn_off_after_min=minutes if duration == "off" else 0,
        turn_back_on_after_min=minutes if duration == "on" else 0,
        catch_up=draw(st.booleans()),
        late_start_window_min=draw(st.integers(0, compiler.MAX_LATE_START_MIN)),
        respect_manual=draw(st.booleans()),
        pulse=pulse,
        extra_conditions=tuple(draw(st.lists(st.sampled_from(EXAMPLE_CONDITIONS), max_size=2))),
        docked_guard=draw(st.booleans()),
    )


def routines() -> st.SearchStrategy[tuple[DomainProfile, str | None, RoutineSettings]]:
    """Draw a profile, its device class and valid canonical settings for it."""
    return profile_cases().flatmap(
        lambda case: routine_settings(case[0]).map(lambda settings: (*case, settings))
    )


@st.composite
def any_settings(draw: st.DrawFn, profile: DomainProfile) -> RoutineSettings:
    """Draw settings for the profile's domain with no regard for validity."""
    minutes = st.integers(-5, 2 * compiler.MAX_DURATION_MIN)
    return RoutineSettings(
        target_entity=f"{profile.domain}.{draw(OBJECT_IDS)}",
        on_time=draw(st.none() | whole_times()),
        off_time=draw(st.none() | whole_times()),
        days=draw(st.sampled_from(list(Days))),
        day_set=draw(st.frozensets(st.sampled_from(list(Weekday)))),
        schedule_entity=draw(st.none() | st.just("schedule.living_room_fan")),
        turn_off_after_min=draw(minutes),
        turn_back_on_after_min=draw(minutes),
        late_start_window_min=draw(minutes),
        pulse=draw(st.none() | st.builds(Pulse, at=whole_times(), minutes=minutes)),
    )


def helper_refs() -> st.SearchStrategy[compiler.HelperRefs]:
    """Draw helper references: real entity ids or the sentinels."""
    return st.builds(
        compiler.HelperRefs,
        device_id=st.sampled_from(["device-2", "device-1"]),
        timer_entity=st.sampled_from([compiler.UNUSED_TIMER, "timer.routine_living_room_fan"]),
        schedule_entity=st.sampled_from(
            [compiler.UNUSED_SCHEDULE, "schedule.routine_living_room_fan"]
        ),
        override_entity=st.sampled_from(
            [compiler.UNUSED_SWITCH, "switch.living_room_fan_manual_override"]
        ),
        paused_until_entity=st.sampled_from(
            [compiler.UNUSED_DATETIME, "datetime.living_room_fan_paused_until"]
        ),
    )


_NAMED_SETS = {Days.EVERY_DAY: ALL_DAYS, Days.WEEKDAYS: WEEKDAYS, Days.WEEKENDS: WEEKEND}


def _loosened(draw: st.DrawFn, moment: time, zones: bool) -> time:
    """Return the time as it is, or with microseconds and, with `zones`, maybe a zone."""
    if not draw(st.booleans()):
        return moment
    zone = draw(st.sampled_from([None, UTC])) if zones else None
    return moment.replace(microsecond=draw(st.integers(1, 999_999)), tzinfo=zone)


@st.composite
def loose_settings(
    draw: st.DrawFn, profile: DomainProfile, *, zones: bool = True
) -> RoutineSettings:
    """Draw valid settings in a form `compiler.canonical` maps to a `routine_settings` draw.

    The manager keeps what a caller sent until the next start reads the automation back,
    so a sentence must not depend on the form: Weekdays sent as Some days with Monday to
    Friday, a day set or a schedule left over from an earlier choice, a time picked with
    microseconds or (with `zones`) a zone.
    """
    settings = draw(routine_settings(profile))
    if settings.days in _NAMED_SETS and draw(st.booleans()):
        settings = replace(settings, days=Days.SOME_DAYS, day_set=_NAMED_SETS[settings.days])
    elif settings.days is not Days.SOME_DAYS and draw(st.booleans()):
        settings = replace(settings, day_set=draw(some_days))
    if settings.days is not Days.WEEKLY_SCHEDULE and draw(st.booleans()):
        settings = replace(settings, schedule_entity=f"schedule.{draw(OBJECT_IDS)}")
    pulse = settings.pulse
    return replace(
        settings,
        on_time=None if settings.on_time is None else _loosened(draw, settings.on_time, zones),
        off_time=None if settings.off_time is None else _loosened(draw, settings.off_time, zones),
        pulse=None if pulse is None else replace(pulse, at=_loosened(draw, pulse.at, zones)),
    )
