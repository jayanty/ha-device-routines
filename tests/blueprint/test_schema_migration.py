"""Behavior matrix: a routine through the upgrades of the blueprint input schema (B50, B51).

TECH_SPEC 4.11 and 5.6: the integration replaces the installed blueprint file, the
automations built on it re read it, and the migration then rewrites every owned routine
with the inputs of the new schema. Between the two steps a routine runs schema 1 inputs
on the schema 2 file, which is why every new input defaults to schema 1 behavior (plan
Section 6.2.1, decision L60). The schema 2 inputs here are hand written through the
mirror, as `compile` writes them for the same settings; the compiler's side is lane 16's.

B50 runs a schema 1 routine on the current file. B51 runs a schema 2 routine with a
countdown on the schema 3 file: `timer_enabled` (decision L83) defaults to on, so every
step that names the timer runs until the migration writes the flag.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta
import hashlib
from pathlib import Path
from typing import Any

from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.automation.helpers import async_get_blueprints
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.core import Event, HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import parse_yaml
import pytest

from custom_components.device_routines import markers
from tests.blueprint.conftest import (
    AUTOMATION,
    BLUEPRINT_SOURCE,
    INPUT_KEYS,
    OVERRIDE,
    PAUSED,
    SCHEMA_1_BLUEPRINT,
    SCHEMA_1_INPUT_KEYS,
    SCHEMA_2_BLUEPRINT,
    SCHEMA_2_INPUT_KEYS,
    SCHEMA_2_NEW_KEYS,
    SWITCH,
    TIMER,
    Clock,
    SandboxDateTime,
    SandboxSwitch,
    async_install_blueprint,
    automation_entries,
    inputs,
    schema_1_inputs,
    schema_2_inputs,
    sun_offset,
)

Routine = Callable[[Mapping[str, Any]], Awaitable[str]]
# The sha256 of the schema 1 file v0.3.0-beta.1 ships; the fixture is that file unchanged.
SCHEMA_1_SHA256 = "2e286fdf5a877635340cef02adae5a81f8424361522c869e9a77daae38a3cb58"
# The sha256 of the schema 2 file v1.0.0 ships; the fixture is that file unchanged.
SCHEMA_2_SHA256 = "ed51f2c55ce72ab2367404261ca8b94f2c12fc447ee95f901f19629a7cfb6093"

# Settings a schema 1 compiler could write, as the mirror's primary inputs: a window
# crossing midnight on weekdays with a countdown for manual changes, and a window the same
# day with a pulse inside it. Both start at 17:00.
SETTINGS: Mapping[str, Mapping[str, Any]] = {
    "weekday_night_window": {
        "on_time": "17:00:00",
        "off_time": "09:00:00",
        "days_start": ["mon", "tue", "wed", "thu", "fri"],
        "timer_entity": TIMER,
        "turn_off_after_min": 30,
        "override_entity": OVERRIDE,
        "paused_until_entity": PAUSED,
    },
    "same_day_window_with_a_pulse": {
        "on_time": "17:00:00",
        "off_time": "23:00:00",
        "late_start_window_min": 20,
        "pulse_at": "20:00:00",
        "pulse_minutes": 1,
        "pulse_min_steady_min": 0,
        "override_entity": OVERRIDE,
        "paused_until_entity": PAUSED,
    },
}


def switch_changes(hass: HomeAssistant) -> list[str]:
    """Record every state the sandbox switch takes from now on."""
    changes: list[str] = []

    def remember(event: Event) -> None:
        if event.data["entity_id"] == SWITCH and event.data["new_state"] is not None:
            old = event.data["old_state"]
            if old is None or old.state != event.data["new_state"].state:
                changes.append(event.data["new_state"].state)

    hass.bus.async_listen("state_changed", remember)
    return changes


def written_inputs(hass: HomeAssistant) -> dict[str, Any]:
    """Return the inputs of the routine's entry in `automations.yaml`."""
    (entry,) = automation_entries(Path(hass.config.config_dir))
    result: dict[str, Any] = entry["use_blueprint"]["input"]
    return result


