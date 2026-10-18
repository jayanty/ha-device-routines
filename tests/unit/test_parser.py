"""The parser grammar, rule by rule (TECH_SPEC 3.5, PRD FR-S2)."""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any

import pytest

from custom_components.device_routines import parser
from custom_components.device_routines.models import (
    WEEKDAYS,
    CalendarTrigger,
    DeviceContext,
    EntityRef,
    FollowUp,
    NamedTrigger,
    NumericTrigger,
    ParsedLine,
    ParseError,
    PatternTrigger,
    StartTrigger,
    StateTrigger,
    SunTrigger,
    TimeTrigger,
    TimeWindow,
    Verb,
    Weekday,
)

FAN = "fan.example_fan"
LIGHT = "light.example_light"
# Registry ids are 32 hex characters; built at runtime so no id shaped literal is committed.
REGISTRY_ID = "ab" * 16
UNKNOWN_REGISTRY_ID = "f" * 32
DEVICE = DeviceContext(
    device_id="device_1",
    entities=(
        EntityRef(FAN, area_id="area_1", floor_id="floor_1", labels=frozenset({"label_1"})),
        EntityRef("sensor.example_power"),
    ),
    registry_ids={REGISTRY_ID: FAN},
)
TURN_ON = {"action": "fan.turn_on", "target": {"entity_id": FAN}}
TURN_OFF = {"action": "fan.turn_off", "target": {"entity_id": FAN}}
AT_NINE = {"trigger": "time", "at": "09:00:00"}


def automation(
    triggers: Any = None, actions: Any = None, conditions: Any = None, **extra: Any
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "id": "a1",
        "alias": "Example",
        "triggers": [AT_NINE] if triggers is None else triggers,
        "actions": [TURN_ON] if actions is None else actions,
        **extra,
    }
    if conditions is not None:
        config["conditions"] = conditions
    return config


def only(config: dict[str, Any], device: DeviceContext = DEVICE) -> ParsedLine:
    lines = parser.summarize(config, device)
    assert len(lines) == 1, lines
    return lines[0]


def trigger_of(node: dict[str, Any]) -> Any:
    line = only(automation(triggers=[node]))
    assert line.understood, line
    assert not line.custom_logic, line
    assert len(line.triggers) == 1
    return line.triggers[0]


def not_understood_trigger(node: Any) -> None:
    line = only(automation(triggers=[node]))
    assert not line.understood


# --------------------------------------------------------------------------------------
# Values
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("09:00", time(9)),
        ("9:05:30", time(9, 5, 30)),
        ("24:00", None),
        ("12:60", None),
        ("noon", None),
        (900, None),
    ],
)
def test_parse_time(value: Any, expected: time | None) -> None:
    assert parser.parse_time(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (90, timedelta(seconds=90)),
        (1.5, timedelta(seconds=1.5)),
        ("00:05:00", timedelta(minutes=5)),
        ("01:30", timedelta(hours=1, minutes=30)),
        ("-00:30:00", timedelta(minutes=-30)),
        ({"minutes": 3}, timedelta(minutes=3)),
        ({"hours": 1, "seconds": 5}, timedelta(hours=1, seconds=5)),
        ({}, None),
        ({"weeks": 1}, None),
        ({"minutes": "3"}, None),
        ("{{ 5 }}", None),
        (True, None),
        (None, None),
    ],
)
def test_parse_duration(value: Any, expected: timedelta | None) -> None:
    assert parser.parse_duration(value) == expected


def test_input_that_is_not_an_automation_is_refused() -> None:
    with pytest.raises(ParseError) as caught:
        parser.summarize({"triggers": []}, DEVICE)
    assert caught.value.translation_key == "not_an_automation"
    with pytest.raises(ParseError):
        parser.summarize(["not", "a", "mapping"], DEVICE)


# --------------------------------------------------------------------------------------
# Triggers
# --------------------------------------------------------------------------------------


def test_time_trigger_fixed_list_and_weekday_option() -> None:
    line = only(
        automation(triggers=[{"trigger": "time", "at": ["09:45", "10:00"], "weekday": "mon"}])
    )
    assert line.triggers == (
        TimeTrigger(at=time(9, 45), weekdays=frozenset({Weekday.MON})),
        TimeTrigger(at=time(10), weekdays=frozenset({Weekday.MON})),
    )


def test_time_trigger_entity_and_entity_with_offset() -> None:
    assert trigger_of({"trigger": "time", "at": "input_datetime.wake"}) == TimeTrigger(
        entity="input_datetime.wake"
    )
    assert trigger_of(
        {"trigger": "time", "at": {"entity_id": "sensor.alarm", "offset": "-00:10:00"}}
    ) == TimeTrigger(entity="sensor.alarm", offset=timedelta(minutes=-10))


