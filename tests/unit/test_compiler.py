"""Routine settings to blueprint inputs and back (TECH_SPEC 3.3 and 5.2, PRD 5.3 and 5.4)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, time
import json
from pathlib import Path
from typing import Any

from hypothesis import given, settings as hypothesis_settings
import pytest

from custom_components.device_routines import compiler, domains, markers
from custom_components.device_routines.models import (
    ALL_DAYS,
    NOMINAL_SUN_TIMES,
    WEEKDAYS,
    CompileError,
    Days,
    DomainProfile,
    Occurrence,
    Option,
    Problem,
    Pulse,
    RoutineSettings,
    RoutineView,
    Source,
    Status,
    TimeKind,
    Verb,
    Weekday,
)
from tests.unit import strategies

COMPONENT = Path(compiler.__file__).parent
STRINGS = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))

FAN = domains.PROFILES["fan"]
VACUUM = domains.PROFILES["vacuum"]
LOCK = domains.PROFILES["lock"]
MEDIA = domains.PROFILES["media_player"]
CLIMATE = domains.PROFILES["climate"]


def refused_profile(domain: str, device_class: str) -> DomainProfile:
    profile = domains.profile_for(domain, device_class)
    assert profile is not None
    return profile


GARAGE = refused_profile("cover", "garage")

REFS = compiler.HelperRefs(
    device_id="device-1",
    timer_entity="timer.routine_living_room_fan",
    schedule_entity="schedule.routine_living_room_fan",
    override_entity="switch.living_room_fan_manual_override",
    paused_until_entity="datetime.living_room_fan_paused_until",
)
WINDOW = RoutineSettings(
    target_entity="fan.living_room_fan", on_time=time(17), off_time=time(9), days=Days.WEEKDAYS
)
# On 30 minutes after sunset, off 45 minutes before sunrise: a window across midnight.
SUN_WINDOW = RoutineSettings(
    target_entity="light.patio_light",
    days=Days.WEEKDAYS,
    on_kind=TimeKind.SUNSET,
    on_sun_offset_min=30,
    off_kind=TimeKind.SUNRISE,
    off_sun_offset_min=-45,
)
LIGHT = domains.PROFILES["light"]

# Blueprint input schema 2 (plan Section 6.2.1), 38 inputs in the blueprint's file order
# (TECH_SPEC 5.2, owner decision O3, decision L74): Target (the device and the four required
# inputs Device Routines sets), the inputs a person may change in the form, then the 11
# other inputs Device Routines sets, in the collapsed last section.
SPEC_KEYS = (
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
    "timer_entity",
    "late_window_end",
    "late_sun_offset",
    "override_entity",
    "paused_until_entity",
)
# The inputs schema 2 added, with the defaults that reproduce schema 1 behavior.
SCHEMA_2_DEFAULTS = {
    "on_kind": "time",
    "on_sun_offset": "00:00:00",
    "off_kind": "time",
    "off_sun_offset": "00:00:00",
    "on_at_sunrise": False,
    "on_at_sunset": False,
    "off_at_sunrise": False,
    "off_at_sunset": False,
    "late_sun_offset": "00:15:00",
}


def compiled(
    settings: RoutineSettings,
    profile: DomainProfile = FAN,
    refs: compiler.HelperRefs = REFS,
) -> dict[str, Any]:
    return dict(compiler.compile(settings, profile, refs).inputs)


def problems(settings: RoutineSettings, profile: DomainProfile = FAN) -> list[Problem]:
    return compiler.validate(settings, profile)


# --------------------------------------------------------------------------------------
# Constants and the input contract
# --------------------------------------------------------------------------------------


def test_input_keys_order_is_fixed() -> None:
    assert compiler.INPUT_KEYS == SPEC_KEYS
    assert len(compiler.INPUT_KEYS) == 38
    assert compiler.BLUEPRINT_SCHEMA_VERSION == 2
    assert list(compiled(WINDOW)) == list(SPEC_KEYS)
    assert list(compiled(SUN_WINDOW, LIGHT)) == list(SPEC_KEYS)
    assert {
        "target_entity",
        "on_action",
        "off_action",
        "inactive_state",
        "device_id",
    } == compiler.REQUIRED_KEYS
    assert set(compiler.INPUT_DEFAULTS) == set(SPEC_KEYS) - compiler.REQUIRED_KEYS
    assert set(compiler._KINDS) == set(SPEC_KEYS)


def test_contract_constants() -> None:
    assert compiler.BLUEPRINT_SCHEMA_VERSION == 2
    assert compiler.MAX_SUN_OFFSET_MIN == 180
    assert compiler.BLUEPRINT_PATH == "device_routines/device_routine.yaml"
    assert compiler.BLUEPRINT_PATH is markers.BLUEPRINT_PATH
    assert compiler.EVENT_ACTION_SKIPPED == "device_routines_action_skipped"
    assert compiler.EVENT_TIMER_CAUGHT_UP == "device_routines_timer_caught_up"
    assert compiler.UNUSED_TIMER == "timer.device_routines_unused"
    assert compiler.UNUSED_SCHEDULE == "schedule.device_routines_unused"
    assert compiler.UNUSED_SWITCH == "switch.device_routines_unused"
    assert compiler.UNUSED_DATETIME == "datetime.device_routines_unused"
    assert compiler.HelperRefs("d") == compiler.HelperRefs(
        "d",
        compiler.UNUSED_TIMER,
        compiler.UNUSED_SCHEDULE,
        compiler.UNUSED_SWITCH,
        compiler.UNUSED_DATETIME,
    )


def test_compile_writes_every_input_of_a_window() -> None:
    """The whole mapping for one routine, as lane 2's blueprint receives it."""
    assert compiled(replace(WINDOW, turn_off_after_min=0)) == {
        "target_entity": "fan.living_room_fan",
        "on_action": "fan.turn_on",
        "off_action": "fan.turn_off",
        "inactive_state": "off",
        "device_id": "device-1",
        "on_time_enabled": True,
        "on_time": "17:00:00",
        "on_kind": "time",
        "on_sun_offset": "00:00:00",
        "off_time_enabled": True,
        "off_time": "09:00:00",
        "off_kind": "time",
        "off_sun_offset": "00:00:00",
        "on_at_sunrise": False,
        "on_at_sunset": False,
        "off_at_sunrise": False,
        "off_at_sunset": False,
        "days_start": ["mon", "tue", "wed", "thu", "fri"],
        "days_end": ["tue", "wed", "thu", "fri", "sat"],
        "crosses_midnight": True,
        "schedule_enabled": False,
        "schedule_entity": compiler.UNUSED_SCHEDULE,
        "timer_entity": compiler.UNUSED_TIMER,
        "turn_off_after_min": 0,
        "turn_back_on_after_min": 0,
        "catch_up": True,
        "late_start_window_min": 15,
        "late_window_end": "17:15:00",
        "late_sun_offset": "00:15:00",
        "respect_manual": True,
        "override_entity": "switch.living_room_fan_manual_override",
        "paused_until_entity": "datetime.living_room_fan_paused_until",
        "pulse_enabled": False,
        "pulse_at": "00:00:00",
        "pulse_minutes": 3,
        "pulse_min_steady_min": 5,
        "docked_guard": True,
        "extra_conditions": [],
    }


