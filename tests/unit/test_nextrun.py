"""Next runs and expected states (TECH_SPEC 3.6), DST per decision L21.

The DST cases are the ones `tests/stage0/test_v10_schedule_dst.py` runs against the core
time trigger: same zones, same nights, same trigger times, same answers.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from hypothesis import given, settings, strategies as st
import pytest

from custom_components.device_routines import nextrun, sentence
from custom_components.device_routines.models import (
    WEEKDAYS,
    WEEKEND,
    Days,
    FollowUp,
    Occurrence,
    ParsedLine,
    PatternTrigger,
    Pulse,
    RoutineSettings,
    StateTrigger,
    SunTrigger,
    TimeKind,
    TimeTrigger,
    TimeWindow,
    Verb,
    Weekday,
)
from tests.stage0.test_v10_schedule_dst import DST_CASES, DstCase
from tests.unit import strategies

LA = ZoneInfo("America/Los_Angeles")
BERLIN = ZoneInfo("Europe/Berlin")
FAN = "fan.example_fan"


def line(*triggers: object, **extra: object) -> ParsedLine:
    return ParsedLine(
        automation_id="a",
        alias="A",
        entity_ids=(FAN,),
        verb=Verb.ON,
        triggers=triggers,  # type: ignore[arg-type]
        **extra,  # type: ignore[arg-type]
    )


def at(hour: int, minute: int = 0) -> TimeTrigger:
    return TimeTrigger(at=time(hour, minute))


# --------------------------------------------------------------------------------------
# DST, the same nights as the Stage 0 harness probe
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", DST_CASES, ids=[case.label for case in DST_CASES])
def test_dst_nights_match_the_core_time_trigger(case: DstCase) -> None:
    tz = ZoneInfo(case.zone)
    hour, minute = (int(part) for part in case.at.split(":")[:2])
    end = case.start + timedelta(hours=case.hours)

    runs = [
        occurrence.at
        for occurrence in nextrun.next_occurrences(line(at(hour, minute)), case.start)
        if occurrence.at < end
    ]

    if case.skipped:
        assert runs == []
    else:
        assert len(runs) == 2
        assert runs[0].dst() != timedelta(0)
        assert runs[1].dst() == timedelta(0)
        assert runs[1].astimezone(UTC) - runs[0].astimezone(UTC) == timedelta(hours=1)
        assert all(run.tzinfo is tz for run in runs)


def test_skipped_time_runs_again_the_next_day() -> None:
    start = datetime(2026, 3, 7, 23, tzinfo=LA)
    upcoming = nextrun.next_run(line(at(2, 30)), start)
    assert upcoming == datetime(2026, 3, 9, 2, 30, tzinfo=LA)


def test_wall_instants() -> None:
    assert nextrun.wall_instants(date(2026, 3, 29), time(2, 30), BERLIN) == []
    assert len(nextrun.wall_instants(date(2026, 10, 25), time(2, 30), BERLIN)) == 2
    assert nextrun.wall_instants(date(2026, 10, 26), time(2, 30), BERLIN) == [
        datetime(2026, 10, 26, 2, 30, tzinfo=BERLIN)
    ]


# --------------------------------------------------------------------------------------
# Fixed times, weekdays, windows, follow ups
# --------------------------------------------------------------------------------------


MONDAY_8 = datetime(2026, 10, 19, 8, tzinfo=LA)


def test_next_run_today_and_tomorrow() -> None:
    assert nextrun.next_run(line(at(9)), MONDAY_8) == datetime(2026, 10, 19, 9, tzinfo=LA)
    assert nextrun.next_run(line(at(7)), MONDAY_8) == datetime(2026, 10, 20, 7, tzinfo=LA)
    assert nextrun.next_run(line(at(8)), MONDAY_8) == datetime(2026, 10, 20, 8, tzinfo=LA)


def test_line_weekdays_and_trigger_weekdays() -> None:
    weekend = line(at(9), weekdays=WEEKEND)
    assert nextrun.next_run(weekend, MONDAY_8) == datetime(2026, 10, 24, 9, tzinfo=LA)
    wednesday = line(TimeTrigger(at=time(9), weekdays=frozenset({Weekday.WED})))
    assert nextrun.next_run(wednesday, MONDAY_8) == datetime(2026, 10, 21, 9, tzinfo=LA)


def test_window_conditions_filter_runs() -> None:
    every_hour = PatternTrigger(hours="*", minutes="0")
    night = line(every_hour, windows=(TimeWindow(after=time(22), before=time(6)),))
    assert nextrun.next_run(night, MONDAY_8) == datetime(2026, 10, 19, 22, tzinfo=LA)
    morning = line(every_hour, windows=(TimeWindow(before=time(10)),))
    assert nextrun.next_run(morning, MONDAY_8) == datetime(2026, 10, 19, 9, tzinfo=LA)
    evening = line(every_hour, windows=(TimeWindow(after=time(20)),))
    assert nextrun.next_run(evening, MONDAY_8) == datetime(2026, 10, 19, 20, tzinfo=LA)


def test_window_bounds_from_entities() -> None:
    bounded = line(at(9), windows=(TimeWindow(after="input_datetime.start"),))
    assert nextrun.next_run(bounded, MONDAY_8) is None
    lookups = nextrun.Lookups(entity_times={"input_datetime.start": time(10)})
    assert nextrun.next_run(bounded, MONDAY_8, lookups) is None
    lookups = nextrun.Lookups(
        entity_times={"input_datetime.start": datetime(2026, 10, 1, 8, 30, tzinfo=LA)}
    )
    assert nextrun.next_run(bounded, MONDAY_8, lookups) == datetime(2026, 10, 19, 9, tzinfo=LA)


@pytest.mark.parametrize(
    ("after", "before", "moment", "inside"),
    [
        (time(8), time(10), time(9), True),
        (time(8), time(10), time(10), False),
        (time(22), time(6), time(23), True),
        (time(22), time(6), time(5), True),
        (time(22), time(6), time(12), False),
        (None, None, time(12), True),
        (time(22), None, time(23), True),
        (time(22), None, time(21), False),
        (None, time(6), time(5), True),
        (None, time(6), time(7), False),
        # The core reads `before: 00:00:00` alone as the whole day (L69).
        (None, time(0), time(10), True),
        (None, time(0), time(0), True),
    ],
)
def test_in_window(after: time | None, before: time | None, moment: time, inside: bool) -> None:
    assert nextrun.in_window(moment, after, before) is inside


def test_follow_ups_are_occurrences() -> None:
    pulse = ParsedLine(
        automation_id="a",
        alias="A",
        entity_ids=(FAN,),
        verb=Verb.OFF,
        triggers=(at(9),),
        follow_ups=(FollowUp(timedelta(minutes=3), Verb.ON),),
    )
    first, second = nextrun.next_occurrences(pulse, MONDAY_8, limit=2)
    assert first == Occurrence(datetime(2026, 10, 19, 9, tzinfo=LA), Verb.OFF)
    assert second == Occurrence(datetime(2026, 10, 19, 9, 3, tzinfo=LA), Verb.ON)


def test_event_driven_and_not_understood_lines_have_no_run() -> None:
    assert nextrun.next_run(line(StateTrigger(entity=FAN, to="on")), MONDAY_8) is None
    assert nextrun.next_run(line(at(9), understood=False), MONDAY_8) is None
    # A line with a time and an event runs at the time.
    mixed = line(StateTrigger(entity=FAN, to="on"), at(9))
    assert nextrun.next_run(mixed, MONDAY_8) == datetime(2026, 10, 19, 9, tzinfo=LA)


def test_limit_and_horizon() -> None:
    every_minute = line(PatternTrigger(hours="*", minutes="*"))
    assert len(nextrun.next_occurrences(every_minute, MONDAY_8, limit=5)) == 5
    weekly = line(at(9), weekdays=frozenset({Weekday.SUN}))
    assert nextrun.next_occurrences(weekly, MONDAY_8, horizon=timedelta(days=2)) == []


# --------------------------------------------------------------------------------------
# Patterns, entity times and the sun
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("trigger", "expected"),
    [
        (PatternTrigger(hours="*", minutes="/15"), datetime(2026, 10, 19, 8, 15, tzinfo=LA)),
        (PatternTrigger(hours="/5", minutes="0"), datetime(2026, 10, 19, 10, tzinfo=LA)),
        (PatternTrigger(hours="7", minutes="30"), datetime(2026, 10, 20, 7, 30, tzinfo=LA)),
        (
            PatternTrigger(hours="*", minutes="5", seconds="30"),
            datetime(2026, 10, 19, 8, 5, 30, tzinfo=LA),
        ),
        (PatternTrigger(hours="30", minutes="0"), None),
        (PatternTrigger(hours="*", minutes="/0"), None),
        (PatternTrigger(hours="*", minutes="0", seconds="75"), None),
    ],
)
def test_patterns(trigger: PatternTrigger, expected: datetime | None) -> None:
    assert nextrun.next_run(line(trigger), MONDAY_8) == expected


def test_entity_time_triggers() -> None:
    daily = line(TimeTrigger(entity="input_datetime.wake", offset=timedelta(minutes=-15)))
    assert nextrun.next_run(daily, MONDAY_8) is None
    lookups = nextrun.Lookups(entity_times={"input_datetime.wake": time(7)})
    assert nextrun.next_run(daily, MONDAY_8, lookups) == datetime(2026, 10, 20, 6, 45, tzinfo=LA)
    once = line(TimeTrigger(entity="sensor.alarm"))
    moment = datetime(2026, 10, 21, 18, tzinfo=UTC)
    lookups = nextrun.Lookups(entity_times={"sensor.alarm": moment})
    assert nextrun.next_run(once, MONDAY_8, lookups) == moment.astimezone(LA)


def test_entity_time_trigger_with_weekday_option() -> None:
    weekday_only = line(
        TimeTrigger(entity="input_datetime.wake", weekdays=frozenset({Weekday.SAT}))
    )
    lookups = nextrun.Lookups(entity_times={"input_datetime.wake": time(7)})
    assert nextrun.next_run(weekday_only, MONDAY_8, lookups) == datetime(2026, 10, 24, 7, tzinfo=LA)


def test_sun_triggers() -> None:
    def sun(day: date, event: str) -> datetime | None:
        if day == date(2026, 10, 19):
            return None
        hour = 7 if event == "sunrise" else 18
        return datetime.combine(day, time(hour), tzinfo=LA)

    sunset = line(SunTrigger(event="sunset", offset=timedelta(minutes=-30)))
    assert nextrun.next_run(sunset, MONDAY_8) is None
    lookups = nextrun.Lookups(sun=sun)
    assert nextrun.next_run(sunset, MONDAY_8, lookups) == datetime(2026, 10, 20, 17, 30, tzinfo=LA)


# --------------------------------------------------------------------------------------
# earliest and expected_state
# --------------------------------------------------------------------------------------


def test_earliest() -> None:
    nine = datetime(2026, 10, 19, 9, tzinfo=LA)
    ten = nine + timedelta(hours=1)
    assert nextrun.earliest([]) is None
    assert nextrun.earliest([Occurrence(ten, Verb.ON), Occurrence(nine, Verb.OFF)]) == (
        Occurrence(nine, Verb.OFF)
    )
    assert nextrun.earliest([Occurrence(nine, Verb.ON), Occurrence(nine, Verb.OFF)]) == (
        Occurrence(nine, None)
    )


WINDOW = RoutineSettings(target_entity=FAN, on_time=time(17), off_time=time(9), days=Days.WEEKDAYS)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 10, 19, 8, tzinfo=LA), "off"),  # Monday: Sunday is not a start day
        (datetime(2026, 10, 19, 18, tzinfo=LA), "on"),
        (datetime(2026, 10, 20, 8, tzinfo=LA), "on"),  # Tuesday morning, Monday's window
        (datetime(2026, 10, 24, 8, tzinfo=LA), "on"),  # Saturday morning, Friday's window
        (datetime(2026, 10, 24, 18, tzinfo=LA), "off"),
        (datetime(2026, 10, 20, 12, tzinfo=LA), "off"),
    ],
)
def test_expected_state_for_a_crossing_window(moment: datetime, expected: str) -> None:
    assert nextrun.expected_state(WINDOW, moment) == expected


def test_expected_state_other_shapes() -> None:
    day = RoutineSettings(target_entity=FAN, on_time=time(9), off_time=time(17))
    assert nextrun.expected_state(day, datetime(2026, 10, 19, 12, tzinfo=LA)) == "on"
    assert nextrun.expected_state(day, datetime(2026, 10, 19, 17, tzinfo=LA)) == "off"
    one_shot = RoutineSettings(target_entity=FAN, on_time=time(9))
    assert nextrun.expected_state(one_shot, MONDAY_8) is None
    weekly = RoutineSettings(
        target_entity=FAN, days=Days.WEEKLY_SCHEDULE, schedule_entity="schedule.fan"
    )
    assert nextrun.expected_state(weekly, MONDAY_8, "on") == "on"
    assert nextrun.expected_state(weekly, MONDAY_8, "unavailable") is None
    some = RoutineSettings(
        target_entity=FAN,
        on_time=time(9),
        off_time=time(17),
        days=Days.SOME_DAYS,
        day_set=frozenset({Weekday.TUE}),
    )
    assert nextrun.expected_state(some, datetime(2026, 10, 19, 12, tzinfo=LA)) == "off"
    assert some.effective_days == frozenset({Weekday.TUE})
    assert WINDOW.effective_days == WEEKDAYS


# --------------------------------------------------------------------------------------
# Properties (TECH_SPEC 11.5): within a week, monotonic, after now
# --------------------------------------------------------------------------------------

# Hypothesis takes naive bounds and attaches the zone itself.
NAIVE_START = datetime(2026, 1, 1)  # noqa: DTZ001
NAIVE_END = datetime(2027, 12, 31)  # noqa: DTZ001
moments = st.datetimes(min_value=NAIVE_START, max_value=NAIVE_END, timezones=st.just(BERLIN))
times = st.times()
day_sets = st.frozensets(st.sampled_from(list(Weekday)), min_size=1)


@settings(max_examples=200, deadline=None)
@given(now=moments, trigger_times=st.lists(times, min_size=1, max_size=3), days=day_sets)
def test_next_runs_are_within_a_week_and_in_order(
    now: datetime, trigger_times: list[time], days: frozenset[Weekday]
) -> None:
    timed = line(*(TimeTrigger(at=t.replace(microsecond=0)) for t in trigger_times), weekdays=days)
    runs = [o.at for o in nextrun.next_occurrences(timed, now, limit=20)]

    assert runs, "a daily time runs at least once a week, DST nights included"
    assert runs[0] - now <= timedelta(days=7, hours=1)
    assert all(run > now for run in runs)
    assert runs == sorted(runs)
    assert all(Weekday.of(run) in days for run in runs)


# --------------------------------------------------------------------------------------
# Routine actions and skip targets (PRD FR-R11, D18, D19; TECH_SPEC 3.6 and 11.5)
# --------------------------------------------------------------------------------------

NIGHTLY = RoutineSettings(target_entity=FAN, on_time=time(17), off_time=time(9))
WEDNESDAY_3PM = datetime(2026, 10, 21, 15, tzinfo=LA)
THURSDAY_8AM = datetime(2026, 10, 22, 8, tzinfo=LA)
MINUTE = timedelta(minutes=1)
WRITER = sentence.Writer(sentence.load_phrases("en"), "12h")


def local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=LA)


def test_skip_target_window_start_pairs_its_end() -> None:
    """D18 and the FR-R11 acceptance: at 15:00, skip tonight's whole window."""
    target = nextrun.skip_target(NIGHTLY, WEDNESDAY_3PM)
    assert target == nextrun.SkipTarget(
        verb=Verb.ON, at=local(21, 17), paired_end=local(22, 9), paused_until=local(22, 9, 1)
    )
    following = nextrun.routine_occurrences(NIGHTLY, WEDNESDAY_3PM, not_before=target.paused_until)
    assert following[0] == Occurrence(local(22, 17), Verb.ON)
    assert WRITER.skipped(Verb.ON, following[0].at, WEDNESDAY_3PM) == "Skipped, on Thu 5:00 PM"

    daytime = RoutineSettings(
        target_entity=FAN,
        on_time=time(9),
        off_time=time(17),
        days=Days.SOME_DAYS,
        day_set=frozenset({Weekday.MON}),
    )
    assert nextrun.skip_target(daytime, local(21, 12)) == nextrun.SkipTarget(
        Verb.ON, local(26, 9), local(26, 17), local(26, 17, 1)
    )
    friday_nights = replace(NIGHTLY, days=Days.WEEKDAYS)
    assert nextrun.skip_target(friday_nights, local(23, 15)) == nextrun.SkipTarget(
        Verb.ON, local(23, 17), local(24, 9), local(24, 9, 1)
    )