@pytest.mark.parametrize(
    "node",
    [
        {"trigger": "time", "at": "{{ states('input_text.t') }}"},
        {"trigger": "time", "at": "soon"},
        {"trigger": "time", "at": {"entity_id": "sensor.alarm", "offset": "x"}},
        {"trigger": "time", "at": {"entity_id": "sensor.alarm", "extra": 1}},
        {"trigger": "time", "at": "09:00", "weekday": ["mon", "funday"]},
        {"trigger": "time", "at": "09:00", "unknown_option": True},
        {"trigger": "time"},
    ],
)
def test_time_triggers_outside_the_grammar(node: dict[str, Any]) -> None:
    not_understood_trigger(node)


def test_legacy_platform_key_is_read() -> None:
    assert trigger_of({"platform": "time", "at": "07:00"}) == TimeTrigger(at=time(7))


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ({"minutes": "/5"}, PatternTrigger(hours="*", minutes="/5", seconds="0")),
        ({"hours": "3"}, PatternTrigger(hours="3", minutes="0", seconds="0")),
        ({"hours": "*", "minutes": 15}, PatternTrigger(hours="*", minutes="15", seconds="0")),
        ({"seconds": "0"}, PatternTrigger(hours="*", minutes="*", seconds="0")),
    ],
)
def test_time_pattern(node: dict[str, Any], expected: PatternTrigger) -> None:
    assert trigger_of({"trigger": "time_pattern", **node}) == expected


@pytest.mark.parametrize(
    "node", [{"seconds": "/10"}, {}, {"minutes": "every"}, {"minutes": "5", "days": 1}]
)
def test_time_patterns_outside_the_grammar(node: dict[str, Any]) -> None:
    not_understood_trigger({"trigger": "time_pattern", **node})


def test_sun_trigger() -> None:
    assert trigger_of({"trigger": "sun", "event": "sunset", "offset": "-00:30:00"}) == SunTrigger(
        event="sunset", offset=timedelta(minutes=-30)
    )
    not_understood_trigger({"trigger": "sun", "event": "noon"})
    not_understood_trigger({"trigger": "sun", "event": "sunrise", "offset": "later"})


def test_state_trigger_with_for_and_list_of_entities() -> None:
    line = only(
        automation(
            triggers=[
                {
                    "trigger": "state",
                    "entity_id": [FAN, "binary_sensor.door"],
                    "to": "on",
                    "for": {"minutes": 60},
                }
            ]
        )
    )
    assert line.triggers == (
        StateTrigger(entity=FAN, to="on", duration=timedelta(minutes=60)),
        StateTrigger(entity="binary_sensor.door", to="on", duration=timedelta(minutes=60)),
    )


def test_state_trigger_values() -> None:
    assert trigger_of(
        {"trigger": "state", "entity_id": FAN, "from": "off", "not_to": ["unavailable"]}
    ) == StateTrigger(entity=FAN, from_state="off")
    assert trigger_of({"trigger": "state", "entity_id": FAN, "to": True}) == StateTrigger(
        entity=FAN, to="on"
    )
    assert trigger_of({"trigger": "state", "entity_id": FAN, "to": [False]}) == StateTrigger(
        entity=FAN, to="off"
    )
    assert trigger_of({"trigger": "state", "entity_id": REGISTRY_ID}) == StateTrigger(entity=FAN)
    assert trigger_of(
        {
            "trigger": "state",
            "entity_id": FAN,
            "not_from": ["unknown", "unavailable"],
            "not_to": ["unknown", "unavailable"],
        }
    ) == StateTrigger(entity=FAN)


def triggers_of(node: dict[str, Any]) -> tuple[Any, ...]:
    line = only(automation(triggers=[node]))
    assert line.understood, line
    assert not line.custom_logic, line
    return line.triggers


def test_a_state_trigger_with_several_states_reads_as_one_trigger_per_state() -> None:
    """`to: [a, b]` fires exactly when `to: a` or `to: b` would, a held `for` included."""
    assert triggers_of({"trigger": "state", "entity_id": FAN, "to": ["on", "off"]}) == (
        StateTrigger(entity=FAN, to="on"),
        StateTrigger(entity=FAN, to="off"),
    )
    assert triggers_of(
        {
            "trigger": "state",
            "entity_id": "sensor.power",
            "to": ["unavailable", "unknown"],
            "for": {"minutes": 10},
        }
    ) == (
        StateTrigger(entity="sensor.power", to="unavailable", duration=timedelta(minutes=10)),
        StateTrigger(entity="sensor.power", to="unknown", duration=timedelta(minutes=10)),
    )
    assert triggers_of(
        {"trigger": "state", "entity_id": "sensor.power", "from": ["unavailable", "unknown"]}
    ) == (
        StateTrigger(entity="sensor.power", from_state="unavailable"),
        StateTrigger(entity="sensor.power", from_state="unknown"),
    )