def test_compile_writes_every_input_of_a_sun_window() -> None:
    """A sun bound writes its kind, its offset and its sun flag; its time is the sentinel."""
    inputs = compiled(SUN_WINDOW, LIGHT)
    sun_inputs = {key: inputs[key] for key in SPEC_KEYS if key in SCHEMA_2_DEFAULTS}
    assert sun_inputs == {
        "on_kind": "sunset",
        "on_sun_offset": "00:30:00",
        "off_kind": "sunrise",
        "off_sun_offset": "-00:45:00",
        "on_at_sunrise": False,
        "on_at_sunset": True,
        "off_at_sunrise": True,
        "off_at_sunset": False,
        "late_sun_offset": "00:45:00",
    }
    assert (inputs["on_time_enabled"], inputs["on_time"]) == (False, compiler.UNUSED_TIME)
    assert (inputs["off_time_enabled"], inputs["off_time"]) == (False, compiler.UNUSED_TIME)
    # Sunset to sunrise crosses midnight by the nominal times, so it ends the day after.
    assert inputs["crosses_midnight"] is True
    assert inputs["days_end"] == ["tue", "wed", "thu", "fri", "sat"]
    # The late window of a time start has no time to follow: it starts at midnight.
    assert inputs["late_window_end"] == "00:15:00"
    morning = compiled(
        RoutineSettings(
            "light.patio_light", on_kind=TimeKind.SUNRISE, off_time=time(9, 30), days=Days.WEEKENDS
        ),
        LIGHT,
    )
    assert (morning["on_at_sunrise"], morning["on_at_sunset"], morning["on_kind"]) == (
        True,
        False,
        "sunrise",
    )
    assert (morning["off_kind"], morning["off_time_enabled"], morning["off_time"]) == (
        "time",
        True,
        "09:30:00",
    )
    assert (morning["crosses_midnight"], morning["days_end"]) == (False, ["sat", "sun"])


def test_schema_2_defaults_reproduce_schema_1() -> None:
    """Every new input defaults to schema 1 behavior: time bounds, no sun trigger (L60)."""
    assert {key: compiler.INPUT_DEFAULTS[key] for key in SCHEMA_2_DEFAULTS} == SCHEMA_2_DEFAULTS
    # A routine of time bounds writes exactly the defaults, with the default late window.
    for settings in (WINDOW, replace(WINDOW, off_time=None), RoutineSettings("fan.x")):
        inputs = compiled(settings)
        assert {key: inputs[key] for key in SCHEMA_2_DEFAULTS} == SCHEMA_2_DEFAULTS
    # Schema 1 inputs (no schema 2 key) read as the same inputs with the defaults filled in.
    schema_1 = {
        key: value for key, value in compiled(WINDOW).items() if key not in SCHEMA_2_DEFAULTS
    }
    assert compiler.is_valid_shape(schema_1)
    assert compiler.decompile(schema_1) == WINDOW
    assert compiler.decompile(schema_1 | SCHEMA_2_DEFAULTS) == WINDOW
    assert compiler.compile(compiler.decompile(schema_1), FAN, REFS).inputs == compiled(WINDOW)


def test_compile_writes_plain_types_for_yaml() -> None:
    """Home Assistant's YAML dumper represents plain types only: no enums, no tuples."""
    inputs = compiled(
        replace(
            WINDOW,
            days=Days.SOME_DAYS,
            day_set=frozenset({Weekday.SUN}),
            extra_conditions=strategies.EXAMPLE_CONDITIONS,
        )
    )
    for value in inputs.values():
        assert type(value) in {str, bool, int, list}
    assert all(type(day) is str for day in inputs["days_start"] + inputs["days_end"])
    assert all(type(condition) is dict for condition in inputs["extra_conditions"])