def test_skip_target_window_end_alone() -> None:
    """D19: inside the window, the end is skipped alone and the device stays on."""
    assert nextrun.skip_target(NIGHTLY, THURSDAY_8AM) == nextrun.SkipTarget(
        Verb.OFF, local(22, 9), None, local(22, 9, 1)
    )
    off_only = RoutineSettings(target_entity=FAN, off_time=time(9))
    target = nextrun.skip_target(off_only, THURSDAY_8AM)
    assert target == nextrun.SkipTarget(Verb.OFF, local(22, 9), None, local(22, 9, 1))
    following = nextrun.routine_occurrences(off_only, THURSDAY_8AM, not_before=target.paused_until)
    assert WRITER.skipped(Verb.OFF, following[0].at, THURSDAY_8AM) == "Skipped, off Fri 9:00 AM"


def test_skip_target_running_countdown() -> None:
    timed = RoutineSettings(target_entity=FAN, turn_off_after_min=30)
    now = local(19, 10, 10)
    ends = local(19, 10, 30)
    assert nextrun.skip_target(timed, now, countdown_ends=ends) == nextrun.SkipTarget(
        Verb.OFF, ends, None, ends + MINUTE
    )
    in_utc = nextrun.skip_target(timed, now, countdown_ends=ends.astimezone(UTC))
    assert in_utc is not None
    assert in_utc.at == ends
    assert in_utc.at.tzinfo is LA
    kept_alive = RoutineSettings(target_entity=FAN, turn_back_on_after_min=10)
    assert nextrun.skip_target(kept_alive, now, countdown_ends=ends) == nextrun.SkipTarget(
        Verb.ON, ends, None, ends + MINUTE
    )
    assert nextrun.skip_target(timed, now, countdown_ends=now - MINUTE) is None
    # Without a duration the timer is not the routine's, so only the window counts.
    assert nextrun.skip_target(NIGHTLY, now, countdown_ends=ends) == nextrun.SkipTarget(
        Verb.ON, local(19, 17), local(20, 9), local(20, 9, 1)
    )
    sooner = replace(NIGHTLY, turn_off_after_min=30)
    assert nextrun.skip_target(sooner, local(19, 16, 50), countdown_ends=local(19, 17)) == (
        nextrun.SkipTarget(Verb.ON, local(19, 17), local(20, 9), local(20, 9, 1))
    )