def test_several_from_and_to_states_read_as_every_pair_per_entity() -> None:
    assert triggers_of(
        {
            "trigger": "state",
            "entity_id": [FAN, "binary_sensor.door"],
            "from": ["idle", "paused"],
            "to": ["heat", "cool"],
        }
    ) == (
        StateTrigger(entity=FAN, from_state="idle", to="heat"),
        StateTrigger(entity=FAN, from_state="idle", to="cool"),
        StateTrigger(entity=FAN, from_state="paused", to="heat"),
        StateTrigger(entity=FAN, from_state="paused", to="cool"),
        StateTrigger(entity="binary_sensor.door", from_state="idle", to="heat"),
        StateTrigger(entity="binary_sensor.door", from_state="idle", to="cool"),
        StateTrigger(entity="binary_sensor.door", from_state="paused", to="heat"),
        StateTrigger(entity="binary_sensor.door", from_state="paused", to="cool"),
    )


def test_a_pair_that_can_never_fire_is_left_out_and_repeats_are_read_once() -> None:
    """The core never fires on a change to the state an entity already has."""
    assert triggers_of(
        {"trigger": "state", "entity_id": FAN, "from": ["on", "off"], "to": "on"}
    ) == (StateTrigger(entity=FAN, from_state="off", to="on"),)
    assert triggers_of({"trigger": "state", "entity_id": FAN, "to": ["on", True, "on"]}) == (
        StateTrigger(entity=FAN, to="on"),
    )


@pytest.mark.parametrize(
    "node",
    [
        {"trigger": "state", "entity_id": FAN, "attribute": "speed"},
        {"trigger": "state", "entity_id": FAN, "not_to": ["off"]},
        {"trigger": "state", "entity_id": FAN, "for": "{{ 5 }}"},
        {"trigger": "state", "entity_id": FAN, "for": "later"},
        {"trigger": "state", "entity_id": UNKNOWN_REGISTRY_ID},
        {"trigger": "state"},
        {"trigger": "state", "entity_id": FAN, "to": []},
        {"trigger": "state", "entity_id": FAN, "to": ["on", 3]},
        {"trigger": "state", "entity_id": FAN, "from": "on", "to": "on"},
    ],
)
def test_state_triggers_outside_the_grammar(node: dict[str, Any]) -> None:
    not_understood_trigger(node)


@pytest.mark.parametrize(
    "node",
    [
        {"from": ["unavailable", "unknown"], "not_to": ["unavailable", "unknown"]},
        {"from": "unavailable", "not_to": ["unknown"]},
        {"to": ["on", "unknown"], "not_from": ["unavailable"]},
    ],
)
def test_an_unavailable_filter_is_noise_only_for_a_trigger_about_real_states(
    node: dict[str, Any],
) -> None:
    """Dropping unknown and unavailable is read as noise filtering ("turns on"), unless the
    trigger itself names unknown or unavailable: then the filter is what it is about."""
    not_understood_trigger({"trigger": "state", "entity_id": "sensor.power", **node})


def test_numeric_state_trigger() -> None:
    assert trigger_of(
        {"trigger": "numeric_state", "entity_id": "sensor.t", "above": 28, "for": "00:03:00"}
    ) == NumericTrigger(entity="sensor.t", above=28.0, duration=timedelta(minutes=3))
    assert trigger_of(
        {"trigger": "numeric_state", "entity_id": "sensor.t", "above": 1, "below": 2.5}
    ) == NumericTrigger(entity="sensor.t", above=1.0, below=2.5)


@pytest.mark.parametrize(
    "node",
    [
        {"entity_id": "sensor.t", "above": "input_number.limit"},
        {"entity_id": "sensor.t"},
        {"entity_id": "sensor.t", "below": 3, "value_template": "{{ x }}"},
        {"entity_id": "sensor.t", "below": 3, "attribute": "temperature"},
        {"entity_id": "sensor.t", "below": 3, "for": "x"},
        {"below": 3},
    ],
)
def test_numeric_triggers_outside_the_grammar(node: dict[str, Any]) -> None:
    not_understood_trigger({"trigger": "numeric_state", **node})


def test_homeassistant_and_calendar_triggers() -> None:
    assert trigger_of({"trigger": "homeassistant", "event": "start"}) == StartTrigger("start")
    assert trigger_of(
        {"trigger": "calendar", "entity_id": "calendar.work", "event": "end", "offset": "0:15"}
    ) == CalendarTrigger(entity="calendar.work", event="end", offset=timedelta(minutes=15))
    not_understood_trigger({"trigger": "homeassistant", "event": "reboot"})
    not_understood_trigger({"trigger": "calendar", "entity_id": "calendar.work", "event": "mid"})


