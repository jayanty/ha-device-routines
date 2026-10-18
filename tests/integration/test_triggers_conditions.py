"""Build A lane 13: the purpose specific triggers and conditions (PRD FR-R17).

`device_routines.action_skipped`, `paused` and `resumed` fire on the manager's bus events
and the blueprint's skip event; `device_routines.is_paused` and `is_active` read the
manager's views. All take a device, area or label target that the manager resolves to
routine devices, triggers take `behavior` each, first or all and conditions any or all,
the shape the core's own purpose specific triggers and conditions have (Stage 0 V13).

The routines run on the shipped blueprint in the synthetic home of the integration
fixtures: the living room fan (the sandbox switch) and the desk lamp, both in the living
room, whose `light` services are mocked so its routine can run. Every name is generic.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import time, timedelta
import json
from pathlib import Path
from typing import Any

from homeassistant.components.automation.config import async_validate_config_item
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import (
    area_registry as ar,
    condition,
    device_registry as dr,
    icon,
    label_registry as lr,
    translation,
    trigger,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.device_routines import compiler
from custom_components.device_routines.condition import async_get_conditions
from custom_components.device_routines.const import DOMAIN, EVENT_PAUSED, EVENT_RESUMED
from custom_components.device_routines.domains import SUPPORTED_DOMAINS
from custom_components.device_routines.manager import RoutineManager
from custom_components.device_routines.models import Status
from custom_components.device_routines.trigger import async_get_triggers
from tests.integration.conftest import FAN, LAMP, Clock, Home, give_routine, save_entry

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / DOMAIN
TRIGGER_KEYS = ("action_skipped", "paused", "resumed")
CONDITION_KEYS = ("is_paused", "is_active")
BEHAVIORS = ("each", "first", "all")
# Device, area and label targets (FR-R17), and the entity and floor targets the selector
# offers too.
TARGET_KINDS = ("device_id", "area_id", "label_id", "entity_id", "floor_id")


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def on(key: str, target: Mapping[str, Any], behavior: str | None = None) -> dict[str, Any]:
    """A trigger of this integration; its id names the key and the behavior."""
    config: dict[str, Any] = {
        "trigger": f"{DOMAIN}.{key}",
        "id": key if behavior is None else f"{key}_{behavior}",
        "target": dict(target),
    }
    if behavior is not None:
        config["options"] = {"behavior": behavior}
    return config


def holds(key: str, target: Mapping[str, Any], behavior: str | None = None) -> dict[str, Any]:
    """A condition of this integration."""
    config: dict[str, Any] = {"condition": f"{DOMAIN}.{key}", "target": dict(target)}
    if behavior is not None:
        config["options"] = {"behavior": behavior}
    return config


def reacting(
    automation_id: str,
    triggers: Iterable[Mapping[str, Any]],
    conditions: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Another automation of the home that reacts to routines and records what it heard.

    It records its own id and, for this integration's triggers, the trigger variables.
    """
    payload = "{{ trigger | tojson if trigger.platform.startswith('device_routines') else '{}' }}"
    return {
        "id": automation_id,
        "alias": f"React {automation_id}",
        "mode": "parallel",
        "max": 100,
        "triggers": list(triggers),
        "conditions": list(conditions),
        "actions": [
            {"action": "test.record", "data": {"automation": automation_id, "heard": payload}}
        ],
    }


async def add_automation(hass: HomeAssistant, config: dict[str, Any]) -> None:
    """Validate an automation as the editor does, then save it into the automations file."""
    validated = await async_validate_config_item(hass, config["id"], config)
    assert validated is not None
    assert validated.validation_status == "ok", validated.validation_error
    await save_entry(hass, config)
    state = hass.states.get(f"automation.react_{config['id']}")
    assert state is not None
    assert state.state == "on"


def heard(calls: list[ServiceCall]) -> list[dict[str, Any]]:
    """Return every recorded trigger payload and forget them."""
    payloads = [
        value if isinstance(value, dict) else json.loads(value)
        for value in (call.data["heard"] for call in calls)
    ]
    calls.clear()
    return payloads


def pairs(calls: list[ServiceCall]) -> list[tuple[str, str]]:
    """Return (trigger id, device id) for every recorded run, sorted, and forget them."""
    return sorted((payload["id"], payload["device_id"]) for payload in heard(calls))


async def check(
    hass: HomeAssistant, key: str, target: Mapping[str, Any], behavior: str | None = None
) -> bool | None:
    """Validate, build and check one condition through the core's condition helper."""
    validated = await condition.async_validate_condition_config(hass, holds(key, target, behavior))
    checker = await condition.async_from_config(hass, validated)
    try:
        return checker.async_check()
    finally:
        checker.async_unload()


