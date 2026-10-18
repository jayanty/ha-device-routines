"""Exact conversion matches (PRD FR-M1, decision L61): one test per shape and per exclusion.

Every automation here is synthetic: a coffee maker switch scheduled by hand, a bathroom fan
turned off after a while. A match is offered only when the routine does exactly what the
automation does; anything else, partial matches included, is None.
"""

from __future__ import annotations

from collections.abc import Callable
import copy
from datetime import time
from typing import Any

from hypothesis import given, settings as hypothesis_settings, strategies as st
import pytest

from custom_components.device_routines import compiler, conversion, domains
from custom_components.device_routines.models import (
    ALL_DAYS,
    Days,
    DeviceContext,
    EntityRef,
    RoutineSettings,
    Weekday,
)

SWITCH = "switch.coffee_maker"
POWER = "sensor.coffee_maker_power"
FAN = "fan.bathroom_fan"
LIGHT = "light.patio_light"
CLIMATE = "climate.hallway_thermostat"
REGISTRY_ID = "ab" * 16
DEVICE = DeviceContext(
    "device-1",
    (EntityRef(SWITCH), EntityRef(POWER), EntityRef(FAN), EntityRef(LIGHT), EntityRef(CLIMATE)),
    registry_ids={REGISTRY_ID: SWITCH},
)

type Config = dict[str, Any]


def on(entity: str = SWITCH, **extra: Any) -> Config:
    domain = entity.partition(".")[0]
    profile = domains.PROFILES[domain]
    return {"action": profile.on_action, "target": {"entity_id": entity}, **extra}


def off(entity: str = SWITCH, **extra: Any) -> Config:
    domain = entity.partition(".")[0]
    return {"action": domains.PROFILES[domain].off_action, "target": {"entity_id": entity}, **extra}


def trigger_is(trigger_id: Any) -> Config:
    return {"condition": "trigger", "id": trigger_id}


def scheduled(on_at: str = "06:30:00", off_at: str = "09:00:00", entity: str = SWITCH) -> Config:
    """FR-R1 as the automation editor writes it: two time triggers and a `choose`."""
    return {
        "id": "1760000000001",
        "alias": "Coffee maker schedule",
        "description": "",
        "mode": "single",
        "triggers": [
            {"trigger": "time", "at": on_at, "id": "start"},
            {"trigger": "time", "at": off_at, "id": "stop"},
        ],
        "conditions": [],
        "actions": [
            {
                "choose": [
                    {"conditions": [trigger_is("start")], "sequence": [on(entity)]},
                    {"conditions": [trigger_is("stop")], "sequence": [off(entity)]},
                ]
            }
        ],
    }


def turned_off_after(period: Any = None, entity: str = FAN) -> Config:
    """FR-R3 as the editor writes it: a state trigger held for a while, one off action."""
    return {
        "id": "1760000000002",
        "alias": "Bathroom fan failsafe",
        "description": "",
        "mode": "single",
        "triggers": [
            {
                "trigger": "state",
                "entity_id": [entity],
                "to": "on",
                "for": {"hours": 0, "minutes": 60, "seconds": 0} if period is None else period,
            }
        ],
        "conditions": [],
        "actions": [off(entity)],
    }


MORNING = RoutineSettings(SWITCH, on_time=time(6, 30), off_time=time(9))


def weekday(days: Any) -> Config:
    return {"condition": "time", "weekday": days}


# --------------------------------------------------------------------------------------
# FR-R1: positive shapes
# --------------------------------------------------------------------------------------


def test_scheduled_times_as_a_choose() -> None:
    assert conversion.match(scheduled(), DEVICE) == MORNING
    # The options in either order, the triggers in either order.
    config = scheduled()
    config["actions"][0]["choose"].reverse()
    config["triggers"].reverse()
    assert conversion.match(config, DEVICE) == MORNING