def test_skip_target_pressed_twice_extends() -> None:
    first = nextrun.skip_target(NIGHTLY, WEDNESDAY_3PM)
    assert first is not None
    second = nextrun.skip_target(NIGHTLY, WEDNESDAY_3PM, first.paused_until)
    assert second == nextrun.SkipTarget(Verb.ON, local(22, 17), local(23, 9), local(23, 9, 1))
    assert nextrun.skip_target(NIGHTLY, WEDNESDAY_3PM, first.paused_until.astimezone(UTC)) == (
        second
    )
    stale = nextrun.skip_target(NIGHTLY, WEDNESDAY_3PM, WEDNESDAY_3PM - timedelta(days=3))
    assert stale == first
    # An action exactly at Paused until runs, so pressing again skips it.
    at_the_edge = nextrun.skip_target(NIGHTLY, WEDNESDAY_3PM, local(22, 17))
    assert at_the_edge is not None
    assert at_the_edge.at == local(22, 17)


def test_skip_target_one_shot_pulse_and_nothing_scheduled() -> None:
    vacuum = RoutineSettings(
        target_entity="vacuum.robot_vacuum", on_time=time(9, 45), days=Days.WEEKDAYS
    )
    assert nextrun.skip_target(vacuum, local(24, 12)) == nextrun.SkipTarget(
        Verb.START, local(26, 9, 45), None, local(26, 9, 46)
    )
    pulsed = RoutineSettings(target_entity=FAN, pulse=Pulse(time(8)))
    assert nextrun.skip_target(pulsed, local(19, 12)) == nextrun.SkipTarget(
        Verb.TOGGLE, local(20, 8), None, local(20, 8, 1)
    )
    assert nextrun.skip_target(RoutineSettings(target_entity=FAN), local(19, 12)) is None
    idle_timer = RoutineSettings(target_entity=FAN, turn_off_after_min=5)
    assert nextrun.skip_target(idle_timer, MONDAY_8) is None