def test_device_trigger_resolves_the_registry_id() -> None:
    assert trigger_of(
        {
            "trigger": "device",
            "device_id": "device_1",
            "domain": "fan",
            "type": "turned_on",
            "entity_id": REGISTRY_ID,
            "for": {"minutes": 5},
        }
    ) == StateTrigger(entity=FAN, to="on", duration=timedelta(minutes=5))
    not_understood_trigger(
        {"trigger": "device", "device_id": "d", "domain": "fan", "type": "speed_changed"}
    )
    not_understood_trigger(
        {
            "trigger": "device",
            "device_id": "d",
            "domain": "fan",
            "type": "turned_on",
            "entity_id": FAN,
            "for": "x",
        }
    )


def test_named_triggers() -> None:
    assert trigger_of(
        {"trigger": "timer.finished", "target": {"entity_id": "timer.fan"}}
    ) == NamedTrigger(name="timer.finished", entities=("timer.fan",))
    assert trigger_of({"trigger": "schedule.block_started"}) == NamedTrigger(
        name="schedule.block_started"
    )
    not_understood_trigger({"trigger": "timer.finished", "target": {"area_id": "kitchen"}})
    not_understood_trigger({"trigger": "timer.finished", "target": {"entity_id": "bad id"}})
    not_understood_trigger({"trigger": "timer.finished", "behavior": "any"})


@pytest.mark.parametrize("behavior", ["each", "any"])
def test_named_triggers_read_with_the_default_behavior(behavior: str) -> None:
    """Any one target is enough: `each`, or its legacy name `any`, is what the line says."""
    assert trigger_of(
        {
            "trigger": "timer.finished",
            "target": {"entity_id": ["timer.a", "timer.b"]},
            "options": {"behavior": behavior},
        }
    ) == NamedTrigger(name="timer.finished", entities=("timer.a", "timer.b"))
    assert trigger_of(
        {"trigger": "schedule.block_ended", "target": {"entity_id": "schedule.s"}, "options": {}}
    ) == NamedTrigger(name="schedule.block_ended", entities=("schedule.s",))


@pytest.mark.parametrize(
    "options",
    [
        {"behavior": "first"},
        {"behavior": "all"},
        {"behavior": "last"},
        {"for": {"minutes": 5}},
        {"behavior": "each", "for": "00:05:00"},
        "each",
    ],
)
def test_named_trigger_options_that_change_the_meaning_are_outside_the_grammar(
    options: Any,
) -> None:
    """The first or all of several targets, or a held duration, is not what the line says."""
    not_understood_trigger(
        {"trigger": "timer.finished", "target": {"entity_id": "timer.a"}, "options": options}
    )


def test_named_triggers_read_only_entities_of_their_own_domain() -> None:
    """The core filters a purpose specific trigger's targets to its domain; others never fire."""
    not_understood_trigger({"trigger": "timer.finished", "target": {"entity_id": FAN}})
    not_understood_trigger(
        {"trigger": "schedule.block_started", "target": {"entity_id": ["schedule.s", "timer.t"]}}
    )


def test_the_vacuum_triggers_are_the_ones_the_core_has() -> None:
    assert trigger_of(
        {"trigger": "vacuum.returned_to_dock", "target": {"entity_id": "vacuum.robot"}}
    ) == NamedTrigger(name="vacuum.returned_to_dock", entities=("vacuum.robot",))
    not_understood_trigger({"trigger": "vacuum.docked", "target": {"entity_id": "vacuum.robot"}})


def test_event_received_reads_with_its_event_types() -> None:
    assert trigger_of(
        {
            "trigger": "event.received",
            "target": {"entity_id": "event.button"},
            "options": {"event_type": ["multi_press_1", "long_press", "multi_press_1"]},
        }
    ) == NamedTrigger(
        name="event.received", entities=("event.button",), values=("multi_press_1", "long_press")
    )
    assert trigger_of(
        {
            "trigger": "event.received",
            "target": {"entity_id": ["event.a", "event.b"]},
            "options": {"event_type": "single"},
        }
    ) == NamedTrigger(name="event.received", entities=("event.a", "event.b"), values=("single",))


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"options": {}},
        {"options": {"event_type": []}},
        {"options": {"event_type": ["single", 3]}},
        {"options": {"event_type": ["single"], "behavior": "each"}},
        {"options": ["single"]},
        {"target": {"entity_id": FAN}, "options": {"event_type": ["single"]}},
    ],
)
def test_event_received_without_exactly_its_event_types_is_outside_the_grammar(
    extra: dict[str, Any],
) -> None:
    not_understood_trigger(
        {"trigger": "event.received", "target": {"entity_id": "event.button"}, **extra}
    )