def test_scheduled_times_as_an_if() -> None:
    with_else = scheduled()
    with_else["actions"] = [{"if": [trigger_is("start")], "then": [on()], "else": [off()]}]
    assert conversion.match(with_else, DEVICE) == MORNING
    off_first = scheduled()
    off_first["actions"] = [{"if": [trigger_is("stop")], "then": [off()], "else": [on()]}]
    assert conversion.match(off_first, DEVICE) == MORNING
    two_ifs = scheduled()
    two_ifs["actions"] = [
        {"if": [trigger_is("start")], "then": [on()]},
        {"if": [trigger_is("stop")], "then": [off()]},
    ]
    assert conversion.match(two_ifs, DEVICE) == MORNING


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (["mon", "tue", "wed", "thu", "fri"], {"days": Days.WEEKDAYS}),
        (["sat", "sun"], {"days": Days.WEEKENDS}),
        ("tue", {"days": Days.SOME_DAYS, "day_set": frozenset({Weekday.TUE})}),
        (
            ["mon", "wed", "wed"],
            {"days": Days.SOME_DAYS, "day_set": frozenset({Weekday.MON, Weekday.WED})},
        ),
        ([day.value for day in Weekday], {"days": Days.EVERY_DAY}),
    ],
)
def test_scheduled_times_with_a_weekday_condition(days: Any, expected: dict[str, Any]) -> None:
    config = scheduled()
    config["conditions"] = [weekday(days)]
    settings = RoutineSettings(SWITCH, on_time=time(6, 30), off_time=time(9), **expected)
    assert conversion.match(config, DEVICE) == settings
    assert compiler.canonical(settings) == settings
    # The same weekdays on both triggers mean the same.
    on_triggers = scheduled()
    for node in on_triggers["triggers"]:
        node["weekday"] = days
    assert conversion.match(on_triggers, DEVICE) == settings


def test_scheduled_times_in_the_forms_the_core_accepts() -> None:
    """Legacy keys, default trigger ids, registry ids, one item lists, `HH:MM` times."""
    config: Config = {
        "alias": "Coffee maker schedule",
        "trigger": [
            {"platform": "time", "at": "06:30"},
            {"platform": "time", "at": "09:00"},
        ],
        "condition": weekday("sat"),
        "action": {
            "choose": [
                {
                    "conditions": trigger_is(["0"]),
                    "sequence": {"action": "switch.turn_on", "target": {"entity_id": REGISTRY_ID}},
                },
                {
                    "alias": "Stop",
                    "conditions": [trigger_is(["1", "1"])],
                    "sequence": [{"service": "switch.turn_off", "target": {"entity_id": [SWITCH]}}],
                },
            ]
        },
        "max_exceeded": "silent",
        "trace": {"stored_traces": 5},
        "initial_state": True,
    }
    assert conversion.match(config, DEVICE) == RoutineSettings(
        SWITCH,
        on_time=time(6, 30),
        off_time=time(9),
        days=Days.SOME_DAYS,
        day_set=frozenset({Weekday.SAT}),
    )


def test_scheduled_times_across_midnight_every_day() -> None:
    assert conversion.match(scheduled("17:00", "09:00"), DEVICE) == RoutineSettings(
        SWITCH, on_time=time(17), off_time=time(9)
    )


@pytest.mark.parametrize(
    "entity", ["fan.bathroom_fan", "light.patio_light", "climate.hallway_thermostat"]
)
def test_scheduled_times_use_the_domain_actions(entity: str) -> None:
    assert conversion.match(scheduled(entity=entity), DEVICE) == RoutineSettings(
        entity, on_time=time(6, 30), off_time=time(9)
    )


# --------------------------------------------------------------------------------------
# FR-R3: positive shape
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "minutes"),
    [
        (None, 60),
        ({"minutes": 30}, 30),
        ("00:30:00", 30),
        ("1:00", 60),
        (1800, 30),
        ({"hours": 24}, 1440),
        ({"minutes": 1}, 1),
        ({"seconds": 120}, 2),
    ],
)
def test_turn_off_after(period: Any, minutes: int) -> None:
    assert conversion.match(turned_off_after(period), DEVICE) == RoutineSettings(
        FAN, turn_off_after_min=minutes
    )


def test_turn_off_after_from_off_on_a_single_entity_id() -> None:
    config = turned_off_after()
    config["triggers"][0] |= {"from": "off", "entity_id": FAN, "id": "held", "alias": "Held on"}
    assert conversion.match(config, DEVICE) == RoutineSettings(FAN, turn_off_after_min=60)
    light = turned_off_after({"minutes": 5}, LIGHT)
    assert conversion.match(light, DEVICE) == RoutineSettings(LIGHT, turn_off_after_min=5)