async def installed_inputs(hass: HomeAssistant) -> tuple[str, ...]:
    """Return the inputs of the blueprint file the automations run, read from disk."""
    blueprints = async_get_blueprints(hass)
    await blueprints.async_reset_cache()
    blueprint = await blueprints.async_get_blueprint(markers.BLUEPRINT_PATH)
    return tuple(blueprint.inputs)


async def reload_automations(hass: HomeAssistant) -> None:
    """Reload every automation, as the integration does after a blueprint upgrade."""
    await hass.services.async_call("automation", "reload", blocking=True)
    await hass.async_block_till_done()
    state = hass.states.get(AUTOMATION)
    assert state is not None
    assert state.state == "on", state


async def run_the_rest_of_the_window(
    hass: HomeAssistant, clock: Clock, switch: SandboxSwitch, settings: str, day: int
) -> list[str]:
    """From inside the window started at 17:00 on `day`, run every action up to its end.

    Returns the states the actions set, in order.
    """
    seen: list[str] = []
    if settings == "weekday_night_window":
        await clock.to(clock.at(day + 1, "08:59:59"))
        assert switch.state_now == "on"
        await clock.to(clock.at(day + 1, "09:00:01"))
    else:
        # The pulse waits in a delay, so the clock only yields until it has restored.
        await clock.to(clock.at(day, "20:00:01"), settle="yield")
        seen.append(str(switch.state_now))
        await clock.to(clock.at(day, "20:01:02"), settle="yield")
        await hass.async_block_till_done()
        seen.append(str(switch.state_now))
        await clock.to(clock.at(day, "23:00:01"))
    seen.append(str(switch.state_now))
    return seen


def test_the_schema_1_fixture_is_the_shipped_schema_1_file() -> None:
    raw = SCHEMA_1_BLUEPRINT.read_bytes()
    data = parse_yaml(raw.decode("utf-8"))
    assert isinstance(data, dict)
    loaded = Blueprint(data, expected_domain="automation", schema=AUTOMATION_BLUEPRINT_SCHEMA)

    assert hashlib.sha256(raw).hexdigest() == SCHEMA_1_SHA256
    assert raw.decode("utf-8").splitlines()[0] == "# Device Routines blueprint, schema 1."
    assert tuple(loaded.inputs) == SCHEMA_1_INPUT_KEYS
    assert raw != BLUEPRINT_SOURCE.read_bytes()


def test_the_schema_2_fixture_is_the_shipped_schema_2_file() -> None:
    raw = SCHEMA_2_BLUEPRINT.read_bytes()
    data = parse_yaml(raw.decode("utf-8"))
    assert isinstance(data, dict)
    loaded = Blueprint(data, expected_domain="automation", schema=AUTOMATION_BLUEPRINT_SCHEMA)

    assert hashlib.sha256(raw).hexdigest() == SCHEMA_2_SHA256
    assert raw.decode("utf-8").splitlines()[0] == "# Device Routines blueprint, schema 2."
    assert tuple(loaded.inputs) == SCHEMA_2_INPUT_KEYS
    assert raw != BLUEPRINT_SOURCE.read_bytes()


@pytest.mark.parametrize("settings", list(SETTINGS))
def test_schema_1_and_2_inputs_of_the_same_settings_differ_by_the_new_defaults(
    settings: str,
) -> None:
    old = schema_1_inputs(**SETTINGS[settings])
    new = inputs(**SETTINGS[settings])
    late = SETTINGS[settings].get("late_start_window_min", 15)

    # A time bound routine on schema 2: time kinds, no offset, no sun flag, and the late
    # sun offset derived from an offset of 0 (the blueprint default covers the usual 15).
    assert {key: new[key] for key in SCHEMA_1_INPUT_KEYS} == old
    assert {key: new[key] for key in SCHEMA_2_NEW_KEYS} == {
        **{key: inputs()[key] for key in SCHEMA_2_NEW_KEYS},
        "late_sun_offset": sun_offset(late),
    }