def test_skip_target_follows_a_weekly_schedule_through_its_next_event() -> None:
    weekly = RoutineSettings(
        target_entity=FAN, days=Days.WEEKLY_SCHEDULE, schedule_entity="schedule.fan"
    )
    block_ends = local(19, 18)
    lookups = nextrun.Lookups(entity_times={"schedule.fan": block_ends.astimezone(UTC)})
    assert nextrun.skip_target(weekly, local(19, 12), None, "on", lookups) == nextrun.SkipTarget(
        Verb.OFF, block_ends, None, block_ends + MINUTE
    )
    # Outside a block the next change is a block start, whose end the core cannot know.
    assert nextrun.skip_target(weekly, local(19, 12), None, "off", lookups) is None
    assert nextrun.routine_occurrences(weekly, local(19, 12), "off", lookups) == [
        Occurrence(block_ends, Verb.ON)
    ]
    assert nextrun.skip_target(weekly, local(19, 12), None, "on") is None
    assert nextrun.skip_target(weekly, local(19, 12), None, "unavailable", lookups) is None
    held_time = nextrun.Lookups(entity_times={"schedule.fan": time(18)})
    assert nextrun.skip_target(weekly, local(19, 12), None, "on", held_time) is None
    unlinked = replace(weekly, schedule_entity=None)
    assert nextrun.skip_target(unlinked, local(19, 12), None, "on", lookups) is None
    timed = replace(weekly, turn_off_after_min=30)
    assert nextrun.skip_target(
        timed, local(19, 12), None, "off", lookups, countdown_ends=local(19, 12, 30)
    ) == nextrun.SkipTarget(Verb.OFF, local(19, 12, 30), None, local(19, 12, 31))