# --------------------------------------------------------------------------------------
# One test per exclusion (L61)
# --------------------------------------------------------------------------------------

type Change = Callable[[Config], None]


def set_in(path: tuple[Any, ...], value: Any) -> Change:
    def change(config: Config) -> None:
        node: Any = config
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return change


def delete_in(path: tuple[Any, ...]) -> Change:
    def change(config: Config) -> None:
        node: Any = config
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]

    return change


def append_in(path: tuple[Any, ...], value: Any) -> Change:
    def change(config: Config) -> None:
        node: Any = config
        for key in path:
            node = node[key]
        node.append(value)

    return change


def both(*changes: Change) -> Change:
    def change(config: Config) -> None:
        for each in changes:
            each(config)

    return change


START = ("actions", 0, "choose", 0)
START_STEP = (*START, "sequence", 0)
NOTIFY = {"action": "notify.notify", "data": {"message": "Coffee is on"}}

SCHEDULE_EXCLUSIONS: list[tuple[str, Change]] = [
    ("a templated time", set_in(("triggers", 0, "at"), "{{ '06:30' }}")),
    ("a templated target", set_in((*START_STEP, "target", "entity_id"), "{{ 'switch.x' }}")),
    ("a template condition", set_in(("conditions",), [{"condition": "template"}])),
    ("variables on the automation", set_in(("variables",), {"level": 1})),
    ("variables on a trigger", set_in(("triggers", 0, "variables"), {"level": 1})),
    ("a variables step", set_in((*START, "sequence"), [{"variables": {"a": 1}}, on()])),
    ("a second entity", set_in((*START_STEP, "target", "entity_id"), [SWITCH, FAN])),
    ("the other entity off", set_in((*START, "sequence"), [on(FAN)])),
    ("a device target", set_in((*START_STEP, "target"), {"device_id": "device-1"})),
    ("an entity of another device", set_in((*START_STEP, "target", "entity_id"), "switch.x")),
    ("an unknown registry id", set_in((*START_STEP, "target", "entity_id"), "f" * 32)),
    ("a delay", set_in((*START, "sequence"), [{"delay": "00:01:00"}, on()])),
    ("a notification", set_in((*START, "sequence"), [on(), NOTIFY])),
    ("a scene", set_in((*START, "sequence"), [{"action": "scene.turn_on", "target": {}}])),
    ("a toggle", set_in((*START_STEP, "action"), "switch.toggle")),
    ("on twice", set_in(("actions", 0, "choose", 1, "sequence"), [on()])),
    (
        "a third option",
        append_in(("actions", 0, "choose"), {"conditions": [trigger_is("start")], "sequence": []}),
    ),
    ("a default", set_in(("actions", 0, "default"), [off()])),
    ("a second step", append_in(("actions",), NOTIFY)),
    ("a disabled trigger", set_in(("triggers", 1, "enabled"), False)),
    ("a disabled action", set_in((*START_STEP, "enabled"), False)),
    ("a disabled choose", set_in(("actions", 0, "enabled"), False)),
    ("a disabled condition", set_in(("conditions",), [weekday("mon") | {"enabled": False}])),
    ("a templated enable", set_in(("triggers", 0, "enabled"), "yes")),
    ("data on the action", set_in((*START_STEP, "data"), {"brightness_pct": 50})),
    ("data in the target", set_in((*START_STEP, "target", "brightness"), 50)),
    ("continue on error", set_in((*START_STEP, "continue_on_error"), True)),
    ("seconds", set_in(("triggers", 0, "at"), "06:30:15")),
    ("an entity held time", set_in(("triggers", 0, "at"), "input_datetime.coffee_time")),
    (
        "an entity held time with an offset",
        set_in(("triggers", 0, "at"), {"entity_id": "sensor.alarm", "offset": "-00:05:00"}),
    ),
    ("two times on one trigger", set_in(("triggers", 0, "at"), ["06:30", "07:30"])),
    ("a state condition", set_in(("conditions",), [{"condition": "state", "entity_id": POWER}])),
    (
        "a time window",
        set_in(("conditions",), [{"condition": "time", "after": "06:00", "weekday": "mon"}]),
    ),
    ("a sun condition", set_in(("conditions",), [{"condition": "sun", "after": "sunrise"}])),
    ("two conditions", set_in(("conditions",), [weekday("mon"), weekday("tue")])),
    ("a bad weekday", set_in(("conditions",), [weekday(["monday"])])),
    ("another condition in an option", append_in((*START, "conditions"), weekday("mon"))),
    ("weekdays on one trigger only", set_in(("triggers", 0, "weekday"), "mon")),
    (
        "other weekdays on each trigger",
        both(set_in(("triggers", 0, "weekday"), "mon"), set_in(("triggers", 1, "weekday"), "tue")),
    ),
    (
        "weekdays on the triggers and a condition",
        both(
            set_in(("triggers", 0, "weekday"), "mon"),
            set_in(("triggers", 1, "weekday"), "mon"),
            set_in(("conditions",), [weekday("mon")]),
        ),
    ),
    ("a bad weekday on the triggers", set_in(("triggers", 0, "weekday"), ["noday"])),
    ("one time twice", set_in(("triggers", 1, "at"), "06:30")),
    ("one id twice", set_in(("triggers", 1, "id"), "start")),
    ("an id that is not text", set_in(("triggers", 0, "id"), 7)),
    ("an option for no trigger", set_in((*START, "conditions"), [trigger_is("never")])),
    ("an option for both", set_in((*START, "conditions"), [trigger_is(["start", "stop"])])),
    (
        "one trigger runs both",
        set_in(("actions", 0, "choose", 1, "conditions"), [trigger_is("start")]),
    ),
    ("a third trigger", append_in(("triggers",), {"trigger": "homeassistant", "event": "start"})),
    ("one trigger only", delete_in(("triggers", 1))),
    ("a sun trigger", set_in(("triggers", 0), {"trigger": "sun", "event": "sunset"})),
    ("both trigger and platform", set_in(("triggers", 0, "platform"), "time")),
    ("both triggers and trigger", set_in(("trigger",), [])),
    ("action and service", set_in((*START_STEP, "service"), "switch.turn_on")),
    ("a blueprint", set_in(("use_blueprint",), {"path": "x.yaml"})),
]