def test_a_timer_event_for_one_timer_reads_as_the_timer_trigger() -> None:
    """The timer fires its event and records the same transition together."""
    assert trigger_of(
        {
            "trigger": "event",
            "event_type": "timer.finished",
            "event_data": {"entity_id": "timer.fan"},
        }
    ) == NamedTrigger(name="timer.finished", entities=("timer.fan",))
    assert triggers_of(
        {
            "trigger": "event",
            "event_type": ["timer.started", "timer.cancelled", "timer.started"],
            "event_data": {"entity_id": "timer.fan"},
        }
    ) == (
        NamedTrigger(name="timer.started", entities=("timer.fan",)),
        NamedTrigger(name="timer.cancelled", entities=("timer.fan",)),
    )


@pytest.mark.parametrize(
    "node",
    [
        {"event_type": "timer.finished"},
        {"event_type": "timer.finished", "event_data": {}},
        {"event_type": "timer.finished", "event_data": "timer.fan"},
        {"event_type": "timer.finished", "event_data": {"entity_id": ["timer.a", "timer.b"]}},
        {"event_type": "timer.finished", "event_data": {"entity_id": REGISTRY_ID}},
        {"event_type": "timer.finished", "event_data": {"entity_id": FAN}},
        {
            "event_type": "timer.finished",
            "event_data": {"entity_id": "timer.fan", "finished_at": "2026-10-17T09:00:00"},
        },
        {
            "event_type": "timer.finished",
            "event_data": {"entity_id": "timer.fan"},
            "context": {"user_id": "u"},
        },
        {"event_type": ["timer.finished", "timer.paused"], "event_data": {"entity_id": "timer.a"}},
        {"event_type": "timer.changed", "event_data": {"entity_id": "timer.fan"}},
        {"event_type": [], "event_data": {"entity_id": "timer.fan"}},
        {"event_type": "custom_event"},
    ],
)
def test_other_event_triggers_are_outside_the_grammar(node: dict[str, Any]) -> None:
    """Any timer, several timers, more event data, a user filter or another event: not read."""
    not_understood_trigger({"trigger": "event", **node})


@pytest.mark.parametrize(
    "node",
    [
        {"trigger": "event", "event_type": "x"},
        {"trigger": "webhook", "webhook_id": "w"},
        {"trigger": "template", "value_template": "{{ true }}"},
        "not a mapping",
    ],
)
def test_other_triggers_are_outside_the_grammar(node: Any) -> None:
    not_understood_trigger(node)


def test_disabled_triggers_are_ignored_but_keep_their_index() -> None:
    line = only(
        automation(
            triggers=[
                {"trigger": "time", "at": "08:00", "enabled": False},
                {"trigger": "time", "at": "09:00"},
            ],
            actions=[
                {
                    "choose": [
                        {"conditions": [{"condition": "trigger", "id": "1"}], "sequence": [TURN_ON]}
                    ]
                }
            ],
        )
    )
    assert line.triggers == (TimeTrigger(at=time(9)),)


def test_a_mix_of_understood_and_unknown_triggers_is_custom_logic() -> None:
    line = only(automation(triggers=[AT_NINE, {"trigger": "event", "event_type": "x"}]))
    assert line.understood
    assert line.custom_logic
    assert line.triggers == (TimeTrigger(at=time(9)),)


# --------------------------------------------------------------------------------------
# Conditions
# --------------------------------------------------------------------------------------


def test_weekday_and_window_conditions_are_folded_in() -> None:
    line = only(
        automation(
            conditions=[
                {"condition": "time", "weekday": ["mon", "tue", "wed", "thu", "fri"]},
                {"condition": "time", "weekday": ["fri", "sat"]},
                {"condition": "time", "after": "08:00", "before": "input_datetime.end"},
            ]
        )
    )
    assert line.weekdays == frozenset({Weekday.FRI})
    assert line.windows == (TimeWindow(after=time(8), before="input_datetime.end"),)
    assert line.condition_count == 0
    assert not line.custom_logic


def test_understood_conditions_are_counted() -> None:
    line = only(
        automation(
            conditions=[
                {"condition": "state", "entity_id": "binary_sensor.door", "state": "off"},
                {"condition": "numeric_state", "entity_id": "sensor.t", "above": 3},
                {"condition": "sun", "after": "sunset"},
                {"condition": "vacuum.is_docked", "target": {"entity_id": "vacuum.v"}},
                {"or": [{"condition": "state", "entity_id": "a.b", "state": "on"}]},
                {"condition": "not", "conditions": [{"condition": "time", "weekday": "sun"}]},
                {"condition": "device", "type": "is_on", "device_id": "d", "domain": "fan"},
                {"condition": "state", "entity_id": "a.b", "state": "on", "enabled": False},
            ]
        )
    )
    assert line.condition_count == 7
    assert not line.custom_logic


