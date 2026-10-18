"""Next runs and expected states (TECH_SPEC 3.6), DST per decision L21.

The DST cases are the ones `tests/stage0/test_v10_schedule_dst.py` runs against the core
time trigger: same zones, same nights, same trigger times, same answers.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from hypothesis import given, settings, strategies as st
import pytest

from custom_components.device_routines import nextrun
from custom_components.device_routines.models import (
    WEEKDAYS,
    WEEKEND,
    Days,
    FollowUp,
    Occurrence,
    ParsedLine,
    PatternTrigger,
    RoutineSettings,
    StateTrigger,
    SunTrigger,
    TimeTrigger,
    TimeWindow,
    Verb,
    Weekday,
)
from tests.stage0.test_v10_schedule_dst import DST_CASES, DstCase

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