def label_devices(hass: HomeAssistant, name: str, *device_ids: str) -> str:
    """Create a label and put it on devices, keeping the labels they already carry."""
    label = lr.async_get(hass).async_create(name)
    devices = dr.async_get(hass)
    for device_id in device_ids:
        device = devices.async_get(device_id)
        assert device is not None
        devices.async_update_device(device_id, labels={*device.labels, label.label_id})
    return label.label_id


@pytest.fixture
def lamp_services(hass: HomeAssistant) -> list[ServiceCall]:
    """The desk lamp is a bare state: its routine's light services are mocked."""
    async_mock_service(hass, "light", "turn_off")
    return async_mock_service(hass, "light", "turn_on")


@pytest.fixture
def calls(hass: HomeAssistant) -> list[ServiceCall]:
    """What the reacting automations recorded."""
    return async_mock_service(hass, "test", "record")


# --------------------------------------------------------------------------------------
# Registration, descriptions, strings and icons
# --------------------------------------------------------------------------------------


async def test_the_platforms_return_exactly_the_contract_keys(hass: HomeAssistant) -> None:
    assert set(await async_get_triggers(hass)) == set(TRIGGER_KEYS)
    assert set(await async_get_conditions(hass)) == set(CONDITION_KEYS)


async def test_the_descriptions_carry_the_target_selector_and_the_behavior_field(
    hass: HomeAssistant, manager: RoutineManager
) -> None:
    """What the editor's pickers read: a target over every domain a routine drives."""
    triggers = await trigger.async_get_all_descriptions(hass)
    conditions = await condition.async_get_all_descriptions(hass)

    for key in TRIGGER_KEYS:
        described = triggers[f"{DOMAIN}.{key}"]
        assert described is not None, key
        (entity_filter,) = described["target"]["entity"]
        assert set(entity_filter["domain"]) == SUPPORTED_DOMAINS
        assert set(described["fields"]) == {"behavior"}
        behavior = described["fields"]["behavior"]
        assert behavior["default"] == "each"
        assert behavior["selector"] == {"automation_behavior": {"mode": "trigger"}}
    for key in CONDITION_KEYS:
        described = conditions[f"{DOMAIN}.{key}"]
        assert described is not None, key
        (entity_filter,) = described["target"]["entity"]
        assert set(entity_filter["domain"]) == SUPPORTED_DOMAINS
        assert set(described["fields"]) == {"behavior"}
        behavior = described["fields"]["behavior"]
        assert behavior["default"] == "any"
        assert behavior["selector"] == {"automation_behavior": {"mode": "condition"}}


async def test_every_trigger_and_condition_has_a_name_a_description_and_an_icon(
    hass: HomeAssistant, manager: RoutineManager
) -> None:
    for category, keys in (("triggers", TRIGGER_KEYS), ("conditions", CONDITION_KEYS)):
        strings = await translation.async_get_translations(hass, "en", category, {DOMAIN})
        icons = await icon.async_get_icons(hass, category, [DOMAIN])
        for key in keys:
            prefix = f"component.{DOMAIN}.{category}.{key}"
            assert strings[f"{prefix}.name"], key
            assert strings[f"{prefix}.description"], key
            assert strings[f"{prefix}.fields.behavior.name"], key
            assert icons[DOMAIN][key][category.removesuffix("s")].startswith("mdi:"), key
    source = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    assert set(source["triggers"]) == set(TRIGGER_KEYS)
    assert set(source["conditions"]) == set(CONDITION_KEYS)


# --------------------------------------------------------------------------------------
# Triggers: device, area and label targets
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", TARGET_KINDS)
async def test_every_trigger_fires_for_each_target_kind(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    calls: list[ServiceCall],
    kind: str,
) -> None:
    """Pause at 16:00 until 17:30: paused, the 17:00 start skipped, resumed at 17:30."""
    clock.set(clock.at(0, "16:00"))
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    targets = {
        "device_id": home.fan,
        "area_id": home.area,
        "label_id": label_devices(hass, "Evening", home.fan),
        "entity_id": FAN,
        "floor_id": home.floor,
    }
    target = {kind: targets[kind]}
    await add_automation(hass, reacting("routines", [on(key, target) for key in TRIGGER_KEYS]))

    await manager.async_pause(home.fan, until=clock.at(0, "17:30"))
    await hass.async_block_till_done()
    (paused,) = heard(calls)
    await clock.to(clock.at(0, "17:00:01"))
    (skipped,) = heard(calls)
    await clock.to(clock.at(0, "17:30:01"))
    (resumed,) = heard(calls)

    until = clock.at(0, "17:30").isoformat()
    common = {
        "platform": f"{DOMAIN}.paused",
        "device_id": home.fan,
        "device_name": "Living room fan",
        "automation_id": automation_id,
    }
    assert paused | common == paused
    assert paused["id"] == "paused"
    assert paused["until"] == until
    assert paused["description"] == "Living room fan routine paused"
    assert skipped | common | {"platform": f"{DOMAIN}.action_skipped"} == skipped
    assert (skipped["trigger_id"], skipped["action"]) == ("scheduled_on", "on")
    assert skipped["description"] == "Living room fan routine skipped an action"
    assert resumed | common | {"platform": f"{DOMAIN}.resumed"} == resumed
    assert resumed["until"] == until
    assert resumed["description"] == "Living room fan routine resumed"