def test_disabled_inputs_carry_sentinels() -> None:
    off_only = RoutineSettings(target_entity="fan.living_room_fan", off_time=time(23))
    defaults = compiled(off_only, refs=compiler.HelperRefs("device-1"))
    assert defaults["on_time_enabled"] is False
    assert defaults["on_time"] == compiler.UNUSED_TIME == "00:00:00"
    assert defaults["late_window_end"] == "00:15:00"
    assert defaults["schedule_enabled"] is False
    assert defaults["schedule_entity"] == compiler.UNUSED_SCHEDULE
    assert defaults["timer_entity"] == compiler.UNUSED_TIMER
    assert defaults["override_entity"] == compiler.UNUSED_SWITCH
    assert defaults["paused_until_entity"] == compiler.UNUSED_DATETIME
    assert defaults["pulse_enabled"] is False
    assert (defaults["pulse_at"], defaults["pulse_minutes"], defaults["pulse_min_steady_min"]) == (
        "00:00:00",
        3,
        5,
    )
    assert defaults["extra_conditions"] == []
    for key, default in compiler.INPUT_DEFAULTS.items():
        if key not in {"off_time_enabled", "off_time"}:
            assert defaults[key] == default, key

    # Real helpers are written only where their feature is on.
    with_refs = compiled(off_only)
    assert with_refs["timer_entity"] == compiler.UNUSED_TIMER
    assert with_refs["schedule_entity"] == compiler.UNUSED_SCHEDULE
    assert with_refs["override_entity"] == REFS.override_entity
    assert with_refs["paused_until_entity"] == REFS.paused_until_entity
    timed = compiled(replace(off_only, turn_off_after_min=30))
    assert timed["timer_entity"] == REFS.timer_entity
    kept_alive = compiled(replace(off_only, off_time=None, turn_back_on_after_min=10))
    assert kept_alive["timer_entity"] == REFS.timer_entity
    weekly = compiled(
        replace(off_only, off_time=None, days=Days.WEEKLY_SCHEDULE, schedule_entity="schedule.x")
    )
    assert (weekly["schedule_enabled"], weekly["schedule_entity"]) == (True, "schedule.x")
    assert weekly["days_start"] == weekly["days_end"] == [day.value for day in Weekday]


def test_a_profile_without_an_on_action_writes_its_safe_action_twice() -> None:
    lock = compiled(RoutineSettings(target_entity="lock.front_door", off_time=time(22)), LOCK)
    assert (lock["on_action"], lock["off_action"], lock["inactive_state"]) == (
        "lock.lock",
        "lock.lock",
        "locked",
    )
    garage = compiled(RoutineSettings(target_entity="cover.garage_door", off_time=time(22)), GARAGE)
    assert garage["on_action"] == garage["off_action"] == "cover.close_cover"
    vacuum = compiled(RoutineSettings(target_entity="vacuum.robot_vacuum", on_time=time(9)), VACUUM)
    assert (vacuum["on_action"], vacuum["off_action"], vacuum["inactive_state"]) == (
        "vacuum.start",
        "vacuum.return_to_base",
        "docked",
    )


# --------------------------------------------------------------------------------------
# Derived inputs
# --------------------------------------------------------------------------------------


def test_days_end_shifts_by_one_when_crossing_midnight() -> None:
    crossing = compiled(WINDOW)
    assert crossing["crosses_midnight"] is True
    assert crossing["days_end"] == ["tue", "wed", "thu", "fri", "sat"]

    weekend_nights = compiled(replace(WINDOW, days=Days.WEEKENDS))
    assert weekend_nights["days_start"] == ["sat", "sun"]
    assert weekend_nights["days_end"] == ["mon", "sun"]  # Sunday's window ends on Monday

    same_day = compiled(replace(WINDOW, on_time=time(9), off_time=time(17)))
    assert same_day["crosses_midnight"] is False
    assert same_day["days_end"] == same_day["days_start"] == ["mon", "tue", "wed", "thu", "fri"]

    one_shot = compiled(replace(WINDOW, off_time=None))
    assert one_shot["crosses_midnight"] is False
    assert one_shot["days_end"] == one_shot["days_start"]


@pytest.mark.parametrize(
    ("on_time", "window", "end"),
    [
        (time(17), 15, "17:15:00"),
        (time(23, 50), 15, "00:05:00"),
        (time(23, 59, 30), 180, "02:59:30"),
        (time(6), 0, "06:00:00"),
        (None, 15, "00:15:00"),
        (None, 180, "03:00:00"),
    ],
)
def test_late_window_end_wraps_at_midnight(on_time: time | None, window: int, end: str) -> None:
    settings = RoutineSettings(
        target_entity="vacuum.robot_vacuum", on_time=on_time, late_start_window_min=window
    )
    assert compiled(settings, VACUUM)["late_window_end"] == end


def test_late_sun_offset_is_offset_plus_window() -> None:
    def late(offset: int, window: int) -> str:
        settings = RoutineSettings(
            "light.patio_light",
            on_kind=TimeKind.SUNSET,
            on_sun_offset_min=offset,
            late_start_window_min=window,
        )
        return str(compiled(settings, LIGHT)["late_sun_offset"])

    assert late(0, 15) == "00:15:00"
    assert late(30, 15) == "00:45:00"
    assert late(-30, 15) == "-00:15:00"
    assert late(-30, 30) == "00:00:00"
    assert late(-180, 0) == "-03:00:00"
    assert late(180, 180) == "06:00:00"
    # A time start has offset 0, so its late sun offset is its window.
    assert compiled(replace(WINDOW, late_start_window_min=40))["late_sun_offset"] == "00:40:00"


def test_settings_know_whether_their_window_crosses_midnight() -> None:
    assert WINDOW.crosses_midnight
    assert WINDOW.end_days == frozenset(
        {Weekday.TUE, Weekday.WED, Weekday.THU, Weekday.FRI, Weekday.SAT}
    )
    assert not replace(WINDOW, off_time=None).crosses_midnight
    assert replace(WINDOW, off_time=None).end_days == WEEKDAYS
    assert Weekday.SUN.following is Weekday.MON


