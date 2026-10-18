"""Every sentence the summary writes (TECH_SPEC 3.8, PRD FR-S2 and FR-S4)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, time, timedelta
from itertools import product
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.device_routines import markers, parser, sentence
from custom_components.device_routines.models import (
    WEEKDAYS,
    WEEKEND,
    CalendarTrigger,
    DeviceContext,
    EntityRef,
    FollowUp,
    NamedTrigger,
    NumericTrigger,
    Occurrence,
    ParsedLine,
    PatternTrigger,
    StartTrigger,
    StateTrigger,
    SunTrigger,
    TimeTrigger,
    TimeWindow,
    Verb,
    Weekday,
)
from custom_components.device_routines.parser_grammar import NAMED_TRIGGERS

LA = ZoneInfo("America/Los_Angeles")
FAN = "fan.example_fan"
DOOR = "binary_sensor.example_door"
NAMES = {DOOR: "Front door", "sensor.example_temperature": "Temperature"}
PHRASES = sentence.load_phrases("en")
NOW = datetime(2026, 10, 19, 8, tzinfo=LA)  # a Monday


class Recording(Mapping[str, str]):
    """A phrase table that remembers which keys were read."""

    def __init__(self, phrases: Mapping[str, str]) -> None:
        self.phrases = phrases
        self.used: set[str] = set()

    def __getitem__(self, key: str) -> str:
        self.used.add(key)
        return self.phrases[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.phrases)

    def __len__(self) -> int:
        return len(self.phrases)


def writer(time_format: str = "12h", phrases: Mapping[str, str] = PHRASES) -> sentence.Writer:
    return sentence.Writer(phrases, time_format, NAMES)


def line(*triggers: Any, verb: Verb | None = Verb.OFF, **extra: Any) -> ParsedLine:
    return ParsedLine(
        automation_id="a1",
        alias="Example",
        entity_ids=(FAN,),
        verb=verb,
        triggers=triggers,
        **extra,
    )


# --------------------------------------------------------------------------------------
# Values
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("moment", "twelve", "twenty_four"),
    [
        (time(9), "9:00 AM", "09:00"),
        (time(0, 5), "12:05 AM", "00:05"),
        (time(12), "12:00 PM", "12:00"),
        (time(17, 30, 15), "5:30:15 PM", "17:30:15"),
    ],
)
def test_clock(moment: time, twelve: str, twenty_four: str) -> None:
    assert writer("12h").clock(moment) == twelve
    assert writer("24h").clock(moment) == twenty_four


def test_an_unknown_time_format_is_refused() -> None:
    with pytest.raises(ValueError, match="auto"):
        sentence.Writer(PHRASES, "auto")


@pytest.mark.parametrize(
    ("period", "text"),
    [
        (timedelta(minutes=3), "3 min"),
        (timedelta(minutes=60), "60 min"),
        (timedelta(minutes=90), "90 min"),
        (timedelta(hours=2), "2 h"),
        (timedelta(hours=2, minutes=30), "2 h 30 min"),
        (timedelta(seconds=65), "1 min 5 s"),
        (timedelta(0), "0 s"),
        (timedelta(minutes=-30), "30 min"),
    ],
)
def test_duration(period: timedelta, text: str) -> None:
    assert writer().duration(period) == text


@pytest.mark.parametrize(
    ("days", "text"),
    [
        (WEEKDAYS, "Weekdays"),
        (WEEKEND, "Weekends"),
        (frozenset({Weekday.FRI, Weekday.MON, Weekday.WED}), "Mon, Wed, Fri"),
        (frozenset(), "No days"),
    ],
)
def test_days(days: frozenset[Weekday], text: str) -> None:
    assert writer().days(days) == text


# --------------------------------------------------------------------------------------
# Lines
# --------------------------------------------------------------------------------------


LINE_CASES = [
    (
        line(
            StateTrigger(entity=DOOR),
            StateTrigger(entity="input_boolean.guest"),
            StartTrigger("start"),
            StateTrigger(entity="sensor.example_temperature"),
            StateTrigger(entity=DOOR, to="on"),
            StateTrigger(entity=DOOR),
            verb=Verb.ON,
        ),
        (
            "When Front door, input_boolean.guest or Temperature changes or when Home Assistant"
            " starts or when Front door turns on: on"
        ),
    ),
    (
        line(
            TimeTrigger(at=time(9, 45)),
            TimeTrigger(at=time(10)),
            verb=Verb.START,
            weekdays=WEEKDAYS,
            condition_count=7,
        ),
        "Weekdays 9:45 AM, 10:00 AM: start (if 7 conditions pass)",
    ),
    (
        line(TimeTrigger(at=time(8)), follow_ups=(FollowUp(timedelta(minutes=3), Verb.ON),)),
        "8:00 AM: off for 3 min, then on",
    ),
    (
        line(StateTrigger(entity=FAN, to="on", duration=timedelta(minutes=60))),
        "Off 60 min after it turns on",
    ),
    (
        line(
            StateTrigger(entity=FAN, to="off", duration=timedelta(minutes=5)),
            verb=Verb.ON,
            condition_count=1,
            custom_logic=True,
        ),
        "On 5 min after it turns off (if 1 condition passes), plus custom logic",
    ),
    (
        line(TimeTrigger(at=time(17), weekdays=frozenset({Weekday.SAT})), TimeTrigger(at=time(9))),
        "Sat 5:00 PM or 9:00 AM: off",
    ),
    (
        line(StateTrigger(entity=DOOR, to="on"), verb=Verb.ON, weekdays=WEEKEND),
        "When Front door turns on, Weekends only: on",
    ),
    (
        line(
            StateTrigger(entity=DOOR, to="open"),
            windows=(TimeWindow(after=time(17), before=time(9)),),
        ),
        "When Front door changes to open, between 5:00 PM and 9:00 AM: off",
    ),
    (
        line(StartTrigger("start"), windows=(TimeWindow(after="input_datetime.start"),)),
        "When Home Assistant starts, after the time in input_datetime.start: off",
    ),
    (
        line(StartTrigger("shutdown"), windows=(TimeWindow(before=time(6)),)),
        "When Home Assistant stops, before 6:00 AM: off",
    ),
    (line(SunTrigger("sunset", timedelta(minutes=-30)), verb=Verb.ON), "Sunset - 30 min: on"),
    (line(SunTrigger("sunrise", timedelta(minutes=15))), "Sunrise + 15 min: off"),
    (
        line(TimeTrigger(entity="input_datetime.wake", weekdays=WEEKDAYS)),
        "Weekdays the time in input_datetime.wake: off",
    ),
    (line(TimeTrigger(entity="input_datetime.wake")), "The time in input_datetime.wake: off"),
    (line(PatternTrigger("*", "/5")), "Every 5 min: off"),
    (line(PatternTrigger("*", "*")), "Every minute: off"),
    (line(PatternTrigger("*", "7")), "Every hour at :07: off"),
    (line(PatternTrigger("7", "30")), "7:30 AM: off"),
    (line(PatternTrigger("/2", "0")), "On a time pattern: off"),
    (line(PatternTrigger("*", "0", "30")), "On a time pattern: off"),
    (line(PatternTrigger("30", "0")), "On a time pattern: off"),
    (
        line(NumericTrigger("sensor.example_temperature", above=28, duration=timedelta(minutes=3))),
        "When Temperature rises above 28 for 3 min: off",
    ),
    (
        line(NumericTrigger("sensor.example_temperature", below=25.5)),
        "When Temperature drops below 25.5: off",
    ),
    (
        line(NumericTrigger("sensor.example_temperature", above=1, below=2)),
        "When Temperature is between 1 and 2: off",
    ),
    (
        line(CalendarTrigger("calendar.work", "start", timedelta(minutes=-10)), verb=Verb.ON),
        "At the start of calendar.work events - 10 min: on",
    ),
    (line(CalendarTrigger("calendar.work", "end")), "At the end of calendar.work events: off"),
    (
        line(NamedTrigger("timer.finished", ("timer.a", "timer.b"))),
        "When timer.a or timer.b finishes: off",
    ),
    (line(NamedTrigger("schedule.block_started")), "When a block of any target starts: off"),
    (line(StateTrigger(entity=DOOR, from_state="on")), "When Front door changes from on: off"),
    (line(StateTrigger(entity=DOOR)), "When Front door changes: off"),
    (line(StateTrigger(entity=DOOR, to="off", from_state="on")), "When Front door turns off: off"),
    (
        line(StateTrigger(entity=FAN, to="on", from_state="unavailable")),
        "When it changes from unavailable to on: off",
    ),
    (
        line(StateTrigger(FAN, to="on", from_state="unavailable", duration=timedelta(seconds=10))),
        "When it changes from unavailable to on for 10 s: off",
    ),
    (
        line(StateTrigger(FAN, from_state="unavailable", duration=timedelta(seconds=10))),
        "When it has not been unavailable for 10 s: off",
    ),
    (
        line(StateTrigger(FAN, to="heat", duration=timedelta(minutes=5))),
        "When it is heat for 5 min: off",
    ),
    (
        line(StateTrigger(FAN, duration=timedelta(minutes=5))),
        "When it stays the same for 5 min: off",
    ),
    (
        line(StateTrigger(DOOR, to="off", duration=timedelta(minutes=5))),
        "When Front door is off for 5 min: off",
    ),
    (line(understood=False), "Automation: Example (custom logic)"),
    (line(TimeTrigger(at=time(9)), verb=None), "Automation: Example (custom logic)"),
]


@pytest.mark.parametrize(("parsed", "text"), LINE_CASES)
def test_lines(parsed: ParsedLine, text: str) -> None:
    assert writer().line(parsed) == text


def test_the_after_form_needs_exactly_that_shape() -> None:
    held = StateTrigger(entity=FAN, to="on", duration=timedelta(minutes=60))
    assert writer().line(line(held, weekdays=WEEKDAYS)) == (
        "When it is on for 60 min, Weekdays only: off"
    )
    other = StateTrigger(entity=DOOR, to="on", duration=timedelta(minutes=60))
    assert writer().line(line(other)) == "When Front door is on for 60 min: off"


def test_lines_from_the_parser_in_24_hour_format() -> None:
    device = DeviceContext("d", (EntityRef(FAN),))
    config = {
        "triggers": [{"trigger": "time", "at": "17:00"}],
        "conditions": [{"condition": "time", "weekday": ["mon", "wed"]}],
        "actions": [{"action": "fan.turn_on", "target": {"entity_id": FAN}}],
    }
    (parsed,) = parser.summarize(config, device)
    assert writer("24h").line(parsed) == "Mon, Wed 17:00: on"


def summarized(trigger: dict[str, Any]) -> str:
    """The line of an automation that turns the fan on, from the parser to the writer."""
    device = DeviceContext("d", (EntityRef(FAN),))
    config = {
        "triggers": [trigger],
        "actions": [{"action": "fan.turn_on", "target": {"entity_id": FAN}}],
    }
    (parsed,) = parser.summarize(config, device)
    return writer().line(parsed)


def test_a_state_trigger_with_several_states_reads_one_clause_per_state() -> None:
    assert summarized(
        {"trigger": "state", "entity_id": [DOOR, "binary_sensor.b"], "to": ["on", "off"]}
    ) == (
        "When Front door or binary_sensor.b turns on"
        " or when Front door or binary_sensor.b turns off: on"
    )
    assert summarized(
        {"trigger": "state", "entity_id": DOOR, "to": ["unavailable", "unknown"], "for": 600}
    ) == ("When Front door is unavailable for 10 min or when Front door is unknown for 10 min: on")


# --------------------------------------------------------------------------------------
# The sensor state and its cap
# --------------------------------------------------------------------------------------


def test_state_today_other_day_and_fallbacks() -> None:
    today = Occurrence(datetime(2026, 10, 19, 9, tzinfo=LA), Verb.OFF)
    wednesday = Occurrence(datetime(2026, 10, 21, 9, 45, tzinfo=LA), Verb.START)
    undecided = Occurrence(datetime(2026, 10, 19, 9, tzinfo=LA), None)
    w = writer()
    assert w.state(today, None, NOW) == "Off at 9:00 AM"
    assert w.state(wednesday, None, NOW) == "Start Wed 9:45 AM"
    assert w.state(undecided, None, NOW) == "Next: 9:00 AM"
    assert w.state(None, "When Front door turns on: on", NOW) == "When Front door turns on: on"
    assert w.state(None, "x" * 50, NOW) == "x" * 37 + "..."
    assert w.state(None, None, NOW) is None


def test_the_cap_drops_the_weekday_then_falls_back_to_next() -> None:
    long_verbs = {**PHRASES, "state_verb_dock": "A very long translated verb for docking"}
    w = sentence.Writer(long_verbs, "12h")
    friday = Occurrence(datetime(2026, 10, 23, 9, tzinfo=LA), Verb.DOCK)
    assert w.state(friday, None, NOW) == "Next: 9:00 AM"
    medium = {**PHRASES, "state_verb_dock": "Return to the dock now please"}
    w = sentence.Writer(medium, "12h")
    assert w.state(friday, None, NOW) == "Return to the dock now please 9:00 AM"


def test_every_state_combination_fits_the_cap() -> None:
    """TECH_SPEC 3.8: every verb, weekday, time and format, today and on another day."""
    w12, w24 = writer("12h"), writer("24h")
    moments = [
        datetime(2026, 10, 19 + day, hour, minute, tzinfo=LA)
        for day, hour, minute in product(range(7), range(24), (0, 59))
    ]
    for verb, moment, w in product([*Verb, None], moments, (w12, w24)):
        text = w.state(Occurrence(moment, verb), None, NOW)
        assert text is not None
        assert len(text) <= sentence.STATE_CAP, text


# --------------------------------------------------------------------------------------
# Routine states (PRD FR-S4): skipped, paused, off
# --------------------------------------------------------------------------------------

WEDNESDAY_3PM = datetime(2026, 10, 21, 15, tzinfo=LA)


def test_state_reads_skipped_paused_and_off_under_40_characters() -> None:
    w = writer()
    thursday_5pm = datetime(2026, 10, 22, 17, tzinfo=LA)
    sunday_6pm = datetime(2026, 10, 25, 18, tzinfo=LA)
    tonight = datetime(2026, 10, 21, 18, tzinfo=LA)
    assert w.skipped(Verb.ON, thursday_5pm, WEDNESDAY_3PM) == "Skipped, on Thu 5:00 PM"
    assert w.skipped(Verb.OFF, tonight, WEDNESDAY_3PM) == "Skipped, off 6:00 PM"
    assert w.skipped(Verb.DOCK, thursday_5pm, WEDNESDAY_3PM) == (
        "Skipped, return to dock Thu 5:00 PM"
    )
    assert w.paused(sunday_6pm, WEDNESDAY_3PM) == "Paused until Sun 6:00 PM"
    assert w.paused(sunday_6pm.astimezone(UTC), WEDNESDAY_3PM) == "Paused until Sun 6:00 PM"
    assert w.paused(tonight, WEDNESDAY_3PM) == "Paused until 6:00 PM"
    # A week or more away the weekday would be ambiguous, so the date shows instead.
    next_wednesday = datetime(2026, 10, 28, 18, tzinfo=LA)
    assert w.paused(next_wednesday, WEDNESDAY_3PM) == "Paused until 2026-10-28 6:00 PM"
    assert w.routine_off() == "Routine off"
    assert writer("24h").paused(sunday_6pm, WEDNESDAY_3PM) == "Paused until Sun 18:00"
    assert w.routine_kind() == "Routine"
    assert w.routine_kind(detached=True) == "Detached routine"

    w12, w24 = writer("12h"), writer("24h")
    moments = [
        WEDNESDAY_3PM.replace(hour=0) + timedelta(days=day, hours=hour, minutes=59, seconds=second)
        for day, hour, second in product(range(10), range(24), (0, 59))
    ]
    for verb, moment, w in product(Verb, moments, (w12, w24)):
        for text in (w.skipped(verb, moment, WEDNESDAY_3PM), w.paused(moment, WEDNESDAY_3PM)):
            assert len(text) <= sentence.STATE_CAP, text
    assert len(w12.routine_off()) <= sentence.STATE_CAP


def test_routine_states_drop_the_weekday_then_cut() -> None:
    thursday_5pm = datetime(2026, 10, 22, 17, tzinfo=LA)
    medium = sentence.Writer({**PHRASES, "verb_dock": "return to the dock now"}, "12h")
    assert medium.skipped(Verb.DOCK, thursday_5pm, WEDNESDAY_3PM) == (
        "Skipped, return to the dock now 5:00 PM"
    )
    long = sentence.Writer({**PHRASES, "verb_dock": "return to the charging dock"}, "12h")
    assert long.skipped(Verb.DOCK, thursday_5pm, WEDNESDAY_3PM) == (
        "Skipped, return to the charging dock..."
    )
    wordy = sentence.Writer(
        {**PHRASES, "state_routine_off": "This routine is switched off for now and then"}, "12h"
    )
    assert wordy.routine_off() == "This routine is switched off for now..."
    far = datetime(2026, 11, 30, 12, 59, 59, tzinfo=LA)
    assert len(long.skipped(Verb.DOCK, far, WEDNESDAY_3PM)) == sentence.STATE_CAP - 1


# --------------------------------------------------------------------------------------
# The phrase table
# --------------------------------------------------------------------------------------


def test_a_missing_language_falls_back_to_english() -> None:
    assert sentence.load_phrases("xx") == PHRASES


def test_the_phrase_table_is_flat_text_with_no_em_dash() -> None:
    raw = json.loads(Path(sentence.SENTENCES_DIR / "en.json").read_text(encoding="utf-8"))
    assert all(isinstance(value, str) for value in raw.values())
    em_dash = chr(0x2014)
    assert not any(em_dash in value for value in raw.values())


def test_every_phrase_is_used() -> None:
    """Rendering every line case, verb, weekday and state reads every phrase, no other."""
    recording = Recording(PHRASES)
    w = writer(phrases=recording)
    for parsed, _ in LINE_CASES:
        w.line(parsed)
    for verb in Verb:
        w.line(line(TimeTrigger(at=time(9)), verb=verb))
        w.state(Occurrence(NOW, verb), None, NOW)
        w.state(Occurrence(NOW + timedelta(days=1), verb), None, NOW)
    for day in Weekday:
        w.days(frozenset({day, Weekday.MON}))
    for name in NAMED_TRIGGERS:
        w.line(line(NamedTrigger(name, ("timer.a",))))
    w.days(WEEKDAYS)
    w.days(WEEKEND)
    w.days(frozenset())
    w.clock(time(13))
    w.duration(timedelta(hours=3))
    w.line(line(StateTrigger(DOOR, to="on", duration=timedelta(minutes=5))))
    w.state(None, "x" * 60, NOW)
    w.state(Occurrence(NOW, None), None, NOW)
    for verb in Verb:
        w.skipped(verb, NOW, NOW)
    w.paused(NOW, NOW)
    w.routine_off()
    w.routine_kind()
    w.routine_kind(detached=True)
    markers.presentation("Example", recording)
    markers.presentation("Example", recording, formerly=True)
    # The weekly schedule helper's name and the AI line (Build A lane 14).
    w.say("schedule_name", device="Example")
    w.say("ai_line", text="Example")

    assert set(PHRASES) - recording.used == set()