@pytest.mark.parametrize(
    ("target", "verbs"),
    [
        ("vacuum.robot_vacuum", (Verb.START, Verb.DOCK)),
        ("lawn_mower.mower", (Verb.START, Verb.DOCK)),
        ("cover.patio_shade", (Verb.OPEN, Verb.CLOSE)),
        ("valve.garden_valve", (Verb.OPEN, Verb.CLOSE)),
        ("light.patio_light", (Verb.ON, Verb.OFF)),
        ("lock.front_door", (Verb.ON, Verb.LOCK)),
        ("media_player.living_room_tv", (Verb.ON, Verb.OFF)),
        ("siren.unsupported", (Verb.ON, Verb.OFF)),
    ],
)
def test_routine_actions_use_the_domain_verbs(target: str, verbs: tuple[Verb, Verb]) -> None:
    settings = RoutineSettings(target_entity=target, on_time=time(9), off_time=time(17))
    upcoming = nextrun.routine_occurrences(settings, MONDAY_8)
    assert upcoming[:2] == [Occurrence(local(19, 9), verbs[0]), Occurrence(local(19, 17), verbs[1])]


def test_routine_occurrences_follow_the_start_day_rule() -> None:
    weekdays = replace(NIGHTLY, days=Days.WEEKDAYS)
    friday_noon = local(23, 12)
    assert [o.at for o in nextrun.routine_occurrences(weekdays, friday_noon)[:4]] == [
        local(23, 17),
        local(24, 9),  # Saturday morning ends Friday's window
        local(26, 17),  # nothing on Saturday or Sunday evening, nothing on Monday morning
        local(27, 9),
    ]


def test_routine_occurrences_follow_the_core_on_dst_nights() -> None:
    spring = RoutineSettings(target_entity=FAN, on_time=time(2, 30))
    saturday = datetime(2026, 3, 7, 23, tzinfo=LA)
    runs = nextrun.routine_occurrences(spring, saturday)
    assert runs[0].at == datetime(2026, 3, 9, 2, 30, tzinfo=LA)  # not on the 8th at all
    fall = RoutineSettings(target_entity=FAN, on_time=time(1, 30), off_time=time(4))
    halloween = datetime(2026, 10, 31, 23, tzinfo=LA)
    first, second, end = nextrun.routine_occurrences(fall, halloween)[:3]
    assert second.at.astimezone(UTC) - first.at.astimezone(UTC) == timedelta(hours=1)
    target = nextrun.skip_target(fall, halloween)
    assert target is not None
    assert (target.at, target.paired_end) == (first.at, end.at)


def seasonal_sun(day: date, event: str) -> datetime | None:
    """A sun that moves with the seasons in Berlin, as the astral helper's answer in UTC."""
    shift = timedelta(minutes=day.timetuple().tm_yday % 120)
    base = time(6) if event == "sunrise" else time(16, 30)
    return (datetime.combine(day, base, tzinfo=BERLIN) + shift).astimezone(UTC)


@settings(max_examples=300, deadline=None)
@given(
    case=strategies.routines(),
    now=moments,
    countdown_in=st.none() | st.integers(1, 1440),
    schedule_state=st.sampled_from(["on", "off", "unavailable"]),
    next_event_in=st.integers(1, 7 * 1440),
)
def test_skip_target_equals_the_sentence_action(
    case: tuple[object, object, RoutineSettings],
    now: datetime,
    countdown_in: int | None,
    schedule_state: str,
    next_event_in: int,
) -> None:
    """TECH_SPEC 11.5: what Skip next skips is the action the Schedule state shows."""
    routine = case[2]
    countdown = None if countdown_in is None else now + timedelta(minutes=countdown_in)
    lookups = nextrun.Lookups(
        sun=seasonal_sun,
        entity_times={routine.schedule_entity or "": now + timedelta(minutes=next_event_in)},
    )
    target = nextrun.skip_target(
        routine, now, None, schedule_state, lookups, countdown_ends=countdown
    )
    upcoming = nextrun.routine_occurrences(
        routine, now, schedule_state, lookups, countdown_ends=countdown
    )
    if target is None:
        assert not upcoming or (routine.days is Days.WEEKLY_SCHEDULE and schedule_state == "off")
        return
    shown = upcoming[0]
    assert (target.verb, target.at) == (shown.verb, shown.at)
    assert WRITER.state(Occurrence(target.at, target.verb), None, now) == WRITER.state(
        nextrun.earliest(upcoming[:1]), None, now
    )
    assert target.paused_until == (target.paired_end or target.at) + MINUTE
    assert target.paired_end is None or target.paired_end > target.at
    again = nextrun.skip_target(
        routine, now, target.paused_until, schedule_state, lookups, countdown_ends=countdown
    )
    assert again is None or again.at >= target.paused_until


# --------------------------------------------------------------------------------------
# Skip next outside a weekly schedule block (Build A lane 14, decision L38)
# --------------------------------------------------------------------------------------

WEEKLY = RoutineSettings(
    target_entity=FAN, days=Days.WEEKLY_SCHEDULE, schedule_entity="schedule.fan"
)


def test_weekly_blocks_read_the_schedule_list_item() -> None:
    item = {
        "id": "abc",
        "name": "Living room fan routine",
        "monday": [{"from": "17:00:00", "to": "22:00:00"}, {"from": "22:00:00", "to": "24:00:00"}],
        "tuesday": [{"from": "00:00", "to": "02:00:00"}],
        "wednesday": [],
        "friday": [{"from": "nonsense", "to": "02:00:00"}, {"to": "03:00:00"}, "nothing"],
        "saturday": "not a list",
    }

    assert nextrun.weekly_blocks(item) == {
        Weekday.MON: ((time(17), time(22)), (time(22), time.max)),
        Weekday.TUE: ((time(0), time(2)),),
    }
    assert nextrun.weekly_blocks({}) == {}