@pytest.mark.parametrize(
    ("on", "off", "crosses"),
    [
        ((TimeKind.SUNSET, None, 0), (TimeKind.SUNRISE, None, 0), True),
        ((TimeKind.SUNRISE, None, 0), (TimeKind.SUNSET, None, 0), False),
        ((TimeKind.TIME, time(22), 0), (TimeKind.SUNRISE, None, 0), True),
        ((TimeKind.SUNSET, None, 0), (TimeKind.TIME, time(23), 0), False),
        # The offsets move the nominal times: 06:00 + 180 is after 18:00 - 180.
        ((TimeKind.SUNSET, None, -180), (TimeKind.SUNRISE, None, 180), True),
        ((TimeKind.SUNRISE, None, 30), (TimeKind.SUNRISE, None, -30), True),
        ((TimeKind.SUNRISE, None, -30), (TimeKind.SUNRISE, None, 30), False),
        ((TimeKind.SUNSET, None, 0), (TimeKind.TIME, time(18), 0), False),
        ((TimeKind.SUNSET, None, 0), (TimeKind.TIME, None, 0), False),
    ],
)
def test_nominal_order_decides_crossing(
    on: tuple[TimeKind, time | None, int], off: tuple[TimeKind, time | None, int], crosses: bool
) -> None:
    """L60: nominal sunrise 06:00 and sunset 18:00 order the bounds, for crossing only."""
    settings = RoutineSettings(
        "light.patio_light",
        on_kind=on[0],
        on_time=on[1],
        on_sun_offset_min=on[2],
        off_kind=off[0],
        off_time=off[1],
        off_sun_offset_min=off[2],
        days=Days.WEEKENDS,
    )
    assert settings.crosses_midnight is crosses
    assert settings.end_days == (
        frozenset({Weekday.SUN, Weekday.MON}) if crosses else frozenset({Weekday.SAT, Weekday.SUN})
    )


def test_settings_know_which_sides_are_set_and_their_nominal_times() -> None:
    assert (SUN_WINDOW.has_on, SUN_WINDOW.has_off) == (True, True)
    assert (SUN_WINDOW.nominal_on, SUN_WINDOW.nominal_off) == (time(18, 30), time(5, 15))
    assert (WINDOW.nominal_on, WINDOW.nominal_off) == (time(17), time(9))
    empty = RoutineSettings("fan.x")
    assert (empty.has_on, empty.has_off, empty.nominal_on, empty.nominal_off) == (
        False,
        False,
        None,
        None,
    )
    # A sun kind sets its side whatever the time field holds.
    stale = RoutineSettings("fan.x", off_kind=TimeKind.SUNSET, off_time=time(9))
    assert stale.has_off
    assert stale.nominal_off == time(18)
    # Out of range offsets (which `validate` refuses) still give a time of day.
    far = RoutineSettings("fan.x", on_kind=TimeKind.SUNRISE, on_sun_offset_min=-400)
    assert far.nominal_on == time(23, 20)
    assert dict(NOMINAL_SUN_TIMES) == {TimeKind.SUNRISE: time(6), TimeKind.SUNSET: time(18)}


# --------------------------------------------------------------------------------------
# validate: one test per TECH_SPEC 3.3 rejection, plus the ranges
# --------------------------------------------------------------------------------------


def test_validate_accepts_a_valid_routine() -> None:
    assert problems(WINDOW) == []


def test_validate_rejects_a_refused_action() -> None:
    unlocking = replace(LOCK, on_action="lock.unlock")
    assert problems(RoutineSettings(target_entity="lock.front_door"), unlocking) == [
        Problem("target_entity", "refused_action", {"action": "lock.unlock"})
    ]
    alarm = DomainProfile(
        domain="alarm_control_panel",
        on_action="alarm_control_panel.alarm_arm_away",
        off_action="alarm_control_panel.alarm_disarm",
        inactive_state="disarmed",
        on_label_key=None,
        off_label_key="turn_off_at",
        options=frozenset({Option.OFF_TIME}),
    )
    found = problems(RoutineSettings(target_entity="alarm_control_panel.house"), alarm)
    assert [problem.translation_key for problem in found] == ["refused_action", "refused_action"]


def test_validate_rejects_the_same_on_and_off_time() -> None:
    assert problems(replace(WINDOW, off_time=time(17))) == [
        Problem("off_time", "same_on_and_off_time")
    ]


@pytest.mark.parametrize(
    ("profile", "turn_off", "turn_back_on", "key"),
    [
        (VACUUM, 30, 0, "turn_off_after_min"),
        (MEDIA, 0, 10, "turn_back_on_after_min"),
        (LOCK, 0, 10, "turn_back_on_after_min"),
        (GARAGE, 0, 10, "turn_back_on_after_min"),
        (CLIMATE, 0, 10, "turn_back_on_after_min"),
    ],
)
def test_validate_rejects_a_duration_the_domain_lacks(
    profile: DomainProfile, turn_off: int, turn_back_on: int, key: str
) -> None:
    settings = RoutineSettings(
        target_entity=f"{profile.domain}.example",
        turn_off_after_min=turn_off,
        turn_back_on_after_min=turn_back_on,
    )
    assert problems(settings, profile) == [
        Problem(key, "duration_not_supported", {"domain": profile.domain})
    ]


def test_validate_rejects_both_durations() -> None:
    both = replace(WINDOW, turn_off_after_min=30, turn_back_on_after_min=10)
    assert problems(both) == [Problem("turn_back_on_after_min", "both_durations")]


@pytest.mark.parametrize("entity", [None, compiler.UNUSED_SCHEDULE])
def test_validate_rejects_a_weekly_schedule_without_its_entity(entity: str | None) -> None:
    weekly = RoutineSettings(
        target_entity="fan.living_room_fan", days=Days.WEEKLY_SCHEDULE, schedule_entity=entity
    )
    assert problems(weekly) == [Problem("schedule_entity", "schedule_entity_missing")]


def test_validate_rejects_times_with_a_weekly_schedule() -> None:
    weekly = replace(WINDOW, days=Days.WEEKLY_SCHEDULE, schedule_entity="schedule.x")
    assert problems(weekly) == [Problem("days", "times_with_weekly_schedule")]
    assert problems(replace(weekly, on_time=None)) == [
        Problem("days", "times_with_weekly_schedule")
    ]


def test_validate_rejects_some_days_with_no_day() -> None:
    empty = replace(WINDOW, days=Days.SOME_DAYS, day_set=frozenset())
    assert problems(empty) == [Problem("day_set", "no_days_selected")]
    # The day set only matters for Some days.
    assert problems(replace(WINDOW, day_set=frozenset())) == []


