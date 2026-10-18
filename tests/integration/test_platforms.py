"""Build A lane 8: the routine controls on the device page and the hub Clean up now button.

TECH_SPEC 4.5 and PRD 4.2: every control is a thin caller of the RoutineManager and sits
on the user's device page through the linked record (decision L25). The tests run the
real manager, the real blueprint and the real platforms over the synthetic home of
`conftest.py`. Every id and name is synthetic.
"""

from __future__ import annotations

import ast
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er, restore_state
from homeassistant.helpers.restore_state import RestoredExtraData, StoredState
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_routines import compiler, ha_adapter, maintenance
from custom_components.device_routines.const import DOMAIN, PLATFORMS
from custom_components.device_routines.domains import PROFILES
from custom_components.device_routines.entity import (
    DeviceRoutinesDeviceEntity,
    RuntimeExtraData,
    runtime_from_dict,
)
from custom_components.device_routines.maintenance import MaintenanceAction
from custom_components.device_routines.manager import (
    ManagerEvent,
    RestoredRuntime,
    RoutineManager,
    UpdateResult,
)
from custom_components.device_routines.models import (
    Occurrence,
    Problem,
    Source,
    Status,
    Verb,
    Weekday,
)
from custom_components.device_routines.number import TurnBackOnAfterNumber
from custom_components.device_routines.select import TargetSelect
from custom_components.device_routines.switch import (
    CatchUpSwitch,
    RespectManualSwitch,
    RoutineSwitch,
)
from tests.integration.conftest import (
    ALIAS,
    AUTOMATION,
    FAN,
    LAMP,
    OVERRIDE,
    PAUSED,
    TIMER,
    Clock,
    Home,
    add_device,
    file_entry,
    flush,
    give_routine,
    inputs_of,
    save_entry,
    state_of,
)

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / DOMAIN

# The controls of TECH_SPEC 4.5 per domain profile (PRD 5.3).
EVERY_PAGE = frozenset(
    {
        "routine",
        "off_time",
        "days",
        "catch_up",
        "respect_manual",
        "skip_next",
        "resume",
        "paused_until",
        "manual_override",
    }
)
TOGGLE = EVERY_PAGE | {"on_time", "turn_off_after", "turn_back_on_after"}
OPEN_CLOSE = EVERY_PAGE | {"on_time", "turn_off_after"}  # climate, cover, valve
OFF_ONLY = EVERY_PAGE | {"turn_off_after"}  # media player, lock, refused cover and valve
START_DOCK = EVERY_PAGE | {"on_time"}  # vacuum, lawn mower

# Key: platform, entity category, enabled by default (TECH_SPEC 4.5).
TABLE: dict[str, tuple[str, EntityCategory | None, bool]] = {
    "routine": ("switch", EntityCategory.CONFIG, True),
    "on_time": ("time", EntityCategory.CONFIG, True),
    "off_time": ("time", EntityCategory.CONFIG, True),
    "days": ("select", EntityCategory.CONFIG, True),
    "turn_off_after": ("number", EntityCategory.CONFIG, True),
    "turn_back_on_after": ("number", EntityCategory.CONFIG, False),
    "catch_up": ("switch", EntityCategory.CONFIG, False),
    "respect_manual": ("switch", EntityCategory.CONFIG, False),
    "skip_next": ("button", None, True),
    "resume": ("button", None, True),
    "paused_until": ("datetime", None, True),
    "manual_override": ("switch", EntityCategory.DIAGNOSTIC, True),
    "target": ("select", EntityCategory.CONFIG, True),
}
CONFIG_KEYS = {key for key, (_, category, _) in TABLE.items() if category is EntityCategory.CONFIG}


def page(hass: HomeAssistant, device_id: str) -> dict[str, er.RegistryEntry]:
    """Every device page control of a device in the registry by key, the Schedule aside."""
    prefix = f"{DOMAIN}_{device_id}_"
    return {
        entry.unique_id.removeprefix(prefix): entry
        for entry in er.async_get(hass).entities.values()
        if entry.platform == DOMAIN
        and entry.unique_id.startswith(prefix)
        and entry.unique_id != f"{prefix}schedule"
    }


def entity_of(hass: HomeAssistant, device_id: str, key: str) -> str:
    entry = page(hass, device_id).get(key)
    assert entry is not None, key
    return entry.entity_id


def add_entity(
    hass: HomeAssistant, home: Home, device_id: str, entity_id: str, state: str = "off"
) -> None:
    """Give an existing device of the sandbox integration one more entity."""
    domain, _, object_id = entity_id.partition(".")
    er.async_get(hass).async_get_or_create(
        domain,
        "sandbox",
        object_id,
        device_id=device_id,
        suggested_object_id=object_id,
        config_entry=home.source,
    )
    hass.states.async_set(entity_id, state)


async def call(hass: HomeAssistant, domain: str, service: str, **data: Any) -> None:
    await hass.services.async_call(domain, service, data, blocking=True)
    await hass.async_block_till_done()


def shown(hass: HomeAssistant, entity_id: str) -> State:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state


