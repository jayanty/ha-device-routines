"""A day's planned actions from the summary: the data of `schedule/today` (TECH_SPEC 4.7).

Build A lane 12 adds `SummaryCoordinator.day_schedule(day)` (decision L45): every action
planned for a local day on every device, routines and hand written automations alike,
with the FR-S6 conflict flag of each action's own minute. These tests use the summary's
own fixtures (a fan and a desk lamp, Monday 2026-10-19 at 08:00 in Los Angeles) and the
fake provider that stands in for the manager. Every name is generic.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest

from custom_components.device_routines import markers
from custom_components.device_routines.models import Status, Verb
from custom_components.device_routines.summary import (
    KIND_AUTOMATION,
    KIND_DETACHED,
    KIND_ROUTINE,
    DayItem,
)
from tests.integration import test_summary
from tests.integration.test_summary import (
    FAN,
    LAMP,
    NIGHTLY,
    ROUTINE_ALIAS,
    ROUTINE_ENTITY,
    WINDOW,
    FakeProvider,
    action,
    at,
    automation,
    coordinator,
    local,
    routine_config,
    routine_item,
    routine_summary,
    start,
    with_provider,
)

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

# The summary's own fixtures: its home (not the manager's of `conftest.py`) and the stand
# in blueprint at the M2 path.
home = test_summary.home
routine_blueprint = test_summary.routine_blueprint

MONDAY = date(2026, 10, 19)
TUESDAY = date(2026, 10, 20)


def rows(items: list[DayItem]) -> list[tuple[Any, ...]]:
    """The readable part of each item: time, device, action, kind, automation, conflict."""
    return [
        (item.time, item.device_id, item.action, item.kind, item.automation, item.conflict)
        for item in items
    ]


async def test_the_day_lists_every_planned_action_by_time_with_its_conflicts(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    fan, lamp = home["fan"].id, home["lamp"].id
    evening_off = automation(
        "evening_off", [at("17:00")], [action("fan.turn_off", {"entity_id": FAN})]
    )
    early_lamp = automation(
        "early_lamp", [at("06:30")], [action("light.turn_on", {"label_id": home["label"].label_id})]
    )
    # Two actions of one automation that read the same for the fan are one entry.
    noon_twice = automation(
        "noon_twice",
        [at("12:00")],
        [
            action("fan.turn_on", {"entity_id": FAN}),
            action("fan.turn_on", {"device_id": fan}),
        ],
    )
    turned_off = automation(
        "turned_off", [at("13:00")], [action("fan.turn_off", {"entity_id": FAN})]
    )
    entry = await start(hass, [WINDOW, evening_off, early_lamp, noon_twice, turned_off])
    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": "automation.turned_off"}, blocking=True
    )
    await hass.async_block_till_done()
    summary = coordinator(entry)

    monday = summary.day_schedule(MONDAY)

    # The whole day, also what was planned before now (08:00); the 17:00 on and off
    # oppose each other in one minute (FR-S6); an automation that is off plans nothing.
    assert rows(monday) == [
        (local(19, 6, 30), lamp, Verb.ON, KIND_AUTOMATION, "automation.early_lamp", False),
        (local(19, 9), fan, Verb.OFF, KIND_AUTOMATION, "automation.fan_window", False),
        (local(19, 12), fan, Verb.ON, KIND_AUTOMATION, "automation.noon_twice", False),
        (local(19, 17), fan, Verb.OFF, KIND_AUTOMATION, "automation.evening_off", True),
        (local(19, 17), fan, Verb.ON, KIND_AUTOMATION, "automation.fan_window", True),
    ]
    assert [item.area_id for item in monday] == [None, *[home["area"].id] * 4]
    # Another day reads the same way and never leaks into its neighbours.
    tuesday = summary.day_schedule(TUESDAY)
    assert [item.time for item in tuesday] == [
        local(20, 6, 30),
        local(20, 9),
        local(20, 12),
        local(20, 17),
        local(20, 17),
    ]


async def test_a_running_routine_plans_its_own_actions_and_its_window_conflicts(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None, freezer: Any
) -> None:
    fan = home["fan"].id
    noon_on = automation("noon_on", [at("12:00")], [action("fan.turn_on", {"entity_id": FAN})])
    entry = await start(hass, [routine_config(fan), noon_on])
    provider = FakeProvider()
    provider.summaries[fan] = routine_summary()
    summary = await with_provider(entry, provider)

    # The 17:00 to 09:00 window from its inputs; the owned automation's parsed line is the
    # routine's item, not a second entry; the noon on falls in the off window (FR-S6).
    assert rows(summary.day_schedule(MONDAY)) == [
        (local(19, 9), fan, Verb.OFF, KIND_ROUTINE, ROUTINE_ENTITY, False),
        (local(19, 12), fan, Verb.ON, KIND_AUTOMATION, "automation.noon_on", True),
        (local(19, 17), fan, Verb.ON, KIND_ROUTINE, ROUTINE_ENTITY, False),
    ]

    # Paused at 10:00 until 18:00: the 17:00 start does not run; the 09:00 end was
    # planned before the pause and stays; tomorrow is untouched.
    freezer.move_to(local(19, 10))
    provider.summaries[fan] = routine_summary(Status.PAUSED, local(19, 18))
    summary.async_refresh_device(fan)
    assert [(item.time, item.kind) for item in summary.day_schedule(MONDAY)] == [
        (local(19, 9), KIND_ROUTINE),
        (local(19, 12), KIND_AUTOMATION),
    ]
    assert [item.time for item in summary.day_schedule(TUESDAY)] == [
        local(20, 9),
        local(20, 12),
        local(20, 17),
    ]

    # A routine that is off plans nothing, and nothing conflicts with it.
    provider.summaries[fan] = routine_summary(Status.OFF)
    summary.async_refresh_device(fan)
    assert rows(summary.day_schedule(MONDAY)) == [
        (local(19, 12), fan, Verb.ON, KIND_AUTOMATION, "automation.noon_on", False),
    ]

    # Nor does an active routine whose automation is off in Home Assistant.
    provider.summaries[fan] = routine_summary()
    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": ROUTINE_ENTITY}, blocking=True
    )
    await hass.async_block_till_done()
    assert [item.kind for item in summary.day_schedule(MONDAY)] == [KIND_AUTOMATION]


async def test_a_routine_without_its_automation_plans_its_next_run_with_no_known_action(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    lamp = home["lamp"].id
    entry = await start(hass, [WINDOW])
    provider = FakeProvider()
    summary = await with_provider(entry, provider)

    provider.summaries[lamp] = routine_summary(items=(routine_item(next_run=local(19, 21)),))
    summary.async_refresh_device(lamp)
    planned = [item for item in summary.day_schedule(MONDAY) if item.device_id == lamp]
    assert rows(planned) == [(local(19, 21), lamp, None, KIND_ROUTINE, ROUTINE_ENTITY, False)]
    assert [item.device_id for item in summary.day_schedule(TUESDAY)] == [home["fan"].id] * 2

    # An item without a next run plans nothing.
    provider.summaries[lamp] = routine_summary(
        items=(routine_item(next_run=local(19, 21)), routine_item("Weekly schedule"))
    )
    summary.async_refresh_device(lamp)
    assert [item.time for item in summary.day_schedule(MONDAY) if item.device_id == lamp] == [
        local(19, 21)
    ]


async def test_a_detached_routine_plans_what_its_automation_does(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    """Take control kept M1 and dropped M2 (Stage 0 V8): the parser reads the automation."""
    fan = home["fan"].id
    detached = automation(
        markers.automation_id(fan),
        [at("17:00")],
        [action("fan.turn_on", {"entity_id": FAN})],
        alias=ROUTINE_ALIAS,
    )
    entry = await start(hass, [detached])
    provider = FakeProvider()
    provider.summaries[fan] = routine_summary(Status.DETACHED)
    summary = await with_provider(entry, provider)

    assert rows(summary.day_schedule(MONDAY)) == [
        (local(19, 17), fan, Verb.ON, KIND_DETACHED, ROUTINE_ENTITY, False)
    ]


async def test_a_device_removed_before_the_rebuild_plans_nothing(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    entry = await start(hass, [WINDOW])

    dr.async_get(hass).async_remove_device(home["fan"].id)

    assert coordinator(entry).day_schedule(MONDAY) == []


async def test_day_items_are_plain_values(hass: HomeAssistant, home: dict[str, Any]) -> None:
    entry = await start(hass, [WINDOW])

    first = coordinator(entry).day_schedule(MONDAY)[0]

    assert isinstance(first.time, datetime)
    assert first.time.utcoffset() == local(19, 9).utcoffset()
    assert first == DayItem(
        time=local(19, 9),
        device_id=home["fan"].id,
        area_id=home["area"].id,
        action=Verb.OFF,
        kind=KIND_AUTOMATION,
        automation="automation.fan_window",
        conflict=False,
        device_name="Living room fan",
        alias="Fan Window",
        conditions=0,
    )


DOOR_CLOSED = {"condition": "state", "entity_id": "binary_sensor.door", "state": "off"}


async def test_day_items_carry_device_name_alias_and_conditions(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None
) -> None:
    """Plan 6.2.5: the device's name, the alias, and the conditions gating each action.

    FR-R9's Today flag: a hand written line counts its conditions on every run; a
    routine's Only when conditions gate its on actions only, as the blueprint gates them.
    """
    fan, lamp = home["fan"].id, home["lamp"].id
    guarded = automation(
        "guarded_lamp",
        [at("06:30")],
        [action("light.turn_on", {"entity_id": LAMP})],
        conditions=[DOOR_CLOSED],
    )
    only_when = replace(NIGHTLY, extra_conditions=(DOOR_CLOSED, DOOR_CLOSED))
    entry = await start(hass, [routine_config(fan, only_when), guarded])
    provider = FakeProvider()
    provider.summaries[fan] = routine_summary()
    summary = await with_provider(entry, provider)

    def read() -> list[tuple[Any, ...]]:
        return [
            (item.time, item.device_name, item.alias, item.action, item.conditions)
            for item in summary.day_schedule(MONDAY)
        ]

    assert read() == [
        (local(19, 6, 30), "Desk lamp", "Guarded Lamp", Verb.ON, 1),
        (local(19, 9), "Living room fan", ROUTINE_ALIAS, Verb.OFF, 0),
        (local(19, 17), "Living room fan", ROUTINE_ALIAS, Verb.ON, 2),
    ]

    # The name a person gave the device wins; a routine whose automation is not indexed
    # names its item's alias and counts no condition, its action being unknown.
    dr.async_get(hass).async_update_device(lamp, name_by_user="Reading lamp")
    provider.summaries[lamp] = routine_summary(items=(routine_item(next_run=local(19, 21)),))
    summary.async_refresh_device(lamp)
    assert [row for row in read() if row[1] == "Reading lamp"] == [
        (local(19, 6, 30), "Reading lamp", "Guarded Lamp", Verb.ON, 1),
        (local(19, 21), "Reading lamp", ROUTINE_ALIAS, None, 0),
    ]