@pytest.mark.parametrize("profile", [LOCK, MEDIA, GARAGE, CLIMATE, VACUUM])
def test_validate_rejects_a_pulse_without_both_actions(profile: DomainProfile) -> None:
    pulsed = RoutineSettings(target_entity=f"{profile.domain}.example", pulse=Pulse(time(8)))
    assert problems(pulsed, profile) == [
        Problem("pulse", "pulse_not_supported", {"domain": profile.domain})
    ]
    assert problems(replace(pulsed, target_entity="fan.example"), FAN) == []


@pytest.mark.parametrize("profile", [LOCK, MEDIA, GARAGE])
def test_validate_rejects_an_on_time_without_an_on_action(profile: DomainProfile) -> None:
    starting = RoutineSettings(target_entity=f"{profile.domain}.example", on_time=time(7))
    assert problems(starting, profile) == [
        Problem("on_time", "on_time_not_supported", {"domain": profile.domain})
    ]


@pytest.mark.parametrize(
    ("patch", "key", "low", "high"),
    [
        ({"turn_off_after_min": -1}, "turn_off_after_min", 0, 1440),
        ({"turn_off_after_min": 1441}, "turn_off_after_min", 0, 1440),
        ({"turn_back_on_after_min": 1441}, "turn_back_on_after_min", 0, 1440),
        ({"late_start_window_min": -1}, "late_start_window_min", 0, 180),
        ({"late_start_window_min": 181}, "late_start_window_min", 0, 180),
        ({"pulse": Pulse(time(8), minutes=0)}, "pulse_minutes", 1, 1440),
        ({"pulse": Pulse(time(8), min_steady_min=1441)}, "pulse_min_steady_min", 0, 1440),
    ],
)
def test_validate_rejects_minutes_out_of_range(
    patch: dict[str, Any], key: str, low: int, high: int
) -> None:
    settings = replace(WINDOW, **patch)
    assert problems(settings) == [
        Problem(key, "out_of_range", {"setting": key, "min": str(low), "max": str(high)})
    ]


@pytest.mark.parametrize(
    ("key", "offset", "edge"),
    [
        ("on_sun_offset_min", -181, -180),
        ("on_sun_offset_min", 181, 180),
        ("off_sun_offset_min", 181, 180),
        ("off_sun_offset_min", -999, -180),
    ],
)
def test_validate_rejects_a_sun_offset_out_of_range(key: str, offset: int, edge: int) -> None:
    beyond: dict[str, Any] = {key: offset}
    settings = replace(SUN_WINDOW, **beyond)
    assert problems(settings, LIGHT) == [
        Problem(key, "out_of_range", {"setting": key, "min": "-180", "max": "180"})
    ]
    at_edge: dict[str, Any] = {key: edge}
    assert problems(replace(settings, **at_edge), LIGHT) == []


@pytest.mark.parametrize("kind", [TimeKind.SUNRISE, TimeKind.SUNSET])
@pytest.mark.parametrize("profile", [LOCK, MEDIA, GARAGE])
def test_validate_rejects_a_sun_start_without_an_on_action(
    profile: DomainProfile, kind: TimeKind
) -> None:
    starting = RoutineSettings(target_entity=f"{profile.domain}.example", on_kind=kind)
    assert problems(starting, profile) == [
        Problem("on_kind", "on_time_not_supported", {"domain": profile.domain})
    ]
    # Lock at sunset only makes a device safer: every profile takes a sun bound to end.
    ending = RoutineSettings(target_entity=f"{profile.domain}.example", off_kind=kind)
    assert problems(ending, profile) == []


def test_validate_rejects_two_equal_sun_bounds() -> None:
    same = replace(SUN_WINDOW, off_kind=TimeKind.SUNSET, off_sun_offset_min=30)
    assert problems(same, LIGHT) == [Problem("off_sun_offset_min", "same_on_and_off_time")]
    # Another offset or the other event is another time; so is a time at the nominal one.
    assert problems(replace(same, off_sun_offset_min=31), LIGHT) == []
    assert problems(replace(same, off_kind=TimeKind.SUNRISE), LIGHT) == []
    at_nominal = replace(SUN_WINDOW, on_sun_offset_min=0, off_kind=TimeKind.TIME, off_time=time(18))
    assert problems(at_nominal, LIGHT) == []
    # A stale time under a sun kind is not compared.
    stale = replace(SUN_WINDOW, on_time=time(9), off_kind=TimeKind.TIME, off_time=time(9))
    assert problems(stale, LIGHT) == []


@pytest.mark.parametrize(
    "patch", [{"on_kind": TimeKind.SUNSET}, {"off_kind": TimeKind.SUNRISE, "off_sun_offset_min": 5}]
)
def test_validate_rejects_a_sun_bound_with_a_weekly_schedule(patch: dict[str, Any]) -> None:
    weekly = RoutineSettings(
        target_entity="light.patio_light",
        days=Days.WEEKLY_SCHEDULE,
        schedule_entity="schedule.x",
        **patch,
    )
    assert problems(weekly, LIGHT) == [Problem("days", "times_with_weekly_schedule")]


def test_validate_collects_every_problem_in_order() -> None:
    bad = RoutineSettings(
        target_entity="lock.front_door",
        on_time=time(7),
        off_time=time(7),
        days=Days.SOME_DAYS,
        day_set=frozenset(),
        turn_off_after_min=30,
        turn_back_on_after_min=10,
        pulse=Pulse(time(8)),
    )
    assert [problem.translation_key for problem in problems(bad, LOCK)] == [
        "on_time_not_supported",
        "same_on_and_off_time",
        "no_days_selected",
        "duration_not_supported",
        "both_durations",
        "pulse_not_supported",
    ]


def test_compile_raises_the_first_problem() -> None:
    with pytest.raises(CompileError) as caught:
        compiler.compile(replace(WINDOW, off_time=time(17)), FAN, REFS)
    assert caught.value.translation_key == "same_on_and_off_time"
    with pytest.raises(CompileError) as caught:
        compiler.compile(RoutineSettings(target_entity="lock.x", on_time=time(7)), LOCK, REFS)
    assert caught.value.translation_key == "on_time_not_supported"
    assert caught.value.placeholders == {"domain": "lock"}