@pytest.mark.parametrize(
    "condition",
    [
        {"condition": "template", "value_template": "{{ true }}"},
        "{{ is_state('a.b', 'on') }}",
        {"condition": "state", "entity_id": "a.b", "state": "{{ x }}"},
        {"condition": "device", "type": "is_speed", "device_id": "d", "domain": "fan"},
        {"condition": "zone", "entity_id": "person.p", "zone": "zone.home"},
        {"condition": "time", "after": "later"},
        {"condition": "time", "weekday": "funday"},
        {"condition": "time", "weekday": "mon", "mode": "x"},
        {"condition": "and", "conditions": []},
        {"condition": "or", "conditions": [{"condition": "template", "value_template": "x"}]},
        {"and": [], "or": []},
        {"condition": "or", "conditions": [{"condition": "trigger", "id": "x"}]},
    ],
)
def test_conditions_outside_the_grammar_make_custom_logic(condition: Any) -> None:
    line = only(automation(conditions=[condition]))
    assert line.custom_logic


def test_inline_condition_step_applies_to_the_steps_after_it() -> None:
    line = only(
        automation(
            actions=[
                {"condition": "state", "entity_id": "binary_sensor.door", "state": "off"},
                TURN_ON,
            ]
        )
    )
    assert line.condition_count == 1


# --------------------------------------------------------------------------------------
# Actions and targets
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    [
        {"entity_id": FAN},
        {"entity_id": [LIGHT, FAN]},
        {"entity_id": REGISTRY_ID},
        {"device_id": "device_1"},
        {"area_id": "area_1"},
        {"floor_id": ["floor_1"]},
        {"label_id": "label_1"},
        {"entity_id": "all"},
    ],
)
def test_targets_reach_the_device(target: dict[str, Any]) -> None:
    line = only(automation(actions=[{"action": "fan.turn_on", "target": target}]))
    assert line.entity_ids == (FAN,)
    assert line.verb is Verb.ON


def test_old_style_entity_id_keys_reach_the_device() -> None:
    assert only(automation(actions=[{"service": "fan.turn_off", "entity_id": FAN}])).verb is (
        Verb.OFF
    )
    assert only(
        automation(actions=[{"action": "fan.toggle", "data": {"entity_id": FAN}}])
    ).verb is (Verb.TOGGLE)


def test_homeassistant_actions_match_any_domain() -> None:
    line = only(
        automation(actions=[{"action": "homeassistant.turn_off", "target": {"area_id": "area_1"}}])
    )
    assert line.entity_ids == (FAN,)
    assert line.verb is Verb.OFF


@pytest.mark.parametrize(
    "action",
    [
        {"action": "light.turn_on", "target": {"area_id": "area_1"}},
        {"action": "fan.turn_on", "target": {"entity_id": "{{ target }}"}},
        {"action": "fan.turn_on", "target": {"device_id": "device_2"}},
        {"action": "{{ service }}", "target": {"entity_id": FAN}},
        {"action": "script.example_script", "data": {}},
        {"action": "notify", "data": {}},
    ],
)
def test_actions_that_do_not_reach_the_device_produce_no_line(action: dict[str, Any]) -> None:
    assert parser.summarize(automation(actions=[action]), DEVICE) == []


def test_a_service_the_grammar_does_not_know_is_not_understood() -> None:
    line = only(
        automation(
            actions=[{"action": "fan.set_percentage", "target": {"entity_id": FAN}, "data": {}}]
        )
    )
    assert not line.understood
    assert line.verb is None


def test_device_actions() -> None:
    device_action = {"device_id": "device_1", "domain": "fan", "type": "turn_off"}
    line = only(automation(actions=[{**device_action, "entity_id": REGISTRY_ID}]))
    assert (line.entity_ids, line.verb) == ((FAN,), Verb.OFF)
    line = only(automation(actions=[device_action]))
    assert (line.entity_ids, line.verb) == ((FAN,), Verb.OFF)
    assert parser.summarize(automation(actions=[{**device_action, "device_id": "x"}]), DEVICE) == []
    line = only(automation(actions=[{**device_action, "type": "set_speed"}]))
    assert not line.understood