@pytest.mark.parametrize(
    "change",
    [item[1] for item in SCHEDULE_EXCLUSIONS],
    ids=[item[0] for item in SCHEDULE_EXCLUSIONS],
)
def test_scheduled_times_exclusions(change: Change) -> None:
    config = scheduled()
    assert conversion.match(config, DEVICE) == MORNING
    change(config)
    assert conversion.match(config, DEVICE) is None


def test_a_window_across_midnight_with_weekdays_is_not_a_match() -> None:
    """The automation ends Friday's window on Friday morning; a routine on Saturday's."""
    config = scheduled("17:00", "09:00")
    config["conditions"] = [weekday(["mon", "tue", "wed", "thu", "fri"])]
    assert conversion.match(config, DEVICE) is None
    for node in config["triggers"]:
        node["weekday"] = ["mon", "tue", "wed", "thu", "fri"]
    config["conditions"] = []
    assert conversion.match(config, DEVICE) is None
    # Every day it is the same window.
    config["conditions"] = [weekday([day.value for day in Weekday])]
    for node in config["triggers"]:
        del node["weekday"]
    assert conversion.match(config, DEVICE) == RoutineSettings(
        SWITCH, on_time=time(17), off_time=time(9)
    )


def test_an_if_form_must_be_exact() -> None:
    for actions in (
        [{"if": [trigger_is("start")], "then": [on()], "else": [off()]}, NOTIFY],
        [{"if": [trigger_is("start")], "then": [on(), NOTIFY], "else": [off()]}],
        [{"if": [trigger_is("start")], "then": [on()], "else": [off(), NOTIFY]}],
        [{"if": [trigger_is("start")], "then": [on()]}],
        [{"if": [trigger_is("start")]}],
        [{"if": [trigger_is("start")], "then": [on()]}, {"if": [], "then": [off()]}],
        [{"if": [trigger_is("start"), weekday("mon")], "then": [on()], "else": [off()]}],
        [{"if": "{{ trigger.id == 'start' }}", "then": [on()], "else": [off()]}],
        [{"if": [{"condition": "trigger"}], "then": [on()], "else": [off()]}],
        [{"if": [trigger_is([])], "then": [on()], "else": [off()]}],
        [{"if": [trigger_is([1])], "then": [on()], "else": [off()]}],
        [{"if": [trigger_is("start")], "then": [on()], "else": [off()], "enabled": False}],
        [
            {"if": [trigger_is("start")], "then": [on()], "else": [off()]},
            {"if": [trigger_is("stop")], "then": [off()]},
        ],
        [{"choose": [{"conditions": [trigger_is("start")], "sequence": [on()]}]}],
        [{"choose": ["nonsense", {"conditions": [trigger_is("stop")], "sequence": [off()]}]}],
        [{"choose": [{"conditions": [trigger_is("start")], "sequence": [], "enabled": True}]}],
        [{"choose": [{"conditions": [trigger_is("start")], "sequence": [on(), off()]}]}],
    ):
        config = scheduled()
        config["actions"] = actions
        assert conversion.match(config, DEVICE) is None, actions