def test_every_problem_is_translated_with_its_placeholders() -> None:
    exceptions = STRINGS["exceptions"]
    assert set(exceptions) >= compiler.PROBLEM_KEYS
    samples = [
        *problems(RoutineSettings(target_entity="lock.x"), replace(LOCK, on_action="lock.unlock")),
        *problems(
            RoutineSettings(
                target_entity="lock.x",
                on_time=time(7),
                off_time=time(7),
                days=Days.SOME_DAYS,
                day_set=frozenset(),
                turn_off_after_min=30,
                turn_back_on_after_min=10,
                pulse=Pulse(time(8)),
            ),
            LOCK,
        ),
        *problems(RoutineSettings(target_entity="fan.x", days=Days.WEEKLY_SCHEDULE)),
        *problems(replace(WINDOW, days=Days.WEEKLY_SCHEDULE, schedule_entity="schedule.x")),
        *problems(replace(WINDOW, late_start_window_min=999)),
        *problems(replace(SUN_WINDOW, on_sun_offset_min=999, off_sun_offset_min=999), LIGHT),
        *problems(RoutineSettings(target_entity="lock.x", on_kind=TimeKind.SUNSET), LOCK),
        *problems(replace(SUN_WINDOW, off_kind=TimeKind.SUNSET, off_sun_offset_min=30), LIGHT),
    ]
    assert {problem.translation_key for problem in samples} | {"invalid_inputs"} == (
        compiler.PROBLEM_KEYS
    )
    for problem in samples:
        message = exceptions[problem.translation_key]["message"]
        assert message.format(**problem.placeholders)
    assert exceptions["invalid_inputs"]["message"].format()


# --------------------------------------------------------------------------------------
# Refusals (PRD 5.4): never emitted, whatever is asked
# --------------------------------------------------------------------------------------


@hypothesis_settings(max_examples=300, deadline=None)
@given(
    case=strategies.profile_cases().flatmap(
        lambda case: strategies.any_settings(case[0]).map(lambda settings: (*case, settings))
    )
)
def test_compile_never_emits_a_refused_action(
    case: tuple[DomainProfile, str | None, RoutineSettings],
) -> None:
    profile, device_class, settings = case
    try:
        inputs = compiler.compile(settings, profile, REFS).inputs
    except CompileError:
        return
    for key in ("on_action", "off_action"):
        action = inputs[key]
        assert not domains.is_refused_action(action, device_class), action
        assert action not in {"lock.unlock", "lock.open"}
        assert not action.startswith("alarm_control_panel.")
        if device_class in {"garage", "gate", "door"}:
            assert action != "cover.open_cover"
        if device_class == "gas":
            assert action != "valve.open_valve"
    assert not compiler.has_refused_action(inputs, device_class)


@pytest.mark.parametrize(
    ("domain", "device_class"),
    [("cover", "garage"), ("cover", "gate"), ("cover", "door"), ("valve", "gas")],
)
def test_a_refused_open_cannot_be_scheduled(domain: str, device_class: str) -> None:
    opening = RoutineSettings(target_entity=f"{domain}.example", on_time=time(7))
    with pytest.raises(CompileError, match="on_time_not_supported"):
        compiler.compile(opening, refused_profile(domain, device_class), REFS)


def test_has_refused_action_reads_raw_inputs() -> None:
    inputs = compiled(RoutineSettings(target_entity="lock.front_door", off_time=time(22)), LOCK)
    assert not compiler.has_refused_action(inputs, None)
    assert compiler.has_refused_action(inputs | {"on_action": "lock.unlock"}, None)
    assert compiler.has_refused_action(inputs | {"off_action": "alarm_control_panel.x"}, None)
    cover = inputs | {"on_action": "cover.open_cover"}
    assert compiler.has_refused_action(cover, "garage")
    assert not compiler.has_refused_action(cover, "shade")
    assert not compiler.has_refused_action({"on_action": 42}, None)


# --------------------------------------------------------------------------------------
# Round trips (TECH_SPEC 11.5)
# --------------------------------------------------------------------------------------


@hypothesis_settings(max_examples=400, deadline=None)
@given(case=strategies.routines(), refs=strategies.helper_refs())
def test_compile_then_decompile_is_identity(
    case: tuple[DomainProfile, str | None, RoutineSettings], refs: compiler.HelperRefs
) -> None:
    profile, _, settings = case
    assert compiler.validate(settings, profile) == []
    assert compiler.canonical(settings) == settings
    assert compiler.decompile(compiler.compile(settings, profile, refs).inputs) == settings


@hypothesis_settings(max_examples=400, deadline=None)
@given(case=strategies.routines(), refs=strategies.helper_refs())
def test_decompile_then_compile_is_identity(
    case: tuple[DomainProfile, str | None, RoutineSettings], refs: compiler.HelperRefs
) -> None:
    profile, _, settings = case
    inputs = compiler.compile(settings, profile, refs).inputs
    assert compiler.is_valid_shape(inputs)
    again = compiler.compile(compiler.decompile(inputs), profile, compiler.refs_of(inputs))
    assert again.inputs == inputs
    assert list(again.inputs) == list(inputs)