# --------------------------------------------------------------------------------------
# The entity set per domain profile, categories and defaults (TECH_SPEC 4.5, PRD 5.3)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entity_id", "state", "device_class", "controls", "on_name", "off_name"),
    [
        ("switch.sandbox_heater", "off", None, TOGGLE, "Turn on at", "Turn off at"),
        ("light.sandbox_lamp", "off", None, TOGGLE, "Turn on at", "Turn off at"),
        ("fan.sandbox_fan", "off", None, TOGGLE, "Turn on at", "Turn off at"),
        ("input_boolean.sandbox_flag", "off", None, TOGGLE, "Turn on at", "Turn off at"),
        ("humidifier.sandbox_humidifier", "off", None, TOGGLE, "Turn on at", "Turn off at"),
        ("climate.sandbox_thermostat", "off", None, OPEN_CLOSE, "Turn on at", "Turn off at"),
        ("media_player.sandbox_speaker", "off", None, OFF_ONLY, None, "Turn off at"),
        ("vacuum.sandbox_vacuum", "docked", None, START_DOCK, "Start at", "Return to dock at"),
        ("lawn_mower.sandbox_mower", "docked", None, START_DOCK, "Start at", "Return to dock at"),
        ("cover.sandbox_blind", "closed", None, OPEN_CLOSE, "Open at", "Close at"),
        ("cover.sandbox_gate", "closed", "gate", OFF_ONLY, None, "Close at"),
        ("lock.sandbox_lock", "locked", None, OFF_ONLY, None, "Lock at"),
        ("valve.sandbox_valve", "closed", None, OPEN_CLOSE, "Open at", "Close at"),
        ("valve.sandbox_gas", "closed", "gas", OFF_ONLY, None, "Close at"),
    ],
)
async def test_each_domain_profile_gets_exactly_its_controls_with_its_own_words(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    entity_id: str,
    state: str,
    device_class: str | None,
    controls: frozenset[str],
    on_name: str | None,
    off_name: str,
) -> None:
    object_id = entity_id.partition(".")[2]
    name = object_id.replace("_", " ").capitalize()
    device_id = add_device(
        hass, home.source, object_id, name, entity_id, state, device_class=device_class
    )

    await manager.async_opt_in(device_id)
    await hass.async_block_till_done()

    entries = page(hass, device_id)
    assert set(entries) == controls
    assert manager.page_keys(device_id) == controls
    off = shown(hass, entries["off_time"].entity_id)
    assert off.attributes["friendly_name"] == f"{name} {off_name}"
    if on_name is not None:
        on = shown(hass, entries["on_time"].entity_id)
        assert on.attributes["friendly_name"] == f"{name} {on_name}"


@pytest.mark.parametrize(
    ("entity_id", "state", "device_class", "duration_name"),
    [
        ("switch.sandbox_heater", "off", None, "Turn off after"),
        ("climate.sandbox_thermostat", "off", None, "Turn off after"),
        ("media_player.sandbox_speaker", "off", None, "Turn off after"),
        ("cover.sandbox_blind", "closed", None, "Close after"),
        ("cover.sandbox_gate", "closed", "gate", "Close after"),
        ("lock.sandbox_lock", "locked", None, "Lock after"),
        ("valve.sandbox_valve", "closed", None, "Close after"),
        ("valve.sandbox_gas", "closed", "gas", "Close after"),
    ],
)
async def test_turn_off_after_takes_the_words_of_the_domain(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    entity_id: str,
    state: str,
    device_class: str | None,
    duration_name: str,
) -> None:
    """Plan A4.0 item 10 (PRD 5.3, L52): Close after and Lock after, as the times do."""
    object_id = entity_id.partition(".")[2]
    name = object_id.replace("_", " ").capitalize()
    device_id = add_device(
        hass, home.source, object_id, name, entity_id, state, device_class=device_class
    )

    await manager.async_opt_in(device_id)
    await hass.async_block_till_done()

    entry = page(hass, device_id)["turn_off_after"]
    assert entry.unique_id == f"{DOMAIN}_{device_id}_turn_off_after"
    label = duration_name.lower().replace(" ", "_")
    assert entry.translation_key == label
    assert shown(hass, entry.entity_id).attributes["friendly_name"] == f"{name} {duration_name}"
    profile = manager.profile(device_id)
    assert profile is not None
    assert profile.off_after_label_key == label


async def test_categories_and_enabled_defaults_follow_the_table(
    hass: HomeAssistant, home: Home, manager: RoutineManager, routines: MockConfigEntry
) -> None:
    add_entity(hass, home, home.lamp, "switch.desk_lamp_plug")

    await manager.async_opt_in(home.lamp)
    await hass.async_block_till_done()

    entries = page(hass, home.lamp)
    assert set(entries) == set(TABLE)
    for key, (platform, category, enabled) in TABLE.items():
        entry = entries[key]
        assert entry.domain == platform, key
        assert entry.entity_category == category, key
        assert (entry.disabled_by is None) is enabled, key
        assert (hass.states.get(entry.entity_id) is not None) is enabled, key
        assert entry.has_entity_name, key
        assert entry.unique_id == f"{DOMAIN}_{home.lamp}_{key}"
        labels = {"on_time": "turn_on_at", "off_time": "turn_off_at"}
        assert entry.translation_key == labels.get(key, key)
        assert manager.entity_id_for(home.lamp, key) == entry.entity_id
    # Every control sits on the linked record of the user's device (L25).
    devices = dr.async_get(hass)
    user = devices.async_get(home.lamp)
    assert user is not None
    linked = {entry.device_id for entry in entries.values()}
    assert len(linked) == 1
    record = devices.async_get(linked.pop() or "")
    assert record is not None
    assert (record.identifiers, record.name) == (user.identifiers, user.name)
    assert record.config_entry_id == routines.entry_id
    assert manager.entity_id_for(home.lamp, "no_such_control") is None