@pytest.mark.parametrize(
    ("action", "verb"),
    [
        ("vacuum.start", Verb.START),
        ("vacuum.return_to_base", Verb.DOCK),
        ("lawn_mower.start_mowing", Verb.START),
        ("lawn_mower.dock", Verb.DOCK),
        ("cover.open_cover", Verb.OPEN),
        ("cover.close_cover", Verb.CLOSE),
        ("valve.open_valve", Verb.OPEN),
        ("valve.close_valve", Verb.CLOSE),
        ("lock.lock", Verb.LOCK),
        ("lock.unlock", Verb.UNLOCK),
        ("vacuum.pause", Verb.PAUSE),
        ("cover.stop", Verb.STOP),
    ],
)
def test_verbs_per_domain(action: str, verb: Verb) -> None:
    entity = f"{action.split('.', maxsplit=1)[0]}.thing"
    device = DeviceContext("d", (EntityRef(entity),))
    line = only(automation(actions=[{"action": action, "target": {"entity_id": entity}}]), device)
    assert line.verb is verb


def test_a_service_another_domain_has_is_not_read_as_a_verb() -> None:
    device = DeviceContext("d", (EntityRef("light.l"),))
    line = only(
        automation(actions=[{"action": "light.start", "target": {"entity_id": "light.l"}}]), device
    )
    assert not line.understood


def test_disabled_actions_are_ignored() -> None:
    assert parser.summarize(automation(actions=[{**TURN_ON, "enabled": False}]), DEVICE) == []


# --------------------------------------------------------------------------------------
# Sequences, delays and branches
# --------------------------------------------------------------------------------------


def test_delay_sequence_becomes_follow_ups() -> None:
    line = only(
        automation(
            actions=[
                TURN_OFF,
                {"action": "notify.phone", "data": {}},
                {"delay": {"minutes": 2}},
                {"delay": "00:01:00"},
                TURN_ON,
                {"delay": 30},
                TURN_OFF,
            ]
        )
    )
    assert line.verb is Verb.OFF
    assert line.follow_ups == (
        FollowUp(timedelta(minutes=3), Verb.ON),
        FollowUp(timedelta(seconds=30), Verb.OFF),
    )
    assert not line.custom_logic


def test_two_actions_without_a_delay_are_two_lines() -> None:
    lines = parser.summarize(automation(actions=[TURN_OFF, TURN_ON]), DEVICE)
    assert [line.verb for line in lines] == [Verb.OFF, Verb.ON]


def test_a_delay_before_the_first_action_is_custom_logic() -> None:
    line = only(automation(actions=[{"delay": 5}, TURN_ON]))
    assert line.custom_logic
    assert line.follow_ups == ()


def test_a_templated_delay_breaks_the_follow_up() -> None:
    lines = parser.summarize(automation(actions=[TURN_OFF, {"delay": "{{ d }}"}, TURN_ON]), DEVICE)
    assert [(line.verb, line.custom_logic) for line in lines] == [
        (Verb.OFF, False),
        (Verb.ON, True),
    ]


@pytest.mark.parametrize(
    "step",
    [
        {"wait_template": "{{ x }}"},
        {"wait_for_trigger": []},
        {"variables": {"x": 1}},
        {"event": "my_event"},
        {"scene": "scene.x"},
        "not a mapping",
    ],
)
def test_opaque_steps_make_later_lines_custom(step: Any) -> None:
    lines = parser.summarize(automation(actions=[TURN_OFF, step, TURN_ON]), DEVICE)
    assert [line.custom_logic for line in lines] == [False, True]


def test_stop_ends_the_sequence() -> None:
    assert parser.summarize(automation(actions=[{"stop": "done"}, TURN_ON]), DEVICE) == []


def test_repeat_is_walked_as_custom_logic() -> None:
    line = only(automation(actions=[{"repeat": {"count": 2, "sequence": [TURN_ON]}}]))
    assert line.custom_logic


def test_parallel_and_sequence_are_walked() -> None:
    lines = parser.summarize(
        automation(
            actions=[
                {"parallel": [TURN_ON, {"sequence": [TURN_OFF]}]},
                {"sequence": [TURN_ON]},
            ]
        ),
        DEVICE,
    )
    assert [line.verb for line in lines] == [Verb.ON, Verb.OFF, Verb.ON]


TWO_TRIGGERS = [
    {"trigger": "time", "at": "17:00", "id": "on"},
    {"trigger": "time", "at": "09:00", "id": "off"},
]


def test_choose_keyed_by_trigger_id() -> None:
    lines = parser.summarize(
        automation(
            triggers=TWO_TRIGGERS,
            actions=[
                {
                    "choose": [
                        {
                            "conditions": [{"condition": "trigger", "id": "on"}],
                            "sequence": [TURN_ON],
                        },
                        {
                            "conditions": {"condition": "trigger", "id": ["off"]},
                            "sequence": [TURN_OFF],
                        },
                        {"enabled": False, "conditions": [], "sequence": [TURN_OFF]},
                    ]
                }
            ],
        ),
        DEVICE,
    )
    assert [(line.verb, line.triggers) for line in lines] == [
        (Verb.ON, (TimeTrigger(at=time(17)),)),
        (Verb.OFF, (TimeTrigger(at=time(9)),)),
    ]