def test_canonical_names_the_day_set_and_drops_what_the_inputs_cannot_hold() -> None:
    weekdays_by_hand = replace(WINDOW, days=Days.SOME_DAYS, day_set=WEEKDAYS)
    assert compiler.canonical(weekdays_by_hand) == WINDOW
    every_day = replace(WINDOW, days=Days.SOME_DAYS, day_set=ALL_DAYS)
    assert compiler.canonical(every_day).days is Days.EVERY_DAY
    weekend = replace(WINDOW, days=Days.SOME_DAYS, day_set=frozenset({Weekday.SAT, Weekday.SUN}))
    assert compiler.canonical(weekend).days is Days.WEEKENDS
    stray_day_set = replace(WINDOW, day_set=frozenset({Weekday.TUE}))
    assert compiler.canonical(stray_day_set) == WINDOW
    stray_schedule = replace(WINDOW, schedule_entity="schedule.x")
    assert compiler.canonical(stray_schedule) == WINDOW
    precise = replace(
        WINDOW,
        on_time=time(17, 0, 5, 999, tzinfo=UTC),
        pulse=Pulse(time(8, 0, 0, 1)),
        extra_conditions=list(strategies.EXAMPLE_CONDITIONS),  # type: ignore[arg-type]
    )
    assert compiler.canonical(precise) == replace(
        WINDOW,
        on_time=time(17, 0, 5),
        pulse=Pulse(time(8)),
        extra_conditions=strategies.EXAMPLE_CONDITIONS,
    )
    for loose in (weekdays_by_hand, every_day, weekend, stray_day_set, stray_schedule, precise):
        assert compiler.decompile(compiled(loose)) == compiler.canonical(loose)
        assert compiled(loose) == compiled(compiler.canonical(loose))


def test_canonical_keeps_a_time_or_an_offset_per_side() -> None:
    """A time bound has offset 0 and a sun bound no time: the inputs hold one of them."""
    offsets_on_times = replace(WINDOW, on_sun_offset_min=20, off_sun_offset_min=-5)
    assert compiler.canonical(offsets_on_times) == WINDOW
    times_on_sun = replace(SUN_WINDOW, on_time=time(5), off_time=time(7, 0, 0, 5))
    assert compiler.canonical(times_on_sun) == SUN_WINDOW
    for loose in (offsets_on_times, times_on_sun):
        profile = FAN if loose.target_entity.startswith("fan.") else LIGHT
        assert compiler.decompile(compiled(loose, profile)) == compiler.canonical(loose)


def test_a_weekly_schedule_round_trips_through_settings_and_refs() -> None:
    weekly = RoutineSettings(
        target_entity="fan.living_room_fan",
        days=Days.WEEKLY_SCHEDULE,
        schedule_entity="schedule.my_own_schedule",
    )
    inputs = compiled(weekly)
    assert inputs["schedule_entity"] == "schedule.my_own_schedule"
    assert compiler.decompile(inputs).schedule_entity == "schedule.my_own_schedule"
    assert compiler.refs_of(inputs).schedule_entity == "schedule.my_own_schedule"
    every_day = compiled(replace(weekly, days=Days.EVERY_DAY))
    assert compiler.decompile(every_day).schedule_entity is None
    assert compiler.refs_of(every_day).schedule_entity == compiler.UNUSED_SCHEDULE


# --------------------------------------------------------------------------------------
# decompile, refs_of and is_valid_shape (sync back)
# --------------------------------------------------------------------------------------

REQUIRED = {
    "target_entity": "fan.living_room_fan",
    "on_action": "fan.turn_on",
    "off_action": "fan.turn_off",
    "inactive_state": "off",
    "device_id": "device-1",
}


def test_decompile_reads_a_form_edit_that_omits_defaults() -> None:
    assert compiler.decompile(REQUIRED) == RoutineSettings(target_entity="fan.living_room_fan")
    edited = REQUIRED | {"on_time_enabled": True, "on_time": "7:30", "turn_off_after_min": 30.0}
    assert compiler.decompile(edited) == RoutineSettings(
        target_entity="fan.living_room_fan", on_time=time(7, 30), turn_off_after_min=30
    )
    assert compiler.refs_of(REQUIRED) == compiler.HelperRefs("device-1")


@pytest.mark.parametrize(("settings", "profile"), [(WINDOW, FAN), (SUN_WINDOW, LIGHT)])
def test_inputs_written_in_another_order_read_the_same(
    settings: RoutineSettings, profile: DomainProfile
) -> None:
    """Inputs are stored flat; their order is the file order of the build that wrote them.

    A routine an older build wrote (before the form's last section, owner decision O3)
    reads the same settings and helpers, and compiling it again gives the same mapping in
    the new order, so sync back finds nothing to repair.
    """
    written = compiled(settings, profile)
    older = {key: written[key] for key in reversed(SPEC_KEYS)}
    again = compiled(compiler.decompile(older), profile, compiler.refs_of(older))

    assert list(older) != list(written)
    assert compiler.is_valid_shape(older)
    assert compiler.decompile(older) == compiler.decompile(written) == compiler.canonical(settings)
    assert compiler.refs_of(older) == compiler.refs_of(written)
    assert again == older
    assert list(again) == list(SPEC_KEYS)


def test_decompile_reads_the_primary_inputs_and_ignores_the_derived_ones() -> None:
    inputs = compiled(WINDOW) | {
        "days_start": ["sat", "sun", "sat"],
        "days_end": ["mon"],
        "crosses_midnight": False,
        "late_window_end": "12:00:00",
        "on_action": "fan.toggle",
        "on_time_enabled": False,
    }
    assert compiler.decompile(inputs) == replace(WINDOW, on_time=None, days=Days.WEEKENDS)
    some = compiled(WINDOW) | {"days_start": ["tue", "thu"]}
    assert compiler.decompile(some) == replace(
        WINDOW, days=Days.SOME_DAYS, day_set=frozenset({Weekday.TUE, Weekday.THU})
    )
    nothing = compiled(WINDOW) | {"days_start": []}
    assert compiler.decompile(nothing).days is Days.SOME_DAYS
    assert compiler.validate(compiler.decompile(nothing), FAN) == [
        Problem("day_set", "no_days_selected")
    ]
    sentinel_schedule = compiled(WINDOW) | {"schedule_enabled": True}
    assert compiler.decompile(sentinel_schedule).schedule_entity is None