@pytest.mark.parametrize("settings", list(SETTINGS))
async def test_b50_schema_1_routine_keeps_running_on_schema_2(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    routine_timer: str,
    settings: str,
) -> None:
    given = SETTINGS[settings]
    after_the_window = ["off", "on", "off"] if settings != "weekday_night_window" else ["off"]

    # A routine on the schema 1 file with schema 1 inputs, as v0.3.0-beta.1 runs it. (A
    # file installed over another reloads the automations, so the component comes first.)
    clock.set(clock.at(0, "16:00"))  # Monday
    assert await async_setup_component(hass, "automation", {})
    await async_install_blueprint(hass, SCHEMA_1_BLUEPRINT)
    await routine_automation(schema_1_inputs(**given))
    assert await installed_inputs(hass) == SCHEMA_1_INPUT_KEYS
    assert tuple(written_inputs(hass)) == SCHEMA_1_INPUT_KEYS
    await clock.to(clock.at(0, "17:00:01"))
    assert sandbox_switch.state_now == "on"
    changes = switch_changes(hass)

    # The schema 2 file is installed over it and the automations reload: nothing changes,
    # and the next scheduled actions run on the schema 2 file with the schema 1 inputs.
    await clock.to(clock.at(0, "18:00"))
    await async_install_blueprint(hass, BLUEPRINT_SOURCE)
    await reload_automations(hass)
    assert await installed_inputs(hass) == INPUT_KEYS
    assert tuple(written_inputs(hass)) == SCHEMA_1_INPUT_KEYS
    assert changes == []
    assert sandbox_switch.state_now == "on"
    assert await run_the_rest_of_the_window(hass, clock, sandbox_switch, settings, 0) == (
        after_the_window
    )
    assert changes == after_the_window

    # The migration rewrites the entry with the schema 2 inputs of the same settings and
    # reloads it: nothing changes again, and the routine keeps its schedule.
    await clock.to(clock.at(1, "12:00"))
    changes.clear()
    await routine_automation(inputs(**given))
    assert list(written_inputs(hass)) == list(inputs())
    assert changes == []
    await clock.to(clock.at(1, "16:59:59"))
    assert changes == []
    await clock.to(clock.at(1, "17:00:01"))
    assert sandbox_switch.state_now == "on"
    assert await run_the_rest_of_the_window(hass, clock, sandbox_switch, settings, 1) == (
        after_the_window
    )
    assert changes == ["on", *after_the_window]


async def test_b51_schema_2_countdown_keeps_running_on_schema_3(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    routine_timer: str,
) -> None:
    given = {"timer_entity": TIMER, "turn_off_after_min": 30}

    async def a_manual_on_turns_off_after_30_minutes(day: int, at: str) -> None:
        await clock.to(clock.at(day, at))
        sandbox_switch.device_change(on=True)
        await hass.async_block_till_done()
        timer = hass.states.get(TIMER)
        assert timer is not None
        assert timer.state == "active"
        await clock.to(clock.at(day, at) + timedelta(minutes=29, seconds=58))
        assert sandbox_switch.state_now == "on"
        await clock.to(clock.at(day, at) + timedelta(minutes=30, seconds=1))
        assert sandbox_switch.state_now == "off"

    # A routine on the schema 2 file with schema 2 inputs, as v1.0.0 runs it.
    clock.set(clock.at(0, "09:00"))
    assert await async_setup_component(hass, "automation", {})
    await async_install_blueprint(hass, SCHEMA_2_BLUEPRINT)
    await routine_automation(schema_2_inputs(**given))
    assert await installed_inputs(hass) == SCHEMA_2_INPUT_KEYS
    await a_manual_on_turns_off_after_30_minutes(0, "10:00")

    # The schema 3 file is installed over it and the automations reload: the countdown
    # still runs with the schema 2 inputs, `timer_enabled` at its default.
    await async_install_blueprint(hass, BLUEPRINT_SOURCE)
    await reload_automations(hass)
    assert await installed_inputs(hass) == INPUT_KEYS
    assert tuple(written_inputs(hass)) == SCHEMA_2_INPUT_KEYS
    await a_manual_on_turns_off_after_30_minutes(0, "12:00")

    # The migration writes `timer_enabled` on for a routine with a timer: no change.
    await routine_automation(inputs(**given))
    assert written_inputs(hass)["timer_enabled"] is True
    await a_manual_on_turns_off_after_30_minutes(0, "14:00")