async def test_routine_controls_appear_only_with_several_candidates_and_pick_the_target(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(7))
    assert "target" not in page(hass, home.fan)
    corner = add_device(hass, home.source, "corner", "Media corner", "switch.media_corner_power")
    add_entity(hass, home, corner, "media_player.media_corner_speaker")
    await manager.async_opt_in(corner)
    await hass.async_block_till_done()

    target = entity_of(hass, corner, "target")
    state = shown(hass, target)
    assert state.state == "switch.media_corner_power"
    assert state.attributes["options"] == [
        "switch.media_corner_power",
        "media_player.media_corner_speaker",
    ]
    assert set(page(hass, corner)) == TOGGLE | {"target"}

    # A media player cannot be turned on at a time: the manager refuses the switch while a
    # start time is set, and the control keeps its value.
    await manager.async_update(corner, {"on_time": time(7)})
    with pytest.raises(ServiceValidationError) as raised:
        await call(
            hass,
            "select",
            "select_option",
            entity_id=target,
            option="media_player.media_corner_speaker",
        )
    assert raised.value.translation_key == "on_time_not_supported"
    assert shown(hass, target).state == "switch.media_corner_power"

    # Without one, the target follows, and the controls follow the media player's profile.
    await manager.async_update(corner, {"on_time": None})
    await call(
        hass,
        "select",
        "select_option",
        entity_id=target,
        option="media_player.media_corner_speaker",
    )
    view = manager.get(corner)
    assert view is not None
    assert view.settings.target_entity == "media_player.media_corner_speaker"
    assert shown(hass, target).state == "media_player.media_corner_speaker"
    assert set(page(hass, corner)) == OFF_ONLY | {"target"}

    await call(
        hass, "select", "select_option", entity_id=target, option="switch.media_corner_power"
    )
    assert set(page(hass, corner)) == TOGGLE | {"target"}

    # A second drivable entity on the fan's device brings its select with the next change.
    add_entity(hass, home, home.fan, "light.living_room_fan_light")
    await manager.async_update(home.fan, {"on_time": time(8)})
    await hass.async_block_till_done()
    assert shown(hass, entity_of(hass, home.fan, "target")).state == FAN


async def test_turn_back_on_after_is_created_disabled_and_inert_until_a_value_is_set(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
    freezer: Any,
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    entry = page(hass, home.fan)["turn_back_on_after"]
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(entry.entity_id) is None
    inputs = inputs_of(hass, automation_id)
    assert (inputs["turn_back_on_after_min"], inputs["timer_entity"]) == (0, compiler.UNUSED_TIMER)
    assert state_of(hass, TIMER) is None

    # A person enables it from the device page; Home Assistant reloads the entry.
    er.async_get(hass).async_update_entity(entry.entity_id, disabled_by=None)
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert state_of(hass, entry.entity_id) == "0"
    assert state_of(hass, TIMER) is None
    await call(hass, "number", "set_value", entity_id=entry.entity_id, value=10)
    await flush(hass, freezer)

    inputs = inputs_of(hass, automation_id)
    assert (inputs["turn_back_on_after_min"], inputs["timer_entity"]) == (10, TIMER)
    assert state_of(hass, entry.entity_id) == "10"
    assert routines.runtime_data.manager is not manager


# --------------------------------------------------------------------------------------
# Every write goes through the manager (PRD P16)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "domain", "service", "data", "patch"),
    [
        ("on_time", "time", "set_value", {"time": "07:30:00"}, {"on_time": time(7, 30)}),
        ("off_time", "time", "set_value", {"time": "22:15:00"}, {"off_time": time(22, 15)}),
        ("days", "select", "select_option", {"option": "weekdays"}, {"days": "weekdays"}),
        (
            "days",
            "select",
            "select_option",
            {"option": "weekly_schedule"},
            {"days": "weekly_schedule"},
        ),
        ("turn_off_after", "number", "set_value", {"value": 30}, {"turn_off_after_min": 30}),
    ],
)
async def test_every_setting_goes_through_async_update_with_its_patch(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    domain: str,
    service: str,
    data: dict[str, Any],
    patch: dict[str, Any],
) -> None:
    await manager.async_opt_in(home.fan)
    await hass.async_block_till_done()
    update = AsyncMock(return_value=UpdateResult(None))
    monkeypatch.setattr(manager, "async_update", update)

    await call(hass, domain, service, entity_id=entity_of(hass, home.fan, key), **data)

    update.assert_awaited_once_with(home.fan, patch, source="entity")