def test_a_profile_without_an_on_action_has_no_scheduled_times() -> None:
    lock = DeviceContext("device-2", (EntityRef("lock.front_door"),))
    config = scheduled()
    config["actions"][0]["choose"][0]["sequence"] = [
        {"action": "lock.unlock", "target": {"entity_id": "lock.front_door"}}
    ]
    config["actions"][0]["choose"][1]["sequence"] = [
        {"action": "lock.lock", "target": {"entity_id": "lock.front_door"}}
    ]
    assert conversion.match(config, lock) is None
    unsupported = DeviceContext("device-3", (EntityRef("siren.porch"),))
    siren = scheduled()
    for index, service in enumerate(("siren.turn_on", "siren.turn_off")):
        siren["actions"][0]["choose"][index]["sequence"] = [
            {"action": service, "target": {"entity_id": "siren.porch"}}
        ]
    assert conversion.match(siren, unsupported) is None


HELD = ("triggers", 0)
TURN_OFF_EXCLUSIONS: list[tuple[str, Change]] = [
    ("to off", set_in((*HELD, "to"), "off")),
    ("to a list", set_in((*HELD, "to"), ["on"])),
    ("to true", set_in((*HELD, "to"), True)),
    ("no to", delete_in((*HELD, "to"))),
    ("from unavailable", set_in((*HELD, "from"), "unavailable")),
    ("from none", set_in((*HELD, "from"), None)),
    ("not to unavailable", set_in((*HELD, "not_to"), ["unavailable"])),
    ("no for", delete_in((*HELD, "for"))),
    ("for zero", set_in((*HELD, "for"), "00:00:00")),
    ("for a day and a minute", set_in((*HELD, "for"), {"minutes": 1441})),
    ("for seconds", set_in((*HELD, "for"), "00:30:15")),
    ("for a fraction of a minute", set_in((*HELD, "for"), {"minutes": 0.5})),
    ("for negative", set_in((*HELD, "for"), "-00:30:00")),
    ("for a template", set_in((*HELD, "for"), "{{ 30 }}")),
    ("for infinite seconds", set_in((*HELD, "for"), {"seconds": float("inf")})),
    ("for no number", set_in((*HELD, "for"), {"seconds": float("nan")})),
    ("for too many hours", set_in((*HELD, "for"), "99999999999:00")),
    ("for infinite", set_in((*HELD, "for"), float("inf"))),
    ("a second entity", set_in((*HELD, "entity_id"), [FAN, LIGHT])),
    ("another device's entity", set_in((*HELD, "entity_id"), "fan.other")),
    ("an attribute", set_in((*HELD, "attribute"), "percentage")),
    ("an id that is not text", set_in((*HELD, "id"), 3)),
    ("a disabled trigger", set_in((*HELD, "enabled"), False)),
    ("a second trigger", append_in(("triggers",), {"trigger": "homeassistant", "event": "start"})),
    ("a condition", set_in(("conditions",), [weekday("mon")])),
    ("off on another entity", set_in(("actions",), [off(LIGHT)])),
    ("on instead of off", set_in(("actions",), [on(FAN)])),
    ("a toggle", set_in(("actions", 0, "action"), "fan.toggle")),
    ("data on the action", set_in(("actions", 0, "data"), {"percentage": 0})),
    ("a second action", append_in(("actions",), NOTIFY)),
    ("a delay first", set_in(("actions",), [{"delay": 5}, off(FAN)])),
    ("a disabled action", set_in(("actions", 0, "enabled"), False)),
    ("a choose", set_in(("actions",), [{"choose": [{"conditions": [], "sequence": [off(FAN)]}]}])),
    ("no action", set_in(("actions",), [])),
    ("a time trigger", set_in(HELD, {"trigger": "time", "at": "07:00"})),
]