def test_decompile_reads_the_primary_sun_inputs_only() -> None:
    """The kind decides a side; the sun flags and the late sun offset are never read."""
    stale = compiled(SUN_WINDOW, LIGHT) | {
        "on_at_sunset": False,
        "on_at_sunrise": True,
        "off_at_sunrise": False,
        "late_sun_offset": "05:00:00",
        "on_time_enabled": True,
        "on_time": "12:00:00",
        "crosses_midnight": False,
    }
    assert compiler.decompile(stale) == SUN_WINDOW
    # A time bound's offset is not read either.
    assert compiler.decompile(compiled(WINDOW) | {"on_sun_offset": "01:00:00"}) == WINDOW
    # A form edit that picks a kind reads it with its offset.
    edited = REQUIRED | {"off_kind": "sunrise", "off_sun_offset": "-1:30"}
    assert compiler.decompile(edited) == RoutineSettings(
        target_entity="fan.living_room_fan", off_kind=TimeKind.SUNRISE, off_sun_offset_min=-90
    )


@pytest.mark.parametrize(
    ("text", "minutes"),
    [
        ("00:00:00", 0),
        ("-00:00:00", 0),
        ("00:30:00", 30),
        ("-00:30:00", -30),
        ("03:00:00", 180),
        ("-03:00:00", -180),
        ("1:30", 90),
        ("-1:30", -90),
        ("+00:45", 45),
        ("00:30:59", 30),
        ("-00:30:59", -30),
        ("-00:00:59", 0),
    ],
)
def test_sun_offset_text_round_trips(text: str, minutes: int) -> None:
    """`compile` writes `[-]HH:MM:SS`; `decompile` also reads `H:MM` and drops seconds."""
    inputs = REQUIRED | {"on_kind": "sunset", "on_sun_offset": text}
    assert compiler.is_valid_shape(inputs)
    read = compiler.decompile(inputs)
    assert (read.on_kind, read.on_sun_offset_min) == (TimeKind.SUNSET, minutes)
    written = compiled(read)["on_sun_offset"]
    sign = "-" if minutes < 0 else ""
    assert written == f"{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}:00"
    assert compiler.decompile(compiled(read)) == read


@pytest.mark.parametrize(
    "inputs",
    [
        None,
        ["target_entity"],
        "inputs",
        REQUIRED | {"unknown_input": 1},
        {key: value for key, value in REQUIRED.items() if key != "device_id"},
        {key: value for key, value in REQUIRED.items() if key != "target_entity"},
        REQUIRED | {"target_entity": "not an entity"},
        REQUIRED | {"target_entity": 42},
        REQUIRED | {"on_action": "turn_on"},
        REQUIRED | {"device_id": ""},
        REQUIRED | {"inactive_state": None},
        REQUIRED | {"on_time_enabled": "yes"},
        REQUIRED | {"catch_up": 1},
        REQUIRED | {"turn_off_after_min": True},
        REQUIRED | {"turn_off_after_min": "30"},
        REQUIRED | {"turn_off_after_min": 30.5},
        REQUIRED | {"late_start_window_min": float("nan")},
        REQUIRED | {"on_time": "25:00:00"},
        REQUIRED | {"on_time": "17:00:00+01:00"},
        REQUIRED | {"on_time": "5 PM"},
        REQUIRED | {"pulse_at": 61200},
        REQUIRED | {"days_start": "mon"},
        REQUIRED | {"days_start": ["monday"]},
        REQUIRED | {"days_end": [1]},
        REQUIRED | {"extra_conditions": {"condition": "state"}},
        REQUIRED | {"extra_conditions": ["state"]},
        REQUIRED | {"timer_entity": None},
        REQUIRED | {"on_kind": "noon"},
        REQUIRED | {"off_kind": None},
        REQUIRED | {"on_kind": "Sunset"},
        REQUIRED | {"on_sun_offset": "30"},
        REQUIRED | {"on_sun_offset": 30},
        REQUIRED | {"on_sun_offset": "00:60:00"},
        REQUIRED | {"on_sun_offset": "00:30:60"},
        REQUIRED | {"off_sun_offset": "--00:30"},
        REQUIRED | {"off_sun_offset": "123:00:00"},
        REQUIRED | {"late_sun_offset": "soon"},
        REQUIRED | {"on_at_sunset": "true"},
        REQUIRED | {"off_at_sunrise": 1},
    ],
)
def test_is_valid_shape_rejects_unknown_missing_and_mistyped_keys(inputs: Any) -> None:
    assert not compiler.is_valid_shape(inputs)
    if isinstance(inputs, dict):
        with pytest.raises(CompileError, match="invalid_inputs"):
            compiler.decompile(inputs)
        with pytest.raises(CompileError, match="invalid_inputs"):
            compiler.refs_of(inputs)


def test_is_valid_shape_accepts_what_compile_and_the_form_write() -> None:
    assert compiler.is_valid_shape(compiled(WINDOW))
    assert compiler.is_valid_shape(compiled(SUN_WINDOW, LIGHT))
    assert compiler.is_valid_shape(REQUIRED)
    assert compiler.is_valid_shape(REQUIRED | {"on_kind": "sunrise", "on_sun_offset": "-0:05"})
    assert compiler.is_valid_shape(
        REQUIRED
        | {
            "on_time": "07:30",
            "turn_off_after_min": 30.0,
            "days_start": ("mon", "tue"),
            "extra_conditions": (),
        }
    )


# --------------------------------------------------------------------------------------
# RoutineView (TECH_SPEC 4.1)
# --------------------------------------------------------------------------------------


def test_routine_view_is_a_frozen_snapshot() -> None:
    at = datetime(2026, 10, 22, 17, tzinfo=UTC)
    view = RoutineView(
        device_id="device-1",
        device_name="Living room fan",
        area_id=None,
        automation_id=markers.automation_id("device-1"),
        automation_entity_id="automation.routine_living_room_fan",
        settings=WINDOW,
        status=Status.SKIPPING,
        enabled=True,
        paused_until=at,
        skipped_action=Occurrence(at, Verb.ON),
        next_action=None,
        sentence="Skipped, on Thu 5:00 PM",
        items=(),
        conflicts=(),
        override=False,
        last_change_source=Source.USER,
    )
    assert view.settings is WINDOW
    with pytest.raises(FrozenInstanceError):
        view.enabled = False  # type: ignore[misc]