@pytest.mark.parametrize(
    ("factory", "act", "patch"),
    [
        (
            TurnBackOnAfterNumber,
            lambda entity: entity.async_set_native_value(15.0),
            {"turn_back_on_after_min": 15.0},
        ),
        (CatchUpSwitch, lambda entity: entity.async_turn_off(), {"catch_up": False}),
        (CatchUpSwitch, lambda entity: entity.async_turn_on(), {"catch_up": True}),
        (RespectManualSwitch, lambda entity: entity.async_turn_off(), {"respect_manual": False}),
        (RespectManualSwitch, lambda entity: entity.async_turn_on(), {"respect_manual": True}),
        (
            TargetSelect,
            lambda entity: entity.async_select_option("switch.living_room_fan"),
            {"target_entity": "switch.living_room_fan"},
        ),
    ],
)
async def test_the_controls_created_disabled_write_through_async_update_too(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    monkeypatch: pytest.MonkeyPatch,
    factory: Callable[[RoutineManager, str], DeviceRoutinesDeviceEntity],
    act: Callable[[Any], Awaitable[None]],
    patch: dict[str, Any],
) -> None:
    await manager.async_opt_in(home.fan)
    update = AsyncMock(return_value=UpdateResult(None))
    monkeypatch.setattr(manager, "async_update", update)

    await act(factory(manager, home.fan))

    update.assert_awaited_once_with(home.fan, patch, source="entity")