@pytest.mark.parametrize(
    "change",
    [item[1] for item in TURN_OFF_EXCLUSIONS],
    ids=[item[0] for item in TURN_OFF_EXCLUSIONS],
)
def test_turn_off_after_exclusions(change: Change) -> None:
    config = turned_off_after()
    assert conversion.match(config, DEVICE) == RoutineSettings(FAN, turn_off_after_min=60)
    change(config)
    assert conversion.match(config, DEVICE) is None


def test_turn_off_after_only_where_on_is_every_turn_on() -> None:
    """A thermostat turns on into heat or cool, never into `on`: no exact match."""
    thermostat = turned_off_after({"minutes": 30}, CLIMATE)
    assert conversion.match(thermostat, DEVICE) is None


@pytest.mark.parametrize("config", [None, [], "automation", 42, {}, {"alias": "Nothing"}])
def test_what_is_no_automation_is_no_match(config: Any) -> None:
    assert conversion.match(config, DEVICE) is None


def test_a_match_validates_against_its_profile() -> None:
    """The caller (lane 20) offers what validates; every positive shape here does."""
    for config, settings in (
        (scheduled(), MORNING),
        (turned_off_after(), RoutineSettings(FAN, turn_off_after_min=60)),
    ):
        found = conversion.match(config, DEVICE)
        assert found == settings
        profile = domains.PROFILES[settings.target_entity.partition(".")[0]]
        assert compiler.validate(found, profile) == []
        assert compiler.canonical(found) == found
        assert found.day_set == ALL_DAYS


# --------------------------------------------------------------------------------------
# Never raises
# --------------------------------------------------------------------------------------

KEYS = st.sampled_from(
    [
        "triggers",
        "trigger",
        "conditions",
        "condition",
        "actions",
        "action",
        "at",
        "id",
        "platform",
        "weekday",
        "entity_id",
        "to",
        "from",
        "for",
        "choose",
        "conditions",
        "sequence",
        "if",
        "then",
        "else",
        "service",
        "target",
        "enabled",
        "alias",
        "minutes",
        "seconds",
        "hours",
    ]
)
WORDS = st.sampled_from(
    [
        "time",
        "state",
        "trigger",
        "on",
        "off",
        "06:30",
        "09:00:00",
        "00:30:00",
        "-1:00",
        "start",
        "stop",
        "0",
        "1",
        "mon",
        SWITCH,
        FAN,
        REGISTRY_ID,
        "switch.turn_on",
        "switch.turn_off",
        "fan.turn_off",
        "{{ x }}",
    ]
)
LEAVES = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=True, allow_infinity=True)
    | st.text(max_size=6)
    | WORDS
)
VALUES = st.recursive(
    LEAVES,
    lambda children: (
        st.lists(children, max_size=4)
        | st.dictionaries(KEYS | st.text(max_size=4), children, max_size=5)
    ),
    max_leaves=40,
)


@st.composite
def mutated(draw: st.DrawFn) -> Any:
    """A valid config with one value somewhere in it replaced by anything at all."""
    config: Any = copy.deepcopy(draw(st.sampled_from([scheduled(), turned_off_after()])))
    node = config
    for _ in range(draw(st.integers(0, 6))):
        children = list(node.items()) if isinstance(node, dict) else list(enumerate(node))
        children = [(key, value) for key, value in children if isinstance(value, dict | list)]
        if not children:
            break
        key, value = draw(st.sampled_from(children))
        if draw(st.booleans()):
            node[key] = draw(VALUES)
            return config
        node = value
    if isinstance(node, dict):
        node[draw(KEYS)] = draw(VALUES)
    elif node:
        node[draw(st.integers(0, len(node) - 1))] = draw(VALUES)
    return config


@hypothesis_settings(max_examples=600, deadline=None)
@given(config=VALUES | mutated())
def test_conversion_never_raises(config: Any) -> None:
    found = conversion.match(config, DEVICE)
    assert found is None or isinstance(found, RoutineSettings)