def test_block_bounds_find_the_block_starting_at_the_next_event() -> None:
    blocks = {
        Weekday.MON: ((time(8), time(9)), (time(17), time(22))),
        Weekday.TUE: ((time(17), time(19)), (time(19), time(21, 30))),
        Weekday.SAT: ((time(22), time.max),),
        Weekday.SUN: ((time(0), time(2)),),
        Weekday.WED: ((time(23), time.max),),
    }
    # Monday 2026-10-19.
    assert nextrun.block_bounds(blocks, local(19, 17)) == (local(19, 17), local(19, 22))
    # Blocks that meet are one block, as the schedule stays on between them (A6).
    assert nextrun.block_bounds(blocks, local(20, 17)) == (local(20, 17), local(20, 21, 30))
    assert nextrun.block_bounds(blocks, local(24, 22)) == (local(24, 22), local(25, 2))
    # A block that ends at midnight with nothing after it ends at midnight.
    assert nextrun.block_bounds(blocks, local(21, 23)) == (local(21, 23), local(22, 0))
    # A start the blocks do not hold is unknown.
    assert nextrun.block_bounds(blocks, local(19, 18)) is None
    assert nextrun.block_bounds({}, local(19, 17)) is None
    # The answer is in the zone of the start, whatever zone the start came in.
    found = nextrun.block_bounds(blocks, local(19, 17))
    assert found is not None
    assert found[1].tzinfo is LA
    # A schedule that never ends has no block end.
    always = {day: ((time(0), time.max),) for day in Weekday}
    assert nextrun.block_bounds(always, local(19, 0)) is None


def test_block_bounds_follow_the_wall_clock_across_a_dst_night() -> None:
    blocks = {Weekday.SAT: ((time(22), time.max),), Weekday.SUN: ((time(0), time(4)),)}
    # Saturday 2026-10-31 22:00 to Sunday 04:00, the fall back night in Los Angeles.
    start = datetime(2026, 10, 31, 22, tzinfo=LA)
    assert nextrun.block_bounds(blocks, start) == (start, datetime(2026, 11, 1, 4, tzinfo=LA))
    end = nextrun.block_bounds(blocks, start)
    assert end is not None
    assert end[1].utcoffset() == timedelta(hours=-8)


def test_next_block_is_the_first_whole_block_starting_at_or_after_a_moment() -> None:
    """Plan A4.0 item 13 (L53): what runs after a skipped block, and what Skip next skips next."""
    blocks = {
        Weekday.MON: ((time(8), time(9)), (time(17), time(22))),
        Weekday.TUE: ((time(17), time(19)), (time(19), time(21, 30))),
        Weekday.SAT: ((time(22), time.max),),
        Weekday.SUN: ((time(0), time(2)),),
    }
    # Monday 2026-10-19, one minute after the evening block ends: Tuesday's evening.
    assert nextrun.next_block(blocks, local(19, 22, 1)) == (local(20, 17), local(20, 21, 30))
    # A block starting at the moment counts; one that started before does not.
    assert nextrun.next_block(blocks, local(19, 17)) == (local(19, 17), local(19, 22))
    assert nextrun.next_block(blocks, local(19, 8, 30)) == (local(19, 17), local(19, 22))
    # A block that continues another (19:00 on Tuesday, Sunday 00:00) starts nothing.
    assert nextrun.next_block(blocks, local(20, 18)) == (local(24, 22), local(25, 2))
    assert nextrun.next_block(blocks, local(24, 23)) == (local(26, 8), local(26, 9))
    # The moment's zone is the wall clock the blocks are read in, and the answer's zone.
    found = nextrun.next_block(blocks, local(19, 22, 1))
    assert found is not None
    assert found[0].tzinfo is LA
    # No blocks, or blocks that never end, have no next block.
    assert nextrun.next_block({}, local(19, 12)) is None
    always = {day: ((time(0), time.max),) for day in Weekday}
    assert nextrun.next_block(always, local(19, 12)) is None


def test_skip_target_skips_a_block_start_with_its_end() -> None:
    """L38: outside a block, Skip next skips the next block's start and its end (D18)."""
    block_starts = local(19, 17)
    lookups = nextrun.Lookups(entity_times={"schedule.fan": block_starts.astimezone(UTC)})
    block = (block_starts, local(19, 22))

    target = nextrun.skip_target(WEEKLY, local(19, 12), None, "off", lookups, block=block)

    assert target == nextrun.SkipTarget(Verb.ON, block_starts, local(19, 22), local(19, 22, 1))
    assert target.at.tzinfo is LA
    # The block given in another zone is the same block.
    in_utc = (block_starts.astimezone(UTC), local(19, 22).astimezone(UTC))
    utc_target = nextrun.skip_target(WEEKLY, local(19, 12), None, "off", lookups, block=in_utc)
    assert utc_target == target
    assert utc_target is not None
    assert utc_target.paired_end is not None
    assert utc_target.paired_end.tzinfo is LA
    # A block that does not start at the next change is not that block.
    stale = (local(20, 17), local(20, 22))
    assert nextrun.skip_target(WEEKLY, local(19, 12), None, "off", lookups, block=stale) is None
    # Inside a block the end is skipped alone, whatever block is given (D19).
    ends = nextrun.skip_target(WEEKLY, local(19, 12), None, "on", lookups, block=block)
    assert ends == nextrun.SkipTarget(Verb.OFF, block_starts, None, block_starts + MINUTE)
    # Without the block, a block start still cannot be skipped.
    assert nextrun.skip_target(WEEKLY, local(19, 12), None, "off", lookups) is None


# --------------------------------------------------------------------------------------
# Sun relative bounds (FR-R10, decision L60)
# --------------------------------------------------------------------------------------