def test_choose_default_takes_the_unclaimed_triggers() -> None:
    lines = parser.summarize(
        automation(
            triggers=TWO_TRIGGERS,
            actions=[
                {
                    "choose": [
                        {
                            "conditions": [{"condition": "trigger", "id": "on"}],
                            "sequence": [TURN_ON],
                        }
                    ],
                    "default": [TURN_OFF],
                }
            ],
        ),
        DEVICE,
    )
    assert lines[1].triggers == (TimeTrigger(at=time(9)),)
    assert not lines[1].custom_logic


def test_choose_default_after_other_conditions_is_custom_logic() -> None:
    lines = parser.summarize(
        automation(
            actions=[
                {
                    "choose": [
                        {
                            "conditions": [
                                {"condition": "state", "entity_id": "a.b", "state": "on"}
                            ],
                            "sequence": [TURN_ON],
                        }
                    ],
                    "default": [TURN_OFF],
                }
            ]
        ),
        DEVICE,
    )
    assert [(line.condition_count, line.custom_logic) for line in lines] == [(1, False), (0, True)]


def test_if_then_else_with_trigger_ids() -> None:
    lines = parser.summarize(
        automation(
            triggers=TWO_TRIGGERS,
            actions=[
                {
                    "if": [{"condition": "trigger", "id": "on"}],
                    "then": [TURN_ON],
                    "else": [TURN_OFF],
                }
            ],
        ),
        DEVICE,
    )
    assert [line.triggers for line in lines] == [
        (TimeTrigger(at=time(17)),),
        (TimeTrigger(at=time(9)),),
    ]


def test_else_of_an_understood_condition_counts_one_condition() -> None:
    lines = parser.summarize(
        automation(
            actions=[
                {
                    "if": [{"condition": "state", "entity_id": "a.b", "state": "on"}],
                    "then": [TURN_ON],
                    "else": [TURN_OFF],
                }
            ]
        ),
        DEVICE,
    )
    assert [(line.condition_count, line.custom_logic) for line in lines] == [(1, False), (1, False)]


def test_else_of_a_mixed_condition_is_custom_logic() -> None:
    lines = parser.summarize(
        automation(
            triggers=TWO_TRIGGERS,
            actions=[
                {
                    "if": [
                        {"condition": "trigger", "id": "on"},
                        {"condition": "state", "entity_id": "a.b", "state": "on"},
                    ],
                    "then": [TURN_ON],
                    "else": [TURN_OFF],
                }
            ],
        ),
        DEVICE,
    )
    assert lines[1].custom_logic


def test_if_without_else() -> None:
    line = only(
        automation(
            actions=[
                {"if": [{"condition": "state", "entity_id": "a", "state": "on"}], "then": [TURN_ON]}
            ]
        )
    )
    assert line.condition_count == 1


def test_no_trigger_reaching_the_action_means_not_understood() -> None:
    line = only(
        automation(
            triggers=TWO_TRIGGERS,
            actions=[
                {
                    "choose": [
                        {"conditions": [{"condition": "trigger", "id": "x"}], "sequence": [TURN_ON]}
                    ]
                }
            ],
        )
    )
    assert not line.understood


def test_alias_falls_back_to_the_id_and_weekdays_survive() -> None:
    config = automation(conditions=[{"condition": "time", "weekday": list(WEEKDAYS)}])
    del config["alias"]
    line = only(config)
    assert line.alias == "a1"
    assert line.weekdays == WEEKDAYS
    assert line.timed


def test_unknown_options_on_calendar_and_device_triggers() -> None:
    not_understood_trigger(
        {"trigger": "calendar", "entity_id": "calendar.work", "event": "start", "x": 1}
    )
    not_understood_trigger(
        {"trigger": "device", "device_id": "d", "domain": "fan", "type": "turned_on", "x": 1}
    )


def test_disabled_children_of_a_logical_condition_are_skipped() -> None:
    line = only(
        automation(
            conditions=[
                {
                    "condition": "or",
                    "conditions": [
                        {"condition": "state", "entity_id": "a.b", "state": "on"},
                        {"condition": "template", "value_template": "x", "enabled": False},
                    ],
                }
            ]
        )
    )
    assert line.condition_count == 1
    assert not line.custom_logic


def test_device_trigger_without_for() -> None:
    assert trigger_of(
        {
            "trigger": "device",
            "device_id": "d",
            "domain": "fan",
            "type": "turned_off",
            "entity_id": FAN,
        }
    ) == StateTrigger(entity=FAN, to="off")