async def test_behavior_each_first_and_all_over_two_routines(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    calls: list[ServiceCall],
    lamp_services: list[ServiceCall],
) -> None:
    """The living room holds two routines; first and all count them as of each event."""
    clock.set(clock.at(0, "12:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    await give_routine(hass, manager, home.lamp, freezer, on_time=time(17))
    fan, lamp = home.fan, home.lamp
    target = {"area_id": home.area}
    await add_automation(
        hass,
        reacting(
            "behaviors",
            [on(key, target, behavior) for key in TRIGGER_KEYS for behavior in BEHAVIORS],
        ),
    )

    # The fan is the first routine of the room to pause.
    await manager.async_pause(fan, until=clock.at(1, "18:00"))
    await hass.async_block_till_done()
    assert pairs(calls) == [("paused_each", fan), ("paused_first", fan)]
    # Its 17:00 start is skipped while it is the only paused routine; the lamp's runs.
    await clock.to(clock.at(0, "17:00:01"))
    assert pairs(calls) == [("action_skipped_each", fan), ("action_skipped_first", fan)]
    assert len(lamp_services) == 1
    # The lamp is the last routine of the room to pause.
    await manager.async_pause(lamp, until=clock.at(1, "18:00"))
    await hass.async_block_till_done()
    assert pairs(calls) == [("paused_all", lamp), ("paused_each", lamp)]
    # Both starts are skipped while every routine of the room is paused.
    await clock.to(clock.at(1, "17:00:01"))
    assert pairs(calls) == sorted(
        [
            ("action_skipped_all", fan),
            ("action_skipped_all", lamp),
            ("action_skipped_each", fan),
            ("action_skipped_each", lamp),
        ]
    )
    # An early Resume: the first routine active again.
    await manager.async_resume(fan)
    await hass.async_block_till_done()
    assert pairs(calls) == [("resumed_each", fan), ("resumed_first", fan)]
    # The lamp's pause ends at its stored time: every routine is active again.
    await clock.to(clock.at(1, "18:00:01"))
    assert pairs(calls) == [("resumed_all", lamp), ("resumed_each", lamp)]
    # One area action pauses both in one go: each event is judged as of its own moment.
    await manager.async_run_action("pause", target, duration=timedelta(hours=1))
    await hass.async_block_till_done()
    assert pairs(calls) == sorted(
        [("paused_each", fan), ("paused_first", fan), ("paused_each", lamp), ("paused_all", lamp)]
    )
    await manager.async_run_action("resume", target)
    await hass.async_block_till_done()
    assert pairs(calls) == sorted(
        [
            ("resumed_each", fan),
            ("resumed_first", fan),
            ("resumed_each", lamp),
            ("resumed_all", lamp),
        ]
    )


async def test_a_routine_that_is_off_neither_pauses_nor_resumes(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    calls: list[ServiceCall],
) -> None:
    """Paused fires as the routine reads paused, resumed as it reads active again."""
    clock.set(clock.at(0, "12:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    target = {"device_id": home.fan}
    await add_automation(hass, reacting("off", [on(key, target) for key in TRIGGER_KEYS]))
    await manager.async_disable(home.fan)
    await hass.async_block_till_done()

    await manager.async_pause(home.fan, duration=timedelta(hours=1))
    await hass.async_block_till_done()
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.OFF
    assert await check(hass, "is_paused", target) is False
    assert await check(hass, "is_active", target) is False
    await manager.async_resume(home.fan)
    await hass.async_block_till_done()

    assert heard(calls) == []


async def test_a_target_with_no_routine_never_fires_and_never_holds(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    calls: list[ServiceCall],
) -> None:
    clock.set(clock.at(0, "16:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    await manager.async_opt_in(home.lamp)  # controls, but no routine yet
    hallway = ar.async_get(hass).async_create("Hallway")
    dr.async_get(hass).async_update_device(home.garage, area_id=hallway.id)
    targets: list[dict[str, Any]] = [
        {"device_id": home.lamp},
        {"device_id": home.garage},
        {"device_id": "no-such-device"},
        {"entity_id": LAMP},
        {"area_id": hallway.id},
        {"area_id": "nowhere"},
        {"label_id": label_devices(hass, "Spare", home.lamp, home.garage)},
        {"label_id": label_devices(hass, "Unused")},
    ]
    await add_automation(
        hass,
        reacting(
            "nothing",
            [
                on(key, target, behavior)
                for key in TRIGGER_KEYS
                for target in targets
                for behavior in BEHAVIORS
            ],
        ),
    )

    await manager.async_pause(home.fan, until=clock.at(0, "17:30"))
    await clock.to(clock.at(0, "17:30:01"))
    # Events about a device the target does not name change nothing either.
    hass.bus.async_fire(EVENT_PAUSED, {"device_id": home.lamp, "automation_id": "x"})
    hass.bus.async_fire(compiler.EVENT_ACTION_SKIPPED, {"device_id": "no-such-device"})
    await hass.async_block_till_done()

    assert heard(calls) == []
    for target in targets:
        for key in CONDITION_KEYS:
            for behavior in ("any", "all"):
                assert await check(hass, key, target, behavior) is False, (target, key)


async def test_an_unloaded_entry_fires_nothing_and_no_condition_holds(
    hass: HomeAssistant,
    home: Home,
    routines: MockConfigEntry,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    calls: list[ServiceCall],
) -> None:
    clock.set(clock.at(0, "16:00"))
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    target = {"device_id": home.fan}
    await add_automation(hass, reacting("unloaded", [on(key, target) for key in TRIGGER_KEYS]))
    await manager.async_pause(home.fan, duration=timedelta(hours=1))
    await hass.async_block_till_done()
    assert [payload["id"] for payload in heard(calls)] == ["paused"]
    assert await check(hass, "is_paused", target) is True

    assert await hass.config_entries.async_unload(routines.entry_id)
    await hass.async_block_till_done()
    data = {"device_id": home.fan, "automation_id": automation_id, "until": None}
    for event_type in (EVENT_PAUSED, EVENT_RESUMED, compiler.EVENT_ACTION_SKIPPED):
        hass.bus.async_fire(event_type, data)
    await hass.async_block_till_done()

    assert heard(calls) == []
    for key in CONDITION_KEYS:
        assert await check(hass, key, target) is False


# --------------------------------------------------------------------------------------
# Conditions
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", TARGET_KINDS)
async def test_conditions_hold_in_an_automation_for_each_target_kind(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    calls: list[ServiceCall],
    kind: str,
) -> None:
    clock.set(clock.at(0, "12:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    targets = {
        "device_id": home.fan,
        "area_id": home.area,
        "label_id": label_devices(hass, "Evening", home.fan),
        "entity_id": FAN,
        "floor_id": home.floor,
    }
    target = {kind: targets[kind]}
    asked = [{"trigger": "event", "event_type": "routine_check", "id": "asked"}]
    await add_automation(hass, reacting("when_paused", asked, [holds("is_paused", target)]))
    await add_automation(hass, reacting("when_active", asked, [holds("is_active", target)]))

    async def ask() -> list[str]:
        hass.bus.async_fire("routine_check")
        await hass.async_block_till_done()
        answered = sorted(call.data["automation"] for call in calls)
        calls.clear()
        return answered

    assert await ask() == ["when_active"]
    await manager.async_pause(home.fan, duration=timedelta(hours=1))
    await hass.async_block_till_done()
    assert await ask() == ["when_paused"]


async def test_is_paused_and_is_active_with_any_and_all(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    lamp_services: list[ServiceCall],
) -> None:
    """A skip is a pause until its paired end (D18, D19); active is on and not paused."""
    clock.set(clock.at(0, "12:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    await give_routine(hass, manager, home.lamp, freezer, on_time=time(17), off_time=time(23))
    target = {"area_id": home.area}

    async def table() -> dict[str, bool | None]:
        return {
            f"{key} {behavior}": await check(hass, key, target, behavior)
            for key in CONDITION_KEYS
            for behavior in ("any", "all")
        }

    assert await table() == {
        "is_paused any": False,
        "is_paused all": False,
        "is_active any": True,
        "is_active all": True,
    }
    assert await check(hass, "is_active", target) is True  # any is the default

    await manager.async_pause(home.fan, duration=timedelta(hours=1))
    assert await table() == {
        "is_paused any": True,
        "is_paused all": False,
        "is_active any": True,
        "is_active all": False,
    }

    await manager.async_skip_next(home.lamp)
    view = manager.get(home.lamp)
    assert view is not None
    assert view.status is Status.SKIPPING
    assert await table() == {
        "is_paused any": True,
        "is_paused all": True,
        "is_active any": False,
        "is_active all": False,
    }

    await manager.async_run_action("resume", target)
    await manager.async_disable(home.fan)
    await hass.async_block_till_done()
    assert await table() == {
        "is_paused any": False,
        "is_paused all": False,
        "is_active any": True,
        "is_active all": False,
    }