LIGHT = "light.patio_light"
# Sunset to sunrise on weekdays: Friday's sunset starts a window Saturday's sunrise ends.
SUN_NIGHTS = RoutineSettings(
    target_entity=LIGHT,
    days=Days.WEEKDAYS,
    on_kind=TimeKind.SUNSET,
    on_sun_offset_min=30,
    off_kind=TimeKind.SUNRISE,
    off_sun_offset_min=-15,
)
SUN_DAYS = RoutineSettings(
    target_entity=LIGHT,
    on_kind=TimeKind.SUNRISE,
    on_sun_offset_min=30,
    off_kind=TimeKind.SUNSET,
    off_sun_offset_min=-30,
)


def la_sun(day: date, event: str) -> datetime | None:
    """Sunrise at 07:00 and sunset at 18:00 in Los Angeles, answered in UTC; none on the 30th."""
    if day == date(2026, 10, 30):
        return None
    at = time(7) if event == "sunrise" else time(18)
    return datetime.combine(day, at, tzinfo=LA).astimezone(UTC)


SUN = nextrun.Lookups(sun=la_sun)


def in_zone(moment: datetime | None, tz: ZoneInfo) -> datetime | None:
    return None if moment is None else moment.astimezone(tz)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (local(19, 7, 29), "off"),
        (local(19, 7, 30), "on"),  # sunrise plus 30
        (local(19, 12), "on"),
        (local(19, 17, 29), "on"),
        (local(19, 17, 30), "off"),  # sunset minus 30
        (local(19, 23), "off"),
    ],
)
def test_expected_state_sun_window_same_day(moment: datetime, expected: str) -> None:
    assert nextrun.expected_state(SUN_DAYS, moment, None, SUN) == expected
    # The lookup's zone does not matter: the bounds are read in the zone of now.
    in_berlin = nextrun.Lookups(sun=lambda day, event: in_zone(la_sun(day, event), BERLIN))
    assert nextrun.expected_state(SUN_DAYS, moment, None, in_berlin) == expected


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (local(19, 2), "off"),  # Monday night: Sunday is not a start day
        (local(19, 18, 29), "off"),
        (local(19, 18, 30), "on"),  # Monday's sunset plus 30
        (local(20, 6, 44), "on"),  # Tuesday before sunrise minus 15 ends Monday's window
        (local(20, 6, 45), "off"),
        (local(23, 20), "on"),  # Friday evening
        (local(24, 2), "on"),  # Saturday 02:00, Friday's window
        (local(24, 8), "off"),
        (local(24, 20), "off"),  # Saturday's sunset does nothing
        (local(25, 2), "off"),  # nor does it make Sunday 02:00 on
    ],
)
def test_expected_state_sunset_to_sunrise_crossing_with_weekdays(
    moment: datetime, expected: str
) -> None:
    assert SUN_NIGHTS.crosses_midnight
    assert nextrun.expected_state(SUN_NIGHTS, moment, None, SUN) == expected


def test_expected_state_mixes_a_time_and_a_sun_bound() -> None:
    late_nights = RoutineSettings(LIGHT, on_time=time(22), off_kind=TimeKind.SUNRISE)
    assert late_nights.crosses_midnight
    assert nextrun.expected_state(late_nights, local(19, 23), None, SUN) == "on"
    assert nextrun.expected_state(late_nights, local(20, 6, 59), None, SUN) == "on"
    assert nextrun.expected_state(late_nights, local(20, 7), None, SUN) == "off"
    evenings = RoutineSettings(LIGHT, on_kind=TimeKind.SUNSET, off_time=time(23))
    assert not evenings.crosses_midnight
    assert nextrun.expected_state(evenings, local(19, 17, 59), None, SUN) == "off"
    assert nextrun.expected_state(evenings, local(19, 18), None, SUN) == "on"
    assert nextrun.expected_state(evenings, local(19, 23), None, SUN) == "off"
    assert nextrun.expected_state(evenings, local(20, 1), None, SUN) == "off"


def test_expected_state_without_sun_lookup_is_none() -> None:
    for lookups in (None, nextrun.Lookups(), nextrun.Lookups(entity_times={"x.y": time(7)})):
        assert nextrun.expected_state(SUN_DAYS, local(19, 12), None, lookups) is None
        assert nextrun.expected_state(SUN_NIGHTS, local(23, 20), None, lookups) is None
    # A day without a sunset (the lookup's 30th): the window that needs it reads None.
    assert nextrun.expected_state(SUN_DAYS, local(30, 12), None, SUN) is None
    assert nextrun.expected_state(SUN_NIGHTS, local(30, 22), None, SUN) is None
    # Saturday 02:00 after a Friday without sunrise or sunset needs Saturday's sunrise only.
    assert nextrun.expected_state(SUN_NIGHTS, local(31, 2), None, SUN) == "on"
    # A day no half of the window applies to needs no sun time at all.
    assert nextrun.expected_state(SUN_NIGHTS, local(25, 2)) == "off"
    mondays = replace(SUN_DAYS, days=Days.SOME_DAYS, day_set=frozenset({Weekday.MON}))
    assert nextrun.expected_state(mondays, local(21, 12)) == "off"
    # Time bounds never need the sun.
    assert nextrun.expected_state(NIGHTLY, local(21, 18)) == "on"
    one_sided = RoutineSettings(LIGHT, on_kind=TimeKind.SUNSET)
    assert nextrun.expected_state(one_sided, local(21, 19), None, SUN) is None