async def test_a_refused_setting_raises_the_translated_problem_and_the_control_keeps_its_value(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    off = entity_of(hass, home.fan, "off_time")

    with pytest.raises(ServiceValidationError) as raised:
        await call(hass, "time", "set_value", entity_id=off, time="17:00:00")

    assert (raised.value.translation_domain, raised.value.translation_key) == (
        DOMAIN,
        "same_on_and_off_time",
    )
    assert shown(hass, off).state == "unknown"
    assert shown(hass, entity_of(hass, home.fan, "on_time")).state == "17:00:00"

    # The placeholders travel with the key.
    placeholders = {"setting": "turn_off_after_min", "min": "0", "max": "1440"}
    problem = Problem("turn_off_after_min", "out_of_range", placeholders)
    monkeypatch.setattr(
        manager, "async_update", AsyncMock(return_value=UpdateResult(None, problem))
    )
    with pytest.raises(ServiceValidationError) as raised:
        await call(
            hass,
            "number",
            "set_value",
            entity_id=entity_of(hass, home.fan, "turn_off_after"),
            value=5,
        )
    assert raised.value.translation_key == "out_of_range"
    assert raised.value.translation_placeholders == placeholders


async def test_the_controls_show_the_routine_settings(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(
        hass,
        manager,
        home.fan,
        freezer,
        on_time=time(17),
        off_time=time(23, 30),
        turn_off_after_min=45,
    )

    # The three advanced controls are created disabled, so they have no state to read.
    enabled = TOGGLE - {"turn_back_on_after", "catch_up", "respect_manual"}
    values = {key: shown(hass, entity_of(hass, home.fan, key)).state for key in enabled}
    assert values == {
        "routine": "on",
        "on_time": "17:00:00",
        "off_time": "23:30:00",
        "days": "every_day",
        "turn_off_after": "45",
        "skip_next": "unknown",
        "resume": "unavailable",
        "paused_until": "unknown",
        "manual_override": "off",
    }
    assert CatchUpSwitch(manager, home.fan).is_on is True
    assert RespectManualSwitch(manager, home.fan).is_on is True
    assert TurnBackOnAfterNumber(manager, home.fan).native_value == 0


# --------------------------------------------------------------------------------------
# Days, the routine switch, skip, pause, resume and the override (PRD 4.2, 5.5)
# --------------------------------------------------------------------------------------


async def test_the_days_select_offers_every_choice_and_some_days_keeps_the_day_set(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    days = entity_of(hass, home.fan, "days")
    state = shown(hass, days)
    assert state.state == "every_day"
    assert state.attributes["options"] == [
        "every_day",
        "weekdays",
        "weekends",
        "some_days",
        "weekly_schedule",
    ]

    # The day set itself is chosen in the routine form or the console (D34).
    await manager.async_update(home.fan, {"day_set": ["mon", "wed", "fri"]})
    await call(hass, "select", "select_option", entity_id=days, option="some_days")
    await flush(hass, freezer)

    assert shown(hass, days).state == "some_days"
    view = manager.get(home.fan)
    assert view is not None
    assert view.settings.effective_days == {Weekday.MON, Weekday.WED, Weekday.FRI}
    assert inputs_of(hass, automation_id)["days_start"] == ["mon", "wed", "fri"]
    await call(hass, "select", "select_option", entity_id=days, option="weekends")
    assert shown(hass, days).state == "weekends"


async def test_the_routine_switch_mirrors_the_automation_both_ways(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await manager.async_opt_in(home.fan)
    await hass.async_block_till_done()
    routine = entity_of(hass, home.fan, "routine")
    assert shown(hass, routine).state == "off"
    with pytest.raises(ServiceValidationError) as raised:
        await call(hass, "switch", "turn_on", entity_id=routine)
    assert raised.value.translation_key == "no_routine"

    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    assert shown(hass, routine).state == "on"

    await call(hass, "switch", "turn_off", entity_id=routine)
    assert (state_of(hass, AUTOMATION), shown(hass, routine).state) == ("off", "off")
    await call(hass, "automation", "turn_on", entity_id=AUTOMATION)
    assert shown(hass, routine).state == "on"
    await call(hass, "automation", "turn_off", entity_id=AUTOMATION)
    assert shown(hass, routine).state == "off"
    await call(hass, "switch", "turn_on", entity_id=routine)
    assert (state_of(hass, AUTOMATION), shown(hass, routine).state) == ("on", "on")


async def test_skip_next_is_unavailable_when_nothing_is_scheduled(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock.set(clock.at(0, "15:00"))
    await manager.async_opt_in(home.fan)
    await hass.async_block_till_done()
    skip = entity_of(hass, home.fan, "skip_next")
    assert shown(hass, skip).state == "unavailable"

    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    assert shown(hass, skip).state == "unknown"
    pressed = AsyncMock(wraps=manager.async_skip_next)
    monkeypatch.setattr(manager, "async_skip_next", pressed)
    await call(hass, "button", "press", entity_id=skip)

    pressed.assert_awaited_once_with(home.fan)
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.SKIPPING
    # Pressing again extends the skip, so the button stays.
    assert shown(hass, skip).state != "unavailable"

    await call(hass, "switch", "turn_off", entity_id=entity_of(hass, home.fan, "routine"))
    assert shown(hass, skip).state == "unavailable"


async def test_skip_next_follows_the_countdown_of_a_routine_without_times(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    """Plan A4.0 item 1 (L52): the timer's start and end reach the device page at once.

    A routine with only Turn off after has nothing scheduled until a countdown runs, so
    Skip next must become available when the timer starts and go when it ends; pressing
    it is "keep it on this time" (D19), from the device page.
    """
    clock.set(clock.at(0, "15:00"))
    await give_routine(hass, manager, home.fan, freezer, turn_off_after_min=30)
    skip = entity_of(hass, home.fan, "skip_next")
    assert shown(hass, skip).state == "unavailable"
    # A first change at the wall names the device as the source of the last change, so
    # the changes below move nothing but the timer.
    home.switch.device_change(True)
    await hass.async_block_till_done()
    heard: list[ManagerEvent] = []
    manager.async_add_listener(heard.append)

    home.switch.device_change(False)  # turned off at the wall: the countdown ends
    await hass.async_block_till_done()

    assert state_of(hass, TIMER) == "idle"
    assert heard == [ManagerEvent("routine_changed", home.fan)]
    assert shown(hass, skip).state == "unavailable"

    home.switch.device_change(True)  # on again: a new countdown starts
    await hass.async_block_till_done()

    assert state_of(hass, TIMER) == "active"
    assert heard[1:] == [ManagerEvent("routine_changed", home.fan)]
    assert shown(hass, skip).state == "unknown"

    await call(hass, "button", "press", entity_id=skip)

    assert state_of(hass, TIMER) == "idle"
    assert shown(hass, skip).state == "unavailable"
    await clock.to(clock.at(0, "15:35"))
    assert home.switch.state_now == "on"  # kept on this time


async def test_resume_is_unavailable_unless_paused_or_skipping(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock.set(clock.at(0, "16:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    resume = entity_of(hass, home.fan, "resume")
    assert shown(hass, resume).state == "unavailable"

    await call(hass, "datetime", "set_value", entity_id=PAUSED, datetime=clock.at(0, "18:30"))
    assert shown(hass, resume).state == "unknown"
    pressed = AsyncMock(wraps=manager.async_resume)
    monkeypatch.setattr(manager, "async_resume", pressed)
    await call(hass, "button", "press", entity_id=resume)

    pressed.assert_awaited_once_with(home.fan)
    assert shown(hass, resume).state == "unavailable"
    assert shown(hass, PAUSED).state == "unknown"

    await call(hass, "button", "press", entity_id=entity_of(hass, home.fan, "skip_next"))
    assert shown(hass, resume).state != "unavailable"


async def test_paused_until_pauses_and_rejects_a_past_value_with_a_translated_error(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock.set(clock.at(0, "16:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))

    with pytest.raises(ServiceValidationError) as raised:
        await call(hass, "datetime", "set_value", entity_id=PAUSED, datetime=clock.at(0, "15:00"))

    assert (raised.value.translation_domain, raised.value.translation_key) == (
        DOMAIN,
        "paused_until_in_past",
    )
    assert shown(hass, PAUSED).state == "unknown"

    paused = AsyncMock(wraps=manager.async_pause)
    monkeypatch.setattr(manager, "async_pause", paused)
    await call(hass, "datetime", "set_value", entity_id=PAUSED, datetime=clock.at(1, "08:00"))
    paused.assert_awaited_once_with(home.fan, until=clock.at(1, "08:00"))
    assert shown(hass, PAUSED).state == dt_util.as_utc(clock.at(1, "08:00")).isoformat()
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.PAUSED


async def test_the_manual_override_names_the_source_and_turning_it_off_catches_up(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock.set(clock.at(0, "12:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    assert shown(hass, OVERRIDE).attributes["last_change_source"] is None

    home.switch.device_change(on=True)
    await hass.async_block_till_done()

    state = shown(hass, OVERRIDE)
    assert (state.state, state.attributes["last_change_source"]) == ("on", "device")
    turned = AsyncMock(wraps=manager.async_set_manual_override)
    monkeypatch.setattr(manager, "async_set_manual_override", turned)

    # A person turns the override off: the schedule takes over again at once.
    await call(hass, "switch", "turn_off", entity_id=OVERRIDE)

    turned.assert_awaited_once_with(home.fan, on=False)
    assert shown(hass, OVERRIDE).state == "off"
    assert home.switch.state_now == "off"

    await call(hass, "switch", "turn_on", entity_id=OVERRIDE)
    turned.assert_awaited_with(home.fan, on=True)
    assert shown(hass, OVERRIDE).state == "on"


# --------------------------------------------------------------------------------------
# Availability (TECH_SPEC 4.2 and 4.5)
# --------------------------------------------------------------------------------------


async def test_the_config_controls_are_unavailable_while_the_adapter_cannot_write(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    working = ha_adapter.check
    monkeypatch.setattr(
        ha_adapter,
        "check",
        lambda _hass: ha_adapter.AdapterReport(failed=(ha_adapter.CAPABILITY_WRITE,)),
    )

    await manager.async_reconcile()
    await hass.async_block_till_done()

    for key, entry in page(hass, home.fan).items():
        if entry.disabled_by is not None:
            continue
        state = shown(hass, entry.entity_id)
        if key in CONFIG_KEYS:
            assert (state.state, state.attributes["reason"]) == (
                "unavailable",
                "adapter_incompatible",
            )
        else:
            assert "reason" not in state.attributes, key
    # Paused until and the override stay readable: the blueprint keeps reading them, and
    # skipping still works.
    for key in ("paused_until", "manual_override", "skip_next"):
        assert shown(hass, entity_of(hass, home.fan, key)).state != "unavailable", key
    assert manager.unavailable_reason(home.fan) == "adapter_incompatible"
    assert manager.unavailable_reason(home.fan, "paused_until") is None

    monkeypatch.setattr(ha_adapter, "check", working)
    await manager.async_reconcile()
    await hass.async_block_till_done()
    days = shown(hass, entity_of(hass, home.fan, "days"))
    assert days.state == "every_day"
    assert "reason" not in days.attributes
    assert days.attributes["options"][0] == "every_day"


async def test_a_detached_routine_makes_every_control_unavailable_with_reason_detached(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))

    await save_entry(
        hass,
        {
            "id": automation_id,
            "alias": ALIAS,
            "triggers": [{"trigger": "time", "at": "17:00:00"}],
            "actions": [{"action": "switch.turn_on", "target": {"entity_id": FAN}}],
        },
    )

    enabled = [entry for entry in page(hass, home.fan).values() if entry.disabled_by is None]
    assert enabled
    for entry in enabled:
        state = shown(hass, entry.entity_id)
        assert (state.state, state.attributes["reason"]) == ("unavailable", "detached")


async def test_a_missing_target_makes_every_control_unavailable_with_reason_missing_target(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await manager.async_opt_in(home.lamp)
    await manager.async_update(home.lamp, {"on_time": time(17)})
    await flush(hass, freezer)

    hass.states.async_remove(LAMP)
    er.async_get(hass).async_remove(LAMP)
    await hass.async_block_till_done()

    enabled = [entry for entry in page(hass, home.lamp).values() if entry.disabled_by is None]
    assert enabled
    for entry in enabled:
        state = shown(hass, entry.entity_id)
        assert (state.state, state.attributes["reason"]) == ("unavailable", "missing_target")


async def test_a_missing_target_leaves_the_target_select_to_pick_another(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    """Plan A4.0 item 9 (L52): Routine controls stays, and picking another target heals.

    The select stays even with one candidate left, since the routine's own target is
    not among the candidates any more.
    """
    add_entity(hass, home, home.lamp, "switch.desk_lamp_plug")
    await give_routine(hass, manager, home.lamp, freezer, on_time=time(17))
    view = manager.get(home.lamp)
    assert view is not None
    automation = view.automation_entity_id
    assert automation is not None

    hass.states.async_remove(LAMP)
    er.async_get(hass).async_remove(LAMP)
    await hass.async_block_till_done()

    target = entity_of(hass, home.lamp, "target")
    assert shown(hass, target).state != "unavailable"
    assert shown(hass, target).attributes["options"] == ["switch.desk_lamp_plug"]
    assert manager.unavailable_reason(home.lamp, "target") is None
    assert manager.unavailable_reason(home.lamp, "days") == "missing_target"
    assert state_of(hass, automation) == "off"

    await call(hass, "select", "select_option", entity_id=target, option="switch.desk_lamp_plug")
    await flush(hass, freezer)

    view = manager.get(home.lamp)
    assert view is not None
    assert view.settings.target_entity == "switch.desk_lamp_plug"
    assert view.status is Status.ACTIVE
    assert state_of(hass, automation) == "on"
    assert manager.unavailable_reason(home.lamp, "days") is None
    assert "target" not in page(hass, home.lamp)  # one candidate again, and it is the target


async def test_turn_back_on_after_is_unavailable_while_the_schedule_says_off(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
    clock: Clock,
    freezer: Any,
) -> None:
    """Plan A4.0 item 9 (PRD 4.3, FR-R4): keep alive never fires while the schedule says off."""
    clock.set(clock.at(0, "15:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    keep_alive = page(hass, home.fan)["turn_back_on_after"].entity_id
    er.async_get(hass).async_update_entity(keep_alive, disabled_by=None)
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    manager = routines.runtime_data.manager

    state = shown(hass, keep_alive)
    assert (state.state, state.attributes["reason"]) == ("unavailable", "schedule_off")
    assert manager.unavailable_reason(home.fan, "turn_off_after") is None

    # The control follows the window by itself, at its start and at its end.
    await clock.to(clock.at(0, "17:00:05"))
    assert shown(hass, keep_alive).state == "0"
    assert manager.unavailable_reason(home.fan, "turn_back_on_after") is None
    await clock.to(clock.at(0, "23:00:05"))
    assert shown(hass, keep_alive).state == "unavailable"

    # Without a window there is no schedule to say off.
    await manager.async_update(home.fan, {"off_time": None})
    assert manager.unavailable_reason(home.fan, "turn_back_on_after") is None
    assert shown(hass, keep_alive).state == "0"


# --------------------------------------------------------------------------------------
# The registry: opt out, the manager's accessors, a device that is gone
# --------------------------------------------------------------------------------------


async def test_the_controls_leave_the_registry_on_opt_out_and_return_on_opt_in(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    before = {key: entry.entity_id for key, entry in page(hass, home.fan).items()}
    assert set(before) == TOGGLE

    await manager.async_opt_out(home.fan)
    await hass.async_block_till_done()

    assert page(hass, home.fan) == {}
    assert all(hass.states.get(entity_id) is None for entity_id in before.values())
    assert manager.page_keys(home.fan) == frozenset()

    await manager.async_opt_in(home.fan)
    await hass.async_block_till_done()

    after = {key: entry.entity_id for key, entry in page(hass, home.fan).items()}
    assert after == before
    assert shown(hass, before["routine"]).state == "on"


async def test_the_controls_of_a_removed_device_go_with_its_linked_record(
    hass: HomeAssistant, home: Home, manager: RoutineManager, routines: MockConfigEntry
) -> None:
    devices = dr.async_get(hass)
    plug = devices.async_get_or_create(
        config_entry_id=home.source.entry_id,
        identifiers={("sandbox", "plug"), ("sandbox", "plug_serial")},
        name="Garden plug",
    )
    add_entity(hass, home, plug.id, "switch.garden_plug")
    await manager.async_opt_in(plug.id)
    await hass.async_block_till_done()
    routine = entity_of(hass, plug.id, "routine")
    linked = devices.async_get_device_by_identifier(("sandbox", "plug"), routines.entry_id)
    assert linked is not None
    assert linked.identifiers == plug.identifiers

    devices.async_remove_device(plug.id)
    await hass.async_block_till_done()

    assert page(hass, plug.id) == {}
    assert hass.states.get(routine) is None
    assert devices.async_get(linked.id) is None
    assert manager.page_keys(plug.id) == frozenset()
    assert plug.id in manager.opted_in_devices()


async def test_a_control_for_a_device_that_is_gone_attaches_nowhere_and_reads_empty(
    hass: HomeAssistant, manager: RoutineManager
) -> None:
    switch = RoutineSwitch(manager, "no-such-device")

    assert switch.device_info is None
    assert switch.is_on is False
    assert CatchUpSwitch(manager, "no-such-device").is_on is False
    assert TurnBackOnAfterNumber(manager, "no-such-device").native_value is None
    assert TargetSelect(manager, "no-such-device").current_option is None


# --------------------------------------------------------------------------------------
# Restore (decision L44)
# --------------------------------------------------------------------------------------


async def test_restored_runtime_is_handed_to_the_manager_when_the_controls_are_added(
    hass: HomeAssistant, home: Home, manager: RoutineManager
) -> None:
    later = dt_util.utcnow().replace(microsecond=0) + timedelta(hours=2)
    runtime = RestoredRuntime(paused_until=later, override=True, last_change_source=Source.USER)
    stored = restore_state.async_get(hass)
    now = dt_util.utcnow()
    stored.last_states[PAUSED] = StoredState(
        State(PAUSED, later.isoformat()), RuntimeExtraData(runtime), now
    )
    # Unreadable data restores nothing rather than clearing what the other control holds.
    stored.last_states[OVERRIDE] = StoredState(
        State(OVERRIDE, "on"), RestoredExtraData({"last_change_source": "ghost"}), now
    )

    await manager.async_opt_in(home.fan)
    await hass.async_block_till_done()

    assert manager.restore_data(home.fan) == runtime
    assert shown(hass, PAUSED).state == later.isoformat()
    assert shown(hass, OVERRIDE).state == "on"


async def test_the_runtime_comes_back_after_a_reload(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
    clock: Clock,
    freezer: Any,
) -> None:
    clock.set(clock.at(0, "16:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    await clock.to(clock.at(0, "20:00"))
    await manager.async_skip_next(home.fan)
    await hass.async_block_till_done()
    before = manager.restore_data(home.fan)
    assert before is not None
    assert before.override
    assert before.paused_until is not None
    await manager.store.async_save()

    assert await hass.config_entries.async_reload(routines.entry_id)
    await hass.async_block_till_done()

    reloaded: RoutineManager = routines.runtime_data.manager
    assert reloaded is not manager
    assert reloaded.restore_data(home.fan) == before
    view = reloaded.get(home.fan)
    assert view is not None
    assert view.status is Status.SKIPPING
    assert shown(hass, OVERRIDE).state == "on"


def test_the_runtime_codec_round_trips_and_refuses_what_it_cannot_read() -> None:
    moment = datetime(2026, 10, 21, 9, 1, tzinfo=UTC)
    runtime = RestoredRuntime(
        moment,
        Occurrence(moment - timedelta(minutes=1), Verb.OFF),
        override=True,
        override_by_skip=True,
        last_change_source=Source.USER,
    )

    stored = RuntimeExtraData(runtime).as_dict()

    assert json.loads(json.dumps(stored)) == stored
    assert runtime_from_dict(stored) == runtime
    assert runtime_from_dict(RuntimeExtraData(RestoredRuntime()).as_dict()) == RestoredRuntime()
    assert runtime_from_dict(
        {"skipped_action": {"at": moment.isoformat(), "verb": None}}
    ) == RestoredRuntime(skipped_action=Occurrence(moment, None))
    for garbage in (
        {"paused_until": "soon"},
        {"paused_until": 5},
        {"skipped_action": {"verb": "off"}},
        {"skipped_action": "yesterday"},
        {"last_change_source": "ghost"},
    ):
        assert runtime_from_dict(garbage) is None, garbage


# --------------------------------------------------------------------------------------
# The hub and the platform modules
# --------------------------------------------------------------------------------------


async def test_the_hub_clean_up_now_button_runs_the_maintenance_action(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    await manager.async_opt_out(home.fan)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    button = registry.async_get_entity_id("button", DOMAIN, f"{DOMAIN}_hub_hub_cleanup_now")
    assert button is not None
    entry = registry.async_get(button)
    assert entry is not None
    assert (entry.entity_category, entry.translation_key) == (
        EntityCategory.CONFIG,
        "hub_cleanup_now",
    )
    assert shown(hass, button).attributes["friendly_name"] == "Device Routines Clean up now"
    run = AsyncMock(wraps=maintenance.async_run)
    monkeypatch.setattr(maintenance, "async_run", run)

    await call(hass, "button", "press", entity_id=button)

    run.assert_awaited_once_with(hass, manager, MaintenanceAction.CLEAN_UP_NOW, dry_run=False)
    assert file_entry(hass, automation_id) is None
    assert home.fan not in manager.store.data.opted_out_at


def test_every_reason_a_control_can_show_is_translated() -> None:
    """Each control's `reason` names a translated state, under every key it can take.

    Config controls lose editing on an incompatible adapter; every control but Routine
    controls reads a missing target (L52); the times read `weekly_schedule` and Turn back
    on after `schedule_off` (PRD 4.2 and 4.3, plan A4.0 item 9).
    """
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))["entity"]
    words: dict[str, set[str]] = {
        "on_time": {"on_time"} | {p.on_label_key for p in PROFILES.values() if p.on_label_key},
        "off_time": {"off_time"} | {p.off_label_key for p in PROFILES.values()},
        "turn_off_after": {p.off_after_label_key for p in PROFILES.values()},
    }
    for key, (platform, category, _enabled) in TABLE.items():
        reasons = {"detached"}
        if category is EntityCategory.CONFIG:
            reasons.add("adapter_incompatible")
        if key != "target":
            reasons.add("missing_target")
        if key in {"on_time", "off_time"}:
            reasons.add("weekly_schedule")
        if key == "turn_back_on_after":
            reasons.add("schedule_off")
        for name in words.get(key, {key}):
            states = strings[platform][name]["state_attributes"]["reason"]["state"]
            assert reasons <= set(states), (platform, name, reasons - set(states))


def test_the_platforms_are_the_platform_modules() -> None:
    """Every forwarded platform has a module, and every platform module is forwarded."""
    modules = {
        path.stem
        for path in COMPONENT.glob("*.py")
        if path.stem in {platform.value for platform in Platform}
        and any(
            isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry"
            for node in ast.parse(path.read_text(encoding="utf-8")).body
        )
    }

    assert {platform.value for platform in PLATFORMS} == modules


@pytest.mark.parametrize("platform", sorted(platform.value for platform in PLATFORMS))
def test_every_platform_module_sets_parallel_updates_to_zero(platform: str) -> None:
    tree = ast.parse((COMPONENT / f"{platform}.py").read_text(encoding="utf-8"))

    values = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "PARALLEL_UPDATES"
            for target in node.targets
        )
    ]

    assert len(values) == 1
    assert isinstance(values[0], ast.Constant)
    assert values[0].value == 0