def test_occurrences_place_sun_actions_on_their_days() -> None:
    friday_noon = local(23, 12)
    upcoming = nextrun.routine_occurrences(SUN_NIGHTS, friday_noon, None, SUN)
    assert upcoming[:5] == [
        Occurrence(local(23, 18, 30), Verb.ON),  # Friday's sunset plus 30
        Occurrence(local(24, 6, 45), Verb.OFF),  # Saturday's sunrise minus 15
        Occurrence(local(26, 18, 30), Verb.ON),  # nothing at the weekend
        Occurrence(local(27, 6, 45), Verb.OFF),
        Occurrence(local(27, 18, 30), Verb.ON),
    ]
    assert all(occurrence.at.tzinfo is LA for occurrence in upcoming)
    # A day the lookup has no sun time for (the 30th) has no sun action.
    days = [o.at.date() for o in nextrun.routine_occurrences(SUN_DAYS, local(29, 12), None, SUN)]
    assert date(2026, 10, 30) not in days
    assert days[:3] == [date(2026, 10, 29), date(2026, 10, 31), date(2026, 10, 31)]
    # Without the sun the sun bounds have no action, but a pulse still runs.
    assert nextrun.routine_occurrences(SUN_NIGHTS, friday_noon) == []
    pulsed = replace(SUN_NIGHTS, pulse=Pulse(time(13)))
    assert nextrun.routine_occurrences(pulsed, friday_noon)[0] == Occurrence(
        local(23, 13), Verb.TOGGLE
    )


def test_sun_actions_follow_the_lookup_on_dst_nights() -> None:
    """A sun bound is the lookup's instant plus the offset, on the 2026 US and EU nights."""

    def wall_sun(tz: ZoneInfo, sunset: time) -> nextrun.SunLookup:
        def sun(day: date, event: str) -> datetime | None:
            at = time(6, 40) if event == "sunrise" else sunset
            return datetime.combine(day, at, tzinfo=tz).astimezone(UTC)

        return sun

    for tz, saturday in ((LA, date(2026, 3, 7)), (BERLIN, date(2026, 3, 28))):
        lookups = nextrun.Lookups(sun=wall_sun(tz, time(18, 5)))
        dusk = RoutineSettings(LIGHT, on_kind=TimeKind.SUNSET, on_sun_offset_min=30)
        now = datetime.combine(saturday, time(12), tzinfo=tz)
        first, second = nextrun.routine_occurrences(dusk, now, None, lookups)[:2]
        assert first.at == datetime.combine(saturday, time(18, 35), tzinfo=tz)
        assert second.at == datetime.combine(saturday + timedelta(days=1), time(18, 35), tzinfo=tz)
        assert second.at.utcoffset() - first.at.utcoffset() == timedelta(hours=1)  # type: ignore[operator]
    # The fall back night: sunrise minus 180 lands after the repeated hour, once.
    lookups = nextrun.Lookups(sun=wall_sun(LA, time(17)))
    dawn = RoutineSettings(LIGHT, off_kind=TimeKind.SUNRISE, off_sun_offset_min=-180)
    halloween = datetime(2026, 10, 31, 23, tzinfo=LA)
    first, second = nextrun.routine_occurrences(dawn, halloween, None, lookups)[:2]
    assert first.at == datetime(2026, 11, 1, 3, 40, tzinfo=LA)
    assert first.at.utcoffset() == timedelta(hours=-8)
    assert second.at - first.at == timedelta(days=1)


def test_skip_target_sun_start_pairs_its_end() -> None:
    """D18 for a sun window: at 15:00, skip tonight's sunset start and the sunrise end."""
    wednesday = replace(SUN_NIGHTS, days=Days.EVERY_DAY)
    target = nextrun.skip_target(wednesday, WEDNESDAY_3PM, None, None, SUN)
    assert target == nextrun.SkipTarget(
        verb=Verb.ON,
        at=local(21, 18, 30),
        paired_end=local(22, 6, 45),
        paused_until=local(22, 6, 46),
    )
    following = nextrun.routine_occurrences(
        wednesday, WEDNESDAY_3PM, None, SUN, not_before=target.paused_until
    )
    assert following[0] == Occurrence(local(22, 18, 30), Verb.ON)
    assert WRITER.skipped(Verb.ON, following[0].at, WEDNESDAY_3PM) == "Skipped, on Thu 6:30 PM"
    # Inside the window the end is skipped alone (D19).
    assert nextrun.skip_target(wednesday, local(22, 2), None, None, SUN) == nextrun.SkipTarget(
        Verb.OFF, local(22, 6, 45), None, local(22, 6, 46)
    )
    # Without the sun nothing is scheduled to skip.
    assert nextrun.skip_target(wednesday, WEDNESDAY_3PM) is None


def test_routine_lines_read_sun_bounds() -> None:
    on, off = nextrun.routine_lines(SUN_NIGHTS, "a", "Routine: Patio light")
    assert on.triggers == (SunTrigger("sunset", timedelta(minutes=30)),)
    assert (on.verb, on.weekdays) == (Verb.ON, WEEKDAYS)
    assert off.triggers == (SunTrigger("sunrise", timedelta(minutes=-15)),)
    # The end runs the day after each start day.
    assert (off.verb, off.weekdays) == (Verb.OFF, frozenset(day.following for day in WEEKDAYS))
    every_day = nextrun.routine_lines(replace(SUN_NIGHTS, days=Days.EVERY_DAY), "a", "A")
    assert [line.weekdays for line in every_day] == [None, None]
    # A time keeps its days on its trigger, next to a sun bound.
    mixed = RoutineSettings(LIGHT, on_time=time(22), off_kind=TimeKind.SUNRISE, days=Days.WEEKENDS)
    start, end = nextrun.routine_lines(mixed, "a", "A")
    assert start.triggers == (TimeTrigger(at=time(22), weekdays=WEEKEND),)
    assert start.weekdays is None
    assert end.triggers == (SunTrigger("sunrise", timedelta(0)),)
    assert end.weekdays == frozenset({Weekday.SUN, Weekday.MON})
    # The lines run when the routine's own actions do.
    friday_noon = local(23, 12)
    from_lines = sorted(
        (o for line in (on, off) for o in nextrun.next_occurrences(line, friday_noon, SUN)),
        key=lambda occurrence: occurrence.at,
    )
    own = nextrun.routine_occurrences(SUN_NIGHTS, friday_noon, None, SUN)
    assert from_lines[:6] == own[:6]
